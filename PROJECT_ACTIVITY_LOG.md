# Project activity log

Running record of significant changes: what was wrong, why, what was decided,
and how it was verified. Newest entry first.

---

## 2026-10-08 — Exp7: student-facing replies are English only

### Bug

During manual Exp7 testing, the English question "Ok so for now I want to
first understand the concept behind this experiment before starting it" got a
reply in Romanized Hindi. The course deploys to students who should get
English only.

### Root cause

`backend/retrieval/pipeline.py` told the model to mirror the student:
`SYSTEM_PROMPT` said "reply in the language AND script the student wrote in
... Hinglish ... reply in the same Roman-letter Hinglish", and the dynamic
tail added "REPLY LANGUAGE: the same language AND script as the student
question below (Roman-letter Hinglish stays in Roman letters)". That was the
only instruction in any prompt that allowed a non-English reply; the exact
reason it fired on an English question was not reproduced (the model applies
"match the student" loosely). The other student-facing prompts
(`rag/phrasing.py`, `socratic_engine/chat.py`, `socratic_engine/realise.py`)
said nothing about language.

### Fix

- One shared `ENGLISH_ONLY_RULE` in `backend/rag/phrasing.py`: always reply
  in English whatever the student's language or script; never Hindi, Hinglish,
  Romanized Hindi or Devanagari; never mirror or switch on request; understand
  mixed-language input and answer in English; chemistry terms, software names,
  menu labels, file names and notation stay as the source writes them.
- Appended to all four student-facing system prompts. In `pipeline.py` it
  replaces the mirroring paragraph, and the tail line now reads "REPLY
  LANGUAGE: English only, whatever language or script the student question
  below uses." Grounding, scope, one-step, phone-only and injection rules are
  unchanged.
- Input handling is unchanged: `scope/normalize.py` still maps Hinglish to
  English for routing, and the walkthrough grader still accepts "haan",
  "theek hai", "kya" etc. as input. Only output language changed.
- Professor-facing prompts (summaries, Exp8 demonstrator note) and the router
  (classification only) were not changed.

### Temperature

Default `LABTUTOR_LLM_TEMPERATURE` 0.7 -> 0.3 (`config.py`, `.env.example`)
for consistent, instruction-following tutoring. It does not enforce English;
the prompt rule does. The OpenAI backend still never sends a temperature
(reasoning models reject non-default values), so this affects the Vertex,
hosted and Ollama paths only.

### Datasets

- `evaluation/exp07_dataset.json`: the 9 Hinglish cases (e07-02, -03, -05,
  -07, -12, -13, -17, -18, -19) rewritten as natural English questions with the
  same intent; language label `hinglish` -> `en_clean`. IDs, step index,
  category, expected intent and expected page unchanged.
- `golden_dataset/qa/exp07.json`: checked, all 170 questions already English
  (`language: english`); not modified.

### Tests

New `backend/tests/test_english_only.py` (11 tests, mocked backend, no network):
every student-facing prompt contains the rule and none of the old mirroring
phrases; the rule names Hindi/Hinglish/Romanized Hindi/Devanagari and forbids
switching; five Exp7 inputs (English, Hinglish, mixed, "Explain this in
Hindi.", "mujhe hinglish me explain karo") all reach the model with the rule
in the system prompt and "REPLY LANGUAGE: English only" in the user prompt,
and the mocked English reply reaches the student unchanged; default
temperature is 0.3. No word-list language validator was added.

### Results

Run with the local `.env` moved aside (it sets `GPT=true`, a real API key and
a different admin email, which leak into tests that expect defaults):

- English-only, Exp7 content, retrieval pipeline, theory-first,
  normalisation, golden QA and walkthrough API suites: 842 passed.
- Full suite: 2102 passed, 1 skipped, 16 failed. The same 16 fail on the
  unmodified tree (router x11 incl. `TestConversationalRouter`, context cache
  x4, OpenAI `max_completion_tokens` x1); none touch language.

Tier 1 computation, signatures, tolerances, the answer gate and walkthrough
grading were not changed.

---

## 2026-10-05 — Conversation flow, intent priority and per-chat state

Branch: `fix/conversation-flow` (worktree off `origin/master` @ `52b1d62`).

### Problems reported

1. A new chat opened at the step where the previous chat stopped.
2. Refusing a step ("I don't want to do this step, I want to study theory",
   "I don't want to draw") moved the student forward through steps 2, 3, 4.
3. Tapping "Give me a hint" returned a hint card that offered "Give me a
   hint" again; the same happened for "Why do this step?" and "Something
   looks different", producing an endless chain of identical cards.
4. "Something looks different" and "It's not working" repeated the step's
   instruction instead of troubleshooting.
5. "I don't have a menu" got an answer that assumed the menu existed.
6. There was no way to choose theory over practice; theory was only ever a
   side question inside the practical flow.

### Audit: where things live

| Concern | Location |
|---|---|
| Chat entry point and routing | `backend/api/chat_routes.py::send_message` |
| Exp7 guided walkthrough (pure state machine) | `backend/socratic_engine/walkthrough/controller.py` (`take_turn`) |
| Walkthrough persistence | `backend/socratic_engine/walkthrough/service.py`, table `walkthrough_progress` |
| Walkthrough intent matching (regex) | `backend/socratic_engine/walkthrough/grader.py` |
| Legacy numeric Socratic engine (other experiments) | `backend/socratic_engine/engine.py`, `chat.py`, table `socratic_sessions` |
| Safety triage | `backend/socratic_engine/triage.py` |
| Optional LLM router (off by default) | `backend/router/` |
| Grounded Q&A + system prompt | `backend/retrieval/pipeline.py` (`SYSTEM_PROMPT`, `answer_question`) |
| Action chips (generation) | `controller.py::_chips` / `_question_ui` |
| Action chips (rendering) | `frontend/components/MessageBubble.tsx` |
| Chat threads, new chat, message list | `frontend/components/ChatWorkspace.tsx`, `backend/api/chat_routes.py` thread routes |
| Client persistence | `localStorage` holds only the selected classroom id; no chat state |

### Root causes

1. **New chat resumes old workflow.** `walkthrough_progress` had a unique key
   on (student, classroom, experiment, actor_type), and the legacy
   `SocraticSession` was looked up by the same key. Workflow state was per
   student, not per conversation, so every new thread found the old row and
   continued it. The frontend was not at fault: `handleNewChat` really did
   create a new thread with no messages.
2. **Refusal advances.** The controller had no notion of refusal. "I don't want
   to do this step..." was graded as an answer to the current free-text
   question; it failed, counted as a wrong try, and the second wrong try took
   the "reveal and move on" path (`wrong_reveal` -> `_advance`).
3. **Recursive chips.** `_question_ui` always attached the full chip list
   (`_chips(q)`), including the chip that had just produced the reply. Nothing
   tracked which action produced a response or which actions had been used.
4. **"Something looks different" repeats the step.** It matched
   `grader.is_problem` (via the word "different") and replied with the
   authored `stuck` text plus the same question and the same chips. There was
   no troubleshooting state, so the student's follow-up description was graded
   as an answer to the step question.
5. **Hallucinated menus.** "I don't have a menu" matched no intent, so it was
   graded as a wrong answer or sent to the LLM as a plain question. The QA
   prompt also told the model to treat short replies as "done" and to give the
   next numbered step itself, so the model could narrate progress the state
   machine never made.
6. **No theory mode.** The only modes were "walkthrough engaged or not" per
   student per experiment.

### Decisions

- **One authoritative place per kind of state.**
  - Conversation mode (initial / theory / practice, previous mode, previous
    step, topic, clarification count, which Socratic session this thread
    owns) is stored in the new `chat_threads.state` JSON column, managed only
    by `backend/socratic_engine/conversation.py::ConversationState`.
  - Practical progress stays in `walkthrough_progress` (Exp7) and
    `socratic_sessions` (others), now linked to one thread
    (`walkthrough_progress.thread_id`, unique; `ConversationState.socratic_session_id`).
  - No new client-side store. The frontend holds no workflow state.
- **Intent before grading.** `conversation.classify()` runs before any
  answer is graded. It is deterministic (regex families, no model call),
  consistent with the CLAUDE.md rule that a model never decides progression.
  The LLM router remains optional and unchanged.
- **Only completion advances.** `_advance(completed=True)` is called only after
  a correct answer, a reveal, or a sanity-checked report. An explicit skip
  calls `_advance(completed=False)`: recorded in `skipped`, not counted in
  `steps_done`. Refusal, troubleshooting, hint, why and mode switches never
  call it.
- **Non-recursive actions as a policy, not special cases.**
  `conversation.actions(candidates, source=..., consumed=...)` drops the
  source action, anything with the same intent as the source, anything
  already used on the current question, and duplicates. Every chip list in
  the walkthrough and the mode replies goes through it, and each response
  carries `ui.action_context = {source_action, depth, suppressed}`.
- **Troubleshooting is a state.** `WalkState.troubleshooting` is set by a
  problem report. While it is set, a free-text message is a report for the
  grounded Q&A path (with the step's authored instruction as context), never
  a wrong try. It clears on "it works now", "Back to step", a correct answer,
  or a new question.
- **Old progress is offered, not loaded.** Rows created before this change
  (`thread_id` NULL), or an unfinished walkthrough in another chat, are only
  used when the student taps or types "Resume previous session".
- **Greeting is rendered by the frontend** for an empty thread, not stored as
  a message. That keeps transcripts, analytics and research exports free of
  synthetic tutor turns. The backend handles the first message in `initial`
  mode either way.

### Files changed

- `backend/socratic_engine/conversation.py` (new): intent classifier, action
  policy, `ConversationState`, greeting text.
- `backend/socratic_engine/walkthrough/controller.py`: intent-first handling,
  troubleshooting state, consumed actions, `_advance(completed=...)`, logging.
- `backend/socratic_engine/walkthrough/service.py`: per-thread lookup,
  pause/resume, "Resume previous session".
- `backend/api/chat_routes.py`: `_conversation_turn` (mode resolution before
  any workflow), thread-scoped Socratic session, theory mode suppresses the
  step machine, mode/intent in message metadata, `[CHAT]/[INTENT]/[STATE]`
  logs.
- `backend/models.py`: `ChatThread.state`, `WalkthroughProgress.thread_id`.
- `backend/migrations/versions/d6e7f8a9b0c1_scope_conversation_state_by_thread.py` (new).
- `backend/retrieval/pipeline.py`, `backend/socratic_engine/chat.py`: prompt
  rules for intent priority, refusal, troubleshooting and no invented UI.
- Tests: see below.
- Frontend: see below.

### Dependencies / tools

No new runtime dependencies. A local `.venv` (git-ignored) was created from
`backend/requirements.txt` because the system Python lacked `openpyxl`.

### Baseline before changes

`pytest` on `origin/master` @ `52b1d62`: 1868 tests, **11 failing**, 1 skipped.
All 11 are in `test_router.py` / `TestConversationalRouter`: they expect the
LLM router on, but commit `d305080` made `LABTUTOR_ROUTER_ENABLED` default to
false. With `LABTUTOR_ROUTER_ENABLED=true` the `test_chat_routes.py` ones
pass. Pre-existing, not touched by this change.

### Behaviour after the change

| Student says | Before | After |
|---|---|---|
| (opens a new chat) | continued the last chat's step | greeting with Theory / Study and Practical / Experiment; mode `initial` |
| "I don't want to do this step, I want to study theory" | graded as a wrong answer, then advanced | PRACTICE -> THEORY; walkthrough paused at the same step; topic and step remembered |
| "I don't want to draw" | wrong answer, then advanced | STEP_REFUSED: asks what they want instead; second time asks differently; never advances |
| "Give me a hint" | hint card offering "Give me a hint" again | hint; chips: Why / Something looks different / Continue; asking again gives "that was the only hint", no new hint card |
| "Why do this step?" | why card offering "Why" again | why; "Why" chip suppressed |
| "Something looks different", "It's not working" | repeated the step | troubleshooting state: asks what they see plus the authored tips; follow-up descriptions go to grounded diagnosis with the step's instruction; never a wrong try, never advances |
| "I don't have that option" | answered as if it existed | believed: "I won't assume that option is there", asks what they do see |
| "Okay, let's continue the experiment" (in theory) | n/a | THEORY -> PRACTICE at the same step |
| side question while the model says "Proceed to Step 4" | (the same) | state unchanged; only the controller moves steps |

### Deviations found while testing (and fixed)

- With `LABTUTOR_ROUTER_ENABLED=true`, a separate theory-mode Q&A branch skipped
  the router and broke 7 router tests. Theory mode now runs through the
  existing dispatch with the step machine suppressed, so the router keeps
  working (a router SOCRATIC decision in theory mode becomes a switch back to
  practice).
- Free-text answer keys are loose patterns (step 1's key accepts any word).
  While troubleshooting, "still nothing" and "it just doesn't open at all"
  counted as correct answers. Now, while troubleshooting, only a short,
  non-negative, correct free-text reply completes the step. "doesn't
  open/show/load" style phrases also classify as troubleshooting.
- From the live UI run: "Something looks different" stayed hidden for the
  rest of the step after one use. It is no longer marked as consumed, since a
  new problem can come up; it is hidden only on its own reply.

### Tests added

`backend/tests/test_conversation_flow.py`, 55 tests, covering all 20 requested
scenarios:

- intent classification for every phrase in the brief (parametrized), and chip
  text round-trips to its own intent;
- action policy: no source action, no equivalent action, no consumed action,
  no duplicates (TEST 18, 19);
- controller: refusal is STEP_REFUSED, not completion, and repeated refusal
  never advances (TEST 7, 14); explicit skip recorded as skipped; hint and why
  never re-offer themselves and repeated hints make no new hint card (TEST 8,
  9, 10); a depth-first walk over every chip from four step cards proves no
  self-loop, no reuse along a path and no step movement (TEST 20);
  troubleshooting state, reports, resolution, missing UI (TEST 11, 12, 13);
- API: new chat starts fresh with no inherited step or messages (TEST 1, 2, 3),
  a new chat does not reuse another chat's legacy Socratic session, greeting
  does not repeat the same menu, theory and practice entry (TEST 4, 5),
  practice -> theory keeps the step and context (TEST 6, 17), theory -> practice
  returns to the same step and "explain this" is expanded with the step topic
  (TEST 16), model prose cannot advance the state (TEST 15), troubleshooting
  over the API with one grounded model call (TEST 12), hint chip suppression
  over the API (TEST 8).

Existing tests updated, because they asserted the old per-student behaviour or
sent follow-ups without a `thread_id` (which creates a new chat):
`test_walkthrough_api.py` (now uses one thread per conversation;
`test_progress_is_stored_per_student_and_survives_a_new_thread` was replaced by
`test_progress_is_stored_per_thread_and_a_new_chat_starts_fresh`),
`test_product_journeys.py` (step attempt sent to the guidance thread),
`test_walkthrough_controller.py` (verdict `stuck` is now `troubleshooting`).

### Validation

| Check | Result |
|---|---|
| `pytest` (full suite) | 1923 tests: 1911 passed, 1 skipped, **11 failed**: the same 11 pre-existing router-default failures as baseline, none new |
| `test_conversation_flow.py` | 55 passed |
| `LABTUTOR_ROUTER_ENABLED=true pytest backend/tests/test_chat_routes.py` | all passed |
| CI steps: answer-gate invariant, golden dataset regenerate + `git diff --exit-code golden_dataset/`, load-test dry run | pass / unchanged / PASS |
| `pyflakes` on changed Python files | clean |
| `npm run typecheck` | clean |
| `npm run build` (Next 15) | success |
| Migration on Postgres 16 (Docker): upgrade with a legacy row, uniqueness per thread, downgrade (dedupe keeps newest), re-upgrade | all correct |
| Live run (uvicorn on SQLite + `next dev`, Playwright): greeting -> practice -> step 2 -> hint -> refuse -> something looks different -> theory switch -> back to experiment -> new chat | behaved as in the table above; `[CHAT]/[INTENT]/[STATE]` log lines present |

No ESLint config exists in `frontend/` (CI runs typecheck + build only), so
there was no lint step to run.

### Observability

INFO logs (no student message text, only ids and labels):
`[CHAT] conversationId=... mode=... previousMode=... previousStep=...`,
`[INTENT] detected=... previous=...`, `[STATE] PRACTICE(step=...) -> THEORY(topic=...) reason=...`,
`[STATE] step=... -> STEP_COMPLETED|STEP_SKIPPED`, `[INTENT] step=... -> ... consumed=[...]`.
DEBUG: `[UI ACTION] source=... depth=1 suppressed=[...]`. Each tutor message's
metadata also carries `mode`, `detected_intent`, and `ui.action_context`.

### Remaining limitations / notes for future developers

- Intent classification is deterministic regex families, not a model. It
  covers the phrasings in the brief and close paraphrases; unusual phrasing
  falls back to normal grading or the side-question path. If an LLM classifier
  is added later, it must only choose an intent, never decide completion.
- The rich step/hint/troubleshoot behaviour exists only where there is an
  authored step script (Exp7). Other experiments use the legacy numeric
  Socratic engine. Mode switching, per-thread scoping and the prompt rules
  apply there too, but its steps advance only on verified numeric data, so
  refusal could never advance them anyway.
- Free-text answer keys in `exp07_script.py` are permissive (step 1 accepts
  any word). Outside troubleshooting, a vague reply can still pass such a
  step. That is authored content and was left as is.
- Old walkthrough rows (`thread_id` NULL) are reachable only via "Resume
  previous session".
- The 11 router test failures predate this work. Fixing them means either
  setting the env in those tests or reverting the router default; that is a
  product decision, so it was not changed here.
- The greeting is shown by the frontend for an empty thread and is not stored
  as a message.
