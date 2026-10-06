"""Phone-only conceptual session for Experiment 7.

For a class whose students have only a phone and the LabTutor page (no
Gabedit, ORCA, Avogadro, second screen or output file), the Exp7 "practical"
is a thinking session built around the experiment instead of a software
walkthrough: six short parts (knowledge/exp07.py `STAGES`), each a factual
context card that LabTutor itself provides, followed by one or two reasoning
questions chosen by pedagogy/policy.py from the student's concept state, then
the nine-question final reflection.

Nothing here asks the student to look at, open, run or read anything outside
this page, and nothing implies they have seen something LabTutor did not show
them. Every question is gated by knowledge/phone_safe.py (source metadata AND
a wording scan) before it can be asked. There is no model call in this module.

State lives in the same `WalkState` / `walkthrough_progress` row as the software
walkthrough (`mode == "concept"`), so persistence, pausing and per-thread scope
are unchanged. The software walkthrough is untouched and stays available behind
`LABTUTOR_PHONE_ONLY=false`.
"""

from __future__ import annotations

from typing import Any

from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.walkthrough import controller as ctl

EXPERIMENT_ID = "exp07"


def _stages():
    return get_knowledge(EXPERIMENT_ID).stages


def _stage_index(state: ctl.WalkState) -> int:
    return max(0, min(state.stage, len(_stages()) - 1))


def progress(state: ctl.WalkState) -> dict[str, Any]:
    stages = _stages()
    i = _stage_index(state)
    return {
        "label": f"Part {i + 1} of {len(stages)}: {stages[i].title}",
        "index": i,
        "total": len(stages),
        "chapter": stages[i].id,
    }


def stage_title(state: ctl.WalkState) -> str:
    return _stages()[_stage_index(state)].title


def _open_question(state: ctl.WalkState, lead: str) -> tuple[str, dict[str, Any]] | None:
    """Ask the next question of the current part, if one is due."""
    stage = _stages()[_stage_index(state)]
    if state.stage_asked >= stage.max_questions:
        return None
    return ctl._concept_moment(state, "stage", lead, resume="stage", step_id=stage.id)


def enter_stage(state: ctl.WalkState, lead: str = "") -> tuple[str, dict[str, Any]]:
    """Show the current part's context card and its first question. A part whose
    ideas the student has already shown they understand is skipped, with a
    one-line note, so a strong student is not re-tested."""
    stages = _stages()
    notes: list[str] = [lead] if lead else []
    while state.stage < len(stages):
        stage = stages[state.stage]
        state.stage_asked = 0
        card = f"**Part {state.stage + 1} of {len(stages)}: {stage.title}**\n\n{stage.context}"
        moment = _open_question(state, "\n\n".join(notes + [card]))
        if moment is not None:
            return moment
        notes.append(f"*Part {state.stage + 1} ({stage.title}): you have already shown you know these ideas, so we will move on.*")
        state.stage += 1
    state.stage = len(stages) - 1  # keep the progress label valid for the closing messages
    return ctl._begin_assessment(state, "\n\n".join(notes))


def after_moment(state: ctl.WalkState, lead: str) -> tuple[str, dict[str, Any]]:
    """A question in this part has been answered (or skipped): ask the next one
    in the same part, or move to the next part."""
    state.stage_asked += 1
    moment = _open_question(state, lead)
    if moment is not None:
        return moment
    state.stage += 1
    return enter_stage(state, lead)


def start(state: ctl.WalkState) -> ctl.TurnResult:
    state.status = "active"
    state.mode = "concept"
    state.stage = 0
    state.stage_asked = 0
    intro = (
        "**Experiment 7, as a thinking session.** You do not need any software for this: "
        "everything you need is on this page. There are "
        f"{len(_stages())} short parts, each with a question or two about the ideas behind the experiment, "
        "then a few closing questions. Short answers are fine, and you can skip any question."
    )
    text, ui = enter_stage(state, intro)
    return ctl.TurnResult(text, state, {"step_id": state.step_id, "verdict": "start", "mode": "concept"}, ui)


def show_current(state: ctl.WalkState, lead: str = "") -> ctl.TurnResult:
    if state.phase == "concept" and state.concept:
        text, ui = ctl._concept_message(state, lead)
    elif state.phase == "assess" and state.assess:
        text, ui = ctl._assess_message(state, lead)
    elif state.status == "done":
        text, ui = ctl._closing_message(state, lead)
    else:
        text, ui = enter_stage(state, lead)
    return ctl.TurnResult(text, state, {"step_id": state.step_id, "verdict": "resume"}, ui)


def step_context(state: ctl.WalkState) -> str:
    """Grounding line for a side question: authored text only, no software."""
    if state.phase == "assess":
        return "The student is answering short closing questions about the ideas in Experiment 7."
    return (
        f"The student is in a phone-only conceptual session on Experiment 7, in the part "
        f"'{stage_title(state)}', and was just asked a short question about the ideas. "
        "They have no software or output in front of them."
    )


def topic_label(state: ctl.WalkState) -> tuple[str, str]:
    return stage_title(state), progress(state)["label"]
