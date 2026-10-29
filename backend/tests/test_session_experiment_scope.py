"""A class session is tied to one experiment, and the tutor stays on it.

Next-class setup: faculty starts a session for Exp 2 (or Exp 4). A student in
that session who names, or decisively asks about, the other experiment is told
what this session covers instead of being answered from the other experiment's
material. Shared vocabulary ("titration", "endpoint") must not trigger it.
"""

from __future__ import annotations

import pytest

from backend.retrieval.pipeline import answer_question
from backend.scope.statuses import AnswerStatus


async def _ask(message: str, active: str):
    return await answer_question(message, active_experiment=active, use_llm=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active, message",
    [
        ("exp02", "can we do experiment 4 instead"),
        ("exp02", "how do i find iron in steel using permanganate"),
        ("exp04", "can we do experiment 2 instead"),
        ("exp04", "explain ester hydrolysis rate constant"),
    ],
)
async def test_other_experiment_is_redirected_not_answered(active, message):
    result = await _ask(message, active)
    assert result.status is AnswerStatus.OUT_OF_SCOPE
    label = "Experiment " + active[-1]
    assert f"This session is for {label}" in result.text
    assert not result.citations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active, message",
    [
        ("exp02", "how do i calculate the rate constant"),
        ("exp02", "what is the infinity reading"),
        ("exp04", "how do i find the endpoint from the delta E delta V plot"),
        # Shared titration vocabulary alone never claims another experiment.
        ("exp02", "what is the endpoint of this titration"),
        ("exp04", "what is normality"),
    ],
)
async def test_own_and_shared_vocabulary_stays_in_the_session(active, message):
    result = await _ask(message, active)
    assert "This session is for" not in result.text
    assert result.status is not AnswerStatus.OUT_OF_SCOPE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "why does the emf curve look like an S",
        "why does permanganate act as its own indicator",
        "why do we use a reference electrode",
    ],
)
async def test_exp04_theory_questions_are_answered_from_its_notes(message):
    result = await _ask(message, "exp04")
    assert result.status in (AnswerStatus.ADJACENT_SUPPORTED, AnswerStatus.IN_SCOPE_SUPPORTED)
    assert result.citations
