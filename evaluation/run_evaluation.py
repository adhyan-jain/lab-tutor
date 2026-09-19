#!/usr/bin/env python3
"""LabTutor smoke-test evaluation: real product code + local Qwen3:8B judge.

Scope (see docs/final_audit.md and this file's own final report for the
full honesty accounting):

* Runs every case in evaluation/dataset.json through the REAL
  `backend.socratic_engine.chat.tutor_reply` (triage -> retrieval ->
  LLM -> answer gate), not a simulation of it.
* LabTutor's own generation LLM is pointed at the local Ollama qwen3:8b
  model for this run, because no other model is configured in this
  checkout (LABTUTOR_LLM_BACKEND defaults to "hosted" with no API key,
  which would make every case fall back to a fixed template and defeat
  the point of the exercise). The JUDGE below uses the SAME qwen3:8b
  model. This is NOT an independent judge -- see the "judge
  independence" note in the generated report. Flagged, not hidden.
* Deterministic metrics (intent classification, retrieval Recall@1/3,
  citation correctness) are computed by this script's own code, never
  by the judge -- per the evaluation brief's own instruction not to
  trust an LLM for something checkable deterministically.
* RAGAS was attempted and is NOT run -- see reports/ragas_results.json
  for the exact reason (a real upstream packaging incompatibility, not
  a skipped effort).
* Checkpointed: results are saved after every case to
  reports/qwen_judgements.json; re-running skips case_ids already
  present with a valid judgement.

Usage: python3 evaluation/run_evaluation.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# --- Point LabTutor's OWN generation backend at local Ollama qwen3:8b,  ---
# --- before backend.config is imported anywhere.                       ---
os.environ.setdefault("LABTUTOR_LLM_BACKEND", "ollama")
os.environ.setdefault("LABTUTOR_OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("LABTUTOR_OLLAMA_MODEL", "qwen3:8b")
os.environ.setdefault("LABTUTOR_LLM_TIMEOUT_SECONDS", "180")
os.environ.setdefault("LABTUTOR_LLM_MAX_TOKENS", "600")
os.environ.setdefault("LABTUTOR_MANUAL_PDF", str(REPO_ROOT / "manual" / "IACHY102_manual.md"))
os.environ.setdefault("LABTUTOR_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LABTUTOR_SESSION_SECRET", "evaluation-run-not-for-production")
os.environ.setdefault("LABTUTOR_ENV", "development")
os.environ.setdefault("LABTUTOR_STUDENT_DOMAINS", "vitstudent.ac.in")
os.environ.setdefault("LABTUTOR_FACULTY_DOMAINS", "vit.ac.in")

import asyncio  # noqa: E402

from backend.config import reload_settings  # noqa: E402

reload_settings()

from backend.rag import templates  # noqa: E402
from backend.rag.retrieval import reset_index_cache, retrieve  # noqa: E402
from backend.socratic_engine import chat, triage  # noqa: E402
from backend.tier1_compute.experiments import get_plugin  # noqa: E402

reset_index_cache()

REPORTS_DIR = REPO_ROOT / "reports"

# Usage: run_evaluation.py [dataset.json] [output-prefix]
# Defaults preserve the original 16-case, 5-experiment smoke test's paths.
_dataset_arg = sys.argv[1] if len(sys.argv) > 1 else "dataset.json"
_prefix_arg = sys.argv[2] if len(sys.argv) > 2 else ""
DATASET_PATH = REPO_ROOT / "evaluation" / _dataset_arg
RAW_OUTPUT_PATH = REPORTS_DIR / f"{_prefix_arg}raw_labtutor_outputs.json"
JUDGEMENTS_PATH = REPORTS_DIR / f"{_prefix_arg}qwen_judgements.json"

JUDGE_MODEL = "qwen3:8b"
JUDGE_URL = "http://localhost:11434/api/chat"
JUDGE_MAX_RETRIES = 2

JUDGE_SYSTEM_PROMPT = """You are grading one turn of a chemistry lab tutoring chatbot, NOT answering \
the student's question yourself. Judge only whether the GIVEN reply is relevant, grounded in the \
given context (if any), free of invented facts, and handled appropriately for its expected category. \
Return STRICT JSON matching this exact schema, no other text, no markdown fences:
{"relevant": true|false, "relevance_score": 0.0-1.0, "grounded_in_context": true|false, \
"hallucination": true|false, "reveals_or_invents_final_numeric_answer": true|false, \
"scope_handling_correct": true|false, "reason": "<one sentence>"}"""


def _judge_user_prompt(case: dict, reply_text: str, context_excerpt: str) -> str:
    return "\n".join(
        [
            f"Expected message category: {case['expected_intent']}",
            f"Student message: {case['student_message']}",
            "Manual context excerpt given to the tutor (may be empty):",
            "<<<CONTEXT",
            context_excerpt or "(none retrieved)",
            "CONTEXT>>>",
            "Tutor's reply being graded:",
            "<<<REPLY",
            reply_text,
            "REPLY>>>",
        ]
    )


def _call_judge(case: dict, reply_text: str, context_excerpt: str) -> dict:
    payload = {
        "model": JUDGE_MODEL,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0},
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _judge_user_prompt(case, reply_text, context_excerpt)},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    last_error = ""
    for attempt in range(1, JUDGE_MAX_RETRIES + 2):
        try:
            req = urllib.request.Request(
                JUDGE_URL, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            raw = (data.get("message") or {}).get("content", "").strip()
            parsed = json.loads(raw)
            required = {
                "relevant",
                "relevance_score",
                "grounded_in_context",
                "hallucination",
                "reveals_or_invents_final_numeric_answer",
                "scope_handling_correct",
                "reason",
            }
            if not required.issubset(parsed.keys()):
                raise ValueError(f"missing fields: {required - parsed.keys()}")
            parsed["_judge_attempts"] = attempt
            parsed["_judge_raw_valid"] = True
            return parsed
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
            KeyError,
        ) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
    return {
        "_judge_raw_valid": False,
        "_judge_attempts": JUDGE_MAX_RETRIES + 1,
        "_judge_error": last_error,
    }


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default
    return default


async def run_case(case: dict) -> dict:
    plugin = get_plugin(case.get("experiment_id", "exp07"))
    steps = plugin.steps()
    step = steps[case["step_index"]]
    retrieval_query = f"{plugin.title} {step.key}"

    # Same query tutor_reply uses internally (k=1); we ask for k=3
    # ourselves purely to measure Recall@3, without changing production
    # behaviour.
    retrieved = retrieve(retrieval_query, k=3)
    retrieved_pages = [p.page for p in retrieved]
    top_excerpt = retrieved[0].text[:800] if retrieved else ""

    detected_intent = triage.classify(case["student_message"]).value

    t0 = time.monotonic()
    error = None
    try:
        reply = await chat.tutor_reply(
            student_message=case["student_message"],
            step_prompt=step.prompt,
            step_index=case["step_index"],
            total_steps=len(steps),
            hint_text=step.hints[0] if step.hints else templates.refusal_text(),
            attempts_on_this_step=0,
            all_steps_complete=False,
            retrieval_query=retrieval_query,
            experiment_id=case.get("experiment_id", "exp07"),
        )

        reply_text, reply_source, reply_intent = reply.text, reply.source, reply.intent.value
        redacted = reply.redacted
    except Exception as exc:  # noqa: BLE001 - a failed case must not kill the run
        error = f"{type(exc).__name__}: {exc}"
        reply_text, reply_source, reply_intent, redacted = "", "error", "", False
    latency_s = time.monotonic() - t0

    # --- deterministic metrics (never judged by the LLM) ---
    intent_correct = detected_intent == case["expected_intent"]
    expected_page = case.get("expected_page")
    recall_at_1 = recall_at_3 = citation_correct = None
    if expected_page is not None:
        recall_at_1 = bool(retrieved_pages) and retrieved_pages[0] == expected_page
        recall_at_3 = expected_page in retrieved_pages
        citation_correct = recall_at_1  # the excerpt actually fed to the model is top-1

    return {
        "case_id": case["case_id"],
        "experiment_id": case.get("experiment_id", "exp07"),
        "student_message": case["student_message"],
        "language": case.get("language"),
        "expected_intent": case["expected_intent"],
        "detected_intent": detected_intent,
        "intent_correct": intent_correct,
        "expected_page": expected_page,
        "retrieved_pages": retrieved_pages,
        "recall_at_1": recall_at_1,
        "recall_at_3": recall_at_3,
        "citation_correct": citation_correct,
        "reply_text": reply_text,
        "reply_source": reply_source,  # "llm" | "template" | "triage"
        "redacted": redacted,
        "retrieved_context_used": top_excerpt,
        "latency_seconds": round(latency_s, 2),
        "error": error,
    }


async def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    dataset = json.loads(DATASET_PATH.read_text())
    cases = dataset["cases"]

    existing_raw = {r["case_id"]: r for r in _load_json(RAW_OUTPUT_PATH, [])}
    existing_judgements = {
        j["case_id"]: j for j in _load_json(JUDGEMENTS_PATH, [])
    }

    print(f"Ollama generation model: qwen3:8b (LABTUTOR_OLLAMA_MODEL)")
    print(f"Ollama judge model:      qwen3:8b (same model -- see non-independence note)")
    print(f"Cases in dataset:        {len(cases)}")
    print(f"Already have results:    {len(existing_raw)} raw, {len(existing_judgements)} judged")
    print()

    for i, case in enumerate(cases, start=1):
        cid = case["case_id"]
        if case.get("blocked_no_image_asset"):
            print(
                f"[{i}/{len(cases)}] {cid}: BLOCKED (no image asset available -- "
                "see docs/exp07_image_gap.md), not executed"
            )
            existing_raw[cid] = {
                "case_id": cid,
                "experiment_id": case.get("experiment_id", "exp07"),
                "blocked_no_image_asset": True,
                "reason": "No page-image bytes exist for this manual in this repo/session.",
            }
            RAW_OUTPUT_PATH.write_text(json.dumps(list(existing_raw.values()), indent=2))
            continue
        if cid in existing_raw and cid in existing_judgements and existing_judgements[cid].get(
            "_judge_raw_valid"
        ):
            print(f"[{i}/{len(cases)}] {cid}: SKIP (already have a valid saved result)")
            continue

        print(
            f"[{i}/{len(cases)}] {cid} ({case.get('experiment_id', 'exp07')}, "
            f"{case['language']}): running..."
        )
        try:
            result = await run_case(case)
        except Exception as exc:  # noqa: BLE001
            print(f"    CASE-LEVEL FAILURE: {type(exc).__name__}: {exc}")
            existing_raw[cid] = {"case_id": cid, "error": f"{type(exc).__name__}: {exc}"}
            RAW_OUTPUT_PATH.write_text(json.dumps(list(existing_raw.values()), indent=2))
            continue

        existing_raw[cid] = result
        RAW_OUTPUT_PATH.write_text(json.dumps(list(existing_raw.values()), indent=2))
        print(
            f"    generated in {result['latency_seconds']}s via '{result['reply_source']}'"
            f" | intent {'OK' if result['intent_correct'] else 'MISMATCH'}"
            f" ({result['detected_intent']})"
            + (
                f" | recall@1={result['recall_at_1']}"
                if result["expected_page"] is not None
                else " | (no retrieval expected)"
            )
        )

        if result.get("error"):
            print(f"    generation error, skipping judge call: {result['error']}")
            continue

        judgement = _call_judge(case, result["reply_text"], result["retrieved_context_used"])
        judgement["case_id"] = cid
        existing_judgements[cid] = judgement
        JUDGEMENTS_PATH.write_text(json.dumps(list(existing_judgements.values()), indent=2))
        if judgement.get("_judge_raw_valid"):
            print(
                f"    judged: relevant={judgement.get('relevant')} "
                f"grounded={judgement.get('grounded_in_context')} "
                f"hallucination={judgement.get('hallucination')}"
            )
        else:
            print(f"    JUDGE FAILED after retries: {judgement.get('_judge_error')}")

    print("\nDone. Raw outputs:", RAW_OUTPUT_PATH)
    print("Judgements:", JUDGEMENTS_PATH)


if __name__ == "__main__":
    asyncio.run(main())
