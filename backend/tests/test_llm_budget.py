"""Live students and background jobs draw from separate LLM concurrency pools,
and a streamed reply records its time to first token."""

import asyncio

import pytest

from backend.config import reload_settings
from backend.llm import client, telemetry

pytestmark = pytest.mark.asyncio


@pytest.fixture
def tiny_pools(monkeypatch):
    monkeypatch.setenv("LABTUTOR_LLM_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("LABTUTOR_LLM_BACKGROUND_CONCURRENCY", "1")
    monkeypatch.setenv("LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS", "0.2")
    reload_settings()
    client.reset_concurrency_limit()
    yield
    monkeypatch.delenv("LABTUTOR_LLM_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("LABTUTOR_LLM_BACKGROUND_CONCURRENCY", raising=False)
    monkeypatch.delenv("LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS", raising=False)
    reload_settings()
    client.reset_concurrency_limit()


async def test_background_work_cannot_take_a_live_students_slot(tiny_pools):
    entered_background = asyncio.Event()
    release = asyncio.Event()

    async def background_job():
        client.mark_background()
        async with client._slot():
            entered_background.set()
            await release.wait()

    task = asyncio.create_task(background_job())
    await entered_background.wait()
    # The background job holds its only slot; a live student still gets theirs.
    async with client._slot():
        pass
    release.set()
    await task


async def test_a_busy_live_pool_does_not_block_background_work_either(tiny_pools):
    async with client._slot():  # the only live slot is taken
        async def background():
            client.mark_background()
            async with client._slot():
                return "ran"

        assert await asyncio.create_task(background()) == "ran"


async def test_live_pool_still_fails_fast_when_full(tiny_pools):
    async with client._slot():
        with pytest.raises(client.LLMUnavailable):
            async with client._slot():
                pass


async def test_marking_background_in_a_task_does_not_leak_to_the_caller(tiny_pools):
    async def job():
        client.mark_background()

    await asyncio.create_task(job())
    assert client._background.get() is False


async def test_ttft_is_recorded_once_and_exposed_in_the_request_meta():
    stats = telemetry.begin_request()
    telemetry.record_ttft(420.04)
    telemetry.record_ttft(999.0)  # a later generation does not overwrite the first
    assert stats.as_meta()["ttft_ms"] == 420.0


async def test_ttft_absent_when_nothing_streamed():
    assert "ttft_ms" not in telemetry.begin_request().as_meta()


# ------------------------------------------------ streaming: retry, TTFT, usage


class _Chunk:
    def __init__(self, text=None, usage=None):
        self.choices = [type("C", (), {"delta": type("D", (), {"content": text})()})()] if text is not None else []
        self.usage = usage


class _Stream:
    def __init__(self, items, fail_after=None, exc=None):
        self.items, self.fail_after, self.exc = items, fail_after, exc

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for i, item in enumerate(self.items):
            if self.fail_after is not None and i == self.fail_after:
                raise self.exc
            yield item


def _backend(create):
    backend = client.OpenAIBackend.__new__(client.OpenAIBackend)
    backend._model, backend._reasoning_effort = "m", ""
    backend._client = type("X", (), {"chat": type("Y", (), {"completions": type("Z", (), {"create": staticmethod(create)})()})()})()
    return backend


def _connection_error():
    import httpx
    from openai import APIConnectionError

    return APIConnectionError(request=httpx.Request("POST", "http://x"))


async def test_stream_retries_once_when_it_fails_before_any_token(tiny_pools, monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_: real_sleep(0))  # no real wait
    attempts = []

    async def create(**kw):
        attempts.append(kw)
        if len(attempts) == 1:
            raise _connection_error()
        usage = type("U", (), {"prompt_tokens": 120, "completion_tokens": 30})()
        return _Stream([_Chunk("Hel"), _Chunk("lo"), _Chunk(None, usage)])

    stats = telemetry.begin_request()
    queue: asyncio.Queue = asyncio.Queue()
    reply = await _backend(create)._complete_streaming(system="s", user="u", max_tokens=50, queue=queue)
    assert reply.text == "Hello" and len(attempts) == 2
    assert attempts[0]["stream_options"] == {"include_usage": True}
    assert (reply.prompt_tokens, reply.completion_tokens) == (120, 30)
    assert stats.retry_count == 1 and stats.ttft_ms is not None
    assert [queue.get_nowait(), queue.get_nowait()] == ["Hel", "lo"]


async def test_stream_does_not_retry_once_text_has_reached_the_student(tiny_pools):
    attempts = []

    async def create(**kw):
        attempts.append(kw)
        return _Stream([_Chunk("Hel"), _Chunk("lo")], fail_after=1, exc=_connection_error())

    queue: asyncio.Queue = asyncio.Queue()
    with pytest.raises(client.LLMUnavailable):
        await _backend(create)._complete_streaming(system="s", user="u", max_tokens=50, queue=queue)
    assert len(attempts) == 1  # a retry would repeat "Hel" to the student


async def test_stream_does_not_retry_a_non_retryable_error(tiny_pools):
    import httpx
    from openai import AuthenticationError

    attempts = []

    async def create(**kw):
        attempts.append(kw)
        resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
        raise AuthenticationError("bad key", response=resp, body=None)

    with pytest.raises(client.LLMUnavailable):
        await _backend(create)._complete_streaming(system="s", user="u", max_tokens=50, queue=asyncio.Queue())
    assert len(attempts) == 1
