# AGENTS.md — development-process roles for building LabTutor

This file defines roles for **Claude Code sessions doing development
work on this repo** — it has nothing to do with LabTutor's own runtime
behavior. LabTutor's product pipeline is deterministic, not agentic
(see the hard rule in [CLAUDE.md](CLAUDE.md)): these are ways of
dividing up *building* the system, not roles the shipped system plays.

A future session can adopt one of these roles by name to keep scope
tight and avoid one session's changes silently reaching into another
role's territory.

---

### `extraction-builder`

**Responsibility**: parsing student-submitted data (form fields,
uploaded readings, free-text entries) into structured, validated
fields that downstream tiers can consume.

**Must NOT**: make any correctness judgment about the extracted
values (that's Tier 1's job), or call an LLM to interpret ambiguous
input in a way that silently guesses at intent — malformed input
should be surfaced as a validation error, not resolved by inference.

**Owns**: `/backend/extraction`

---

### `tier1-compute-builder`

**Responsibility**: the deterministic math and signature-detection
modules — one plugin per experiment, built on the shared checker
types (`direct_formula`, `calibration_curve`, `endpoint_detection`,
`regression_slope`). Computes expected values from the manual's exact
formulas and detects known numeric failure signatures (e.g. sign
errors, non-monotonic data, poor R²).

**Must NOT**: touch LLM calls in any form, including for "borderline"
cases. If a case doesn't fit a deterministic rule, it should flow to
Tier 2/Tier 3, not get an LLM opinion. Must not implement real
diagnosis for Experiments 7/8 — those are stub plugins that always
escalate to Tier 3.

**Owns**: `/backend/tier1_compute` (including `/shared` and
`/experiments` subfolders)

---

### `rag-builder`

**Responsibility**: the retrieval layer over the manual PDF (chunking,
embedding, retrieval) and the LLM phrasing layer that turns an
already-computed diagnosis into natural language, citing the specific
manual passage that supports it.

**Must NOT**: make or influence a pass/fail or diagnosis determination.
The diagnosis this layer phrases must already be fully decided by
Tier 1/2/3 before this layer sees it; if a prompt template gives the
LLM room to change *what* is being said rather than just *how*, that's
a bug in this role's own territory to fix, not ship.

**Owns**: `/backend/rag`

---

### `auth-security-builder`

**Responsibility**: the Google OAuth flow, server-side role
determination by email domain (student vs. professor, both
domain-configurable via environment variables — never hardcoded),
session handling, and enforcing data isolation between students.

**Must NOT**: perform the domain check only at login and then trust a
session claim indefinitely without re-verification where it matters;
must not hardcode a specific faculty domain in code (it must come from
env var, confirmed with the team before deployment).

**Owns**: `/backend/auth`

---

### `test-builder`

**Responsibility**: the golden dataset and automated test suite —
known-correct worked examples from the manual, known-deviation cases
per Tier 1 signature, adversarial/edge inputs, and prompt-injection /
off-scope attempts against the LLM phrasing layer. See
[docs/golden_dataset_plan.md](docs/golden_dataset_plan.md) for the
spec this role builds against.

**Must NOT**: invent "known correct" values that aren't actually
verifiable against the manual — a fabricated ground truth is worse
than no test. Must not weaken a failing test by loosening its
assertion instead of fixing the underlying bug.

**Owns**: `/golden_dataset`, `/backend/tests`,
`docs/golden_dataset_plan.md`

---

### `deploy-builder`

**Responsibility**: Docker/deployment configuration, environment
separation (dev/staging/prod), health checks, and documenting the
Ollama-fallback vs. hosted-LLM-primary inference split (see
ARCHITECTURE.md).

**Must NOT**: bake real secrets into any committed config or image;
must not make local Ollama-on-lab-hardware the primary production
inference path (it's a documented fallback/dev-only option due to
concurrency limits).

**Owns**: `/infra`, root-level Docker/CI config

---

## General rules for every role

- Stay inside your owned files/folders. If a change requires touching
  another role's territory, say so explicitly rather than doing it
  silently.
- If a task looks like it's asking you to violate the hard rule in
  CLAUDE.md (LLM making a correctness determination), stop and flag it
  instead of implementing it.
- Follow the commit conventions in CLAUDE.md: small, single-purpose
  commits, no AI co-author attribution.
