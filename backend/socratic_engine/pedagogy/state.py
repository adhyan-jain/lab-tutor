"""Per-student concept state with explicit, auditable transitions.

Pure and deterministic; no model call lives here. Every change to a concept's
state goes through `apply_classification`, which appends a history row naming
its source (`deterministic` or `llm_advisory`), so a state can always be
traced back to the evidence that produced it. Free LLM prose never mutates
state: an advisory classification is clamped (see `apply_advisory`).

There is no clock. "Recency" is a turn counter (`ConceptStates.seq`), so
intervention cooldowns never depend on wall-clock time.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

STATES: tuple[str, ...] = (
    "UNKNOWN", "INTRODUCED", "ATTEMPTED", "PARTIALLY_UNDERSTOOD", "UNDERSTOOD", "MASTERED",
)
RANK = {s: i for i, s in enumerate(STATES)}
UNDERSTOOD_OR_BETTER = ("UNDERSTOOD", "MASTERED")

CLASSIFICATIONS = ("CORRECT", "PARTIAL", "MISCONCEPTION", "UNCLEAR")
SOURCES = ("deterministic", "llm_advisory")

# An advisory classification can lift a concept at most to this state.
ADVISORY_CEILING = "PARTIALLY_UNDERSTOOD"


@dataclass
class ConceptRecord:
    state: str = "UNKNOWN"
    attempts: int = 0
    misconceptions: list[str] = field(default_factory=list)  # ids seen
    asked: list[str] = field(default_factory=list)  # question ids
    types_asked: list[str] = field(default_factory=list)  # question types
    misses: dict[str, int] = field(default_factory=dict)  # question id -> non-correct count
    last_seq: int | None = None  # turn counter of the last intervention
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ConceptStates:
    seq: int = 0
    records: dict[str, ConceptRecord] = field(default_factory=dict)

    def get(self, concept_id: str) -> ConceptRecord:
        rec = self.records.get(concept_id)
        if rec is None:
            rec = self.records[concept_id] = ConceptRecord()
        return rec

    def tick(self) -> int:
        self.seq += 1
        return self.seq

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ConceptStates":
        out = cls()
        if not data:
            return out
        out.seq = int(data.get("seq", 0))
        for cid, raw in (data.get("records") or {}).items():
            rec = ConceptRecord()
            for key, value in (raw or {}).items():
                if hasattr(rec, key):
                    setattr(rec, key, copy.deepcopy(value))
            if rec.state not in RANK:
                rec.state = "UNKNOWN"
            out.records[cid] = rec
        return out


def _next_state(current: str, classification: str) -> str:
    """The transition table. Never regresses understanding on a PARTIAL or
    UNCLEAR answer; a stated misconception drops UNDERSTOOD one step."""
    if classification == "CORRECT":
        return current if current == "MASTERED" else "UNDERSTOOD"
    if classification == "PARTIAL":
        return current if RANK[current] >= RANK["PARTIALLY_UNDERSTOOD"] else "PARTIALLY_UNDERSTOOD"
    if classification == "MISCONCEPTION":
        if RANK[current] >= RANK["UNDERSTOOD"]:
            return "PARTIALLY_UNDERSTOOD"
        return current if RANK[current] >= RANK["ATTEMPTED"] else "ATTEMPTED"
    # UNCLEAR
    return current if RANK[current] >= RANK["ATTEMPTED"] else "ATTEMPTED"


def _record(rec: ConceptRecord, before: str, after: str, source: str, reason: str, seq: int) -> None:
    rec.history.append({"from": before, "to": after, "source": source, "reason": reason, "seq": seq})


def introduce(states: ConceptStates, concept_id: str) -> bool:
    """Mark a concept as shown (card or question). Returns True if it changed."""
    rec = states.get(concept_id)
    if rec.state != "UNKNOWN":
        return False
    rec.state = "INTRODUCED"
    _record(rec, "UNKNOWN", "INTRODUCED", "deterministic", "introduced", states.seq)
    return True


def apply_classification(
    states: ConceptStates,
    concept_id: str,
    classification: str,
    *,
    question_id: str = "",
    question_type: str = "",
    misconception_id: str | None = None,
    reason: str = "",
) -> ConceptRecord:
    """Apply a deterministic classification of a student answer."""
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"unknown classification {classification!r}")
    rec = states.get(concept_id)
    before = rec.state
    rec.attempts += 1
    if question_id and question_id not in rec.asked:
        rec.asked.append(question_id)
    if question_type:
        rec.types_asked.append(question_type)
    if classification != "CORRECT" and question_id:
        rec.misses[question_id] = rec.misses.get(question_id, 0) + 1
    if misconception_id and misconception_id not in rec.misconceptions:
        rec.misconceptions.append(misconception_id)
    rec.state = _next_state(before, classification)
    rec.last_seq = states.seq
    _record(rec, before, rec.state, "deterministic", reason or classification.lower(), states.seq)
    return rec


def mark_mastered(states: ConceptStates, concept_id: str, reason: str = "transfer_correct") -> None:
    """MASTERED is reachable only from UNDERSTOOD, via a correct TRANSFER answer."""
    rec = states.get(concept_id)
    if rec.state == "UNDERSTOOD":
        _record(rec, "UNDERSTOOD", "MASTERED", "deterministic", reason, states.seq)
        rec.state = "MASTERED"


def apply_advisory(
    states: ConceptStates, concept_id: str, suggested: str, *, reason: str = "llm_suggestion"
) -> ConceptRecord:
    """Fold in a model's suggested classification for an answer the
    deterministic grader could not classify (UNCLEAR).

    Clamped: it can lift the state by at most one level and never past
    PARTIALLY_UNDERSTOOD, and it can never drop a state or reach
    UNDERSTOOD/MASTERED. The model advises; it does not decide.
    """
    rec = states.get(concept_id)
    if suggested not in CLASSIFICATIONS or suggested == "UNCLEAR":
        return rec
    before = rec.state
    target = _next_state(before, "PARTIAL" if suggested == "CORRECT" else suggested)
    # One level up, but an answered question is at least ATTEMPTED.
    ceiling = min(max(RANK[before] + 1, RANK["ATTEMPTED"]), RANK[ADVISORY_CEILING])
    after = STATES[min(RANK[target], ceiling)] if RANK[target] > RANK[before] else before
    if after != before:
        rec.state = after
        _record(rec, before, after, "llm_advisory", reason, states.seq)
    return rec
