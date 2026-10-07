"""A broad "explain the concepts before I start" request gets a short overview.

Regression for Exp7 manual testing: that request got a near-complete
restatement of the experiment's material, because the model is handed all of
Exp7's passages (correctly, for grounding) and nothing told it which parts a
broad overview needs. The fix is a code-detected OVERVIEW focus line in the
per-message prompt only; every other question keeps its existing prompt.
Prompt contract and detection are tested, never an exact generated paragraph.
"""

from __future__ import annotations

import pytest

from backend.rag.phrasing import ENGLISH_ONLY_RULE
from backend.retrieval import pipeline
from backend.retrieval.pipeline import OVERVIEW_FOCUS, answer_question, is_overview_request
from backend.tests.test_chat_isolation import _setup, auth  # noqa: F401
from backend.tests.test_english_only import _RecordingBackend
from backend.tests.test_theory_first import llm  # noqa: F401
from backend.tests.test_walkthrough_api import _send

OVERVIEW = [
    "Explain the concepts involved in this experiment before I start.",
    "What concepts should I understand before starting Experiment 7?",
    "Can you give me an overview of the theory behind this experiment?",
    "Teach me the basic concepts before I begin.",
    "exp7 start karne se pehle concepts samjha do",
    "What is this experiment about?",
    "Can you explain the theory behind this experiment first?",
]
NOT_OVERVIEW = [
    "What is HOMO?",
    "Explain HOMO and LUMO in detail and compare them.",
    "Walk me through the complete Experiment 7 procedure.",
    "What is DFT?",
    "Why do we use DFT here?",
    "How do we choose a basis set?",
    "What is geometry optimization?",
    "Explain all the concepts in detail.",
]


@pytest.fixture
def backend(monkeypatch):
    fake = _RecordingBackend()
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake)
    return fake


@pytest.mark.parametrize("message", OVERVIEW)
def test_broad_concept_requests_are_detected(message):
    assert is_overview_request(message)


@pytest.mark.parametrize("message", NOT_OVERVIEW)
def test_specific_detailed_and_procedure_requests_are_not_overviews(message):
    assert not is_overview_request(message)


def test_overview_rule_lives_only_in_the_per_message_focus_not_the_global_prompt():
    assert "OVERVIEW" not in pipeline.SYSTEM_PROMPT
    for phrase in ("supporting evidence, not a checklist", "4 to 6 concepts", "150 to 250 words"):
        assert phrase in OVERVIEW_FOCUS


@pytest.mark.asyncio
@pytest.mark.parametrize("message", OVERVIEW[:5])
async def test_overview_prompt_keeps_full_grounding_but_asks_for_a_synthesis(backend, message):
    result = await answer_question(message, active_experiment="exp07")
    call = backend.calls[-1]
    # The failure mode: far more material than an overview needs is supplied...
    assert len(call["user"]) > 20000
    # ...and the model is told to synthesise it, not restate it.
    assert OVERVIEW_FOCUS in call["user"]
    assert "lead with the official procedure" not in call["user"]
    # Grounding and Fix #1 are untouched.
    assert result.citations
    assert ENGLISH_ONLY_RULE in call["system"]
    assert "REPLY LANGUAGE: English only" in call["user"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["Explain HOMO and LUMO in detail and compare them.", "What is HOMO?"],
)
async def test_detailed_and_specific_questions_keep_their_existing_prompt(backend, message):
    await answer_question(message, active_experiment="exp07")
    assert OVERVIEW_FOCUS not in backend.calls[-1]["user"]


@pytest.mark.asyncio
async def test_a_short_followup_is_never_turned_into_an_overview(backend):
    history = "STUDENT: what is HOMO\nTUTOR: The HOMO is the highest occupied orbital."
    await answer_question("explain more", active_experiment="exp07", conversation_history=history)
    assert OVERVIEW_FOCUS not in backend.calls[-1]["user"]


@pytest.mark.asyncio
async def test_overview_through_the_chat_api_reaches_the_model_with_the_overview_focus(
    client, make_user, llm  # noqa: F811
):
    classroom_id, _, token = await _setup(client, make_user, "overview-api")
    await _send(client, token, classroom_id, OVERVIEW[0])
    assert OVERVIEW_FOCUS in llm.calls[-1]["user"]


@pytest.mark.asyncio
async def test_procedure_request_through_the_chat_api_is_not_an_overview(client, make_user, llm):  # noqa: F811
    classroom_id, _, token = await _setup(client, make_user, "overview-proc")
    await _send(client, token, classroom_id, "Walk me through the complete Experiment 7 procedure.")
    assert all(OVERVIEW_FOCUS not in c["user"] for c in llm.calls)
