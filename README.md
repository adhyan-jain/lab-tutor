# LabTutor

LabTutor is a learning-support system for VIT's BACHY105 (Applied
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

Add credentials, run one command, done.

```bash
cp .env.example .env          # fill in every CHANGEME value
docker compose -f infra/docker-compose.yml up -d --build
```

That brings up the backend, frontend, Postgres and a Caddy reverse proxy
that terminates HTTPS and obtains a certificate automatically for
`LABTUTOR_DOMAIN`. Only the proxy is published on the host.

Before a real pilot you also need to:

1. **Put the manual in place** — drop `BACHY105.pdf` into `manual/`. See
   [What the manual unblocks](#what-the-manual-unblocks).
2. **Register the OAuth client** — Google Cloud Console, with the
   redirect URI `https://<your-domain>/api/auth/callback`.
3. **Generate a session secret** — `openssl rand -hex 32`.

Health checks:

- `GET /health` — process and database. Deliberately does **not** call
  the inference backend, so a paid provider is not probed by every
  load-balancer check.
- `GET /health/llm` — inference connectivity, separately, so an inference
  outage does not make the container look dead and get restarted.

### Remote DB (Supabase)

The bundled `db` service in `infra/docker-compose.yml` is plain Postgres
and works fine for local dev/pilot use, but for a shared/remote database
(e.g. for the marks-analytics data used in the paper), point the backend
at a Supabase project instead:

1. Create a Supabase project (Settings → Database has the connection
   string).
2. Use the **direct connection** (port 5432), not the pgbouncer
   transaction pooler on 6543 -- that pooler doesn't reliably support the
   prepared statements the async psycopg driver issues.
3. Set `LABTUTOR_DATABASE_URL` in `.env` to that connection string. It
   overrides every `POSTGRES_*` value above, so nothing else needs to
   change.
4. Run `alembic upgrade head` from `backend/` to create the schema on
   Supabase (production startup does not call `create_all()` -- see
   `backend/main.py`).

### Load-testing before the pilot

```bash
python infra/loadtest.py --students 70 --turns 6
```

Drives the real tutor path at section scale against whichever backend is
configured, reports p50/p95/p99 and error rate, and exits non-zero past
its thresholds. `--dry-run` exercises the harness without spending
inference. Run this against the real backend before the first session,
not during it.

## Inference backends

Selected by `LABTUTOR_LLM_BACKEND`. The provider is a URL in the
environment; no provider name is hardcoded anywhere.

| | `hosted` | `ollama` |
|---|---|---|
| Use | **The pilot runs on this** | Development and degraded mode only |
| Config | Any OpenAI-compatible `/chat/completions` endpoint (Cerebras, Groq, OpenAI, Together, …) | Local Ollama server |
| Concurrency | Provider's | Whatever one lab machine can do |

**Ollama on lab hardware is explicitly not a deployment target for real
student traffic.** A single machine serving a full section will queue
requests into timeouts. It exists so development and offline testing do
not require an API key. If you are considering it for the pilot, run
`infra/loadtest.py --students 70` against it first and read the p95.

### Rollback plan

A live pilot needs defined degraded behaviour, not a crash.

**LabTutor degrades rather than failing.** Every model call in this
system phrases something already decided, so an inference outage costs
polish, never correctness. With no model reachable at all:

- diagnoses are still computed and still shown, in deterministic template
  prose;
- Socratic hints are still selected by Tier 1 and shown verbatim;
- step verification and the reveal are entirely unaffected — neither ever
  used a model;
- per-student summaries fall back to the deterministic rendering.

If the hosted provider fails mid-session:

1. **Automatic** — with `LABTUTOR_LLM_AUTO_FALLBACK=true` (the default),
   a failed hosted call retries against the Ollama endpoint if one is
   reachable. Start it with
   `docker compose -f infra/docker-compose.yml --profile ollama up -d`.
2. **Manual switch** — set `LABTUTOR_LLM_BACKEND=ollama` in `.env` and
   `docker compose up -d backend`. Expect slower replies; the
   deterministic paths are unchanged.
3. **Accept template mode** — change nothing. Every call fails fast to
   templates and the session continues, less fluently. This is a
   legitimate way to finish a lab.
4. **Maintenance mode** — if the backend itself is unhealthy, stop
   `backend` and let Caddy serve the error; students fall back to the
   paper procedure for that session.

Check `GET /health/llm` to see which state you are in.

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

## What the manual unblocks

The BACHY105 PDF is not in this repository, and nothing was invented in
its absence. Concretely, until it is added:

| Blocked | State |
|---|---|
| The 8 numeric experiment plugins | Registered as `PendingManualPlugin`; raise `ManualNotTranscribedError` on use, so a submission escalates to review instead of getting a fabricated diagnosis |
| Socratic step decomposition for those 8 | The engine, hint ladder and gate are generic and tested, but the ordered steps come from the manual, so guided mode returns 503 for them. Only exp07/exp08 have steps today |
| Golden dataset Category 1 | Empty, with a README explaining why and the transcription procedure |
| Retrieval citations | Retrieval returns nothing; phrased output carries no citation |
| Experiment titles and numbering | Placeholders; even the 7/8 assignment is unverified |

Everything else — the four shared checker types, the answer gate, auth,
classrooms, storage, summaries, the dashboard, deployment, the test
suite — is complete and tested against a reference plugin
(`backend/tests/reference_plugin.py`) that wires the shared checkers
exactly as a real experiment will.

Adding an experiment is then configuration, not code: transcribe the
formula and tolerance into one thin plugin file. See
`backend/tier1_compute/experiments/_template.py` for a worked reference.

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
- **Schema is created at startup**, not migrated. Alembic is installed
  but no migration chain exists; a schema change during the pilot means
  a manual migration.
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
  tier1_compute/
    shared/         four reusable checker types + signature detectors
    experiments/    one thin config plugin per experiment
  tier2_exceptions/ static curated mistake library
  tier3_escalation/ abstain and queue
  rag/              manual retrieval + phrasing (never decides)
  llm/              swappable hosted/Ollama backends
  socratic_engine/  steps, verification, hint ladder
  auth/             OAuth, per-request role derivation
  api/              HTTP routes
  tests/            the suite
golden_dataset/     test data, categories 1-5
frontend/           Next.js student and staff UI
infra/              Docker, Caddy, load test
manual/             put BACHY105.pdf here
docs/               architecture and the dataset spec
```

Development roles and what owns what: [AGENTS.md](AGENTS.md).
Guidance for anyone (or anything) writing code here:
[CLAUDE.md](CLAUDE.md).
