# LLM usage: request budget, caching and latency

Part 1 is the enforced per-message budget and context cache. Part 2 is a code-level latency/concurrency audit (not a measurement of any deployment).

## Part 1 - Request budget and context caching


Two rules, both enforced in code and covered by tests:

1. **A student message costs at most one model generation.**
2. **The stable part of an experiment's prompt is cached natively on Vertex**,
   versioned by a fingerprint of its content.

### One generation per message

`backend/llm/telemetry.py` keeps a per-request counter. Every backend
`complete()` increments `llm_calls`; the chat route stores the result in the
assistant message's `metadata_json` and in one log line per message:

    chat_message llm_calls=1 attempts=1 retries=0 vertex_ok=True fallback=False
    cache_hit=True cached_tokens=9800 model=gemini-2.5-flash student=... classroom=... exp=exp07

A value above 1 also logs `llm_calls_exceeded` at WARNING.

| Message kind | Generations |
|---|---|
| Exp7/8 question (grounded Q&A) | 1 |
| Other experiments, plain Q&A | 1 |
| Socratic hint | 1 (failure or empty/meta reply -> deterministic hint template, never a second call) |
| Numeric submission (Tier 1 to 3) | 1 (phrasing only; the verdict is computed deterministically) |
| Safety / distress / off-scope triage | 0 |

The LLM router is **off by default** (`LABTUTOR_ROUTER_ENABLED=false`): it was a
second generation per message. Interaction mode (Q&A / Socratic / diagnostic /
clarification / safety / out-of-scope) is chosen by the existing deterministic
code and is stated to the one answering call. Background summary jobs are not
per-message and are counted separately.

**Retries have exactly one owner**: `VertexBackend._generate`. Only 429/5xx are
retried, with exponential backoff and jitter, bounded by
`LABTUTOR_LLM_MAX_ATTEMPTS` (3) and a wall-clock budget
(`LABTUTOR_LLM_RETRY_BUDGET_SECONDS`, 25). The SDK's own retry is unset and no
caller retries, so one logical generation is at most 3 HTTP attempts.
Automatic function calling is disabled on every request.

**Concurrency** is bounded per process (`LABTUTOR_LLM_MAX_CONCURRENCY`) with a
queue timeout (`LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS`); a request that cannot get
a slot takes the extractive fallback instead of waiting. This is *not* a
project-wide rate limiter: with Cloud Run `maxScale` N the ceiling is N x the
setting, and the project's Vertex quota is enforced by Google. No RPM figure is
hard-coded anywhere. Assumption: replicas are few (currently `maxScale=3`).

**The extractive fallback is observable**: `fallback_used`, `fallback_reason`,
`vertex_attempted`, `vertex_succeeded`, `vertex_error` (exception class and
status code only, never message text), `retry_count` and latency are in the
message metadata.

### Context caching

What is cached: the system prompt plus the experiment's complete source
material (official procedure in document order, then the labelled background
explainer). About 9-10k tokens for Exp7, measured live -- this grew from an
earlier 6.5k estimate as the Exp7 background file
(`knowledge/adjacent/exp07_background.md`) gained the screen-control
glossary and ORCA output guide. What is
never cached: the question, conversation history, session/Socratic/
diagnostic/walkthrough state, or anything about a student. The per-message
dynamic tail is sent uncached; the guided walkthrough's own turns
(hooks, steps, hints, checkpoints) make no model call at all and never touch
the cache -- see docs/ARCHITECTURE.md §2.1.2.

Enable with `LABTUTOR_LLM_CONTEXT_CACHE=true` (Vertex backend only);
`LABTUTOR_LLM_CONTEXT_CACHE_SCOPES` (default `exp07`) picks the experiments,
`LABTUTOR_LLM_CONTEXT_CACHE_TTL_SECONDS` (default 10800) the lifetime.

**Versioning.** The cache name is `labtutor-{experiment}-{fingerprint16}`. The
fingerprint is a SHA-256 over: the policy version, experiment, model, location,
the system prompt text, the full stable source text, and the id/document/tier/
version of every passage. Nothing about the cache id is stored in code, the
image or the environment.

**Lifecycle** (`backend/llm/context_cache.py`):

- Requests look the cache up in memory; creation never blocks a student. The
  first request(s) before a cache exists go out uncached (still one generation).
- Creation is single-flight per fingerprint in a process; across Cloud Run
  instances it is list-before-create, and if two instances race the cache with
  the oldest `create_time` wins and the loser deletes its duplicate. No Redis.
- The cache is warmed at startup in the background, and renewed on use once half
  its TTL is spent.
- If Google reports the cache gone, that same generation is re-sent uncached
  (one extra HTTP attempt, still one generation) and the cache is recreated.
- Old versions are not deleted during a deploy; they expire by TTL.

**Dev commands**

    python -m backend.llm.context_cache --list
    python -m backend.llm.context_cache --refresh [--delete-stale]

or, equivalently: `make list-llm-cache`, `make refresh-llm-cache`.

**Observability.** `cache_hit`, `cache_ref` (fingerprint, first 8 hex
characters -- a version id, not a secret) and `cached_tokens` are in every
tutor message's metadata (`llm_stats.as_meta()`) and in the `chat_message`
log line. `context_cache.py` additionally logs one INFO line per lifecycle
event: `created` vs `reused` on `ensure()`, `expired` and `miss` (creation
started) in `resolve()`, and a line if renewal fails. None of these ever
include student text or a secret.

### If I edit `manual/IACHY102_manual.md`, what happens?

Redeploy (or restart) the backend so the retrieval index is rebuilt. The Exp7
stable text now differs, so its fingerprint differs, so the **old cache is
simply never selected**. On start the warm-up creates a new
`labtutor-exp07-<new fingerprint>` cache; until it exists, requests go out
uncached with the same prompt (correct answers, just more input tokens). The
old cache expires by TTL. Nothing needs to be flushed by hand, and nothing can
serve an answer from the old text once the new build is live. Reverting the edit
restores the old fingerprint and reuses its cache if it has not expired. Editing
any tier-B/tier-C source file for Exp7, the system prompt, the model, or the
location behaves the same way. To force a rebuild immediately in dev, run
`--refresh --delete-stale`.

Citations are unaffected: they still come from the application's own retrieval
ranking, not from the cache.

## Part 2 - Latency and concurrency audit


Scope: what the repository's code and defaults do on an Exp7 turn, what was
measured here, and what could not be. **Nothing below is a measurement of the
deployed system.** The deployment (VPS/Compose vs Cloud Run), worker count in
production, database host and network path to OpenAI are not recorded in the
repo and were not verified.

### What was verified from code

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

### A real concurrency risk found in the code (not fixed)

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

### What was run here, and its limits

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

### Still to measure (needs a key and a running stack)

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
