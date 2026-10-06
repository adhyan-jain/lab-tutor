"""Database side of a guided walkthrough: load and save the student's state
and decide whether this message belongs to the walkthrough at all.

State is scoped to one chat thread: a new chat starts with no walkthrough,
and opening chat B never loads chat A's step. A walkthrough left unfinished
in another chat (or from before threads were tracked) is only picked up when
the student explicitly asks to "resume previous session".

`handle_turn` returns None when the walkthrough is not engaged (no row and
no start request, paused, or finished) so the caller carries on with normal
grounded Q&A. It returns a TurnResult with `reply=None` for a genuine side
question, which the caller answers with Q&A and follows with `resume_line`.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ActorType, WalkthroughProgress
from backend.socratic_engine import conversation as conv
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough import grader

log = logging.getLogger("labtutor.walkthrough")

SUPPORTED_EXPERIMENTS = frozenset({"exp07"})

_RESUME_PREVIOUS_RE = re.compile(
    r"\b(resume|continue|pick up|load)\s+(my\s+|the\s+)?(previous|last|earlier|old|other)\s+"
    r"(session|progress|walkthrough|chat|run)\b",
    re.IGNORECASE,
)


def is_resume_previous(text: str) -> bool:
    return bool(_RESUME_PREVIOUS_RE.search(text or ""))


async def get_progress(db: AsyncSession, thread_id: str) -> WalkthroughProgress | None:
    return (
        await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.thread_id == thread_id))
    ).first()


async def previous_progress(
    db: AsyncSession,
    *,
    user_id: str,
    classroom_id: str,
    experiment_id: str,
    actor_type: ActorType,
    exclude_thread_id: str,
) -> WalkthroughProgress | None:
    """The most recent unfinished walkthrough this student has outside this
    thread -- offered, never loaded automatically."""
    rows = (
        await db.scalars(
            select(WalkthroughProgress)
            .where(
                WalkthroughProgress.student_id == user_id,
                WalkthroughProgress.classroom_id == classroom_id,
                WalkthroughProgress.experiment_id == experiment_id,
                WalkthroughProgress.actor_type == actor_type,
                WalkthroughProgress.status != "done",
            )
            .order_by(WalkthroughProgress.updated_at.desc())
        )
    ).all()
    return next((r for r in rows if r.thread_id != exclude_thread_id), None)


def _save(row: WalkthroughProgress, state: ctl.WalkState) -> None:
    row.state = state.to_dict()
    row.status = state.status


async def apply_advisory(db: AsyncSession, thread_id: str, concept_id: str, suggested: str) -> str | None:
    """Fold a model's suggested classification into the stored concept state,
    clamped by pedagogy.state.apply_advisory. Returns the resulting state."""
    from backend.socratic_engine.pedagogy import state as pstate

    row = await get_progress(db, thread_id)
    if row is None:
        return None
    wstate = ctl.WalkState.from_dict(row.state)
    cs = ctl._cs(wstate)
    rec = pstate.apply_advisory(cs, concept_id, suggested)
    ctl._save_cs(wstate, cs)
    _save(row, wstate)
    return rec.state


def pause(row: WalkthroughProgress) -> ctl.WalkState:
    """Leave practice for theory: the step is kept exactly where it was."""
    state = ctl.WalkState.from_dict(row.state)
    if state.status == "active":
        state.status = "paused"
    _save(row, state)
    return state


def resume(row: WalkthroughProgress, lead: str) -> ctl.TurnResult:
    """Back to practice at the same step, never a later one."""
    state = ctl.WalkState.from_dict(row.state)
    if state.status == "paused":
        state.status = "active"
    result = ctl.show_current(state, lead)
    _save(row, state)
    return result


async def handle_turn(
    db: AsyncSession,
    *,
    thread_id: str,
    user_id: str,
    classroom_id: str,
    class_session_id: str | None,
    experiment_id: str,
    actor_type: ActorType,
    message: str,
    entering_practice: bool = False,
) -> ctl.TurnResult | None:
    if experiment_id not in SUPPORTED_EXPERIMENTS:
        return None

    row = await get_progress(db, thread_id)
    seed_key = f"{user_id}:{classroom_id}:{experiment_id}"
    scope = dict(user_id=user_id, classroom_id=classroom_id, experiment_id=experiment_id, actor_type=actor_type)

    if row is None:
        wants_previous = is_resume_previous(message)
        if not (entering_practice or wants_previous or grader.is_start_request(message) or grader.is_affirmative_start(message)):
            return None
        state = ctl.new_state(seed_key)
        result = ctl.start(state)
        previous = await previous_progress(db, **scope, exclude_thread_id=thread_id)
        if previous is not None and wants_previous:
            state = ctl.WalkState.from_dict(previous.state)
            state.status = "active"
            result = ctl.show_current(state, "Picking up where you left off in your previous session.")
            result.events["verdict"] = "resume_previous"
        elif previous is not None:
            # Offer, don't load: the student chose a fresh chat.
            prev_state = ctl.WalkState.from_dict(previous.state)
            label = ctl._progress(prev_state)["label"]
            result.reply += (
                f"\n\n*You also have an unfinished walkthrough from another chat ({label}). "
                'Tap "Resume previous session" to continue that one instead.*'
            )
            result.ui["chips"] = list(result.ui.get("chips", [])) + [conv.ACTIONS["resume_previous"]]
        row = WalkthroughProgress(
            thread_id=thread_id,
            student_id=user_id,
            classroom_id=classroom_id,
            class_session_id=class_session_id,
            experiment_id=experiment_id,
            actor_type=actor_type,
        )
        _save(row, state)
        db.add(row)
        log.info("[CHAT] conversationId=%s walkthrough=%s", thread_id, result.events.get("verdict"))
        return result

    state = ctl.WalkState.from_dict(row.state)
    row.class_session_id = class_session_id or row.class_session_id

    if is_resume_previous(message) and state.steps_done == 0:
        previous = await previous_progress(db, **scope, exclude_thread_id=thread_id)
        if previous is not None:
            state = ctl.WalkState.from_dict(previous.state)
            state.status = "active"
            result = ctl.show_current(state, "Picking up where you left off in your previous session.")
            result.events["verdict"] = "resume_previous"
            _save(row, state)
            return result

    if grader.is_restart(message) and (
        state.status != "active" or grader.wants_answer(message) or len(message.split()) <= 4
    ):
        state = ctl.new_state(seed_key)
        result = ctl.start(state)
        _save(row, state)
        result.events["verdict"] = "restart"
        return result

    if state.status == "paused":
        if entering_practice or grader.is_resume(message) or grader.is_start_request(message) or grader.is_resume_phrase(message):
            result = resume(row, "Welcome back. Here is where we were.")
            return result
        return None

    if state.status == "done":
        return None

    if grader.is_stop(message):
        state.status = "paused"
        _save(row, state)
        return ctl.TurnResult(
            'Paused. Ask me anything in the meantime, and say "resume" when you want to carry on from '
            f"{ctl._progress(state)['label']}.",
            state,
            {"verdict": "paused", "step_id": state.step_id},
            {"progress": ctl._progress(state), "phase": state.phase, "kind": "paused", "chips": [conv.ACTIONS["resume"]]},
        )

    if state.phase == "hook" and grader.is_start_request(message) and not grader.wants_answer(message):
        result = ctl.show_current(state, "We are already set up. Here is the question I asked:")
        _save(row, state)
        return result

    result = ctl.take_turn(state, message)
    _save(row, state)
    return result
