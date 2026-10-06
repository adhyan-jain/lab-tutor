# Latency and concurrency audit (code-level)

Scope: what the repository's code and defaults do on an Exp7 turn, what was
measured here, and what could not be. **Nothing below is a measurement of the
deployed system.** The deployment (VPS/Compose vs Cloud Run), worker count in
production, database host and network path to OpenAI are not recorded in the
repo and were not verified.

## What was verified from code

| Item | Finding |
| --- | --- |
| LLM calls per turn | 0 for walkthrough steps, quizzes, hints, concept moments, probes, scaffolds, the final assessment; 1 for grounded Q&A and for an UNCLEAR free-text conceptual answer; 2 only if `LABTUTOR_ROUTER_ENABLED` (default off). Tested: `test_walkthrough_api.py`, `test_concept_realise.py`. |
| OpenAI model default | `OPENAI_MODEL=gpt-5.6-luna` (config default); the live value is whatever the deployed env sets. |
| Reasoning effort | `OPENAI_REASONING_EFFORT` defaults to empty, so the parameter is not sent and the model's own default applies. **Not changed.** Benchmark `none` / `low` / current with `scripts/bench_exp07.py` before choosing. |
| Output-token caps | Q&A 3072, Exp7/8 Q&A 8192, Socratic reply 1000, router 200, new advisory realisation 300. Exp7 Q&A at 8192 is a ceiling, not a target; reply length is controlled by the prompt. Not changed without quality measurement. |
| Timeouts / retries | 30 s client timeout; non-streaming OpenAI retries (408/429/5xx, up to 3 attempts, 25 s budget). Streaming previously had **no retry**; it now retries once, only before the first token (`test_llm_budget.py`). |
| Streaming | Real SSE for OpenAI only (`/api/chat/messages/stream`). Raw tokens stream before post-processing, so the streamed text can differ slightly from the stored message. The advisory realisation call deliberately does not stream (it returns JSON). Vertex/Ollama/hosted do not stream. |
| Telemetry | Per-reply `timing` {total_ms, llm_ms, ttft_ms, non_llm_ms, llm_calls, retry_count}; streamed replies record `ttft_ms` and token usage (`stream_options.include_usage`); a `chat_timing` log line adds the commit time. No prompt or reply text is logged. |
| Concurrency pools | `LABTUTOR_LLM_MAX_CONCURRENCY` (code default 20, `.env.example` 70) is **per process**. Background summaries previously shared it; they now use `LABTUTOR_LLM_BACKGROUND_CONCURRENCY` (default 4). Tested with a starvation test. The streaming path holds its slot for the whole stream. |
| Prompt caching | Vertex-only context cache, off by default; not on the OpenAI path. For Exp7/8 the full source material leads the prompt, so OpenAI automatic prefix caching can apply; only `cached_tokens` is read back. |

## A real concurrency risk found in the code (not fixed)

In `_process_message` the student's message is `flush`ed (line ~993) but the
transaction is not committed until the reply is persisted (line ~1398). The
request's DB session therefore stays open across every model call.

- On **SQLite** (local dev, tests) that holds the single write lock for the
  whole model wait. The simulated 70-student test shows it: with a 50 ms fake
  model, p95 is about 4 s because requests serialise on the lock.
- On **Postgres** the equivalent is one pooled connection held for the full
  model wait (about 1-5 s per real call). The pool is `pool_size=20,
  max_overflow=10` **per worker** and the container default is 2 workers. 70
  simultaneous in-flight chats is about 35 per worker, which exceeds 30, so
  the excess would queue on pool checkout. That is a latency tail, not
  necessarily errors, but it is plausible and unmeasured.
- Not changed because the obvious fix, committing the student message before
  the model call, alters behaviour: a failed turn would leave a stored student
  message with no reply (affecting retries and prompt-count analytics). It
  should be a deliberate decision, followed by a Postgres measurement. Do not
  simply raise the pool size.

## What was run here, and its limits

- `backend/tests/test_load_simulated.py`: 70 concurrent students through the
  real API on SQLite with a fake 50 ms model. Result: 0 failures, exactly one
  model call per side question, no retries or fallbacks, and live students kept
  getting replies while 8 background workers fought over the background pool.
  This checks orchestration only. It says nothing about OpenAI latency,
  Postgres, CPU, memory or the deployed server.
- `scripts/bench_exp07.py`: runs; with the local `.env` (hosted backend
  returns 401, Ollama not running) the model-backed rows correctly report "no
  model reply", so **no latency numbers exist**. The deterministic rows (0
  calls) run in about a millisecond or less.

## Still to measure (needs a key and a running stack)

1. `python scripts/bench_exp07.py --runs 20 --show` for the current model
   settings, then once each with `OPENAI_REASONING_EFFORT=low` and `none`;
   compare p50/p95, completion tokens and read the sample replies for
   chemistry correctness. Choose on latency, quality, cost and scalability
   together, not the model name.
2. `python scripts/load_test_openai.py` at 1 / 10 / 30 / 70 users for
   provider-side latency and 429s.
3. The same through the real API against Postgres with the intended worker
   count, recording active/idle connections, pool wait, p50/p95/p99, TTFT,
   error rate and CPU/memory, before any claim of 70-student capacity.
4. Confirm the live deployment platform and its worker/CPU/memory/instance
   settings from the deployment itself.
