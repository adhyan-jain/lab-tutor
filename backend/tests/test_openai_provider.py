"""GPT=true/false provider switch.

A fake OpenAI client stands in for the network, mirroring only the
response shape `OpenAIBackend` reads (choices[0].message.content,
finish_reason, usage and its nested *_details). No real network call is
made anywhere in this file.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.config import Settings, reload_settings
from backend.llm import telemetry
from backend.llm.client import (
    FallbackBackend,
    LLMUnavailable,
    OpenAIBackend,
    VertexBackend,
    build_backend,
)

pytestmark = pytest.mark.asyncio


def _usage(prompt=100, completion=50, cached=None, reasoning=None):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached) if cached is not None else None,
        completion_tokens_details=(
            SimpleNamespace(reasoning_tokens=reasoning) if reasoning is not None else None
        ),
    )


def _response(text="an answer", finish_reason="stop", usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)],
        usage=usage if usage is not None else _usage(),
    )


def _openai_error(cls_name: str, status_code: int | None, code: str | None = None):
    import openai

    cls = getattr(openai, cls_name)
    if cls_name == "APIConnectionError":
        return cls(request=SimpleNamespace())
    response = SimpleNamespace(status_code=status_code, headers={}, request=SimpleNamespace())
    body = {"code": code} if code else None
    return cls(message=cls_name, response=response, body=body)


@pytest.fixture
def gpt_settings(monkeypatch):
    monkeypatch.setenv("GPT", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    reload_settings()
    yield
    monkeypatch.delenv("GPT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    reload_settings()


@pytest.fixture
def fake_openai(monkeypatch):
    """Patch AsyncOpenAI so `OpenAIBackend.__init__` gets a fake client
    with a scriptable `chat.completions.create`."""
    created = SimpleNamespace(calls=[], outcomes=[])

    async def _create(**kwargs):
        created.calls.append(kwargs)
        if created.outcomes:
            outcome = created.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return _response()

    def _factory(*, api_key=None, max_retries=0, timeout=None):
        return SimpleNamespace(
            api_key=api_key,
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
        )

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _factory)
    return created


# --------------------------------------------------------------- selection


async def test_gpt_true_selects_openai_and_never_builds_a_vertex_client(gpt_settings, fake_openai, monkeypatch):
    built_vertex = []
    monkeypatch.setattr(VertexBackend, "__init__", lambda self, settings: built_vertex.append(1))
    backend = build_backend(Settings())
    assert isinstance(backend, OpenAIBackend)
    assert not built_vertex


async def test_gpt_false_selects_the_existing_vertex_path_unchanged(monkeypatch):
    monkeypatch.delenv("GPT", raising=False)
    monkeypatch.setenv("LABTUTOR_LLM_BACKEND", "vertex")
    monkeypatch.setenv("LABTUTOR_LLM_AUTO_FALLBACK", "false")
    monkeypatch.setattr(
        "backend.llm.client.genai.Client", lambda **kwargs: SimpleNamespace(aio=SimpleNamespace())
    )
    backend = build_backend(reload_settings())
    assert isinstance(backend, VertexBackend)
    monkeypatch.delenv("LABTUTOR_LLM_BACKEND", raising=False)
    monkeypatch.delenv("LABTUTOR_LLM_AUTO_FALLBACK", raising=False)
    reload_settings()


async def test_gpt_true_gives_no_ollama_fallback(gpt_settings, fake_openai):
    backend = build_backend(Settings())
    assert isinstance(backend, OpenAIBackend)
    assert not isinstance(backend, FallbackBackend)


async def test_model_defaults_to_the_named_model_and_env_can_override(gpt_settings, fake_openai, monkeypatch):
    backend = OpenAIBackend(Settings())
    assert backend._model == "gpt-5.6-luna"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-9000")
    backend2 = OpenAIBackend(reload_settings())
    assert backend2._model == "gpt-9000"


async def test_missing_api_key_raises_a_clear_config_error_that_omits_the_key(monkeypatch):
    monkeypatch.setenv("GPT", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError) as exc_info:
        Settings(_env_file=None)
    message = str(exc_info.value)
    assert "OPENAI_API_KEY" in message
    assert "sk-" not in message
    monkeypatch.delenv("GPT", raising=False)
    reload_settings()


async def test_gpt_false_never_touches_openai(monkeypatch):
    monkeypatch.delenv("GPT", raising=False)
    monkeypatch.setenv("LABTUTOR_LLM_BACKEND", "vertex")
    monkeypatch.setenv("LABTUTOR_LLM_AUTO_FALLBACK", "false")
    import openai

    called = []
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: called.append(kw) or SimpleNamespace())
    monkeypatch.setattr(
        "backend.llm.client.genai.Client", lambda **kwargs: SimpleNamespace(aio=SimpleNamespace())
    )
    build_backend(reload_settings())
    assert called == []
    monkeypatch.delenv("LABTUTOR_LLM_BACKEND", raising=False)
    monkeypatch.delenv("LABTUTOR_LLM_AUTO_FALLBACK", raising=False)
    reload_settings()


# ------------------------------------------------------------- request shape


async def test_request_uses_max_completion_tokens_no_temperature_same_prompt_as_vertex(
    gpt_settings, fake_openai
):
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    await backend.complete(system="SYS", user="USER", max_tokens=500)
    call = fake_openai.calls[-1]
    assert call["max_completion_tokens"] == 500
    assert "temperature" not in call
    assert call["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


async def test_reasoning_effort_is_passed_only_when_configured(gpt_settings, fake_openai, monkeypatch):
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    await backend.complete(system="s", user="u")
    assert "reasoning_effort" not in fake_openai.calls[-1]

    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    backend2 = OpenAIBackend(reload_settings())
    await backend2.complete(system="s", user="u")
    assert fake_openai.calls[-1]["reasoning_effort"] == "low"
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)


# ----------------------------------------------------------------- one call


async def test_one_message_is_at_most_one_generation_on_success(gpt_settings, fake_openai):
    backend = OpenAIBackend(Settings())
    stats = telemetry.begin_request()
    await backend.complete(system="s", user="u")
    assert stats.calls == 1
    assert stats.attempts == 1


async def test_rate_limit_then_success_is_one_generation_and_one_retry(gpt_settings, fake_openai):
    fake_openai.outcomes = [_openai_error("RateLimitError", 429), _response()]
    backend = OpenAIBackend(Settings())
    stats = telemetry.begin_request()
    reply = await backend.complete(system="s", user="u")
    assert reply.text == "an answer"
    assert stats.calls == 1 and stats.attempts == 2 and stats.retry_count == 1


async def test_insufficient_quota_does_not_retry(gpt_settings, fake_openai):
    fake_openai.outcomes = [_openai_error("RateLimitError", 429, code="insufficient_quota")]
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    assert len(fake_openai.calls) == 1


async def test_auth_error_does_not_retry(gpt_settings, fake_openai):
    fake_openai.outcomes = [_openai_error("AuthenticationError", 401)]
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    assert len(fake_openai.calls) == 1


async def test_bad_request_does_not_retry(gpt_settings, fake_openai):
    fake_openai.outcomes = [_openai_error("BadRequestError", 400)]
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    assert len(fake_openai.calls) == 1


async def test_retries_are_bounded_by_max_attempts(gpt_settings, fake_openai, monkeypatch):
    monkeypatch.setenv("LABTUTOR_LLM_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LABTUTOR_LLM_RETRY_INITIAL_SECONDS", "0.001")
    monkeypatch.setenv("LABTUTOR_LLM_RETRY_MAX_SECONDS", "0.001")
    reload_settings()
    fake_openai.outcomes = [_openai_error("InternalServerError", 500) for _ in range(5)]
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")
    assert len(fake_openai.calls) == 3
    monkeypatch.delenv("LABTUTOR_LLM_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("LABTUTOR_LLM_RETRY_INITIAL_SECONDS", raising=False)
    monkeypatch.delenv("LABTUTOR_LLM_RETRY_MAX_SECONDS", raising=False)
    reload_settings()


async def test_truncated_empty_reply_raises_for_the_extractive_fallback(gpt_settings, fake_openai):
    fake_openai.outcomes = [_response(text="", finish_reason="length")]
    backend = OpenAIBackend(Settings())
    telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")


async def test_no_silent_cross_provider_fallback_on_openai_failure(gpt_settings, fake_openai):
    """The selected provider stays selected: a failure raises, it never
    quietly calls a different backend."""
    fake_openai.outcomes = [_openai_error("AuthenticationError", 401)]
    backend = build_backend(Settings())
    assert not isinstance(backend, FallbackBackend)
    telemetry.begin_request()
    with pytest.raises(LLMUnavailable):
        await backend.complete(system="s", user="u")


# ------------------------------------------------------------------ telemetry


async def test_telemetry_records_provider_model_and_token_breakdown(gpt_settings, fake_openai):
    fake_openai.outcomes = [_response(usage=_usage(prompt=900, completion=300, cached=200, reasoning=40))]
    backend = OpenAIBackend(Settings())
    stats = telemetry.begin_request()
    await backend.complete(system="s", user="u")
    assert stats.backend == "openai"
    assert stats.model == "gpt-5.6-luna"
    assert stats.prompt_tokens == 900 and stats.completion_tokens == 300
    assert stats.cached_tokens == 200 and stats.thinking_tokens == 40


async def test_message_metadata_reports_the_active_provider():
    """_llm_meta reads from recorded telemetry, not settings, so it stays
    correct whichever provider actually served the turn."""
    from backend.api.chat_routes import _llm_meta

    stats = telemetry.begin_request()
    stats.backend = "openai"
    stats.model = "gpt-5.6-luna"
    meta = _llm_meta(1234.0, 900, 300)
    assert meta["llm_backend"] == "openai"
    assert meta["llm_model"] == "gpt-5.6-luna"
