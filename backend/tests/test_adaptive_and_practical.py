"""Adaptive follow-up questions and the guided practical progress tracker.

Adaptive tutoring extends the existing deterministic concept engine
(pedagogy/policy.py, walkthrough/controller.py): authored questions, regex
answer keys, no model deciding anything. The tracker reads (or, for
self-report experiments, records one step at a time) per-thread practical
progress built from each experiment's own authored steps.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models import ChatThread
from backend.rag.language import looks_non_english
from backend.socratic_engine import conversation as conv
from backend.socratic_engine import practical, theory
from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.pedagogy import policy
from backend.socratic_engine.pedagogy import state as pstate
from backend.socratic_engine.walkthrough import controller as ctl
from backend.tests.concept_answers import GOOD
from backend.tests.test_chat_isolation import _setup, auth  # noqa: F401
from backend.tests.test_reflection_routing import _pending_state
from backend.tests.test_student_feedback import ENGLISH, scripted  # noqa: F401
from backend.tests.test_walkthrough_api import _send

K = get_knowledge("exp07")


def _session() -> ctl.WalkState:
    state = ctl.new_state("stu", mode="concept")
    ctl.start(state)
    assert state.phase == "concept"
    return state


def _question(state: ctl.WalkState):
    return K.question_by_id[state.concept["question_id"]]


def _misses(state, q) -> int:
    return pstate.ConceptStates.from_dict(state.concepts).get(q.concept_id).misses.get(q.id, 0)


# ============================================================ level ladder


def test_the_ladder_covers_every_authored_question_type():
    from backend.socratic_engine.knowledge.types import QUESTION_TYPES

    assert set(policy.LEVEL) == set(QUESTION_TYPES)
    assert policy.LEVEL["OBSERVATION"] < policy.LEVEL["WHY"] < policy.LEVEL["PREDICTION"] <= policy.LEVEL["TRANSFER"]


def test_deeper_question_is_same_concept_higher_level_and_unasked():
    for q in K.questions:
        rec = pstate.ConceptRecord(asked=[q.id])
        nxt = policy.deeper_question(K, q, rec)
        if nxt is not None:
            assert nxt.concept_id == q.concept_id
            assert policy.LEVEL[nxt.qtype] > policy.LEVEL[q.qtype]
            assert nxt.id not in rec.asked


# ================================================= adaptive answer handling


def test_a_full_correct_answer_earns_one_deeper_question_then_moves_on():
    """Across a whole guided session answered well, at least one correct answer
    leads to a harder question on the same idea, never two in a row."""
    state = _session()
    verdicts = []
    for _ in range(80):
        if state.status == "done":
            break
        if state.phase == "concept":
            q = _question(state)
            r = ctl.take_turn(state, GOOD[q.id])
            verdicts.append(r.events["verdict"])
            if r.events["verdict"] == "concept_deeper":
                nxt = _question(state)
                assert nxt.concept_id == q.concept_id
                assert policy.LEVEL[nxt.qtype] > policy.LEVEL[q.qtype]
                assert r.reply.startswith("**Yes.**") and "one level deeper" in r.reply
        else:
            ctl.take_turn(state, GOOD[state.assess["queue"][state.assess["i"]]])
    assert state.status == "done"  # the quiz completes
    assert "concept_deeper" in verdicts
    assert all(not (a == b == "concept_deeper") for a, b in zip(verdicts, verdicts[1:]))


def test_a_partial_answer_gets_a_focused_scaffold_not_mastery():
    """The HOMO/LUMO question needs both ideas; naming only the HOMO is
    acknowledged and the missing part asked for, and nothing is mastered."""
    state = _pending_state()
    q = K.question_by_id[state.pending["question_id"]]
    turn = theory.handle_pending(state, "HOMO stands for Highest Occupied Molecular Orbital.")
    assert turn.events["pedagogy"]["classification"] == "PARTIAL"
    assert turn.events["verdict"] == "concept_scaffold"
    assert turn.reply.startswith(ctl._PARTIAL_OPENERS) and q.scaffold in turn.reply
    assert state.pending and state.pending["question_id"] == q.id  # still open for a second try
    rec = pstate.ConceptStates.from_dict(state.concepts).get(q.concept_id)
    assert rec.state not in ("UNDERSTOOD", "MASTERED")


def test_wrong_answer_probes_then_explains_after_repeated_misses():
    state = _session()
    q = _question(state)
    misconceptions = [m for m in K.misconceptions if m.concept_id == q.concept_id]
    wrong = misconceptions[0].statement if misconceptions else "banana banana"
    first = ctl.take_turn(state, wrong)
    assert first.events["verdict"] in ("concept_probe", "concept_scaffold")
    assert state.concept["question_id"] == q.id  # a second attempt is allowed
    second = ctl.take_turn(state, wrong)
    assert second.events["verdict"] == "concept_explained"  # existing reveal policy


def test_a_hint_then_a_second_attempt_succeeds():
    state = _session()
    q = _question(state)
    hint = ctl.take_turn(state, "Give me a hint")
    assert hint.events["verdict"] == "concept_hint" and hint.reply == f"**Hint:** {q.scaffold}"
    assert conv.ACTIONS["hint"] not in hint.ui["chips"]  # used once
    assert _misses(state, q) == 0  # asking for a hint is not a wrong answer
    again = ctl.take_turn(state, "hint please")
    assert again.events["verdict"] == "concept_hint_repeated"
    done = ctl.take_turn(state, GOOD[q.id])
    assert done.events["verdict"] in ("concept_correct", "concept_deeper")


@pytest.mark.parametrize("message", ["I'm confused", "I don't understand", "this is too hard", "samajh nahi aaya", "I'm stuck"])
def test_confusion_gets_a_simpler_explanation_and_keeps_the_question(message):
    state = _session()
    q = _question(state)
    concept = K.concept_by_id[q.concept_id]
    r = ctl.take_turn(state, message)
    assert r.events["verdict"] == "concept_simplified"
    assert concept.description in r.reply and "easier way in" in r.reply
    assert state.concept["question_id"] == q.id and _misses(state, q) == 0
    assert not looks_non_english(r.reply)


def test_an_example_request_is_answered_by_q_and_a_and_keeps_the_question():
    state = _session()
    q = _question(state)
    r = ctl.take_turn(state, "Show an example")
    assert r.events["verdict"] == "side_question" and r.reply is None
    assert K.concept_by_id[q.concept_id].name in r.side_query
    assert state.concept["question_id"] == q.id


def test_an_unrelated_question_during_the_quiz_is_answered_not_graded():
    state = _session()
    q = _question(state)
    r = ctl.take_turn(state, "What is a basis set?")
    assert r.events["verdict"] == "side_question"
    assert state.concept["question_id"] == q.id and _misses(state, q) == 0


def test_the_concept_question_offers_only_fitting_actions():
    state = _session()
    _, ui = ctl._concept_message(state)
    chips = ui["chips"]
    assert conv.ACTIONS["example"] in chips and conv.ACTIONS["pause_session"] in chips
    assert conv.ACTIONS["just_tell"] in chips
    theory_state = _pending_state()
    ws = theory._walk_state(theory_state)
    _, tui = ctl._concept_message(ws)
    assert conv.ACTIONS["pause_session"] not in tui["chips"]  # no session to pause in theory mode


def test_theory_follow_ups_never_chain_deeper_questions():
    state = _pending_state()
    q = K.question_by_id[state.pending["question_id"]]
    turn = theory.handle_pending(state, GOOD[q.id])
    assert turn.events["verdict"] == "concept_correct" and state.pending is None


def test_example_query_names_the_pending_concept():
    state = _pending_state()
    name = K.concept_by_id[state.pending["concept_id"]].name
    assert name in theory.example_query(state, "Show an example")
    assert theory.example_query(state, "What is DFT?") is None


@pytest.mark.parametrize("message", ["Pause", "pause the quiz", "End the quiz", "I want to end the session"])
def test_pause_phrasings_pause(message):
    assert conv.classify(message) is conv.Intent.SWITCH_TO_THEORY


@pytest.mark.parametrize("message", ["Resume the key ideas", "resume quiz", "continue the quiz"])
def test_resume_phrasings_resume(message):
    assert conv.classify(message) is conv.Intent.GUIDED_CONCEPTS


def test_every_authored_adaptive_text_is_english():
    texts = [c.description + " " + c.experiment_relevance for c in K.concepts]
    texts += [q.ask for q in K.questions] + [q.scaffold for q in K.questions if q.scaffold]
    texts += [q.expected_reasoning for q in K.questions] + list(conv.ACTIONS.values())
    assert [t for t in texts if looks_non_english(t)] == []


# ======================================================= pause and resume, API


async def test_pause_keeps_the_question_and_resume_returns_to_it(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "ad-pause")
    first = await _send(client, token, classroom_id, "Test my understanding")
    thread = first["thread_id"]
    asked = first["message"]["metadata"]["ui"]["intervention"]["question_id"]
    paused = await _send(client, token, classroom_id, "Pause", thread)
    assert "pause here" in paused["message"]["content"] and "saved where you were" in paused["message"]["content"]
    assert paused["message"]["metadata"]["ui"]["chips"] == [conv.ACTIONS["resume_key_ideas"]]
    side = await _send(client, token, classroom_id, "What is a basis set?", thread)
    assert side["message"]["metadata"]["type"] == "qa"
    resumed = await _send(client, token, classroom_id, "Resume the key ideas", thread)
    assert resumed["message"]["metadata"]["type"] == "walkthrough"
    assert K.question_by_id[asked].ask in resumed["message"]["content"]


# ============================================================ practical tracker


def test_steps_come_from_each_experiments_own_procedure():
    exp08 = [r["title"] for r in practical.steps("exp08")]
    assert exp08 == ["Ethane geometry setup", "Ethane energies", "Cyclohexane geometry setup", "Cyclohexane energies"]
    assert len(practical.steps("exp01")) != len(exp08)  # never one shared list
    assert practical.kind("exp08") == "self_report"
    assert practical.kind("exp01") == "verified"
    assert practical.kind("exp07") is None  # phone-only: no software steps


def test_tracker_states():
    t = practical.tracker("exp08", practical_done=1)
    assert [s["status"] for s in t["steps"]] == ["completed", "current", "upcoming", "upcoming"]
    assert (t["completed"], t["current"], t["total"], t["status"]) == (1, 1, 4, "in_progress")
    assert practical.tracker("exp08")["status"] == "not_started"
    assert practical.tracker("exp08", practical_done=4)["status"] == "complete"
    verified = practical.tracker("exp01", session_step=1)
    assert verified["completed"] == 1 and verified["current"] == 1
    assert practical.tracker("exp01", session_step=0, session_complete=True)["status"] == "complete"
    assert practical.tracker("exp07") == {"available": False, "experiment_id": "exp07"}


async def _exp08_thread(client, make_user, scripted_backend, email="prof.track@vit.ac.in"):  # noqa: F811
    _, prof = await make_user(email)
    created = await client.post("/api/classrooms", json={"name": "T"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    resp = await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": "exp08", "message": "What is torsional strain?"},
        headers=auth(prof),
    )
    return classroom_id, prof, resp.json()["thread_id"]


async def _progress(client, token, thread):
    resp = await client.get(f"/api/chat/threads/{thread}/practical", headers=auth(token))
    assert resp.status_code == 200
    return resp.json()


async def _complete(client, token, thread, i):
    return await client.post(f"/api/chat/threads/{thread}/practical/complete", json={"step_index": i}, headers=auth(token))


async def test_completion_advances_one_step_only_after_the_backend_accepts_it(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    _, prof, thread = await _exp08_thread(client, make_user, scripted)
    start = await _progress(client, prof, thread)
    assert (start["current"], start["completed"], start["status"]) == (0, 0, "not_started")

    ok = await _complete(client, prof, thread, 0)
    assert ok.status_code == 200 and ok.json()["current"] == 1

    dup = await _complete(client, prof, thread, 0)  # double tap / stale page
    assert dup.status_code == 409 and not looks_non_english(dup.json()["detail"])
    skip = await _complete(client, prof, thread, 3)  # out of order
    assert skip.status_code == 409
    assert (await _progress(client, prof, thread))["completed"] == 1  # nothing moved

    for i in (1, 2, 3):
        assert (await _complete(client, prof, thread, i)).status_code == 200
    assert (await _progress(client, prof, thread))["status"] == "complete"
    assert (await _complete(client, prof, thread, 4)).status_code == 409


async def test_progress_survives_a_refresh_and_is_scoped_to_its_thread(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, prof, thread = await _exp08_thread(client, make_user, scripted, "prof.scope@vit.ac.in")
    await _complete(client, prof, thread, 0)
    assert (await _progress(client, prof, thread))["completed"] == 1  # a fresh read = a refresh
    other = await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": "exp08", "message": "What is a conformer?"},
        headers=auth(prof),
    )
    assert (await _progress(client, prof, other.json()["thread_id"]))["completed"] == 0


async def test_another_user_cannot_read_or_complete_my_steps(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    _, _, thread = await _exp08_thread(client, make_user, scripted, "prof.owner@vit.ac.in")
    _, intruder = await make_user("s.intruder@vitstudent.ac.in")
    assert (await client.get(f"/api/chat/threads/{thread}/practical", headers=auth(intruder))).status_code == 404
    assert (await _complete(client, intruder, thread, 0)).status_code == 404


async def test_switching_experiment_shows_that_experiments_procedure(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, prof, thread08 = await _exp08_thread(client, make_user, scripted, "prof.switch@vit.ac.in")
    resp = await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": "exp01", "message": "What is a salt bridge?"},
        headers=auth(prof),
    )
    p01 = await _progress(client, prof, resp.json()["thread_id"])
    p08 = await _progress(client, prof, thread08)
    assert p01["kind"] == "verified" and p08["kind"] == "self_report"
    assert [s["title"] for s in p01["steps"]] != [s["title"] for s in p08["steps"]]


@pytest.mark.parametrize("message", ["Explain this step: Ethane energies", "I'm stuck on this step: Ethane energies", "I've completed this step"])
async def test_chat_messages_never_advance_the_tracker(client, make_user, scripted, message):  # noqa: F811
    """Only the completion endpoint records a step; explaining, being stuck, or
    typing "done" in the chat changes nothing."""
    scripted(ENGLISH)
    classroom_id, prof, thread = await _exp08_thread(client, make_user, scripted, "prof.noadv@vit.ac.in")
    await _complete(client, prof, thread, 0)
    await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": "exp08", "message": message, "thread_id": thread},
        headers=auth(prof),
    )
    assert (await _progress(client, prof, thread))["completed"] == 1


async def test_verified_experiments_refuse_a_self_reported_completion(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    _, prof = await make_user("prof.verified@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "V"}, headers=auth(prof))
    resp = await client.post(
        "/api/chat/messages",
        json={"classroom_id": created.json()["id"], "experiment_id": "exp01", "message": "What is a salt bridge?"},
        headers=auth(prof),
    )
    refused = await _complete(client, prof, resp.json()["thread_id"], 0)
    assert refused.status_code == 409
    assert "report your results in the chat" in refused.json()["detail"]


# ====================================================== the two stay separate


async def test_quiz_state_and_practical_progress_are_independent(client, make_user, scripted, db):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "ad-indep")
    first = await _send(client, token, classroom_id, "What is HOMO?")  # opens a theory reflection
    thread_id = first["thread_id"]
    before = (await db.scalars(select(ChatThread).where(ChatThread.id == thread_id))).one().state
    assert before.get("pending")
    # Exp7 on phones has no practical: a completion is refused and the quiz is untouched.
    assert (await _complete(client, token, thread_id, 0)).status_code == 409
    await db.refresh((await db.scalars(select(ChatThread).where(ChatThread.id == thread_id))).one())
    after = (await db.scalars(select(ChatThread).where(ChatThread.id == thread_id))).one().state
    assert after.get("pending") == before.get("pending") and after.get("practical_done", 0) == 0


async def test_an_unrelated_question_changes_neither_state(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, prof, thread = await _exp08_thread(client, make_user, scripted, "prof.unrel@vit.ac.in")
    await _complete(client, prof, thread, 0)
    await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": "exp08", "message": "What is a basis set?", "thread_id": thread},
        headers=auth(prof),
    )
    assert (await _progress(client, prof, thread))["completed"] == 1


def test_tracker_text_is_english():
    for exp in ("exp01", "exp03", "exp08"):
        for row in practical.steps(exp):
            assert not looks_non_english(row["title"] + " " + row["detail"])
