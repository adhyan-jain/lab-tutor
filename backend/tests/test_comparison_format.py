"""Comparison questions get a mobile-friendly structured answer.

Regression for Exp7 manual testing: "How is HOMO different from LUMO" got one
dense paragraph. Two causes: nothing in the prompt asked for structure, and the
phone-only guard (`theory.guard_answer`) rejoined every kept sentence with
spaces, flattening any structure the model did produce. Comparison intent is
detected in code and adds one FORMAT line to the per-message prompt only.
"""

from __future__ import annotations

import pytest

from backend.rag.phrasing import ENGLISH_ONLY_RULE
from backend.retrieval import pipeline
from backend.retrieval.pipeline import (
    COMPARISON_FORMAT,
    OVERVIEW_FOCUS,
    answer_question,
    is_comparison_request,
)
from backend.socratic_engine import theory
from backend.tests.test_chat_isolation import _setup, auth  # noqa: F401
from backend.tests.test_english_only import _RecordingBackend
from backend.tests.test_theory_first import llm  # noqa: F401
from backend.tests.test_walkthrough_api import _send

COMPARISON = [
    "How is HOMO different from LUMO?",
    "Compare HOMO and LUMO.",
    "What's the difference between HOMO and LUMO?",
    "HOMO vs LUMO?",
    "How do HOMO and LUMO differ?",
    "What is the difference between B3LYP and B3P?",
    "Compare B3LYP and B3P.",
    "Compare 6-31G and 6-31G*.",
    "How are these two basis sets different?",
    "bhai HOMO aur LUMO me kya difference hai",
    "And how is it different from LUMO?",
]
NOT_COMPARISON = [
    "What is HOMO?",
    "Explain HOMO in detail.",
    "Why is HOMO important?",
    "Walk me through the Experiment 7 procedure.",
    "Explain the concepts involved in this experiment before I start.",
    "Why do different methods give different values?",
]


@pytest.fixture
def backend(monkeypatch):
    fake = _RecordingBackend()
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake)
    return fake


@pytest.mark.parametrize("message", COMPARISON)
def test_comparison_questions_are_detected(message):
    assert is_comparison_request(message)


@pytest.mark.parametrize("message", NOT_COMPARISON)
def test_other_questions_are_not_comparisons(message):
    assert not is_comparison_request(message)


def test_format_is_mobile_first_and_lives_only_in_the_per_message_prompt():
    assert "COMPARISON" not in pipeline.SYSTEM_PROMPT and "FORMAT:" not in pipeline.SYSTEM_PROMPT
    for phrase in ("labelled section", "**In short:**", "No table unless", "Use only facts from the material"):
        assert phrase in COMPARISON_FORMAT
    assert "words" not in COMPARISON_FORMAT.split("No table")[0]  # no word limit


@pytest.mark.asyncio
@pytest.mark.parametrize("message", COMPARISON[:8] + ["bhai HOMO aur LUMO me kya difference hai"])
async def test_comparison_prompt_asks_for_structure_and_stays_grounded_and_english(backend, message):
    result = await answer_question(message, active_experiment="exp07")
    call = backend.calls[-1]
    assert COMPARISON_FORMAT in call["user"]
    assert OVERVIEW_FOCUS not in call["user"]
    assert result.citations
    assert ENGLISH_ONLY_RULE in call["system"]
    assert "REPLY LANGUAGE: English only" in call["user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("message", NOT_COMPARISON)
async def test_non_comparisons_get_no_format_line(backend, message):
    await answer_question(message, active_experiment="exp07")
    for call in backend.calls:
        assert COMPARISON_FORMAT not in call["user"]


@pytest.mark.asyncio
async def test_overview_still_gets_the_overview_focus(backend):
    await answer_question(NOT_COMPARISON[4], active_experiment="exp07")
    assert OVERVIEW_FOCUS in backend.calls[-1]["user"]


@pytest.mark.asyncio
async def test_followup_comparison_gets_the_format(backend):
    # Detected from the follow-up's own wording. (Exp7 sends no history for a
    # message of FOLLOWUP_MAX_WORDS or fewer; that is existing behaviour and
    # test_student_text_stays_out_of_every_model_prompt depends on it.)
    history = "STUDENT: What is HOMO?\nTUTOR: The HOMO is the highest occupied molecular orbital."
    await answer_question(
        "And how is it different from LUMO?", active_experiment="exp07", conversation_history=history
    )
    assert COMPARISON_FORMAT in backend.calls[-1]["user"]


STRUCTURED = (
    "**HOMO — Highest Occupied Molecular Orbital**\n"
    "The HOMO is the highest-energy orbital that still holds electrons.\n\n"
    "**LUMO — Lowest Unoccupied Molecular Orbital**\n"
    "- The LUMO is the lowest-energy orbital with no electrons in it.\n"
    "- Open Avogadro and look at your screen to see it.\n\n"
    "**In short:** the HOMO holds the outermost electrons and the LUMO is the first empty level."
)


def test_phone_guard_drops_software_sentences_but_keeps_the_structure():
    out = theory.guard_answer(STRUCTURED, "How is HOMO different from LUMO?")
    assert "Avogadro" not in out and "screen" not in out
    assert "**HOMO — Highest Occupied Molecular Orbital**\nThe HOMO is" in out
    assert "\n- The LUMO is the lowest-energy orbital" in out
    assert "\n\n**In short:**" in out


def test_phone_guard_leaves_a_clean_structured_answer_untouched():
    clean = STRUCTURED.replace("- Open Avogadro and look at your screen to see it.\n", "")
    assert theory.guard_answer(clean, "Compare HOMO and LUMO.") == clean


@pytest.mark.asyncio
async def test_structured_comparison_survives_the_chat_api(client, make_user, llm):  # noqa: F811
    llm.reply = STRUCTURED
    classroom_id, _, token = await _setup(client, make_user, "cmp-api")
    out = await _send(client, token, classroom_id, "How is HOMO different from LUMO?")
    content = out["message"]["content"]
    assert COMPARISON_FORMAT in llm.calls[-1]["user"]
    assert "**HOMO — Highest Occupied Molecular Orbital**\n" in content
    assert "\n- The LUMO is the lowest-energy orbital" in content
    assert "Avogadro" not in content
