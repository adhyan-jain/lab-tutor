"""LLM backend interface and the concrete implementations.

Callers depend on `LLMBackend`, never on a provider. Adding a backend
means adding a class here and one value to the config enum; no call site
changes.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import re
import time
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from backend.config import Settings, get_settings

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


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return _semaphore


class LLMUnavailable(RuntimeError):
    """No configured backend could serve the request.

    Callers must degrade gracefully -- every LLM use in this system is for
    *phrasing* something already decided, so an outage costs polish, never
    correctness. See README "Rollback plan".
    """


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
        try:
            async with _get_semaphore():
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
                    resp.raise_for_status()
                    data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
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
        try:
            async with _get_semaphore():
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
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
        self._client = genai.Client(
            vertexai=True,
            project=settings.vertex_project or None,
            location=settings.vertex_location,
        )

    @retry(
        retry=retry_if_exception(_is_retryable_vertex_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        reraise=True,
    )
    async def _generate(self, *, system: str, user: str, max_tokens: int, temperature: float):
        async with _get_semaphore():
            return await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                ),
                timeout=self._timeout,
            )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        started = time.monotonic()
        try:
            response = await self._generate(
                system=system,
                user=user,
                max_tokens=max_tokens or self._default_max_tokens,
                temperature=temperature if temperature is not None else self._temperature,
            )
        except (genai_errors.APIError, TimeoutError) as exc:
            raise LLMUnavailable(f"Vertex AI request failed: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000
        text = (getattr(response, "text", None) or "").strip()
        usage = getattr(response, "usage_metadata", None)
        return LLMReply(
            text=_strip_markdown_emphasis(text),
            backend=self.name,
            model=self._model,
            latency_ms=latency_ms,
            prompt_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            completion_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
        )

    async def health(self) -> bool:
        try:
            await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents="ping",
                    config=genai_types.GenerateContentConfig(max_output_tokens=1),
                ),
                timeout=5.0,
            )
            return True
        except (genai_errors.APIError, TimeoutError):
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

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        try:
            return await self.primary.complete(
                system=system, user=user, max_tokens=max_tokens, temperature=temperature
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
    primary: LLMBackend
    secondary: LLMBackend
    if settings.llm_backend == "ollama":
        primary, secondary = OllamaBackend(settings), HostedBackend(settings)
    elif settings.llm_backend == "vertex":
        primary, secondary = VertexBackend(settings), OllamaBackend(settings)
    else:
        primary, secondary = HostedBackend(settings), OllamaBackend(settings)

    if settings.llm_auto_fallback:
        return FallbackBackend(primary, secondary)
    return primary


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
    global _semaphore
    _semaphore = None
