"""Database side of a guided walkthrough: load and save the student's state
and decide whether this message belongs to the walkthrough at all.

`handle_turn` returns None when the walkthrough is not engaged (no row and
no start request, paused, or finished) so the caller carries on with normal
grounded Q&A. It returns a TurnResult with `reply=None` for a genuine side
question, which the caller answers with Q&A and follows with `resume_line`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ActorType, WalkthroughProgress
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough import grader

SUPPORTED_EXPERIMENTS = frozenset({"exp07"})


async def get_progress(
    db: AsyncSession, user_id: str, classroom_id: str, experiment_id: str, actor_type: ActorType
) -> WalkthroughProgress | None:
    return (
        await db.scalars(
            select(WalkthroughProgress).where(
                WalkthroughProgress.student_id == user_id,
                WalkthroughProgress.classroom_id == classroom_id,
                WalkthroughProgress.experiment_id == experiment_id,
                WalkthroughProgress.actor_type == actor_type,
            )
        )
    ).first()


def _save(row: WalkthroughProgress, state: ctl.WalkState) -> None:
    row.state = state.to_dict()
    row.status = state.status


async def handle_turn(
    db: AsyncSession,
    *,
    user_id: str,
    classroom_id: str,
    class_session_id: str | None,
    experiment_id: str,
    actor_type: ActorType,
    message: str,
) -> ctl.TurnResult | None:
    if experiment_id not in SUPPORTED_EXPERIMENTS:
        return None

    row = await get_progress(db, user_id, classroom_id, experiment_id, actor_type)
    seed_key = f"{user_id}:{classroom_id}:{experiment_id}"

    if row is None:
        if not (grader.is_start_request(message) or grader.is_affirmative_start(message)):
            return None
        state = ctl.new_state(seed_key)
        result = ctl.start(state)
        row = WalkthroughProgress(
            student_id=user_id,
            classroom_id=classroom_id,
            class_session_id=class_session_id,
            experiment_id=experiment_id,
            actor_type=actor_type,
        )
        _save(row, state)
        db.add(row)
        return result

    state = ctl.WalkState.from_dict(row.state)
    row.class_session_id = class_session_id or row.class_session_id

    if grader.is_restart(message) and (
        state.status != "active" or grader.wants_answer(message) or len(message.split()) <= 4
    ):
        state = ctl.new_state(seed_key)
        result = ctl.start(state)
        _save(row, state)
        result.events["verdict"] = "restart"
        return result

    if state.status == "paused":
        if grader.is_resume(message) or grader.is_start_request(message) or grader.is_resume_phrase(message):
            state.status = "active"
            result = ctl.show_current(state, "Welcome back. Here is where we were.")
            _save(row, state)
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
            {"progress": ctl._progress(state), "phase": state.phase, "kind": "paused", "chips": ["Resume"]},
        )

    if state.phase == "hook" and grader.is_start_request(message) and not grader.wants_answer(message):
        result = ctl.show_current(state, "We are already set up. Here is the question I asked:")
        _save(row, state)
        return result

    result = ctl.take_turn(state, message)
    _save(row, state)
    return result
