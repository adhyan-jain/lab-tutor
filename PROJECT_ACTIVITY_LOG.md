# Project activity log

Running record of significant changes: what was wrong, why, what was decided,
and how it was verified. Newest entry first.

---

## 2026-10-08 — Exp7: a new question during a reflection is answered, not graded

### Observation

With a reflection pending ("**Think about this:** In your own words, what do
HOMO and LUMO stand for, and how do they differ?"), the student typed
"Compare B3LYP and B3P." LabTutor graded it as an answer to the reflection
(UNCLEAR, so a probe plus the advisory rephrasing call) and replied with
another reflection prompt instead of answering the question.

### Root cause

A message is only treated as a new question while a reflection is pending if
it starts with a wh/auxiliary word or contains "?" with 6+ words
(`conversation.classify` USER_QUESTION in `theory.handle_pending`;
`grader.is_side_question` in the walkthrough controller). An imperative
request with no question mark ("Compare B3LYP and B3P", "bhai B3LYP aur B3P
compare kar", "mujhe HOMO samjha") matched neither, so it fell through to
grading. Two related problems in the theory path:

1. A message that *was* recognised as a question deleted the pending
   reflection (`conv_state.pending = None`), and the follow-up opened after
   the answer then replaced it with a different question.
2. The USER_QUESTION check ran before grading, so a tentative answer such as
   "HOMO is the highest occupied molecular orbital, right?" (has "?", 6+
   words) was never graded.

### Routing design (deterministic, no new model call)

- `grader.is_new_request`: a clear new request is a wh-word or imperative ask
  at the start (what/why/how/..., explain, compare, contrast, describe,
  define, differentiate, distinguish, elaborate, summarise, clarify, tell me,
  teach me, can/could/would/will you), optionally after filler ("and", "so",
  "bhai", "please", ...), or a Hinglish ask anywhere ("... compare kar",
  "samjhao", "batao", "mujhe ... samjha", "kya hai/hota", "kaise", "kyun").
  Yes/no openers ("is it...?", "does...?") are deliberately excluded because
  they are usually tentative answers. "Just tell me" and "skip" are never new
  requests. No list of exact sentences; no question-mark rule on its own.
- Reflection pending, message arrives:
  1. A change of direction (switch to theory/practice, key-ideas session,
     procedure request) behaves exactly as before: the existing rule in
     `chat_routes._conversation_turn_phone` drops the follow-up.
  2. A clear new request is never graded. In theory mode
     `theory.handle_pending` returns None, so the message continues to the
     **existing** grounded Q&A branch (grounding, citations, English-only,
     overview focus, comparison format, answer gate, scope, phone-safe guard
     all unchanged). In a walkthrough concept moment or final reflection,
     `_turn_concept` / `_turn_assess` return the existing `side_question`
     result, which `chat_routes` already answers through the same Q&A path
     plus the existing "Back to my question" line.
  3. Anything else goes to the existing authored grading, unchanged. A
     weaker question signal (aux opener, or "?" with 6+ words) is only treated
     as a side question if grading matches nothing, so "HOMO is the highest
     occupied molecular orbital, right?" is graded.
- Preserving the reflection (theory mode): the pending reflection is no longer
  deleted by a new question. `theory.open_followup`, which runs after the Q&A
  answer, now sees the pending reflection and, instead of stacking a second
  question, appends "*Back to my question:* ..." **once** (a `reminded` flag on
  the pending dict); later unrelated questions get a plain answer. The
  reflection stays pending until answered, skipped, "just tell me", or a
  change of direction.

### Safety constraints preserved

- No model decides whether a message is an answer: routing is regex only, in
  `grader.py`, which still imports no LLM or retrieval code
  (`test_walkthrough_modules_import_no_model_or_retrieval_code` passes).
- Reflection answers stay on the authored grading path and reach no Q&A
  prompt; a correct answer costs zero model calls, as before.
- Only messages classified as new questions reach Q&A, through the path that
  already handled side questions; nothing new is sent to the realise/advisory
  call. A new question no longer triggers that advisory call at all.
- `test_student_text_stays_out_of_every_model_prompt` passes.
- No change to `chat_routes.py`, retrieval, prompts, citations, English-only,
  overview, comparison formatting, chemistry or Tier 1.

### Tests added (`backend/tests/test_reflection_routing.py`, 67 tests)

- Detector: 16 new-question phrasings (with/without "?", Hinglish, "And how is
  it different from LUMO?") are new requests; 8 reflection answers (incl.
  Hinglish and "..., right?") and 7 controls ("Just tell me", "Skip this
  question", yes, no, okay, haan, theek hai) are not.
- Theory follow-up: answers are graded against the pending question; new
  questions return to Q&A with the pending reflection unchanged and no
  grading evidence recorded; controls keep their verdicts; the reminder is
  shown once and the reflection is never replaced; a change of direction still
  drops it.
- Walkthrough concept moment: "Compare B3LYP and B3P", Hinglish and a
  HOMO/LUMO comparison are `side_question` with the moment kept; a real answer
  is still `concept_correct`.
- Real `/api/chat/messages` endpoint: a reflection answer follows the
  reflection path with zero model calls; "Compare B3LYP and B3P." gets one Q&A
  call, one "Back to my question", reflection preserved; a second question
  gets no repeated reminder; the student can still answer it afterwards;
  Hinglish request reaches Q&A with the English-only line; Fix #3 comparison
  format and Fix #2 overview focus still apply to questions asked mid-reflection.

### Validation

| Check | Result |
|---|---|
| `test_reflection_routing.py` | 67 passed |
| theory/walkthrough/phone-only/isolation/concept/pedagogy suites | all passed |
| Full suite, clean copy without local `.env` (2250 tests) | 16 failures, the **identical** set with and without this change (router-default + OpenAI provider tests) |
| Full suite in the working tree (local `.env` present) | same pre-existing env-dependent failures as before this change, plus `test_llm_unavailable_falls_back_to_extractive_answer`, which makes a live model call with the local key and does not touch the changed modules |

### Limitations

- Contextual follow-up: "And how is it different from LUMO?" is routed to Q&A
  correctly, but for Exp7 the Q&A prompt omits conversation history when the
  message is 7 words or fewer (`pipeline._generate_answer` `show_last`; the
  LASTMSG block is only emitted for Exp8), so "it" is not resolved from the
  previous turn. Left as is: changing prompt assembly is out of scope, and the
  routing fix does not widen any context.
- A clear new request is never graded, so an answer phrased as one ("what I
  think is ...", "explain: HOMO is ...") would go to Q&A. Rare; the student
  can re-answer and the reflection is still pending.
- "Explain the concepts involved..." mid-reflection is a switch to theory, so
  the existing change-of-direction rule drops the reflection (unchanged).
- While a theory reflection stays pending, no new follow-up is asked after
  later answers (one question at a time); answering or skipping it resumes
  normal follow-ups.

---

## 2026-10-08 — Exp7: structured, mobile-friendly comparison answers

### Observation

"How is HOMO different from LUMO" got a correct answer as one dense
paragraph (HOMO definition, behaviour, LUMO definition, behaviour, gap,
methane details). Students use LabTutor on phones, where a long paragraph is
hard to scan and the two things being compared blur together.

### Root cause

1. Nothing in the prompt asked for structure on a comparison; the system
   prompt and the phone-only line ask for prose.
2. `socratic_engine/theory.guard_answer` (Exp7 phone-only theory answers)
   split the answer into sentences *and lines*, and when it dropped any
   sentence naming software or a step it rejoined the rest with spaces. Any
   heading, bullet or paragraph break the model produced was flattened into
   one paragraph.

### Fix

- `is_comparison_request` in `retrieval/pipeline.py`: deterministic regex
  ("compare", "difference", "differ", "X vs Y", "different from/than",
  "how are ... different", Hinglish "fark"). A bare "different" ("why do
  different methods give different values") is not a comparison.
- When it matches, one `COMPARISON_FORMAT` line is added to the per-message
  prompt: a short bold-labelled section per item (full name for an
  abbreviation), 1-3 sentences or compact bullets each, then an
  "**In short:**" one-sentence takeaway. Tables only for several short
  attributes with few-word cells, so labelled sections are the default.
  Facts only from the material; length follows the question (a request for
  detail may be longer). No word limit. Nothing about HOMO/LUMO is hardcoded.
- A comparison is never also treated as an overview (Fix #2).
- `guard_answer` now filters line by line, keeping list markers, headings
  and paragraph breaks. Which sentences it drops is unchanged.
- `SYSTEM_PROMPT` is unchanged, so every non-comparison question gets
  exactly the prompt it had before; no global length change.

### Streaming vs final message (investigated, not changed)

`/messages/stream` sends the model's raw tokens as they arrive, then a
`done` event with the saved message, which the frontend shows in their
place. The saved text is post-processed after streaming: `pipeline`
strips leaked passage references and normalises markdown, `guard_answer`
drops software/step sentences for phone-only Exp7, an authored concept
explanation replaces it when the model reply was not usable, and a
follow-up/invite suffix is appended. So the streamed and final text differ
by design whenever any of those apply.

### Found, not changed

For Exp7, a message of `FOLLOWUP_MAX_WORDS` (7) words or fewer gets no
conversation context in the prompt: the LASTMSG block is built only for other
experiments, and HISTORY is skipped whenever LASTMSG would apply. Sending
HISTORY in that case breaks
`test_walkthrough_api::test_student_text_stays_out_of_every_model_prompt`,
which relies on walkthrough replies never reaching the model. Left as is;
it needs a decision on what history Exp7 may send.

### Tests

New `backend/tests/test_comparison_format.py` (38 tests): 11 comparison
phrasings detected (HOMO/LUMO variants, B3LYP vs B3P, 6-31G vs 6-31G*,
"how are these two basis sets different", Hinglish "bhai HOMO aur LUMO me
kya difference hai", follow-up "And how is it different from LUMO?"); 6
non-comparisons not detected ("What is HOMO?", "Explain HOMO in detail.",
"Why is HOMO important?", procedure, overview, "Why do different methods
give different values?"); comparison prompts carry the format line,
citations and the English-only rule, and no overview focus; non-comparisons
get no format line; the overview still gets its focus; the format line is
not in the global system prompt and has no word limit; `guard_answer` drops
a software sentence while keeping headings, bullets and breaks; a
structured answer survives the full chat API.

### Results

Run with the local `.env` moved aside. New tests plus English-only,
overview, theory-first, Exp7 content, retrieval pipeline, walkthrough API,
conversation flow, normalisation and golden QA suites: 961 passed. Full
suite: 2166 passed, 1 skipped, 16 failed, the same 16 pre-existing
failures, no new ones. Tier 1, the answer gate, walkthrough grading,
grounding, Fix #1 and Fix #2 behaviour unchanged.

---

## 2026-10-08 — Exp7: concise answers to broad concept-overview requests

### Observation

In manual Exp7 testing, "Explain the concepts involved in this experiment
before I start" got a correct, grounded, but very long answer that restated
most of the material (workflow, optimisation, single point, HOMO/LUMO, DFT,
basis sets, orbital contributions, electron counts, methane/oxygen). Other
Exp7 questions were sized fine.

### Root cause

The message is classified `switch_to_theory` and answered by
`retrieval/pipeline.py`. For Exp7 the pipeline hands the model the whole
experiment's material (about 62k characters, 67 passages; deliberate, for
grounding and context caching). The per-message FOCUS line for this question
was "lead with the official procedure", since it is not scope-level ADJACENT.
The system prompt's length rules cover "what is X" (90-130 words) and
"answer every part of a multi-part question", but nothing covers a broad
overview, so the model treated all the supplied material as what to cover.

### Fix

- `is_overview_request` in `pipeline.py`: deterministic regex for broad
  requests ("concepts involved/behind/before I start", "basic/key concepts",
  "overview", "what is this experiment about", "theory behind this
  experiment", Hinglish "concepts samjha do"). A request for detail, a
  comparison or the procedure is never an overview, and nor is a short
  follow-up.
- When it matches, the per-message FOCUS becomes `OVERVIEW_FOCUS`: the
  material is supporting evidence, not a checklist; one intro sentence, the
  4-6 concepts that matter most at 1-2 sentences each, no procedure,
  settings, numbers or output details, about 150-250 words (soft target),
  and one closing sentence inviting detail. In phone-only mode that closing
  sentence is allowed as the one exception to "do not end with an offer".
- `SYSTEM_PROMPT` is unchanged, so every other question gets exactly the
  prompt it had before and the cached Exp7 context fingerprint is
  unaffected. No new model call, no truncation, the same material and
  citations as before.

### Tests

New `backend/tests/test_concept_overview.py` (26 tests): 7 overview
phrasings (including Hinglish) detected; 8 non-overview phrasings ("What is
HOMO?", "Explain HOMO and LUMO in detail and compare them.", "Walk me through
the complete Experiment 7 procedure.", "Explain all the concepts in detail.",
etc.) not detected; the overview prompt still carries the full Exp7 material
(>20k chars), citations, the English-only rule and the OVERVIEW focus, and
drops "lead with the official procedure"; detailed, specific and follow-up
questions do not get the overview focus; the rule is absent from the global
system prompt; through the chat API an overview request reaches the model
with the overview focus and a procedure request does not.

### Results

Run with the local `.env` moved aside. New tests plus theory-first, Exp7
content, retrieval pipeline, walkthrough API, conversation flow,
normalisation, English-only and golden QA suites: 923 passed. Full suite:
2128 passed, 1 skipped, 16 failed: the same 16 pre-existing failures listed
in the entry below, no new ones. The golden dataset and evaluation dataset
were not changed. Tier 1, the answer gate, walkthrough grading and the
English-only rule were not changed.

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
