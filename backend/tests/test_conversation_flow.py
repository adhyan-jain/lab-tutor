"""Conversation flow: per-chat state, theory vs practice, intent before
grading, troubleshooting, and non-recursive action chips.

Unit tests drive the pure pieces (`conversation.classify`,
`conversation.actions`, the walkthrough controller); API tests drive the
real /api/chat endpoints. The Exp7 walkthrough is the practical workflow
used here because it is the one with steps and chips; a reference plugin
covers the legacy Socratic session for the new-chat test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.auth import session as session_cookie
from backend.config import reload_settings
from backend.models import ChatThread, WalkthroughProgress
from backend.socratic_engine import conversation as conv
from backend.socratic_engine.conversation import Intent
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough.exp07_script import SCRIPT
from backend.tests.reference_plugin import reference_plugin

@pytest.fixture(autouse=True)
def _software_walkthrough(monkeypatch):
    """These tests cover the SOFTWARE walkthrough's conversation flow. Phone-only
    mode (the default) is covered by test_theory_first.py."""
    monkeypatch.setenv("LABTUTOR_PHONE_ONLY", "false")
    reload_settings()
    yield
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()


HINT, WHY, DIFFERENT = conv.ACTIONS["hint"], conv.ACTIONS["why"], conv.ACTIONS["different"]
STEP_CHIPS = (HINT, WHY, DIFFERENT, conv.ACTIONS["study_theory"])


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


def at_step(step_id: str) -> ctl.WalkState:
    state = ctl.new_state("stu")
    ctl.start(state)
    state.phase = "step"
    state.step_id = step_id
    state.pending = "evidence" if SCRIPT.step(step_id).evidence else "check"
    return state


# ------------------------------------------------------------ intent unit


@pytest.mark.parametrize(
    "text, intent",
    [
        ("I don't want to do this step, I want to study theory.", Intent.SWITCH_TO_THEORY),
        ("I want to study theory.", Intent.SWITCH_TO_THEORY),
        ("I want to learn instead.", Intent.SWITCH_TO_THEORY),
        ("I just want the theory.", Intent.SWITCH_TO_THEORY),
        ("Theory / Study", Intent.SWITCH_TO_THEORY),
        ("Practical / Experiment", Intent.SWITCH_TO_PRACTICE),
        ("Okay, let's continue the experiment.", Intent.SWITCH_TO_PRACTICE),
        ("I want to go back to the experiment.", Intent.SWITCH_TO_PRACTICE),
        ("I don't want to do this.", Intent.STEP_REFUSED),
        ("I don't want to do this step.", Intent.STEP_REFUSED),
        ("I don't want to draw.", Intent.STEP_REFUSED),
        ("Skip this.", Intent.STEP_SKIPPED),
        ("I don't have that option.", Intent.TROUBLESHOOTING),
        ("That button isn't there.", Intent.TROUBLESHOOTING),
        ("I don't have a menu", Intent.TROUBLESHOOTING),
        ("It's not working.", Intent.TROUBLESHOOTING),
        ("This looks different.", Intent.TROUBLESHOOTING),
        ("Something looks different", Intent.TROUBLESHOOTING),
        ("I can't do this", Intent.TROUBLESHOOTING),
        ("it just doesn't open at all", Intent.TROUBLESHOOTING),
        ("Give me a hint.", Intent.USER_REQUESTED_HINT),
        ("Why do I need to do this?", Intent.USER_REQUESTED_EXPLANATION),
        ("Why do this step?", Intent.USER_REQUESTED_EXPLANATION),
        ("I don't understand this step.", Intent.USER_REQUESTED_EXPLANATION),
        ("what is a basis set?", Intent.USER_QUESTION),
        ("Why do we use B3LYP?", Intent.USER_QUESTION),
        ("charge 0, multiplicity 1", Intent.ANSWER),
        ("B", Intent.ANSWER),
        ("ORCA TERMINATED NORMALLY", Intent.ANSWER),
    ],
)
def test_natural_phrasings_map_to_intents(text, intent):
    assert conv.classify(text) is intent


def test_every_chip_text_classifies_back_to_its_own_intent():
    """A tapped chip and the same words typed by hand must behave the same."""
    for action_id, intent in conv.ACTION_INTENT.items():
        assert conv.classify(conv.ACTIONS[action_id]) is intent, action_id


# ---------------------------------------------------------- action policy


def test_18_child_never_contains_its_source_or_an_equivalent_action():
    chips, ctx = conv.actions(["theory", "study_theory", "hint", "why"], source="study_theory")
    assert conv.ACTIONS["study_theory"] not in chips and conv.ACTIONS["theory"] not in chips
    assert ctx == {"source_action": "study_theory", "depth": 1, "suppressed": ["theory", "study_theory"]}


def test_19_no_duplicate_action_buttons():
    chips, _ = conv.actions(["hint", "why", "hint", "why", "different"])
    assert chips == [HINT, WHY, DIFFERENT]


def test_consumed_actions_are_not_offered_again():
    chips, _ = conv.actions(["hint", "why", "different", "continue"], source="why", consumed=["hint"])
    assert chips == [DIFFERENT, conv.ACTIONS["continue"]]


# -------------------------------------------------- controller: refusals


def test_14_refusing_a_step_is_step_refused_not_completed():
    state = at_step("b2_draw")
    before = (state.step_id, state.steps_done, list(state.skipped))
    out = ctl.take_turn(state, "I don't want to do this step.")
    assert out.events["verdict"] == "step_refused" and out.events["intent"] == "step_refused"
    assert (state.step_id, state.steps_done, state.skipped) == before
    assert state.tries == {}  # not even counted as a wrong attempt


def test_7_i_dont_want_to_draw_never_advances_even_when_repeated():
    state = at_step("b2_draw")
    first = ctl.take_turn(state, "I don't want to draw.")
    assert conv.ACTIONS["study_theory"] in first.ui["chips"]
    second = ctl.take_turn(state, "I don't want to draw.")
    third = ctl.take_turn(state, "no, I really don't want to draw")
    assert state.step_id == "b2_draw" and state.steps_done == 0 and state.tries == {}
    # The second clarification is phrased differently, not the same menu again.
    assert second.reply != first.reply and second.events["verdict"] == "step_refused_again"
    assert third.events["verdict"] == "step_refused_again"


def test_explicit_skip_is_recorded_as_skipped_not_completed():
    state = at_step("b2_draw")
    ctl.take_turn(state, "skip this step")
    assert "b2_draw" in state.skipped and state.steps_done == 0 and state.step_id == "b3_methane"


# ------------------------------------------- controller: hint / why chips


def test_8_hint_response_never_offers_hint_again():
    state = at_step("b2_draw")
    card = ctl.show_current(state)
    assert list(card.ui["chips"]) == list(STEP_CHIPS)
    hint = ctl.take_turn(state, HINT)
    assert hint.events["verdict"] == "hint_requested" and "**Hint:**" in hint.reply
    assert HINT not in hint.ui["chips"]
    assert hint.ui["chips"] == [WHY, DIFFERENT, conv.ACTIONS["continue"]]
    assert hint.ui["action_context"]["source_action"] == "hint"
    assert "hint" in hint.ui["action_context"]["suppressed"]
    assert state.step_id == "b2_draw"


def test_9_repeated_hint_requests_do_not_produce_new_hint_cards():
    state = at_step("b2_draw")
    first = ctl.take_turn(state, HINT)
    replies = [ctl.take_turn(state, "give me a hint") for _ in range(4)]
    for r in replies:
        assert r.events["verdict"] == "hint_repeated" and "**Hint:**" not in r.reply
        assert HINT not in r.ui["chips"]
    assert first.reply.count("**Hint:**") == 1 and state.step_id == "b2_draw"
    # Going back to the step card still does not resurrect the used hint.
    card = ctl.take_turn(state, "Continue")
    assert HINT not in card.ui["chips"]


def test_10_why_response_never_offers_why_again():
    state = at_step("b2_draw")
    out = ctl.take_turn(state, "Why do I need to do this?")
    assert out.events["verdict"] == "why_requested" and "Why this step" in out.reply
    assert WHY not in out.ui["chips"] and HINT in out.ui["chips"]
    again = ctl.take_turn(state, WHY)
    assert again.events["verdict"] == "why_repeated" and WHY not in again.ui["chips"]


def test_20_action_graph_has_no_cycles():
    """Follow every chip from a fresh step card, depth-first. No reply may
    offer the chip that produced it, an action may be used at most once per
    question, and every path ends (no infinite tree)."""
    terminal = {conv.ACTIONS[a] for a in ("study_theory", "skip", "back_to_step", "continue", "just_tell")}

    def walk(state: ctl.WalkState, chips: list[str], used: tuple[str, ...], depth: int) -> int:
        assert depth < 8, f"action path too deep: {used}"
        explored = 0
        for chip in chips:
            if chip in terminal:
                continue
            assert chip not in used, f"{chip} offered again after {used}"
            child = ctl.WalkState.from_dict(state.to_dict())
            out = ctl.take_turn(child, chip)
            assert child.step_id == state.step_id, f"{chip} moved the step"
            assert chip not in out.ui.get("chips", []), f"{chip} offered itself"
            explored += 1 + walk(child, out.ui.get("chips", []), used + (chip,), depth + 1)
        return explored

    for step_id in ("b1_open", "b2_draw", "b3_methane", "o1_open_file"):
        state = at_step(step_id)
        card = ctl.show_current(state)
        assert walk(state, card.ui["chips"], (), 0) > 0


# --------------------------------------- controller: troubleshooting state


def test_11_something_looks_different_enters_troubleshooting():
    state = at_step("b2_draw")
    out = ctl.take_turn(state, DIFFERENT)
    assert out.events["verdict"] == "troubleshooting" and state.troubleshooting
    assert "describe what you see" in out.reply
    assert DIFFERENT not in out.ui["chips"]
    assert out.ui["chips"] == [conv.ACTIONS["back_to_step"], conv.ACTIONS["study_theory"], conv.ACTIONS["skip"]]
    # The follow-up description is a report to diagnose, never a wrong try.
    report = ctl.take_turn(state, "there is only a blank grey window with a toolbar")
    assert report.reply is None and report.events["verdict"] == "troubleshoot_report"
    assert state.tries == {} and state.step_id == "b2_draw"
    assert "reporting a problem" in ctl.step_context(state)
    # Back on the step card a new problem can still be reported.
    card = ctl.take_turn(state, "Back to step")
    assert not state.troubleshooting and DIFFERENT in card.ui["chips"]


def test_12_its_not_working_never_advances():
    state = at_step("b1_open")
    out = ctl.take_turn(state, "It's not working.")
    assert out.events["verdict"] == "troubleshooting" and state.step_id == "b1_open"
    for msg in ("still nothing", "it just doesn't open at all", "hmm no"):
        ctl.take_turn(state, msg)
    assert state.step_id == "b1_open" and state.steps_done == 0 and state.tries == {}
    resolved = ctl.take_turn(state, "ok it works now")
    assert resolved.events["verdict"] == "problem_resolved" and not state.troubleshooting
    assert state.step_id == "b1_open"


def test_13_missing_option_is_believed_not_contradicted():
    state = at_step("b2_draw")
    out = ctl.take_turn(state, "I don't have that option.")
    assert out.events["verdict"] == "troubleshooting"
    assert "won't assume that option is there" in out.reply and "what you do see" in out.reply
    assert state.step_id == "b2_draw"


def test_a_detailed_problem_report_goes_straight_to_grounded_diagnosis():
    state = at_step("b2_draw")
    out = ctl.take_turn(state, "when I click the geometry menu nothing opens and I get an error box")
    assert out.reply is None and out.events["verdict"] == "troubleshoot_report"
    assert state.troubleshooting and state.step_id == "b2_draw"


def test_correct_answer_during_troubleshooting_completes_the_step():
    state = at_step("b3_methane")
    ctl.take_turn(state, "It's not working.")
    q = ctl._current_question(state)
    ctl.take_turn(state, str(int(q.numbers[0])))
    # Evidence accepted: on to the step's cross-question, troubleshooting over.
    assert not state.troubleshooting and state.pending == "check" and state.step_id == "b3_methane"


# ------------------------------------------------------------- API tests


ANSWER = "Here is a grounded explanation."


@pytest.fixture
def counting_llm(fake_llm, monkeypatch):
    fake_llm.reply = ANSWER
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


async def _setup(client, make_user, tag: str, experiment_id: str = "exp07"):
    _, prof = await make_user(f"prof.{tag}@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "C"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": experiment_id},
        headers=auth(prof),
    )
    assert started.status_code == 201
    user, token = await make_user(f"s.{tag}@vitstudent.ac.in")
    await client.post(
        "/api/classrooms/join", json={"join_code": created.json()["student_join_code"]}, headers=auth(token)
    )
    return user, token, classroom_id


class Chat:
    def __init__(self, client, token, classroom_id, experiment_id="exp07", thread_id=None):
        self.client, self.token, self.classroom_id = client, token, classroom_id
        self.experiment_id, self.thread_id = experiment_id, thread_id

    @classmethod
    async def new(cls, client, token, classroom_id, experiment_id="exp07"):
        resp = await client.post(
            "/api/chat/threads",
            json={"classroom_id": classroom_id, "experiment_id": experiment_id},
            headers=auth(token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["mode"] == "initial"
        return cls(client, token, classroom_id, experiment_id, resp.json()["id"])

    async def send(self, message: str) -> dict:
        body = {"classroom_id": self.classroom_id, "experiment_id": self.experiment_id, "message": message}
        if self.thread_id:
            body["thread_id"] = self.thread_id
        resp = await self.client.post("/api/chat/messages", json=body, headers=auth(self.token))
        assert resp.status_code == 200, resp.text
        self.thread_id = resp.json()["thread_id"]
        return resp.json()["message"]

    async def messages(self) -> list[dict]:
        resp = await self.client.get(f"/api/chat/threads/{self.thread_id}/messages", headers=auth(self.token))
        return resp.json()["messages"]


async def _thread_state(db, thread_id: str) -> dict:
    thread = (await db.scalars(select(ChatThread).where(ChatThread.id == thread_id))).one()
    await db.refresh(thread)
    return thread.state or {}


async def _walk_row(db, thread_id: str) -> WalkthroughProgress | None:
    row = (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.thread_id == thread_id))).first()
    if row is not None:
        await db.refresh(row)
    return row


async def _practice_at_step_2(chat: Chat) -> None:
    await chat.send("Practical / Experiment")
    await chat.send("a guess")  # curiosity hook
    out = await chat.send("geometry")  # step 1 evidence
    assert "Step 2 of 27" in out["content"]


@pytest.mark.asyncio
async def test_1_2_3_new_chat_starts_fresh(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t1")
    chat_a = await Chat.new(client, token, classroom_id)
    await _practice_at_step_2(chat_a)

    chat_b = await Chat.new(client, token, classroom_id)
    assert chat_b.thread_id != chat_a.thread_id
    assert await chat_b.messages() == []  # TEST 3: no inherited messages
    assert await _walk_row(db, chat_b.thread_id) is None  # TEST 2: no inherited step
    assert (await _thread_state(db, chat_b.thread_id))["mode"] == "initial"

    # Anything sent in B is handled from B's own fresh state.
    out = await chat_b.send("hi")
    assert out["metadata"]["type"] == "mode" and "What would you like to do today?" in out["content"]
    assert out["metadata"]["ui"]["chips"] == [conv.ACTIONS["theory"], conv.ACTIONS["practice"]]
    assert "Step 2" not in out["content"]
    # And chat A is still exactly where it was.
    assert (await _walk_row(db, chat_a.thread_id)).state["step_id"] == "b2_draw"


@pytest.mark.asyncio
async def test_greeting_does_not_repeat_the_same_menu(client, make_user, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t1b")
    chat = await Chat.new(client, token, classroom_id)
    first = await chat.send("hi")
    second = await chat.send("hello")
    assert first["content"] != second["content"]


@pytest.mark.asyncio
async def test_new_chat_does_not_reuse_another_chats_socratic_session(client, make_user, db, monkeypatch):
    from backend.tier1_compute.experiments import registry

    plugin = reference_plugin()
    monkeypatch.setitem(registry._REGISTRY, plugin.id, plugin)
    _, token, classroom_id = await _setup(client, make_user, "t2s", experiment_id="ref01")
    chat_a = Chat(client, token, classroom_id, "ref01")
    guide = await chat_a.send("Can you guide me through this experiment?")
    assert guide["kind"] == "socratic"
    step = await chat_a.send("standard_normality=0.1, standard_volume=25.0, value=2.5")
    assert step["metadata"]["current_step"] == 1

    chat_b = Chat(client, token, classroom_id, "ref01")
    fresh = await chat_b.send("Can you guide me through this experiment?")
    assert fresh["kind"] == "socratic" and fresh["metadata"]["current_step"] == 0
    a_state = await _thread_state(db, chat_a.thread_id)
    b_state = await _thread_state(db, chat_b.thread_id)
    assert a_state["socratic_session_id"] and a_state["socratic_session_id"] != b_state["socratic_session_id"]


@pytest.mark.asyncio
async def test_4_choosing_theory_enters_theory_mode(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t4")
    chat = await Chat.new(client, token, classroom_id)
    out = await chat.send(conv.ACTIONS["theory"])
    assert out["metadata"]["mode"] == "theory" and "What concept" in out["content"]
    assert (await _thread_state(db, chat.thread_id))["mode"] == "theory"
    # In theory mode even a how-to question is answered, not turned into steps.
    q = await chat.send("how do I read the HOMO energy?")
    assert q["metadata"]["type"] == "qa" and q["metadata"]["mode"] == "theory"
    assert await _walk_row(db, chat.thread_id) is None
    assert counting_llm.calls  # grounded answer path


@pytest.mark.asyncio
async def test_5_choosing_practice_enters_the_practical_workflow(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t5")
    chat = await Chat.new(client, token, classroom_id)
    out = await chat.send(conv.ACTIONS["practice"])
    assert out["metadata"]["type"] == "walkthrough" and out["metadata"]["mode"] == "practice"
    assert out["metadata"]["ui"]["kind"] == "hook"
    assert (await _walk_row(db, chat.thread_id)) is not None


@pytest.mark.asyncio
async def test_6_17_refusing_for_theory_switches_mode_and_keeps_the_step(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t6")
    chat = await Chat.new(client, token, classroom_id)
    await _practice_at_step_2(chat)
    out = await chat.send("I don't want to do this step, I want to study theory.")
    assert out["metadata"]["type"] == "mode" and out["metadata"]["mode"] == "theory"
    assert out["content"].startswith("Sure, we can study the theory instead.")
    assert "Step 3" not in out["content"]
    assert out["metadata"]["ui"]["chips"] == [conv.ACTIONS["back_to_experiment"]]
    row = await _walk_row(db, chat.thread_id)
    assert row.state["step_id"] == "b2_draw" and row.status == "paused" and row.state["steps_done"] == 1
    state = await _thread_state(db, chat.thread_id)  # TEST 17: context kept
    assert state["previous_mode"] == "practice" and state["previous_step"] == "b2_draw"
    assert state["topic"] == SCRIPT.step("b2_draw").title


@pytest.mark.asyncio
async def test_16_theory_back_to_practice_returns_to_the_same_step(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t16")
    chat = await Chat.new(client, token, classroom_id)
    await _practice_at_step_2(chat)
    await chat.send("I want to study theory")
    q = await chat.send("explain this")
    assert q["metadata"]["type"] == "qa" and q["metadata"]["ui"]["chips"] == [conv.ACTIONS["back_to_experiment"]]
    # The deictic "this" was expanded with the step the student left.
    assert SCRIPT.step("b2_draw").title in counting_llm.calls[-1]["user"]
    back = await chat.send("Okay, let's continue the experiment.")
    assert back["metadata"]["mode"] == "practice" and "Step 2 of 27" in back["content"]
    row = await _walk_row(db, chat.thread_id)
    assert row.status == "active" and row.state["step_id"] == "b2_draw"


@pytest.mark.asyncio
async def test_15_model_prose_cannot_advance_the_state_machine(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t15")
    chat = await Chat.new(client, token, classroom_id)
    await _practice_at_step_2(chat)
    counting_llm.reply = "Great, you've finished this one. Proceed to Step 4: run the calculation."
    out = await chat.send("what is a basis set?")
    assert "Back to Step 2 of 27" in out["content"]
    row = await _walk_row(db, chat.thread_id)
    assert row.state["step_id"] == "b2_draw" and row.state["steps_done"] == 1


@pytest.mark.asyncio
async def test_12_api_its_not_working_is_troubleshooting_and_grounded(client, make_user, db, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t12")
    chat = await Chat.new(client, token, classroom_id)
    await _practice_at_step_2(chat)
    out = await chat.send("It's not working.")
    assert out["metadata"]["walkthrough"]["verdict"] == "troubleshooting"
    assert out["metadata"]["detected_intent"] == "troubleshooting"
    calls_before = len(counting_llm.calls)
    report = await chat.send("the window that opens has no geometry entry at the top")
    assert report["metadata"]["walkthrough"]["verdict"] == "troubleshoot_report"
    assert len(counting_llm.calls) == calls_before + 1
    assert "reporting a problem" in counting_llm.calls[-1]["user"]
    assert (await _walk_row(db, chat.thread_id)).state["step_id"] == "b2_draw"


@pytest.mark.asyncio
async def test_8_api_hint_card_has_no_hint_chip(client, make_user, counting_llm):
    _, token, classroom_id = await _setup(client, make_user, "t8")
    chat = await Chat.new(client, token, classroom_id)
    await _practice_at_step_2(chat)
    out = await chat.send(HINT)
    assert HINT not in out["metadata"]["ui"]["chips"]
    assert out["metadata"]["ui"]["action_context"]["source_action"] == "hint"
