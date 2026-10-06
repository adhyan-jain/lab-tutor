"""Experiment knowledge model: what a tutor needs to know about an experiment.

Pure authored data, no behaviour and no model calls. The pedagogical engine
(`backend/socratic_engine/pedagogy/`) is generic; only the instances of these
types differ per experiment, so Experiments 1-10 can each add one module.

CLAUDE.md hard rule: nothing here, or in anything that reads it, asks a model
to decide whether an answer is right. Misconceptions carry their own
detection patterns, matched deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

QuestionType = Literal[
    "PREDICTION", "WHY", "CONSEQUENCE", "OBSERVATION", "INTERPRETATION", "TRANSFER"
]
QUESTION_TYPES: tuple[str, ...] = (
    "PREDICTION", "WHY", "CONSEQUENCE", "OBSERVATION", "INTERPRETATION", "TRANSFER",
)


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    description: str  # one or two sentences, safe to show as a concept card
    prerequisites: tuple[str, ...] = ()
    # 1 (background) .. 3 (core to the experiment's point)
    importance: int = 2
    experiment_relevance: str = ""


@dataclass(frozen=True)
class Misconception:
    id: str
    concept_id: str
    statement: str  # the wrong belief, in the student's likely words
    # Regex alternatives; any match on the normalised answer flags it.
    patterns: tuple[str, ...]
    # Socratic question that targets it without revealing the answer.
    probe: str
    # Concise correction, used only after repeated difficulty.
    correction: str


@dataclass(frozen=True)
class ConceptQuestion:
    """One authored question for a concept, with deterministic answer keys."""

    id: str
    concept_id: str
    qtype: str  # one of QUESTION_TYPES
    ask: str
    # Each group is a set of regex alternatives; `need` groups must match for
    # the answer to count as CORRECT. Fewer (but >=1) matched means PARTIAL.
    groups: tuple[tuple[str, ...], ...] = ()
    need: int = 1
    # What a good answer contains, handed to the phrasing step as grounding.
    expected_reasoning: str = ""
    # Short scaffold used when the answer is PARTIAL or after repeated misses.
    scaffold: str = ""
    # Only ask once the student has recorded this many runs of the repeated
    # method/basis table (a pattern question needs a pattern to look at).
    min_rows: int = 0


@dataclass(frozen=True)
class StepKnowledge:
    step_id: str  # matches a WalkStep.id in the walkthrough script
    why: str
    concepts: tuple[str, ...] = ()
    expected_observation: str = ""
    possible_consequence: str = ""
    misconceptions: tuple[str, ...] = ()
    # True only where the step is a conceptual transition worth a Socratic
    # moment. Procedural clicks stay False and are never interrupted.
    checkpoint: bool = False
    # Question ids (into ExperimentKnowledge.questions), in preferred order.
    questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentKnowledge:
    experiment_id: str
    concepts: tuple[Concept, ...]
    steps: tuple[StepKnowledge, ...]
    misconceptions: tuple[Misconception, ...]
    questions: tuple[ConceptQuestion, ...]
    # Final reasoning/transfer assessment, question ids in order.
    assessment: tuple[str, ...] = ()
    concept_by_id: dict[str, Concept] = field(default_factory=dict, compare=False)
    step_by_id: dict[str, StepKnowledge] = field(default_factory=dict, compare=False)
    misconception_by_id: dict[str, Misconception] = field(default_factory=dict, compare=False)
    question_by_id: dict[str, ConceptQuestion] = field(default_factory=dict, compare=False)

    def validate(self, known_step_ids: set[str] | None = None) -> list[str]:
        """Return a list of structural problems (empty means consistent)."""
        problems: list[str] = []
        cids = set(self.concept_by_id)
        for c in self.concepts:
            for p in c.prerequisites:
                if p not in cids:
                    problems.append(f"concept {c.id}: unknown prerequisite {p}")
        # prerequisite cycles
        state: dict[str, int] = {}

        def visit(cid: str) -> bool:
            if state.get(cid) == 1:
                return True
            if state.get(cid) == 2:
                return False
            state[cid] = 1
            for p in self.concept_by_id[cid].prerequisites:
                if p in self.concept_by_id and visit(p):
                    return True
            state[cid] = 2
            return False

        for cid in cids:
            if visit(cid):
                problems.append(f"prerequisite cycle through {cid}")
                break
        for s in self.steps:
            if known_step_ids is not None and s.step_id not in known_step_ids:
                problems.append(f"step {s.step_id}: not in the walkthrough script")
            for cid in s.concepts:
                if cid not in cids:
                    problems.append(f"step {s.step_id}: unknown concept {cid}")
            for mid in s.misconceptions:
                if mid not in self.misconception_by_id:
                    problems.append(f"step {s.step_id}: unknown misconception {mid}")
            for qid in s.questions:
                if qid not in self.question_by_id:
                    problems.append(f"step {s.step_id}: unknown question {qid}")
        for m in self.misconceptions:
            if m.concept_id not in cids:
                problems.append(f"misconception {m.id}: unknown concept {m.concept_id}")
        for q in self.questions:
            if q.concept_id not in cids:
                problems.append(f"question {q.id}: unknown concept {q.concept_id}")
            if q.qtype not in QUESTION_TYPES:
                problems.append(f"question {q.id}: bad type {q.qtype}")
        for qid in self.assessment:
            if qid not in self.question_by_id:
                problems.append(f"assessment: unknown question {qid}")
        return problems


def build(
    experiment_id: str,
    concepts: tuple[Concept, ...],
    steps: tuple[StepKnowledge, ...],
    misconceptions: tuple[Misconception, ...],
    questions: tuple[ConceptQuestion, ...],
    assessment: tuple[str, ...] = (),
) -> ExperimentKnowledge:
    return ExperimentKnowledge(
        experiment_id=experiment_id,
        concepts=concepts,
        steps=steps,
        misconceptions=misconceptions,
        questions=questions,
        assessment=assessment,
        concept_by_id={c.id: c for c in concepts},
        step_by_id={s.step_id: s for s in steps},
        misconception_by_id={m.id: m for m in misconceptions},
        question_by_id={q.id: q for q in questions},
    )
