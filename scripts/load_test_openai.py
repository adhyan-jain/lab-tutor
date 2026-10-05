"""Load test: 100 concurrent users, 1 LLM request each, via OpenAIBackend.

Usage:
    # From project root, with venv activated and .env loaded:
    python scripts/load_test_openai.py

    # Optional: override user count (default 100):
    LOAD_TEST_USERS=50 python scripts/load_test_openai.py

Prerequisites:
    .env must have GPT=true and OPENAI_API_KEY=<key>
"""

from __future__ import annotations

import asyncio
import os
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

from backend.config import get_settings
from backend.llm.client import OpenAIBackend, LLMUnavailable, reset_backend_cache, reset_concurrency_limit

NUM_USERS = int(os.getenv("LOAD_TEST_USERS", "100"))

SYSTEM_PROMPT = (
    "You are a helpful chemistry lab tutor for undergraduate students. "
    "Answer concisely and accurately."
)

QUESTIONS = [
    "What is the purpose of a blank in a titration experiment?",
    "Why do we use a water bath instead of direct heating for some reactions?",
    "What does pH 7 mean in terms of hydrogen ion concentration?",
    "Explain the difference between molarity and molality.",
    "Why is it important to rinse the burette with the titrant before filling?",
    "What is an indicator and how does it work in acid-base titrations?",
    "Why should we avoid parallax error when reading the burette?",
    "What is the role of EDTA in complexometric titrations?",
    "Explain what a primary standard is and give an example.",
    "Why do we perform multiple titrations and take an average?",
]


class RequestResult:
    __slots__ = ("user_id", "success", "latency_ms", "backend", "model",
                 "prompt_tokens", "completion_tokens", "error")

    def __init__(self, user_id: int, success: bool, latency_ms: float,
                 backend: str = "", model: str = "",
                 prompt_tokens: int | None = None,
                 completion_tokens: int | None = None,
                 error: str = ""):
        self.user_id = user_id
        self.success = success
        self.latency_ms = latency_ms
        self.backend = backend
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.error = error


async def run_single(backend: OpenAIBackend, user_id: int) -> RequestResult:
    question = QUESTIONS[user_id % len(QUESTIONS)]
    t0 = time.monotonic()
    try:
        reply = await backend.complete(
            system=SYSTEM_PROMPT,
            user=question,
            max_tokens=256,
        )
        return RequestResult(
            user_id=user_id,
            success=True,
            latency_ms=(time.monotonic() - t0) * 1000,
            backend=reply.backend,
            model=reply.model,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
        )
    except (LLMUnavailable, Exception) as exc:
        return RequestResult(
            user_id=user_id,
            success=False,
            latency_ms=(time.monotonic() - t0) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )


def _bar(value: float, max_value: float, width: int = 40) -> str:
    filled = int(round(value / max_value * width)) if max_value > 0 else 0
    return "█" * filled + "░" * (width - filled)


def print_report(results: list[RequestResult], total_wall_ms: float) -> None:
    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]
    latencies = sorted(r.latency_ms for r in ok)

    print("\n" + "=" * 62)
    print("  LABTUTOR  —  OPENAI LOAD TEST RESULTS")
    print("=" * 62)
    print(f"  Requests:       {len(results)}")
    print(f"  Successful:     {len(ok)}  ({100*len(ok)/len(results):.1f}%)")
    print(f"  Failed:         {len(fail)}  ({100*len(fail)/len(results):.1f}%)")
    print(f"  Wall-clock:     {total_wall_ms/1000:.2f} s")
    if results:
        print(f"  Throughput:     {len(results)/(total_wall_ms/1000):.2f} req/s")
    print()

    if latencies:
        p50 = statistics.median(latencies)
        p90 = latencies[int(len(latencies) * 0.90)]
        p99 = latencies[int(len(latencies) * 0.99)]
        mean = statistics.mean(latencies)
        stddev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

        print("  LATENCY  (successful requests only)")
        print(f"    min    {min(latencies):>8.0f} ms")
        print(f"    mean   {mean:>8.0f} ms")
        print(f"    p50    {p50:>8.0f} ms")
        print(f"    p90    {p90:>8.0f} ms")
        print(f"    p99    {p99:>8.0f} ms")
        print(f"    max    {max(latencies):>8.0f} ms")
        print(f"    stdev  {stddev:>8.0f} ms")
        print()

        buckets = [500, 1000, 2000, 3000, 5000, 10000, float("inf")]
        labels  = ["<500ms", "<1s", "<2s", "<3s", "<5s", "<10s", "≥10s"]
        counts  = [0] * len(buckets)
        for lat in latencies:
            for i, b in enumerate(buckets):
                if lat < b:
                    counts[i] += 1
                    break
        print("  LATENCY DISTRIBUTION")
        for label, count in zip(labels, counts):
            print(f"    {label:>7}  {_bar(count, len(latencies))}  {count}")
        print()

    tp = sum(r.prompt_tokens or 0 for r in ok)
    tc = sum(r.completion_tokens or 0 for r in ok)
    if tp or tc:
        print("  TOKEN USAGE")
        print(f"    prompt      {tp:>8,}")
        print(f"    completion  {tc:>8,}")
        print(f"    total       {tp+tc:>8,}")
        print()

    if ok:
        print(f"  Model:    {ok[0].model}")
        print(f"  Backend:  {ok[0].backend}")
        print()

    if fail:
        from collections import Counter
        print("  ERRORS")
        for err, count in Counter(r.error for r in fail).most_common():
            msg = err[:80] + "…" if len(err) > 80 else err
            print(f"    [{count}x] {msg}")
        print()

    print("=" * 62 + "\n")


async def main() -> None:
    reset_backend_cache()
    reset_concurrency_limit()
    settings = get_settings()

    if not settings.gpt:
        print("ERROR: GPT=true is not set in your .env")
        print("       Add:  GPT=true")
        sys.exit(1)
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY is not set in your .env")
        sys.exit(1)

    backend = OpenAIBackend(settings)
    print(f"  users:      {NUM_USERS}")
    print(f"  model:      {settings.openai_model}")
    print(f"  concurrency cap: {settings.llm_max_concurrency}  (LABTUTOR_LLM_MAX_CONCURRENCY)")
    print("\nFiring all requests...\n")

    wall_start = time.monotonic()
    tasks = [asyncio.create_task(run_single(backend, uid)) for uid in range(NUM_USERS)]

    results: list[RequestResult] = []
    done = 0
    for coro in asyncio.as_completed(tasks):
        r = await coro
        results.append(r)
        done += 1
        tag = "OK  " if r.success else "FAIL"
        print(f"  [{done:>3}/{NUM_USERS}] user {r.user_id:>3}  {tag}  {r.latency_ms:.0f}ms", end="\r")

    total_wall_ms = (time.monotonic() - wall_start) * 1000
    print()
    print_report(results, total_wall_ms)


if __name__ == "__main__":
    asyncio.run(main())
