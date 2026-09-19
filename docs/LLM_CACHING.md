# LLM request budget and context caching

Two rules, both enforced in code and covered by tests:

1. **A student message costs at most one model generation.**
2. **The stable part of an experiment's prompt is cached natively on Vertex**,
   versioned by a fingerprint of its content.

## One generation per message

`backend/llm/telemetry.py` keeps a per-request counter. Every backend
`complete()` increments `llm_calls`; the chat route stores the result in the
assistant message's `metadata_json` and in one log line per message:

    chat_message llm_calls=1 attempts=1 retries=0 vertex_ok=True fallback=False
    cache_hit=True cached_tokens=6500 model=gemini-2.5-flash student=... classroom=... exp=exp07

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

## Context caching

What is cached: the system prompt plus the experiment's complete source
material (official procedure in document order, then the labelled background
explainer). About 6.5k tokens for Exp7. What is never cached: the question,
conversation history, session/Socratic/diagnostic state, or anything about a
student. The per-message dynamic tail is sent uncached.

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

## If I edit `manual/IACHY102_manual.md`, what happens?

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
