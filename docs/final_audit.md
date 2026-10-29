# Final audit — Catalyst vs the Phase 2 build/audit/hardening request

Date: 2026-09-12, updated 2026-09-14 (§7). Scope note up front, because
it governs every verdict below: **the Phase 2 request describes a
different, much larger product than what exists in this repository**,
and this audit says so rather than inventing evidence to close the gap.
See "Architecture mismatch" before reading the checklist.

## 0. Architecture mismatch (read this first)

The Phase 2 request assumes an already-built system with: a vector
database, an embeddings/chunking/reranking pipeline, image-aware
(multimodal) page retrieval, a three-level scope classifier, an adjacent-
knowledge layer, a 70-concurrent-user load-test harness, an automated
LLM-based evaluation suite hitting a real model, and 550–750 golden QA
cases across 10 experiments. It refers to a prior "Antigravity" build,
`docs/current_state_audit.md`, and `docs/handoff_phase2.md`.

None of that exists in this repository, and none of those files exist.
What exists (`git log`, all first-party commits) is **Catalyst**: a
Socratic/Diagnostic chemistry-lab tutor built around a *deterministic*
Tier 1 compute layer (`backend/tier1_compute/`) with a thin,
non-vector, TF-IDF-style text retrieval module (`backend/rag/
retrieval.py`) whose only job is to hand a citation to an LLM
*phrasing* layer — never to decide correctness. This is a coherent,
well-tested, much smaller system than the one the request describes.

The request also names a manual (`IACHY102-2026-27-manual_2_260830_
133124.pdf`) that turned out to be for a *different course* than the one
CLAUDE.md and every doc in this repo were written against — the repo
says **BACHY105** (a B.Tech applied-chemistry lab); the manual's own
title page says **IACHY102**, "FOR FIRST/SECOND SEMESTER M.TECH." Since
these may be different VIT course offerings entirely, and nothing in
the manual text says this Catalyst deployment is for the M.Tech course,
that identification was taken on the user's instruction in this
session, not independently verified. If it's wrong, everything below
that treats IACHY102 as authoritative needs re-checking against the
right manual.

Given this, the audit below is honest about **what this repository
actually is** against the request's checklist, not a fabricated status
report pretending the assumed architecture is present.

## 1. What was audited

- Full git history (`git log --oneline`, all 17 commits) and working
  tree (`git status` — clean before this session's changes).
- Every doc: `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`,
  `docs/golden_dataset_plan.md`. `docs/current_state_audit.md` and
  `docs/handoff_phase2.md`, named by the request, do not exist.
- `backend/` in full: `tier1_compute/` (shared checkers + all 10
  experiment plugins + registry), `rag/` (retrieval, phrasing,
  templates, qualitative), `socratic_engine/`, `answer_gate/`,
  `tier2_exceptions/`, `tier3_escalation/`, `auth/`, `classrooms/`,
  `api/`, `dashboard_api/`, `summaries/`, `extraction/`, `models.py`,
  `pipeline.py`, `db.py`, `config.py`, `data_access.py`, `idempotency.py`,
  `ratelimit.py`, `audit.py`.
- `frontend/` (Next.js app: student, faculty, faculty/[classroomId] pages).
- `golden_dataset/` (6 categories + generator) and `backend/tests/`
  (18 test files, 663 test cases before this session's edits).
- `infra/` (Docker Compose, Caddyfile, `loadtest.py`).
- The three files the user added to the working tree this session
  (`BTech_Lab_V5_09072025.docx`, `ML_lab_manual_08.07.25.docx`,
  `script_stu.ipynb`) — noted as Tier B (course-supplied scripts/
  notebooks per the request's source hierarchy) but **not opened or
  transcribed in this pass**; they are `.docx`/`.ipynb`, not text tools
  read directly, and reading them was out of scope for this turn.
- The manual content, pasted in-chat as the IACHY102 PDF's extracted
  text (51 pages), now transcribed to `manual/IACHY102_manual.md`.
- Ran the full backend test suite after every code change
  (`python3 -m pytest backend/tests`): 663 passed, 1 skipped (a
  pre-existing, unrelated skip), 0 failed, at the end of this session.

## 2. Per-request-section verdict

| # | Request section | Verdict | Notes |
|---|---|---|---|
| 1 | Tier 1 diagnosis never delegated to an LLM | **PASS** | Structurally enforced: `tier1_compute` has no LLM import anywhere (`backend/rag/qualitative.py` is the one documented, contained exception, and even it never resolves a verdict — see below). Confirmed by reading, not just by the doc's claim. |
| 2 | Full audit of ingestion/chunking/embeddings/vector DB/reranking/metadata filtering/scope classifier | **NOT IMPLEMENTED** | There is no embeddings pipeline, no vector DB, no reranker, no metadata filter, no scope classifier of any kind. `retrieval.py` is ~170 lines: extract PDF text with `pypdf`, chunk on blank lines, TF-IDF cosine-ish scoring, top-k. This is a legitimate, working, *much smaller* thing — it is not the system §2 assumes exists to be audited for correctness. |
| 3 | Do not preserve bad architecture (reject retrieval-only scope detection, giant prompts, hallucinated citations, etc.) | **N/A / mostly moot** | The listed anti-patterns mostly presuppose the RAG system in §2. What *is* present and worth checking: `backend/rag/phrasing.py` isolates student text with delimiters and never lets a model's reply override a pre-computed verdict (`answer_gate/gate.py` enforces this — see row 22). No evidence of giant whole-manual prompts (only top-k passages, capped, are ever concatenated into a prompt — see `qualitative.py`'s 1200-char cap). |
| 4 / 4A | All 10 experiments implemented/routable/searchable/cited/scope-aware/tested | **PARTIAL — see per-experiment table below** | 1 of 10 experiments (Exp 1) has a real Tier 1 plugin with a manual-verified worked-example regression test, added this session. The other 9 are honestly `PendingManualPlugin` (raise rather than guess), now with reasons that state *why* (formula-shape known, no worked example vs. genuinely more analysis needed) instead of the stale "manual not present." None of the 10 have RAG-style "routing," a scope classifier, or citation validation in the sense §6/§18 describe, because that layer does not exist (see row 2). |
| 5 | Source hierarchy (Tier A/B/C/D) enforced | **NOT IMPLEMENTED** | No tiering exists. Retrieval has exactly one source (the manual index) and no adjacent-knowledge or general-model-knowledge layer to rank against it. |
| 6 | Three-level scope classification (IN_SCOPE/ADJACENT/OUT_OF_SCOPE × supported/insufficient/human-review) | **NOT IMPLEMENTED** | No scope classifier exists at all — not a bad one, none. Retrieval returning zero passages is not used as an out-of-scope signal anywhere in this codebase (there is no such branch to check), so the specific bug pattern §6 warns against doesn't currently exist either, for the same reason: the whole mechanism is absent. |
| 7 | Adjacent knowledge layer (`knowledge/adjacent/`, policy doc) | **NOT IMPLEMENTED** | Directory does not exist. Not created this session — building a real, curated adjacent-knowledge dataset with correct scope/confidence/citation metadata per topic is substantive content work, not a mechanical fix, and doing it quickly risks exactly the "plausible-sounding invented content" CLAUDE.md forbids. |
| 8–9 | Experiment 7 flagship demo, image-aware page retrieval, 150–200+ golden cases | **NOT IMPLEMENTED** | Experiment 7 in the *real* manual (p.39–42) is a Gabedit→ORCA→Avogadro orbital-contribution workflow (CH4, O2), not the ethane-conformer check the pre-existing code had registered under that id. That mismatch is fixed this session (see §3 below) but the experiment itself has zero Tier 1 checker, zero golden cases, and no image/page retrieval of any kind — there is no image handling anywhere in the codebase to begin with (`retrieval.py` extracts text only). |
| 10–13 | Experiment 8/2/3, remaining six, full golden distribution (~550–750 cases) | **NOT IMPLEMENTED at the volume requested** | Golden dataset currently has 6 categories per `docs/golden_dataset_plan.md`, populated for categories 2–6 with synthetic/structural cases (not manual-numbers-dependent) plus one new Category 1 case (Exp 1). Total case count is nowhere near 550–750, and the 9 experiments without a Tier 1 plugin cannot get calculation-grounded golden cases yet without inventing numbers. |
| 14–19 | Golden test schema, automated evaluator, RAG/retrieval evaluation, citation validation, image-aware RAG tests | **NOT IMPLEMENTED** | No evaluator producing `reports/latest_evaluation.json` exists; building a real one requires the scope classifier and retrieval system from rows 2/6/7, none of which exist yet. |
| 20 | 70/50/25/10-user load test | **NOT EXECUTED** | `infra/loadtest.py` exists (pre-dates this session) and is a real, runnable Locust-style script per `docs/ARCHITECTURE.md`, but no load test was run in this session — no backend server was started against a live Postgres, and running one was out of scope for an audit-and-fix pass with no confirmed deployment target. Marking this NOT EXECUTED rather than claiming a result, per the request's own §32/§34 rule. |
| 21 | Bounded LLM concurrency, caching, timeouts, retries, rate limiting, circuit breaker | **PARTIAL** | `backend/ratelimit.py` and `backend/idempotency.py` exist and are tested (`test_single_fire_and_summaries.py`). `backend/llm/client.py` was not re-audited line-by-line this session for retry/backoff/circuit-breaker behavior specifically — flagging as unverified rather than PASS. |
| 22 | Answer gate / safety | **PASS** | `backend/answer_gate/gate.py` + `test_answer_gate.py` exist and were exercised by the full suite this session (663 passed). Both diagnostic and Socratic output are routed through it per `git log` (`c141d6a Route diagnostic output through the answer gate too`). |
| 23 | Prompt injection resistance | **PARTIAL** | `golden_dataset/category4_prompt_injection/` and `backend/tests/test_phrasing_injection.py` exist and pass. Coverage is against the existing (small) RAG/phrasing surface, not against a scope-policy/source-hierarchy layer that doesn't exist yet. |
| 24 | Data isolation / server-side authz | **PASS (re-verified)** | `backend/tests/test_data_isolation.py` exists and passes; this session ran it after editing it (one `exp07`→`exp08` fix, unrelated to the isolation logic itself) and it still passes. |
| 25–26 | Frontend demo quality, demo runbook | **NOT VERIFIED / NOT IMPLEMENTED** | Frontend was not started or exercised in a browser this session (no UI changes were made, so this was not re-verified). `docs/demo_runbook.md` does not exist. |
| 27–28 | Observability, error handling | **PARTIAL** | `backend/audit.py` exists; not re-audited line-by-line against the request's specific field list (request ID, retrieval latency, etc.) this session. |
| 29–33 | Per-experiment table, quality gates, final regression, deliverables checklist | **See §3 below and the acceptance-gate summary at the end.** | |

## 3. Concrete fixes made this session

1. **`manual/IACHY102_manual.md`** — the manual's text (pasted in-chat)
   transcribed into the repo as the new source of truth, with page
   numbers preserved for citation, every formula transcribed verbatim,
   and every worked numeric example the manual actually prints
   (Experiment 1 only — see the summary table inside that file).
   The PDF binary itself was not deposited (only pasted as chat content),
   so `manual/README.md`'s instruction to drop `BACHY105.pdf` there is
   now doubly stale — updated separately (see below).

2. **Experiment 7/8 identity, corrected.** The pre-existing code (before
   the manual arrived) guessed Experiment 7 = ethane conformers,
   Experiment 8 = cyclohexane conformers, as two separate ordering
   checks. The real manual has **one** experiment (8) covering **both**
   ethane and cyclohexane conformer energies, and Experiment 7 is an
   unrelated DFT/orbital-contribution workflow with no ordering to
   check at all (a single run has one HOMO and one LUMO, not two
   conformers to compare).
   - `exp08.py` rewritten: now a `QualitativeOrderingPlugin` with both
     ethane and cyclohexane orderings and 4 Socratic steps (was 2).
   - `exp07.py` rewritten: now honestly `PendingManualPlugin`, with a
     reason explaining the real problem shape (needs a fifth,
     not-yet-built "computation sanity" checker type — job completion +
     HOMO<LUMO + energy decreased after optimization — not an ordering
     check) instead of silently keeping the wrong ethane logic live.
   - `backend/rag/qualitative.py`'s `ALLOWED_EXPERIMENTS` narrowed from
     `{exp07, exp08}` to `{exp08}`, since Exp 7 no longer uses this
     mechanism.
   - `docs/ARCHITECTURE.md` §2.1 amended (§2.1.1) recording the
     correction, in the pattern the document's own header requires.
   - 8 test files updated to stop asserting the wrong mapping
     (`test_pipeline_and_tiers.py`, `test_phrasing_injection.py`,
     `test_single_fire_and_summaries.py`, `test_data_isolation.py`,
     `test_student_questions.py`) — full suite re-run green after each
     change.

3. **Experiment 1 (Zn–Cu EMF thermodynamics) fully implemented**, the
   one experiment the manual gives a complete worked numeric example
   for (p.13–15): Nernst-equation `Ecell` as an intermediate Socratic
   step, `ΔG = -nFEcell` as the final checker. Both formulas verified
   against the manual's own numbers (`backend/tests/test_exp01_emf.py`,
   `golden_dataset/category1_worked_examples/exp01.json`). ΔH/ΔS were
   **not** implemented: the manual's method pools ΔG at two different
   temperatures from two different runs before differencing, a shape
   none of the four shared checker types cover — flagged rather than
   forced into the wrong one.

4. **Experiments 2–6, 9, 10**: reason strings corrected from the stale
   "BACHY105 manual not present in the repository" (now false — the
   manual is present) to an accurate, experiment-specific statement of
   what's actually missing (a worked numeric example to verify a
   tolerance against — the formula itself is known and cited to a page
   range in every case). Not implemented as real checkers this session:
   each needs a deliberate tolerance-policy decision (the manual gives
   no experiment-specific numeric acceptance band, only the course-wide
   marks-vs-error-percentage rubric on p.8, which is not the same thing
   as a Tier 1 self-consistency tolerance and must not be conflated with
   one), which is a judgment call worth making individually per
   experiment rather than rushing six at once.

5. Full test suite run after every change; 663 passed, 1 pre-existing
   skip, 0 failed, at the end of the session.

Not fixed / not attempted this session, and why: everything in §2's
NOT IMPLEMENTED rows. Each is either (a) a substantial subsystem this
repo never had (vector DB, scope classifier, adjacent-knowledge corpus,
image-aware retrieval, load-test execution, an LLM-eval harness costing
real API calls) that cannot be built and *validated* honestly inside one
session without producing exactly the fabricated-evidence problem this
audit exists to prevent, or (b) six more Tier 1 experiments that each
deserve the same individual, unhurried treatment Experiment 1 got rather
than a batch of six rushed tolerance guesses.

## 4. Per-experiment status (the table the request's §29 asks for)

Updated 2026-09-14 (see §7): retrieval now works, so the "Retrieval"
column below is no longer blanket N/A. Routing/scope classification and
citation *validation* still don't exist as subsystems (see §2 row 2).
Session-start (`POST /api/socratic/session`) works only for experiments
with a Tier 1 checker below (steps configured); the rest still 503.

| # | Title | Tier 1 checker | Session-start | Worked example | Golden cases | Retrieval |
|---|---|---|---|---|---|---|
| 1 | Zn-Cu EMF thermodynamics | **Implemented** (Ecell + ΔG; final-step checker bug found+fixed this session) | Works | Yes, p.13, verified | 1 (Category 1) | Real (19-passage index) |
| 2 | Ester hydrolysis kinetics | **Implemented** (regression_slope; tolerance/fit DEFAULTS, not manual-stated) | Works | No | 0 | Real |
| 3 | Ni2+ colorimetry (conventional only) | **Implemented** (calibration_curve; tolerance/fit DEFAULTS, not manual-stated) | Works | No | 0 | Real |
| 4 | Fe potentiometry | Pending (endpoint_detection shape known) | 503 | No | 0 | Real (index has content; nothing calls it) |
| 5 | ZnO prep/characterization | Pending (Scherrer eq. known, no sample data) | 503 | No | 0 | Real |
| 6 | Sulfate conductometry | Pending (endpoint_detection shape known) | 503 | No | 0 | Real |
| 7 | Orbital contributions (Gabedit/ORCA/Avogadro) | **Implemented** (new `ComputationSanityPlugin`) | Works (chat/diagnostic; `/attempt` step-advance doesn't — see ARCHITECTURE.md §2.1.1) | No | 0 | Real |
| 8 | Ethane + cyclohexane conformers | **Implemented** (`QualitativeOrderingPlugin`, corrected 2026-09-12) | Works (same `/attempt` limitation as Exp 7) | N/A (ordering-only check by design) | pre-existing category 2/5 cases (generic, not manual-numeric) | Real |
| 9 | Fe2+ colorimetry | Pending (calibration_curve shape known) | 503 | No | 0 | Real |
| 10 | Cu2O nanoparticle colour | Pending (calibration_curve shape known) | 503 | No | 0 | Real |

## 5. Final acceptance gate (request §33, honestly filled in)

Nearly everything in the request's checklist is unchecked, and it should
read that way rather than be marked done on the strength of adjacent
work. The items this session can actually check:

- [x] Tier 1 math never delegated to an LLM (structural, re-verified)
- [x] Server-side authz / data isolation (re-verified, tests pass)
- [x] Answer gate covers both modes (re-verified, tests pass)
- [x] Experiment 1 implemented, routable-in-the-sense-this-codebase-has
      (registered, used by the pipeline), source-grounded (manual page
      cited in `manual_reference`), baseline-tested (golden + unit)
- [x] Experiment 8 identity corrected and both conformer pairs covered
- [ ] Everything else in the request's §33 checklist — **unchecked**,
      because the underlying subsystem (RAG/scope/adjacent-knowledge/
      image retrieval/load test/evaluator) does not exist yet, not
      because it exists and scored poorly.

**The honest one-line summary:** this repository is a working,
well-tested, ~10%-of-the-way point toward the product the Phase 2
request describes, on a course whose manual only just arrived — one
experiment now has a real, manual-verified deterministic checker, the
biggest latent correctness bug (Experiment 7/8 identity) is fixed, and
every other gap is named specifically enough that the next session can
pick any one item in §2 and build it for real, rather than being told
"mostly done" and discovering otherwise later.

## 7. Session 2 (2026-09-14): fixing the two blockers found while
scoping the Qwen+RAGAS evaluation pipeline

A separate request asked for a Qwen3:8B (Ollama) + RAGAS evaluation
pipeline against Experiments 2, 3, 7, 8 (priority) and the rest. Before
building it, tracing an actual question ("exp7 me orca wala kaise
krna") through the real code (not simulated) surfaced two blockers, and
the user chose to fix both before any evaluation work:

**Blocker 1 — retrieval returned zero passages under every reachable
config.** `manual_pdf` defaulted to `manual/BACHY105.pdf` (doesn't
exist); pointing it at `manual/IACHY102_manual.md` instead failed too,
since `pypdf` can't parse markdown. Verified live both ways before
touching anything. Fixed: `backend/rag/retrieval.py::build_index` now
dispatches on file extension; a new `_chunk_markdown` splits the
transcription on its `## Experiment N ... (p.X-Y)` headings and tags
each chunk with the parsed page/page-range. `Passage.citation()` updated
to say "IACHY102 manual" instead of the old "BACHY105 manual" string.
Config default and `.env.example` updated. Re-verified live: 19 passages
indexed; an Exp7-flavoured Hinglish query ("orca run krdia ab avogadro
homo lumo") correctly top-ranks the Experiment 7 section; an ester-
hydrolysis query correctly top-ranks Experiment 2. New test file:
`backend/tests/test_retrieval.py` (none existed before — this subsystem
had zero test coverage until now).

**Blocker 2 — 8 of 10 experiments 503'd at Socratic session-start**,
before reaching any retrieval, LLM, or Q&A code, because
`POST /api/socratic/session` calls `steps_for(plugin)` immediately and
every non-implemented experiment is a `PendingManualPlugin` that raises.
The user asked specifically to unblock Experiments 7, 2 and 3 (the three
priority experiments that were still pending; Exp 8 already worked).
Fixed, all three, all manual-grounded, all with the full test suite
green after each:

- **Experiment 2** (ester hydrolysis rate constant): `RegressionSlopeChecker`,
  transcribed formula `k1' = slope * 2.303` from a plot of
  `log10(V_inf - Vt)` vs `t` (p.18). Required a real enhancement to the
  shared checker — `y_reference_key`/`reference_transform`, since the
  per-point transform needs the student's own `V_inf` reading, not a
  manual constant — added to `regression_slope.py` generically, not
  special-cased. **Tolerance (`rel_tol=0.05`) and fit floor
  (`min_r_squared=0.98`) are deliberate engineering defaults, not
  manual-derived** — the manual states no experiment-specific band for
  this experiment (see `manual/IACHY102_manual.md`'s summary table) and
  the module docstring says so explicitly, same for the sign convention
  applied to the slope (the manual's printed formula has no minus sign;
  standard kinetics convention does).
- **Experiment 3** (Ni2+ colorimetry, conventional method only):
  `CalibrationCurveChecker` against the manual's 2/4/6/8 ppm standards at
  440 nm (p.22). Same caveat: tolerance and fit floor are defaults, not
  manual-stated. The smartphone/RGB-ratio variant is explicitly **not**
  implemented (different, still-undecided input shape — which RGB ratio
  is "the" calibration axis varies per run).
- **Experiment 7** (orbital contributions): needed the "fifth checker
  type" flagged as missing in the first audit session. Built
  `registry.ComputationSanityPlugin` — checks two facts that hold for
  any molecule/method/basis set (energy must not rise after
  optimisation; LUMO must exceed HOMO), never returns PASS (method
  choice still needs a human, same rationale as Exp 8's ordering check).

**Bugs found and fixed along the way, not part of the original ask:**

- **Experiment 1's final Socratic step had no checker at all** —
  `step_checkers={0: ECELL_CHECKER}` was missing an entry for step 1
  (the final ΔG step). Since `handle_attempt` calls `check_step` for
  whichever step is current, including the final one, a student could
  open an Exp 1 session and get through step 0, but attempting the
  final step would raise `ManualNotTranscribedError` → HTTP 503. Fixed:
  `step_checkers={0: ECELL_CHECKER, 1: DELTA_G_CHECKER}`.
- **Experiments 7 and 8 cannot be "completed" via `/attempt` at all**,
  discovered while building Exp 7's checker and confirmed to also be
  true of the pre-existing Exp 8: because neither plugin's `check_step`
  can honestly return PASS (that's the entire point of a method-choice
  check), and `handle_attempt` only advances the step index on PASS, a
  session opens and the chat/diagnostic paths work, but step-by-step
  numeric advancement through `/attempt` never completes for either
  experiment. This is a real, structural gap in
  `QualitativeOrderingPlugin`/`ComputationSanityPlugin`'s design (the
  Socratic step machine has no outcome between "advance" and "hint
  forever"), not something patched around here with a fake PASS. Left
  open, documented in `docs/ARCHITECTURE.md` §2.1.1 and in code
  comments, flagged as future work.
- **`test_answer_never_enters_the_prompt` in `test_socratic_refusal.py`
  started failing** the moment real retrieval went live, because its
  synthetic `reference_plugin`'s step prompt happened to lexically match
  a real Experiment 10 manual passage containing the digit "4", which
  collided with one of the test's own unrelated fixture constants. Not a
  gate bug — the manual excerpt is *supposed* to be able to contain
  numbers; the test's assertion was written when retrieval was
  guaranteed empty and became too strong once it wasn't. Fixed by
  monkeypatching retrieval out for that module specifically (it tests
  the answer-gate's structural guarantee against a synthetic plugin, not
  real manual grounding — `test_retrieval.py` now covers the latter).

**Verification, not claims:** full backend test suite run after every
change in this section; **674 passed, 1 pre-existing skip, 0 failed** at
the end. Session-start (`steps_for`/`present_step`) re-checked live for
all 10 experiments after the fixes: exp01/02/03/07/08 succeed,
exp04/05/06/09/10 still correctly 503 (untouched, out of scope for this
pass). Retrieval re-checked live against the real index, not asserted.

**Still not done, and why:** Experiments 4, 5, 6, 9, 10 remain
`PendingManualPlugin` — untouched in this pass, the user's request was
scoped to 7/2/3 specifically. The Qwen3:8B + RAGAS evaluation pipeline
itself has not been built or run yet as of this update; that is the
next piece of work, now on top of a real (if partial) retrieval and
Tier 1 surface instead of one that would have produced only empty
citations and 503s for most of the priority experiments.

## 8. Session 3 (2026-09-14, later): a live 16-case evaluation run, and
what it found

The evaluation harness described as "not yet built" in §7 above was
built (`evaluation/run_evaluation.py`, `evaluation/build_reports.py`)
and actually run: 16 real cases across Exp1/2/3/7/8, through the real
`chat.tutor_reply` code, local `qwen3:8b` (Ollama) as both generator and
judge (flagged non-independent throughout every report). 16/16 executed,
0 failed. RAGAS was attempted (two versions) and is genuinely blocked by
an upstream `ragas`/`langchain_community` packaging incompatibility
(`langchain_community.chat_models.vertexai` no longer exists in the
installed version) — documented with the real traceback in
`reports/ragas_results.json` rather than faked. One fix attempt
(downgrading `langchain-community`) briefly broke numpy/langgraph
version constraints for other tools in this shared Python environment;
caught immediately and reverted (`pip install -U` back to the working
set), repo tests re-confirmed green before continuing.

**Two real, measured issues the run surfaced, both since fixed:**

1. **Retrieval Recall@1 was 0.0 for Exp2 and Exp3** (1.0 for Exp1/7/8).
   Root cause: a short front-matter table listing all 10 experiment
   titles in one compact chunk out-ranked each experiment's own real
   section on BM25's length normalisation (shorter documents score
   higher for the same term overlap). Recall@3 was 1.0 -- the real
   section was always second -- so generated content was usually still
   relevant, but the *cited* page was wrong 100% of the time for these
   two experiments. **Fixed**: `backend/rag/retrieval.py`'s
   `_chunk_markdown` now only indexes sections headed "Experiment N ..."
   (`_EXPERIMENT_HEADING_RE`); front-matter/summary tables are excluded
   from retrieval entirely. Re-verified live: Exp2/Exp3 queries now
   correctly top-rank their own section.
2. **12 of 16 replies silently fell back to the fixed hint template**
   instead of a real LLM reply, because `qwen3:8b`'s default "thinking"
   mode spent the whole `num_predict` budget on internal reasoning
   before any visible content, and `chat.py` already treats empty LLM
   output as unavailable (falls back to template) -- a safe degradation,
   but it meant most of the run measured template text, not generated
   prose. **Fixed**: added a `think` toggle to `OllamaBackend`
   (`LABTUTOR_OLLAMA_THINK`, default `false`) --
   `backend/llm/client.py` + `backend/config.py`, with
   `backend/tests/test_llm_ollama_backend.py` pinning both the default
   and the opt-in. Verified live via direct Ollama call: `think: false`
   dropped a trivial-prompt round trip from ~22s to ~5s.

Both fixes verified against the full test suite (green after each) and
against a live retrieval/API call, not just unit-tested in isolation.

## 9. Session 3 continued: Experiment-7-focused deep dataset, per
`/goal` (2026-09-14)

A `/goal` set a session-scoped directive: test Experiment 7 specifically,
improve the pipeline toward "excellent, prod level," check whether
manual images were handled, and flag any other robustness gaps.

- **Images: not handled, and cannot be from what exists in this repo.**
  See `docs/exp07.md` for the full account. Short version: the
  manual reached this repo as chat-rendered pages, transcribed to text
  only; the image bytes were never saved anywhere (verified: no image
  file exists in the repo or session scratch directories for this
  document), and there is no mechanism available to retroactively
  extract them from a past chat turn. Fixing this needs either the real
  PDF (enabling a new page-image extraction path alongside the existing
  text one) or manually captured screenshots -- both are new inputs from
  outside this session, not a pipeline bug to engineer around.
- **Expanded Exp7 golden dataset**: `evaluation/exp07_dataset.json`, 34
  cases (30 executed, 4 explicitly marked `blocked_no_image_asset` and
  skipped rather than faked) covering procedure, molecule-build
  (CH4/O2), workflow transitions, concepts (HOMO/LUMO, basis sets),
  troubleshooting, Hinglish/typos, a stateless-chat "false memory" probe
  (see below), cross-experiment confusion, prompt injection, answer
  fishing, off-scope and safety. Still far short of the original
  150-200 target, but a real, deliberate expansion of the 4-case Exp7
  slice from the first run.
- **Real architecture finding: Socratic chat has no conversation memory
  at all.** `chat._build_user_prompt` sends only the current message,
  the step prompt, the current hint, and a manual excerpt -- no prior
  turns. A "multi-turn" test in the sense of context-aware follow-ups is
  therefore not meaningfully different from a single-turn one in this
  system; what *is* meaningfully testable is whether a message that
  presupposes false prior context ("what did you say earlier about...")
  gets a sensible reply without the model inventing a fake memory --
  that is what the `false_memory_probe` cases test.
- **Robustness sweep** (Explore agent, read-only, targeted at the two
  bug families already found plus concurrency/idempotency/config-cache
  risk): found 4 more real, code-verified issues, all fixed this
  session --
  1. `_chunk_markdown` splitting a long section dropped the experiment
     heading from every chunk after the first, so a mid-section chunk
     (e.g. Exp1's worked example) competed at retrieval with no
     identifying terms of its own. **Fixed**: `_chunk_page` gained a
     `prefix` param, applied to every chunk. Verified live: the agent's
     own repro query ("Experiment 1 Nernst equation worked example")
     now top-ranks Exp1's own chunk (score 4.27) instead of Exp5's
     (was beating or nearly tying it before).
  2. `idempotency.claim()` had no expiry on `in_flight` records and
     `release()` is only called from a few routes' explicit error
     branches (`grep -rn "finally" backend/api` — zero hits repo-wide),
     so a mid-request crash wedged that exact `(user, scope, key)`
     forever. **Fixed**: `STALE_IN_FLIGHT_SECONDS` (300s) — a claim
     older than that is reclaimed rather than refused indefinitely;
     tests added, including a regression test for the crash scenario.
  3. `reload_settings()` only cleared the settings cache itself, not
     `rag.retrieval`'s index cache or `llm.client`'s backend cache —
     each needed its own separately-named reset call, a real footgun
     for exactly the kind of env-var-mutating script this session
     wrote. **Fixed**: `reload_settings()` now cascades to both (the DB
     engine's cache is deliberately left alone — disposing it is async
     and cannot run from this sync function).
  4. No bounded concurrency anywhere on the interactive LLM call path
     (chat, phrasing, the Exp8 note) — unlike `summaries/jobs.py`'s
     batch fan-out, which already has a semaphore for the same reason.
     At ~70 concurrent students against a slow/degrading provider,
     up to ~70 simultaneous requests could be in flight at once.
     **Fixed**: `LABTUTOR_LLM_MAX_CONCURRENCY` (default 20), enforced
     via a lazily-built `asyncio.Semaphore` around the actual HTTP call
     in both `HostedBackend` and `OllamaBackend`. Test proves the cap
     holds under real concurrent load (10 calls, cap 3, measured peak
     concurrency = 3).
  Checked and found fine: `socratic_engine/chat.py`/`engine.py` (no
  cross-session mutable state), `ratelimit.py` (correctly locked,
  reasonable limits for 70 users; only a trivial unbounded-dict nitpick,
  not fixed).
- **Prompt-quality finding from the first full Exp7 run (30 cases, real
  LLM replies)**: 28/30 were relevant/grounded; the 2 misses
  (`e07-14` "what's the actual difference between HOMO and LUMO
  conceptually", `e07-15` "whats the diff between B3LYP and B3P
  basically") both got the generic hint-refusal placeholder instead of
  an actual explanation, even though retrieval had correctly found the
  right manual section (recall@1 was 1.0 throughout). Root cause: the
  Socratic chat `SYSTEM_PROMPT` only knew one mode -- "re-word the
  supplied hint" -- so a genuine conceptual question got squeezed into
  that frame and answered with whatever placeholder hint text existed
  (`templates.refusal_text()` on a first message, since no real hint
  has been computed yet). **Fixed**: `SYSTEM_PROMPT` now names two
  message kinds -- hint requests (unchanged behaviour) and genuine
  procedure/concept questions (now answered directly from the MANUAL
  EXTRACT, up to 3 sentences) -- with the same numeric-safety rules
  applying to both. The "never reveal the final computed answer" and
  "never introduce a number not already in hint/step/manual/student
  text" constraints are unchanged and are enforced structurally either
  way (`answer_gate.scrub_outbound`), so this loosens what the model is
  *allowed to try to say*, not what it's allowed to leak.

**Final measured results, Exp7, 30/30 executed (4 correctly blocked, 0
failed) — after both fixes above:**

| Metric | Before (first run) | After |
|---|---|---|
| Retrieval Recall@1 | 1.0 | 1.0 |
| Retrieval Recall@3 | 1.0 | 1.0 |
| Citation correctness | 1.0 | 1.0 |
| Intent classification accuracy | 1.0 | 1.0 |
| Qwen-judged relevance | 0.933 (28/30) | **1.0 (30/30)** |
| Qwen-judged grounded-in-context | 0.933 | **1.0** |
| Qwen-judged scope-handling-correct | 0.933 | **1.0** |
| Hallucination rate | 0.0 | 0.0 |
| Final-answer-leak rate | 0.0 | 0.0 |
| Answer-gate redactions | 0 | 1 (see below) |
| Reply source | 27/30 real LLM, 3/30 triage short-circuit | same |
| Avg generation latency | 4.67s | 8.25s (longer, more substantive replies) |

The one redaction in the "after" run is the gate working as designed,
not a defect: asked how to build methane, the model volunteered the
tetrahedral bond angle ("close to 109.5 degrees") — a real, harmless
fact, but not a number present in the hint/step/manual excerpt/student
message, so `scrub_outbound` withheld it. Conservative, and consistent
with this system's documented safety-first design.

Judge independence caveat applies throughout (same `qwen3:8b` model
generates and judges) — see `reports/exp07_evaluation_report.md`.
Still not attempted: the 150-200-case target volume, and anything
requiring the manual's images (`docs/exp07.md`).
