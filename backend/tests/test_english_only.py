"""Student-facing replies are English only, whatever language the student uses.

Regression for a live Exp7 bug: an English question got a Hinglish reply
because the answering prompt said "reply in the language AND script the
student wrote in". Hinglish *input* is still understood (see
test_normalisation.py); only the *output* language is pinned here.

The language rule is a prompt contract, so it is tested structurally: the
rule is present in every student-facing prompt, the old mirroring rule is
gone, and Hinglish input still reaches the model with the English-only
instruction attached. No real model is called.
"""

from __future__ import annotations

import re

import pytest

from backend.config import Settings
from backend.llm import telemetry
from backend.rag import phrasing
from backend.rag.phrasing import ENGLISH_ONLY_RULE
from backend.retrieval import pipeline
from backend.retrieval.pipeline import answer_question
from backend.socratic_engine import chat, realise

STUDENT_FACING_PROMPTS = {
    "retrieval.pipeline": pipeline.SYSTEM_PROMPT,
    "rag.phrasing": phrasing.SYSTEM_PROMPT,
    "socratic_engine.chat": chat.SYSTEM_PROMPT,
    "socratic_engine.realise": realise._SYSTEM,
}

OLD_MIRRORING_PHRASES = (
    "language AND script",
    "Roman-letter Hinglish",
    "reply in the same Roman-letter",
    "only use Devanagari if they did",
)

ENGLISH_REPLY = "The HOMO is the highest occupied molecular orbital of the molecule."
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


class _RecordingBackend:
    name = "fake"
    supports_context_cache = False

    def __init__(self):
        self.calls: list[dict] = []

    async def complete(self, *, system, user, max_tokens=None, temperature=None):
        from backend.llm.client import LLMReply

        telemetry.record_call()
        self.calls.append({"system": system, "user": user})
        return LLMReply(text=ENGLISH_REPLY, backend="fake", model="m")


@pytest.fixture
def backend(monkeypatch):
    fake = _RecordingBackend()
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake)
    return fake


@pytest.mark.parametrize("name", sorted(STUDENT_FACING_PROMPTS))
def test_every_student_facing_prompt_carries_the_english_only_rule(name):
    prompt = STUDENT_FACING_PROMPTS[name]
    assert ENGLISH_ONLY_RULE in prompt
    for phrase in OLD_MIRRORING_PHRASES:
        assert phrase not in prompt, f"{name} still has the old mirroring rule: {phrase!r}"


def test_rule_forbids_hinglish_and_language_switching():
    rule = ENGLISH_ONLY_RULE
    assert "always respond to the student in English" in rule
    for banned in ("Hindi", "Hinglish", "Romanized Hindi", "Devanagari"):
        assert banned in rule
    assert "do not switch language even if the student asks" in rule


@pytest.mark.parametrize(
    "message",
    [
        "What is HOMO?",  # A. English
        "bro homo kaha se milega",  # B. Hinglish
        "what is HOMO aur why is it important?",  # C. mixed
        "Explain this in Hindi.",  # D. explicit switch request
        "mujhe hinglish me explain karo",  # E. Romanized Hindi request
    ],
)
async def test_any_input_language_gets_an_english_only_prompt_and_reply(backend, message):
    result = await answer_question(message, active_experiment="exp07")

    assert backend.calls, "every case here is an in-scope Exp7 question"
    call = backend.calls[-1]
    assert ENGLISH_ONLY_RULE in call["system"]
    assert "REPLY LANGUAGE: English only" in call["user"]
    for phrase in OLD_MIRRORING_PHRASES:
        assert phrase not in call["system"] and phrase not in call["user"]
    assert result.text == ENGLISH_REPLY
    assert not _DEVANAGARI.search(result.text)


def test_default_temperature_is_low_for_consistent_tutoring():
    assert Settings.model_fields["llm_temperature"].default == 0.3
