"""Short, kind, never-refusing replies for the vague questions phone students ask.

Pure unit tests of the deterministic helpers: no model, no network.
"""

from __future__ import annotations

import pytest

from backend.retrieval.pipeline import _followup_topic, _rephrase_topic
from backend.socratic_engine import conversation


@pytest.mark.parametrize(
    "text",
    [
        "what is this experiment about?",
        "what are we measuring in this experiment?",
        "what is the aim of this experiment",
        "purpose of the lab",
    ],
)
def test_generic_orientation_questions_are_recognised(text):
    assert conversation.is_orientation_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "why do we use so much water compared to the ester?",
        "what is the Nernst equation?",
        "why does the EMF jump at the endpoint?",
    ],
)
def test_real_concept_questions_are_not_orientation(text):
    assert not conversation.is_orientation_request(text)


@pytest.mark.parametrize("text", ["what do I do first in the lab?", "what should we do first", "what's the first step", "how is the practical performed?", "How is this experiment done"])
def test_what_do_i_do_first_opens_the_practical_overview(text):
    assert conversation.is_procedure_request(text)


def test_orientation_text_names_the_experiment_and_offers_questions():
    text = conversation.orientation_text("Iron by potentiometry", "the Nernst equation", ["Q one?", "Q two?"])
    assert "Iron by potentiometry" in text and "the Nernst equation" in text
    assert "- Q one?" in text and "- Q two?" in text


def test_support_fallback_is_kind_and_never_a_refusal():
    text = conversation.support_fallback_text(["Q one?", "Q two?"])
    assert "okay" in text.lower() and "- Q one?" in text
    assert "manual" not in text.lower() and "guess" not in text.lower()


HISTORY = (
    "STUDENT: why do we use so much water compared to the ester?\n"
    "TUTOR: Water is in large excess so its concentration is constant.\n"
    "STUDENT: so what does that mean for the order?\n"
    "TUTOR: Pseudo-first-order."
)


@pytest.mark.parametrize("text", ["can you explain that again more simply?", "i dont understand"])
def test_longer_rephrase_requests_are_followups_about_the_thread(text):
    topic = _rephrase_topic(text, HISTORY)
    assert "order" in topic and "water" not in topic  # only the last question


def test_a_new_concept_question_is_not_treated_as_a_followup():
    assert _followup_topic("what is the Nernst equation and why does it matter here?", HISTORY) == ""


@pytest.mark.parametrize(
    "text",
    ["explain that again", "explain again", "can you repeat that", "once more please", "what do you mean", "still confused"],
)
def test_natural_rephrase_requests_are_recognised(text):
    assert conversation.difficulty_kind(text) in ("repeat", "confused")


def test_ordinary_questions_are_not_rephrase_requests():
    for text in ("what is the rate constant?", "why do we use a blank?", "how do I find the unknown concentration?"):
        assert conversation.difficulty_kind(text) is None


# --- "Show an example" and the next-question ladder (Exp2) ---------------------

from backend.socratic_engine import theory  # noqa: E402


def _exp02_with_waiting_question():
    state = conversation.ConversationState()
    state.mode = conversation.Mode.THEORY.value
    turn = theory.open_followup(state, "why do we plot the log of V infinity minus Vt against time", "exp02")
    assert turn is not None and state.pending
    return state


def test_show_an_example_searches_on_the_waiting_question_not_just_the_concept_name():
    state = _exp02_with_waiting_question()
    query = theory.example_query(state, "Show an example", "exp02")
    assert query and "logarithm" in query.lower() and "example" in query.lower()
    assert state.pending, "the question stays waiting"


def test_a_settled_follow_up_leads_to_the_next_authored_question():
    state = _exp02_with_waiting_question()
    first = state.pending["question_id"]
    turn = theory.handle_pending(state, "it is a straight line because the reaction is first order", "exp02")
    assert turn.events["pedagogy"]["classification"] == "CORRECT" and not state.pending
    nxt = theory.next_followup(state, "exp02", "log_plot")
    assert nxt is not None and state.pending and state.pending["question_id"] != first


def test_no_second_question_is_stacked_on_one_that_is_waiting():
    state = _exp02_with_waiting_question()
    assert theory.next_followup(state, "exp02", "log_plot") is None
