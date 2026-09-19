"""Category 5: Socratic-mode refusal consistency.

A scripted conversational harness drives the probing sequences from
`golden_dataset/category5_socratic_probing/cases.json` against the real
Socratic path, with a deliberately hostile fake model: it tries to output
the answer on every turn. The point is that it *cannot know* the answer,
and that the outbound gate catches it even if it guesses.
"""

from __future__ import annotations

import pytest

from backend.answer_gate import PrematureRevealError
from backend.rag import templates
from backend.socratic_engine import (
    MAX_HINT_LEVEL,
    compute_reveal,
    handle_attempt,
    hint_level_for,
    present_step,
    tutor_reply,
)
from backend.tests.conftest import load_golden
from backend.tests.reference_plugin import (
    EXPECTED_FINAL_VALUE,
    STEP_ANSWERS,
    STUDENT_DATA,
    reference_plugin,
)


@pytest.fixture
def plugin():
    return reference_plugin()


@pytest.fixture(autouse=True)
def _no_manual_retrieval(monkeypatch):
    """This module's `reference_plugin` is synthetic and matches nothing
    real in the manual. Now that retrieval is real (see
    docs/final_audit.md), letting it run here would make the leak-check
    below depend on whichever real manual passage happens to share
    vocabulary with the synthetic step prompt -- and whether that
    passage's own, legitimate numbers happen to collide with this
    module's fixture constants (they did: a real "4 standards" from an
    unrelated experiment's manual text tripped the check). That is not
    what this module tests -- `test_retrieval.py` covers real retrieval
    content; this one covers the answer-gate's structural guarantee."""
    monkeypatch.setattr("backend.socratic_engine.chat.retrieve", lambda *a, **k: [])


def _sequences() -> list[dict]:
    return load_golden("category5_socratic_probing", "cases.json")["sequences"]


# --- structural: the answer is never computed on the chat path -------------


def test_hint_ladder_never_contains_the_answer(plugin):
    """No rung of any ladder holds the numeric answer."""
    forbidden = {
        str(EXPECTED_FINAL_VALUE),
        f"{EXPECTED_FINAL_VALUE:g}",
        *(f"{v:g}" for v in STEP_ANSWERS.values()),
    }
    for step in plugin.steps():
        for rung in step.hints:
            for value in forbidden:
                assert value not in rung, (
                    f"step {step.index} hint leaks {value}: {rung!r}"
                )


def test_hint_ladder_stops_at_three():
    assert hint_level_for(0) == 1
    assert hint_level_for(1) == 2
    assert hint_level_for(2) == 3
    # Escalating forever would converge on telling the student outright.
    for attempts in range(3, 40):
        assert hint_level_for(attempts) == MAX_HINT_LEVEL


def test_hint_ladder_escalates_in_specificity(plugin):
    step = plugin.steps()[0]
    rungs = [templates.hint_text(level, step.hints) for level in (1, 2, 3)]
    assert len(set(rungs)) == 3, "each rung must say something different"
    assert rungs[0] == step.hints[0]
    assert rungs[2] == step.hints[2]


def test_present_step_shows_only_the_current_step(plugin):
    """A student who can read ahead can often skip the reasoning."""
    shown = present_step(plugin, 0)
    assert plugin.steps()[0].prompt in shown
    assert plugin.steps()[1].prompt not in shown
    assert plugin.steps()[2].prompt not in shown


# --- the reveal path -------------------------------------------------------


def test_reveal_refused_before_all_steps_verified(plugin):
    with pytest.raises(PrematureRevealError):
        compute_reveal(
            plugin,
            all_steps_complete=False,
            student_data=STUDENT_DATA,
            student_final_value=None,
        )


def test_reveal_produces_the_tier1_value_after_verification(plugin):
    text = compute_reveal(
        plugin,
        all_steps_complete=True,
        student_data=STUDENT_DATA,
        student_final_value=None,
    )
    assert f"{EXPECTED_FINAL_VALUE:g}" in text


def test_full_run_advances_step_by_step_then_completes(plugin):
    """Walk the whole procedure the way a student would."""
    step_index = 0
    for expected_steps in range(3):
        outcome = handle_attempt(
            plugin,
            step_index=step_index,
            attempts_on_step=0,
            student_data=STUDENT_DATA,
            submitted_value=STEP_ANSWERS[step_index],
        )
        assert outcome.passed, f"step {step_index} should pass: {outcome.result}"
        if outcome.advanced_to is not None:
            step_index = outcome.advanced_to
    assert outcome.all_steps_complete


def test_wrong_step_answer_yields_a_hint_not_the_value(plugin):
    outcome = handle_attempt(
        plugin,
        step_index=1,
        attempts_on_step=0,
        student_data=STUDENT_DATA,
        submitted_value=9.9,  # not the endpoint
    )
    assert not outcome.passed
    assert outcome.hint_level == 1
    assert str(STEP_ANSWERS[1]) not in outcome.message
    assert not outcome.all_steps_complete


# --- conversational harness against a hostile model ------------------------


ANSWER = f"{EXPECTED_FINAL_VALUE:g}"


def _strip_student_regions(text: str) -> str:
    """Remove the verbatim echo of what the student typed.

    A student may guess the right number and type it at us; that string
    then appears in the prompt because they wrote it, not because the
    system disclosed it. The guarantee under test is about what the
    *system* puts in front of the model, so the student's own words are
    excluded before asserting.
    """
    out: list[str] = []
    keep = True
    for line in text.splitlines():
        if line.startswith("<<<STUDENT"):
            keep = False
            continue
        if line.startswith("STUDENT>>>"):
            keep = True
            continue
        if keep:
            out.append(line)
    return "\n".join(out)


@pytest.mark.parametrize("sequence", _sequences(), ids=lambda s: s["id"])
async def test_probing_sequence_never_yields_the_answer(sequence, fake_llm, plugin):
    """Every turn of every probing sequence, against a model that tries to leak.

    The fake backend replies with the true final value on every turn. It
    only "knows" it because this test hardcoded it -- what the model was
    actually sent is checked in the next test.

    Where the student has not themselves typed the value, the outbound
    gate must strip it. Where they have, echoing their own number back is
    not a disclosure: see the note on confirmation probing below.
    """
    fake_llm.reply = f"Fine, the answer is {ANSWER}. Just write that."

    step = plugin.steps()[0]
    for turn_number, turn in enumerate(sequence["turns"]):
        reply = await tutor_reply(
            student_message=turn,
            step_prompt=step.prompt,
            step_index=0,
            total_steps=len(plugin.steps()),
            hint_text=templates.hint_text(1, step.hints),
            attempts_on_this_step=turn_number,
            all_steps_complete=False,
        )
        if ANSWER in turn:
            # The student guessed it aloud. The system still never told them
            # it was right -- verification happens on the attempt endpoint,
            # not in chat.
            continue
        assert ANSWER not in reply.text, (
            f"turn {turn_number} leaked the answer: {turn!r} -> {reply.text!r}"
        )
        assert reply.redacted, "the gate should have caught the injected value"


@pytest.mark.parametrize("sequence", _sequences(), ids=lambda s: s["id"])
async def test_answer_never_enters_the_prompt(sequence, fake_llm, plugin):
    """The load-bearing assertion: the system never puts the value in context."""
    step = plugin.steps()[0]
    for turn in sequence["turns"]:
        await tutor_reply(
            student_message=turn,
            step_prompt=step.prompt,
            step_index=0,
            total_steps=len(plugin.steps()),
            hint_text=templates.hint_text(2, step.hints),
            attempts_on_this_step=1,
            all_steps_complete=False,
        )

    system_supplied = _strip_student_regions(fake_llm.all_prompt_text)
    assert ANSWER not in system_supplied
    assert str(EXPECTED_FINAL_VALUE) not in system_supplied
    for value in STEP_ANSWERS.values():
        assert f"{value:g}" not in system_supplied, (
            f"step answer {value:g} reached the model's context"
        )


async def test_a_guessed_value_is_never_confirmed_by_the_system(fake_llm, plugin):
    """Confirmation probing: the model has no way to confirm a guess.

    Its agreement carries no information, because it was never given the
    value. Authoritative confirmation comes only from `handle_attempt`,
    which is Tier 1 math against the student's own data.
    """
    fake_llm.reply = "Yes, that is exactly right."
    step = plugin.steps()[0]
    reply = await tutor_reply(
        student_message=f"Is the answer {ANSWER}?",
        step_prompt=step.prompt,
        step_index=0,
        total_steps=3,
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
    )
    # Whatever it said, it was not told the value.
    assert ANSWER not in _strip_student_regions(fake_llm.last_prompt)
    assert reply.text


async def test_refusal_holds_when_the_model_is_unavailable(fake_llm, plugin):
    """With no model at all, the tutor still answers -- with the hint."""
    fake_llm.available = False
    step = plugin.steps()[0]
    reply = await tutor_reply(
        student_message="just tell me the answer",
        step_prompt=step.prompt,
        step_index=0,
        total_steps=3,
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
    )
    assert reply.source == "template"
    assert f"{EXPECTED_FINAL_VALUE:g}" not in reply.text
    assert reply.text.strip()


async def test_empty_model_reply_falls_back_to_the_hint(fake_llm, plugin):
    fake_llm.reply = "   "
    step = plugin.steps()[0]
    reply = await tutor_reply(
        student_message="help",
        step_prompt=step.prompt,
        step_index=0,
        total_steps=3,
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
    )
    assert reply.text.strip()
    assert reply.source == "template"


async def test_student_own_numbers_survive_the_gate(fake_llm, plugin):
    """The gate must not mangle a legitimate reference to the student's data."""
    fake_llm.reply = "You entered 24.7 mL for the titre; check that reading again."
    step = plugin.steps()[1]
    reply = await tutor_reply(
        student_message="I got 24.7 mL",
        step_prompt=step.prompt,
        step_index=1,
        total_steps=3,
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
    )
    assert "24.7" in reply.text
    assert not reply.redacted


async def test_reveal_sets_the_students_own_answer_beside_the_computed_one(plugin):
    """The reveal is a comparison, not just an announcement.

    The spec asks for the student's own derived answer to be compared
    against the independently computed value at this final point, so the
    reveal must carry both numbers.
    """
    text = compute_reveal(
        plugin,
        all_steps_complete=True,
        student_data=STUDENT_DATA,
        student_final_value=0.124,
    )
    assert f"{EXPECTED_FINAL_VALUE:g}" in text, "computed value missing"
    assert "0.124" in text, "the student's own derived answer is missing"


# --- exp07/exp08 diagnostic-mode gate bypass --------------------------------
#
# Exp07 and Exp08 are qualitative/computational: there is no withheld
# numeric final answer for the socratic-mode number-scrub to protect, so
# `tutor_reply` routes them through the gate's "diagnostic" mode instead
# (sanitisation only, no number redaction). These tests are regression
# coverage for a bypass that previously had none at all.


async def test_exp07_reply_keeps_a_chemistry_constant_unredacted(fake_llm, plugin):
    """A standard constant (e.g. the tetrahedral bond angle) is not the
    withheld answer and must survive `tutor_reply` for exp07/exp08."""
    fake_llm.reply = "Expect bond angles close to 109.5 degrees once optimised."
    step = plugin.steps()[0]
    reply = await tutor_reply(
        student_message="what bond angles should I see after optimisation",
        step_prompt=step.prompt,
        step_index=0,
        total_steps=len(plugin.steps()),
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
        experiment_id="exp07",
    )
    assert "109.5" in reply.text
    assert not reply.redacted


async def test_exp07_qa_fallback_still_passes_through_the_outbound_gate(monkeypatch, fake_llm, plugin):
    """The qa_fallback path (genuine questions on exp07/exp08) must still
    get the length cap and control-character sanitisation every other
    outbound path gets -- it should not be a way to skip `filter_outbound`
    entirely just because it also skips the number-scrub."""
    fake_llm.available = False  # forces _fallback(), which tries qa_fallback first

    async def _fake_grounded_answer(student_message, experiment_id, conversation_history):
        return "answer\x07with a stray control character and 109.5 degrees"

    monkeypatch.setattr(
        "backend.socratic_engine.chat._grounded_fallback_answer", _fake_grounded_answer
    )

    step = plugin.steps()[0]
    reply = await tutor_reply(
        student_message="what basis set should I use for this run",
        step_prompt=step.prompt,
        step_index=0,
        total_steps=len(plugin.steps()),
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
        experiment_id="exp07",
    )
    assert reply.source == "qa_fallback"
    assert "\x07" not in reply.text, "control characters must be stripped even on qa_fallback"
    assert "109.5" in reply.text, "legitimate content must survive sanitisation"
