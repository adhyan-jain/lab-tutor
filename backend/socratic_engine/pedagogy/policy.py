"""Deterministic pedagogical policy: when to intervene, which question type,
how to classify an answer, and what to do next.

Policy lives here, not in a prompt. Nothing in this module calls a model; a
test asserts it imports no LLM code (CLAUDE.md hard rule). A model only ever
phrases the outcome of these decisions, downstream.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..knowledge.types import ConceptQuestion, ExperimentKnowledge, Misconception
from .state import RANK, UNDERSTOOD_OR_BETTER, ConceptRecord, ConceptStates

# A concept is not re-raised for this many controller turns after an
# intervention. A turn counter, not a clock.
CONCEPT_COOLDOWN_TURNS = 4
# After this many non-correct answers on one concept the tutor gives a
# concise explanation and moves on instead of asking again.
EXPLAIN_AFTER_MISSES = 2
# Only concepts at or above this importance raise a proactive card.
CARD_MIN_IMPORTANCE = 3

_NEGATION = re.compile(r"\b(not|n't|never|rather\s+than|instead\s+of)\b[^.;,!?]*$|n't\b[^.;,!?]*$", re.I)
_DONT_KNOW = re.compile(
    r"^\s*(i\s+)?(don'?t|do\s+not|dunno|no\s+idea|not\s+sure|idk|\?+|no)\b|\b(no\s+idea|not\s+sure|idk)\b",
    re.I,
)


@dataclass(frozen=True)
class Classification:
    label: str  # CORRECT | PARTIAL | MISCONCEPTION | UNCLEAR
    misconception_id: str | None = None
    matched_groups: int = 0
    dont_know: bool = False


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _misconception_hit(m: Misconception, text: str) -> bool:
    """A pattern counts only when the student is not negating it
    ("it's not just to look nicer" must not read as the misconception)."""
    for pat in m.patterns:
        for hit in re.finditer(pat, text, re.I):
            if not _NEGATION.search(text[: hit.start()][-40:]):
                return True
    return False


def classify_answer(
    question: ConceptQuestion,
    text: str,
    knowledge: ExperimentKnowledge,
    *,
    step_id: str = "",
) -> Classification:
    """Classify a free-text answer against the authored keys. Deterministic."""
    t = _normalise(text)
    if not t:
        return Classification("UNCLEAR", dont_know=True)
    step = knowledge.step_by_id.get(step_id)
    candidates: list[str] = list(step.misconceptions) if step else []
    candidates += [m.id for m in knowledge.misconceptions if m.concept_id == question.concept_id]
    seen: set[str] = set()
    for mid in candidates:
        if mid in seen:
            continue
        seen.add(mid)
        m = knowledge.misconception_by_id[mid]
        if _misconception_hit(m, t):
            return Classification("MISCONCEPTION", misconception_id=mid)
    matched = sum(1 for group in question.groups if any(re.search(p, t, re.I) for p in group))
    if matched >= question.need and question.groups:
        return Classification("CORRECT", matched_groups=matched)
    if matched >= 1:
        return Classification("PARTIAL", matched_groups=matched)
    return Classification("UNCLEAR", dont_know=bool(_DONT_KNOW.search(t)))


@dataclass(frozen=True)
class Decision:
    action: str  # none | question | card_question
    concept_id: str = ""
    question: ConceptQuestion | None = None
    reason: str = ""


# Question types that make sense before the student acts on a step, and
# after (they need a result to look at). The controller passes one set.
PRE_STEP_TYPES = frozenset({"PREDICTION", "CONSEQUENCE"})
POST_STEP_TYPES = frozenset({"WHY", "OBSERVATION", "INTERPRETATION", "TRANSFER"})


def _eligible_concepts(knowledge: ExperimentKnowledge, step_id: str, states: ConceptStates) -> list[str]:
    step = knowledge.step_by_id.get(step_id)
    if step is None or not step.checkpoint:
        return []
    out: list[tuple[int, int, str]] = []
    for order, cid in enumerate(step.concepts):
        concept = knowledge.concept_by_id[cid]
        rec = states.get(cid)
        if rec.state in UNDERSTOOD_OR_BETTER:
            continue
        if rec.last_seq is not None and states.seq - rec.last_seq < CONCEPT_COOLDOWN_TURNS:
            continue
        out.append((-concept.importance, order, cid))
    out.sort()
    return [cid for _, _, cid in out]


def choose_question(
    knowledge: ExperimentKnowledge,
    step_id: str,
    concept_id: str,
    rec: ConceptRecord,
    allowed: frozenset[str] | None = None,
    available: "Callable[[ConceptQuestion], bool] | None" = None,
) -> ConceptQuestion | None:
    """Pick a question type from the concept's state, then an unasked
    question of that type. Cheap, deterministic, no repeated questions
    unless the student is partial and a scaffold is the next move."""
    step = knowledge.step_by_id.get(step_id)
    # A question belongs to its own concept: a step's questions are tried
    # first, but never asked (or credited) on behalf of a different concept.
    pool: list[ConceptQuestion] = [knowledge.question_by_id[q] for q in step.questions] if step else []
    pool += [q for q in knowledge.questions if q not in pool]
    pool = [q for q in pool if q.concept_id == concept_id]
    if available is not None:  # e.g. a pattern question needs enough recorded runs
        pool = [q for q in pool if available(q)]
    if rec.state == "UNKNOWN" or rec.state == "INTRODUCED":
        order = ("PREDICTION", "WHY", "OBSERVATION")
    elif rec.state == "ATTEMPTED":
        order = ("WHY", "OBSERVATION", "PREDICTION")
    elif rec.state == "PARTIALLY_UNDERSTOOD":
        order = ("INTERPRETATION", "OBSERVATION", "CONSEQUENCE", "WHY")
    elif rec.state == "UNDERSTOOD":
        return None  # do not re-test understood concepts at a step
    else:  # MASTERED
        order = ("TRANSFER",)
    for qtype in order:
        if allowed is not None and qtype not in allowed:
            continue
        for q in pool:
            if q.qtype == qtype and q.id not in rec.asked:
                return q
    if rec.state != "MASTERED":
        # The preferred types had nothing authored for this concept: use any
        # other unasked, allowed question rather than leaving a core concept
        # (e.g. HOMO, which only has INTERPRETATION questions) unraised.
        for q in pool:
            if q.qtype != "TRANSFER" and q.id not in rec.asked and (allowed is None or q.qtype in allowed):
                return q
    return None


def decide(
    knowledge: ExperimentKnowledge,
    step_id: str,
    states: ConceptStates,
    *,
    blocked: bool = False,
    allowed: frozenset[str] | None = None,
    available: "Callable[[ConceptQuestion], bool] | None" = None,
) -> Decision:
    """Should the tutor raise a conceptual moment before/at this step?

    `blocked` is set by the caller for safety triage or an active
    troubleshooting report: safety and problem-solving always win over a
    pedagogical interruption.
    """
    if blocked:
        return Decision("none", reason="blocked")
    for cid in _eligible_concepts(knowledge, step_id, states):
        rec = states.get(cid)
        q = choose_question(knowledge, step_id, cid, rec, allowed, available)
        if q is None:
            continue
        concept = knowledge.concept_by_id[cid]
        card = rec.state == "UNKNOWN" and concept.importance >= CARD_MIN_IMPORTANCE
        return Decision("card_question" if card else "question", cid, q, reason=f"state={rec.state}")
    return Decision("none", reason="no eligible concept")


@dataclass(frozen=True)
class Followup:
    kind: str  # advance | probe | scaffold | explain
    text: str = ""  # authored text for the kind (probe/scaffold/correction)
    misconception_id: str | None = None


def next_after_answer(
    knowledge: ExperimentKnowledge,
    question: ConceptQuestion,
    cls: Classification,
    rec: ConceptRecord,
) -> Followup:
    """What the tutor does with a classified answer. State must already be
    updated (so `rec.misses` includes this answer)."""
    if cls.label == "CORRECT":
        return Followup("advance")
    misses = rec.misses.get(question.id, 0)
    if cls.label == "MISCONCEPTION" and cls.misconception_id:
        m = knowledge.misconception_by_id[cls.misconception_id]
        if misses >= EXPLAIN_AFTER_MISSES:
            return Followup("explain", m.correction, m.id)
        return Followup("probe", m.probe, m.id)
    if misses >= EXPLAIN_AFTER_MISSES:
        return Followup("explain", question.expected_reasoning)
    return Followup("scaffold", question.scaffold)


def summarise_state(states: ConceptStates) -> dict[str, str]:
    """Compact concept -> state map for telemetry."""
    return {cid: rec.state for cid, rec in states.records.items() if RANK[rec.state] > 0}
