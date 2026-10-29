"""Q&A (chat) routes -- the general theory/procedure/troubleshooting
assistant, shared by students and faculty/admin (brief item 1: "Students
and faculty must use the SAME Catalyst system; faculty must not need
student mode.").

Unlike Socratic mode, this path has no step machine, no student answer to
verify, and never reveals or decides a diagnosis -- it only produces a
grounded answer via `backend.retrieval.pipeline.answer_question`, which
enforces the "never invent evidence" rule structurally (see that module's
docstring). This route is wiring, validation and persistence only, same
posture as every other file in this package (see `backend/api/__init__.py`).

A student's Q&A turn requires an ACTIVE class session for the classroom
they're asking in, and is rejected the moment that session ends --
including from a stale browser tab that never reloaded, because the check
is re-run on every request rather than cached client-side. Faculty/admin
may ask without an active session (browsing/testing between classes), and
their activity is stamped `FACULTY_TEST`/`ADMIN_TEST` so it can never be
mistaken for real student engagement (see `ChatMessage.actor_type` and
`backend/summaries/` which excludes non-student actors).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit, ratelimit
from backend import classrooms as classroom_service
from backend.auth import Principal, current_user
from backend.data_access import FacultyScope, StudentScope
from backend.db import get_session
from backend.models import ActorType, ChatMessage, ChatMessageKind
from backend.retrieval.pipeline import answer_question
from backend.socratic_engine import triage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/qa", tags=["qa"])


class AskRequest(BaseModel):
    classroom_id: str
    message: str = Field(min_length=1, max_length=4000)


async def _actor_type_for(db: AsyncSession, principal: Principal, classroom_id: str) -> ActorType:
    if principal.is_admin:
        return ActorType.ADMIN_TEST
    if principal.is_faculty:
        return ActorType.FACULTY_TEST
    # A student promoted to classroom-scoped co-faculty here (see
    # classrooms/service.py::can_act_as_faculty) is tagged FACULTY_TEST for
    # their activity in THIS classroom, same as any other faculty test
    # activity -- never counted as their own student engagement/summaries.
    if await classroom_service.can_act_as_faculty(db, principal, classroom_id):
        return ActorType.FACULTY_TEST
    return ActorType.STUDENT


async def _resolve_context(
    db: AsyncSession, principal: Principal, actor_type: ActorType, classroom_id: str
) -> tuple[str | None, str | None]:
    """Returns (class_session_id, experiment_id), both possibly None for a
    faculty/admin caller with no active session. Raises 404/409 for a
    student who isn't enrolled or has no active class session -- the
    server-side gate that makes a stale tab's request fail after class
    ends, same mechanism as `socratic_routes._reject_if_session_ended`.
    """
    if actor_type is ActorType.STUDENT:
        scope = StudentScope(db, principal.id)
        if not await scope.is_enrolled(classroom_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
            )
        active = await classroom_service.get_active_session(db, classroom_id)
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active class session for this classroom yet.",
            )
        return active.id, active.experiment_id

    fscope = FacultyScope(db, principal.id)
    if not (principal.is_admin or await fscope.is_member(classroom_id)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
        )
    active = await classroom_service.get_active_session(db, classroom_id)
    if active is None:
        return None, None
    return active.id, active.experiment_id


@router.post("/ask")
async def ask(
    body: AskRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    actor_type = await _actor_type_for(db, principal, body.classroom_id)
    class_session_id, experiment_id = await _resolve_context(
        db, principal, actor_type, body.classroom_id
    )

    limit = ratelimit.check_qa_turn(principal.id)
    if not limit.allowed:
        await audit.record(
            db, audit.RATE_LIMITED, user_id=principal.id,
            classroom_id=body.classroom_id, detail={"scope": "qa"}, commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You are sending messages too quickly; wait a moment.",
            headers={"Retry-After": str(int(limit.retry_after_seconds) + 1)},
        )

    db.add(
        ChatMessage(
            kind=ChatMessageKind.QA,
            session_id=None,
            class_session_id=class_session_id,
            student_id=principal.id,
            classroom_id=body.classroom_id,
            experiment_id=experiment_id or "",
            actor_type=actor_type,
            author="student",
            content=body.message,
        )
    )

    # Deterministic safety triage runs before any model call, exactly as
    # it does for Socratic chat -- a Q&A message can just as easily be a
    # safety incident as a step-attempt message can.
    intent = triage.classify(body.message)
    if triage.short_circuits(intent):
        reply_text = triage.fixed_response(intent) or ""
        result_status: str | None = None
        citations: list[dict] = []
        answer_source = "triage"
    else:
        result = await answer_question(body.message, active_experiment=experiment_id)
        reply_text = result.text
        result_status = result.status.value
        citations = [
            {"text": c.text, "page": c.page, "tier": c.tier.value}
            for c in result.citations
        ]
        answer_source = result.answer_source

    if actor_type is ActorType.STUDENT and triage.needs_staff_attention(intent):
        await audit.record(
            db, audit.STUDENT_FLAG, user_id=principal.id,
            classroom_id=body.classroom_id,
            detail={"intent": intent.value, "message": body.message[:500]},
        )

    db.add(
        ChatMessage(
            kind=ChatMessageKind.QA,
            session_id=None,
            class_session_id=class_session_id,
            student_id=principal.id,
            classroom_id=body.classroom_id,
            experiment_id=experiment_id or "",
            actor_type=actor_type,
            author="tutor",
            content=reply_text,
        )
    )
    await db.commit()

    return {
        "reply": reply_text,
        "status": result_status,
        "citations": citations,
        "answer_source": answer_source,
        "experiment_id": experiment_id,
        "intent": intent.value,
    }


@router.get("/history")
async def history(
    classroom_id: str = Query(...),
    limit: int = Query(default=100, le=500),
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The caller's own Q&A transcript for a classroom, oldest first.

    Owner-scoped through `StudentScope` regardless of the caller's
    platform role -- a faculty/admin caller reviewing their own test
    conversation goes through the identical query shape, just keyed to
    their own account id, never another user's.
    """
    scope = StudentScope(db, principal.id)
    stmt = (
        scope.select(ChatMessage)
        .where(
            ChatMessage.kind == ChatMessageKind.QA,
            ChatMessage.classroom_id == classroom_id,
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
    )
    rows = list((await db.scalars(stmt)).all())
    return {
        "messages": [
            {
                "author": m.author,
                "content": m.content,
                "experiment_id": m.experiment_id or None,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]
    }
