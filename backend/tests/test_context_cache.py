"""Versioned native context caching -- no real Vertex call is made.

A fake `google.genai` client stands in for the cache API and for
`generate_content`, so these tests check what LabTutor *asks Google to do*:
which cache it selects, when it creates one, what it sends per message, and
that a message still costs exactly one generation.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from backend.config import Settings, reload_settings
from backend.llm import telemetry
from backend.llm.client import VertexBackend
from backend.llm.context_cache import (
    POLICY_VERSION,
    CacheRequest,
    ContextCacheManager,
    cache_display_name,
)
from backend.retrieval.chunks import Chunk
from backend.retrieval.stable_context import build_cache_request, experiment_chunks
from backend.sources.tiers import SourceTier

pytestmark = pytest.mark.asyncio

MODEL = "gemini-2.5-flash"
LOCATION = "asia-south1"


# --- fakes ------------------------------------------------------------------


class _AsyncIter:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._it = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


class _FakeCaches:
    def __init__(self):
        self.store: list[SimpleNamespace] = []
        self.created = 0
        self.updated: list[str] = []
        self.deleted: list[str] = []
        self.create_configs: list = []
        self.fail_create = False
        self.create_delay = 0.0
        self._n = 0

    def add(self, display_name, *, age_seconds=0, ttl=10800, model=MODEL):
        self._n += 1
        now = dt.datetime.now(dt.timezone.utc)
        item = SimpleNamespace(
            name=f"cachedContents/{self._n}",
            display_name=display_name,
            model=f"projects/p/locations/{LOCATION}/publishers/google/models/{model}",
            create_time=now - dt.timedelta(seconds=age_seconds),
            expire_time=now + dt.timedelta(seconds=ttl),
        )
        self.store.append(item)
        return item

    async def create(self, *, model, config):
        if self.create_delay:
            await asyncio.sleep(self.create_delay)
        if self.fail_create:
            raise RuntimeError("cache service down")
        self.created += 1
        self.create_configs.append(config)
        return self.add(config.display_name, model=model)

    async def list(self, config=None):
        return _AsyncIter(list(self.store))

    async def update(self, *, name, config):
        self.updated.append(name)
        item = next(i for i in self.store if i.name == name)
        item.expire_time = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=10800)
        return item

    async def delete(self, *, name):
        self.deleted.append(name)
        self.store = [i for i in self.store if i.name != name]


class _FakeModels:
    def __init__(self):
        self.calls: list[dict] = []
        self.outcomes: list = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return SimpleNamespace(
            text="an answer",
            usage_metadata=SimpleNamespace(
                prompt_token_count=6900,
                candidates_token_count=300,
                cached_content_token_count=6500 if config.cached_content else 0,
            ),
        )


class _FakeClient:
    def __init__(self):
        self.aio = SimpleNamespace(caches=_FakeCaches(), models=_FakeModels())


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    real_sleep = asyncio.sleep

    async def _tiny(seconds):
        await real_sleep(0)

    monkeypatch.setattr("backend.llm.client.asyncio.sleep", _tiny)


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr("backend.llm.client.genai.Client", lambda **kw: client)
    return client


@pytest.fixture
def cache_on(monkeypatch):
    monkeypatch.setenv("LABTUTOR_LLM_CONTEXT_CACHE", "true")
    reload_settings()
    yield
    monkeypatch.delenv("LABTUTOR_LLM_CONTEXT_CACHE", raising=False)
    reload_settings()


def _request(question="What is HOMO?", *, context="PASSAGES v1", scope="exp07"):
    return CacheRequest(
        scope=scope,
        system="SYSTEM",
        context_text=context,
        dynamic_user=f"QUESTION: {question}",
        provenance="c1|doc|A|v1",
    )


def _manager(client, ttl=10800):
    return ContextCacheManager(client=client, model=MODEL, location=LOCATION, ttl_seconds=ttl)


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


def _chunk(chunk_id, text, tier=SourceTier.OFFICIAL_MANUAL, experiment_id="exp07"):
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        document_id="doc",
        document_title="Doc",
        tier=tier,
        source_version="v1",
        page=1,
        experiment_id=experiment_id,
    )


# --- fingerprint / naming ---------------------------------------------------


async def test_fingerprint_is_stable_and_scope_model_location_sensitive():
    a, b = _request(), _request()
    fp = a.fingerprint(model=MODEL, location=LOCATION)
    assert fp == b.fingerprint(model=MODEL, location=LOCATION)
    assert fp != a.fingerprint(model="gemini-2.5-pro", location=LOCATION)
    assert fp != a.fingerprint(model=MODEL, location="us-central1")
    assert fp != _request(scope="exp08").fingerprint(model=MODEL, location=LOCATION)
    assert POLICY_VERSION  # part of the hash; bumping it re-versions every cache


async def test_dynamic_part_never_changes_the_fingerprint():
    one = _request("What is HOMO?").fingerprint(model=MODEL, location=LOCATION)
    two = _request("a completely different question").fingerprint(model=MODEL, location=LOCATION)
    assert one == two


async def test_cache_name_is_deterministic_and_scoped():
    fp = _request().fingerprint(model=MODEL, location=LOCATION)
    assert cache_display_name("exp07", fp) == f"labtutor-exp07-{fp[:16]}"
    assert cache_display_name("exp07", fp) != cache_display_name("exp08", fp)


async def test_stable_prefix_is_byte_identical_across_questions():
    a, b = _request("first question"), _request("second, unrelated question")
    assert a.context_text == b.context_text and a.system == b.system
    assert a.inline_user.startswith(a.context_text)
    assert a.inline_user.endswith(a.dynamic_user)


# --- versioning: editing the source ----------------------------------------


async def test_editing_a_source_passage_selects_a_new_cache_automatically(fake_client):
    manager = _manager(fake_client)
    old = SimpleNamespace(chunks=[_chunk("c1", "The manual says do X.")])
    new = SimpleNamespace(chunks=[_chunk("c1", "The manual says do Y.")])

    req_old = build_cache_request("exp07", index=old, system="SYS")
    req_new = build_cache_request("exp07", index=new, system="SYS")
    assert manager.fingerprint(req_old) != manager.fingerprint(req_new)

    await manager.ensure(req_old)
    assert fake_client.aio.caches.created == 1
    old_name = cache_display_name("exp07", manager.fingerprint(req_old))

    # Same store, edited manual: the old cache is not selected; a new one is made.
    assert await manager.resolve(req_new) is None
    await _settle()
    assert fake_client.aio.caches.created == 2
    new_name = cache_display_name("exp07", manager.fingerprint(req_new))
    assert new_name != old_name
    assert await manager.resolve(req_new) is not None
    assert {i.display_name for i in fake_client.aio.caches.store} == {old_name, new_name}


async def test_reverting_the_edit_reuses_the_original_cache(fake_client):
    manager = _manager(fake_client)
    original = SimpleNamespace(chunks=[_chunk("c1", "The manual says do X.")])
    await manager.ensure(build_cache_request("exp07", index=original, system="SYS"))
    created_before = fake_client.aio.caches.created

    fresh = _manager(fake_client)  # e.g. another instance / after a restart
    await fresh.ensure(build_cache_request("exp07", index=original, system="SYS"))
    assert fake_client.aio.caches.created == created_before  # found, not recreated


async def test_exp07_context_never_contains_or_selects_exp08_material(fake_client):
    index = SimpleNamespace(
        chunks=[
            _chunk("a", "exp07 procedure", experiment_id="exp07"),
            _chunk("b", "EXP08-ONLY-SECRET conformer text", experiment_id="exp08"),
        ]
    )
    req7 = build_cache_request("exp07", index=index, system="SYS")
    assert "EXP08-ONLY-SECRET" not in req7.context_text
    assert [c.chunk_id for c in experiment_chunks("exp07", index)] == ["a"]

    manager = _manager(fake_client)
    req8 = build_cache_request("exp08", index=index, system="SYS")
    await manager.ensure(req8)
    assert await manager.resolve(req7) is None  # exp08's cache is invisible to exp07
    await _settle()
    assert fake_client.aio.caches.created == 2


# --- lifecycle --------------------------------------------------------------


async def test_twenty_concurrent_students_create_exactly_one_cache(fake_client):
    fake_client.aio.caches.create_delay = 0.01
    manager = _manager(fake_client)
    results = await asyncio.gather(*[manager.resolve(_request(f"q{i}")) for i in range(20)])
    assert all(r is None for r in results)  # none of them waited for the create
    await asyncio.sleep(0.05)
    assert fake_client.aio.caches.created == 1
    assert await manager.resolve(_request()) is not None


async def test_two_instances_racing_converge_on_the_oldest_cache(fake_client):
    fp = _request().fingerprint(model=MODEL, location=LOCATION)
    name = cache_display_name("exp07", fp)
    older = fake_client.aio.caches.add(name, age_seconds=30)
    fake_client.aio.caches.add(name, age_seconds=1)

    chosen = await _manager(fake_client).ensure(_request())
    assert chosen == older.name
    assert fake_client.aio.caches.created == 0  # nothing new was made


async def test_a_losing_duplicate_is_deleted_by_the_instance_that_made_it(fake_client):
    fp = _request().fingerprint(model=MODEL, location=LOCATION)
    name = cache_display_name("exp07", fp)
    real_create = fake_client.aio.caches.create

    async def create_while_older_appears(*, model, config):
        # Another instance's (older) cache lands while ours is being created.
        fake_client.aio.caches.add(name, age_seconds=60)
        return await real_create(model=model, config=config)

    fake_client.aio.caches.create = create_while_older_appears
    chosen = await _manager(fake_client).ensure(_request())
    survivors = [i.name for i in fake_client.aio.caches.store]
    assert survivors == [chosen]
    assert len(fake_client.aio.caches.deleted) == 1


async def test_creation_failure_serves_uncached_without_raising_or_hammering(fake_client):
    fake_client.aio.caches.fail_create = True
    manager = _manager(fake_client)
    assert await manager.resolve(_request()) is None
    await _settle()
    lists_after_first = manager.lists
    assert await manager.resolve(_request()) is None  # inside the backoff window
    await _settle()
    assert manager.lists == lists_after_first  # no second attempt
    assert fake_client.aio.caches.store == []


async def test_ttl_is_renewed_on_use_when_half_spent(fake_client):
    manager = _manager(fake_client, ttl=10800)
    await manager.ensure(_request())
    entry = next(iter(manager._entries.values()))
    entry.expire_at = time.time() + 1000  # well under half of the TTL
    assert await manager.resolve(_request()) == entry.name
    await _settle()
    assert fake_client.aio.caches.updated == [entry.name]


async def test_expired_cache_is_forgotten_and_recreated(fake_client):
    manager = _manager(fake_client)
    await manager.ensure(_request())
    entry = next(iter(manager._entries.values()))
    entry.expire_at = time.time() - 5
    fake_client.aio.caches.store.clear()  # the server dropped it too
    assert await manager.resolve(_request()) is None
    await _settle()
    assert await manager.resolve(_request()) is not None


# --- request path through VertexBackend ------------------------------------


async def test_cache_hit_sends_only_the_dynamic_part_and_costs_one_call(fake_client, cache_on):
    backend = VertexBackend(Settings())
    await backend.cache_manager.ensure(_request())
    stats = telemetry.begin_request()

    req = _request("What is HOMO?")
    reply = await backend.complete(system=req.system, user=req.inline_user, cache=req)
    call = fake_client.aio.models.calls[-1]
    assert call["contents"] == req.dynamic_user  # nothing stable is re-sent
    assert call["config"].cached_content
    assert not call["config"].system_instruction  # lives inside the cache
    assert stats.calls == 1 and stats.attempts == 1
    assert stats.cache_hit is True and stats.cache_ref
    assert stats.cached_tokens == 6500 and stats.prompt_tokens == 6900
    assert reply.text == "an answer"


async def test_cache_miss_sends_the_full_inline_prompt_and_still_one_call(fake_client, cache_on):
    backend = VertexBackend(Settings())
    stats = telemetry.begin_request()
    req = _request()
    await backend.complete(system=req.system, user=req.inline_user, cache=req)
    call = fake_client.aio.models.calls[-1]
    assert call["contents"] == req.inline_user
    assert call["config"].system_instruction == req.system
    assert not call["config"].cached_content
    assert stats.calls == 1 and stats.cache_hit is False


async def test_cache_gone_on_server_retries_the_same_generation_uncached(fake_client, cache_on):
    backend = VertexBackend(Settings())
    await backend.cache_manager.ensure(_request())
    fake_client.aio.models.outcomes = [
        genai_errors.APIError(
            code=404,
            response_json={"error": {"message": "cached content expired", "status": "NOT_FOUND"}},
        )
    ]
    stats = telemetry.begin_request()
    req = _request()
    reply = await backend.complete(system=req.system, user=req.inline_user, cache=req)
    first, second = fake_client.aio.models.calls[-2:]
    assert first["config"].cached_content and not second["config"].cached_content
    assert second["contents"] == req.inline_user
    assert reply.text == "an answer"
    assert stats.calls == 1 and stats.attempts == 2  # one generation, one retry
    assert stats.cache_hit is False


async def test_cache_disabled_makes_no_cache_calls_at_all(fake_client, monkeypatch):
    monkeypatch.delenv("LABTUTOR_LLM_CONTEXT_CACHE", raising=False)
    reload_settings()
    backend = VertexBackend(Settings(_env_file=None))
    assert backend.cache_manager is None and backend.supports_context_cache is False
    req = _request()
    await backend.complete(system=req.system, user=req.inline_user, cache=req)
    assert fake_client.aio.caches.created == 0 and fake_client.aio.caches.store == []


async def test_no_student_text_ever_reaches_the_cache(fake_client, cache_on):
    backend = VertexBackend(Settings())
    secret_question = "my reg no is 24BCE0001 and my answer is 42"
    req = _request(secret_question)
    await backend.complete(system=req.system, user=req.inline_user, cache=req)
    await asyncio.sleep(0.01)
    created = fake_client.aio.caches.create_configs
    assert created, "a cache should have been created in the background"
    payload = repr(created[0])
    assert "24BCE0001" not in payload and secret_question not in payload


# --- pipeline wiring --------------------------------------------------------


class _CachingFake:
    """A backend that advertises native caching and records what it is sent."""

    name = "fake"
    supports_context_cache = True

    def __init__(self):
        self.calls: list[dict] = []

    async def complete(self, *, system, user, max_tokens=None, temperature=None, cache=None):
        from backend.llm.client import LLMReply

        telemetry.record_call()
        self.calls.append({"system": system, "user": user, "cache": cache})
        return LLMReply(text="an answer", backend="fake", model="m")


async def test_exp07_answer_is_split_into_stable_and_dynamic_halves(monkeypatch):
    from backend.retrieval.pipeline import answer_question

    fake = _CachingFake()
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake)
    await answer_question("What is HOMO?", active_experiment="exp07")
    await answer_question("Which basis set should I pick for methane?", active_experiment="exp07")

    first, second = fake.calls
    assert first["cache"].scope == "exp07" and second["cache"].scope == "exp07"
    # identical stable half regardless of the question -> one cache serves everyone
    assert first["cache"].context_text == second["cache"].context_text
    assert first["cache"].system == second["cache"].system
    # the question lives only in the dynamic half
    assert "What is HOMO?" in first["cache"].dynamic_user
    assert "What is HOMO?" not in first["cache"].context_text
    # and the uncached fallback prompt is that same text, stable half first
    assert first["user"] == first["cache"].inline_user
    assert first["user"].startswith(first["cache"].context_text)
    # a whole-experiment block: official procedure and background both present
    assert "lab manual" in first["cache"].context_text
    assert "background explainer, not the manual" in first["cache"].context_text


async def test_other_experiments_never_get_a_cache_request(monkeypatch):
    from backend.retrieval.pipeline import answer_question

    fake = _CachingFake()
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake)
    await answer_question("What is the Nernst equation?", active_experiment="exp01")
    assert fake.calls and all(c["cache"] is None for c in fake.calls)


async def test_a_backend_without_cache_support_is_called_without_the_cache_argument(monkeypatch):
    from backend.llm.client import LLMReply
    from backend.retrieval.pipeline import answer_question

    seen = {}

    class _Plain:
        name = "plain"

        async def complete(self, *, system, user, max_tokens=None):  # no `cache` parameter
            telemetry.record_call()
            seen["user"] = user
            return LLMReply(text="ok", backend="plain", model="m")

    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: _Plain())
    await answer_question("What is HOMO?", active_experiment="exp07")
    assert "RETRIEVED PASSAGES" in seen["user"] and "What is HOMO?" in seen["user"]
