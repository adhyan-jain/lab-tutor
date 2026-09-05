# LabTutor

LabTutor is a learning-support system for VIT's BACHY105 (Applied
Chemistry Lab) course. It helps students work through chemistry lab
experiments correctly while they're still doing them, and helps
professors and TAs understand what went wrong when a student's
submitted result is incorrect — without turning either process into
an answer-dispensing machine.

## Problem statement

Students who make a procedural or conceptual error mid-experiment
usually don't find out until grading, days later, when the error is no
longer actionable. Manually reviewing every submission for the
*reason* a result is wrong doesn't scale to a professor or TA covering
many sections. Generic AI tools either hand over the final answer
directly (defeating the point of the lab) or aren't grounded in the
specific formulas, tolerances, and procedure described in this
course's manual, and so can't be trusted to judge correctness.

## Architecture

LabTutor has two modes: a **Socratic mode** that guides a student
through an experiment step-by-step without revealing the final answer,
and a **Diagnostic mode** that recomputes and explains what went wrong
in a finished submission. Both modes are built on deterministic,
manual-derived computation first; an LLM is only ever used to phrase
an already-determined result, never to decide it.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline
design, tier breakdown, data flow, and stack choice.

## Local development setup

TODO — to be filled in once the stack is finalized (see Commit 5 /
ARCHITECTURE.md). This will include backend setup, frontend setup,
database setup, and required environment variables.

## Status

**Pilot build — 2 experiments, 2-week timeline**, scoped down from the
full 5-experiment / 3-tier vision. See
[ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full-scope roadmap vs.
pilot scope.

<!-- TODO: the spec this repo was scaffolded from is internally
inconsistent about pilot scope — it separately states the pilot
"covers ALL 10 assessed experiments from the manual" while also
giving this exact "2 experiments... 5-experiment vision" status line
verbatim. Confirm the real pilot scope (2 vs. 10 experiments) with
the team before the second build session commits to either number. -->
