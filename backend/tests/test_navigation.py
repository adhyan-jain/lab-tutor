"""Step navigation: "next", "back", "repeat" and "go to step N".

Regression tests for three bugs seen with real students:

1. On step X, "next" produced unrelated output: it was graded as an answer
   (and phrased by the model) or answered by the Q&A path.
2. A question about a step, then "next step", landed on step 1.
3. "Go to step 5" from step 1 went to step 2: the free-text key accepted the
   words as an answer and advanced one step.

Navigation is parsed deterministically before anything grades the message or
calls a model, in every place a student can be: the software walkthrough, the
phone-only key-ideas session, and the phone-only procedure overview.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.config import reload_settings
from backend.models import SocraticSession, WalkthroughProgress
from backend.socratic_engine import procedure
from backend.socratic_engine.walkthrough import concept_session, grader, navigation
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough.exp07_script import LINEAR_STEP_IDS, SCRIPT
from backend.socratic_engine.walkthrough.navigation import Nav
from backend.tests.test_chat_isolation import _setup
from backend.tests.test_walkthrough_api import _send

# ---------------------------------------------------------------- the parser (pure)

COMMANDS = [
    ("next", Nav.NEXT, None),
    ("ok next", Nav.NEXT, None),
    ("Next step", Nav.NEXT, None),
    ("next please", Nav.NEXT, None),
    ("go to the next step", Nav.NEXT, None),
    ("move on", Nav.NEXT, None),
    ("proceed", Nav.NEXT, None),
    ("go to step 5", Nav.GOTO, 5),
    ("Go to step 5 please", Nav.GOTO, 5),
    ("jump to step 12", Nav.GOTO, 12),
    ("skip to step five", Nav.GOTO, 5),
    ("take me to the fifth step", Nav.GOTO, 5),
    ("step 5", Nav.GOTO, 5),
    ("Step 5?", Nav.GOTO, 5),
    ("5th step", Nav.GOTO, 5),
    ("can we go to step 3", Nav.GOTO, 3),
    ("what is step 3", Nav.GOTO, 3),
    ("explain step 2", Nav.GOTO, 2),
    ("part 4", Nav.GOTO, 4),
    ("back", Nav.BACK, None),
    ("go back", Nav.BACK, None),
    ("previous step", Nav.BACK, None),
    ("repeat", Nav.REPEAT, None),
    ("say that again", Nav.REPEAT, None),
    ("again", Nav.REPEAT, None),
    ("where am i", Nav.REPEAT, None),
]

NOT_COMMANDS = [
    "Back to step",  # the resume chip: show the same question again
    "Continue",
    "what now",
    "the next step is to optimise the geometry",
    "HOMO is at step 3",
    "skip this step",  # a skip, handled by the existing skip path
    "go ahead",
    "what is a basis set?",
    "10",
    "geometry",
]


@pytest.mark.parametrize("text,kind,target", COMMANDS)
def test_navigation_commands_are_recognised(text, kind, target):
    cmd = navigation.parse(text)
    assert cmd is not None and cmd.kind is kind, text
    assert cmd.target == target


@pytest.mark.parametrize("text", NOT_COMMANDS)
def test_sentences_that_merely_mention_next_or_a_step_are_not_commands(text):
    assert navigation.parse(text) is None


def test_navigation_text_is_never_an_answer():
    # Bug 3: step 1's free-text key accepts any words, and step 3 asks for a
    # number -- "go to step 5" satisfied both.
    assert not grader.grade(SCRIPT.step("b1_open").evidence, "go to step 5").attempted
    assert not grader.grade(SCRIPT.step("b3_methane").evidence, "go to step 5").correct
    assert not grader.grade(SCRIPT.step("b3_methane").evidence, "can we jump to step 5 now").attempted


# ---------------------------------------------------------------- software walkthrough (pure)


def _at(step_id: str) -> ctl.WalkState:
    state = ctl.new_state("nav")
    ctl.start(state)
    state.phase = "step"
    state.step_id = step_id
    state.pending = "evidence" if SCRIPT.step(step_id).evidence else "check"
    return state


@pytest.mark.parametrize("text", ["go to step 5", "step 5", "jump to step five", "take me to the fifth step"])
def test_go_to_step_5_from_step_1_lands_on_step_5(text):
    state = _at("b1_open")
    result = ctl.take_turn(state, text)
    assert state.step_id == LINEAR_STEP_IDS[4]
    assert result.events["verdict"] == "goto" and "Step 5 of" in result.reply
    # The steps jumped past are recorded as not checked, never as done.
    assert state.skipped == list(LINEAR_STEP_IDS[:4]) and state.steps_done == 0


def test_go_to_a_step_from_the_opening_guess_question_skips_the_guess():
    state = ctl.new_state("nav")
    ctl.start(state)
    assert state.phase == "hook"
    result = ctl.take_turn(state, "go to step 3")
    assert state.phase == "step" and state.step_id == LINEAR_STEP_IDS[2] and "Step 3 of" in result.reply


def test_go_to_an_unknown_step_stays_put_and_says_how_many_there_are():
    state = _at("b2_draw")
    result = ctl.take_turn(state, "go to step 99")
    assert state.step_id == "b2_draw" and result.events["verdict"] == "goto_out_of_range"
    assert f"There are {len(LINEAR_STEP_IDS)} numbered steps" in result.reply


@pytest.mark.parametrize("text", ["next", "ok next", "next step", "move on", "Next step"])
def test_next_moves_to_the_following_step_with_no_penalty(text):
    state = _at("b2_draw")
    result = ctl.take_turn(state, text)
    assert state.step_id == "b3_methane" and result.events["verdict"] == "next"
    assert "b2_draw" in state.skipped and state.needs_help == [] and not state.tries
    assert result.realise is None  # never a model call


def test_next_after_the_evidence_was_verified_counts_the_step_as_done():
    state = _at("b3_methane")
    ctl.take_turn(state, "5")  # correct atom count: on to the why-question
    assert state.pending == "check"
    ctl.take_turn(state, "next")
    assert state.step_id != "b3_methane" and "b3_methane" in state.completed and "b3_methane" not in state.skipped


def test_a_side_question_then_next_step_carries_on_from_the_same_step():
    # Bug 2, at the controller: the side question leaves the step untouched.
    state = _at("o2_orca_dialog")
    side = ctl.take_turn(state, "Why does ORCA need a charge and multiplicity at all?")
    assert side.reply is None and side.events["verdict"] == "side_question" and state.step_id == "o2_orca_dialog"
    result = ctl.take_turn(state, "next step")
    assert state.step_id == "o3_job_scf" and "Step 7 of" in result.reply


def test_repeat_reshows_the_current_step_and_back_goes_back_one():
    state = _at("b3_methane")
    again = ctl.take_turn(state, "repeat")
    assert state.step_id == "b3_methane" and again.events["verdict"] == "repeat" and "Step 3 of" in again.reply
    back = ctl.take_turn(state, "back")
    assert state.step_id == "b2_draw" and back.events["verdict"] == "back"


def test_repeat_on_a_why_question_does_not_send_the_student_back_to_the_evidence_question():
    state = _at("b3_methane")
    ctl.take_turn(state, "5")
    assert state.pending == "check"
    again = ctl.take_turn(state, "say that again")
    assert state.pending == "check" and "why-question" in again.reply


def test_jumping_back_to_a_finished_step_and_forward_again_does_not_mark_it_skipped():
    state = _at("b3_methane")
    ctl.take_turn(state, "5")
    ctl.take_turn(state, "next")  # b3 verified
    ctl.take_turn(state, "go to step 1")
    ctl.take_turn(state, "go to step 5")
    assert "b3_methane" not in state.skipped and "b1_open" in state.skipped


def test_a_finished_walkthrough_can_still_be_revisited_by_step_number():
    state = _at(LINEAR_STEP_IDS[0])
    state.status, state.phase = "done", "done"
    assert ctl.take_turn(state, "next").reply is None  # nothing after the end
    result = ctl.take_turn(state, "go to step 4")
    assert state.status == "active" and state.step_id == LINEAR_STEP_IDS[3] and "Step 4 of" in result.reply


# ---------------------------------------------------------------- phone-only key-ideas session (pure)


def _key_ideas() -> ctl.WalkState:
    state = ctl.new_state("nav", mode="concept")
    concept_session.start(state)
    return state


def test_next_in_the_key_ideas_skips_the_question_without_grading_or_a_model_call():
    # Bug 1, phone-only: "next" was graded UNCLEAR (a recorded miss) and phrased
    # by the model.
    state = _key_ideas()
    qid = state.concept["question_id"]
    result = ctl.take_turn(state, "next")
    assert result.events["verdict"] == "concept_skipped" and result.realise is None
    assert qid not in str(state.concepts.get("records", {}))  # nothing recorded against it


@pytest.mark.parametrize("text", ["go to step 4", "part 4", "jump to part four"])
def test_go_to_a_part_in_the_key_ideas(text):
    state = _key_ideas()
    result = ctl.take_turn(state, text)
    assert state.stage == 3 and "Part 4 of 6" in result.reply


def test_next_part_back_and_out_of_range_in_the_key_ideas():
    state = _key_ideas()
    ctl.take_turn(state, "next part")
    assert state.stage == 1
    ctl.take_turn(state, "back")
    assert state.stage == 0
    out = ctl.take_turn(state, "part 9")
    assert state.stage == 0 and "There are 6 parts" in out.reply


# ---------------------------------------------------------------- the procedure overview stepper (pure)


def test_the_overview_stepper_walks_its_stages():
    pos, text, chips = procedure.navigate(0, navigation.parse("next"))
    assert pos == 1 and "Stage 1 of 6" in text and "next_step" in chips
    pos, text, _ = procedure.navigate(pos, navigation.parse("step 5"))
    assert pos == 5 and "Stage 5 of 6" in text
    pos, text, _ = procedure.navigate(pos, navigation.parse("back"))
    assert pos == 4 and "Stage 4 of 6" in text
    pos, text, _ = procedure.navigate(6, navigation.parse("next"))
    assert pos == 6 and "last stage" in text
    pos, text, _ = procedure.navigate(1, navigation.parse("previous"))
    assert pos == 0 and "How Experiment 7 is normally performed" in text


# ---------------------------------------------------------------- through the real endpoint


def _content(out) -> str:
    return out["message"]["content"]


def _meta(out) -> dict:
    return out["message"]["metadata"]


@pytest.fixture
def software_llm(fake_llm, monkeypatch):
    fake_llm.reply = "Charge and multiplicity tell the program how many electrons there are and how they pair."
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.setenv("LABTUTOR_PHONE_ONLY", "false")
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()


@pytest.fixture
def phone_llm(fake_llm, monkeypatch):
    fake_llm.reply = (
        "A basis set is the collection of mathematical functions used to describe where electrons can be. "
        "A bigger basis set describes them more flexibly."
    )
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


@pytest.mark.asyncio
async def test_api_software_go_to_step_then_a_concept_question_then_next_step(client, make_user, db, software_llm):
    classroom_id, user, token = await _setup(client, make_user, "nav-sw")
    first = await _send(client, token, classroom_id, "How do I start the experiment?")
    thread = first["thread_id"]
    calls = len(software_llm.calls)

    jumped = await _send(client, token, classroom_id, "go to step 5", thread)  # bug 3
    assert "Step 5 of 27" in _content(jumped)

    # Bug 2: a question about the idea behind the step is answered in place...
    side = await _send(client, token, classroom_id, "Can you explain the concept behind this step?", thread)
    assert _meta(side)["type"] == "qa" and "Back to Step 5 of 27" in _content(side)
    # ...and "next step" carries on from step 5, not from step 1.
    nxt = await _send(client, token, classroom_id, "next step", thread)
    assert "Step 6 of 27" in _content(nxt), _content(nxt)
    assert len(software_llm.calls) - calls == 1  # only the side question used the model

    row = (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.thread_id == thread))).one()
    assert row.state["step_id"] == LINEAR_STEP_IDS[5]


@pytest.mark.asyncio
async def test_api_software_step_number_after_pausing_resumes_there_not_at_a_new_step_one(
    client, make_user, db, software_llm
):
    classroom_id, user, token = await _setup(client, make_user, "nav-pause")
    first = await _send(client, token, classroom_id, "How do I start the experiment?")
    thread = first["thread_id"]
    await _send(client, token, classroom_id, "stop the walkthrough", thread)
    out = await _send(client, token, classroom_id, "step 3", thread)
    assert "Step 3 of 27" in _content(out)
    sessions = (await db.scalars(select(SocraticSession).where(SocraticSession.student_id == user.id))).all()
    assert sessions == []  # never the legacy session that restarts at step one


@pytest.mark.asyncio
async def test_api_software_theory_detour_then_next_step_returns_to_the_same_step(
    client, make_user, db, software_llm
):
    classroom_id, user, token = await _setup(client, make_user, "nav-theory")
    first = await _send(client, token, classroom_id, "How do I start the experiment?")
    thread = first["thread_id"]
    await _send(client, token, classroom_id, "go to step 7", thread)
    away = await _send(client, token, classroom_id, "I want to study the theory instead", thread)
    assert _meta(away)["mode"] == "theory"
    calls = len(software_llm.calls)
    back = await _send(client, token, classroom_id, "next step", thread)
    assert "Step 8 of 27" in _content(back), _content(back)
    assert len(software_llm.calls) == calls


@pytest.mark.asyncio
async def test_api_phone_overview_stepper_survives_a_question_in_between(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "nav-phone")
    first = await _send(client, token, classroom_id, "How do I perform Experiment 7?")
    thread = first["thread_id"]
    assert "Next step" in _meta(first)["ui"]["chips"]
    calls = len(phone_llm.calls)

    s1 = await _send(client, token, classroom_id, "next", thread)  # bug 1: never Q&A
    assert "Stage 1 of 6" in _content(s1)
    s2 = await _send(client, token, classroom_id, "Next step", thread)
    assert "Stage 2 of 6" in _content(s2)
    assert len(phone_llm.calls) == calls  # stepping is deterministic

    await _send(client, token, classroom_id, "What is a basis set?", thread)  # a question in between
    s3 = await _send(client, token, classroom_id, "next step", thread)  # bug 2: not stage 1, not Q&A
    assert "Stage 3 of 6" in _content(s3), _content(s3)
    s5 = await _send(client, token, classroom_id, "go to step 5", thread)  # bug 3
    assert "Stage 5 of 6" in _content(s5)
    s4 = await _send(client, token, classroom_id, "back", thread)
    assert "Stage 4 of 6" in _content(s4)


@pytest.mark.asyncio
async def test_api_phone_next_with_nothing_open_is_an_authored_reply_not_a_model_answer(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "nav-nothing")
    first = await _send(client, token, classroom_id, "What is a basis set?")
    # The theory answer may leave a follow-up pending: "next" skips it, ungraded.
    calls = len(phone_llm.calls)
    skipped = await _send(client, token, classroom_id, "next", first["thread_id"])
    assert "Yes." not in _content(skipped) and "Good attempt" not in _content(skipped)
    again = await _send(client, token, classroom_id, "next", first["thread_id"])
    assert "nothing open to step through" in _content(again)
    assert len(phone_llm.calls) == calls


@pytest.mark.asyncio
async def test_api_phone_key_ideas_next_and_go_to_part(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "nav-ideas")
    first = await _send(client, token, classroom_id, "Guide me through the key ideas")
    thread = first["thread_id"]
    calls = len(phone_llm.calls)
    nxt = await _send(client, token, classroom_id, "next", thread)
    assert _meta(nxt)["walkthrough"]["verdict"] == "concept_skipped"
    part = await _send(client, token, classroom_id, "go to step 4", thread)
    assert "Part 4 of 6" in _content(part)
    assert len(phone_llm.calls) == calls  # no grading, no model phrasing
