"""Latency and call-count benchmark for the seven Experiment 7 interaction types.

Runs the real code paths against whatever LLM backend the environment
configures, and reports, per interaction: LLM calls per request, latency
(p50 / p95), tokens, retries and errors. It invents nothing: if no backend is
reachable, the model-backed rows say so instead of showing numbers.

  1 procedural question      grounded Q&A                        1 model call
  2 conceptual question      grounded Q&A                        1 model call
  3 Socratic follow-up       realise_turn (advisory call)        1 model call
  4 misconception            controller, authored probe          0 calls
  5 proactive intervention   controller, authored concept card   0 calls
  6 result interpretation    realise_turn (advisory call)        1 model call
  7 final transfer question  controller, final assessment        0 calls

Usage (project root, venv active, .env loaded):
  python scripts/bench_exp07.py                 # 5 runs per interaction
  python scripts/bench_exp07.py --runs 20
  python scripts/bench_exp07.py --json out.json

To compare model settings, run it once per configuration, e.g.
  OPENAI_REASONING_EFFORT=low python scripts/bench_exp07.py --json low.json
  OPENAI_REASONING_EFFORT=none python scripts/bench_exp07.py --json none.json
and compare calls, p50/p95, completion tokens AND read the sample replies
(--show) for chemistry correctness: latency alone is not the criterion.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from backend.llm import telemetry  # noqa: E402
from backend.llm.client import LLMUnavailable, get_backend  # noqa: E402
from backend.retrieval.pipeline import answer_question  # noqa: E402
from backend.socratic_engine import realise  # noqa: E402
from backend.socratic_engine.knowledge import get_knowledge  # noqa: E402
from backend.socratic_engine.walkthrough import controller as ctl  # noqa: E402
from backend.tests.concept_answers import GOOD  # noqa: E402

K = get_knowledge("exp07")


def _ctx(qid: str, answer: str, misses: int = 0) -> dict:
    q = K.question_by_id[qid]
    c = K.concept_by_id[q.concept_id]
    return {
        "step_title": "Start the optimisation", "concept_name": c.name, "concept_description": c.description,
        "question_type": q.qtype, "question": q.ask, "expected_reasoning": q.expected_reasoning,
        "concept_state": "ATTEMPTED", "misses": misses, "student_answer": answer, "concept_id": c.id,
    }


def _walk_to(predicate, student="bench"):
    state = ctl.new_state(student)
    ctl.start(state)
    from backend.tests.test_walkthrough_controller import good_answer

    for _ in range(900):
        r = ctl.take_turn(state, good_answer(state))
        if predicate(state):
            return state, r
    raise RuntimeError("could not reach the benchmark state")


async def _run_qa(message: str):
    stats = telemetry.begin_request()
    t0 = time.monotonic()
    result = await answer_question(message, active_experiment="exp07", conversation_history="")
    # Only a model-written answer is a model sample; extractive/fallback text
    # means the backend was unavailable and must not be reported as one.
    text = result.text if result.answer_source == "llm" else None
    return stats, (time.monotonic() - t0) * 1000, text


async def _run_realise(ctx: dict):
    stats = telemetry.begin_request()
    t0 = time.monotonic()
    out = await realise.realise_turn(ctx)
    return stats, (time.monotonic() - t0) * 1000, out.response if out else None


async def _run_controller(make):
    """Deterministic path: time the pure controller turn (no model)."""
    stats = telemetry.begin_request()
    state, msg = make()
    t0 = time.monotonic()
    result = ctl.take_turn(state, msg)
    return stats, (time.monotonic() - t0) * 1000, result.reply


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


async def bench(runs: int):
    def misconception():
        state, _ = _walk_to(lambda s: s.phase == "concept")
        return state, "geometry optimization makes the molecule look nicer"

    def intervention():
        # time the turn that opens the concept moment (card + question): the
        # answer to the optimisation chapter's opening guess moves on to r1_run
        state, _ = _walk_to(lambda s: s.phase == "hook" and s.step_id == "r1_run")
        return state, "I would guess it moves the atoms a bit"

    def final_transfer():
        state, _ = _walk_to(lambda s: s.phase == "assess")
        state.assess["i"] = len(state.assess["queue"]) - 1
        return state, GOOD[state.assess["queue"][-1]]

    cases = [
        ("1 procedural question", lambda: _run_qa("How do I open the Orca input dialog in Gabedit?"), True),
        ("2 conceptual question", lambda: _run_qa("Why do we optimise the geometry before the orbital calculation?"), True),
        ("3 Socratic follow-up", lambda: _run_realise(_ctx("q_opt_why", "hmm the software figures it out somehow")), True),
        ("4 misconception", lambda: _run_controller(misconception), False),
        ("5 proactive intervention", lambda: _run_controller(intervention), False),
        ("6 result interpretation", lambda: _run_realise(_ctx("q_pattern_interpret", "the numbers moved a bit when I changed things")), True),
        ("7 final transfer question", lambda: _run_controller(final_transfer), False),
    ]
    rows = []
    for name, call, needs_model in cases:
        lat, calls, ptoks, ctoks, retries, errors, sample = [], [], [], [], 0, 0, None
        for _ in range(runs):
            try:
                stats, ms, text = await call()
            except LLMUnavailable as exc:
                errors += 1
                sample = f"backend unavailable: {exc}"
                continue
            if needs_model and text is None:
                errors += 1  # the model path degraded to its fallback; not a real sample
                sample = "no model reply (backend not configured, unreachable, or fell back)"
                continue
            lat.append(ms)
            calls.append(stats.calls)
            if stats.prompt_tokens:
                ptoks.append(stats.prompt_tokens)
            if stats.completion_tokens:
                ctoks.append(stats.completion_tokens)
            retries += stats.retry_count
            sample = text
        rows.append({
            "interaction": name, "runs": runs, "ok": len(lat), "errors": errors,
            "llm_calls_per_request": statistics.mean(calls) if calls else None,
            "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95),
            "mean_prompt_tokens": statistics.mean(ptoks) if ptoks else None,
            "mean_completion_tokens": statistics.mean(ctoks) if ctoks else None,
            "retries": retries, "sample": sample,
        })
    return rows


def _fmt(v, nd=0):
    return "-" if v is None else f"{v:.{nd}f}"


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--json", help="write full results here")
    ap.add_argument("--show", action="store_true", help="print a sample reply per interaction")
    args = ap.parse_args()

    backend = get_backend()
    print(f"backend={getattr(backend, 'name', type(backend).__name__)} runs={args.runs}\n")
    rows = await bench(args.runs)
    print(f"{'interaction':28} {'ok':>4} {'err':>4} {'calls':>6} {'p50ms':>8} {'p95ms':>8} {'ptok':>6} {'ctok':>6} {'retry':>6}")
    for r in rows:
        print(
            f"{r['interaction']:28} {r['ok']:>4} {r['errors']:>4} {_fmt(r['llm_calls_per_request'], 1):>6} "
            f"{_fmt(r['p50_ms']):>8} {_fmt(r['p95_ms']):>8} {_fmt(r['mean_prompt_tokens']):>6} "
            f"{_fmt(r['mean_completion_tokens']):>6} {r['retries']:>6}"
        )
        if args.show and r["sample"]:
            print(f"    sample: {str(r['sample'])[:300]!r}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
