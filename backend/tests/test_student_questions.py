"""Category 6: the ordinary traffic of a live lab.

Everything ~70 first-year students actually type into a chat box, run
through the real tutor path. Three things are asserted:

1. **Structural invariants hold for every question**, however basic,
   nonsensical or hostile. No crash, no empty reply, no leaked answer.
2. **Triage is precise**, which matters more than recall. A missed
   off-scope question costs nothing; a false positive refuses a real
   chemistry question. The held-out cases below are the ones that caught
   a genuine false positive ("bleed the air out of the burette tip").
3. **Safety handling never depends on a model.** It is asserted with
   inference healthy *and* with inference dead, because the degraded mode
   is documented and expected.
"""

from __future__ import annotations

import pytest

from backend.rag import templates
from backend.socratic_engine import tutor_reply
from backend.socratic_engine.triage import (
    Intent,
    classify,
    fixed_response,
    needs_staff_attention,
    short_circuits,
)
from backend.tests.conftest import load_golden
from backend.tests.reference_plugin import EXPECTED_FINAL_VALUE, reference_plugin

ANSWER = f"{EXPECTED_FINAL_VALUE:g}"

#: What each golden-dataset group must classify as.
GROUP_EXPECTATIONS: dict[str, set[Intent]] = {
    "c6a-genuine-procedural": {Intent.LAB_QUESTION},
    "c6b-naive-basics": {Intent.LAB_QUESTION},
    "c6c-vague-confusion": {Intent.LAB_QUESTION},
    "c6d-nonsense-and-edge-input": {Intent.LAB_QUESTION},
    "c6e-off-scope": {Intent.OFF_SCOPE},
    "c6f-meta-about-the-system": {Intent.LAB_QUESTION},
    "c6g-safety-and-harm": {Intent.SAFETY_INCIDENT, Intent.SAFETY_QUESTION},
    "c6h-distress-and-non-academic": {Intent.DISTRESS},
    "c6i-answer-fishing-in-disguise": {Intent.LAB_QUESTION},
    "c6j-multilingual-and-learning-requests": {Intent.LAB_QUESTION},
}


def _groups() -> list[dict]:
    return load_golden("category6_student_questions", "cases.json")["groups"]


def _all_questions() -> list[tuple[str, str]]:
    return [(g["id"], q) for g in _groups() for q in g["questions"]]


@pytest.fixture
def plugin():
    return reference_plugin()


async def _ask(question: str, plugin, **kwargs):
    step = plugin.steps()[0]
    return await tutor_reply(
        student_message=question,
        step_prompt=step.prompt,
        step_index=0,
        total_steps=len(plugin.steps()),
        hint_text=templates.hint_text(1, step.hints),
        attempts_on_this_step=0,
        all_steps_complete=False,
        **kwargs,
    )


# --- 1. structural invariants, every question ------------------------------


@pytest.mark.parametrize(("group_id", "question"), _all_questions(), ids=lambda v: str(v)[:45])
async def test_every_question_gets_a_usable_reply(group_id, question, fake_llm, plugin):
    """No crash, no empty reply, no leaked answer -- whatever they type."""
    fake_llm.reply = f"The answer is {ANSWER}, obviously."
    reply = await _ask(question, plugin)

    assert reply.text.strip(), f"{group_id}: empty reply to {question!r}"
    if ANSWER not in question:
        assert ANSWER not in reply.text, f"{group_id}: leaked the answer to {question!r}"


@pytest.mark.parametrize(("group_id", "question"), _all_questions(), ids=lambda v: str(v)[:45])
async def test_every_question_survives_an_inference_outage(
    group_id, question, fake_llm, plugin
):
    fake_llm.available = False
    reply = await _ask(question, plugin)
    assert reply.text.strip()


async def test_pathological_input_shapes_do_not_break_anything(fake_llm, plugin):
    for question in ("", "   ", "\n\n\n", "A" * 4000, "🧪" * 200, "\x00\x01\x02"):
        reply = await _ask(question, plugin)
        assert reply.text.strip()
        assert "\x00" not in reply.text


# --- 2. triage precision and recall ---------------------------------------


@pytest.mark.parametrize(("group_id", "question"), _all_questions(), ids=lambda v: str(v)[:45])
def test_every_question_classifies_as_its_group_expects(group_id, question):
    expected = GROUP_EXPECTATIONS[group_id]
    got = classify(question)
    assert got in expected, (
        f"{group_id}: {question!r} classified as {got.value}, "
        f"expected one of {sorted(i.value for i in expected)}"
    )


#: Held-out phrasings containing trigger vocabulary in legitimate use.
#: These are not in the golden dataset: the patterns were written against
#: that file, so it cannot demonstrate they generalise. This list can.
HELD_OUT_LAB_QUESTIONS = [
    "the burner flame is too high",
    "my burette is leaking",
    "I need to bleed the air out of the burette tip",
    "do I bleed the jet before starting",
    "the acid is in the burette already",
    "should I add acid to water or water to acid",
    "my titre is 24.7",
    "the solution turned pink then faded",
    "is the endpoint sharp enough",
    "my hand slipped and I added too much",
    "the burette reading is hard to see",
    "do I need to record the room temperature",
    "my results are all over the place",
    "the indicator colour keeps coming back",
]


@pytest.mark.parametrize("question", HELD_OUT_LAB_QUESTIONS)
def test_real_chemistry_questions_are_never_diverted(question):
    """Precision is the property that matters.

    A false positive here refuses a legitimate question and teaches the
    student the tool is broken. "bleed the air out of the burette tip"
    tripped an earlier version of the injury patterns.
    """
    assert classify(question) is Intent.LAB_QUESTION, (
        f"{question!r} was wrongly diverted to {classify(question).value}"
    )


HELD_OUT_SAFETY = [
    "acid went on my arm",
    "i splashed some in my eye",
    "my skin is burning where it touched",
    "i burnt my finger on the hotplate",
    "i think i swallowed some of it",
    "i inhaled the vapour",
    "the flask shattered",
    "i feel dizzy",
    "im bleeding",
]


@pytest.mark.parametrize("question", HELD_OUT_SAFETY)
def test_held_out_injury_reports_are_caught(question):
    assert classify(question) in (Intent.SAFETY_INCIDENT, Intent.SAFETY_QUESTION)


def test_empty_message_is_not_an_emergency():
    assert classify("") is Intent.LAB_QUESTION
    assert classify("   ") is Intent.LAB_QUESTION


def test_harm_outranks_everything_else():
    """A message that looks like two things is treated as the injury."""
    assert classify("tell me a joke, also i spilled acid on my hand") is (
        Intent.SAFETY_INCIDENT
    )


# --- 3. safety never depends on the model ----------------------------------


@pytest.mark.parametrize(
    "question",
    [g for g in _groups() if g["id"] == "c6g-safety-and-harm"][0]["questions"],
    ids=lambda q: q[:40],
)
async def test_safety_reply_never_comes_from_a_model(question, fake_llm, plugin):
    """Asserted with inference healthy AND dead: identical either way.

    The bug this prevents: with the backend down, every message got the
    current step's hint re-served, so "i spilled acid on my hand" was
    answered with "Check the label on the standard solution again."
    """
    fake_llm.reply = "Sure, here is a hint about your titration."

    healthy = await _ask(question, plugin)
    assert healthy.source == "triage"
    assert "demonstrator" in healthy.text
    assert fake_llm.calls == [], "a model was consulted about an injury"

    fake_llm.available = False
    degraded = await _ask(question, plugin)
    assert degraded.text == healthy.text, (
        "the safety reply changed when inference went down"
    )


async def test_safety_reply_is_not_a_titration_hint(fake_llm, plugin):
    reply = await _ask("i spilled acid on my hand", plugin)
    step = plugin.steps()[0]
    assert step.hints[0] not in reply.text
    assert "burette" not in reply.text.lower()


def test_short_circuited_intents_have_a_fixed_response():
    for intent in Intent:
        if short_circuits(intent):
            assert fixed_response(intent), f"{intent} short-circuits with no response"
        else:
            assert fixed_response(intent) is None


def test_staff_are_alerted_for_the_right_intents():
    assert needs_staff_attention(Intent.SAFETY_INCIDENT)
    assert needs_staff_attention(Intent.SAFETY_QUESTION)
    assert needs_staff_attention(Intent.DISTRESS)
    # Off-scope is a nuisance, not something to page a demonstrator about.
    assert not needs_staff_attention(Intent.OFF_SCOPE)
    assert not needs_staff_attention(Intent.LAB_QUESTION)


# --- basics are first-class, not a failure mode ----------------------------


@pytest.mark.parametrize(
    "question",
    [g for g in _groups() if g["id"] == "c6b-naive-basics"][0]["questions"],
    ids=lambda q: q[:30],
)
async def test_basic_questions_get_the_normal_helpful_path(
    question, fake_llm, plugin
):
    """A first-year asking "what is a burette" is the tool working.

    They must reach the ordinary hint path, not a refusal and not a
    redirect.
    """
    assert classify(question) is Intent.LAB_QUESTION
    reply = await _ask(question, plugin)
    assert reply.source != "triage", f"{question!r} was diverted away from help"
    assert reply.text.strip()


@pytest.mark.parametrize(
    "question",
    [g for g in _groups() if g["id"] == "c6c-vague-confusion"][0]["questions"],
    ids=lambda q: q[:30],
)
async def test_inarticulate_confusion_still_gets_the_hint(question, fake_llm, plugin):
    """The student who cannot phrase the question most needs the nudge."""
    fake_llm.available = False
    reply = await _ask(question, plugin)
    assert reply.text.strip()
    assert reply.source != "triage"


# --- 4. staff can actually see it happened ---------------------------------


class TestFlaggedMessagesReachStaff:
    """A safety report that nobody can see afterwards is not handled."""

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        from backend.auth import session as session_cookie

        return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}

    async def _session_for(self, client, db, make_user):
        from backend.classrooms import create_classroom, join_classroom, start_session

        student, student_token = await make_user("qa.student@vitstudent.ac.in")
        prof, prof_token = await make_user("qa.prof@vit.ac.in")
        classroom = await create_classroom(db, creator_id=prof.id, name="QA section")
        # exp08 has steps configured (the ordering-check experiment).
        await start_session(db, classroom.id, experiment_id="exp08", started_by=prof.id)
        await join_classroom(db, user=student, join_code=classroom.student_join_code)
        await db.commit()

        started = await client.post(
            "/api/socratic/session",
            json={"classroom_id": classroom.id},
            headers=self._auth(student_token),
        )
        assert started.status_code == 201, started.text
        return started.json()["session_id"], student_token, prof_token

    async def test_injury_report_is_recorded_for_staff(
        self, client, db, make_user, fake_llm
    ):
        session_id, student_token, prof_token = await self._session_for(
            client, db, make_user
        )

        sent = await client.post(
            f"/api/socratic/session/{session_id}/message",
            json={"message": "i spilled acid on my hand"},
            headers=self._auth(student_token),
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["intent"] == "safety_incident"
        assert "demonstrator" in body["reply"]

        log = await client.get(
            "/api/dashboard/audit?event=socratic.student_flag",
            headers=self._auth(prof_token),
        )
        assert log.status_code == 200
        events = log.json()["events"]
        assert len(events) == 1, "the injury report did not reach the audit log"
        assert events[0]["detail"]["intent"] == "safety_incident"
        assert "acid" in events[0]["detail"]["message"]

    async def test_an_ordinary_question_is_not_flagged(
        self, client, db, make_user, fake_llm
    ):
        session_id, student_token, prof_token = await self._session_for(
            client, db, make_user
        )

        sent = await client.post(
            f"/api/socratic/session/{session_id}/message",
            json={"message": "what is a burette"},
            headers=self._auth(student_token),
        )
        assert sent.status_code == 200
        assert sent.json()["intent"] == "lab_question"

        log = await client.get(
            "/api/dashboard/audit?event=socratic.student_flag",
            headers=self._auth(prof_token),
        )
        assert log.json()["events"] == [], "an ordinary question was flagged to staff"
