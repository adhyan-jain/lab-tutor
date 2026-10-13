"""Vague openers: "I don't know what to ask", bare "what is this?" (deterministic)."""
from backend.retrieval import pipeline
from backend.rag.language import looks_non_english
from backend.socratic_engine import conversation as conv
from backend.socratic_engine.suggestions import starter_questions

import pytest


@pytest.mark.parametrize("t", [
    "I don't know what to ask", "not sure where to start", "what should I ask?",
    "where do I begin", "no idea what to ask you",
])
def test_lost_detected(t):
    assert conv.is_lost(t)


@pytest.mark.parametrize("t", [
    "What is a basis set?", "I don't know the HOMO value", "explain geometry optimisation",
    "why is the LUMO higher than the HOMO in this molecule given the optimisation result shown here",
])
def test_lost_not_over_matched(t):
    assert not conv.is_lost(t)


@pytest.mark.parametrize("t", ["what is this?", "Explain this", "why?", "what does this mean", "what's this"])
def test_bare_referent(t):
    assert conv.is_bare_referent(t)


@pytest.mark.parametrize("t", ["what is HOMO?", "why does the energy drop", "explain this basis set"])
def test_referent_not_over_matched(t):
    assert not conv.is_bare_referent(t)


def test_lost_text_english_and_rotates():
    texts = {conv.lost_text("Exp 7", attempt=i) for i in range(3)}
    assert len(texts) == 3
    assert not any(looks_non_english(x) for x in texts)
    assert not looks_non_english(conv.referent_clarify_text())


def test_referent_line_only_with_tutor_context():
    assert "REFERENT" in pipeline.REFERENT
    assert starter_questions("exp07")


# ---- end to end (scripted model: no network) --------------------------------
from backend.tests.test_chat_isolation import _setup, auth  # noqa: F401,E402
from backend.tests.test_student_feedback import ENGLISH, scripted  # noqa: F401,E402
from backend.tests.test_walkthrough_api import _send  # noqa: E402


async def test_lost_student_gets_starters_and_no_model_call(client, make_user, scripted):
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "vg-lost")
    out = await _send(client, token, classroom_id, "I don't know what to ask")
    meta = out["message"]["metadata"]
    assert meta["transition_reason"] == "vague opener"
    assert meta["ui"]["chips"] and set(meta["ui"]["chips"]) <= set(starter_questions("exp07"))
    assert not looks_non_english(out["message"]["content"])


async def test_bare_what_is_this_in_a_new_chat_asks_once_with_chips(client, make_user, scripted):
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "vg-ref")
    out = await _send(client, token, classroom_id, "what is this?")
    assert out["message"]["metadata"]["transition_reason"] == "vague opener"
    assert out["message"]["metadata"]["ui"]["chips"]


async def test_asked_starter_is_not_offered_again(client, make_user, scripted):
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "vg-dedup")
    first = starter_questions("exp07")[0]
    out = await _send(client, token, classroom_id, first)
    tid = out["thread_id"]
    out = await _send(client, token, classroom_id, "where do I start", thread_id=tid)
    assert first not in out["message"]["metadata"]["ui"]["chips"]
