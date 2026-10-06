# Phone-only mode for Experiment 7 (theory first, procedure on request)

Some classes have only a phone and the LabTutor website: no computer, Gabedit,
ORCA, Avogadro, second screen or output file. For those, Exp7 must never ask the
student to look at, open, run or read anything outside the page. This mode is on
by default (`LABTUTOR_PHONE_ONLY=true`); set it to `false` for a class that does
have the software, to restore the step-by-step software walkthrough.

## The three ways to use it

| Student says | What happens | Model calls |
| --- | --- | --- |
| A theory question ("What is geometry optimization?", "Why do we use DFT?", "What is HOMO?") | Grounded answer, then ONE authored, phone-safe Socratic question about that concept ("Think about this: ..."). Their reply is graded deterministically (probe, scaffold, or a short explanation after two misses). | 1 for the answer; 0 for the follow-up and its grading; +1 only for free text the patterns cannot place |
| An explicit procedure request ("How do I perform Experiment 7?", "Walk me through the lab") or the Practical chip | An authored overview of how the practical is normally done **on the lab computer**, saying plainly they need not do any of it here, with chips "Explain the theory instead" and "Guide me through the key ideas". Never a stepper. | 0 |
| "Guide me through the key ideas" / "quiz me" | A six-part conceptual session (context card, then one or two reasoning questions per part, then nine closing questions), adaptive to concept state, every question phone-safe. | 0, except the same single advisory call for unclassifiable free text |

Leaving is always possible, in any common wording ("forget the steps", "skip the
procedure", "I only want the theory", "explain the chemistry behind this", "why
does this work"). All of these switch to theory; if the message also holds a real
question ("forget the steps, explain why optimisation works") it is answered at
once, not just acknowledged. A new question or a mode switch never gets graded as
an answer to an old follow-up.

## Why it used to start procedures by itself (root causes, verified from code)

1. The start detector treated any "how do I...", "how to", "help me" or
   "procedure" as a request to begin the walkthrough, so "How do we choose a basis
   set?" started it.
2. Every Exp7 theory answer ended with a standing offer to "work through this step
   by step", and a bare "yes", "ok" or "sure" accepted it.
3. Once in practice mode every message went through the stepper, so a theory
   question got a "Back to Step N" tail, and natural exits ("forget the steps")
   did not classify as a switch to theory.

Phone-only mode replaces the detector with a strict one
(`conversation.is_procedure_request`), removes the standing offer, and routes
exits through one deterministic path. Other experiments are unchanged.

## Deterministic, no extra model call

Mode detection, procedure detection, exit detection, follow-up selection and
grading, the safety gate and the fallback explanation are all regular
expressions and authored data. No model decides theory versus procedure.

## The phone-only gate

`backend/socratic_engine/knowledge/phone_safe.py`. A question can be asked only if

- its `source` is THEORY, CONCEPTUAL_REASONING or GIVEN_DATA_INTERPRETATION
  (never EXTERNAL_OBSERVATION or PROCEDURAL_EXTERNAL_ACTION), and
- none of the text the student would read (question, scaffold, explanation)
  matches an external-dependency pattern (screen, drawing area, terminal,
  Gabedit, ORCA, Avogadro, "look at your...", "what do you see", "run the...",
  "your <output/structure/results>"...).

Model replies are scanned too. A theory answer that mentions software or numbers
a step has the offending sentences removed (falling back to the authored concept
explanation if little is left); a model reply to a follow-up that does so is
discarded in favour of the authored one. With no model available at all, a
question about a known concept gets the authored explanation instead of an
unrelated manual excerpt.

## Audit of the walkthrough (27 linear steps, plus a 4-step loop run 12 times)

Progress reads "Step N of 27" for the linear part; counting the tables loop the
walkthrough has 75 steps in all. Classified from step titles and question kinds
(I did not read each step's authored text line by line):

| Chapter | Steps | What they are | Phone-only treatment |
| --- | --- | --- | --- |
| Build (b1-b4) | 4 | Open Gabedit, draw, place methane, save. External software; evidence = what is on the screen. | Procedure overview only. Idea kept: molecular structure and geometry (part 1). |
| Set up (o1-o5) | 5 | Open the file, the ORCA dialog, job type/charge/spin, method/basis, read the input. External software. | Overview only. Ideas kept: DFT, basis set, charge/spin (parts 2, 5). |
| Run (r1-r3) | 3 | Start the optimisation, check it finished, read first/last energy. External; evidence is output the student reads. | Overview only. Ideas kept: geometry optimisation, energy (part 3). |
| Read (p1-p5) | 5 | Optimised geometry, single point, orbital table, read HOMO/LUMO. External output. | Overview only. Ideas kept: why use the optimised geometry, HOMO/LUMO (part 4). |
| Orbitals (v1-v4) | 4 | Open Avogadro, read the panel, draw HOMO and LUMO. External visualisation. | Overview only. Idea kept: what an orbital picture represents (part 4). |
| Oxygen (x1-x6) | 6 | Repeat for O2: build, spin, optimise, orbitals. External. | Overview only. Idea kept: O2 versus CH4 (part 5). |
| Tables (t1-t4, x12) | 4 x 12 | Set method/basis, run, record HOMO/LUMO, s/p/d/f shells, twelve times. External; numeric reports. | Overview only. Ideas kept: comparing methods, orbital contribution (part 6). |

None of these 75 steps is reachable in phone-only mode. Their conceptual content
lives in the knowledge model (`knowledge/exp07.py`: concepts, misconceptions, and
the stages and questions above) and is asked as self-contained theory.

## What still depends on external software (by design)

- The software walkthrough itself, behind `LABTUTOR_PHONE_ONLY=false`.
- `q_pattern_interpret`, which interprets the student's own recorded results
  (marked EXTERNAL_OBSERVATION; never asked in phone-only mode, which asks the
  prediction version `q_pattern_predict` instead).
- A student who asks a procedural question the gate does not recognise as one may
  still get a model answer that names software; theory questions are cleaned,
  procedure requests get the overview.

## Limits

- Model-written theory answers and follow-up phrasing are NOT verified live (no
  working model key was available when this was built); the deterministic paths
  and the fallbacks were.
- The authored questions, answer patterns and overview text need review by someone
  who teaches the course.
- The wording gate is conservative: it can reject a harmless question; it cannot
  make a wrong reply.
