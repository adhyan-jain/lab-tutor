# manual/

**Put the current manual PDF here, named `IACHY102.pdf`.**

The source filename supplied for this course is
`IACHY102-2026-27-manual_2_260830_133124.pdf`; either that name or
`IACHY102.pdf` is picked up, but keep the version encoded in the
filename if you have it — see `docs/source_manifest.json`, which pins
ingestion to a specific `version` string precisely so a manual revision
produces new chunk IDs instead of silently overwriting old ones.

This directory is mounted read-only into the backend container at
`/app/manual` (see `infra/docker-compose.yml`), and `LABTUTOR_MANUAL_PDF`
points at it.

## Text transcription

Its text is transcribed in `IACHY102_manual.md` in this directory —
pasted in-chat as document content during a Claude Code session, not
uploaded as a PDF file. **No PDF binary has been placed here.**

**Update (2026-09-14): retrieval is fixed.** `backend/rag/retrieval.py`
now dispatches on file extension — a `.md` path (this file) is chunked
by its `## Experiment N ... (p.X-Y)` headings via `_chunk_markdown`
rather than pushed through `pypdf`. `LABTUTOR_MANUAL_PDF` defaults here
already. If a real PDF ever becomes available, dropping it in as
`IACHY102.pdf` and repointing the setting still works too (the old PDF
path through `pypdf` is untouched) — it's no longer required, just an
option. See `docs/final_audit.md` §7 for what was verified live (19
passages indexed; correct top-ranked section for both an Exp7 Hinglish
query and an Exp2 kinetics query).

`IACHY102_manual.md` is the source of truth for every formula,
tolerance, experiment name and worked example a Tier 1 plugin should
use — see `docs/final_audit.md` §4 for which of the 10 assessed
experiments have real plugins so far (1, 2, 3, 7, 8) and which are still
`PendingManualPlugin` and why (4, 5, 6, 9, 10).

The manual is the source of truth for every formula, tolerance,
experiment name, numbering, screenshot and worked example in this
system — see `docs/final_audit.md` §0 and
`backend/sources/tiers.py` for the full source-hierarchy rule. Nothing
here was inferred, guessed, or filled in from a plausible textbook
value.

**A previous build session targeted a different, superseded course
manual (BACHY105).** That manual is declared in the source manifest as
`superseded_by: iachy102_manual_2026_27` specifically so a stray copy
left on a machine is recognised and refused rather than silently
ingested as current — do not drop a `BACHY105.pdf` here expecting it to
be used.

The PDF itself is deliberately not committed: it is course material, and
whether it may be redistributed is the department's call, not this
repository's. Add it locally and it will be picked up on the next
ingestion run — no code change is required.
