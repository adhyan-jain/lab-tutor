"""A patient, compassionate tutor whose teaching changes when a student struggles.

Tone cannot be asserted with exact strings, so these tests pin what can be
checked deterministically: which strategy runs (routing, state, the per-message
SUPPORT line, authored feedback paths), that warmth is matched to the moment
(no reassurance on a plain factual question), honesty (a wrong answer is never
called right), English-only output, concise practical steps, preserved quiz /
practical / reflection state, and the temperature each provider receives.
No network, no paid calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.config import Settings, reload_settings
from backend.llm import telemetry
from backend.llm.client import OpenAIBackend, openai_accepts_temperature
from backend.rag import phrasing
from backend.rag.language import looks_non_english
from backend.rag.phrasing import TUTOR_PERSONA
from backend.retrieval import pipeline
from backend.retrieval.pipeline import GENERAL_KNOWLEDGE, SUPPORT, answer_question
from backend.socratic_engine import chat as socratic_chat
from backend.socratic_engine import conversation as conv
from backend.socratic_engine import practical, realise, theory
from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.pedagogy import state as pstate
from backend.socratic_engine.walkthrough import controller as ctl
from backend.tests.concept_answers import GOOD
from backend.tests.test_adaptive_and_practical import _complete, _exp08_thread, _progress, _session
from backend.tests.test_chat_isolation import _setup, auth  # noqa: F401
from backend.tests.test_openai_provider import _response, fake_openai, gpt_settings  # noqa: F401
from backend.tests.test_reflection_routing import _pending_state
from backend.tests.test_student_feedback import (  # noqa: F401
    ENGLISH,
    HINGLISH,
    _events,
    _stream,
    _streamed_text,
    scripted,
)
from backend.tests.test_walkthrough_api import _send

K = get_knowledge("exp07")
PRAISE_FOR_WRONG = ("correct", "that's right", "exactly right", "well done", "perfect")


def _q(state):
    return K.question_by_id[state.concept["question_id"]]


# ===================================================== shared personality


@pytest.mark.parametrize(
    "prompt",
    [pipeline.SYSTEM_PROMPT, phrasing.SYSTEM_PROMPT, socratic_chat.SYSTEM_PROMPT, realise._SYSTEM],
    ids=["qa", "diagnosis", "socratic", "concept"],
)
def test_one_shared_persona_reaches_every_student_facing_prompt(prompt):
    assert TUTOR_PERSONA in prompt
    assert phrasing.ENGLISH_ONLY_RULE in prompt  # the persona never replaces the language rule


def test_the_persona_asks_for_matched_warmth_honesty_and_a_changed_approach():
    for idea in (
        "answer an ordinary question directly",
        "with no reassurance",
        "change the approach",
        "never call a wrong answer right",
        "Never claim progress or mastery",
        "If they ask for the answer directly, give it",
        "Respect their choice to pause or stop",
        'do not open with \\"Hey\\"'.replace("\\", ""),
    ):
        assert idea in TUTOR_PERSONA, idea


# ============================================== detecting how it is going


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("I don't know.", "uncertain"),
        ("I don't know the answer.", "uncertain"),
        ("I'm not sure.", "uncertain"),
        ("I have no idea.", "uncertain"),
        ("pata nahi", "uncertain"),
        ("मुझे नहीं पता", "uncertain"),
        ("I don't understand.", "confused"),
        ("I don't understand geometry optimization", "confused"),
        ("I'm confused.", "confused"),
        ("Bhai, mujhe samajh nahi aaya.", "confused"),
        ("मुझे समझ नहीं आया।", "confused"),
        ("Explain HOMO more simply", "confused"),
        ("I still don't get it.", "repeat"),
        ("Can you explain it again?", "repeat"),
        ("This is too difficult.", "overwhelmed"),
        ("I don't understand anything.", "overwhelmed"),
        ("I'm not understanding anything. This experiment is too difficult.", "overwhelmed"),
        ("I'm getting everything wrong.", "frustrated"),
        ("I can't do this.", "frustrated"),
    ],
)
def test_difficulty_is_recognised(message, kind):
    assert conv.difficulty_kind(message) == kind


@pytest.mark.parametrize(
    "message",
    [
        "What is a basis set?",
        "What is Avogadro?",
        "Thanks, I understand now.",
        "Staggered",
        "ok",
        "yes",
        "HOMO is the highest occupied orbital",
        "I don't know exactly but staggered is lower because the bonds are further apart and repel less",
    ],
)
def test_ordinary_questions_answers_and_thanks_are_not_difficulty(message):
    assert conv.difficulty_kind(message) is None


@pytest.mark.parametrize("message", ["I want to pause", "Can we stop for now", "let's take a break", "Pause"])
def test_a_wish_to_stop_is_a_pause(message):
    assert conv.is_pause_request(message)
    assert conv.classify(message) is conv.Intent.SWITCH_TO_THEORY


# =============================================== quiz: authored feedback


def test_case1_i_dont_know_is_normalised_and_gets_a_manageable_next_step():
    state = _session()
    q = _q(state)
    r = ctl.take_turn(state, "I don't know")
    assert r.reply.startswith(ctl._UNSURE_OPENERS) and q.scaffold in r.reply
    assert state.concept["question_id"] == q.id  # same question, another way in


def test_case2_a_wrong_answer_is_corrected_without_praise():
    state = _pending_state()
    q = K.question_by_id[state.pending["question_id"]]
    wrong = next(m.statement for m in K.misconceptions if m.concept_id == q.concept_id) if any(
        m.concept_id == q.concept_id for m in K.misconceptions
    ) else "LUMO is the full orbital and HOMO is the empty one"
    turn = theory.handle_pending(state, wrong)
    text = turn.reply.lower()
    assert not any(p in text for p in PRAISE_FOR_WRONG)
    assert turn.events["pedagogy"]["classification"] in ("MISCONCEPTION", "UNCLEAR", "PARTIAL")


def test_case3_a_partial_answer_is_acknowledged_and_the_gap_targeted():
    state = _pending_state()
    q = K.question_by_id[state.pending["question_id"]]
    turn = theory.handle_pending(state, "HOMO stands for Highest Occupied Molecular Orbital.")
    assert turn.reply.startswith(ctl._PARTIAL_OPENERS) and q.scaffold in turn.reply


def test_case4_still_not_understanding_changes_the_approach():
    state = _session()
    q = _q(state)
    first = ctl.take_turn(state, "I don't understand")
    assert first.events["verdict"] == "concept_simplified"
    second = ctl.take_turn(state, "I still don't get it")
    assert second.events["verdict"] == "concept_explained"  # worked reasoning, not the same simplification
    assert q.expected_reasoning in second.reply and second.reply != first.reply


@pytest.mark.parametrize(("message", "opener"), [
    ("This is too difficult.", "overwhelmed"),
    ("I'm getting everything wrong.", "frustrated"),
    ("Can you explain it again?", "repeat"),
])
def test_cases5_6_overwhelm_and_frustration_slow_down_without_grading(message, opener):
    state = _session()
    q = _q(state)
    misses_before = pstate.ConceptStates.from_dict(state.concepts).get(q.concept_id).misses.get(q.id, 0)
    r = ctl.take_turn(state, message)
    assert r.reply.startswith(ctl._STRUGGLE_OPENERS[opener])
    assert "easier way in" in r.reply and state.concept["question_id"] == q.id
    assert pstate.ConceptStates.from_dict(state.concepts).get(q.concept_id).misses.get(q.id, 0) == misses_before
    assert conv.ACTIONS["pause_session"] in r.ui["chips"]  # stopping is always an option


def test_case8_a_direct_answer_is_given_when_asked():
    state = _session()
    q = _q(state)
    r = ctl.take_turn(state, "just tell me")
    assert q.expected_reasoning in r.reply and r.events["verdict"] == "concept_explained"


def test_case14_repeated_wrong_answers_switch_to_a_worked_explanation():
    state = _session()
    q = _q(state)
    first = ctl.take_turn(state, "banana banana")
    second = ctl.take_turn(state, "banana banana")
    assert first.events["verdict"] in ("concept_scaffold", "concept_probe")
    assert second.events["verdict"] == "concept_explained"
    assert "walk through it together" in second.reply and second.reply != first.reply


def test_feedback_openers_are_varied_honest_and_english():
    openers = list(ctl._UNSURE_OPENERS) + list(ctl._MISCONCEPTION_OPENERS) + list(ctl._PARTIAL_OPENERS)
    openers += list(ctl._STRUGGLE_OPENERS.values())
    assert len(set(openers)) == len(openers) and len(ctl._UNSURE_OPENERS) > 1
    for text in ctl._MISCONCEPTION_OPENERS:
        assert not any(p in text.lower() for p in PRAISE_FOR_WRONG)
    assert not [t for t in openers if looks_non_english(t) or t.lower().startswith("hey")]


def test_case11_an_unrelated_question_during_the_quiz_keeps_the_quiz():
    state = _session()
    q = _q(state)
    r = ctl.take_turn(state, "What is a basis set?")
    assert r.events["verdict"] == "side_question" and state.concept["question_id"] == q.id


# ============================================ Q&A: the per-message strategy


@pytest.mark.parametrize("kind", sorted(SUPPORT))
def test_every_struggle_has_its_own_strategy(kind):
    assert SUPPORT[kind].startswith("SUPPORT:") and not looks_non_english(SUPPORT[kind])


async def test_case7_a_plain_factual_question_gets_no_reassurance(scripted):  # noqa: F811
    backend = scripted(ENGLISH)
    await answer_question("What is Avogadro?", active_experiment="exp07")
    user = backend.calls[-1]["user"]
    assert "SUPPORT:" not in user and TUTOR_PERSONA in backend.calls[-1]["system"]


@pytest.mark.parametrize(("message", "kind"), [
    ("I don't know what geometry optimization is", "uncertain"),
    ("I don't understand geometry optimization", "confused"),
    ("This experiment is too difficult", "overwhelmed"),
    ("I'm getting everything wrong", "frustrated"),
])
async def test_struggle_messages_get_their_strategy_in_the_prompt(scripted, message, kind):  # noqa: F811
    backend = scripted(ENGLISH)
    await answer_question(message, active_experiment="exp07")
    assert SUPPORT[kind] in backend.calls[-1]["user"]


async def test_case4_explain_again_sees_the_last_explanation_to_avoid_repeating_it(scripted):  # noqa: F811
    backend = scripted(ENGLISH)
    history = (
        "STUDENT: What is geometry optimization?\n"
        "TUTOR: Geometry optimization adjusts atom positions until the energy is lowest."
    )
    await answer_question("I still don't get it", active_experiment="exp07", conversation_history=history)
    user = backend.calls[-1]["user"]
    assert SUPPORT["repeat"] in user
    assert "Do NOT repeat your last explanation" in user
    assert "adjusts atom positions until the energy is lowest" in user  # the tutor's own text only
    assert "What is geometry optimization?" not in user.split("<<<QUESTION")[0]  # no student turn added


async def test_case15_manual_questions_stay_grounded_and_cited(scripted):  # noqa: F811
    backend = scripted(ENGLISH)
    result = await answer_question("What is Gabedit used for?", active_experiment="exp07")
    assert result.citations and GENERAL_KNOWLEDGE not in backend.calls[-1]["user"]
    assert "Never state a fact that is not in the retrieved passages" in backend.calls[-1]["system"]


async def test_case16_general_chemistry_is_labelled_not_attributed(scripted):  # noqa: F811
    backend = scripted(ENGLISH)
    result = await answer_question("Where is methane commonly used in real life?", active_experiment="exp07")
    assert GENERAL_KNOWLEDGE in backend.calls[-1]["user"] and result.general_knowledge


# ================================ English for supportive replies, end to end


@pytest.mark.parametrize("message", [
    "I don't understand geometry optimization",
    "Bhai, mujhe samajh nahi aaya.",
    "मुझे समझ नहीं आया।",
    "Explain this in Hindi.",
])
async def test_cases9_10_17_support_is_streamed_and_saved_in_english(client, make_user, scripted, message):  # noqa: F811
    scripted(HINGLISH, ENGLISH)  # worst case: a Hinglish first draft
    classroom_id, _, token = await _setup(client, make_user, "cp-lang")
    events = await _stream(client, token, classroom_id, message)
    assert events[-1]["type"] == "done"
    assert not looks_non_english(_streamed_text(events))
    assert not looks_non_english(events[-1]["message"]["content"])


async def test_a_struggling_student_gets_help_not_another_question(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "cp-noq")
    out = await _send(client, token, classroom_id, "I don't understand HOMO")
    ui = out["message"]["metadata"].get("ui") or {}
    assert ui.get("kind") != "theory_followup"  # no reflection stacked on top
    assert ui.get("chips") == theory.support_chips("I don't understand HOMO")
    for chip in ui["chips"]:
        assert conv.difficulty_kind(chip) in ("confused", None)


# ================================================== pause, practical help


async def test_case13_a_pause_is_respected_and_the_session_kept(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "cp-pause")
    first = await _send(client, token, classroom_id, "Test my understanding")
    thread = first["thread_id"]
    asked = first["message"]["metadata"]["ui"]["intervention"]["question_id"]
    paused = await _send(client, token, classroom_id, "I want to pause", thread)
    text = paused["message"]["content"]
    assert "pause here" in text and "saved where you were" in text
    assert paused["message"]["metadata"]["ui"]["chips"] == [conv.ACTIONS["resume_key_ideas"]]
    resumed = await _send(client, token, classroom_id, "Resume the key ideas", thread)
    assert K.question_by_id[asked].ask in resumed["message"]["content"]


async def test_a_pause_with_nothing_running_is_still_gentle(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "cp-pause2")
    out = await _send(client, token, classroom_id, "Can we stop for now")
    assert "pause here" in out["message"]["content"] and out["message"]["metadata"]["ui"]["chips"] == []


async def test_case12_help_during_a_practical_never_advances_it(client, make_user, scripted):  # noqa: F811
    scripted(ENGLISH)
    classroom_id, prof, thread = await _exp08_thread(client, make_user, scripted, "prof.cp12@vit.ac.in")
    await _complete(client, prof, thread, 0)
    for message in ("I'm stuck on this step: Ethane energies", "I don't understand this step", "I'm confused"):
        await client.post(
            "/api/chat/messages",
            json={"classroom_id": classroom_id, "experiment_id": "exp08", "message": message, "thread_id": thread},
            headers=auth(prof),
        )
    assert (await _progress(client, prof, thread))["completed"] == 1


# ================================================= concise practical steps


def test_case18_practical_steps_stay_short_and_keywords_are_not_explained_inline():
    prompt = pipeline.SYSTEM_PROMPT
    assert "Keep the step to the action itself, in 1 to 3" in prompt
    assert "do not explain what each keyword, parameter or setting" in prompt
    assert "give it once, on its own line as a code block" in prompt
    assert "do not repeat it in later replies unless the student asks" in prompt
    assert "Explain a keyword only when the student asks about it" in prompt
    assert "never invent a menu location" in prompt and "never invent a menu path, button name or number" in prompt


def test_tracker_and_struggle_states_are_separate():
    """Struggling changes the teaching, never practical progress."""
    t = practical.tracker("exp08", practical_done=2)
    assert t["completed"] == 2
    assert practical.tracker("exp08", practical_done=2) == t  # nothing here reads the chat


# ===================================================== temperature, providers


def test_case19_20_which_openai_models_take_a_temperature():
    for model in ("gpt-4o", "gpt-4o-mini", "gpt-4.1"):
        assert openai_accepts_temperature(model)
    for model in ("gpt-5", "gpt-5-mini", "gpt-5.6-luna", "o1", "o3-mini", "o4-mini"):
        assert not openai_accepts_temperature(model)


async def test_case19_openai_receives_the_configured_temperature(gpt_settings, fake_openai, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    backend = OpenAIBackend(reload_settings())
    telemetry.begin_request()
    await backend.complete(system="s", user="u")
    assert fake_openai.calls[-1]["temperature"] == 0.5


async def test_case20_a_reasoning_model_never_receives_temperature(gpt_settings, fake_openai, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
    backend = OpenAIBackend(reload_settings())
    telemetry.begin_request()
    await backend.complete(system="s", user="u")
    assert "temperature" not in fake_openai.calls[-1]


@pytest.mark.parametrize(("model", "sent"), [("gpt-4o", True), ("gpt-5.6-luna", False)])
async def test_streaming_requests_follow_the_same_rule(gpt_settings, fake_openai, monkeypatch, model, sent):  # noqa: F811
    import asyncio

    from backend.llm.client import _stream_queue

    monkeypatch.setenv("OPENAI_MODEL", model)
    backend = OpenAIBackend(reload_settings())
    seen = {}

    async def _create(**kwargs):
        seen.update(kwargs)

        async def chunks():
            yield SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="Hi."))])

        return chunks()

    backend._client.chat.completions.create = _create
    token = _stream_queue.set(asyncio.Queue())
    try:
        telemetry.begin_request()
        await backend.complete(system="s", user="u")
    finally:
        _stream_queue.reset(token)
    assert seen.get("stream") is True
    assert ("temperature" in seen) is sent and (not sent or seen["temperature"] == 0.5)


def test_other_backends_take_the_central_setting():
    assert Settings.model_fields["llm_temperature"].default == 0.5
    from backend.llm import client

    src = __import__("inspect").getsource(client)
    # Hosted, Ollama and Vertex read settings.llm_temperature; nothing hardcodes a value.
    assert src.count("settings.llm_temperature") >= 4
    assert "temperature=0." not in src and '"temperature": 0.' not in src


def test_a_correct_answer_is_not_overpraised():
    state = _session()
    q = _q(state)
    r = ctl.take_turn(state, GOOD[q.id])
    assert r.reply.startswith("**Yes.**") and "!!" not in r.reply
