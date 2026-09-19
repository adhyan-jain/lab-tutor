"""Per-request LLM accounting.

A student message must cost at most one model generation. `begin_request`
installs a mutable stats object in a contextvar at the top of a request;
every backend `complete()` adds to it. Child asyncio tasks share the same
object, so nothing a handler awaits can spend a generation unseen.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class LLMRequestStats:
    #: Logical generations requested (one per `complete()` call).
    calls: int = 0
    #: HTTP attempts actually sent to the provider (>= calls when retried).
    attempts: int = 0
    retry_count: int = 0
    vertex_attempted: bool = False
    vertex_succeeded: bool = False
    vertex_error: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    backend: str | None = None
    model: str | None = None
    latency_ms: float = 0.0
    cache_hit: bool | None = None
    cache_ref: str | None = None
    cached_tokens: int | None = None
    #: Hidden reasoning tokens (Gemini 2.5). Billed and slow, but not part of
    #: the visible completion count, so a long wait can hide here.
    thinking_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def as_meta(self) -> dict:
        meta: dict = {
            "llm_calls": self.calls,
            "llm_attempts": self.attempts,
            "retry_count": self.retry_count,
            "vertex_attempted": self.vertex_attempted,
            "vertex_succeeded": self.vertex_succeeded,
            "fallback_used": self.fallback_used,
        }
        if self.vertex_error:
            meta["vertex_error"] = self.vertex_error
        if self.fallback_reason:
            meta["fallback_reason"] = self.fallback_reason
        if self.cache_hit is not None:
            meta["cache_hit"] = self.cache_hit
        if self.cache_ref:
            meta["cache_ref"] = self.cache_ref
        if self.cached_tokens is not None:
            meta["cached_tokens"] = self.cached_tokens
        if self.thinking_tokens is not None:
            meta["thinking_tokens"] = self.thinking_tokens
        return meta


_current: ContextVar[LLMRequestStats | None] = ContextVar("labtutor_llm_stats", default=None)


def begin_request() -> LLMRequestStats:
    stats = LLMRequestStats()
    _current.set(stats)
    return stats


def current() -> LLMRequestStats | None:
    return _current.get()


def record_call() -> None:
    stats = _current.get()
    if stats is None:
        return
    stats.calls += 1
    if stats.calls > 1:
        log.warning(
            "llm_calls_exceeded calls=%d (one generation per message is the budget)",
            stats.calls,
        )


def record_attempt(*, retry: bool = False) -> None:
    stats = _current.get()
    if stats is None:
        return
    stats.attempts += 1
    if retry:
        stats.retry_count += 1


def record_fallback(reason: str) -> None:
    stats = _current.get()
    if stats is None:
        return
    stats.fallback_used = True
    stats.fallback_reason = reason


def record_result(
    *,
    backend: str,
    model: str,
    ok: bool,
    latency_ms: float,
    error: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
    thinking_tokens: int | None = None,
) -> None:
    stats = _current.get()
    if stats is None:
        return
    stats.backend = backend
    stats.model = model
    stats.latency_ms += latency_ms
    if backend == "vertex":
        stats.vertex_attempted = True
        stats.vertex_succeeded = ok
        stats.vertex_error = None if ok else error
    if ok:
        stats.prompt_tokens = prompt_tokens
        stats.completion_tokens = completion_tokens
        stats.cached_tokens = cached_tokens
        stats.thinking_tokens = thinking_tokens


def record_cache(*, hit: bool, ref: str | None) -> None:
    stats = _current.get()
    if stats is None:
        return
    stats.cache_hit = hit
    stats.cache_ref = ref
