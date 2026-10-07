"""Theory-first Socratic follow-ups for Experiment 7 (phone-only).

Theory is the default. A student who asks "what is geometry optimization?"
gets an ordinary grounded answer; this module then adds ONE short authored
question about the concept they asked about, chosen from their concept state by
pedagogy/policy.py (deterministic, phone-safe, never one they already
understand, never repeated within the cooldown), and remembers it in the
thread's own `ConversationState` so their next message is graded against it.

Everything here is deterministic and model-free. Reusing the walkthrough's
concept-moment controller for the answer keeps one implementation of
classification, probes, scaffolds, explanations and the advisory-call context;
it is run on a throwaway `WalkState(mode="theory")` built from, and written back
to, the thread's state. Nothing is shared between threads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.socratic_engine import conversation as conv
from backend.socratic_engine.knowledge import get_knowledge, phone_safe
from backend.socratic_engine.pedagogy import policy
from backend.socratic_engine.pedagogy import state as pstate
from backend.socratic_engine.walkthrough import controller as ctl

EXPERIMENT_ID = "exp07"

_STOP = frozenset(
    "the a an of to me i instead please just only now actually this that it and about is are was what "
    "want with for in on my we you can could would do does how why when who which then so but not no yes "
    "ok okay tell show give understand know learn explain teach help let".split()
)
_NOT_AN_ANSWER = frozenset({
    conv.Intent.USER_QUESTION, conv.Intent.SWITCH_TO_THEORY, conv.Intent.SWITCH_TO_PRACTICE,
    conv.Intent.GUIDED_CONCEPTS,
})
_STEP_RE = re.compile(r"\bstep\s*\d+\b|^\s*step\s*:", re.IGNORECASE | re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_LIST_MARKER = re.compile(r"\s*(?:[-*•]|\d+[.)]|#+)\s+")


def concept_for_message(text: str) -> str | None:
    """The concept a student's wording is about, or None. Specific phrases
    score higher than generic ones; ties go to the more important concept."""
    knowledge = get_knowledge(EXPERIMENT_ID)
    lowered = (text or "").lower()
    best: tuple[tuple[int, int], str] | None = None
    for concept in knowledge.concepts:
        score = 0
        for pattern in concept.aliases:
            match = re.search(pattern, lowered)
            if match:
                score += len(match.group(0))
        if score and (best is None or (score, concept.importance) > best[0]):
            best = ((score, concept.importance), concept.id)
    return best[1] if best else None


def has_substance(text: str) -> bool:
    """After removing the phrases that merely switch to theory, is there a real
    question left? ("Forget the steps. Explain why optimisation works" yes;
    "Explain the theory instead" no.)"""
    rest = text or ""
    for span in conv.exit_spans(rest):
        rest = rest.replace(span, " ")
    tokens = [w for w in re.findall(r"[a-z0-9\-]+", rest.lower()) if w not in _STOP]
    return len(tokens) >= 2 or concept_for_message(rest) is not None


def guard_answer(text: str, message: str) -> str:
    """Theory answers must not send a phone-only student to external software.
    Unless they asked how the practical is performed, drop any sentence that
    names software/screens/files or numbers a step; if little is left, fall back
    to the authored concept description. Deterministic; no model call."""
    if not text or conv.is_procedure_request(message):
        return text
    def bad(s: str) -> bool:
        return bool(phone_safe.external_dependency(s) or _STEP_RE.search(s))

    if not any(bad(s) for s in _SENTENCE_SPLIT.split(text) if s.strip()):
        return text
    # Filter line by line so headings, bullets and paragraph breaks survive.
    lines: list[str] = []
    for line in text.split("\n"):
        marker = _LIST_MARKER.match(line)
        prefix = marker.group(0) if marker else ""
        kept = [s for s in _SENTENCE_SPLIT.split(line[len(prefix):]) if s.strip() and not bad(s)]
        if kept:
            lines.append(prefix + " ".join(kept))
        elif not line.strip() and lines and lines[-1]:
            lines.append("")
    cleaned = "\n".join(lines).strip()
    if len(cleaned) >= 60:
        return cleaned
    cid = concept_for_message(message)
    knowledge = get_knowledge(EXPERIMENT_ID)
    base = knowledge.concept_by_id[cid].description if cid else "I can explain the idea behind that."
    return f"{base} The practical software steps are normally done on a lab computer, so here we will stick to the ideas."


def fallback_explanation(message: str) -> str | None:
    """A short, authored, phone-safe explanation of the concept the student
    asked about, for when no model answer is available. Better than showing an
    unrelated manual excerpt; None if the wording maps to no known concept."""
    cid = concept_for_message(message)
    if cid is None:
        return None
    concept = get_knowledge(EXPERIMENT_ID).concept_by_id[cid]
    return f"Here is the short version. **{concept.name}**: {concept.description}"


@dataclass
class TheoryTurn:
    reply: str
    ui: dict[str, Any]
    events: dict[str, Any]
    realise: dict[str, Any] | None = None


def _walk_state(conv_state: conv.ConversationState) -> ctl.WalkState:
    """A throwaway walkthrough state carrying only this thread's concept state."""
    ws = ctl.new_state("theory", mode="theory")
    ws.status = "active"
    ws.concepts = conv_state.concepts
    ws.concept = conv_state.pending
    ws.phase = "concept" if conv_state.pending else "step"
    return ws


def open_followup(conv_state: conv.ConversationState, message: str) -> TheoryTurn | None:
    """Pick one Socratic follow-up for the concept the student just asked
    about, remember it as pending, and return its text. None if there is
    nothing worth asking (unknown concept, already understood, on cooldown, no
    phone-safe question left)."""
    cid = concept_for_message(message)
    if cid is None:
        return None
    knowledge = get_knowledge(EXPERIMENT_ID)
    cs = pstate.ConceptStates.from_dict(conv_state.concepts)
    cs.tick()
    rec = cs.get(cid)
    conv_state.concepts = cs.to_dict()  # keep the turn counter moving
    if rec.state in pstate.UNDERSTOOD_OR_BETTER:
        return None
    if rec.last_seq is not None and cs.seq - rec.last_seq < policy.CONCEPT_COOLDOWN_TURNS:
        return None
    question = policy.choose_question(knowledge, "", cid, rec, None, phone_safe.is_phone_safe)
    if question is None:
        return None
    pstate.introduce(cs, cid)
    cs.get(cid).last_seq = cs.seq
    conv_state.concepts = cs.to_dict()
    conv_state.pending = {
        "concept_id": cid, "question_id": question.id, "step_id": "theory",
        "when": "theory", "resume": "theory", "card": False,
    }
    ws = _walk_state(conv_state)
    text, ui = ctl._concept_message(ws, "")
    ui = {**ui, "kind": "theory_followup"}
    return TheoryTurn(text, ui, {"step_id": "theory", "verdict": "theory_followup", "intervention": ui.get("intervention", {})})


def handle_pending(conv_state: conv.ConversationState, message: str) -> TheoryTurn | None:
    """Grade the student's message against the pending follow-up. Returns the
    authored reply, or None when the message is not an attempt at it (a new
    question) -- in which case the follow-up is dropped and the new question is
    answered normally."""
    if not conv_state.pending:
        return None
    # A new question, or a request to change mode, is never an attempt at the
    # follow-up: drop the follow-up and let the message be answered on its own.
    if conv.classify(message) in _NOT_AN_ANSWER:
        conv_state.pending = None
        return None
    ws = _walk_state(conv_state)
    result = ctl.take_turn(ws, message)
    conv_state.concepts = ws.concepts
    if result.reply is None:
        conv_state.pending = None
        return None
    conv_state.pending = ws.concept if ws.phase == "concept" else None
    ui = {**result.ui, "kind": "theory_followup"}
    return TheoryTurn(result.reply, ui, result.events, result.realise)


def apply_advisory(conv_state: conv.ConversationState, concept_id: str, suggested: str) -> str:
    """Fold the advisory model classification into this thread's concept state
    (clamped by pedagogy.state.apply_advisory). Returns the resulting state."""
    cs = pstate.ConceptStates.from_dict(conv_state.concepts)
    rec = pstate.apply_advisory(cs, concept_id, suggested)
    conv_state.concepts = cs.to_dict()
    return rec.state
