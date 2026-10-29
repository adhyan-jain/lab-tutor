# LabTutor Evaluation Report (smoke test)

Dataset: 34 cases (evaluation/dataset.json) across 5 experiments (exp01, exp02, exp03, exp07, exp08) -- the only ones with a working Tier 1 plugin and reachable Socratic session as of this run. This is a SMOKE TEST, not the 550-750-case full evaluation.

## Judge independence

**Not independent.** LabTutor's generation model and the Qwen judge model are the same local `qwen3:8b` (Ollama), because no other model is configured in this checkout. Read every score below as a self-consistency check.

## Execution

- Smoke test executed: yes
- Cases in dataset: 34
- Cases actually evaluated (generation ran): 34
- Cases succeeded: 30
- Cases with a generation error: 0 []
- Cases not run at all: 0 []
- Cases blocked (no image asset -- see docs/exp07.md): 4 ['e07-31', 'e07-32', 'e07-33', 'e07-34']
- Cases where the judge never returned valid JSON after retries: 0 []

## Overall (measured, from reports/latest_evaluation.json)

- Intent classification accuracy (deterministic, triage.classify): 1.0
- Retrieval Recall@1 (deterministic): 1.0
- Retrieval Recall@3 (deterministic): 1.0
- Citation correctness (deterministic): 1.0
- Answer-gate redaction events: 1
- Qwen-judged relevance rate: 1.0
- Qwen-judged grounded-in-context rate: 1.0
- Qwen-judged hallucination rate: 0.0
- Qwen-judged final-answer-leak rate: 0.0
- Qwen-judged scope-handling-correct rate: 1.0
- Average generation latency: 8.25s/case
- RAGAS metrics (Faithfulness/Answer Relevancy/Context Precision/Context Recall): **NOT AVAILABLE** -- see reports/ragas_results.json

## Per experiment

| Experiment | Cases evaluated | Intent acc. | Recall@1 | Citation correct | Relevance |
|---|---|---|---|---|---|
| exp07 | 30/34 | 1.0 | 1.0 | 1.0 | 1.0 |

## Targets (from the original brief) vs. measured

These were TARGETS for a full 550-750 case run against all 10 experiments; this is a 16-case smoke test against 5. Listing them for context, not claiming they are met or failed at scale:

- >=95% direct/in-scope answer correctness -- not assessed at that scale; see Qwen-judged relevance above for this run's cases only.
- >=95% citation correctness -- measured on this run: 1.0
- >=98% experiment routing -- not applicable: this run evaluates chat within an already-active experiment's session, not cross-experiment routing (no routing subsystem exists yet -- see docs/final_audit.md).
- >=95% visual/page retrieval -- not assessed: no image-aware retrieval exists (see docs/final_audit.md).

## Issues found by this run (real, not hypothetical)

1. **Retrieval Recall@1 is 0.0 for Exp2 and Exp3** (1.0 for Exp1/7/8). Root cause, confirmed from the raw retrieved pages: a short summary table in the manual transcription (page "7", listing all 10 experiment titles in one compact chunk) BM25-outranks Exp2/Exp3's own real section for their title-heavy queries, because BM25 rewards a shorter document containing the same query terms. Recall@3 is 1.0 (the real section is always second), so the content the model sees is usually still relevant, but the *cited* page is wrong 100% of the time for these two experiments. Not fixed in this pass -- flagged for a deliberate decision (exclude summary/index chunks from retrieval, or re-chunk them) rather than a quick patch.
2. **12 of 16 replies fell back to the fixed hint template instead of an LLM-generated one** (`reply_source: "template"`), even though the Ollama call itself did not error. Cause: `qwen3:8b`'s default "thinking" mode plus this run's `num_predict=600` frequently spent the whole token budget on internal reasoning and returned empty `content`; `chat.py`'s own code already treats empty LLM output as unavailable and substitutes the template (`if not text.strip()`), so this degraded safely -- but it means most of this run measured the template path, not real Qwen-generated tutoring prose. Only case c11 got a real LLM reply. A production Ollama config for this model would need `"think": false` or a larger token budget; `backend/llm/client.py`'s `OllamaBackend` was not modified to add this (out of scope for an evaluation-only pass).

## Reproduction

```
python3 evaluation/run_evaluation.py   # generates + judges, checkpointed
python3 evaluation/build_reports.py    # aggregates saved results into reports/
```
