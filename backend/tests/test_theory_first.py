"""Theory is the default; the practical is explained only on request, and the
student can leave it at any moment. Exp7, phone-only (the default mode).

Mode detection is deterministic: no model call decides theory vs procedure.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from backend.config import reload_settings
from backend.models import ChatThread, WalkthroughProgress
from backend.socratic_engine import conversation as conv
from backend.socratic_engine import theory
from backend.socratic_engine.knowledge.phone_safe import external_dependency
from backend.tests.test_chat_isolation import _messages, _new_thread, _setup, auth  # noqa: F401
from backend.tests.test_walkthrough_api import _send

pytestmark = pytest.mark.asyncio

# What a model would plausibly say for a theory question: prose, no software.
CONCEPTUAL = (
    "Geometry optimization adjusts the positions of the atoms to find the arrangement with the lowest "
    "calculated energy. The structure we first draw is only an approximate guess, so it usually is not "
    "already at that minimum."
)

STEPS_RE = re.compile(r"\bstep\s*\d|^\s*\d+\.\s", re.IGNORECASE | re.MULTILINE)


@pytest.fixture
def llm(fake_llm, monkeypatch):
    fake_llm.reply = CONCEPTUAL
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


def _content(out) -> str:
    return out["message"]["content"]


def _meta(out) -> dict:
    return out["message"]["metadata"]


# ---------------------------------------------------------------- the detectors (pure)

PROCEDURE = [
    "How do I perform Experiment 7?",
    "How do I do this experiment?",
    "Can you walk me through the procedure?",
    "What are the steps for Experiment 7?",
    "How do I use ORCA for this?",
    "Explain the practical procedure.",
    "Walk me through the lab.",
    "How do I actually perform this experiment?",
]
NOT_PROCEDURE = [
    "What is DFT?",
    "Why do we use DFT here?",
    "What is the purpose of geometry optimization?",
    "What is geometry optimization?",
    "What is HOMO?",
    "How do we choose a basis set?",
    "How do I interpret the HOMO?",
    "Help me understand hybridization",
    "Why is geometry optimization necessary?",
]
EXIT = [
    "Forget the steps. Explain why geometry optimization works.",
    "Skip the procedure. What is HOMO?",
    "I only want the theory.",
    "Actually, I only want to understand the theory.",
    "Explain the theory instead.",
    "I don't want the procedure.",
    "Why does this work?",
    "Skip the steps.",
    "Just teach me the concept.",
    "Explain the chemistry behind this.",
]


@pytest.mark.parametrize("text", PROCEDURE)
async def test_explicit_procedure_requests_are_detected(text):
    assert conv.is_procedure_request(text)


@pytest.mark.parametrize("text", NOT_PROCEDURE)
async def test_theory_questions_are_never_procedure_requests(text):
    assert not conv.is_procedure_request(text)
    assert conv.classify(text) is not conv.Intent.SWITCH_TO_PRACTICE


@pytest.mark.parametrize("text", EXIT)
async def test_every_common_way_of_leaving_the_procedure_switches_to_theory(text):
    assert conv.classify(text) is conv.Intent.SWITCH_TO_THEORY
    assert not conv.is_procedure_request(text)


async def test_skipping_one_step_is_still_a_step_skip_not_an_exit():
    assert conv.classify("Skip this step") is conv.Intent.STEP_SKIPPED


@pytest.mark.parametrize(
    "text,real_question",
    [
        ("Forget the steps. Explain why geometry optimization works.", True),
        ("Skip the procedure. What is HOMO?", True),
        ("Explain the concept of HOMO", True),
        ("I only want the theory.", False),
        ("Explain the theory instead.", False),
        ("Just teach me the concept.", False),
    ],
)
async def test_a_switch_message_with_a_real_question_is_answered_not_just_acknowledged(text, real_question):
    assert theory.has_substance(text) is real_question


# ---------------------------------------------------------------- THEORY is the default


@pytest.mark.parametrize("question", ["What is geometry optimization?", "Why do we use DFT?", "What is HOMO?"])
async def test_a_theory_question_gets_a_conceptual_answer_with_no_procedure(client, make_user, db, llm, question):
    classroom_id, user, token = await _setup(client, make_user, f"tf-{abs(hash(question)) % 10000}")
    out = await _send(client, token, classroom_id, question)
    text = _content(out)
    assert _meta(out)["type"] == "qa" and _meta(out)["mode"] == "theory"
    assert not STEPS_RE.search(text)
    assert "Gabedit" not in text and "Avogadro" not in text and "ORCA" not in text
    assert external_dependency(text) is None
    assert "step by step" not in text.lower() and "let's start" not in text.lower()
    assert "Think about this" in text  # still Socratic: one short follow-up question
    assert _meta(out)["llm_calls"] == 1  # exactly one generation: the answer; the follow-up is authored
    assert (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.student_id == user.id))).all() == []


async def test_the_model_prompt_for_a_theory_answer_forbids_procedure_and_screens(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-prompt")
    await _send(client, token, classroom_id, "What is HOMO?")
    prompt = llm.all_prompt_text
    assert "PHONE-ONLY" in prompt and "no computer and no software" in prompt
    assert "Do NOT give numbered or step-by-step software instructions" in prompt


async def test_a_procedural_model_answer_is_stripped_before_the_student_sees_it(client, make_user, llm):
    llm.reply = (
        "Step 1: Open Gabedit and draw the molecule. "
        "The HOMO is the highest occupied molecular orbital, the orbital of highest energy that still holds electrons. "
        "It matters because it is where the most loosely held electrons sit, so it helps explain reactivity. "
        "Look at your screen and click the orbital to see it."
    )
    classroom_id, _, token = await _setup(client, make_user, "tf-guard")
    text = _content(await _send(client, token, classroom_id, "What is HOMO?"))
    answer = text.split("Think about this")[0]
    assert "highest occupied molecular orbital" in answer and "loosely held electrons" in answer
    assert "Gabedit" not in answer and "Step 1" not in answer and "screen" not in answer.lower()


async def test_saying_yes_or_ok_after_a_theory_answer_never_starts_a_procedure(client, make_user, db, llm):
    classroom_id, user, token = await _setup(client, make_user, "tf-yes")
    first = await _send(client, token, classroom_id, "What is HOMO?")
    thread = first["thread_id"]
    for word in ("yes", "ok", "sure", "let's start"):
        out = await _send(client, token, classroom_id, word, thread)
        assert not STEPS_RE.search(_content(out)) and "Gabedit" not in _content(out)
    assert (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.student_id == user.id))).all() == []


async def test_theory_answers_never_offer_the_walkthrough(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-invite")
    out = await _send(client, token, classroom_id, "What is geometry optimization?")
    assert "work through this step by step" not in _content(out)


# ---------------------------------------------------------------- Socratic follow-up (deterministic)


async def test_the_follow_up_is_graded_deterministically_and_updates_concept_state(client, make_user, db, llm):
    classroom_id, user, token = await _setup(client, make_user, "tf-soc")
    first = await _send(client, token, classroom_id, "What is geometry optimization?")
    thread = first["thread_id"]
    calls = len(llm.calls)
    probe = await _send(client, token, classroom_id, "it just makes the molecule look nicer", thread)
    assert len(llm.calls) == calls  # a misconception is handled with zero model calls
    assert "What quantity is the calculation actually trying to make smaller" in _content(probe)
    assert _meta(probe)["walkthrough"]["pedagogy"]["misconception_id"] == "opt_is_cosmetic"
    good = await _send(client, token, classroom_id, "It lowers the energy of the structure, the energy minimum", thread)
    assert "Yes." in _content(good) or "key idea" in _content(good).lower() or "short version" in _content(good).lower()
    row = (await db.scalars(select(ChatThread).where(ChatThread.id == thread).execution_options(populate_existing=True))).one()
    assert row.state["concepts"]["records"]["geometry_optimization"]["state"] in ("PARTIALLY_UNDERSTOOD", "UNDERSTOOD")
    assert not row.state.get("pending") or row.state["pending"]["concept_id"] == "geometry_optimization"


async def test_a_new_question_abandons_the_pending_follow_up_and_is_answered(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-abandon")
    first = await _send(client, token, classroom_id, "What is geometry optimization?")
    out = await _send(client, token, classroom_id, "What is a basis set and why does the calculation need one?", first["thread_id"])
    assert _meta(out)["type"] == "qa"  # answered as a fresh theory question


async def test_an_understood_concept_is_not_asked_about_again(client, make_user, db, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-understood")
    first = await _send(client, token, classroom_id, "What is geometry optimization?")
    thread = first["thread_id"]
    await _send(client, token, classroom_id,
                "No, a hand-built structure is only a rough guess so its energy is probably not the lowest", thread)
    # whatever the state is now, asking again after the cooldown must not repeat an understood concept's question
    again = await _send(client, token, classroom_id, "Why is geometry optimization necessary?", thread)
    row = (await db.scalars(select(ChatThread).where(ChatThread.id == thread).execution_options(populate_existing=True))).one()
    state = row.state["concepts"]["records"]["geometry_optimization"]["state"]
    if state in ("UNDERSTOOD", "MASTERED"):
        assert "Think about this" not in _content(again)


# ---------------------------------------------------------------- PROCEDURE is opt-in


async def test_a_procedure_request_gets_an_overview_that_says_it_is_done_on_a_lab_computer(client, make_user, db, llm):
    classroom_id, user, token = await _setup(client, make_user, "tf-proc")
    calls = len(llm.calls)
    out = await _send(client, token, classroom_id, "How do I perform Experiment 7?")
    text = _content(out)
    assert _meta(out)["type"] == "mode" and _meta(out)["transition_reason"] == "procedure overview"
    assert len(llm.calls) == calls  # deterministic, zero model calls
    assert "On the lab computer" in text and "You do not need to do any of them here" in text
    assert "only your phone" in text and "Gabedit" in text  # it is the procedure, so it may name the tools
    assert "Look at" not in text and "Step 1" not in text
    chips = _meta(out)["ui"]["chips"]
    assert "Explain the theory instead" in chips and "Guide me through the key ideas" in chips
    assert (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.student_id == user.id))).all() == []


async def test_the_practical_chip_also_gives_the_overview_not_a_stepper(client, make_user, db, llm):
    classroom_id, user, token = await _setup(client, make_user, "tf-chip")
    out = await _send(client, token, classroom_id, "Practical / Experiment")
    assert _meta(out)["transition_reason"] == "procedure overview"
    assert (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.student_id == user.id))).all() == []


# ---------------------------------------------------------------- EXIT the procedure, any time


async def test_leaving_the_procedure_with_a_question_answers_it_immediately(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-exit1")
    first = await _send(client, token, classroom_id, "How do I perform Experiment 7?")
    thread = first["thread_id"]
    calls = len(llm.calls)
    out = await _send(client, token, classroom_id, "Forget the steps. Explain why geometry optimization works.", thread)
    assert len(llm.calls) - calls == 1
    assert _meta(out)["mode"] == "theory" and _meta(out)["type"] == "qa"
    assert not STEPS_RE.search(_content(out)) and "finish" not in _content(out).lower()
    assert "Back to" not in _content(out)


async def test_skip_the_procedure_then_a_theory_question_is_answered(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-exit2")
    first = await _send(client, token, classroom_id, "How do I perform Experiment 7?")
    out = await _send(client, token, classroom_id, "Skip the procedure. What is HOMO?", first["thread_id"])
    assert _meta(out)["mode"] == "theory" and _meta(out)["type"] == "qa"
    assert not STEPS_RE.search(_content(out))
    assert "paused" not in _content(out).lower() and "Back to" not in _content(out)


async def test_i_only_want_the_theory_switches_mode_with_no_model_call(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-exit3")
    first = await _send(client, token, classroom_id, "How do I perform Experiment 7?")
    calls = len(llm.calls)
    out = await _send(client, token, classroom_id, "I only want the theory.", first["thread_id"])
    assert len(llm.calls) == calls
    assert _meta(out)["mode"] == "theory"
    assert "What would you like to understand?" in _content(out)
    assert not STEPS_RE.search(_content(out))


# ---------------------------------------------------------------- the guided key-ideas session (opt-in, exitable)


async def test_the_key_ideas_session_is_opt_in_phone_safe_and_exitable(client, make_user, db, llm):
    classroom_id, user, token = await _setup(client, make_user, "tf-guided")
    first = await _send(client, token, classroom_id, "Guide me through the key ideas")
    thread = first["thread_id"]
    assert "thinking session" in _content(first) and "Part 1 of 6" in _content(first)
    assert external_dependency(_content(first)) is None
    assert _meta(first)["ui"]["kind"] == "concept"
    out = await _send(client, token, classroom_id, "Skip the steps. What is HOMO?", thread)
    assert _meta(out)["mode"] == "theory"
    assert "paused the key-ideas session" in _content(out) or _meta(out)["type"] == "qa"
    back = await _send(client, token, classroom_id, "Guide me through the key ideas", thread)
    assert "Part 1 of 6" in _content(back) or "Back to the key ideas" in _content(back)


# ---------------------------------------------------------------- PART O: the realistic journey


async def test_the_realistic_student_journey_end_to_end(client, make_user, db, llm):
    classroom_id, user, token = await _setup(client, make_user, "tf-journey")

    # 2-3. New chat; the student asks about geometry optimization.
    chat_a = await _new_thread(client, token, classroom_id)
    a1 = await _send(client, token, classroom_id, "What is geometry optimization?", chat_a)
    # 4-5. A conceptual answer and one short Socratic follow-up; no procedure.
    assert not STEPS_RE.search(_content(a1)) and "Think about this" in _content(a1)
    # 6-7. The student answers; the tutor continues conceptually.
    a2 = await _send(client, token, classroom_id, "it just makes the molecule look nicer", chat_a)
    assert "What quantity" in _content(a2) and not STEPS_RE.search(_content(a2))

    # 8-10. Another new chat: nothing from chat A.
    chat_b = await _new_thread(client, token, classroom_id)
    before = len(llm.calls)
    b1 = await _send(client, token, classroom_id, "What is HOMO?", chat_b)
    b_prompt = "\n".join(c["system"] + c["user"] for c in llm.calls[before:])
    assert "look nicer" not in b_prompt and "geometry optimization?" not in b_prompt.lower().split("homo")[0]
    assert "STUDENT:" not in b_prompt  # no history lines at all in a fresh thread's first turn
    assert "look nicer" not in _content(b1)

    # 11-12. Now the student explicitly asks for the procedure.
    b2 = await _send(client, token, classroom_id, "How do I actually perform this experiment?", chat_b)
    assert _meta(b2)["transition_reason"] == "procedure overview"
    assert "lab computer" in _content(b2)

    # 13-14. And leaves it again.
    b3 = await _send(client, token, classroom_id, "Actually, I only want to understand the theory.", chat_b)
    assert _meta(b3)["mode"] == "theory" and not STEPS_RE.search(_content(b3))

    # 15-16. A conceptual answer.
    b4 = await _send(client, token, classroom_id, "Why is geometry optimization necessary?", chat_b)
    assert _meta(b4)["type"] in ("qa", "walkthrough") and not STEPS_RE.search(_content(b4))

    # 17. Nothing anywhere asked the student to look at or open anything external.
    for out in (a1, a2, b1, b3, b4):
        assert external_dependency(_content(out)) is None, _content(out)
    assert (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.student_id == user.id))).all() == []


# ---------------------------------------------------------------- LLM-call budget for each kind of turn


async def test_llm_calls_per_kind_of_turn(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-calls")
    calls = lambda: len(llm.calls)  # noqa: E731
    c0 = calls()
    greeting = await _send(client, token, classroom_id, "hi")
    assert calls() == c0  # a greeting / new chat: zero
    thread = greeting["thread_id"]
    theory_q = await _send(client, token, classroom_id, "What is a basis set?", thread)
    assert _meta(theory_q)["llm_calls"] == 1  # a theory question: exactly one
    c1 = calls()
    await _send(client, token, classroom_id, "How do I perform Experiment 7?", thread)
    assert calls() == c1  # procedure mode: zero
    await _send(client, token, classroom_id, "I only want the theory.", thread)
    assert calls() == c1  # a bare mode switch: zero


# ---------------------------------------------------------------- model unavailable


async def test_with_no_model_a_known_concept_gets_an_authored_explanation_not_a_manual_excerpt(client, make_user, llm):
    llm.available = False
    classroom_id, _, token = await _setup(client, make_user, "tf-nomodel")
    out = await _send(client, token, classroom_id, "What is geometry optimization?")
    text = _content(out)
    assert "Here is the short version." in text and "Geometry optimization" in text
    assert "converge" not in text.lower() and not STEPS_RE.search(text)
    assert external_dependency(text) is None
    assert "Think about this" in text  # still Socratic


async def test_with_no_model_an_unknown_topic_still_never_shows_procedure_or_software(client, make_user, llm):
    llm.available = False
    classroom_id, _, token = await _setup(client, make_user, "tf-nomodel2")
    out = await _send(client, token, classroom_id, "Tell me something about the lab material please")
    assert "Gabedit" not in _content(out) and "ORCA" not in _content(out) and not STEPS_RE.search(_content(out))


# ---------------------------------------------------------------- a pending follow-up + a change of direction
# (found in a live run: the exit message was graded as an answer to the old follow-up)


async def test_a_pending_follow_up_does_not_swallow_a_procedure_request_and_then_an_exit_question(client, make_user, llm):
    classroom_id, _, token = await _setup(client, make_user, "tf-pending-switch")
    first = await _send(client, token, classroom_id, "What is geometry optimization?")  # leaves a follow-up pending
    thread = first["thread_id"]
    await _send(client, token, classroom_id, "it just makes the molecule look nicer", thread)  # probed, still pending
    overview = await _send(client, token, classroom_id, "How do I perform Experiment 7?", thread)
    assert _meta(overview)["transition_reason"] == "procedure overview"
    calls = len(llm.calls)
    out = await _send(client, token, classroom_id, "Forget the steps. Explain why geometry optimization works.", thread)
    assert len(llm.calls) - calls == 1  # answered by the model as a NEW question...
    assert _meta(out)["type"] == "qa"  # ...not graded against the stale follow-up
    assert "short version:" not in _content(out)
    assert _meta(out)["mode"] == "theory"


@pytest.mark.parametrize(
    "new_question",
    ["What is a basis set?", "Why do different methods give different values?", "Explain hybridization to me"],
)
async def test_a_new_question_while_a_follow_up_is_pending_is_answered_not_graded(client, make_user, llm, new_question):
    classroom_id, _, token = await _setup(client, make_user, f"tf-newq-{abs(hash(new_question)) % 1000}")
    first = await _send(client, token, classroom_id, "What is geometry optimization?")
    calls = len(llm.calls)
    out = await _send(client, token, classroom_id, new_question, first["thread_id"])
    assert len(llm.calls) - calls == 1
    assert _meta(out)["type"] == "qa" and "Yes." not in _content(out)


async def test_authored_explanations_do_not_carry_unrelated_source_citations(client, make_user, llm):
    llm.available = False
    classroom_id, _, token = await _setup(client, make_user, "tf-nocite")
    out = await _send(client, token, classroom_id, "What is HOMO?")
    assert "Here is the short version." in _content(out)
    assert _meta(out)["citations"] == []
