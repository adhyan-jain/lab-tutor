# ARCHITECTURE.md

This is the reference document for LabTutor's pipeline, tier design,
data flow, and stack. Any implementation decision that contradicts
this document should either update this document (with a note on why)
or be treated as a bug.

> **Manual status (updated 2026-09-12).** The course's manual arrived —
> as **IACHY102** (VIT M.Tech Engineering Chemistry Lab), not the
> `BACHY105.pdf` this document and CLAUDE.md were written against. The
> two course codes may denote different programs entirely (M.Tech vs the
> B.Tech this repo's docs assumed); nothing in the manual PDF itself
> says which VIT course offering this LabTutor deployment is actually
> for, so that identification was taken on the user's word, not
> re-derived. Its text is transcribed in `manual/IACHY102_manual.md` (no
> PDF binary was deposited in the repo — see `manual/README.md`). The 10
> assessed experiments and their real content are documented there; the
> guesses this document and the per-experiment plugins made before the
> manual arrived were wrong in one confirmed place (Experiment 7 vs 8 —
> see §2.1.1) and unverified everywhere else. `docs/final_audit.md` has
> the full experiment-by-experiment status.
>
> **Update (2026-09-14).** `backend/rag/retrieval.py` previously pointed
> at a nonexistent `manual/BACHY105.pdf` and could not have parsed the
> markdown transcription anyway (`pypdf` on non-PDF text) — retrieval
> returned zero passages under every reachable configuration, verified
> live. Both are fixed: `build_index` now dispatches on file extension
> and chunks the markdown by its `## Experiment N ... (p.X-Y)` headings,
> and the default `LABTUTOR_MANUAL_PDF` points at the transcription.
> Retrieval is real again (19 passages, verified live) and citations now
> read "IACHY102 manual, p. ..." rather than the old BACHY105 string.
> Real Tier 1 plugins now exist for Experiments 1, 2, 3, 7 and 8
> (Experiment 7 via a new `ComputationSanityPlugin` — see §2.1.1);
> Experiments 4, 5, 6, 9, 10 still raise `PendingManualPlugin`. See
> `docs/final_audit.md` for the full status and for tolerance/fit-quality
> values in Exp 2/3 that are deliberate engineering defaults, not
> manual-derived numbers.

## 1. Pipeline overview

LabTutor has two modes. Both sit on top of the same three-tier
diagnosis core; they differ in *when* they run (mid-experiment vs.
after submission) and in what they're allowed to reveal.

### 1.1 Socratic mode (in-progress help)

```
Student working through experiment
        |
        v
[ Auth: role + classroom check ]
        |
        v
[ Classroom: resolve "active experiment" for this classroom ]
        |
        v
[ Socratic Engine ]
   - loads ordered official procedure steps for the active
     experiment (from the manual)
   - student submits their own intermediate value for step N
   - Tier 1 shared checker types verify step N against the
     student's OWN prior data (never against a hidden answer key
     revealed to the student)
        |
        +--> consistent? --> unlock step N+1, no answer ever shown
        |
        +--> inconsistent? --> Adaptive Hint Ladder:
                 attempt 1: vague nudge ("check your electrode
                            polarity assignment")
                 attempt 2: more specific nudge (points at the
                            exact quantity that looks off)
                 attempt 3+: names the category of error without
                            giving the corrected number
             (escalating specificity, but the final numeric
             answer is NEVER produced by this mode)
```

Note: hint *phrasing* may go through the RAG/LLM phrasing layer for
natural language, but the ladder level and what category of error is
being hinted at is decided by Tier 1 logic, not the LLM.

### 1.2 Diagnostic mode (after submission)

```
Student submits finished record
        |
        v
[ Auth: role + classroom check ]
        |
        v
[ Extraction: parse submission into structured fields ]
        |
        v
[ TIER 1 — deterministic, no LLM ]
   a. Recompute expected result from student's OWN inputs using
      the manual's exact formula for the active experiment
      (via the matching shared checker type)
   b. Compare to student's reported result
        |
        +--> matches (within manual's stated tolerance)?
        |         --> PASS, done
        |
        +--> does not match?
                  --> run signature detection against the raw data
                      shape (peak sharpness, monotonicity, R²,
                      sign, endpoint geometry) for this experiment's
                      plugin
                        |
                        +--> clean signature match?
                        |        --> diagnosis determined, tier = 1
                        |
                        +--> no clean signature?
                                 v
                        [ TIER 2 — curated known-mistake library ]
                        checks this experiment's library of
                        previously catalogued non-numeric mistakes
                                |
                                +--> match? --> diagnosis
                                |     determined, tier = 2
                                |
                                +--> no match?
                                         v
                                [ TIER 3 — escalation ]
                                explicitly ABSTAIN. Enqueue for
                                human TA/professor review. Do not
                                guess.
        |
        v
[ RAG / LLM phrasing layer ]
   Takes the already-determined diagnosis (tier 1, 2, or "escalated,
   no diagnosis yet") + retrieves the relevant manual passage, and
   phrases it in natural language for the student and/or the
   dashboard. Never invents or overrides the diagnosis.
        |
        v
[ Summaries (async) ]
   Pre-summary AI sanity check + a per-student trajectory-based
   2-line summary for the professor dashboard. This is a
   qualitative engagement/understanding read, not a grading
   signal — it does not re-compare against an answer key.
        |
        v
[ Dashboard API --> Professor/TA dashboard ]
   Shows per-student results, diagnoses, tier reached, and the
   Tier 3 review queue.
```

### 1.3 Conversational routing (added a later session)

The two modes above run behind a single chat surface
(`POST /api/chat/messages`), not two separate UIs. Deciding *which* of
the three (Q&A / Socratic / diagnostic) a given message is for was
originally pure keyword matching (does it contain numbers? does it read
like "guide me"?), which correctly refuses to guess about anything it
can't detect deterministically, but also cannot tell a genuine
mid-experiment question ("why is V_inf needed?") from a follow-up that
only makes sense given the conversation ("why?").

`backend/router/` sits in front of that dispatch as an LLM-driven
routing layer: given the message, a bounded window of the thread's own
prior turns, and the classroom's active experiment, it decides `qa` /
`socratic` / `diagnostic` / `clarification` / `out_of_scope` and
(`qa` only) an optional context-expanded search query. It is
**routing-only, never authoritative** — Tier 1-3 still computes every
diagnosis, the Socratic engine and answer gate still own step
verification and the reveal, and `classify_scope`/`resolve_status`
still independently decide whether a `qa`-routed message is actually
answerable. Any failure of the router (unavailable, malformed output,
low confidence, disabled) falls back to the original keyword-based
dispatch unchanged. See `backend/router/router.py`'s module docstring
for the exact authority boundary, and `docs/handoff_phase4.md` for how
and why this was built.

## 2. Pilot scope vs. full vision

| Piece | Pilot (2-week timeline) | Full vision (deferred) |
|---|---|---|
| Experiment coverage | All 10 assessed experiments, via the templated plugin system (scope conflict resolved — see below) | No further experiments; the plugin system is the extension point |
| Tier 1 (deterministic compute + signature detection) | Full — built for the pilot experiments via shared checker types | Extended to all remaining experiments; Experiments 7/8-equivalent (non-numeric, method-choice experiments) stay stub-escalate permanently, by design, not as a pilot cut |
| Tier 2 (known-mistake library) | Seeded with a handful of manually-entered known mistakes per pilot experiment | Adaptive growth: TAs add newly-observed mistakes over time via a curation workflow |
| Tier 3 (escalation) | Blanket escalation to a review queue — no confidence calibration, every abstain looks the same | Calibrated confidence model, possibly prioritizing the queue by likely severity/frequency |
| Cross-experiment pattern tracking | None | Track whether a given student repeats the same mistake type across experiments |
| Socratic mode | Built for pilot experiments | Extended alongside Tier 1 coverage |
| Auth | Full (both roles, env-configured domains, server-side enforcement) | Same — no deferred scope here |
| Classrooms | Full (persistent, class-code join, active-experiment tagging) | Same — no deferred scope here |

> **RESOLVED — scope conflict.** The scaffolding flagged that the plan
> said both "all 10 assessed experiments, templated" and "2 experiments,
> scoped down from a 5-experiment vision". The build session took **10**,
> because the brief's scope section states it explicitly and at length
> (naming the shared checker types and the thin-plugin structure that
> only make sense across many experiments), while the two-experiment
> line survives only in a leftover status sentence. The choice is cheap
> either way: with the templated system, an experiment is a config file,
> so the cost of ten slots over two is eight small files — currently
> eight loud stubs. Say so if this is backwards.

### 2.1 Amendment: Experiments 7 and 8 are not blanket stubs

CLAUDE.md and the original version of this document said the two
computational experiments get "a stub that always escalates to Tier 3,
not an LLM judgment call". The build session deviated, deliberately, and
this section records why — per the amendment rule at the top of this
file.

What was built instead (`QualitativeOrderingPlugin`):

- The conformer **energy ordering** is checked **deterministically** —
  staggered below eclipsed, chair below boat. No model is involved in
  that check, so the hard rule in CLAUDE.md is not weakened: a machine
  contradiction is still found by arithmetic.
- A consistent ordering is **not** a pass. It returns `NOT_APPLICABLE`
  and escalates, because ordering being right is necessary but not
  sufficient for the thing these experiments actually assess.
- A model may add a short note on the student's method narrative
  (`backend/rag/qualitative.py`). It is always marked low-confidence,
  can never produce a pass, and escalates on any failure.

Why deviate at all: a blanket stub gives a demonstrator no more
information than "look at this", for every single submission. Checking
the ordering deterministically is free, is reproducible, and catches the
common concrete error (swapped geometries, an unconverged job) before it
reaches a human.

Why keep it contained: this is the only place a model contributes to a
judgment. `qualitative_note` raises for any experiment id outside
`{exp08}`, and a test asserts exactly one plugin is of this kind. If
another experiment appears to need this, that is a signal the experiment
needs a deterministic checker — not that the exception should grow.

### 2.1.1 Correction (2026-09-12): it is one experiment, not two

The IACHY102 manual (course code corrected from BACHY105 — see the
"Manual status" note above) arrived and showed the guess in §2.1 was
half wrong about *which* experiment is which, though right about the
mechanism and about there being exactly two conformer-ordering pairs to
check:

- **Experiment 8** ("Conformational analysis of cyclohexane and ethane
  molecules and plotting the potential energy profile", manual p.43–47)
  is the *only* ordering-check experiment, and covers **both** molecule
  pairs (ethane staggered/eclipsed **and** cyclohexane chair/boat/
  twist-boat/half-chair). `exp08.py` now registers both sets of
  orderings under one plugin.
- **Experiment 7** ("Build atoms and molecules... calculating the
  orbital contributions", manual p.39–42) is a **different** experiment:
  a Gabedit → ORCA → Avogadro workflow producing one HOMO/LUMO orbital
  energy per run (CH4 and O2, six method/basis-set combinations each).
  It has no ordering to check — a single run has one HOMO and one LUMO,
  not two conformers to compare — so `QualitativeOrderingPlugin` does not
  fit it. `backend/rag/qualitative.py`'s model-note exception is narrowed
  to `{exp08}` accordingly (Exp 7 has no narrative-note mechanism at all).

**Update (2026-09-14): the fifth checker type now exists.** Exp 7 is
implemented via `registry.ComputationSanityPlugin` — it checks two facts
that hold regardless of molecule, method or basis set (energy must not
increase after optimisation; LUMO must be higher than HOMO), and never
returns PASS, escalating to Tier 3 on a clean run exactly as Exp 8 does,
because the method/basis-set choice itself still needs a human eye.
**Known shared limitation, Exp 7 and Exp 8 both:** because neither
plugin's `check_step` can honestly return PASS, and `handle_attempt`
(Socratic's `/attempt` endpoint) only advances the step index on PASS,
a student can open a session for either experiment and chat about it,
but cannot step-by-step "complete" it through `/attempt` — that always
returns a hint, never advances, never sets `all_steps_complete`. The
diagnostic submission path (`plugin.check(...)`, used by
`POST /api/submissions`) and the free-text Socratic chat path
(`tutor_reply`, which never calls `check_step`) both work as intended for
both experiments; only step-by-step numeric advancement does not. This
was discovered, not designed — see `docs/final_audit.md` — and fixing it
properly (giving the Socratic step machine a third outcome between
"advance" and "hint forever") is future work, not something patched
around here with a fake PASS.

See `manual/IACHY102_manual.md` and `docs/final_audit.md` for the full
per-experiment mapping against the real manual.

## 3. Data flow diagram

```
                         +-------------------+
                         |   Student (web)    |
                         +---------+----------+
                                   |
                                   v
                    +--------------------------+
                    |  Google OAuth (frontend)  |
                    +-------------+------------+
                                   |
                                   v
          +----------------------------------------------+
          |  auth/ : server-side domain check on EVERY    |
          |  role-gated request                           |
          |    - @vitstudent.ac.in            -> student  |
          |    - env-configured domain(s)     -> professor|
          |    - anything else                -> rejected |
          +----------------------+-------------------------+
                                   |
                     +-------------+--------------+
                     |                             |
                     v                             v
         +-----------------------+     +---------------------------+
         | classrooms/           |     | classrooms/ (professor)   |
         | student joins via     |     | create classroom, get     |
         | class code, sees      |     | high-entropy class code,  |
         | classroom's active    |     | set active experiment     |
         | experiment            |     | before each session       |
         +-----------+-----------+     +---------------------------+
                     |
        +------------+-------------+
        |                          |
        v                          v
+---------------+       +-----------------------+
| Socratic mode |       | Diagnostic mode        |
| (in progress) |       | (finished submission)  |
+-------+-------+       +-----------+------------+
        |                            |
        v                            v
+------------------------------------------------+
|      Tier 1 / Tier 2 / Tier 3 pipeline          |
|      (see section 1.2 above)                    |
+---------------------+----------------------------+
                       |
                       v
        +-------------------------------+
        |  rag/ : LLM phrasing layer     |
        |  (grounded in manual passages) |
        +---------------+-----------------+
                       |
         +-------------+--------------+
         |                            |
         v                            v
+------------------+       +-------------------------+
| Student-facing    |       | summaries/ (async) +     |
| result / hint      |       | dashboard_api/           |
+-------------------+       +------------+-------------+
                                          |
                                          v
                             +-------------------------+
                             | Professor/TA dashboard   |
                             | (results, diagnoses,     |
                             |  Tier 3 review queue)    |
                             +-------------------------+
```

## 4. Stack

**CONFIRMED** by the build session. The scaffolding left this as a
recommendation requiring explicit confirmation; it is confirmed as
written below, with the LLM provider left deliberately unfixed (it is an
endpoint URL in the environment, not a name in the code).

- **Backend**: FastAPI (Python) — matches the Tier 1 compute work
  being numeric/scientific Python, and keeps extraction/tier1/tier2/
  tier3/rag as clearly separated modules within one service.
- **Database**: Postgres — relational fit for classrooms, students,
  submissions, and the Tier 2 known-mistake library.
- **Frontend**: Next.js (TypeScript) — student and professor-facing
  UI, OAuth flow, dashboard.
- **LLM inference**: a hosted LLM API (e.g. Anthropic/OpenAI-class
  provider — exact provider TBD, confirm with team) as the **primary**
  inference path, used only for the RAG phrasing layer.
- **Local Ollama endpoint**: documented as a **fallback / dev-only**
  option. **Ollama running on lab hardware is explicitly NOT the
  primary production inference path** — it does not have the
  concurrency headroom for a full classroom hitting it at once. It
  exists so development and offline testing don't require a hosted
  API key, not as a deployment target for real student traffic.

Confirmed as above. The one refinement worth recording: the "hosted LLM
API" slot is provider-agnostic in code. Any OpenAI-compatible
`/chat/completions` endpoint works, supplied as `LABTUTOR_LLM_BASE_URL`,
so swapping providers mid-pilot is an environment change and a restart.

## 5. Folder structure

See the repo root for the actual scaffolded structure. Summary of
what owns what (also see [AGENTS.md](../AGENTS.md) for the
corresponding development roles):

Three packages were added during the build that the scaffolding did not
anticipate, listed first:

- `/backend/answer_gate` — the single component every outbound student
  response passes through, and the home of the reveal guarantee. Read its
  module docstring before changing anything in Socratic mode.
- `/backend/llm` — the swappable hosted/Ollama backend interface. Shared
  infrastructure rather than role-owned, because both `rag/` and
  `summaries/` need it. Nothing in `tier1_compute/` may import it.
- `/backend/api` — HTTP routes. All logic lives in the packages they
  import; these files are wiring, validation and persistence only.

- `/backend/extraction` — parsing submissions into structured fields
- `/backend/tier1_compute/shared` — reusable checker types:
  `direct_formula`, `calibration_curve`, `endpoint_detection`,
  `regression_slope`
- `/backend/tier1_compute/experiments` — one thin config/plugin file
  per experiment, built on the shared checker types; the two
  non-numeric, method-choice experiments (referred to in planning as
  "Experiments 7 and 8" — re-verify the real numbering against the
  manual) get a stub plugin that always escalates to Tier 3
- `/backend/tier2_exceptions` — curated known-mistake library
- `/backend/tier3_escalation` — human review queue
- `/backend/rag` — retrieval over the manual PDF + LLM phrasing layer
- `/backend/socratic_engine` — step ordering, per-step verification,
  adaptive hint ladder
- `/backend/auth` — OAuth, server-side role determination, enforcement
- `/backend/classrooms` — classroom CRUD, join-by-code, active
  experiment
- `/backend/summaries` — async trajectory-based summary job
- `/backend/dashboard_api` — professor/TA-facing API
- `/backend/tests` — automated test suite
- `/frontend/app`, `/frontend/components`, `/frontend/lib` — Next.js
  app
- `/docs` — this file, plus `golden_dataset_plan.md`
- `/golden_dataset` — actual test data (generated by the second
  build session against `docs/golden_dataset_plan.md`)
- `/infra` — Docker/deployment config
