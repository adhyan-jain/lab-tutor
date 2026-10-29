"""Socratic-mode routes.

The reveal endpoint is the only place a final answer leaves this system,
and it consults exactly one thing: the server-side `all_steps_complete`
flag, set by Tier 1 verification. The chat endpoint cannot reach that
value at all -- see `backend/answer_gate`.

Faculty and admin may also open Socratic sessions (brief §11), for
testing/demo/reproduction -- through the exact same engine, never a
parallel implementation. Every session/attempt/message they create is
stamped with `actor_type` so it can never be mistaken for real student
activity in summaries or analytics.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit, ratelimit
from backend import classrooms as classroom_service
from backend.answer_gate import PrematureRevealError
from backend.auth import Principal, current_user
from backend.data_access import FacultyScope, StudentScope
from backend.db import get_session
from backend.extraction import ExtractionError, extract_submission, parse_number
from backend.models import (
    ActorType,
    ChatMessage,
    ChatMessageKind,
    ClassSession,
    SocraticAttempt,
    SocraticSession,
)
from backend.rag import templates
from backend.socratic_engine import (
    compute_reveal,
    handle_attempt,
    present_step,
    steps_for,
    triage,
    tutor_reply,
)
from backend.tier1_compute.experiments import (
    ManualNotTranscribedError,
    UnknownExperimentError,
    get_plugin,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/socratic", tags=["socratic"])


class StartSessionRequest(BaseModel):
    classroom_id: str
    #: Faculty/admin test sessions may not have an active class session to
    #: inherit from -- they may name the experiment explicitly. A real
    #: student session always ignores this field.
    experiment_id: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AttemptRequest(BaseModel):
    #: The student's own readings for this step.
    data: dict[str, Any] = Field(default_factory=dict)
    value: Any = None


async def _actor_type_for(db: AsyncSession, principal: Principal, classroom_id: str) -> ActorType:
    if principal.is_admin:
        return ActorType.ADMIN_TEST
    if principal.is_faculty:
        return ActorType.FACULTY_TEST
    if await classroom_service.can_act_as_faculty(db, principal, classroom_id):
        return ActorType.FACULTY_TEST
    return ActorType.STUDENT


async def _own_session(db: AsyncSession, principal: Principal, session_id: str) -> SocraticSession:
    """Owner-scoped fetch. A student only ever sees their own rows; a
    faculty/admin caller only ever sees rows they themselves created as
    test sessions -- never a real student's session, even though they can
    reach the Socratic engine.
    """
    session = (
        await db.scalars(select(SocraticSession).where(SocraticSession.id == session_id))
    ).first()
    if session is None or session.student_id != principal.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return session


async def _reject_if_session_ended(db: AsyncSession, session: SocraticSession) -> None:
    """The server-side fix for a stale browser tab: if the class session
    this Socratic session belongs to has since ended, no further
    attempt/message/reveal may proceed, regardless of what the client
    still has open. Sessions predating ClassSession (class_session_id is
    null) or faculty/admin test sessions with no matching active session
    are not subject to this -- there is no "class" to have ended for them.
    """
    if session.class_session_id is None:
        return
    row = (
        await db.scalars(
            select(ClassSession).where(ClassSession.id == session.class_session_id)
        )
    ).first()
    from backend.models import SessionStatus

    if row is None or row.status != SessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This class session has ended. No further activity is accepted.",
        )


def _plugin_for(session: SocraticSession):
    try:
        return get_plugin(session.experiment_id)
    except UnknownExperimentError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/session", status_code=status.HTTP_201_CREATED)
async def start_session(
    body: StartSessionRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Resume the caller's session for the classroom's active class session.

    Students must be enrolled and there must be an active class session --
    the experiment is always resolved server-side, never from the client.
    Faculty/admin may run a test session against an explicit experiment_id
    even with no active class session (brief §11/§12).
    """
    actor_type = await _actor_type_for(db, principal, body.classroom_id)

    class_session_id: str | None = None
    if actor_type is ActorType.STUDENT:
        scope = StudentScope(db, principal.id)
        if not await scope.is_enrolled(body.classroom_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
            )
        active = await classroom_service.get_active_session(db, body.classroom_id)
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active class session for this classroom yet.",
            )
        experiment_id = (
            body.experiment_id
            if body.experiment_id in active.allowed_experiments
            else active.experiment_id
        )
        class_session_id = active.id
    else:
        fscope = FacultyScope(db, principal.id)
        if not (principal.is_admin or await fscope.is_member(body.classroom_id)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
            )
        active = await classroom_service.get_active_session(db, body.classroom_id)
        experiment_id = body.experiment_id or (active.experiment_id if active else None)
        if not experiment_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active class session; name experiment_id explicitly for a test session.",
            )
        class_session_id = active.id if (active and experiment_id in active.allowed_experiments) else None

    existing = (
        await db.scalars(
            select(SocraticSession).where(
                SocraticSession.student_id == principal.id,
                SocraticSession.classroom_id == body.classroom_id,
                SocraticSession.experiment_id == experiment_id,
                SocraticSession.actor_type == actor_type,
            )
        )
    ).first()
    session = existing
    if session is None:
        session = SocraticSession(
            student_id=principal.id,
            classroom_id=body.classroom_id,
            class_session_id=class_session_id,
            experiment_id=experiment_id,
            actor_type=actor_type,
        )
        db.add(session)
        await db.flush()
        await db.commit()

    plugin = _plugin_for(session)
    try:
        prompt = present_step(plugin, session.current_step)
        total = len(steps_for(plugin))
    except ManualNotTranscribedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "This experiment is not set up for guided mode yet. "
                f"({exc})"
            ),
        ) from exc

    return {
        "session_id": session.id,
        "experiment_id": session.experiment_id,
        "current_step": session.current_step,
        "total_steps": total,
        "prompt": prompt,
        "complete": session.all_steps_complete,
        "actor_type": actor_type.value,
    }


@router.post("/session/{session_id}/attempt")
async def attempt(
    session_id: str,
    body: AttemptRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Verify the current step against the caller's own data."""
    session = await _own_session(db, principal, session_id)
    await _reject_if_session_ended(db, session)
    if session.all_steps_complete:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Every step is already verified for this session.",
        )
    plugin = _plugin_for(session)

    numeric_keys = tuple(k for k, v in body.data.items() if not isinstance(v, (list, tuple)))
    series_keys = tuple(k for k, v in body.data.items() if isinstance(v, (list, tuple)))
    extracted = extract_submission(
        body.data, numeric_fields=numeric_keys, series_fields=series_keys
    )
    total_steps = len(steps_for(plugin))

    def _invalid_attempt_response(message: str) -> dict:
        # Same shape as the full success/failure path below -- a partial
        # dict here (missing total_steps/complete/prompt) previously made
        # the frontend's unconditional `setState({...result})` overwrite
        # those fields with undefined, rendering "Step NaN of" (found live
        # in a browser smoke test by submitting an empty/invalid attempt).
        return {
            "passed": False,
            "current_step": session.current_step,
            "total_steps": total_steps,
            "message": message,
            "hint_level": 0,
            "complete": session.all_steps_complete,
            "prompt": (
                present_step(plugin, session.current_step)
                if not session.all_steps_complete
                else ""
            ),
        }

    if not extracted.ok:
        return _invalid_attempt_response("; ".join(extracted.errors))

    submitted: float | None = None
    if body.value is not None:
        try:
            submitted = parse_number(body.value, "value")
        except ExtractionError as exc:
            return _invalid_attempt_response(str(exc))

    # Accumulate the caller's own readings across steps.
    merged = dict(session.student_data or {})
    merged.update(extracted.values)

    attempts_on_step = int(
        await db.scalar(
            select(func.count())
            .select_from(SocraticAttempt)
            .where(
                SocraticAttempt.session_id == session.id,
                SocraticAttempt.step_index == session.current_step,
            )
        )
        or 0
    )

    try:
        outcome = handle_attempt(
            plugin,
            step_index=session.current_step,
            attempts_on_step=attempts_on_step,
            student_data=merged,
            submitted_value=submitted,
        )
    except ManualNotTranscribedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    db.add(
        SocraticAttempt(
            session_id=session.id,
            student_id=principal.id,
            step_index=session.current_step,
            submitted_value=submitted,
            passed=outcome.passed,
            hint_level=outcome.hint_level,
            detail=outcome.detail,
        )
    )

    session.student_data = merged
    if outcome.advanced_to is not None:
        session.current_step = outcome.advanced_to
    if outcome.all_steps_complete:
        session.all_steps_complete = True
        if outcome.passed:
            await audit.record(
                db, audit.REVEAL_GRANTED, user_id=principal.id,
                classroom_id=session.classroom_id,
                class_session_id=session.class_session_id,
                detail={"session": session.id, "experiment": session.experiment_id},
            )

    db.add(
        ChatMessage(
            kind=ChatMessageKind.SOCRATIC,
            session_id=session.id,
            class_session_id=session.class_session_id,
            student_id=principal.id,
            classroom_id=session.classroom_id,
            experiment_id=session.experiment_id,
            actor_type=session.actor_type,
            author="tutor",
            content=outcome.message,
        )
    )
    await db.commit()

    total = len(steps_for(plugin))
    return {
        "passed": outcome.passed,
        "current_step": session.current_step,
        "total_steps": total,
        "message": outcome.message,
        "hint_level": outcome.hint_level,
        "complete": session.all_steps_complete,
        "prompt": (
            present_step(plugin, session.current_step)
            if not session.all_steps_complete
            else ""
        ),
    }


@router.post("/session/{session_id}/message")
async def message(
    session_id: str,
    body: MessageRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """One conversational turn.

    Whatever the caller writes -- including a demand for the answer, a
    claim of being staff, or a claim that the system is broken -- the
    model answering them was never given the final value.
    """
    session = await _own_session(db, principal, session_id)
    await _reject_if_session_ended(db, session)
    if session.all_steps_complete and session.revealed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session is finished. Start a new one to keep chatting.",
        )
    plugin = _plugin_for(session)

    limit = ratelimit.check_socratic_turn(principal.id)
    if not limit.allowed:
        await audit.record(
            db, audit.RATE_LIMITED, user_id=principal.id,
            classroom_id=session.classroom_id, detail={"scope": "socratic"}, commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You are sending messages too quickly; wait a moment.",
            headers={"Retry-After": str(int(limit.retry_after_seconds) + 1)},
        )

    db.add(
        ChatMessage(
            kind=ChatMessageKind.SOCRATIC,
            session_id=session.id,
            class_session_id=session.class_session_id,
            student_id=principal.id,
            classroom_id=session.classroom_id,
            experiment_id=session.experiment_id,
            actor_type=session.actor_type,
            author="student",
            content=body.message,
        )
    )

    try:
        steps = steps_for(plugin)
    except ManualNotTranscribedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    step = steps[min(session.current_step, len(steps) - 1)]
    attempts_on_step = int(
        await db.scalar(
            select(func.count())
            .select_from(SocraticAttempt)
            .where(
                SocraticAttempt.session_id == session.id,
                SocraticAttempt.step_index == session.current_step,
            )
        )
        or 0
    )

    # The hint rung is chosen here, by attempt count -- not by the model,
    # and not by anything in the caller's message.
    hint = (
        templates.hint_text(min(attempts_on_step, 3), step.hints)
        if attempts_on_step
        else ""
    )

    reply = await tutor_reply(
        student_message=body.message,
        step_prompt=step.prompt,
        step_index=session.current_step,
        total_steps=len(steps),
        hint_text=hint or templates.refusal_text(),
        attempts_on_this_step=attempts_on_step,
        all_steps_complete=session.all_steps_complete,
        retrieval_query=f"{plugin.title} {step.key}",
    )

    if reply.redacted:
        await audit.record(
            db, audit.ANSWER_GATE_REDACTION, user_id=principal.id,
            classroom_id=session.classroom_id,
            detail={"session": session.id, "step": session.current_step},
        )

    # An injury report, a safety question or a student in difficulty is
    # not a chat turn to be forgotten. Record it so staff can see it on
    # the dashboard even if nobody was watching the room at the time.
    # Not raised for faculty/admin test sessions -- there is no real
    # student in difficulty there.
    if session.actor_type is ActorType.STUDENT and triage.needs_staff_attention(reply.intent):
        await audit.record(
            db, audit.STUDENT_FLAG, user_id=principal.id,
            classroom_id=session.classroom_id,
            detail={
                "intent": reply.intent.value,
                "session": session.id,
                "experiment": session.experiment_id,
                "message": body.message[:500],
            },
        )

    db.add(
        ChatMessage(
            kind=ChatMessageKind.SOCRATIC,
            session_id=session.id,
            class_session_id=session.class_session_id,
            student_id=principal.id,
            classroom_id=session.classroom_id,
            experiment_id=session.experiment_id,
            actor_type=session.actor_type,
            author="tutor",
            content=reply.text,
        )
    )
    await db.commit()

    return {
        "reply": reply.text,
        "intent": reply.intent.value,
        "current_step": session.current_step,
        "total_steps": len(steps),
        "complete": session.all_steps_complete,
    }


@router.post("/session/{session_id}/reveal")
async def reveal(
    session_id: str,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The separate, non-LLM reveal path. Refuses until verification passes."""
    session = await _own_session(db, principal, session_id)
    await _reject_if_session_ended(db, session)
    plugin = _plugin_for(session)

    # The caller's own derived answer, so the reveal can set it beside the
    # independently computed value rather than just announcing a number.
    # Taken from the attempt that passed the final step -- the only value
    # they actually stood behind.
    final_step_index = max(len(steps_for(plugin)) - 1, 0)
    derived = (
        await db.scalars(
            select(SocraticAttempt.submitted_value)
            .where(
                SocraticAttempt.session_id == session.id,
                SocraticAttempt.step_index == final_step_index,
                SocraticAttempt.passed.is_(True),
            )
            .order_by(SocraticAttempt.created_at.desc())
            .limit(1)
        )
    ).first()

    try:
        text = compute_reveal(
            plugin,
            all_steps_complete=session.all_steps_complete,
            student_data=session.student_data or {},
            student_final_value=derived,
        )
    except PrematureRevealError:
        # Deliberately the same response whatever the reason, so probing
        # this endpoint reveals nothing about how close the caller is.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The final value is available once every step has been "
                "verified. Keep going -- the current step is still open."
            ),
        ) from None
    except ManualNotTranscribedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    session.revealed = True
    db.add(
        ChatMessage(
            kind=ChatMessageKind.SOCRATIC,
            session_id=session.id,
            class_session_id=session.class_session_id,
            student_id=principal.id,
            classroom_id=session.classroom_id,
            experiment_id=session.experiment_id,
            actor_type=session.actor_type,
            author="tutor",
            content=text,
        )
    )
    await db.commit()
    return {"reveal": text, "source": "template"}
