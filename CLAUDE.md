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
it. This rule applies even under deadline pressure, even for
experiments that seem "too simple to bother with real Tier 1 logic,"
and even for Experiments 7 and 8 (see ARCHITECTURE.md) — those get a
stub that always escalates to Tier 3, not an LLM judgment call.

## Coding conventions

- **Language/framework**: TBD, confirm with team. (Commit 5 of the
  scaffolding session proposed FastAPI + Postgres + Next.js as a
  recommendation, not a locked decision — verify before assuming.)
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
