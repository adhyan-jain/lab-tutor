# Experiment 7 demo

The brief calls this the first real demo. This document is the script;
`scripts/demo_exp7.py` runs it against live code.

## Running it

```
python scripts/demo_exp7.py
```

No service, database, OAuth setup, or LLM API key is required. The
script builds the retrieval index from whatever `docs/source_manifest.json`
currently makes ingestible (today: the five `knowledge/adjacent/` files,
31 chunks — the IACHY102 manual itself is not yet in the repository; see
`docs/current_state_audit.md` §0) and drives
`backend.retrieval.pipeline.answer_question` through 15 turns with
`use_llm=False`, which forces the deterministic extractive answer path.
This is not a special demo mode — it is also exactly what happens
automatically in normal operation whenever no LLM backend is configured
(`backend/retrieval/pipeline.py::_generate_answer`), so the demo's
answers are not simplified or faked for the occasion.

## What "success" looks like right now, honestly

This demo proves the **pipeline plumbing**, not manual-grounded answers,
because the manual isn't in the repository yet. Concretely, a correct
run today shows:

1. Every procedural exp07 question (turns 1–13) routes to `exp07` and
   resolves to `IN_SCOPE_RETRIEVAL_INSUFFICIENT` — recognised as a fair,
   in-scope question, refused only because there is nothing to answer it
   from, never told it's off-topic. This is brief §12's central
   distinction, holding in a live multi-turn run.
2. The adjacent-theory question (turn 14, "why does DFT work
   physically") resolves to `ADJACENT_SUPPORTED`, cited to
   `knowledge/adjacent/exp07_background.md` (at the time of this run two
   separate files, since merged into that one), with the answer text itself opening
   "This is supplementary material, not the manual itself".
3. The out-of-scope question (turn 15, "what is the best gpu for
   gaming") is refused — correctly, even though every prior turn had the
   session pinned to experiment 7. (This exact turn caught a real bug on
   first run: session context was overriding the refusal. Fixed in
   `backend/scope/classifier.py`; see `backend/tests/test_scope_classifier.py
   ::test_an_active_session_experiment_never_immunises_a_genuine_refusal`.)

**Once the manual is ingested**, re-run the script. Turns 1–13 should
start flipping from `IN_SCOPE_RETRIEVAL_INSUFFICIENT` to
`IN_SCOPE_SUPPORTED` with real citations. Any turn that doesn't flip
despite the manual covering it is a retrieval/chunking bug worth
investigating directly — this script is a fast manual smoke test for
exactly that.

## The scripted conversation, and what each turn is meant to show

| # | Student message | What it exercises |
| - | --- | --- |
| 1 | "hey how to do exp 7" | Filler-word stripping ("hey"), clean English, routes to exp07 |
| 2 | "gabedit me ch4 kaise banau" | Hinglish + software name + protected chemical formula (CH4 must not be "corrected") |
| 3 | "which method and basis set should i use" | Multi-turn context carrying the experiment forward with no re-mention of "exp 7" |
| 4 | "orca input generator kaha hai" | Hinglish "kaha" → "where"; software-specific procedural ask |
| 5 | "job completion message nahi aa raha, normal hai kya" | Negation preservation ("nahi" → "not"), a genuinely ambiguous troubleshooting phrasing |
| 6 | "after optimization what next" | Sequencing language, still procedural not adjacent |
| 7 | "orca ka output kaha milega" | Same intent as turn 4, different Hinglish phrasing — should resolve identically |
| 8 | "avogadro me homo kaise dekhe" | Second software name, protected acronym "homo" not mangled |
| 9 | "where is HOMO LUMO in the output" | Same intent as turn 8 in clean English — cross-checks Hinglish/English parity |
| 10 | "how calculate orbital contribution" | Strong exp07 vocabulary, ungrammatical English |
| 11 | "what do i fill in the table" | Anaphora-adjacent ("the table") relying on session context |
| 12 | "oxygen molecule same process?" | Fragment, question mark absent from most of the flow, tests robustness to terse phrasing |
| 13 | "which screen comes after this one" | Explicit anaphora — must inherit the session's experiment (`has_anaphora=True`) |
| 14 | "why does DFT work physically" | Level 2 (adjacent): background theory, not a manual procedure — must carry the supplementary label |
| 15 | "what is the best gpu for gaming" | Level 3 (out of scope): must be refused even with an active exp07 session |

## Extending the demo to the other P0 experiments

The same script pattern works for experiments 2, 3 and 8 — swap `TURNS`
for messages from `golden_dataset/qa/exp02.json` /
`exp03.json` / `exp08.json` (every case there was itself verified
against the live pipeline, so any subset is guaranteed runnable). A
dedicated `demo_exp2.md` / `demo_exp3.md` / `demo_exp8.md` was not
written this phase — see `docs/handoff_phase2.md` — because Experiment 7
was the brief's explicit first-demo priority and duplicating this
document three times added little beyond what the golden dataset already
covers per experiment.
