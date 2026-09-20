"""Authored content types for a guided walkthrough.

Everything a student is asked, and how their answer is judged, is written
down here in advance by a person. Nothing in this package calls a model:
the CLAUDE.md hard rule keeps correctness decisions out of LLM hands, so a
question carries its own answer key and the grader only matches against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

QuestionKind = Literal["mcq", "short", "number", "report"]


@dataclass(frozen=True)
class Choice:
    key: str
    text: str
    # Why this option is right or tempting-but-wrong; shown after answering.
    why: str = ""


@dataclass(frozen=True)
class Question:
    id: str
    ask: str
    kind: QuestionKind = "short"
    # mcq
    choices: tuple[Choice, ...] = ()
    correct: str = ""
    # short: each group is a set of regex alternatives; `need` groups must match
    groups: tuple[tuple[str, ...], ...] = ()
    need: int = 1
    # number: any of these values is accepted (exact within `tol`)
    numbers: tuple[float, ...] = ()
    tol: float = 0.0
    # report: the student's own number is captured under `capture`; nothing
    # is right or wrong about it beyond the sanity rules in the controller
    capture: str = ""
    hint: str = ""
    reveal: str = ""
    ok: str = ""


@dataclass(frozen=True)
class WalkStep:
    id: str
    chapter: str
    title: str
    do: str
    why: str
    # Ask this before moving on: only someone who did the step can answer.
    evidence: Question | None = None
    # A "why does this work" cross-question, asked after the evidence.
    check: Question | None = None
    # What the student sees when they say they are stuck.
    stuck: str = ""
    # A fact the student must have from an earlier step, stated back to them.
    prereq: str = ""
    # Shown once after the step completes.
    ack: str = ""
    # When set, the step's ack quotes back the guess the student made in the
    # chapter's curiosity hook, next to what they just observed.
    closes_hook: bool = False


@dataclass(frozen=True)
class QuizItem:
    id: str
    stem: str
    choices: tuple[Choice, ...]
    correct: str
    # Only for preview items: the step where the answer becomes visible.
    teaser_step: str = ""
    teaser: str = ""


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    # One curiosity question, asked before the chapter's first step. Ungraded.
    hook: str
    hook_ack: str
    step_ids: tuple[str, ...] = ()
    recall: tuple[QuizItem, ...] = ()
    preview: tuple[QuizItem, ...] = ()


@dataclass(frozen=True)
class Script:
    experiment_id: str
    title: str
    chapters: tuple[Chapter, ...]
    steps: tuple[WalkStep, ...]
    by_id: dict[str, WalkStep] = field(default_factory=dict, compare=False)

    def step(self, step_id: str) -> WalkStep:
        return self.by_id[step_id]

    def chapter_of(self, step_id: str) -> Chapter:
        cid = self.by_id[step_id].chapter
        return next(c for c in self.chapters if c.id == cid)

    def index_of(self, step_id: str) -> int:
        return next(i for i, s in enumerate(self.steps) if s.id == step_id)
