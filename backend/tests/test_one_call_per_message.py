"""A student message costs at most one model generation.

Drives the real `/api/chat/messages` endpoint with a counting fake backend
(installed everywhere `get_backend` is imported, including the retrieval
pipeline) and asserts on the per-message `llm_calls` metadata and on the
number of backend calls actually made.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.auth import session as session_cookie
from backend.config import Settings, reload_settings

pytestmark = pytest.mark.asyncio

ANSWER = "HOMO is the highest occupied molecular orbital."


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


@pytest.fixture
def counting_llm(fake_llm, monkeypatch):
    fake_llm.reply = ANSWER
    # The pipeline imports get_backend by name; `fake_llm` does not patch it.
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    # A developer's local .env may switch the router on; the shipped default
    # is off, and that default is what these tests pin.
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


async def _joined_student(client, make_user, experiment_id: str, tag: str):
    _, prof = await make_user(f"prof.{tag}@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "C"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    code = created.json()["student_join_code"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": experiment_id},
        headers=auth(prof),
    )
    assert started.status_code == 201
    _, student = await make_user(f"student.{tag}@vitstudent.ac.in")
    await client.post("/api/classrooms/join", json={"join_code": code}, headers=auth(student))
    return classroom_id, student


async def _send(client, student, classroom_id, experiment_id, message):
    resp = await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": experiment_id, "message": message},
        headers=auth(student),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["message"]["metadata"]


async def test_router_is_off_by_default(monkeypatch):
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    assert Settings(_env_file=None).router_enabled is False


async def test_exp07_question_is_exactly_one_generation(client, make_user, counting_llm):
    classroom_id, student = await _joined_student(client, make_user, "exp07", "a")
    meta = await _send(client, student, classroom_id, "exp07", "What is HOMO?")
    assert meta["llm_calls"] == 1
    assert len(counting_llm.calls) == 1
    assert meta["fallback_used"] is False


async def test_exp07_vague_followup_is_still_one_generation(client, make_user, counting_llm):
    classroom_id, student = await _joined_student(client, make_user, "exp07", "b")
    await _send(client, student, classroom_id, "exp07", "What is HOMO?")
    counting_llm.calls.clear()
    meta = await _send(client, student, classroom_id, "exp07", "give me some def atleast")
    assert meta["llm_calls"] == 1
    assert len(counting_llm.calls) == 1


async def test_outage_is_one_attempt_then_observable_extractive_fallback(
    client, make_user, counting_llm
):
    counting_llm.available = False
    classroom_id, student = await _joined_student(client, make_user, "exp07", "c")
    meta = await _send(client, student, classroom_id, "exp07", "What is HOMO?")
    assert meta["llm_calls"] == 1  # no second generation to "rescue" the first
    assert len(counting_llm.calls) == 1
    assert meta["fallback_used"] is True
    assert meta["fallback_reason"] == "llm_unavailable"


async def test_safety_message_uses_zero_generations(client, make_user, counting_llm):
    classroom_id, student = await _joined_student(client, make_user, "exp07", "d")
    meta = await _send(client, student, classroom_id, "exp07", "acid spilled on my arm")
    assert meta.get("llm_calls", 0) == 0
    assert counting_llm.calls == []


async def test_non_qualitative_plain_question_is_at_most_one_generation(
    client, make_user, counting_llm
):
    classroom_id, student = await _joined_student(client, make_user, "exp02", "e")
    meta = await _send(client, student, classroom_id, "exp02", "What is a burette used for?")
    assert meta["llm_calls"] <= 1
    assert len(counting_llm.calls) <= 1


async def test_socratic_guidance_turn_is_at_most_one_generation(client, make_user, counting_llm):
    classroom_id, student = await _joined_student(client, make_user, "exp02", "f")
    meta = await _send(client, student, classroom_id, "exp02", "guide me through this experiment")
    assert meta["llm_calls"] <= 1
    assert len(counting_llm.calls) <= 1


async def test_socratic_failure_degrades_to_template_not_a_second_call(
    client, make_user, counting_llm
):
    counting_llm.available = False
    classroom_id, student = await _joined_student(client, make_user, "exp02", "g")
    meta = await _send(client, student, classroom_id, "exp02", "guide me through this experiment")
    assert meta["llm_calls"] <= 1
    assert len(counting_llm.calls) <= 1


async def test_meta_commentary_rejection_does_not_trigger_a_second_call(
    client, make_user, counting_llm
):
    counting_llm.reply = "The user is asking me to provide a hint for the current step."
    classroom_id, student = await _joined_student(client, make_user, "exp02", "h")
    meta = await _send(client, student, classroom_id, "exp02", "what's the next step")
    assert meta["llm_calls"] <= 1
    assert len(counting_llm.calls) <= 1


async def test_numeric_diagnostic_is_at_most_one_generation(client, make_user, counting_llm):
    classroom_id, student = await _joined_student(client, make_user, "exp07", "i")
    meta = await _send(
        client,
        student,
        classroom_id,
        "exp07",
        "energy_before: -40.5, energy_after: -40.52, homo_energy: -0.25, lumo_energy: 0.05",
    )
    assert meta["llm_calls"] <= 1
    assert len(counting_llm.calls) <= 1


async def test_concurrent_students_each_cost_one_generation(client, make_user, counting_llm):
    setups = [await _joined_student(client, make_user, "exp07", f"z{i}") for i in range(6)]
    results = await asyncio.gather(
        *[_send(client, s, cid, "exp07", "What is HOMO?") for cid, s in setups]
    )
    assert all(m["llm_calls"] == 1 for m in results)
    assert len(counting_llm.calls) == len(setups)  # exactly one each, nothing multiplied
