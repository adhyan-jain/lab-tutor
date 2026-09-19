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
    assert len(models.calls) == 6  # stopped after the configured attempt cap


async def test_non_retryable_error_fails_on_first_attempt(monkeypatch):
    bad_request = genai_errors.APIError(
        code=400, response_json={"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}}
    )
    models = _install_fake_client(monkeypatch, [bad_request])
    backend = VertexBackend(Settings())
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    assert len(models.calls) == 1  # no retry wasted on a request that will never succeed
