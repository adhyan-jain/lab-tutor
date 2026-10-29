"""Phone-only conceptual session for Experiment 7.

For a class whose students have only a phone and the Catalyst page (no
Gabedit, ORCA, Avogadro, second screen or output file), the Exp7 "practical"
is a thinking session built around the experiment instead of a software
walkthrough: six short parts (knowledge/exp07.py `STAGES`), each a factual
context card that Catalyst itself provides, followed by one or two reasoning
questions chosen by pedagogy/policy.py from the student's concept state, then
the nine-question final reflection.

Nothing here asks the student to look at, open, run or read anything outside
this page, and nothing implies they have seen something Catalyst did not show
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
from backend.socratic_engine.walkthrough.navigation import Nav, NavCommand

def _stages(state: ctl.WalkState):
    return get_knowledge(state.experiment_id).stages


def _stage_index(state: ctl.WalkState) -> int:
    return max(0, min(state.stage, len(_stages(state)) - 1))


def progress(state: ctl.WalkState) -> dict[str, Any]:
    stages = _stages(state)
    i = _stage_index(state)
    return {
        "label": f"Part {i + 1} of {len(stages)}: {stages[i].title}",
        "index": i,
        "total": len(stages),
        "chapter": stages[i].id,
    }


def stage_title(state: ctl.WalkState) -> str:
    return _stages(state)[_stage_index(state)].title


def _open_question(state: ctl.WalkState, lead: str) -> tuple[str, dict[str, Any]] | None:
    """Ask the next question of the current part, if one is due."""
    stage = _stages(state)[_stage_index(state)]
    if state.stage_asked >= stage.max_questions:
        return None
    return ctl._concept_moment(state, "stage", lead, resume="stage", step_id=stage.id)


def enter_stage(state: ctl.WalkState, lead: str = "") -> tuple[str, dict[str, Any]]:
    """Show the current part's context card and its first question. A part whose
    ideas the student has already shown they understand is skipped, with a
    one-line note, so a strong student is not re-tested."""
    stages = _stages(state)
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
        f"**{ctl.exp_label(state)}, as a thinking session.** No apparatus or software needed. "
        f"There are {len(_stages(state))} short parts with a question or two each, then a few closing questions. "
        "Short answers are fine, and you can skip any."
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


def _jump_to_part(state: ctl.WalkState, n: int, lead: str) -> ctl.TurnResult:
    stages = _stages(state)
    newly: list[str] = []
    if state.status != "done" and state.phase != "assess":
        for stage in stages[_stage_index(state):n - 1]:
            key = f"part:{stage.id}"
            if key not in state.skipped:
                state.skipped.append(key)
                newly.append(key)
    ctl._leave_detours(state)
    state.stage = n - 1
    text, ui = enter_stage(state, lead)
    return ctl.TurnResult(text, state, {"step_id": state.step_id, "verdict": "goto", "target": n, "jumped_past": newly}, ui)


def navigate(state: ctl.WalkState, cmd: NavCommand) -> ctl.TurnResult | None:
    """Navigation in the key-ideas session. Its numbered units are the six
    parts, so "go to step 3" and "part 3" both mean Part 3; "next" skips the
    question on screen (no penalty), "next part" moves to the next part."""
    stages = _stages(state)
    total = len(stages)
    current = _stage_index(state) + 1
    if cmd.kind is Nav.REPEAT:
        return ctl._repeat(state, "Here it is again.", "repeat")
    if cmd.kind is Nav.NEXT:
        if cmd.unit == "part":
            if current >= total:
                return ctl._repeat(state, "This is the last part.", "next_at_end")
            return _jump_to_part(state, current + 1, f"On to Part {current + 1}.")
        if state.status == "done":
            return None
        if state.phase == "concept" and state.concept:
            return ctl._turn_concept(state, "skip")
        if state.phase == "assess" and state.assess:
            return ctl._turn_assess(state, "skip")
        return show_current(state, "Here is where you are.")
    if cmd.kind is Nav.BACK:
        target = total if (state.phase == "assess" or state.status == "done") else current - 1
        if target < 1:
            return ctl._repeat(state, "This is the first part.", "back_at_start")
        return _jump_to_part(state, target, f"Going back to Part {target}.")
    n = cmd.target or 0
    if not 1 <= n <= total:
        return ctl._repeat(state, f"There are {total} parts. Say a part number from 1 to {total}.", "goto_out_of_range")
    if n == current and state.phase == "concept" and state.status == "active":
        return ctl._repeat(state, f"You are already on Part {n}.", "goto_same")
    return _jump_to_part(state, n, f"Jumping to Part {n}.")


def step_context(state: ctl.WalkState) -> str:
    """Grounding line for a side question: authored text only, no software."""
    if state.phase == "assess":
        return f"The student is answering short closing questions about the ideas in {ctl.exp_label(state)}."
    return (
        f"The student is in a phone-only conceptual session on {ctl.exp_label(state)}, in the part "
        f"'{stage_title(state)}', and was just asked a short question about the ideas. "
        "They have no apparatus, software or output in front of them."
    )


def topic_label(state: ctl.WalkState) -> tuple[str, str]:
    return stage_title(state), progress(state)["label"]
