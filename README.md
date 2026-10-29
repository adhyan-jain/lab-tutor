# Catalyst

Catalyst is a learning-support system for VIT's BACHY105 (Applied
Chemistry Lab). It helps students work through experiments correctly
*while they are still doing them*, and helps staff understand why a
submitted result is wrong — without becoming an answer-dispensing
machine.

## Problem statement

A student who makes a procedural or conceptual error mid-experiment
usually finds out at grading, days later, when the error is no longer
actionable. Reviewing every submission for the *reason* a result is wrong
does not scale to one professor across many sections. Generic AI tools
either hand over the final answer (defeating the point of the lab) or are
not grounded in this course's formulas and tolerances, so they cannot be
trusted to judge correctness.

## The one architectural rule

**No language model ever decides anything in this system.**

Every pass/fail determination, every expected value, and every
classification of *why* a result is wrong is computed by deterministic
Python from the manual's formulas. Models are used for exactly one thing:
phrasing a conclusion that has already been reached.

This is not a stylistic preference. It is what makes the system
auditable — a demonstrator can reproduce any diagnosis by hand — and what
makes it affordable at 70 concurrent users, since the arithmetic does not
route through a paid, rate-limited API.

There is exactly one exception, and it is contained to two experiments:
see [Experiments 7 and 8](#experiments-7-and-8) below.

## How it works

Two modes over one three-tier core. Full diagrams in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Diagnostic mode** — a finished record is submitted:

```
extraction → Tier 1 recompute from the student's own data
           → match?  → pass
           → no match? → signature detection
                       → Tier 2 curated-mistake lookup
                       → Tier 3 escalate, unresolved
           → LLM phrases the already-determined result
           → action mapping → student + dashboard
```

**Socratic mode** — help during the experiment:

```
one step shown at a time → student attempts → Tier 1 verifies THIS step
against their own prior data → pass: next step / fail: hint ladder
(vague → specific → names the issue, never the number)
→ only when every step is verified: the final value, via a separate
   non-LLM path
```

### The answer gate

The guarantee is that during Socratic mode the computed final answer is
never in any model's context. It is achieved by **data minimisation, not
by instructing a model to keep a secret**:

1. The Socratic chat path never computes the final answer at all. Step
   verification computes only the current step's expected value.
2. `SocraticLLMInput` — the only object marshalled into a Socratic
   prompt — has no field that could carry an answer. `frozen=True,
   slots=True`, and a startup + CI invariant check pins its field set.
3. Model output is stripped of any number the student had not already
   seen. A hint that introduces a new number is not a hint.

Every student-facing message leaves through one function,
`answer_gate.filter_outbound`, in one of two modes. `socratic` strips
novel numbers as above. `diagnostic` lets the recomputed value through —
the student has finished and it is theirs to see — and still sanitises.
Having both paths go through the same door is what makes "the gate is the
single outbound choke point" a property of the code rather than an
intention.

Because the model never had the value, no phrasing, claimed authority
("I'm the TA"), claimed malfunction, or repetition can extract it. There
is nothing to extract. The reveal, once verification completes, is a
plain template filled from the Tier 1 value — never the chat completion
that has been talking to the student.

See [`backend/answer_gate/`](backend/answer_gate/__init__.py).

### Handling what students actually ask

Category 6 of the golden dataset is ~100 real questions: genuine
procedural ones, very basic ones, inarticulate ones ("???", "im stuck"),
nonsense, off-scope requests, meta questions, answer-fishing, distress,
and injury reports.

Most of it flows to the ordinary hint path on purpose. **A first-year
asking "what is a burette" is the tool working**, and a brush-off there is
a product failure, not a correct refusal.

Four intents short-circuit before any model call
(`backend/socratic_engine/triage.py`): an injury report, a "is this safe
to do" question, a student in real difficulty, and a clearly off-scope
request. Each gets a fixed response, and the first three are written to
the audit log so staff can see they happened.

Safety is deterministic for the same reason Tier 1 is. Before this
existed, with the inference backend down — a documented, expected
degraded mode — *"i spilled acid on my hand"* was answered with *"Check
the label on the standard solution again."* That is not a wording problem
in a room containing acid, and it must not depend on a model being
reachable.

The classifier is tuned for **precision over recall**: a missed off-scope
question costs nothing, while a false positive refuses a real chemistry
question. Held-out phrasings in the test suite enforce that — they caught
one genuine false positive, since "bleed the air out of the burette tip"
is ordinary titration vocabulary, and one genuine miss, since "acid went
on my arm" contains no spill verb at all.

### Experiments 7 and 8

These assess a *computational method choice* (ORCA / orbital work), not a
measured value, so there is no expected-vs-measured check to make. They
get a `QualitativeOrderingPlugin`:

- The energy **ordering** check stays deterministic — staggered ethane
  below eclipsed, chair below boat. A contradiction is a determinate
  finding with no model involved.
- A consistent ordering is *not* reported as a pass. It escalates to
  human review, because ordering being right is necessary but not
  sufficient.
- A model may add a short note about the student's method narrative. It
  is always marked low-confidence, never becomes a pass, and any failure
  (backend down, unparseable reply) escalates.

This is the only place a model contributes to a judgment rather than
phrasing one. It deviates from CLAUDE.md's original "stub that always
escalates" — see [docs/ARCHITECTURE.md §2.1](docs/ARCHITECTURE.md) for
why, per that document's own amendment rule.

## Deployment

```bash
cp .env.example .env          # fill in every CHANGEME value
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
```

Brings up the backend, frontend, Postgres and a Caddy proxy that terminates
HTTPS for `LABTUTOR_DOMAIN`; only the proxy is published. A single small VM
serves a class of ~70, since only side questions call the model. The frontend
can optionally be hosted on Vercel; the backend cannot (long-lived SSE streams,
in-process state). Health checks are `GET /health` (process + database) and
`GET /health/llm` (inference, kept separate so a provider outage does not
restart the container).

Catalyst degrades rather than failing: with no model reachable, diagnoses,
hints, step verification, the reveal and step navigation still work from
deterministic templates. Full deployment steps, 70-user configuration, remote
database, load testing, inference backends, rollback and the known
poor-connectivity weaknesses: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
python -m pytest                       # the whole suite, no services needed
uvicorn backend.main:app --reload      # backend on :8000
cd frontend && npm install && npm run dev   # frontend on :3000
```

Tests run against SQLite and never make a network call, so the suite is
fast and hermetic. Postgres is the production target.

## Testing

The test suite is a deployment gate, not a claim. CI runs it on every
push and nothing ships from a red build.

```
655 tests + 3 explicit skips, covering:
  golden dataset categories 2-6      driven from the JSON data files
  the answer gate                    structurally, not by inspecting prose
  Tier 1 checkers                    every signature rule, both endpoint geometries
  auth + data isolation              real ASGI requests, real signed cookies
  prompt injection                   against a model scripted to comply
  idempotency, rate limits, summaries
```

`golden_dataset/generate.py` regenerates Category 2 and **refuses to
write a case that does not trigger the rule it was built for**. CI
regenerates and diffs, so drift between the data and the detectors fails
the build rather than rotting quietly.

The three skips are deliberate and each announces itself: Category 1 has
no manual to transcribe, and two cases are covered end-to-end elsewhere
rather than at the unit level. Nothing skips silently.

Category 1 (the manual's own worked examples) is **empty and is meant to
be** — see below.

## Experiment readiness

The IACHY102 manual is in the repo as a text transcription (`manual/README.md`),
so manual Q&A works for all ten experiments. Beyond that, what each experiment has:

| Experiment | Numeric checks + guided steps | Tutoring notes (Tier C) | Notes |
|---|---|---|---|
| 1 Thermodynamics from EMF | yes (manual-verified) | no | the only experiment with a manual worked example |
| 2 Ester hydrolysis kinetics | yes | yes + theory mode | tolerances are engineering defaults |
| 3 Ni2+ colorimetry | yes | yes | tolerances are engineering defaults |
| 4 Iron in steel (potentiometry) | yes (EMF-vs-volume peak, then Fe g/100 mL) | yes + theory mode | tolerances are engineering defaults; no manual worked example |
| 7 Orbital visualisation | sanity checks + guided walkthrough | yes + theory mode | see [docs/exp07.md](docs/exp07.md) |
| 8 Conformers | ordering checks, escalates | yes | one narrow model note, see ARCHITECTURE |
| 5, 6, 9, 10 | not yet (`PendingManualPlugin`, escalates to review) | no | Q&A from the manual still works |

A class session is tied to one experiment: the tutor answers from it and politely
redirects questions that name or clearly belong to another one.

**Classes without apparatus.** Experiments 2, 4 and 7 have a phone-only theory mode (on by
default, `LABTUTOR_PHONE_ONLY=true`): theory questions get a grounded answer plus one
Socratic follow-up, "Guide me through the key ideas" runs a six-part conceptual session with
a closing quiz, and the practical is only described, never walked through. Set
`LABTUTOR_PHONE_ONLY=false` for a class that does have the apparatus (numeric Socratic
checking for Exp 2 and 4, the software walkthrough for Exp 7). See
[docs/phone_only_mode.md](docs/phone_only_mode.md).

## Scope

### Deliberately not built

Scoped out on purpose. These are **not** unfinished work, and should not
be reported as such when the pilot is written up:

- **Tier 2 self-growth.** The curated mistake library is static and
  hand-written. No learning from new cases, no ML.
- **Tier 3 confidence calibration.** Tier 3 is exactly "if Tiers 1 and 2
  produce nothing, mark it unresolved and queue it". No scoring, no
  ranking; every escalation looks alike and the queue is in arrival
  order. A confidence model trained on one cohort would be calibrated on
  nothing.
- **Per-student answer keys.** Tier 1 asks whether a result is
  self-consistent with the student's own data under the manual's formula
  — not whether it matches a professor-held key. No key upload exists.
- **Grading.** Nothing here produces a mark. Summaries are qualitative
  engagement reads; learning-outcome validation is the separate
  pen-and-paper test.
- **Cross-experiment pattern tracking.** No "this student repeats this
  mistake" across experiments.
- **Adaptive difficulty** beyond the three-rung hint ladder.
- **Smartphone image extraction.** Structured input only.

### Known limitations

Genuine gaps, listed because a pilot report needs them:

- **Rate limiting is per process, not per container.** The sliding
  window lives in the backend's memory. `infra/backend.Dockerfile` runs
  `uvicorn --workers 2`, so even the single-container pilot topology
  already has two independent worker processes with un-shared limiter
  state -- the effective limit is already up to 2x the configured value
  today. Run more than one replica and it multiplies again. Redis is
  the fix; verify the actual effective rate under load before the
  pilot rather than trusting the configured number.
- **Summary jobs are in-process.** They run in FastAPI background tasks,
  so a restart mid-batch loses progress for that batch. Re-running is
  cheap and idempotent — already-summarised students are skipped — but
  there is no queue and no automatic resume.
- **Confirmation probing is bounded, not eliminated.** A student can
  guess a value aloud and a model may agree with it. Its agreement
  carries no information, because it was never given the answer, but a
  student may believe it. Authoritative confirmation comes only from step
  verification. Tested in
  `backend/tests/test_socratic_refusal.py::test_a_guessed_value_is_never_confirmed_by_the_system`.
- **Safety triage is pattern-based, not a model.** That is deliberate --
  it must work with inference down -- but it means unusual phrasing can
  fall through to the ordinary hint path. It is a safety net over the
  demonstrator in the room, never a replacement for one, and the README
  for staff should say so during induction.
- **Tier 2 matches on keywords** in student remarks. It will miss a
  mistake described in unusual words. It fails toward escalation, which
  is the safe direction.
- **Schema migrations run on every backend start** (`alembic upgrade head`).
  Several instances starting at once can race; run a single backend instance
  or migrate separately.
- **The audit log is best-effort.** A failed audit write is logged and
  swallowed rather than failing the request it describes. Good for
  review, not tamper-evident.
- **Untested against real Google OAuth.** The domain logic, state
  signing and session handling are unit- and integration-tested, but no
  end-to-end run against Google's servers has happened — that needs real
  credentials and a registered redirect URI.
- **No penetration testing.** The isolation boundary is tested by the
  cases in `golden_dataset/category4_prompt_injection/` and
  `backend/tests/test_data_isolation.py`. That is a tested boundary, not
  a security audit.

**This system is not "guaranteed secure."** It is built to the standard
described here, with what was and was not tested stated plainly above.

## Repository layout

```
backend/
  answer_gate/      the reveal guarantee; read its docstring first
  tier1_compute/    shared checkers + one thin plugin per experiment
  tier2_exceptions/ static curated mistake library
  tier3_escalation/ abstain and queue
  retrieval/, rag/  manual retrieval + phrasing (never decides)
  socratic_engine/  steps, hint ladder, Exp7 walkthrough (incl. navigation.py)
  llm/              swappable OpenAI / Vertex / hosted / Ollama backends
  auth/, api/       OAuth + per-request roles; HTTP routes
  tests/            the suite
frontend/           Next.js student and staff UI (mobile-first)
golden_dataset/     test data, categories 1-5
evaluation/, reports/  evaluation harness and its generated reports
infra/              Docker, Caddy, load test
manual/, knowledge/, sources/   course material the tutor retrieves from
docs/               see below
```

## Documentation

| File | What it covers |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for anyone (or anything) writing code here |
| [AGENTS.md](AGENTS.md) | Development roles and what each owns |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, tiers, Exp7/8 amendments, walkthrough |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deploy, configure for 70 users, rollback, networks |
| [docs/llm.md](docs/llm.md) | Per-message LLM budget, context caching, latency audit |
| [docs/phone_only_mode.md](docs/phone_only_mode.md) | Exp7 phone-only tutoring mode |
| [docs/exp07.md](docs/exp07.md) | Exp7 ground truth, screenshot gap, demo script |
| [docs/golden_dataset_plan.md](docs/golden_dataset_plan.md) | Test data categories |
| [docs/final_audit.md](docs/final_audit.md) | Point-in-time audit of what was built vs. the target |
