# CLAUDE.md — LabTutor development guide

This file guides any Claude Code session (or human developer) working
in this repository. Read it before writing code here.

## Project summary

LabTutor is a chemistry lab learning-support system for VIT's
BACHY105 (Applied Chemistry Lab) course, with two modes:

- **Socratic mode**: guides a student through an in-progress
  experiment step by step, verifying each intermediate result against
  the student's own data using deterministic computation, and nudging
  (never revealing the final answer) when something is inconsistent.
- **Diagnostic mode**: given a finished submission, independently
  recomputes the expected result from the manual's formulas, and if
  the result is wrong, tries to determine *why* — first via numeric
  signature detection, then a curated library of known non-numeric
  mistakes, and only escalates to human review if neither matches.

See [README.md](README.md) for the problem statement and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline,
tier breakdown, and pilot-vs-full-vision scope.

## Hard architectural rule — read this before touching Tier 1 or the LLM layer

**Tier 1 diagnosis logic — the math, the signature detection, and the
pass/fail determination — must NEVER be delegated to an LLM call.**
This includes:

- Computing an expected value from a student's inputs.
- Deciding whether a student's intermediate step or final result is
  correct.
- Classifying *why* a result is wrong (numeric signature detection).

LLMs in this system have exactly one job: **phrase an
already-computed diagnosis in natural language, grounded in a
retrieved passage from the course manual.** They never invent the
diagnosis, and they never see student data without a diagnosis
already attached for them to describe.

If you find yourself writing a prompt that asks an LLM to "check if
this is right," "decide what the student did wrong," or "compute the
expected value," **stop — this is a bug.** Flag it instead of writing
it. This rule applies even under deadline pressure, and even for
experiments that seem "too simple to bother with real Tier 1 logic."

**Experiments 7 and 8 — amended.** This file originally said those two
get "a stub that always escalates to Tier 3, not an LLM judgment call."
The build session deviated, but not identically for both — they are
different experiment shapes, corrected in
[docs/ARCHITECTURE.md §2.1.1](docs/ARCHITECTURE.md):

- **Experiment 8** (conformer analysis) has energy **ordering** checked
  deterministically (staggered below eclipsed, chair below boat). A
  consistent ordering still escalates rather than passing, and a model
  may add a low-confidence note about the student's method narrative
  (`backend/rag/qualitative.py`, restricted to `exp08` only).
- **Experiment 7** (Gabedit/ORCA orbital-energy runs) has no ordering to
  check — a single run has one HOMO and one LUMO, not two conformers to
  compare — so it uses a different deterministic checker instead
  (`ComputationSanityPlugin`: optimisation must not raise energy, LUMO
  must exceed HOMO), always escalating on a clean run exactly as
  Experiment 8 does. It has no narrative-note mechanism at all.

The hard rule above is intact for both — no model decides the ordering or
the sanity check — but Experiment 8 is the one place a model contributes
to a judgment at all. The full rationale and the containment measures are
recorded in [docs/ARCHITECTURE.md §2.1](docs/ARCHITECTURE.md). Do not
extend that exception to a third experiment; if one seems to need it, it
needs a
deterministic checker instead.

**Experiment 7 — guided walkthrough (added later in the build).** Exp7 now
has a second layer on top of `ComputationSanityPlugin`:
`backend/socratic_engine/walkthrough/` (`exp07_script.py`, `grader.py`,
`controller.py`, `service.py`) steps a student through Gabedit → ORCA →
Avogadro one instruction at a time, verifying each step with a question
only someone who actually did it can answer. This does **not** weaken the
hard rule above — it tightens the same boundary one layer earlier:

- Every question, its correct answer (or answer key/regex), every hint,
  every multiple-choice option's rationale, and every quiz item is
  **authored in `exp07_script.py` by a person**, not generated at runtime.
- `grader.py` matches a student's message against that authored key with
  regex/exact comparison only. It imports no LLM client, no `google.genai`,
  no retrieval module — checked by a repo test
  (`test_walkthrough_modules_import_no_model_or_retrieval_code`).
- `controller.py` (`take_turn`) is a pure function from (state, message) to
  the next state and reply. It decides whether to advance, hint, reveal, or
  probe again — the model is never asked "is this right?" or "what should
  happen next?".
- Numeric "report" answers (energies, HOMO/LUMO, electron counts) are
  checked by the **same** `ComputationSanityPlugin._sanity_violations`
  Tier 1 already uses (energy not up after optimisation, LUMO above HOMO),
  reused rather than re-implemented, plus one walkthrough-local check
  (shell-electron totals against the molecule's own electron count).
- The LLM is used for exactly one thing here, and only after the
  walkthrough has explicitly stepped aside: a genuine free-form side
  question mid-walkthrough, answered by the ordinary grounded Q&A path with
  a step-context line, then a code-appended "Back to Step N" line. Hooks,
  acknowledgements, hints, reveals and quiz feedback are all authored text
  chosen by code — zero model calls.

If you find yourself wanting to ask a model to write a new quiz item, grade
a free-text answer beyond regex matching, or decide when a step is "close
enough" — stop, that is the same bug this file already warns about, just
one level deeper into a specific experiment. Do not extend the walkthrough
pattern to a third experiment without the same authored-content, code-
decides discipline.

## Coding conventions

- **Language/framework**: FastAPI + Postgres + Next.js. Confirmed by the
  build session; the scaffolding's recommendation is now the decision.
  See [docs/ARCHITECTURE.md §4](docs/ARCHITECTURE.md). Tests run against
  SQLite so the suite needs no services.
- **Commits**: small, one logical change per commit. No AI
  co-author attribution in commit messages, ever.

### Non-negotiable: no Claude/AI attribution anywhere pushed to GitHub

This repo's owner pushes every commit themselves and does not want
Claude, or any AI tool, appearing in GitHub's contributor list,
commit history, or PR authorship for this repo — regardless of any
standing default (session-level or otherwise) that would normally add
attribution like `Co-Authored-By: Claude ...` or a `Claude-Session:`
link to commits/PRs.

**Before writing any commit message or PR description for this repo,
and before running or suggesting any `git push`, a Claude Code session
must:**

1. Never insert `Co-Authored-By: Claude ...`, `Generated with Claude
   Code`, a `Claude-Session:` link, or any equivalent attribution line
   into a commit message or PR description for this repo, even if a
   session-level default instructs otherwise elsewhere.
2. Not run `git push` on this repo unless the user has explicitly
   asked for that specific push. By default, prepare the commit and
   hand the user the exact command to push themselves.
3. Before actually pushing (only when explicitly asked to), run
   `git log --format='%H %an %ae%n%B---' <range>` and confirm no
   attribution lines and no unexpected author identity have crept in.
   If any are found, fix them (e.g. `git commit --amend` before
   pushing, never after) rather than pushing as-is.
- **Folder structure**: see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
  for the authoritative structure and what owns what; the actual
  layout is scaffolded under `/backend`, `/frontend`, `/docs`,
  `/golden_dataset`, and `/infra`.

## Testing philosophy

Every Tier 1 computation module (see `/backend/tier1_compute`) needs
unit tests built against **known correct answers computed by hand
from the manual's own worked examples.** The BACHY105 manual includes
worked sample calculations for at least some experiments — use those
numbers verbatim as ground truth test cases. Do not invent expected
values; if the manual doesn't provide a worked example for a given
experiment, say so explicitly in the test file rather than fabricating
one.

See [docs/golden_dataset_plan.md](docs/golden_dataset_plan.md) for the
full test data categories (worked examples, known deviations,
adversarial inputs, prompt-injection attempts, Socratic-mode probing).

## Security non-negotiables

- OAuth domain check (student vs. professor role) must happen
  **server-side**, on every request to a role-gated endpoint — never
  trust a client-supplied email claim, and never check only at login.
- No student can query or see another student's submission data,
  under any circumstance.
- All secrets (OAuth client IDs/secrets, LLM API keys, DB credentials)
  live in environment variables, never committed to the repo.
- LLM prompt templates must isolate student input from system
  instructions (e.g. clear delimiters, no string-concatenation of raw
  student text into the instruction block) to resist prompt injection.
