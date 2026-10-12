"""Regressions for the first live demo's student feedback.

1. Replies sometimes appeared in Hindi/Hinglish, "especially with network
   issues". Cause: the English check ran only after streaming, so the student
   watched a Hinglish draft stream in and then saw it replaced by a fallback
   that said "I couldn't put together a full explanation just now" -- which
   reads as a network failure. Now the stream is gated, a violation gets one
   corrective retry, and the fallback no longer blames the connection.
2. Students did not know what to ask: experiment-aware starter questions.
3. More interaction: learning modes and contextual next-step chips, built on
   the existing key-ideas session and reflection machinery.

Behaviour is tested with scripted model output (no network, no paid calls),
not by grepping prompts alone.
"""

from __future__ import annotations

import json
import re

import pytest

from backend.auth import session as session_cookie
from backend.config import reload_settings
from backend.llm import LLMUnavailable, telemetry
from backend.llm.client import LLMReply, _stream_queue
from backend.rag import phrasing
from backend.rag.language import EnglishStreamGate, looks_non_english
from backend.retrieval import pipeline
from backend.retrieval.pipeline import (
    COMPARISON_FORMAT,
    GENERAL_KNOWLEDGE,
    answer_question,
    is_general_knowledge_request,
)
from backend.retrieval.stable_context import build_cache_request
from backend.socratic_engine import conversation as conv
from backend.socratic_engine import theory
from backend.socratic_engine.knowledge.exp07 import STARTER_QUESTIONS
from backend.socratic_engine.suggestions import GENERIC_STARTERS
from backend.socratic_engine.walkthrough import grader
from backend.tests.test_chat_isolation import _setup, auth  # noqa: F401
from backend.tests.test_reflection_routing import _pending_state
from backend.tests.test_walkthrough_api import _send

ENGLISH = (
    "Geometry optimization moves the atoms step by step until the calculated energy stops "
    "falling, so the orbital energies are read from a realistic structure."
)
HINGLISH = (
    "Geometry optimization ka matlab hai ki atoms ko adjust karte hain taki energy kam ho "
    "jaaye aur structure stable hota hai."
)
#: English opening long enough to pass the stream's hold-back, then Hinglish.
LATE_HINGLISH = (
    "Geometry optimization is the step that finds a stable structure. Iska matlab hai ki "
    "energy kam hoti hai aur structure stable hota hai."
)
DEVANAGARI = "ज्यामिति अनुकूलन में परमाणुओं को समायोजित किया जाता है।"


class _ScriptedBackend:
    """Returns the scripted replies in order (the last one repeats) and, like
    the OpenAI backend, streams them word by word when a stream queue is set.
    An item may be an exception (raised) or (partial, exception): stream the
    partial text, then fail mid-stream."""

    name = "fake"
    supports_context_cache = False

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def complete(self, *, system, user, max_tokens=None, temperature=None, cache=None):
        telemetry.record_call()
        queue = _stream_queue.get()
        self.calls.append({"system": system, "user": user, "streamed": queue is not None})
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        partial, failure = (item if isinstance(item, tuple) else (item, None))
        if isinstance(partial, Exception):
            raise partial
        if queue is not None:
            for word in re.findall(r"\S+\s*", partial):
                await queue.put(word)
        if failure is not None:
            raise failure
        return LLMReply(text=partial, backend="fake", model="m")


@pytest.fixture
def scripted(monkeypatch):
    def install(*script):
        backend = _ScriptedBackend(*script)
        monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: backend)
        return backend

    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()
    yield install
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


def _events(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


async def _stream(client, token, classroom_id, message):
    resp = await client.post(
        "/api/chat/messages/stream",
        json={"classroom_id": classroom_id, "experiment_id": "exp07", "message": message},
        headers={"Cookie": f"{session_cookie.COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 200
    return _events(resp.text)


def _streamed_text(events) -> str:
    return "".join(e["text"] for e in events if e["type"] == "chunk")


# ============================================================ 1. language check


CHEMISTRY_ENGLISH = [
    "The Ka of acetic acid and the Ne in the noble gases are unrelated; se is not a word here.",
    "B3LYP and B3P differ in the correlation functional: B3LYP uses LYP, B3P uses P86, for CH4 and O2 alike.",
    "CH4 is tetrahedral; the HOMO-LUMO gap from B3LYP/6-31G* is larger than with HF.",
    "Use `! B3LYP 6-31G* Opt` in the ORCA input, then open the .out file in Avogadro.",
    "The energy difference is $\\Delta E = E_{LUMO} - E_{HOMO}$ in hartree or eV.",
    "O2 is a triplet, so set the spin multiplicity to 3 in Gabedit before you run ORCA.",
    "sp3 hybridization explains the 109.5 degree H-C-H angle in methane.",
    "Methane is used as a fuel, as natural gas, and as a feedstock for hydrogen and methanol.",
]


@pytest.mark.parametrize("text", CHEMISTRY_ENGLISH)
def test_chemistry_english_is_not_flagged(text):
    assert not looks_non_english(text)


def test_the_real_exp07_material_raises_no_false_positive():
    paragraphs = [p for p in build_cache_request("exp07").context_text.split("\n---\n") if p.strip()]
    assert len(paragraphs) > 20
    flagged = [p[:80] for p in paragraphs if looks_non_english(p)]
    assert flagged == []


@pytest.mark.parametrize(
    "text",
    [
        HINGLISH,
        LATE_HINGLISH,
        DEVANAGARI,
        "HOMO kya hai? Ye sabse upar wala orbital hai.",
        # Natural Hinglish with only ONE unambiguous word plus particles.
        "Geometry optimization karne se molecule ki energy minimum hoti hai.",
        "Is reaction ka Ka value se pH nikalte hain.",
    ],
)
def test_hindi_and_hinglish_are_flagged(text):
    assert looks_non_english(text)


def test_stream_gate_passes_english_through_unchanged():
    gate = EnglishStreamGate()
    out = ""
    for word in re.findall(r"\S+\s*", ENGLISH):
        text, reset = gate.feed(word)
        assert not reset
        out += text
    out += gate.flush()
    assert out == ENGLISH


def test_stream_gate_resets_a_draft_that_turns_hinglish():
    gate = EnglishStreamGate()
    shown, resets = "", 0
    for word in re.findall(r"\S+\s*", LATE_HINGLISH):
        text, reset = gate.feed(word)
        shown += text
        resets += reset
    shown += gate.flush()
    assert resets == 1 and gate.blocked
    assert not looks_non_english(shown)  # nothing Hinglish ever reached the browser


def test_stream_gate_never_shows_devanagari_and_needs_no_reset():
    gate = EnglishStreamGate()
    text, reset = gate.feed(DEVANAGARI)
    assert (text, reset) == ("", False) and gate.flush() == ""


def test_stream_gate_flushes_a_short_reply():
    gate = EnglishStreamGate()
    assert gate.feed("Yes.") == ("", False)
    assert gate.flush() == "Yes."


# ======================================================= 1. pipeline behaviour


async def test_a_hinglish_reply_gets_one_corrective_retry_and_the_english_answer_wins(scripted):
    backend = scripted(HINGLISH, ENGLISH)
    result = await answer_question("Why do we optimize the geometry?", active_experiment="exp07")
    assert result.text == ENGLISH and result.answer_source == "llm"
    assert len(backend.calls) == 2
    assert "LANGUAGE CORRECTION" in backend.calls[1]["user"]
    assert "LANGUAGE CORRECTION" not in backend.calls[0]["user"]


async def test_an_english_reply_costs_exactly_one_call(scripted):
    backend = scripted(ENGLISH)
    result = await answer_question("Why do we optimize the geometry?", active_experiment="exp07")
    assert result.text == ENGLISH and len(backend.calls) == 1


async def test_two_non_english_replies_end_in_an_english_fallback_that_does_not_blame_the_network(scripted):
    backend = scripted(HINGLISH, DEVANAGARI)
    result = await answer_question("Why do we optimize the geometry?", active_experiment="exp07")
    assert len(backend.calls) == 2
    assert result.answer_source == "extractive"
    assert result.text.startswith("Here is the most relevant part of the lab material")
    assert "just now" not in result.text and not looks_non_english(result.text)


async def test_a_real_outage_still_says_so(scripted):
    scripted(LLMUnavailable("provider down"))
    result = await answer_question("Why do we optimize the geometry?", active_experiment="exp07")
    assert result.answer_source == "extractive"
    assert "couldn't put together a full explanation just now" in result.text


@pytest.mark.parametrize(
    "message",
    [
        "Bhai, geometry optimization kyu karte hain?",
        "Explain HOMO in Hindi.",
        "Mujhe B3LYP aur B3P ka difference batao.",
        "मुझे HOMO समझाओ",
        "what is HOMO aur iska kya use hai?",
        "mujhe hinglish me explain karo",
    ],
)
async def test_any_input_language_ends_in_an_english_reply(scripted, message):
    scripted(HINGLISH, ENGLISH)
    result = await answer_question(message, active_experiment="exp07")
    assert result.status.answerable
    assert result.text == ENGLISH


def test_diagnosis_phrasing_rejects_a_hinglish_reply():
    from backend.tier1_compute.shared.types import Outcome, Tier1Result

    for outcome in (Outcome.PASS, Outcome.FAIL_NO_SIGNATURE):
        ok, note = phrasing.validate_output(HINGLISH, Tier1Result(outcome=outcome))
        assert not ok and note == "reply was not in English"
    assert phrasing.validate_output(ENGLISH, Tier1Result(outcome=Outcome.NOT_APPLICABLE))[0]


# =================================================== 1. streaming, end to end


async def test_a_draft_that_turns_hinglish_is_reset_and_never_kept(client, make_user, scripted):
    backend = scripted(LATE_HINGLISH, ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-reset")
    events = await _stream(client, token, classroom_id, "Why do we optimize the geometry?")
    types = [e["type"] for e in events]
    assert "reset" in types and types[-1] == "done"
    shown_after_reset = _streamed_text(events[types.index("reset") + 1 :])
    assert shown_after_reset == ""  # the Hinglish draft never continues
    assert not looks_non_english(_streamed_text(events))
    assert ENGLISH in events[-1]["message"]["content"]
    assert [c["streamed"] for c in backend.calls] == [True, False]  # the retry is not streamed


async def test_a_devanagari_draft_is_never_shown_at_all(client, make_user, scripted):
    scripted(DEVANAGARI, ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-deva")
    events = await _stream(client, token, classroom_id, "मुझे geometry optimization समझाओ")
    assert _streamed_text(events) == "" and "reset" not in [e["type"] for e in events]
    assert ENGLISH in events[-1]["message"]["content"]


async def test_an_english_stream_is_unchanged(client, make_user, scripted):
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-en")
    events = await _stream(client, token, classroom_id, "Why do we optimize the geometry?")
    assert _streamed_text(events) == ENGLISH
    assert "reset" not in [e["type"] for e in events]


async def test_a_stream_that_breaks_midway_still_ends_in_an_english_saved_reply(client, make_user, scripted):
    scripted((ENGLISH[:70], LLMUnavailable("connection reset by peer")))
    classroom_id, _, token = await _setup(client, make_user, "fb-break")
    events = await _stream(client, token, classroom_id, "Why do we optimize the geometry?")
    assert events[-1]["type"] == "done"
    final = events[-1]["message"]["content"]
    assert final.strip() and not looks_non_english(final)
    assert events[-1]["message"]["metadata"]["answer_source"] != "llm"


async def test_an_internal_error_shows_plain_english_never_exception_text(client, make_user, scripted, monkeypatch):
    from backend.api import chat_routes

    scripted(ENGLISH)

    async def boom(*args, **kwargs):
        raise RuntimeError("psycopg internal detail xyz")

    monkeypatch.setattr(chat_routes, "answer_question", boom)
    classroom_id, _, token = await _setup(client, make_user, "fb-err")
    events = await _stream(client, token, classroom_id, "Why do we optimize the geometry?")
    assert events[-1] == {"type": "error", "status": 500, "detail": chat_routes.STREAM_ERROR_DETAIL}
    assert "xyz" not in json.dumps(events)


# ===================================================== 2. discoverability


async def test_the_catalogue_carries_starter_questions_and_guided_availability(client, make_user):
    _, token = await make_user("s.catalogue@vitstudent.ac.in")
    resp = await client.get("/api/classrooms/experiments", headers=auth(token))
    experiments = {e["id"]: e for e in resp.json()["experiments"]}
    assert experiments["exp07"]["suggestions"] == list(STARTER_QUESTIONS)
    assert experiments["exp07"]["guided_learning"] is True
    assert experiments["exp01"]["suggestions"] == list(GENERIC_STARTERS)
    assert experiments["exp01"]["guided_learning"] is False


@pytest.mark.parametrize("question", STARTER_QUESTIONS)
async def test_every_exp07_starter_is_answered_through_the_normal_path(client, make_user, scripted, question):
    backend = scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-start")
    out = await _send(client, token, classroom_id, question)
    meta = out["message"]["metadata"]
    assert meta["type"] == "qa" and meta["answer_source"] == "llm"
    assert backend.calls and question in backend.calls[-1]["user"]
    assert bool(meta.get("general_knowledge")) == is_general_knowledge_request(question)
    if "differ" in question:
        assert COMPARISON_FORMAT in backend.calls[-1]["user"]


async def test_generic_starters_are_answered_for_an_experiment_without_authored_ones(client, make_user, scripted):
    scripted(ENGLISH)
    _, prof = await make_user("prof.generic@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "G"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    for question in GENERIC_STARTERS:
        resp = await client.post(
            "/api/chat/messages",
            json={"classroom_id": classroom_id, "experiment_id": "exp01", "message": question},
            headers=auth(prof),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["message"]["content"].strip()


# ====================================================== 3. interactivity


def test_next_step_chips_are_new_requests_or_an_explicit_check():
    chips = theory.next_step_chips("What is HOMO?")
    assert chips == [
        "Explain HOMO with a simple example",
        "How does this experiment use HOMO?",
        "Test my understanding",
    ]
    for chip in chips[:2]:
        assert grader.is_new_request(chip)
    assert conv.classify(chips[2]) is conv.Intent.GUIDED_CONCEPTS
    assert theory.next_step_chips("what is the capital of France") == []


@pytest.mark.parametrize("chip", theory.next_step_chips("What is HOMO?")[:2])
def test_tapping_a_chip_with_a_reflection_pending_is_answered_and_keeps_the_reflection(chip):
    state = _pending_state()
    before = dict(state.pending)
    assert theory.handle_pending(state, chip) is None  # -> normal Q&A, not graded
    assert state.pending == before


async def test_an_answer_without_a_reflection_offers_next_steps(client, make_user, scripted, monkeypatch):
    scripted(ENGLISH)
    monkeypatch.setattr(theory, "open_followup", lambda state, message: None)
    classroom_id, _, token = await _setup(client, make_user, "fb-chips")
    out = await _send(client, token, classroom_id, "What is a basis set?")
    assert out["message"]["metadata"]["ui"]["chips"] == theory.next_step_chips("What is a basis set?")


async def test_an_answer_with_a_reflection_keeps_only_the_reflection(client, make_user, scripted):
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-refl")
    out = await _send(client, token, classroom_id, "What is HOMO?")
    ui = out["message"]["metadata"].get("ui") or {}
    assert ui.get("kind") == "theory_followup"
    assert "Test my understanding" not in (ui.get("chips") or [])


async def test_a_direct_question_is_answered_not_turned_into_a_quiz(client, make_user, scripted):
    scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-direct")
    out = await _send(client, token, classroom_id, "What is a basis set?")
    assert out["message"]["metadata"]["type"] == "qa"
    assert ENGLISH in out["message"]["content"]


async def test_test_my_understanding_starts_the_existing_key_ideas_session(client, make_user, scripted):
    backend = scripted(ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-quiz")
    out = await _send(client, token, classroom_id, "Test my understanding")
    assert out["message"]["metadata"]["type"] == "walkthrough"
    assert backend.calls == []  # authored questions, no model call


# ================================================== 3D. general chemistry


@pytest.mark.parametrize(
    ("message", "general"),
    [
        ("Where is methane commonly used in real life?", True),
        ("Give me a real-world example of geometry optimization", True),
        ("What are the applications of DFT?", True),
        ("What is methane used for?", True),
        ("What is ORCA used for?", False),
        ("What is Gabedit used for?", False),
        ("Which basis set is used in this experiment?", False),
        ("What is a basis set?", False),
        ("Where do I find the HOMO in the output?", False),
    ],
)
def test_general_knowledge_detection(message, general):
    assert is_general_knowledge_request(message) is general


async def test_a_real_world_question_may_use_labelled_general_knowledge(scripted):
    backend = scripted(ENGLISH)
    result = await answer_question("Where is methane commonly used in real life?", active_experiment="exp07")
    assert GENERAL_KNOWLEDGE in backend.calls[-1]["user"]
    assert result.general_knowledge is True
    assert result.citations  # still only the experiment material actually supplied


async def test_an_experiment_question_stays_strictly_grounded(scripted):
    backend = scripted(ENGLISH)
    result = await answer_question("What is Gabedit used for?", active_experiment="exp07")
    assert GENERAL_KNOWLEDGE not in backend.calls[-1]["user"]
    assert result.general_knowledge is False


def test_the_grounding_rule_keeps_its_force_and_names_its_one_exception():
    prompt = pipeline.SYSTEM_PROMPT
    assert "Never state a fact that is not in the retrieved passages" in prompt
    assert "The one exception is a message marked GENERAL KNOWLEDGE below" in prompt
    assert "never attribute it to the manual" in GENERAL_KNOWLEDGE


async def test_no_general_knowledge_label_without_a_model_answer(scripted):
    scripted(LLMUnavailable("down"))
    result = await answer_question("Where is methane commonly used in real life?", active_experiment="exp07")
    assert result.general_knowledge is False


# ============================== practical wording and English-only, end to end

from backend.socratic_engine.walkthrough import exp07_script  # noqa: E402

STEP_ENGLISH = (
    "**Step 1:** Build the chair conformer. Open Avogadro and construct the first cyclohexane "
    "conformer in its chair form. If you need help finding the right tool, ask your lab "
    "instructor. Reply \"done\" once you have built the chair structure."
)
STEP_HINGLISH = (
    "**Step 1:** Chair conformer banana hai. Avogadro kholo aur cyclohexane ka chair form "
    "banao, phir done likho. Agar tool nahi milta toh instructor se pucho."
)

LANGUAGE_CASES = [
    "Bhai, first step kya hai?",
    "पहला स्टेप क्या है?",
    "Explain geometry optimization in Hindi.",
    "Mujhe B3LYP aur B3P ka difference batao.",
    "What is the first step of the experiment?",
]


@pytest.fixture
def scripted_everywhere(monkeypatch, scripted):
    """`scripted`, installed on every module that calls a model, so a test holds
    whichever path (grounded Q&A, Socratic hint, concept tutoring) a message takes."""

    def install(*script):
        backend = scripted(*script)
        for target in (
            "backend.socratic_engine.chat.get_backend",
            "backend.socratic_engine.realise.get_backend",
            "backend.rag.phrasing.get_backend",
        ):
            monkeypatch.setattr(target, lambda: backend)
        return backend

    return install


def test_the_practical_rules_guide_instead_of_listing_manual_gaps():
    prompt = pipeline.SYSTEM_PROMPT
    for gone in ("say so once, plainly", "what the lab material does not spell", "a setting the manual never states"):
        assert gone not in prompt
    assert 'do not tell them "the manual does not specify"' in prompt
    assert "ask your lab instructor" in prompt
    # The safety rules that stop invented software instructions are unchanged.
    assert "never invent a menu location" in prompt
    assert "never invent a menu path, button name or number" in prompt


def test_the_authored_walkthrough_never_says_the_manual_does_not_say():
    import inspect

    source = inspect.getsource(exp07_script)
    assert not re.search(r"manual does not|manual doesn.t|manual never", source, re.IGNORECASE)
    assert "lab instructor" in source


@pytest.mark.parametrize("message", LANGUAGE_CASES)
async def test_every_case_streams_and_saves_english_only(client, make_user, scripted_everywhere, message):
    """A Hindi/Hinglish first draft (the worst case) is never shown while
    streaming, and the saved reply is English."""
    scripted_everywhere(STEP_HINGLISH, STEP_ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-lang")
    events = await _stream(client, token, classroom_id, message)
    assert events[-1]["type"] == "done", events[-1]
    assert not looks_non_english(_streamed_text(events))
    saved = events[-1]["message"]["content"]
    assert saved.strip() and not looks_non_english(saved)


async def test_an_english_practical_step_streams_and_saves_unchanged(client, make_user, scripted_everywhere):
    scripted_everywhere(STEP_ENGLISH)
    classroom_id, _, token = await _setup(client, make_user, "fb-step")
    events = await _stream(client, token, classroom_id, "What is the first step of the experiment?")
    assert "reset" not in [e["type"] for e in events]
    streamed = _streamed_text(events)
    assert streamed == "" or STEP_ENGLISH.startswith(streamed) or streamed == STEP_ENGLISH
    assert not looks_non_english(events[-1]["message"]["content"])


@pytest.mark.parametrize("message", LANGUAGE_CASES)
async def test_exp08_practical_steps_are_english_too(client, make_user, scripted_everywhere, message):
    """Exp8 (the chair conformer) teaches its practical through the model, one
    step at a time; the same gate and retry apply there."""
    backend = scripted_everywhere(STEP_HINGLISH, STEP_ENGLISH)
    _, prof = await make_user("prof.exp08lang@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "E8"}, headers=auth(prof))
    resp = await client.post(
        "/api/chat/messages/stream",
        json={"classroom_id": created.json()["id"], "experiment_id": "exp08", "message": message},
        headers={"Cookie": f"{session_cookie.COOKIE_NAME}={prof}"},
    )
    events = _events(resp.text)
    assert events[-1]["type"] == "done", events[-1]
    assert not looks_non_english(_streamed_text(events))
    assert not looks_non_english(events[-1]["message"]["content"])
    # The model path really ran: the Hinglish draft, then the one correction.
    assert len(backend.calls) == 2 and "LANGUAGE CORRECTION" in backend.calls[1]["user"]


def test_starters_and_suggested_follow_ups_are_english():
    texts = list(STARTER_QUESTIONS) + list(GENERIC_STARTERS)
    for concept in ("What is HOMO?", "What is a basis set?", "Why do we optimize geometry?"):
        texts += theory.next_step_chips(concept)
    assert not [t for t in texts if looks_non_english(t)]


@pytest.mark.parametrize(
    "text",
    [
        STEP_ENGLISH,
        "The chair conformer of cyclohexane is lower in energy than the boat because it avoids "
        "eclipsed C-H bonds and flagpole interactions; B3LYP/6-31G* reproduces that ordering.",
    ],
)
def test_english_practical_and_chemistry_text_is_not_flagged(text):
    assert not looks_non_english(text)
