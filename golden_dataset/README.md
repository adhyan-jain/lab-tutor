# golden_dataset

Test data for Catalyst, in two families. The spec for both is
[docs/golden_dataset_plan.md](../docs/golden_dataset_plan.md).

## Diagnosis categories (`category1`-`category6`)

Test the diagnosis pipeline: Tier 1 recomputation, signature detection,
Socratic hint gating, edge inputs, prompt injection and student questions.
`category1_worked_examples/` holds only manual-sourced worked examples (see its
own README); `generate.py` builds the synthetic categories.

## Q&A scope-and-routing set (`qa/`)

The Q&A scope-and-routing golden dataset (Phase 1 brief, sections 8-10).

**This is a different thing from `category1-6/`.** Those test the
*diagnosis* pipeline (Tier 1 recomputation, signature detection,
Socratic hint gating). This directory tests the *Q&A/retrieval* product:
given a real-shaped student question, does the system classify its scope
correctly, route it to the right experiment, and respond with the right
`AnswerStatus`?

### How these cases were built, and why that matters

Every case's `expected_behavior`, `routed_experiment`, `scope_level`,
`normalized_intent` and `citation_expected` fields were **not authored
by hand** — they were computed by running the question through the live
`backend.retrieval.pipeline.answer_question()` at generation time
(`generate_qa.py`), and a case is only written if it resolves the way it
was built to test. A template meant to probe an out-of-scope refusal
that the classifier does not actually produce is rejected, not silently
included — the generator found and rejected two such templates on its
first run (`"software engineering interview"`, `"lab report"`), which is
what led to the precision fix in `backend/scope/ontology.py`'s
`_WEAK_GENERIC_DOMAIN_TERMS`.

`backend/tests/test_golden_qa_dataset.py` replays all 600+ cases against
the pipeline on every test run, so a later change that quietly breaks
one of these questions is caught immediately.

### What `expected_answer_facts: null` means

Every case's `expected_answer_facts` is `null`, with a `blocked_reason`
explaining why. This is not an oversight: the IACHY102 manual is not in
this repository (`docs/final_audit.md` §0), so there is no
factual content to verify an answer against yet. Filling this in with a
plausible-sounding fact would be exactly the fabrication CLAUDE.md and
the brief both forbid. Once the manual is ingested, re-running
`generate_qa.py` will show many `IN_SCOPE_RETRIEVAL_INSUFFICIENT` cases
flip to `IN_SCOPE_SUPPORTED` — that transition, per case, is the
coverage signal for Phase 2, and is a more honest metric than a
hand-written "pass rate" would be today.

### Distribution

| Experiment | Cases | Priority |
| --- | --- | --- |
| exp07 | 170 | P0+ |
| exp02, exp03, exp08 | 115 each | P0 |
| exp01, exp04, exp05, exp06, exp09, exp10 | 18 each | P1 |

**623 cases total.** Within each priority experiment's allocation, the
mix is roughly 35% clean direct questions, 35% messy (Hinglish/typo/
shorthand) direct questions, 15% adjacent, 10% out-of-scope, 5%
adversarial (prompt-injection / answer-fishing attempts), matching the
brief's target split. The six unrouted experiments get direct-number
("exp 5 ka procedure kya hai") and out-of-scope cases only — no
subject-matter vocabulary is invented for them, consistent with
`backend/scope/ontology.py`'s stance that their topics are genuinely
unknown pending the manual.

### Regenerating

```
python golden_dataset/qa/generate_qa.py
```

Deterministic given the same code (no LLM call, no randomness). Refuses
to write if any case's expected outcome no longer holds against the live
pipeline — read its stderr, don't force a write around it.

### Files

- `expNN.json` — one file per experiment, each case in `cases`.
- `summary.json` — case counts by experiment and the generator's targets.
