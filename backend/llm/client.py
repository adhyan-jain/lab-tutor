"""LLM backend interface and the concrete implementations.

Callers depend on `LLMBackend`, never on a provider. Adding a backend
means adding a class here and one value to the config enum; no call site
changes.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from backend.config import Settings, get_settings
from backend.llm import telemetry
from backend.llm.context_cache import CacheRequest, ContextCacheManager

log = logging.getLogger(__name__)


def _strip_markdown_emphasis(text: str) -> str:
    """Pass text through directly to allow natural markdown formatting in frontend."""
    return text



#: Bounds how many LLM calls run at once across every backend instance
#: and every caller (chat, phrasing, qualitative note) -- see
#: `Settings.llm_max_concurrency`'s docstring for why. Lazily built (an
#: `asyncio.Semaphore` binds to whichever loop is running when it's
#: first used, so it must not be constructed at import time) and reset
#: alongside the backend cache so a settings reload -- or a test that
#: changes `LABTUTOR_LLM_MAX_CONCURRENCY` -- picks up the new limit.
_semaphore: asyncio.Semaphore | None = None
#: Separate, small pool for background work, so a summary job cannot take a
#: slot a live student is waiting for.
_bg_semaphore: asyncio.Semaphore | None = None
_background: ContextVar[bool] = ContextVar("_llm_background", default=False)

#: When set, every OpenAIBackend.complete() call in this asyncio task
#: streams tokens into this queue instead of waiting for the full reply.
#: The streaming endpoint sets it before spawning the worker task; the
#: worker inherits it via asyncio's copy-on-write context propagation.
#: Value is None (default) on every ordinary non-streaming request.
_stream_queue: ContextVar[asyncio.Queue | None] = ContextVar("_llm_stream_queue", default=None)


def _get_semaphore() -> asyncio.Semaphore:
    """The pool for the current task: background work has its own."""
    global _semaphore, _bg_semaphore
    if _background.get():
        if _bg_semaphore is None:
            _bg_semaphore = asyncio.Semaphore(get_settings().llm_background_concurrency)
        return _bg_semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _semaphore


def mark_background() -> None:
    """Call at the top of a background task: every model call it makes in
    this task context uses the background pool, never the live-student one."""
    _background.set(True)


class LLMUnavailable(RuntimeError):
    """No configured backend could serve the request.

    Callers must degrade gracefully -- every LLM use in this system is for
    *phrasing* something already decided, so an outage costs polish, never
    correctness. See README "Rollback plan".
    """


@asynccontextmanager
async def _slot() -> AsyncIterator[None]:
    """A concurrency slot, or `LLMUnavailable` if none frees up in time.

    Failing fast here sends the request to the extractive fallback instead
    of letting a burst queue for minutes behind a slow provider.
    """
    sem = _get_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=get_settings().llm_queue_timeout_seconds)
    except TimeoutError:
        raise LLMUnavailable("LLM concurrency queue timeout") from None
    try:
        yield
    finally:
        sem.release()


def _error_label(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    return f"{type(exc).__name__}:{code}" if code else type(exc).__name__


@dataclass(frozen=True)
class LLMReply:
    text: str
    backend: str
    model: str
    #: Wall-clock time for the completion call, populated by every
    #: backend. Token counts are populated where the backend's response
    #: reports them (Vertex does; others may not) -- None rather than an
    #: invented number when unavailable.
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMBackend(abc.ABC):
    name: str = "base"
    #: Only backends with native context caching accept `cache=` in complete().
    supports_context_cache: bool = False

    @abc.abstractmethod
    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        ...

    @abc.abstractmethod
    async def health(self) -> bool:
        ...


class HostedBackend(LLMBackend):
    """Any OpenAI-compatible `/chat/completions` endpoint."""

    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.llm_base_url.rstrip("/")
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout_seconds
        self._default_max_tokens = settings.llm_max_tokens
        self._temperature = settings.llm_temperature

    def _configured(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        if not self._configured():
            raise LLMUnavailable(
                "Hosted LLM backend is not configured (base URL, API key and "
                "model are all required)"
            )
        payload = {
            "model": self._model,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        started = time.monotonic()
        telemetry.record_call()
        telemetry.record_attempt()
        try:
            async with _slot():
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
                    resp.raise_for_status()
                    data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            telemetry.record_result(
                backend=self.name, model=self._model, ok=False,
                latency_ms=(time.monotonic() - started) * 1000, error=_error_label(exc),
            )
            raise LLMUnavailable(f"Hosted backend request failed: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"Unexpected hosted backend response shape: {exc}") from exc
        usage = data.get("usage") or {}
        return LLMReply(
            text=_strip_markdown_emphasis((text or "").strip()),
            backend=self.name,
            model=self._model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def health(self) -> bool:
        if not self._configured():
            return False
        try:
            async with httpx.AsyncClient(timeout=min(self._timeout, 10.0)) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return resp.status_code < 500
        except httpx.HTTPError:
            return False


class OllamaBackend(LLMBackend):
    """Local Ollama. Development and degraded-mode use only."""

    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self._timeout = settings.llm_timeout_seconds
        self._default_max_tokens = settings.llm_max_tokens
        self._think = settings.ollama_think
        self._temperature = settings.llm_temperature

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        payload = {
            "model": self._model,
            "stream": False,
            "think": self._think,
            "options": {
                "temperature": temperature if temperature is not None else self._temperature,
                "num_predict": max_tokens or self._default_max_tokens,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        started = time.monotonic()
        telemetry.record_call()
        telemetry.record_attempt()
        try:
            async with _slot():
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            telemetry.record_result(
                backend=self.name, model=self._model, ok=False,
                latency_ms=(time.monotonic() - started) * 1000, error=_error_label(exc),
            )
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000

        text = (data.get("message") or {}).get("content", "")
        return LLMReply(
            text=_strip_markdown_emphasis((text or "").strip()),
            backend=self.name,
            model=self._model,
            latency_ms=latency_ms,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code < 500
        except httpx.HTTPError:
            return False


def _is_retryable_vertex_error(exc: BaseException) -> bool:
    """429 (quota) and 5xx are worth a retry; anything else (bad request,
    auth failure, model not found) will just fail again immediately."""
    return isinstance(exc, genai_errors.APIError) and exc.code in (429, 500, 502, 503, 504)


def _is_cache_gone(exc: BaseException) -> bool:
    """The server no longer has the cached content we referenced."""
    if not isinstance(exc, genai_errors.APIError):
        return False
    return exc.code == 404 or (exc.code == 400 and "cache" in str(exc).lower())


def _backoff_seconds(attempt: int, initial: float, cap: float) -> float:
    """Exponential backoff with jitter: half to full of `initial * 2^(n-1)`."""
    ceiling = min(cap, initial * (2 ** (attempt - 1)))
    return ceiling * (0.5 + random.random() * 0.5)


class VertexBackend(LLMBackend):
    """Vertex AI Gemini -- the pilot's production backend.

    Authenticates via Application Default Credentials (the Cloud Run
    runtime service account's identity), never an API key -- the
    `google-genai` client picks this up automatically when `vertexai=True`
    and no explicit credentials are passed.
    """

    name = "vertex"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.vertex_model
        self._timeout = settings.llm_timeout_seconds
        self._default_max_tokens = settings.llm_max_tokens
        self._temperature = settings.llm_temperature
        self._vertex_project = settings.vertex_project or None
        self._vertex_location = settings.vertex_location
        self._context_cache_enabled = settings.llm_context_cache_enabled
        self._cache_ttl = settings.llm_context_cache_ttl_seconds
        # Client is created lazily on first use so a missing ADC at startup
        # (e.g. local dev with GPT=true + Vertex as fallback) doesn't crash.
        self._client: genai.Client | None = None
        self.cache_manager: ContextCacheManager | None = None
        self.supports_context_cache = settings.llm_context_cache_enabled

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self._vertex_project,
                location=self._vertex_location,
            )
            if self._context_cache_enabled:
                self.cache_manager = ContextCacheManager(
                    client=self._client,
                    model=self._model,
                    location=self._vertex_location,
                    ttl_seconds=self._cache_ttl,
                )
        return self._client

    async def _generate(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        cache: CacheRequest | None = None,
        cache_name: str | None = None,
        cache_fp: str | None = None,
    ):
        """The ONE place a Vertex generation is retried.

        Nothing above (router, pipeline, chat) retries, and the SDK's own
        retry is left unset, so a message can never multiply requests
        beyond `llm_max_attempts`. The concurrency slot is held only while
        a request is in flight, not while backing off.
        """
        settings = get_settings()
        started = time.monotonic()
        attempt = 0
        while True:
            attempt += 1
            telemetry.record_attempt(retry=attempt > 1)
            # With a live cache the system prompt and source material are
            # already server-side; only the dynamic half is sent.
            afc = genai_types.AutomaticFunctionCallingConfig(disable=True)
            # -1 leaves the model's own (dynamic) thinking alone; >= 0 caps it.
            thinking = (
                genai_types.ThinkingConfig(thinking_budget=settings.llm_thinking_budget)
                if settings.llm_thinking_budget >= 0
                else None
            )
            if cache_name and cache is not None:
                contents = cache.dynamic_user
                config = genai_types.GenerateContentConfig(
                    cached_content=cache_name,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    automatic_function_calling=afc,
                    thinking_config=thinking,
                )
            else:
                contents = user
                config = genai_types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    automatic_function_calling=afc,
                    thinking_config=thinking,
                )
            try:
                async with _slot():
                    return await asyncio.wait_for(
                        self._get_client().aio.models.generate_content(
                            model=self._model, contents=contents, config=config
                        ),
                        timeout=self._timeout,
                    )
            except genai_errors.APIError as exc:
                if cache_name and _is_cache_gone(exc) and attempt < settings.llm_max_attempts:
                    # Expired or deleted server-side: same generation, sent
                    # uncached this time (inline prompt), cache forgotten.
                    log.warning("Vertex context cache no longer valid; sending this request uncached")
                    if self.cache_manager is not None and cache_fp:
                        self.cache_manager.invalidate(cache_fp)
                    cache_name = None
                    telemetry.record_cache(hit=False, ref=(cache_fp or "")[:8] or None)
                    continue
                if not _is_retryable_vertex_error(exc) or attempt >= settings.llm_max_attempts:
                    raise
                delay = _backoff_seconds(
                    attempt, settings.llm_retry_initial_seconds, settings.llm_retry_max_seconds
                )
                if (time.monotonic() - started) + delay > settings.llm_retry_budget_seconds:
                    raise
                log.info("Vertex %s; retry %d in %.1fs", exc.code, attempt, delay)
                await asyncio.sleep(delay)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache: CacheRequest | None = None,
    ) -> LLMReply:
        started = time.monotonic()
        telemetry.record_call()
        cache_name: str | None = None
        cache_fp: str | None = None
        if cache is not None and self.cache_manager is not None:
            cache_fp = self.cache_manager.fingerprint(cache)
            cache_name = await self.cache_manager.resolve(cache)
            telemetry.record_cache(hit=cache_name is not None, ref=cache_fp[:8])
        try:
            response = await self._generate(
                system=system,
                user=user,
                max_tokens=max_tokens or self._default_max_tokens,
                temperature=temperature if temperature is not None else self._temperature,
                cache=cache,
                cache_name=cache_name,
                cache_fp=cache_fp,
            )
        except (genai_errors.APIError, TimeoutError, LLMUnavailable) as exc:
            telemetry.record_result(
                backend=self.name, model=self._model, ok=False,
                latency_ms=(time.monotonic() - started) * 1000, error=_error_label(exc),
            )
            if isinstance(exc, LLMUnavailable):
                raise
            raise LLMUnavailable(f"Vertex AI request failed: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000
        text = (getattr(response, "text", None) or "").strip()
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) if usage else None
        completion_tokens = getattr(usage, "candidates_token_count", None) if usage else None
        cached_tokens = getattr(usage, "cached_content_token_count", None) if usage else None
        thinking_tokens = getattr(usage, "thoughts_token_count", None) if usage else None
        telemetry.record_result(
            backend=self.name, model=self._model, ok=True, latency_ms=latency_ms,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens, thinking_tokens=thinking_tokens,
        )
        return LLMReply(
            text=_strip_markdown_emphasis(text),
            backend=self.name,
            model=self._model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def health(self) -> bool:
        try:
            await asyncio.wait_for(
                self._get_client().aio.models.generate_content(
                    model=self._model,
                    contents="ping",
                    config=genai_types.GenerateContentConfig(max_output_tokens=1),
                ),
                timeout=5.0,
            )
            return True
        except (genai_errors.APIError, TimeoutError, Exception):
            return False


def _is_retryable_openai_error(exc: BaseException) -> bool:
    """429 (except a quota exhaustion, which will not resolve itself),
    408/5xx, and network-level timeouts/connection failures are worth a
    retry; auth, permission, bad-request and not-found will just fail
    again immediately."""
    from openai import APIConnectionError, APIStatusError

    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        if exc.code == "insufficient_quota":
            return False
        return exc.status_code in (408, 429, 500, 502, 503, 504)
    return False


class OpenAIBackend(LLMBackend):
    """OpenAI Chat Completions -- selected when `GPT=true`.

    Uses the official `openai` SDK for transport only (`max_retries=0`):
    this class is the single retry owner for its own calls, the same
    discipline `VertexBackend._generate` uses, so one message can never
    multiply requests beyond `llm_max_attempts` regardless of which
    provider is wired in. The selected provider stays selected -- a
    failure here raises `LLMUnavailable`, which the caller's existing
    extractive fallback handles; this never silently calls Vertex, and
    `build_backend` never gives it an Ollama secondary, for the same
    reason (see that function's docstring).

    Chat Completions, not Responses: the same shape as the Vertex path
    (one system string, one user string in, one text reply out), so the
    prompt this backend receives is byte-identical to what Vertex would
    get -- prompt parity by construction, nothing OpenAI-specific in the
    content itself. `max_completion_tokens` replaces `max_tokens` and
    `temperature` is left at the API default (reasoning-family models
    reject a non-default value); `reasoning_effort` is passed only if
    configured.
    """

    name = "openai"
    supports_context_cache = False

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        self._model = settings.openai_model
        self._timeout = settings.llm_timeout_seconds
        self._default_max_tokens = settings.llm_max_tokens
        self._reasoning_effort = settings.openai_reasoning_effort
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key or None, max_retries=0, timeout=self._timeout
        )

    def _configured(self) -> bool:
        return bool(self._client.api_key) and bool(self._model)

    async def _generate(self, *, system: str, user: str, max_tokens: int):
        """The ONE place an OpenAI generation is retried -- mirrors
        `VertexBackend._generate`'s attempt/backoff/budget discipline."""
        settings = get_settings()
        started = time.monotonic()
        attempt = 0
        kwargs: dict = {}
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        while True:
            attempt += 1
            telemetry.record_attempt(retry=attempt > 1)
            try:
                async with _slot():
                    return await self._client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        max_completion_tokens=max_tokens,
                        **kwargs,
                    )
            except Exception as exc:
                if not _is_retryable_openai_error(exc) or attempt >= settings.llm_max_attempts:
                    raise
                delay = _backoff_seconds(
                    attempt, settings.llm_retry_initial_seconds, settings.llm_retry_max_seconds
                )
                if (time.monotonic() - started) + delay > settings.llm_retry_budget_seconds:
                    raise
                log.info("OpenAI %s; retry %d in %.1fs", type(exc).__name__, attempt, delay)
                await asyncio.sleep(delay)

    async def _complete_streaming(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        queue: asyncio.Queue,
    ) -> LLMReply:
        """complete() in streaming mode: pushes text chunks to queue, returns full reply.

        The caller (the SSE endpoint's background worker) already owns the
        concurrency slot via the normal _slot() path that wraps complete(); we
        acquire a fresh slot here because _complete_streaming IS complete() for
        this request -- the slot keeps the stream counted against the cap.
        """
        kwargs: dict = {}
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        started = time.monotonic()
        telemetry.record_call()
        telemetry.record_attempt()
        chunks: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

        sem = _get_semaphore()
        try:
            await asyncio.wait_for(
                sem.acquire(), timeout=get_settings().llm_queue_timeout_seconds
            )
        except TimeoutError:
            raise LLMUnavailable("LLM concurrency queue timeout") from None

        try:
            # One retry, and only while nothing has reached the student yet:
            # once a token is on the wire a retry would repeat or garble text.
            for attempt in range(2):
                try:
                    stream = await self._client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        max_completion_tokens=max_tokens,
                        stream=True,
                        stream_options={"include_usage": True},
                        **kwargs,
                    )
                    async for chunk in stream:
                        usage = getattr(chunk, "usage", None)
                        if usage is not None:
                            prompt_tokens = getattr(usage, "prompt_tokens", None)
                            completion_tokens = getattr(usage, "completion_tokens", None)
                        delta = chunk.choices[0].delta.content if chunk.choices else None
                        if delta:
                            if not chunks:
                                telemetry.record_ttft((time.monotonic() - started) * 1000)
                            chunks.append(delta)
                            await queue.put(delta)
                    break
                except Exception as exc:
                    if chunks or attempt == 1 or not _is_retryable_openai_error(exc):
                        raise
                    log.warning("OpenAI stream failed before the first token (%s); retrying once", _error_label(exc))
                    telemetry.record_attempt(retry=True)
                    await asyncio.sleep(0.5)
        except Exception as exc:
            latency_ms = (time.monotonic() - started) * 1000
            telemetry.record_result(
                backend=self.name, model=self._model, ok=False,
                latency_ms=latency_ms, error=_error_label(exc),
            )
            raise LLMUnavailable(f"OpenAI streaming request failed: {exc}") from exc
        finally:
            sem.release()

        latency_ms = (time.monotonic() - started) * 1000
        full_text = "".join(chunks)
        telemetry.record_result(
            backend=self.name, model=self._model, ok=True, latency_ms=latency_ms,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )
        return LLMReply(
            text=_strip_markdown_emphasis(full_text.strip()),
            backend=self.name,
            model=self._model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache: CacheRequest | None = None,
    ) -> LLMReply:
        if not self._configured():
            raise LLMUnavailable("OpenAI backend is not configured (OPENAI_API_KEY is required)")

        token_cap = max(max_tokens or self._default_max_tokens, 1000)
        # Streaming mode: when the SSE endpoint has set a queue in this task's
        # context, push tokens to it and return the assembled reply as normal.
        queue = _stream_queue.get()
        if queue is not None:
            return await self._complete_streaming(
                system=system,
                user=user,
                max_tokens=token_cap,
                queue=queue,
            )

        started = time.monotonic()
        telemetry.record_call()
        try:
            response = await self._generate(
                system=system, user=user, max_tokens=token_cap
            )
        except Exception as exc:
            telemetry.record_result(
                backend=self.name, model=self._model, ok=False,
                latency_ms=(time.monotonic() - started) * 1000, error=_error_label(exc),
            )
            raise LLMUnavailable(f"OpenAI request failed: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if choice.finish_reason == "length" and not text:
            # Truncated before producing any visible text -- the extractive
            # fallback is more useful than an empty reply.
            telemetry.record_result(
                backend=self.name, model=self._model, ok=False,
                latency_ms=latency_ms, error="openai_truncated",
            )
            raise LLMUnavailable("OpenAI reply was truncated with no visible text")
        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        completion_details = getattr(usage, "completion_tokens_details", None) if usage else None
        cached_tokens = getattr(prompt_details, "cached_tokens", None) if prompt_details else None
        thinking_tokens = (
            getattr(completion_details, "reasoning_tokens", None) if completion_details else None
        )
        telemetry.record_result(
            backend=self.name, model=self._model, ok=True, latency_ms=latency_ms,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens, thinking_tokens=thinking_tokens,
        )
        return LLMReply(
            text=_strip_markdown_emphasis(text),
            backend=self.name,
            model=self._model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def health(self) -> bool:
        if not self._configured():
            return False
        try:
            await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_completion_tokens=50,
                ),
                timeout=5.0,
            )
            return True
        except Exception:
            return False


class FallbackBackend(LLMBackend):
    """Tries the primary backend, then the secondary.

    Wired only when `LABTUTOR_LLM_AUTO_FALLBACK` is on. It exists so a
    mid-pilot outage of the hosted provider degrades to local inference
    instead of failing every request -- the documented rollback path.
    """

    name = "fallback"

    def __init__(self, primary: LLMBackend, secondary: LLMBackend) -> None:
        self.primary = primary
        self.secondary = secondary
        self.supports_context_cache = primary.supports_context_cache

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache: CacheRequest | None = None,
    ) -> LLMReply:
        try:
            extra = {"cache": cache} if cache is not None else {}
            return await self.primary.complete(
                system=system, user=user, max_tokens=max_tokens, temperature=temperature, **extra
            )
        except LLMUnavailable as exc:
            log.warning(
                "Primary LLM backend (%s) unavailable, falling back to %s: %s",
                self.primary.name,
                self.secondary.name,
                exc,
            )
        return await self.secondary.complete(
            system=system, user=user, max_tokens=max_tokens, temperature=temperature
        )

    async def health(self) -> bool:
        results = await asyncio.gather(
            self.primary.health(), self.secondary.health(), return_exceptions=True
        )
        return any(r is True for r in results)


_cached: LLMBackend | None = None


def build_backend(settings: Settings) -> LLMBackend:
    # GPT=true: OpenAI is primary.
    if settings.gpt:
        return OpenAIBackend(settings)

    # Pure Vertex path (production, non-GPT). No local secondary.
    if settings.llm_backend == "vertex":
        return VertexBackend(settings)

    # Local dev paths only (ollama / hosted).
    lo: LLMBackend
    hi: LLMBackend
    if settings.llm_backend == "ollama":
        lo, hi = OllamaBackend(settings), HostedBackend(settings)
    else:
        lo, hi = HostedBackend(settings), OllamaBackend(settings)

    if settings.llm_auto_fallback:
        return FallbackBackend(lo, hi)
    return lo


def get_backend() -> LLMBackend:
    global _cached
    if _cached is None:
        _cached = build_backend(get_settings())
    return _cached


def reset_backend_cache() -> None:
    """Tests and config reloads."""
    global _cached
    _cached = None


def reset_concurrency_limit() -> None:
    """Tests and config reloads (LABTUTOR_LLM_MAX_CONCURRENCY changes)."""
    global _semaphore, _bg_semaphore
    _semaphore = None
    _bg_semaphore = None
