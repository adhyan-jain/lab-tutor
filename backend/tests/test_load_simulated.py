"""Simulated classroom load through the real API.

WHAT THIS IS: 70 students in one classroom each send a walkthrough message and
then a side question, concurrently, against the real app with SQLite and a fake
model that has a fixed artificial latency. It checks orchestration under
concurrency: no request fails, no turn spends more than one model call, a
background job cannot starve live students, and latency stays near the model's.

WHAT THIS IS NOT: a measurement of OpenAI latency, Postgres connection
behaviour, or the deployed server. Those need `scripts/bench_exp07.py` and
`scripts/load_test_openai.py` against the real stack. Nothing here supports a
claim that 70 students are served in production.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time

import pytest

from backend.llm import client as llm_client
from backend.tests.test_walkthrough_api import (  # noqa: F401
    Chat,
    _classroom,
    _student,
    counting_llm,
)

pytestmark = pytest.mark.asyncio

USERS = int(os.getenv("LOAD_SIM_USERS", "70"))
MODEL_LATENCY_S = 0.05
SIDE_QUESTION = "What is a basis set and why does ORCA need one for this calculation?"


@pytest.fixture
def slow_model(counting_llm):  # noqa: F811
    real = counting_llm.complete

    async def delayed(**kwargs):
        await asyncio.sleep(MODEL_LATENCY_S)
        return await real(**kwargs)

    counting_llm.complete = delayed
    return counting_llm


async def _one_student(client, token, classroom_id):
    chat = Chat(client, token, classroom_id)
    await chat.send("guide me through this experiment")  # zero-call walkthrough turn
    started = time.monotonic()
    out = await chat.send(SIDE_QUESTION)  # exactly one model call
    return (time.monotonic() - started) * 1000, out["message"]["metadata"]


async def test_seventy_concurrent_students_one_call_each_and_no_failures(client, make_user, slow_model):
    classroom_id, code, _ = await _classroom(client, make_user, "load")
    tokens = [(await _student(client, make_user, code, f"s{i}.load@vitstudent.ac.in"))[1] for i in range(USERS)]
    before = len(slow_model.calls)

    results = await asyncio.gather(
        *(_one_student(client, t, classroom_id) for t in tokens), return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, failures[:3]

    latencies = sorted(ms for ms, _ in results)
    metas = [m for _, m in results]
    assert len(slow_model.calls) - before == USERS  # one generation per side question, none extra
    assert all(m.get("llm_calls") == 1 for m in metas)
    assert all(m.get("retry_count", 0) == 0 for m in metas)
    assert not any(m.get("fallback_used") for m in metas)
    p50 = statistics.median(latencies)
    p95 = latencies[int(0.95 * (len(latencies) - 1))]
    print(f"\nsimulated {USERS} users: p50={p50:.0f}ms p95={p95:.0f}ms (model latency {MODEL_LATENCY_S*1000:.0f}ms)")
    # Orchestration overhead (DB, routing, retrieval) must not dwarf the model.
    assert p95 < 15_000


async def test_a_busy_background_job_does_not_slow_live_students(client, make_user, slow_model, monkeypatch):
    monkeypatch.setenv("LABTUTOR_LLM_MAX_CONCURRENCY", "5")
    monkeypatch.setenv("LABTUTOR_LLM_BACKGROUND_CONCURRENCY", "1")
    from backend.config import reload_settings

    reload_settings()
    llm_client.reset_concurrency_limit()
    try:
        classroom_id, code, _ = await _classroom(client, make_user, "bg")
        tokens = [(await _student(client, make_user, code, f"s{i}.bg@vitstudent.ac.in"))[1] for i in range(5)]

        stop = asyncio.Event()

        async def hog_background():
            llm_client.mark_background()
            while not stop.is_set():
                async with llm_client._slot():
                    await asyncio.sleep(0.05)

        hogs = [asyncio.create_task(hog_background()) for _ in range(8)]
        try:
            results = await asyncio.gather(*(_one_student(client, t, classroom_id) for t in tokens))
        finally:
            stop.set()
            await asyncio.gather(*hogs)
        # all five live students got a real model reply while eight background
        # workers fought over the single background slot
        assert all(m.get("llm_calls") == 1 and not m.get("fallback_used") for _, m in results)
    finally:
        monkeypatch.delenv("LABTUTOR_LLM_MAX_CONCURRENCY", raising=False)
        monkeypatch.delenv("LABTUTOR_LLM_BACKGROUND_CONCURRENCY", raising=False)
        reload_settings()
        llm_client.reset_concurrency_limit()
