"""Fix #4: a new question asked while a reflection ("Think about this: ...")
is pending is answered, not graded -- and the reflection stays pending.

Found in manual testing: with "what do HOMO and LUMO stand for?" pending, the
student typed "Compare B3LYP and B3P." (no wh-word, no "?"), which was graded
as an answer and earned another reflection prompt instead of an answer.

Routing is deterministic (grader.is_new_request): no model decides whether a
message is an answer. Reflection answers keep the existing authored grading
path and never reach the Q&A model; only messages classified as new questions
go to the existing grounded Q&A path.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.config import reload_settings
from backend.models import ChatThread
from backend.socratic_engine import conversation as conv
from backend.socratic_engine import theory
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough import grader
from backend.tests.test_chat_isolation import _setup
from backend.tests.test_walkthrough_api import _send

HOMO_Q = "q_homo_meaning"  # "In your own words, what do HOMO and LUMO stand for, and how do they differ?"

REFLECTION_ANSWERS = [
    "HOMO stands for Highest Occupied Molecular Orbital.",
    "HOMO stands for Highest Occupied Molecular Orbital and LUMO stands for Lowest Unoccupied Molecular Orbital.",
    "HOMO is the highest occupied orbital and LUMO is the lowest unoccupied orbital.",
    "HOMO has electrons while LUMO doesn't.",
    "The HOMO is occupied and the LUMO is empty.",
    "haan HOMO highest occupied molecular orbital hota hai",
    # a tentative answer with a question mark is still an answer
    "HOMO is the highest occupied molecular orbital, right?",
    "is it the highest occupied orbital?",
]

NEW_QUESTIONS = [
    "Compare B3LYP and B3P.",
    "Compare B3LYP and B3P",
    "What is Gabedit?",
    "Why do we optimize the geometry?",
    "What is the difference between 6-31G and 6-31G*?",
    "Can you explain that again?",
    "What does HOMO mean?",
    "Tell me about oxygen.",
    "How does geometry optimization work?",
    "What happens after optimization?",
    "Can you explain B3LYP?",
    "How is HOMO different from LUMO?",
    "bhai B3LYP aur B3P compare kar",
    "mujhe HOMO samjha",
    "HOMO kya hai",
    "And how is it different from LUMO?",
]

CONTROLS = ["Just tell me", "Skip this question", "yes", "no", "okay", "haan", "theek hai"]


def _pending_state() -> conv.ConversationState:
    state = conv.ConversationState(mode=conv.Mode.THEORY.value)
    state.pending = {
        "concept_id": "homo", "question_id": HOMO_Q, "step_id": "theory",
        "when": "theory", "resume": "theory", "card": False,
    }
    return state


# ---------------------------------------------------------------- the detector (pure)


@pytest.mark.parametrize("message", NEW_QUESTIONS)
def test_new_questions_are_detected_with_or_without_a_question_mark(message):
    assert grader.is_new_request(message)


@pytest.mark.parametrize("message", REFLECTION_ANSWERS + CONTROLS)
def test_answers_and_controls_are_not_new_questions(message):
    assert not grader.is_new_request(message)


# ---------------------------------------------------------------- theory follow-up (pure)


@pytest.mark.parametrize("message", REFLECTION_ANSWERS)
def test_a_reflection_answer_is_graded_by_the_existing_path(message):
    state = _pending_state()
    turn = theory.handle_pending(state, message)
    assert turn is not None and turn.events["verdict"].startswith("concept_")
    assert turn.events["pedagogy"]["question_id"] == HOMO_Q


@pytest.mark.parametrize("message", NEW_QUESTIONS)
def test_a_new_question_is_not_graded_and_the_reflection_stays_pending(message):
    state = _pending_state()
    before = dict(state.pending)
    assert theory.handle_pending(state, message) is None  # -> normal Q&A path
    assert state.pending == before  # not deleted, not answered, not skipped
    assert "homo" not in state.concepts.get("records", {})  # no grading evidence recorded


def test_existing_controls_keep_their_behaviour():
    state = _pending_state()
    assert theory.handle_pending(state, "Just tell me").events["verdict"] == "concept_explained"
    assert state.pending is None
    state = _pending_state()
    assert theory.handle_pending(state, "Skip this question").events["verdict"] == "concept_skipped"
    assert state.pending is None
    for word in ("yes", "no", "okay", "haan", "theek hai"):
        state = _pending_state()
        turn = theory.handle_pending(state, word)
        # a bare word is still an (unclear) attempt at the reflection, never a new question
        assert turn is not None and turn.events["verdict"] != "side_question"


def test_the_reflection_is_pointed_back_to_once_not_after_every_message():
    state = _pending_state()
    first = theory.open_followup(state, "Compare B3LYP and B3P.")
    assert first is not None and "Back to my question" in first.reply and "HOMO and LUMO" in first.reply
    assert theory.open_followup(state, "What is Gabedit?") is None
    assert state.pending["question_id"] == HOMO_Q  # never replaced by a second question


def test_a_change_of_direction_still_drops_the_follow_up():
    state = _pending_state()
    assert theory.handle_pending(state, "Guide me through the key ideas") is None
    assert state.pending is None


# ---------------------------------------------------------------- walkthrough concept moments (pure)


def _concept_moment() -> ctl.WalkState:
    state = ctl.new_state("reflection-routing", mode="concept")
    state.status, state.phase = "active", "concept"
    state.concept = {"concept_id": "homo", "question_id": HOMO_Q, "step_id": "p5_homo_lumo", "when": "post"}
    return state


@pytest.mark.parametrize("message", ["Compare B3LYP and B3P.", "bhai B3LYP aur B3P compare kar", "How is HOMO different from LUMO?"])
def test_walkthrough_concept_moment_hands_new_questions_to_qa(message):
    state = _concept_moment()
    r = ctl.take_turn(state, message)
    assert r.reply is None and r.events["verdict"] == "side_question"
    assert state.phase == "concept" and state.concept["question_id"] == HOMO_Q
    assert "Back to my question" in r.resume_line


def test_walkthrough_concept_moment_still_grades_answers():
    state = _concept_moment()
    r = ctl.take_turn(state, "HOMO is the highest occupied orbital and LUMO is the lowest unoccupied orbital.")
    assert r.reply and r.events["verdict"] == "concept_correct"


# ---------------------------------------------------------------- the real chat endpoint


@pytest.fixture
def llm(fake_llm, monkeypatch):
    fake_llm.reply = "B3LYP and B3P are both hybrid functionals that differ in their correlation part."
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


async def _thread_state(db, thread_id: str) -> dict:
    row = (
        await db.scalars(select(ChatThread).where(ChatThread.id == thread_id).execution_options(populate_existing=True))
    ).one()
    return row.state


async def _with_homo_reflection(client, make_user, db, tag):
    """A theory answer about HOMO, with the HOMO/LUMO reflection pending."""
    classroom_id, _, token = await _setup(client, make_user, tag)
    first = await _send(client, token, classroom_id, "What is HOMO?")
    thread = first["thread_id"]
    row = (await db.scalars(select(ChatThread).where(ChatThread.id == thread))).one()
    state = dict(row.state)
    state["pending"] = _pending_state().pending
    row.state = state
    await db.commit()
    return classroom_id, token, thread


@pytest.mark.asyncio
async def test_endpoint_reflection_answer_follows_the_reflection_path_with_no_model_call(client, make_user, db, llm):
    classroom_id, token, thread = await _with_homo_reflection(client, make_user, db, "rr-answer")
    calls = len(llm.calls)
    out = await _send(
        client, token, classroom_id,
        "HOMO stands for Highest Occupied Molecular Orbital and LUMO stands for Lowest Unoccupied Molecular Orbital.",
        thread,
    )
    meta = out["message"]["metadata"]
    assert meta["type"] == "walkthrough" and meta["walkthrough"]["verdict"] == "concept_correct"
    assert len(llm.calls) == calls  # the protected path: authored grading, no model


@pytest.mark.asyncio
async def test_endpoint_new_question_gets_qa_and_the_reflection_is_preserved(client, make_user, db, llm):
    classroom_id, token, thread = await _with_homo_reflection(client, make_user, db, "rr-newq")
    calls = len(llm.calls)
    out = await _send(client, token, classroom_id, "Compare B3LYP and B3P.", thread)
    meta, content = out["message"]["metadata"], out["message"]["content"]
    assert meta["type"] == "qa" and len(llm.calls) - calls == 1  # normal Q&A, one call
    assert "Compare B3LYP and B3P" in llm.calls[-1]["user"]
    assert content.count("Back to my question") == 1
    assert (await _thread_state(db, thread))["pending"]["question_id"] == HOMO_Q

    # A second unrelated question: answered, no repeated reminder, still pending.
    out = await _send(client, token, classroom_id, "What is Gabedit?", thread)
    assert out["message"]["metadata"]["type"] == "qa"
    assert "Back to my question" not in out["message"]["content"]
    assert (await _thread_state(db, thread))["pending"]["question_id"] == HOMO_Q

    # The student can still come back and answer it.
    calls = len(llm.calls)
    back = await _send(client, token, classroom_id, "The HOMO is the highest occupied orbital and the LUMO is the lowest unoccupied one.", thread)
    assert back["message"]["metadata"]["walkthrough"]["verdict"] == "concept_correct"
    assert len(llm.calls) == calls


@pytest.mark.asyncio
async def test_endpoint_hinglish_new_question_is_answered_in_english_path(client, make_user, db, llm):
    classroom_id, token, thread = await _with_homo_reflection(client, make_user, db, "rr-hing")
    out = await _send(client, token, classroom_id, "bhai B3LYP aur B3P compare kar", thread)
    assert out["message"]["metadata"]["type"] == "qa"
    assert "English only" in llm.calls[-1]["user"]  # Fix #1's reply-language rule still applies


@pytest.mark.asyncio
async def test_endpoint_contextual_follow_up_is_routed_to_qa(client, make_user, db, llm):
    """'And how is it different from LUMO?' is a new question and goes to the
    normal Q&A path, never to reflection grading.

    Known limitation, left as is (RAG/prompt assembly is out of scope): for
    Exp7 the Q&A prompt omits the HISTORY block when the message is 7 words or
    fewer (pipeline._generate_answer `show_last`), and its LASTMSG block is only
    emitted for Exp8, so "it" is not resolved from the earlier turn. Nothing is
    widened here to make that work."""
    classroom_id, token, thread = await _with_homo_reflection(client, make_user, db, "rr-ctx")
    out = await _send(client, token, classroom_id, "And how is it different from LUMO?", thread)
    assert out["message"]["metadata"]["type"] == "qa"
    assert "And how is it different from LUMO?" in llm.calls[-1]["user"]
    assert (await _thread_state(db, thread))["pending"]["question_id"] == HOMO_Q


@pytest.mark.asyncio
async def test_endpoint_new_questions_keep_fix2_overview_and_fix3_comparison(client, make_user, db, llm):
    classroom_id, token, thread = await _with_homo_reflection(client, make_user, db, "rr-fix23")
    out = await _send(client, token, classroom_id, "How is HOMO different from LUMO?", thread)
    assert out["message"]["metadata"]["type"] == "qa"
    assert "asking for a comparison" in llm.calls[-1]["user"]  # Fix #3 format
    # "Explain the concepts..." is a change of direction to theory: the existing
    # rule (chat_routes._conversation_turn_phone) drops the pending follow-up,
    # and the message is answered with the Fix #2 overview focus.
    out = await _send(client, token, classroom_id, "Explain the concepts involved in this experiment before I start.", thread)
    assert out["message"]["metadata"]["type"] == "qa"
    assert "short conceptual OVERVIEW" in llm.calls[-1]["user"]
