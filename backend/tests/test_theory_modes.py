"""Phone-only theory mode for Experiments 2 and 4 (students with no apparatus).

Exp7 already had this; Exp2 (ester hydrolysis kinetics) and Exp4 (iron in steel
by potentiometry) now have the same: authored, phone-safe concept content, a
key-ideas session, theory Q&A with one Socratic follow-up, and an overview of
how the practical is normally done. Everything here is deterministic.
"""

from __future__ import annotations

import pytest

from backend.config import reload_settings
from backend.retrieval.pipeline import answer_question
from backend.scope.classifier import classify_scope
from backend.scope.statuses import AnswerStatus
from backend.socratic_engine import procedure
from backend.socratic_engine.knowledge import get_knowledge, phone_safe
from backend.socratic_engine.knowledge.phone_safe import external_dependency
from backend.socratic_engine.knowledge.types import QUESTION_TYPES
from backend.socratic_engine.pedagogy import policy
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough.navigation import Nav, NavCommand
from backend.tests.concept_answers_theory import GOOD
from backend.tests.test_chat_isolation import auth
from backend.tests.test_walkthrough_api import _student

EXPS = ["exp02", "exp04"]
LABEL = {"exp02": "Experiment 2", "exp04": "Experiment 4"}


# ------------------------------------------------------------ authored content


@pytest.mark.parametrize("exp", EXPS)
def test_knowledge_is_structurally_consistent(exp):
    k = get_knowledge(exp)
    assert k is not None and k.validate() == []
    assert len(k.stages) == 6 and len(k.assessment) >= 7
    assert len(k.starter_questions) >= 6 and k.closing_summary and k.topics_hint


@pytest.mark.parametrize("exp", EXPS)
def test_every_question_type_is_authored(exp):
    k = get_knowledge(exp)
    assert {q.qtype for q in k.questions} == set(QUESTION_TYPES)


@pytest.mark.parametrize("exp", EXPS)
def test_every_question_is_phone_safe(exp):
    k = get_knowledge(exp)
    unsafe = {q.id: phone_safe.why_not_phone_safe(q) for q in k.questions if not phone_safe.is_phone_safe(q)}
    assert unsafe == {}


@pytest.mark.parametrize("exp", EXPS)
def test_all_other_student_facing_authored_text_is_clean(exp):
    k = get_knowledge(exp)
    texts = [c.description for c in k.concepts]
    texts += [t for m in k.misconceptions for t in (m.probe, m.correction)]
    texts += [t for s in k.stages for t in (s.title, s.context)]
    texts += [k.closing_summary]
    assert [(t, external_dependency(t)) for t in texts if external_dependency(t)] == []


@pytest.mark.parametrize("exp", EXPS)
def test_procedure_overview_is_authored_per_experiment(exp):
    text = procedure.overview(exp)
    assert LABEL[exp] in text and "You do not need to do any of them here" in text
    assert "Gabedit" not in text and "ORCA" not in text and "Avogadro" not in text
    assert len(procedure.stages_for(exp)) == 6


@pytest.mark.parametrize("exp", EXPS)
def test_every_authored_answer_key_accepts_a_good_answer_and_rejects_junk(exp):
    k = get_knowledge(exp)
    ids = {q.id for q in k.questions}
    assert ids <= set(GOOD), f"missing model answers: {ids - set(GOOD)}"
    for q in k.questions:
        assert policy.classify_answer(q, GOOD[q.id], k).label == "CORRECT", q.id
        for junk in ("i dont know", "yes", "ok", "no", "not sure", "next", "hmm", ""):
            assert policy.classify_answer(q, junk, k).label != "CORRECT", (q.id, junk)


MISCONCEPTION_STATEMENTS = [
    ("exp02", "q2_first_order_meaning", "the order is the number of molecules in the balanced equation", "order_is_equation_count"),
    ("exp02", "q2_order_vs_molecularity", "order is the same as molecularity", "molecularity_is_order"),
    ("exp02", "q2_k_const", "the rate constant decreases as the reactant is used up", "k_changes_with_conc"),
    ("exp02", "q2_catalyst_role", "the acid catalyst is used up during the reaction", "catalyst_used_up"),
    ("exp02", "q2_slope_sign", "the rate constant is negative because the slope is negative", "k_is_negative"),
    ("exp04", "q4_endpoint_derivative", "the endpoint is where the highest emf is", "endpoint_at_max_emf"),
    ("exp04", "q4_normality_calc", "normality is the same as molarity", "normality_is_molarity"),
]


@pytest.mark.parametrize("exp,qid,statement,expected", MISCONCEPTION_STATEMENTS)
def test_known_misconceptions_are_detected(exp, qid, statement, expected):
    k = get_knowledge(exp)
    c = policy.classify_answer(k.question_by_id[qid], statement, k)
    assert (c.label, c.misconception_id) == ("MISCONCEPTION", expected)


@pytest.mark.parametrize("exp", EXPS)
def test_starter_questions_stay_on_their_own_experiment(exp):
    for q in get_knowledge(exp).starter_questions:
        decision = classify_scope(q, active_experiment=exp)
        assert decision.experiment_id in (exp, None), (q, decision.experiment_id)
        assert decision.is_in_scope, q


# ------------------------------------------------------------ a whole session


def _run_session(exp, answer_for):
    state = ctl.new_state("stu", mode="concept", experiment_id=exp)
    msgs = [ctl.start(state).reply]
    asked: list[str] = []
    for _ in range(80):
        if state.status == "done":
            break
        if state.phase == "concept":
            qid = state.concept["question_id"]
        elif state.phase == "assess":
            qid = state.assess["queue"][state.assess["i"]]
        else:  # pragma: no cover - the session never idles
            raise AssertionError(state.phase)
        asked.append(qid)
        msgs.append(ctl.take_turn(state, answer_for(qid)).reply)
    return state, msgs, asked


@pytest.mark.parametrize("exp", EXPS)
def test_a_complete_session_needs_nothing_outside_the_page(exp):
    state, msgs, asked = _run_session(exp, lambda qid: GOOD[qid])
    assert state.status == "done" and len(asked) >= 8
    assert LABEL[exp] in msgs[0] and "thinking session" in msgs[0] and "apparatus or software" in msgs[0]
    assert [m for m in msgs if external_dependency(m)] == []
    k = get_knowledge(exp)
    assert all(phone_safe.is_phone_safe(k.question_by_id[qid]) for qid in asked)
    assert f"ideas behind {LABEL[exp]}" in msgs[-1]


@pytest.mark.parametrize("exp", EXPS)
def test_a_struggling_or_misconception_filled_session_still_finishes_cleanly(exp):
    wrong = "the endpoint is where the highest emf is and the order is the number of molecules in the equation"
    for answer in ("hmm not sure what that means", wrong):
        state, msgs, _ = _run_session(exp, lambda qid, a=answer: a)
        assert state.status == "done"
        assert [m for m in msgs if external_dependency(m)] == []


@pytest.mark.parametrize("exp", EXPS)
def test_key_ideas_navigation_covers_the_six_parts(exp):
    state = ctl.new_state("stu", mode="concept", experiment_id=exp)
    ctl.start(state)
    out = ctl.take_turn(state, "go to part 4")
    assert "Part 4 of 6" in out.reply
    out = ctl.take_turn(state, "go to part 9")
    assert "There are 6 parts" in out.reply


@pytest.mark.parametrize("exp", EXPS)
def test_procedure_overview_walks_its_own_stages(exp):
    pos, text, _ = procedure.navigate(0, NavCommand(Nav.NEXT), exp)
    assert pos == 1 and "Stage 1 of 6" in text
    pos, text, _ = procedure.navigate(pos, NavCommand(Nav.GOTO, target=5), exp)
    assert pos == 5 and "Stage 5 of 6" in text


# ------------------------------------------------------------ answers stay in the theory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exp,question",
    [
        ("exp02", "why is ester hydrolysis pseudo first order"),
        ("exp02", "why do we plot log of v infinity minus vt against time"),
        ("exp04", "why does permanganate act as its own indicator"),
        ("exp04", "why do we use a reference electrode"),
    ],
)
async def test_theory_questions_are_answered_from_the_authored_notes(exp, question):
    result = await answer_question(question, active_experiment=exp, use_llm=False)
    assert result.status in (AnswerStatus.ADJACENT_SUPPORTED, AnswerStatus.IN_SCOPE_SUPPORTED)
    assert result.citations


# ------------------------------------------------------------ through the API


@pytest.fixture
def phone_on(fake_llm, monkeypatch):
    fake_llm.reply = (
        "A catalyst speeds a reaction by giving it an easier path, and it is not used up overall. "
        "That is why the acid does not run out as the hydrolysis goes on."
    )
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


async def _lab(client, make_user, exp, tag):
    """A classroom whose active class session is `exp`, with one student."""
    _, prof = await make_user(f"prof.{tag}@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "C"}, headers=auth(prof))
    classroom_id, code = created.json()["id"], created.json()["student_join_code"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start", json={"experiment_id": exp}, headers=auth(prof)
    )
    assert started.status_code == 201
    _, token = await _student(client, make_user, code, f"s.{tag}@vitstudent.ac.in")
    return classroom_id, token


async def _send(client, token, classroom_id, exp, message, thread_id=None):
    body = {"classroom_id": classroom_id, "experiment_id": exp, "message": message}
    if thread_id:
        body["thread_id"] = thread_id
    resp = await client.post("/api/chat/messages", json=body, headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("exp", EXPS)
async def test_the_catalogue_offers_guided_learning_and_starters(client, make_user, exp, phone_on):
    _, prof = await make_user(f"prof.cat-{exp}@vit.ac.in")
    resp = await client.get("/api/classrooms/experiments", headers=auth(prof))
    entry = next(e for e in resp.json()["experiments"] if e["id"] == exp)
    assert entry["guided_learning"] is True
    assert entry["suggestions"] == list(get_knowledge(exp).starter_questions)


@pytest.mark.asyncio
@pytest.mark.parametrize("exp", EXPS)
async def test_key_ideas_session_over_the_api_is_phone_safe(client, make_user, exp, phone_on):
    classroom_id, token = await _lab(client, make_user, exp, f"ki-{exp}")
    first = await _send(client, token, classroom_id, exp, "Guide me through the key ideas")
    content = first["message"]["content"]
    assert LABEL[exp] in content and "Part 1 of 6" in content
    assert external_dependency(content) is None
    assert first["message"]["metadata"]["ui"]["kind"] == "concept"


@pytest.mark.asyncio
@pytest.mark.parametrize("exp", EXPS)
async def test_procedure_request_gets_the_overview_not_a_stepper(client, make_user, exp, phone_on):
    classroom_id, token = await _lab(client, make_user, exp, f"pr-{exp}")
    out = await _send(client, token, classroom_id, exp, "How do I actually perform this experiment?")
    content = out["message"]["content"]
    assert out["message"]["metadata"]["transition_reason"] == "procedure overview"
    assert f"How {LABEL[exp]} is normally performed" in content
    nxt = await _send(client, token, classroom_id, exp, "next", out["thread_id"])
    assert "Stage 1 of 6" in nxt["message"]["content"]
    jump = await _send(client, token, classroom_id, exp, "go to step 5", out["thread_id"])
    assert "Stage 5 of 6" in jump["message"]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exp,question",
    [("exp02", "What is a catalyst?"), ("exp04", "What is the Nernst equation?")],
)
async def test_a_theory_question_gets_an_answer_and_a_phone_safe_followup(client, make_user, exp, question, phone_on):
    classroom_id, token = await _lab(client, make_user, exp, f"th-{exp}")
    out = await _send(client, token, classroom_id, exp, question)
    content = out["message"]["content"]
    assert out["message"]["metadata"]["mode"] == "theory"
    assert "Think about this" in content
    assert external_dependency(content) is None


# ------------------------------------------------------------ the CLAUDE.md advisory-call boundary


@pytest.mark.parametrize("exp,expect_advisory", [("exp07", True), ("exp02", False), ("exp04", False)])
def test_the_advisory_model_call_stays_confined_to_exp07(exp, expect_advisory):
    """An unclassifiable free-text answer may be handed to the single advisory
    model call only for Exp7 (CLAUDE.md); Exp2/Exp4 get the authored fallback."""
    state = ctl.new_state("stu", mode="concept", experiment_id=exp)
    ctl.start(state)
    result = ctl.take_turn(state, "it depends on various factors in a complicated way overall")
    assert (result.realise is not None) is expect_advisory
    assert result.reply  # the authored reply is there either way
