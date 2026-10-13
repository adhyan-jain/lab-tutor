# Project activity log

Running record of significant changes: what was wrong, why, what was decided,
and how it was verified. Newest entry first.

---

## 2026-10-13 — Vague openers: "I don't know what to ask", bare "what is this?"

### Inspection findings

Most of the brief already shipped in `fb2e072` (shared persona, difficulty
kinds with per-kind strategy, authored starters, next-step and support chips,
hint-before-reveal in quizzes, pause/resume, English-only gate, practical
tracker). Remaining gaps found:

- "I don't know what to ask" matched the *uncertain* difficulty pattern and
  went to the model as if it were a failed answer.
- A bare "what is this?" / "explain this" / "why?" in a new chat reached the
  model with nothing to point at; with a previous tutor reply there was no
  instruction to explain *that* rather than ask for clarification.
- Next-step chips could repeat a question the student had already asked.

### Changes

- `socratic_engine/conversation.py`: `is_lost`, `is_bare_referent`, authored
  `lost_text` (three rotating openers) and `referent_clarify_text`. Deterministic.
- `api/chat_routes.py`: `_vague_opening`, called first in `_conversation_turn`.
  Authored orientation plus up to three of the experiment's own starter
  questions the student has not already asked, as ordinary chips (sent as
  normal messages, never graded). Skipped during a guided session or a pending
  follow-up. Next-step chips drop anything already in the thread.
- `retrieval/pipeline.py`: `REFERENT` line when a bare referent follows a tutor
  reply: explain that message's main idea simply, do not ask what "this" means.
  Difficulty kinds still take priority.

No change to Tier 1, grading, walkthrough state, auth, rate limits or the
English gate. No extra model call for either new path.

### Tests

New `backend/tests/test_vague_openers.py` (22): detection and non-over-matching,
English authored text, and end to end (scripted model): lost student gets
starters, bare "what is this?" in a new chat clarifies with chips, an
already-asked starter is not offered again.

Backend (local `.env` moved aside, `-o addopts=""`): 2512 passed, 1 skipped,
17 failed. The 17 are the same pre-existing failures as the previous entry
(`test_chat_routes` x7, `test_router` x4, `test_context_cache` x4,
`test_openai_provider` x1, `test_research_export` x1). Frontend untouched, so
typecheck/build were not re-run.

### Limitations

- Viva practice ("Test my understanding") still exists only for Exp7: it needs
  an authored key per experiment, and grading must not be a model call. Other
  experiments need authored viva content before this can extend.
- Detection is a pattern list; unusual phrasings fall through to normal Q&A.
- Model-written warmth was not sampled live (no paid calls).

---

## 2026-10-11 — Compassionate tutoring, struggle-aware teaching, concise steps, temperature 0.5

### Inspection findings

- Student-facing generation goes through four system prompts (Q&A pipeline,
  diagnosis phrasing, Socratic hints, Exp7 concept tutoring); quiz feedback
  is authored text in `walkthrough/controller.py`. None described a tutoring
  personality.
- In a quiz, "I don't know" / "no idea" matched the "just tell me" pattern
  and revealed the answer at once (`Here is the short version: ...`): the
  exact behaviour the brief calls bad.
- Struggle was only partly recognised (my earlier `is_confused`); the Q&A
  path had no strategy change for "I still don't get it", and for Exp7 a
  short follow-up reaches the model with no context, so it could not avoid
  repeating itself.
- Temperature: config 0.3; Vertex, hosted and Ollama send it; the OpenAI
  backend sent no temperature at all. The configured model `gpt-5.6-luna` is a
  reasoning family, whose API rejects a non-default temperature.
- Practical steps: the one-step rule said "2 to 4 short sentences" and "give
  all [dialog settings] in that one step", which invited inline explanations of
  every ORCA keyword.

### Changes

- `rag/phrasing.py`: shared `TUTOR_PERSONA` (patient senior-to-junior
  voice; warmth matched to the moment, none on ordinary factual questions;
  change approach instead of repeating; varied wording; honest, never calling
  a wrong answer right or claiming unshown mastery; direct answer when asked;
  pausing respected; emojis at most rarely). Appended to all four prompts,
  next to the English-only rule. No extra model call.
- `socratic_engine/conversation.py`: `difficulty_kind` (uncertain /
  confused / repeat / overwhelmed / frustrated) for short messages about the
  student, English, Hinglish and Devanagari; ordinary questions, answers and
  "thanks" are not matched, and messages over 14 words never are.
  `is_pause_request` ("I want to pause", "can we stop for now", "let's take a
  break") pauses like the Pause chip.
- `retrieval/pipeline.py`: a per-message `SUPPORT` line per difficulty kind
  (e.g. "repeat": do not repeat your last explanation, use a different
  approach; "overwhelmed": one manageable starting point only). For anything
  but plain uncertainty, the tutor's own last message is supplied so it can
  avoid repeating itself (tutor text only, no student turn added). Practical
  steps: the action in 1-3 short sentences, no inline explanation of
  keywords, a required keyword line once in its own code block and not
  repeated, keywords explained when asked or when a mistake is likely.
- `walkthrough/controller.py`: struggle (including "I don't know") is
  handled before the reveal: first a reassuring opener, the concept in simple
  terms and an easier way into the same question, ungraded; if it still has
  not clicked, the reasoning worked through. Explicit "just tell me" still
  reveals. Openers are authored, honest and rotated (`_UNSURE_OPENERS`,
  `_MISCONCEPTION_OPENERS`, `_PARTIAL_OPENERS`, `_STRUGGLE_OPENERS`); a
  concept's lab note is added only if it passes the phone-safety gate.
  Pinned phrases ("come at it another way", "Here is the short version") are
  kept inside the new wording.
- `api/chat_routes.py`: a pause request gets "Of course, let's pause here"
  and keeps the session (Resume chip); a struggling student in theory Q&A gets
  help and two support chips ("Explain <concept> more simply", "... with a
  simple example") instead of another reflection question.
- `socratic_engine/theory.py`: `support_chips`.
- `llm/client.py`, `config.py`, `.env.example` (and the local `.env`):
  temperature 0.5 from `LABTUTOR_LLM_TEMPERATURE`. OpenAI now sends it, in
  both the streaming and non-streaming request, unless the model is a
  reasoning family (o1/o3/o4/gpt-5*), via `openai_accepts_temperature`.
  Vertex, hosted and Ollama already sent it.
- `tests/test_english_only.py`: the default-temperature assertion follows the
  new product setting (0.3 -> 0.5).

No frontend change was needed: chips use the existing rendering.

### Tests

New `backend/tests/test_compassionate_tutoring.py` (77): the persona is in
all four prompts with the English rule; 19 difficulty phrasings (English,
Hinglish, Devanagari) recognised and 8 ordinary messages not; pause wishes;
cases 1-20 of the brief: "I don't know" normalised with a next step, wrong
answers corrected without praise, partial acknowledged, repeated confusion
switches to a worked explanation, overwhelm/frustration slow down ungraded
with Pause offered, direct answer respected, repeated wrong answers change
strategy, unrelated question keeps the quiz, plain factual question gets no
SUPPORT line, each struggle kind gets its strategy, "explain again" sees the
last explanation and no student turn, manual grounding and general-knowledge
labelling intact, supportive replies streamed and saved in English for
English/Hinglish/Devanagari/"in Hindi" (Hinglish first draft), no reflection
stacked on a struggling student, pause keeps and resumes the session, help
during an Exp8 practical never advances it, concise-step rules, OpenAI
temperature sent for gpt-4o and not for gpt-5.6-luna (streaming and not),
central setting used, no overpraise of a correct answer.

### Results

Backend via the guarded `.env` wrapper: full suite 2490 passed, 1 skipped, 17
failed: the same 17 as clean `master`. (An intermediate run showed 4 new
failures from tests that build `OpenAIBackend` without `__init__`; the helper
now falls back to the central setting.) Related suites: 1006 passed before
the last wording fix, then the affected files re-run green. Frontend
unchanged this round.

Representative authored replies were printed and read: "I don't know" ->
"No problem at all, that's what we're here for." + simple terms + easier way
in, then the worked reasoning; "This is too difficult." -> "That's fair, there
is a lot here. Let's take just one small piece."; repeated wrong answers ->
scaffold, then "Let's walk through it together".

### Limitations

- The configured OpenAI model (gpt-5.6-luna) is a reasoning family, so it
  receives no temperature; 0.5 reaches gpt-4o-style models, Vertex, hosted and
  Ollama. Tone there rests on the prompt, as intended.
- Model-written tone was not sampled live (no paid calls); its behaviour is
  steered by the persona and SUPPORT lines and checked by prompt contract,
  while authored quiz feedback was checked directly.
- Difficulty detection is a pattern list; unusual phrasings fall through to
  normal handling.
- "I give up" counts as frustration first (support, then the worked answer on
  a second struggle message), not an immediate reveal.

---

## 2026-10-11 — Practical wording, stricter English check, adaptive follow-ups, practical tracker

Builds on the entry below (same day, same uncommitted tree).

### Inspection findings

- The "the manual does not specify the exact Avogadro menu path" wording (an
  Exp8 chair-conformer step) came from two answering-prompt rules in
  `retrieval/pipeline.py` that told the model to "say plainly what the lab
  material does not spell out" and, when a control's location is unknown, to
  "say so once, plainly". Two authored lines in `walkthrough/exp07_script.py`
  said the same ("The manual does not say ...").
- The language backstop needed two distinct Roman-Hindi words, so natural
  Hinglish such as "Geometry optimization karne se molecule ki energy minimum
  hoti hai" (one such word plus particles) passed.
- An adaptive engine already exists and is deterministic: authored questions
  with regex answer keys, CORRECT/PARTIAL/MISCONCEPTION/UNCLEAR, a concept
  state machine (UNKNOWN..MASTERED), question type chosen from the state,
  probe/scaffold/explain follow-ups, skip, "just tell me", side questions
  answered by Q&A with the question kept, pause (switching to theory) and
  resume. It has authored content for Exp7 only. Gaps: no harder question after
  a correct answer, confusion graded as a wrong answer, no hint or example
  handling inside a question, pause/resume not offered as actions.
- Practical state: numeric experiments advance a SocraticSession only on
  verified data. Exp7/Exp8's step machine never advances by design
  (ARCHITECTURE 2.1.1); Exp8's practical is taught by the model counting
  "Step N" in its own text, with no backend progress. Exp7 in phone-only mode
  (the default) has no practical steps. No tracker existed.

### Changes

Practical wording (no change to sequence or grading):

- `pipeline.SYSTEM_PROMPT`: a gap is now handled as guidance ("you will read
  this from your output", or one natural line pointing to the lab
  instructor), with an explicit ban on saying "the manual does not specify";
  for an unknown control location the step is still given as far as the
  material supports, then "If you need help finding the right tool, ask your
  lab instructor." The bans on inventing menu paths, button names, numbers or
  facts are unchanged.
- `exp07_script.py`: the two authored lines now point to the lab instructor
  without mentioning the manual.

English-only:

- `rag/language.py`: unambiguous Roman-Hindi words (list extended), plus the
  particles ka/ki/ke/se/ko/ne, which count only next to such a word (so "Ka",
  "Ne" and "se" in English chemistry are never enough). Flagged: Devanagari,
  two distinct words, or one word plus two particles. Checked against all 114
  paragraphs of the manual and the Exp7 material: no false positive. The same
  function drives the stream gate, the corrective retry and the fallbacks, so
  every path gets the stricter check.

Adaptive follow-ups (existing engine, still no model decision):

- `pedagogy/policy.py`: `LEVEL` maps the authored question types onto
  recall (OBSERVATION) -> understanding (WHY) -> application (PREDICTION,
  CONSEQUENCE) -> analysis (INTERPRETATION, TRANSFER); `deeper_question`
  picks the next unasked question on the same concept one level up.
- `walkthrough/controller.py` (`_turn_concept`): a full CORRECT answer (all
  required ideas, not a keyword or an option) in the guided key-ideas session
  earns one harder question on the same idea, once per moment, never during
  software steps or theory follow-ups; a hint request gives the authored
  scaffold once without counting a miss; "I'm confused / I don't understand /
  I'm stuck / samajh nahi aaya" gives the concept's authored description and
  an easier way into the same question, ungraded; "Show an example" is
  answered by grounded Q&A with a concept-named question (`side_query`) and
  the question stays pending. Chips are contextual: hint (until used),
  example, just tell me, skip, and Pause in a guided session.
- `walkthrough/grader.py`: `is_confused`, `is_example_request` (requests,
  not answers that say "for example").
- `conversation.py`: Pause / "pause the quiz" / "end the session" pause the
  session (never complete it); "Resume the key ideas" / "resume quiz" resume
  it. Bare "stop" and "exit" are unchanged.
- `api/chat_routes.py`: the paused reply offers "Resume the key ideas";
  side questions and theory-mode example requests use the concept-named
  query (`theory.example_query`).

Practical progress tracker:

- `socratic_engine/practical.py` (new): steps come from each experiment's own
  authored, manual-confirmed StepSpecs. "verified" experiments (numeric):
  progress is read from the thread's SocraticSession and moves only when the
  engine verifies data. "self_report" (Exp8, and Exp7 outside phone-only):
  the backend records a completion for the current step only, in the thread's
  `ConversationState.practical_done`; a duplicate, stale or out-of-order
  request is refused (409) and changes nothing. Exp7 in phone-only mode has
  no tracker.
- `api/chat_routes.py`: `GET /api/chat/threads/{id}/practical` and
  `POST .../practical/complete` (owner-only; verified experiments refuse a
  self-reported completion). No new table.
- `frontend/components/PracticalTracker.tsx` (new), `ChatWorkspace.tsx`,
  `lib/api.ts`, `globals.css`: a compact strip ("Step 2 of 4 · Ethane
  energies") that expands to done / now / next with three actions. "I've
  completed this step" posts (self-report) or sends the message through chat
  (verified); "Explain this step" and "I'm stuck" are chat messages naming
  the step. The strip shows only what the backend returns, re-reads after
  every reply, and is per thread.

Quiz state (`walkthrough_progress`, `ConversationState.pending`) and
practical state (`practical_done`, SocraticSession) are separate fields; no
code path writes both.

### Tests

- `backend/tests/test_adaptive_and_practical.py` (new, 38): ladder covers
  all types; deeper questions are same-concept, higher, unasked; a full
  session answered well completes, goes deeper at least once and never twice
  in a row; partial -> scaffold, no mastery; wrong -> probe, then explain;
  hint once, then a second attempt; five confusion phrasings simplified and
  ungraded; example -> Q&A with the question kept; unrelated question not
  graded; contextual chips; theory follow-ups never chain; pause/resume
  phrasings; all authored adaptive text English; pause -> unrelated question
  -> resume returns to the same question (API); tracker steps per experiment,
  states, accept/duplicate/out-of-order/complete, refresh, thread scope,
  ownership (404), experiment switch, chat messages never advance it,
  verified experiments refuse self-report, quiz and practical independent,
  tracker text English.
- `backend/tests/test_student_feedback.py` (+16 since the entry below): the
  practical wording rules, no "manual does not" in authored text, the five
  language cases streamed and saved English for Exp7 and Exp8 (Exp8 asserts
  the retry ran), an English practical step unchanged, natural Hinglish and
  "ka ... se" flagged, "Ka"/"Ne" and B3LYP/B3P/CH4/O2 text not flagged.

### Results

Backend (local `.env` moved aside by a wrapper that refuses to start without
it and always restores it; see "Note" below): full suite 2413 passed, 1
skipped, 17 failed -- the same 17 that fail on clean `master` (router x4,
chat_routes router-default x7, context cache x4, OpenAI provider x1,
research export x1). No new failures. Tutoring suites (concept moments,
realise, walkthrough controller/API, conversation flow, reflection routing,
theory-first, phone-only, pedagogy): 413 passed before the new file.

Frontend: `tsc --noEmit` clean, `next build` succeeds. Playwright against the
production build, Chromium and WebKit: tracker 130 checks pass (320-1280px,
no overflow, collapsed by default, states, accept, refusal leaves it
unchanged, verified completion goes through chat, re-read after a reply,
explain/stuck, hidden without a practical, quiz chips); the earlier 122
feedback checks and 39 functional checks still pass.

Note: an interrupted test run had left `.env` moved into the session's
scratch folder; it was restored byte-identical to the last known-good copy
before any further work, and all later runs use the guarded wrapper.

### Limitations and follow-up

- Adaptive questions exist only where questions are authored (Exp7). Exp8
  has no knowledge module, so no Exp8 quiz; adding one means authoring
  concepts, questions, answer keys and misconceptions for ethane/cyclohexane
  and making the controller experiment-generic (it loads Exp7 directly).
- Exp8 "completed" is the student's report, not verification; the model's
  own "Step N" wording in Exp8 replies is not tied to the tracker.
- Tracker step titles are the authored step keys ("Ethane energies",
  "Delta g"), not separately written titles.
- The tracker appears once a thread exists (after the first message).
- A completion tapped while a reply is being generated could be overwritten
  by that turn's state save; the UI disables the button while sending.
- The language check is still a heuristic, not a guarantee.

---

## 2026-10-11 — Live-demo feedback: English output, discoverability, interactivity

### Student feedback (first live demo, about 70 students)

1. Replies sometimes appeared in Hindi/Hinglish, "particularly when network
   issues occur".
2. Students did not know what they could ask.
3. They wanted the tutor to feel more interactive.

### Findings (audit of the current tree, branch `master` @ `6533db8`)

Already present and working: a shared `ENGLISH_ONLY_RULE` on the four
student-facing prompts (Q&A pipeline, diagnosis phrasing, Socratic hints,
Exp7 concept tutoring); a deterministic backstop `rag/language.looks_non_english`
on the pipeline, Socratic hints and concept tutoring; temperature 0.3;
overview, comparison and reflection-routing fixes with their tests; the mobile
UI. No language-mirroring instruction remains anywhere.

Gaps found:

- **Root cause of "Hinglish with network issues".** The English check ran on
  the *final* text only. With streaming, the student watched a Hinglish draft
  arrive token by token; the server then replaced it with the extractive
  fallback, whose lead is "I couldn't put together a full explanation just
  now ... Please ask again in a moment". The student saw Hinglish followed by
  what reads as a network failure. Real provider failures fall back to English
  text (extractive or authored), so the network was not the cause; the
  correlation came from that wording. No demo data is in the local database
  (19 local messages), so this is established from the code path, not from
  logs of the demo.
- Diagnosis phrasing (`rag/phrasing.validate_output`) had no English check.
- An internal stream error sent `str(exception)` to the student.
- A phone that loses signal mid-stream can hang the request forever; a
  dropped connection showed raw browser text ("Load failed") and restored the
  question even when the server had already saved the reply (resending it
  duplicated the Q&A).
- A Devanagari question in a new Exp7 chat got the greeting: the "too short,
  greet" check counted Latin tokens only.
- Discoverability: the empty chat offered only Theory/Practical buttons.
- General chemistry: a real-world question ("Where is methane commonly used?")
  reached the model, but the system prompt forbids any fact not in the
  passages, so it could only say the manual does not cover it.
- Interactivity: Exp7 theory answers already end with one authored reflection
  question (`theory.open_followup`); "quiz me" / "test my understanding"
  already start the deterministic key-ideas session. Neither was visible.

### Changes

Language (no extra model call on a normal answer):

- `rag/language.py`: more unambiguous Roman-Hindi function words;
  `EnglishStreamGate` holds back the first 48 characters of a stream, then
  forwards text until the text so far looks non-English, after which nothing
  more is forwarded and one `reset` event is sent if anything was shown.
- `api/chat_routes.py`: the SSE endpoint runs every stream through the gate;
  internal errors become a fixed English `STREAM_ERROR_DETAIL` (the exception
  is logged).
- `retrieval/pipeline.py`: a non-English reply gets one corrective retry
  (not streamed, "LANGUAGE CORRECTION" line); if that also fails, the English
  extractive fallback with a neutral lead ("Here is the most relevant part of
  the lab material for your question.") instead of the "just now" outage text.
- `rag/phrasing.py`: `validate_output` rejects a non-English diagnosis
  (template used); the shared rule now names headings, labels, summaries and
  follow-up questions.
- `api/chat_routes.py`: the new-chat greeting check counts words in any script.

Reliability (frontend, existing retry framework untouched):

- `lib/api.ts`: 90 s inactivity watchdog on the reply stream (AbortController,
  reset on every chunk); network failures become `ApiError(0, ...)` with plain
  English text; `reset` event type.
- `ChatWorkspace.tsx`: `reset` clears the draft back to the typing indicator;
  after a connection error the thread is reloaded and, if the server saved
  the question and its reply, they are shown instead of offering a resend.

Discoverability and interactivity:

- `knowledge/types.py`, `knowledge/exp07.py`: authored `starter_questions`
  (7 for Exp7). `socratic_engine/suggestions.py`: per-experiment starters
  (generic ones where none are authored) and whether the guided key-ideas
  session exists. `api/classroom_routes.py`: both returned with the
  experiment catalogue (no extra request).
- `ChatWorkspace.tsx` empty state: "What would you like to learn?", four
  starter questions (full-width rows on phones, chips on desktop), then
  "Or choose how to learn": Theory/Study, Practical/Experiment and, where
  supported, "Test my understanding". Every button sends a normal message.
- `theory.next_step_chips` + `chat_routes`: an Exp7 theory answer that
  carries no reflection offers "Explain <concept> with a simple example",
  "How does this experiment use <concept>?" and "Test my understanding". Each
  names the concept (short Exp7 follow-ups reach the model without history)
  and reads as a new request, so it is never graded against a pending
  reflection. An answer with a reflection keeps only the reflection.

General chemistry knowledge:

- `pipeline.is_general_knowledge_request`: real-world / everyday / uses /
  applications / "example of" questions, excluding anything about this
  experiment's own software, steps, settings or output. Those get a
  `GENERAL_KNOWLEDGE` line: established textbook knowledge allowed, labelled
  once as general knowledge, never attributed to the manual, no uncertain
  numbers. The system prompt's grounding rule is unchanged except for naming
  this one exception. `AnswerResult.general_knowledge` -> message metadata ->
  a small "Includes general chemistry knowledge, not from the lab manual"
  note in `MessageBubble.tsx`. Citations still list only the material
  actually supplied.

No new dependency. No change to Tier 1, grading tolerances, the answer gate,
walkthrough grading, authentication, rate limits or idempotency.

### Datasets

- `evaluation/exp07_dataset.json`: 14 cases added (e07-35..e07-48), same
  schema plus the existing optional `notes`: Hinglish, Devanagari and mixed
  inputs (kept on purpose: the rule is about output), explicit requests for a
  Hindi/Hinglish reply, direct, detailed, comparison, real-world, guided,
  understanding-check and follow-up-chip wording. Existing cases untouched.
- `golden_dataset/category6_student_questions/cases.json`: new group
  `c6j-multilingual-and-learning-requests` (11 questions), registered in
  `test_student_questions.GROUP_EXPECTATIONS`, so every question runs through
  the existing reply/outage/triage invariants.

### Tests

New `backend/tests/test_student_feedback.py` (60 tests, scripted model, no
network): chemistry English and the whole Exp7 material are not flagged;
Hindi/Hinglish/Devanagari are; the stream gate passes English through
byte-for-byte, resets a draft that turns Hinglish, never shows Devanagari,
flushes a short reply; a Hinglish reply is retried once and the English one
wins; English costs one call; two violations give the neutral English
fallback; a real outage still says so; six multilingual inputs end in
English; diagnosis phrasing rejects Hinglish; end to end over SSE: reset sent
and the draft never continues, Devanagari never shown, English stream
unchanged, a mid-stream failure still ends in an English saved reply, an
internal error shows the fixed English text and no exception detail;
catalogue carries starters and guided availability; every Exp7 starter is
answered through the normal path (comparison format and general-knowledge
flag where expected); generic starters work for exp01; next-step chips are
new requests, keep a pending reflection, appear only when no reflection is
attached; a direct question is not turned into a quiz; "Test my
understanding" starts the existing session with no model call; general-
knowledge detection, prompt line, flag, unchanged grounding rule, no label
without a model answer.

### Results

Backend, with the local `.env` moved aside (it sets `GPT=true` and a real
key, which leak into tests that expect defaults):

- Full suite: 2355 passed, 1 skipped, 17 failed. The unmodified `master`
  (fresh worktree, same command) gives 2262 passed, 1 skipped and the same
  17 failures: `test_chat_routes` x7 and `test_router` x4 (router default),
  `test_context_cache` x4, `test_openai_provider` x1, and
  `test_research_export` x1 (new on master since the last entry). No new
  failures.
- Related suites (English-only, overview, comparison, reflection routing,
  theory-first, Exp7 content, retrieval pipeline, walkthrough API,
  conversation flow): 317 passed before the new tests were added;
  `test_student_questions.py`: 401 passed.

Frontend: `tsc --noEmit` clean, `next build` succeeds. Playwright against the
production build with a mocked `/api`, Chromium and WebKit: 122 checks pass
(empty state at 320-1280px with no overflow, 44px starters, composer visible,
light theme, starter click sends, exp01 generic starters, `reset` handling,
dropped connection with and without a saved reply, server error text,
general-knowledge note, chips send their text) and the earlier 39 functional
checks still pass.

### Limitations

- The language check is a heuristic: Devanagari, or two distinct
  unambiguous Roman-Hindi function words. A Hinglish reply avoiding those
  words would pass; it is not a guarantee.
- The first 48 characters of every streamed reply are held back (a fraction
  of a second). A violation found after text was shown causes one visible
  reset back to the typing indicator.
- A corrective retry adds one model call, only when a reply fails the check.
- General-knowledge answers rely on the model keeping to established facts;
  they are labelled, never cited to the manual, and only enabled for
  real-world/application questions.
- Exp7 still sends no conversation history for messages of 7 words or fewer
  (see the comparison-format entry); the chips name their concept for that
  reason.
- Not tested on a physical phone; the 90 s watchdog was tested by aborting
  requests, not by a real signal loss.

---

## 2026-10-08 — Mobile-first redesign of the student chat UI

Frontend only. No backend, prompt, retrieval, API or chemistry change.

### Audit (baseline, rendered at 320-1280px)

- Header crammed into a narrow column: title cut to "Build...", classroom
  name over three lines, P0+ badge, session pill and Light button competing.
- Drawer looked like a desktop sidebar; Escape did not close it; it stayed
  focusable when closed; the theme toggle was only in the header.
- Thinking state was an empty bubble containing only "Copy".
- Composer: two-line textarea plus a separate text "Send" button.
- Most chat styling was inline, so phone rules needed `!important`.
- No page-level horizontal overflow at any width (kept that way).

### Architecture

One responsive layout, no second mobile app. Desktop keeps the fixed
sidebar; at <=768px the same `<aside>` becomes an off-canvas drawer. The
inline styles of `ChatWorkspace` and `MessageBubble` moved into classes in
the "Chat workspace" section of `globals.css`, replacing the old chat
`!important` overrides. `useNarrow()` (matchMedia) only picks the shorter
placeholder and marks the closed drawer `inert`.

### Changes

- Header (phone): menu button, `EXP07` code chip over a short title (first
  clause of the experiment title; the full title is on desktop and in the
  drawer), compact "Active"/"No session" status with a dot and text (not
  colour alone). P0+ badge, classroom line, Settings and theme toggle hidden
  on phones. About 56px plus the top safe area.
- Drawer: 86vw (max 340px), rounded right edge, blurred fading backdrop,
  eased slide, close button, Escape and backdrop tap close it, body scroll
  locked while open, own scroll, `inert` when closed. Order: brand, identity,
  classroom, experiment, chats + New chat, theme toggle + Sign out. Active
  chat has an accent bar and bold title; thread rows are real buttons.
- Messages: tutor replies use the full width on phones, student bubbles at
  most 84% and rounder; 0.97rem / 1.62 line height on phones; long words,
  formulas and inline code wrap; code blocks and tables scroll inside the
  bubble. Typing dots replace the empty streaming bubble; Copy is hidden
  until the reply settles.
- Sources: collapsed by default, chevron toggle with `aria-expanded`, 44px
  tap height, cards wrap long titles and file names.
- Composer: one rounded field with an integrated circular send button
  (44px on phones, spinner while waiting), auto-grows to 160px, 16px text
  (no iOS zoom), focus ring on the whole pill, short inline note when no
  session is active. Enter-to-send on desktop and newline on touch kept.
- iOS: `env(safe-area-inset-*)` on header, drawer and composer;
  `--app-h` follows `visualViewport` height (skipped while pinch-zoomed) so
  the keyboard shrinks the app instead of covering the composer.
- Auto-scroll follows streaming text only while the reader is near the
  bottom; sending a message always scrolls to its reply.
- Touch targets: every control on the phone layout is >=40px and the drawer
  and header controls are 44px (audited by script).
- Reduced motion: drawer, backdrop, chevron and message transitions off.
- `app/layout.tsx`: `suppressHydrationWarning` on `<html>`; the pre-paint
  theme script sets `data-theme` before hydration, which logged a hydration
  error in light mode (pre-existing).

### Streaming (documented, not changed)

The frontend shows streamed chunks in a temporary message and replaces it
with the saved message from the `done` event. The server post-processes
the saved text (see the comparison-format entry), so the two can differ by
design. The UI change keeps that replacement exactly as before.

### Validation

Against a production build (`next build` + `next start`) with a mocked
`/api`, Playwright (Chromium and WebKit, the latter as the iOS Safari
engine):

- 320, 360, 375, 390, 430, 768, 1280px; states: conversation, sources open,
  drawer open, keyboard open (visual viewport halved), empty chat, session
  inactive, thinking, error, sent. No horizontal overflow in any state in
  either engine; composer visible with the keyboard open.
- 39 functional checks pass at 390px and 1280px: load, sources, copy,
  switch chat, drawer open/close (button, backdrop, Escape), scroll lock,
  inert drawer, rename, delete, new chat, classroom switch, theme toggle,
  greeting buttons, typed send, Enter sends on desktop, streamed draft
  replaced by the saved reply, composer cleared, sign out, "Just tell me"
  chip, no console errors.
- `tsc --noEmit` clean, `next build` succeeds.

Not tested on a physical iPhone; WebKit in Playwright does not reproduce
the real iOS keyboard, so keyboard behaviour should be confirmed on a device.

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
