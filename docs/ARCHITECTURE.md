# ARCHITECTURE.md

This is the reference document for LabTutor's pipeline, tier design,
data flow, and stack. Any implementation decision that contradicts
this document should either update this document (with a note on why)
or be treated as a bug.

> **TODO**: this document was written during repo scaffolding, before
> the BACHY105 manual PDF was present in the repo. The experiment
> list, exact formula shapes, and worked-example numbers below are
> placeholders/structural only — re-derive the actual experiment
> count, names, and formulas from whatever manual file is actually
> committed at the repo root before building Tier 1 plugins.

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

## 2. Pilot scope vs. full vision

| Piece | Pilot (2-week timeline) | Full vision (deferred) |
|---|---|---|
| Experiment coverage | 2 experiments (TODO: confirm which 2 once manual is in repo — see scope-conflict TODO below) | Remaining experiments, up to all assessed experiments in the manual |
| Tier 1 (deterministic compute + signature detection) | Full — built for the pilot experiments via shared checker types | Extended to all remaining experiments; Experiments 7/8-equivalent (non-numeric, method-choice experiments) stay stub-escalate permanently, by design, not as a pilot cut |
| Tier 2 (known-mistake library) | Seeded with a handful of manually-entered known mistakes per pilot experiment | Adaptive growth: TAs add newly-observed mistakes over time via a curation workflow |
| Tier 3 (escalation) | Blanket escalation to a review queue — no confidence calibration, every abstain looks the same | Calibrated confidence model, possibly prioritizing the queue by likely severity/frequency |
| Cross-experiment pattern tracking | None | Track whether a given student repeats the same mistake type across experiments |
| Socratic mode | Built for pilot experiments | Extended alongside Tier 1 coverage |
| Auth | Full (both roles, env-configured domains, server-side enforcement) | Same — no deferred scope here |
| Classrooms | Full (persistent, class-code join, active-experiment tagging) | Same — no deferred scope here |

> **TODO — scope conflict to resolve with the team before Commit 6 /
> second build session**: the planning discussion that produced this
> scaffolding request describes the pilot as covering "ALL 10 assessed
> experiments from the manual" with a templated plugin system, but
> separately specifies the README/status text as "2 experiments,
> scoped down from a 5-experiment vision." These two scope statements
> are inconsistent. Do not silently pick one — confirm the real pilot
> experiment count against the actual manual and the team's current
> plan before building Tier 1 plugins.

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

**Recommended** (confirm with team before treating as final):

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

This stack is a recommendation from the scaffolding session, not a
locked-in decision — the second build session should confirm it (or
override it) explicitly rather than silently assuming it.

## 5. Folder structure

See the repo root for the actual scaffolded structure. Summary of
what owns what (also see [AGENTS.md](../AGENTS.md) for the
corresponding development roles):

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
