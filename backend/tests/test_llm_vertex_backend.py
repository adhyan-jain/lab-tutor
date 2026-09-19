"""VertexBackend -- the pilot's production LLM backend.

Mocks `google.genai.Client` entirely; no real Vertex AI call is made.
Covers: successful replies get the same markdown-stripping every backend
applies, 429/5xx are retried and eventually succeed, retries are
exhausted and surface as LLMUnavailable (never a raw SDK exception), and
a non-retryable error (e.g. 400) fails on the first attempt instead of
wasting two retries on something that will never succeed.
"""

from __future__ import annotations

import asyncio

import pytest
from google.genai import errors as genai_errors

from backend.config import Settings
from backend.llm.client import LLMUnavailable, VertexBackend

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, side_effects: list) -> None:
        # Each entry is either an _FakeResponse (returned) or an
        # exception instance (raised) for that call, in order.
        self._side_effects = list(side_effects)
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self._side_effects.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeAio:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


class _FakeClient:
    def __init__(self, models: _FakeModels, **kwargs) -> None:
        self.aio = _FakeAio(models)


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Tenacity's async wait sleeps via `asyncio.sleep` -- make retries
    in this test module instant instead of waiting up to 8s each."""

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _install_fake_client(monkeypatch, side_effects: list) -> _FakeModels:
    models = _FakeModels(side_effects)

    def _fake_ctor(*, vertexai, project, location):
        return _FakeClient(models)

    monkeypatch.setattr("backend.llm.client.genai.Client", _fake_ctor)
    return models


async def test_successful_reply_preserves_content(monkeypatch):
    _install_fake_client(monkeypatch, [_FakeResponse("**bold** reply")])
    backend = VertexBackend(Settings())
    reply = await backend.complete(system="s", user="u")
    assert reply.text == "**bold** reply"
    assert reply.backend == "vertex"



async def test_retries_on_429_then_succeeds(monkeypatch):
    rate_limited = genai_errors.APIError(
        code=429, response_json={"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    models = _install_fake_client(
        monkeypatch, [rate_limited, rate_limited, _FakeResponse("ok on third try")]
    )
    backend = VertexBackend(Settings())
    reply = await backend.complete(system="s", user="u")
    assert reply.text == "ok on third try"
    assert len(models.calls) == 3


async def test_exhausted_retries_surface_as_llm_unavailable(monkeypatch):
    server_error = genai_errors.APIError(
        code=503, response_json={"error": {"message": "unavailable", "status": "UNAVAILABLE"}}
    )
    models = _install_fake_client(monkeypatch, [server_error] * 6)
    backend = VertexBackend(Settings())
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    # stopped after the configured attempt cap (LABTUTOR_LLM_MAX_ATTEMPTS=3)
    assert len(models.calls) == Settings().llm_max_attempts == 3


async def test_afc_is_disabled_on_every_request(monkeypatch):
    models = _install_fake_client(monkeypatch, [_FakeResponse("hi")])
    await VertexBackend(Settings()).complete(system="s", user="u")
    afc = models.calls[0]["config"].automatic_function_calling
    assert afc is not None and afc.disable is True


async def test_telemetry_counts_one_call_and_its_retries(monkeypatch):
    from backend.llm import telemetry

    rate_limited = genai_errors.APIError(
        code=429, response_json={"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    _install_fake_client(monkeypatch, [rate_limited, _FakeResponse("ok")])
    stats = telemetry.begin_request()
    await VertexBackend(Settings()).complete(system="s", user="u")
    assert stats.calls == 1  # one logical generation ...
    assert stats.attempts == 2 and stats.retry_count == 1  # ... two HTTP attempts
    assert stats.vertex_attempted and stats.vertex_succeeded


async def test_failure_is_recorded_without_leaking_message_text(monkeypatch):
    from backend.llm import telemetry

    bad_request = genai_errors.APIError(
        code=400, response_json={"error": {"message": "secret student text", "status": "X"}}
    )
    _install_fake_client(monkeypatch, [bad_request])
    stats = telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await VertexBackend(Settings()).complete(system="s", user="u")
    assert stats.vertex_attempted and not stats.vertex_succeeded
    assert stats.vertex_error.endswith(":400")
    assert "secret" not in stats.vertex_error


async def test_retry_stops_when_wall_clock_budget_is_spent(monkeypatch):
    from backend.config import get_settings

    server_error = genai_errors.APIError(
        code=503, response_json={"error": {"message": "unavailable", "status": "UNAVAILABLE"}}
    )
    models = _install_fake_client(monkeypatch, [server_error] * 6)
    monkeypatch.setenv("LABTUTOR_LLM_RETRY_BUDGET_SECONDS", "0")
    get_settings.cache_clear()
    try:
        with pytest.raises(LLMUnavailable):
            await VertexBackend(Settings()).complete(system="s", user="u")
    finally:
        monkeypatch.delenv("LABTUTOR_LLM_RETRY_BUDGET_SECONDS")
        get_settings.cache_clear()
    assert len(models.calls) == 1  # no retry fits inside a zero budget


async def test_concurrency_queue_timeout_falls_back_instead_of_waiting(monkeypatch):
    from backend.config import get_settings
    from backend.llm import client as llm_client

    _install_fake_client(monkeypatch, [_FakeResponse("never sent")])
    monkeypatch.setenv("LABTUTOR_LLM_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()
    llm_client.reset_concurrency_limit()
    try:
        await llm_client._get_semaphore().acquire()  # the only slot is busy
        with pytest.raises(LLMUnavailable, match="queue timeout"):
            await VertexBackend(Settings()).complete(system="s", user="u")
    finally:
        monkeypatch.delenv("LABTUTOR_LLM_MAX_CONCURRENCY")
        monkeypatch.delenv("LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS")
        get_settings.cache_clear()
        llm_client.reset_concurrency_limit()


async def test_non_retryable_error_fails_on_first_attempt(monkeypatch):
    bad_request = genai_errors.APIError(
        code=400, response_json={"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}}
    )
    models = _install_fake_client(monkeypatch, [bad_request])
    backend = VertexBackend(Settings())
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    assert len(models.calls) == 1  # no retry wasted on a request that will never succeed
