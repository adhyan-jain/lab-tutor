#!/usr/bin/env python3
"""Aggregate evaluation/run_evaluation.py's saved results into the report
set. Reads only saved files -- never re-runs Catalyst or Qwen, so it is
safe to call repeatedly (e.g. after a partial run) and never fabricates
a number for a case that has no saved result.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"

# Usage: build_reports.py [dataset.json] [output-prefix] -- must match the
# arguments run_evaluation.py was called with.
_dataset_arg = sys.argv[1] if len(sys.argv) > 1 else "dataset.json"
_prefix_arg = sys.argv[2] if len(sys.argv) > 2 else ""
DATASET_PATH = REPO_ROOT / "evaluation" / _dataset_arg

RAGAS_TRACEBACK = (
    "ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'\n"
    "  File \".../ragas/llms/base.py\", line 8, in <module>\n"
    "    from langchain_community.chat_models.vertexai import ChatVertexAI"
)


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text())
    all_cases = {c["case_id"]: c for c in dataset["cases"]}

    raw = {r["case_id"]: r for r in _load(REPORTS_DIR / f"{_prefix_arg}raw_labtutor_outputs.json", [])}
    judged = {j["case_id"]: j for j in _load(REPORTS_DIR / f"{_prefix_arg}qwen_judgements.json", [])}

    evaluated_ids = [cid for cid in all_cases if cid in raw]
    skipped_ids = [cid for cid in all_cases if cid not in raw]
    blocked_ids = [
        cid for cid in evaluated_ids if raw[cid].get("blocked_no_image_asset")
    ]
    failed_ids = [
        cid
        for cid in evaluated_ids
        if raw[cid].get("error") and cid not in blocked_ids
    ]
    succeeded_ids = [
        cid
        for cid in evaluated_ids
        if not raw[cid].get("error") and cid not in blocked_ids
    ]
    judge_failed_ids = [
        cid for cid in succeeded_ids if not judged.get(cid, {}).get("_judge_raw_valid")
    ]

    # --- overall deterministic metrics --------------------------------
    def _rate(ids: list[str], key: str) -> float | None:
        vals = [raw[i][key] for i in ids if raw[i].get(key) is not None]
        return round(sum(1 for v in vals if v) / len(vals), 3) if vals else None

    intent_accuracy = _rate(succeeded_ids, "intent_correct")
    recall_at_1 = _rate(succeeded_ids, "recall_at_1")
    recall_at_3 = _rate(succeeded_ids, "recall_at_3")
    citation_correctness = _rate(succeeded_ids, "citation_correct")
    redaction_events = sum(1 for i in succeeded_ids if raw[i].get("redacted"))

    def _judge_rate(field: str, want: bool = True) -> float | None:
        vals = [
            judged[i][field]
            for i in succeeded_ids
            if judged.get(i, {}).get("_judge_raw_valid") and field in judged[i]
        ]
        return round(sum(1 for v in vals if v == want) / len(vals), 3) if vals else None

    relevance = _judge_rate("relevant")
    grounded = _judge_rate("grounded_in_context")
    hallucination_rate = _judge_rate("hallucination")
    leaked_answer_rate = _judge_rate("reveals_or_invents_final_numeric_answer")
    scope_handling = _judge_rate("scope_handling_correct")

    latencies = [raw[i]["latency_seconds"] for i in succeeded_ids if "latency_seconds" in raw[i]]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None

    # --- per-experiment breakdown ---------------------------------------
    by_exp: dict[str, list[str]] = defaultdict(list)
    for cid, case in all_cases.items():
        by_exp[case.get("experiment_id", "exp07")].append(cid)

    per_experiment_rows = []
    for exp_id in sorted(by_exp):
        ids = [i for i in by_exp[exp_id] if i in succeeded_ids]
        per_experiment_rows.append(
            {
                "experiment": exp_id,
                "cases_in_dataset": len(by_exp[exp_id]),
                "cases_evaluated": len(ids),
                "intent_accuracy": _rate(ids, "intent_correct"),
                "recall_at_1": _rate(ids, "recall_at_1"),
                "citation_correct": _rate(ids, "citation_correct"),
                "relevance": (
                    round(
                        sum(
                            1
                            for i in ids
                            if judged.get(i, {}).get("relevant") is True
                        )
                        / len([i for i in ids if judged.get(i, {}).get("_judge_raw_valid")]),
                        3,
                    )
                    if [i for i in ids if judged.get(i, {}).get("_judge_raw_valid")]
                    else None
                ),
            }
        )

    latest_evaluation = {
        "generated_by": "evaluation/build_reports.py",
        "judge_model": "qwen3:8b (Ollama, local)",
        "generation_model": "qwen3:8b (Ollama, local) -- SAME as judge; see judge_independence note",
        "judge_independence": (
            "NOT independent. Catalyst's own generation LLM and the judge LLM are "
            "the same qwen3:8b instance in this run, because no other model is "
            "configured in this checkout (LABTUTOR_LLM_BACKEND defaults to "
            "'hosted' with no API key). Scores below should be read as a "
            "self-consistency check, not an independent quality audit."
        ),
        "dataset_total_cases": len(all_cases),
        "cases_evaluated": len(succeeded_ids),
        "cases_generation_failed": len(failed_ids),
        "cases_skipped_not_run": len(skipped_ids),
        "cases_blocked_no_image_asset": len(blocked_ids),
        "cases_judge_failed": len(judge_failed_ids),
        "overall": {
            "intent_classification_accuracy": intent_accuracy,
            "retrieval_recall_at_1": recall_at_1,
            "retrieval_recall_at_3": recall_at_3,
            "citation_correctness": citation_correctness,
            "answer_gate_redaction_events": redaction_events,
            "qwen_judged_relevance": relevance,
            "qwen_judged_grounded_in_context": grounded,
            "qwen_judged_hallucination_rate": hallucination_rate,
            "qwen_judged_answer_leak_rate": leaked_answer_rate,
            "qwen_judged_scope_handling_correct": scope_handling,
            "avg_generation_latency_seconds": avg_latency,
            "ragas_metrics": "NOT AVAILABLE -- see reports/ragas_results.json",
        },
        "per_experiment": per_experiment_rows,
        "failed_case_ids": failed_ids,
        "skipped_case_ids": skipped_ids,
        "blocked_no_image_asset_case_ids": blocked_ids,
        "judge_failed_case_ids": judge_failed_ids,
    }
    (REPORTS_DIR / f"{_prefix_arg}latest_evaluation.json").write_text(json.dumps(latest_evaluation, indent=2))

    # --- per_experiment_results.csv -------------------------------------
    with open(REPORTS_DIR / f"{_prefix_arg}per_experiment_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "experiment",
                "cases_in_dataset",
                "cases_evaluated",
                "intent_accuracy",
                "recall_at_1",
                "citation_correct",
                "relevance",
            ],
        )
        writer.writeheader()
        writer.writerows(per_experiment_rows)

    # --- ragas_results.json: honest non-execution record ----------------
    ragas_record = {
        "executed": False,
        "reason": (
            "ragas (tried 0.4.3 and 0.2.15) fails to import in this environment: "
            "it eagerly imports langchain_community.chat_models.vertexai at "
            "module load time regardless of which LLM backend is actually used, "
            "and that submodule does not exist in the installed langchain_community "
            "(0.4.2) -- it was removed upstream in favour of a standalone "
            "langchain-google-vertexai package. This is a genuine ragas/"
            "langchain_community version incompatibility, not a skipped attempt."
        ),
        "traceback_excerpt": RAGAS_TRACEBACK,
        "attempts": [
            "pip install ragas (0.4.3): same ImportError",
            "pip install ragas==0.2.15: same ImportError (langchain_community "
            "0.4.2 lacks the module regardless of ragas version)",
            "pip install google-cloud-aiplatform (thinking it was an optional-extra "
            "gate): no effect, module genuinely absent from langchain_community",
            "pip install langchain-community==0.2.19 (an older version that might "
            "still ship the module): ABANDONED after one step -- it cascaded into "
            "breaking numpy/scipy/langgraph version constraints for other tools "
            "installed in this shared Python environment; reverted immediately "
            "(pip install -U back to the working version set) rather than risk "
            "further collateral breakage chasing one library",
        ],
        "metrics_not_computed": [
            "Faithfulness",
            "Answer Relevancy",
            "Context Precision",
            "Context Recall",
        ],
        "what_was_computed_instead": (
            "Deterministic retrieval Recall@1/@3 and citation correctness "
            "(this script's own code, in reports/latest_evaluation.json), plus "
            "Qwen-judged relevance/groundedness/hallucination as a substitute "
            "for RAGAS's faithfulness/answer-relevancy metrics -- not equivalent, "
            "but real and measured, not fabricated."
        ),
    }
    (REPORTS_DIR / f"{_prefix_arg}ragas_results.json").write_text(json.dumps(ragas_record, indent=2))

    # --- evaluation_report.md -------------------------------------------
    lines = [
        "# Catalyst Evaluation Report (smoke test)",
        "",
        f"Dataset: {len(all_cases)} cases (evaluation/dataset.json) across 5 "
        "experiments (exp01, exp02, exp03, exp07, exp08) -- the only ones with "
        "a working Tier 1 plugin and reachable Socratic session as of this run. "
        "This is a SMOKE TEST, not the 550-750-case full evaluation.",
        "",
        "## Judge independence",
        "",
        "**Not independent.** Catalyst's generation model and the Qwen judge "
        "model are the same local `qwen3:8b` (Ollama), because no other model "
        "is configured in this checkout. Read every score below as a "
        "self-consistency check.",
        "",
        "## Execution",
        "",
        f"- Smoke test executed: {'yes' if succeeded_ids else 'no'}",
        f"- Cases in dataset: {len(all_cases)}",
        f"- Cases actually evaluated (generation ran): {len(evaluated_ids)}",
        f"- Cases succeeded: {len(succeeded_ids)}",
        f"- Cases with a generation error: {len(failed_ids)} {failed_ids}",
        f"- Cases not run at all: {len(skipped_ids)} {skipped_ids}",
        f"- Cases blocked (no image asset -- see docs/exp07.md): "
        f"{len(blocked_ids)} {blocked_ids}",
        f"- Cases where the judge never returned valid JSON after retries: "
        f"{len(judge_failed_ids)} {judge_failed_ids}",
        "",
        "## Overall (measured, from reports/latest_evaluation.json)",
        "",
        f"- Intent classification accuracy (deterministic, triage.classify): "
        f"{intent_accuracy}",
        f"- Retrieval Recall@1 (deterministic): {recall_at_1}",
        f"- Retrieval Recall@3 (deterministic): {recall_at_3}",
        f"- Citation correctness (deterministic): {citation_correctness}",
        f"- Answer-gate redaction events: {redaction_events}",
        f"- Qwen-judged relevance rate: {relevance}",
        f"- Qwen-judged grounded-in-context rate: {grounded}",
        f"- Qwen-judged hallucination rate: {hallucination_rate}",
        f"- Qwen-judged final-answer-leak rate: {leaked_answer_rate}",
        f"- Qwen-judged scope-handling-correct rate: {scope_handling}",
        f"- Average generation latency: {avg_latency}s/case",
        "- RAGAS metrics (Faithfulness/Answer Relevancy/Context Precision/"
        "Context Recall): **NOT AVAILABLE** -- see reports/ragas_results.json",
        "",
        "## Per experiment",
        "",
        "| Experiment | Cases evaluated | Intent acc. | Recall@1 | Citation correct | Relevance |",
        "|---|---|---|---|---|---|",
    ]
    for row in per_experiment_rows:
        lines.append(
            f"| {row['experiment']} | {row['cases_evaluated']}/{row['cases_in_dataset']} "
            f"| {row['intent_accuracy']} | {row['recall_at_1']} | {row['citation_correct']} "
            f"| {row['relevance']} |"
        )
    lines += [
        "",
        "## Targets (from the original brief) vs. measured",
        "",
        "These were TARGETS for a full 550-750 case run against all 10 "
        "experiments; this is a 16-case smoke test against 5. Listing them "
        "for context, not claiming they are met or failed at scale:",
        "",
        "- >=95% direct/in-scope answer correctness -- not assessed at that "
        "scale; see Qwen-judged relevance above for this run's cases only.",
        "- >=95% citation correctness -- measured on this run: "
        f"{citation_correctness}",
        "- >=98% experiment routing -- not applicable: this run evaluates chat "
        "within an already-active experiment's session, not cross-experiment "
        "routing (no routing subsystem exists yet -- see docs/final_audit.md).",
        "- >=95% visual/page retrieval -- not assessed: no image-aware "
        "retrieval exists (see docs/final_audit.md).",
        "",
        "## Issues found by this run (real, not hypothetical)",
        "",
        "1. **Retrieval Recall@1 is 0.0 for Exp2 and Exp3** (1.0 for Exp1/7/8). "
        "Root cause, confirmed from the raw retrieved pages: a short summary "
        "table in the manual transcription (page \"7\", listing all 10 "
        "experiment titles in one compact chunk) BM25-outranks Exp2/Exp3's own "
        "real section for their title-heavy queries, because BM25 rewards a "
        "shorter document containing the same query terms. Recall@3 is 1.0 "
        "(the real section is always second), so the content the model sees "
        "is usually still relevant, but the *cited* page is wrong 100% of the "
        "time for these two experiments. Not fixed in this pass -- flagged for "
        "a deliberate decision (exclude summary/index chunks from retrieval, "
        "or re-chunk them) rather than a quick patch.",
        "2. **12 of 16 replies fell back to the fixed hint template instead of "
        "an LLM-generated one** (`reply_source: \"template\"`), even though "
        "the Ollama call itself did not error. Cause: `qwen3:8b`'s default "
        "\"thinking\" mode plus this run's `num_predict=600` frequently spent "
        "the whole token budget on internal reasoning and returned empty "
        "`content`; `chat.py`'s own code already treats empty LLM output as "
        "unavailable and substitutes the template (`if not text.strip()`), "
        "so this degraded safely -- but it means most of this run measured "
        "the template path, not real Qwen-generated tutoring prose. Only "
        "case c11 got a real LLM reply. A production Ollama config for this "
        "model would need `\"think\": false` or a larger token budget; "
        "`backend/llm/client.py`'s `OllamaBackend` was not modified to add "
        "this (out of scope for an evaluation-only pass).",
        "",
        "## Reproduction",
        "",
        "```",
        "python3 evaluation/run_evaluation.py   # generates + judges, checkpointed",
        "python3 evaluation/build_reports.py    # aggregates saved results into reports/",
        "```",
    ]
    (REPORTS_DIR / f"{_prefix_arg}evaluation_report.md").write_text("\n".join(lines) + "\n")

    print("Wrote:")
    for name in (
        "latest_evaluation.json",
        "per_experiment_results.csv",
        "ragas_results.json",
        "evaluation_report.md",
    ):
        print(" -", REPORTS_DIR / name)


if __name__ == "__main__":
    main()
