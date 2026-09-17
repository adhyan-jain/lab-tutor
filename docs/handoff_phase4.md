# Phase 4 handoff

Written 2026-09-17, branch `master`, HEAD `3e099ee` (updated in place as
the session continued — see item 8), continuing directly from
`docs/handoff_phase3.md` (still accurate — nothing in it was reversed
this session; treat it as background, this document as current).

## What changed this session, in order

1. **UI cleanup**: emoji glyphs replaced with SVG icons
   (`frontend/components/Icons.tsx`); the experiment picker now lists
   `EXP01..EXP10` in plain numeric order instead of star-marking a
   hardcoded subset (`7ecd55f`).

2. **Two real bugs found via live testing, fixed**:
   - Socratic answer-key recognition and a stale error banner (`5b83442`).
   - A plain question no longer silently starts a guided Socratic session
     (`dc6da98`).
   - An unhandled 500 when a Socratic step attempt's data didn't match
     the step's declared field names — `_handle_socratic_attempt` in
     `chat_routes.py` now catches `ManualNotTranscribedError` the same
     way `socratic_routes.py` already did (`d745130`).
   - Post-session summaries were unreachable through the UI once a
     session ended (`eaae49d`).

3. **A serious content-grounding bug, found from a live screenshot
   complaint and fixed**: `manual/IACHY102_manual.md` — the file the RAG
   pipeline indexes and quotes to students as authoritative "official
   manual" text — had internal build-session engineering notes mixed
   directly into several experiments (references to `docs/final_audit.md`,
   this codebase's own "Tier 1" terminology, `exp07.py`/
   `QualitativeOrderingPlugin`, a developer-only golden-test-tracking
   table). A student asking a normal question got engineering jargon
   quoted back with a fabricated page citation. Stripped, verified no
   chemistry/procedure/rubric content was touched (`ccc9cc5`).
   - Side effect, handled properly rather than ignored: this shifted the
     retrieval corpus's BM25/TF-IDF statistics enough that 6
     `golden_dataset/qa/*.json` cases stopped matching their recorded
     `expected_behavior` — this went unnoticed locally for a while (a
     mistake — a "known baseline" that was actually red CI) until
     checked with `gh run view --log-failed` against the real GitHub
     Actions run. Fixed properly by running the repo's own sanctioned
     `golden_dataset/qa/generate_qa.py`, which re-verifies every case
     against the live pipeline before writing it (`17b12e2`). **CI is
     green as of this commit** — confirm this is still true before
     trusting anything below it if much time has passed.

4. **LLM meta-commentary leaking into tutor/diagnosis replies**: a weak
   local model (Ollama `llama3:latest`) sometimes narrated its own task
   ("Here's a re-worded hint for the student: ...") instead of just
   answering. Added a reject-and-fall-back-to-template check, then
   broadened it after live testing caught a phrasing variant and a
   literal leaked prompt-section-label case the first version missed
   (`b8a1d02`, `623b915`, `4b909c5`).

5. **Conversation memory + a real mid-experiment Q&A fallback**
   (`079315a`): neither plain Q&A nor Socratic chat ever saw a thread's
   own prior messages, so a ChatGPT-style follow-up ("what does that
   mean?") had no idea what "that" meant. Threaded a bounded, per-thread
   history (last 12 messages) into both prompts as context-only text.
   Separately: during active Socratic guidance, a non-numeric message
   that wasn't clearly a hint/nudge request used to always fall back to
   the current step's hint verbatim on any LLM trouble — now it falls
   back to the same grounded Q&A pipeline plain chat uses instead, since
   that pipeline never had access to the withheld answer either.

6. **The LLM conversational router** (`430a699`) — the main piece of
   work this session, described in full below.

7. `.playwright-mcp/` (local browser-testing snapshot dumps) added to
   `.gitignore` (`1a92e55`).

8. **Markdown leaking into student-facing text, found live and fixed**:
   the local Ollama model sometimes emitted `**bold**`/`__bold__` despite
   every system prompt saying "plain prose only, no markdown" — the
   frontend renders replies as plain text, so a student saw literal
   double-asterisks around terms like `**CH4**`. Fixed structurally at
   the one place every `LLMReply` is built
   (`backend/llm/client.py::_strip_markdown_emphasis`), so it's fixed for
   every caller (Q&A, Socratic, diagnosis phrasing, summaries) at once —
   not by re-wording the prompt and hoping. Only the unambiguous
   double-marker forms are stripped; single `*`/`_` are left alone
   (ordinary chemistry notation — a radical dot, a subscript-adjacent
   underscore) (`3e099ee`).

## The conversational router

### Why it exists

Root cause traced precisely, not guessed at: `answer_question()` in
`backend/retrieval/pipeline.py` runs `classify_scope()` /
`resolve_status()` **before** ever calling the LLM. For a content-free
follow-up like "why?", scope classification correctly inherits the
active experiment, but *retrieval* searches the index on the literal
text "why" — which matches nothing — so the function returns the
deterministic "I couldn't find enough" template **before**
`_phrase_with_llm` (and therefore item 5's new conversation history) is
ever reached. The conversation-memory fix alone could not solve this,
because a deterministic, content-blind gate sat in front of the LLM.

### What it is

New package `backend/router/`:
- `schema.py` — `RouterMode` (`qa`/`socratic`/`diagnostic`/
  `clarification`/`out_of_scope`) and `RouterDecision` (pydantic:
  `mode`, `experiment_id`, `confidence`, `needs_retrieval`,
  `retrieval_query`, `rationale`).
- `router.py` — `route_message(...)`: builds a prompt from the same
  bounded history text `chat_routes.py` already computes, the classroom's
  active experiment, whether a Socratic session is active, and the known
  experiment id→title map (so it can never invent an id); calls the LLM;
  parses the reply defensively (strips markdown fences, extracts the
  outermost `{...}`, `json.loads`, pydantic-validates). **Any** failure
  — backend unavailable, a call exceeding `router_timeout_seconds`,
  malformed JSON, schema validation failure, an unknown experiment id, or
  confidence below `router_min_confidence` — returns `None`, and `None`
  is the *only* value that ever comes back short of a fully-valid,
  sufficiently-confident decision. There is no partial-trust state.

### Wiring (`backend/api/chat_routes.py::send_message`)

Unchanged, still first: safety/distress/off-scope triage
(`triage.classify`/`short_circuits`), and the numeric-step-attempt check
(an active, incomplete Socratic session plus extractable numeric data is
*always* Tier 1's to verify, never routed). Everything else calls
`route_message`; on `None` it runs the exact pre-existing keyword-based
dispatch, unchanged, line for line. On a decision, it dispatches:
`diagnostic`→Tier 1-3 (only if numbers were actually extracted, never
invented), `socratic`→the existing state machine (only if the experiment
has steps), `clarification`→a small fixed deterministic reply, and
`qa`/`out_of_scope` both go through the *same* `answer_question()` call
— a deliberate choice (see below), with the router able to override the
search text (`retrieval_query`, a context-expanded restatement of a
follow-up like "why?") and which experiment is used for retrieval, never
the raw text that gets stored as the student's own turn.

**Why `qa` and `out_of_scope` are treated identically**: `answer_question`
already re-derives scope deterministically via
`classify_scope`/`resolve_status`, and that classifier is explicitly
precision-biased against wrongly refusing a real question (see its own
module docstring). Trusting the router's own out-of-scope call directly
would add a second, far-less-tested refusal path with no safety benefit.
This was an explicit design choice, confirmed with the user via
`AskUserQuestion` before implementing (chose "advisory only" over
"immediate deterministic refusal").

### What is still fully deterministic — unchanged by this feature

Safety/distress/off-scope triage, numeric-step-attempt detection, Tier
1-3 diagnosis (`backend.pipeline.run_diagnosis`), the Socratic
verifier/reveal gate (`backend.socratic_engine.engine`,
`backend.answer_gate`), citation/evidence grounding
(`backend.scope.classifier`, `backend.retrieval.pipeline`'s
evidence-sufficiency check), and every session/auth/classroom boundary
check. `backend/router/router.py`'s own module docstring states this
authority boundary explicitly — read it before changing a call site.

### Config

`LABTUTOR_ROUTER_ENABLED` (default `true`, a zero-risk kill switch),
`LABTUTOR_ROUTER_MIN_CONFIDENCE` (default `0.4`),
`LABTUTOR_ROUTER_TIMEOUT_SECONDS` (default `8.0` — **found live, fixed
before shipping**: without its own short timeout, a slow/unavailable
backend let the router's own attempt run the full `llm_timeout_seconds`
(30s) before failing, then the deterministic fallback made its own
full-length call on top of that — up to double the per-turn latency in
exactly the degraded-backend case this system is supposed to degrade
gracefully from). All three documented in `.env.example`, enforced by
`test_single_fire_and_summaries.py::TestEnvExampleIsComplete`.

### Tests

`backend/tests/test_router.py` (10 tests, unit-level: malformed JSON,
missing required field, invalid mode string, unknown experiment id
discarded-not-rejected, low confidence, `LLMUnavailable`, disabled,
markdown-fence stripping, clarification forcing `needs_retrieval=false`).
`backend/tests/test_chat_routes.py::TestConversationalRouter` (10 tests,
integration-level via the real HTTP client with `fake_llm` scripting the
router's reply and a spy on `answer_question` to assert what it was
called with): normal question, the "why?" repro case itself (asserts the
second call's search text is not literally "why?" and the experiment was
inherited), "what does that mean?", "explain that again", a contextual
diagnostic message, a contextual Socratic request with no active session
keyword match, an experiment-comparison switch, an explicit
out-of-scope question (asserts it still reaches `answer_question`), a
safety request (asserts the router is never even called), a
brand-new thread with zero context (asserts `clarification`), a
stale/closed session (asserts the router is never reached, 409 first),
and thread-history cross-thread isolation.

`fake_llm` in `conftest.py` now also patches
`backend.router.router.get_backend`. Every pre-existing test in the
suite continues to exercise the **fallback tree** unchanged, because the
real, unconfigured `HostedBackend` used throughout the test environment
raises `LLMUnavailable` immediately and deterministically — the router
fails closed with zero network calls, exactly like every other LLM call
site already did before this feature existed. Full suite green
(`pytest backend/tests -q`), frontend `tsc --noEmit` and `next build`
both clean (no frontend files touched by this feature).

### Live verification — what worked and what the environment couldn't show

Restarted the app against real Ollama (`llama3:latest`) and tried the
"why?" repro live, twice, in a single existing chat thread (per explicit
instruction: don't spawn a new thread for every check). Both times, the
router's own call exceeded its 8s timeout and correctly, safely deferred
to the deterministic fallback — confirmed via a direct `curl` to
`localhost:11434/api/chat` with a trivial "say hi" prompt, which itself
did not respond within 20 seconds. **This is the same pre-existing
resource-contention issue flagged repeatedly in earlier sessions**: a
long-running, unrelated `ollama runner` process on this dev machine has
been pinned at ~90%+ CPU for hours at a time, starving the model server
of the compute it needs to respond at all. It is not a router defect —
the fail-safe engaged exactly as designed under real degraded
conditions, and the automated tests (which control the LLM output
directly) already prove the router's own routing/decision logic is
correct end-to-end. **A live, successful "why?" demo on this specific
machine is blocked on that unrelated CPU contention, not on this code.**
Whoever continues should either free up this machine's CPU, or verify
against a real hosted LLM provider instead of local Ollama (see next
section) — an 8-9B local model on a shared, contended host was never a
realistic proxy for pilot-grade latency anyway.

## Next steps, per the user's own stated plan (not yet started)

The user explicitly said, mid-session: *"we still need to setup auth and
vertex ai and deploy after load testing with vertex ai."* None of the
three has been started. Notes for whoever picks this up:

1. **Real Google OAuth**: `.env.example`'s `GOOGLE_CLIENT_ID`/
   `GOOGLE_CLIENT_SECRET` are dummy values in every session so far
   (`dummy.apps.googleusercontent.com`/`dummy`). All auth flows this
   session and prior ones were exercised via a signed-session-cookie
   helper script, never a real Google OAuth round-trip. This needs real
   credentials from Google Cloud Console (OAuth consent screen +
   credentials) before anything below it can be tested for real.

2. **Vertex AI**: `backend/config.py::Settings.llm_backend` is
   `Literal["hosted", "ollama"]`. `"hosted"` is a generic OpenAI-
   compatible `/chat/completions` client (`backend/llm/client.py::
   HostedBackend`) — the provider is just a base URL + API key + model
   name, nothing provider-specific is hardcoded. Google has published an
   OpenAI-compatibility layer for Vertex AI's Gemini models
   (`https://<region>-aiplatform.googleapis.com/v1/...openapi` /
   the `chat/completions`-shaped endpoint) — **this has not been
   tried against this codebase**, so before assuming it works: point
   `LABTUTOR_LLM_BASE_URL`/`LABTUTOR_LLM_API_KEY`/`LABTUTOR_LLM_MODEL`
   at Vertex's OpenAI-compatible endpoint and run one real request
   through `/api/chat/messages` end-to-end before trusting it for load
   testing. If Vertex's auth model (service-account/IAM token, not a
   static bearer key) doesn't fit `HostedBackend`'s
   `Authorization: Bearer {api_key}` header as-is, that's a small,
   contained change to `HostedBackend.complete()` — not a new backend
   class — since the request/response shape should already match.

3. **Load testing**: `infra/loadtest.py` already exists and was never
   run against a real provider (no credentials, every prior session).
   `docs/handoff_phase3.md`'s "Recommended load-test plan" section
   (bottom of that file) is a full, still-valid, not-yet-executed plan —
   read it before re-deriving one. Do this against the real Vertex AI
   endpoint once step 2 is confirmed working, not against local Ollama
   (see the live-verification note above for why Ollama on a shared dev
   box is not a meaningful latency proxy). Also worth re-checking once
   real load is possible: the router adds **one extra LLM round-trip per
   turn** to the common case (versus the old keyword-only dispatch) —
   confirm this is an acceptable cost at pilot scale, or consider
   `LABTUTOR_ROUTER_ENABLED=false` as an immediate lever if it isn't.

4. **Deploy**: not started. `infra/docker-compose.yml` + the CI
   `compose` job (validates config, checks no `.env` is committed) are
   the only deployment-adjacent pieces that exist; no actual deployment
   target/CD pipeline has been set up.

## Environment gotchas (still true, repeating from phase3 since they bit
this session too)

- This machine runs very low on free memory basically continuously —
  `free -h` regularly showed under 500Mi free this session, and the
  backend/frontend background processes were killed by memory pressure
  multiple times mid-session (unrelated apps: Chrome, VSCode helpers,
  other Claude sessions, ClickHouse, Logflare/Erlang — not this app).
  Check `free -h` before starting either process; if killed, just
  restart both (`backend.log`/`frontend.log` under
  `/tmp/claude-1000/browser_verify/` this session, but that's a scratch
  path from this session specifically, not a repo convention).
- A separate, long-running `ollama runner` process for an unrelated
  model has been observed pinned at 90%+ CPU for hours at a time on this
  same machine across multiple sessions now. This starves the actual
  Ollama model this app talks to. Worth root-causing/killing
  independently of this codebase if local Ollama testing needs to be
  reliable again.
- `next build` without `BACKEND_INTERNAL_URL` set silently produces a
  build with no `/api/*` rewrite (baked in at build time). Always
  `BACKEND_INTERNAL_URL=http://127.0.0.1:<port> npx next build` before
  `next start` for any live check.
