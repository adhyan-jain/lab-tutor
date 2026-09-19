"""Classroom routes.

Every route re-checks the caller's role/capability through
`require_faculty_or_admin` / `require_classroom_faculty` /
`require_student` / `require_admin`, and every classroom-scoped route
additionally proves faculty capability for that specific classroom
(`can_act_as_faculty` -- real faculty, admin, or a promoted co-faculty)
before touching it. ADMIN bypasses membership scoping by design (global
authority, per brief §8) but never bypasses `require_admin` itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit
from backend import classrooms as classroom_service
from backend import idempotency
from backend.auth import (
    Principal,
    require_admin,
    require_faculty_or_admin,
    require_student,
)
from backend.data_access import FacultyScope, StudentScope
from backend.auth.dependencies import current_user, faculty_or_admin_scope, student_scope
from backend.db import get_session
from backend.models import Classroom, ClassroomMembership, ClassroomRole, Role, User
from backend.tier1_compute.experiments import all_plugins

router = APIRouter(prefix="/api/classrooms", tags=["classrooms"])


class CreateClassroomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=128)


class JoinRequest(BaseModel):
    join_code: str = Field(min_length=1, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)


class StartSessionRequest(BaseModel):
    experiment_id: str


class JoinOpenRequest(BaseModel):
    join_open: bool


class RenameClassroomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RegenerateCodeRequest(BaseModel):
    which: str = Field(pattern="^(student|faculty)$")


async def require_classroom_faculty(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    """Admin, a genuine platform-faculty member of this classroom, or a
    student promoted to classroom-scoped co-faculty here -- see
    `classroom_service.can_act_as_faculty`. Replaces `require_faculty_or_
    admin` + `FacultyScope` membership check on every route a promoted
    co-faculty needs real (not cosmetic) access to.

    Same two-stage 403-then-404 split as `require_faculty_or_admin_or_co_
    faculty` (dashboard_routes.py): a caller with zero faculty capability
    anywhere gets a flat 403 (matches every pre-existing "staff only"
    test); a caller who IS faculty/co-faculty somewhere but not for THIS
    classroom_id gets 404, indistinguishable from "does not exist" --
    consistent with every other membership check in this file.
    """
    if not (principal.is_faculty or principal.is_admin):
        if not await classroom_service.has_any_faculty_membership(db, principal.id):
            await audit.record(
                db, audit.AUTH_FAILURE, user_id=principal.id,
                detail={"reason": "faculty_or_admin_role_required", "actual": principal.role.value},
                commit=True,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Staff only"
            )
    if not await classroom_service.can_act_as_faculty(db, principal, classroom_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
        )
    return principal


async def _get_classroom_or_404(db: AsyncSession, classroom_id: str) -> Classroom:
    """Membership/role already proven by `require_classroom_faculty` --
    this just fetches the row."""
    classroom = (
        await db.scalars(select(Classroom).where(Classroom.id == classroom_id))
    ).first()
    if classroom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
        )
    return classroom


async def _classroom_payload(db: AsyncSession, classroom: Classroom, *, include_codes: bool) -> dict:
    active_session = await classroom_service.get_active_session(db, classroom.id)
    payload = {
        "id": classroom.id,
        "name": classroom.name,
        "join_open": classroom.join_open,
        "active_experiment_id": active_session.experiment_id if active_session else None,
        "active_session_id": active_session.id if active_session else None,
        "student_count": await classroom_service.student_count(db, classroom.id),
        "archived": classroom.archived_at is not None,
        "archived_at": classroom.archived_at.isoformat() if classroom.archived_at else None,
    }
    if include_codes:
        payload["student_join_code"] = classroom.student_join_code
        payload["faculty_join_code"] = classroom.faculty_join_code
    return payload


@router.get("/experiments")
async def list_experiments(
    principal: Principal = Depends(current_user),
) -> dict:
    """Every experiment that may be started as a class session, readiness,
    and its evaluation priority (P0+/P0/P1 -- product coverage is all ten;
    this only orders where testing effort concentrated, per
    backend/scope/ontology.py::PRIORITY). Listed in priority order so the
    best-covered experiments surface first without hiding the rest.

    Any authenticated role may read this -- id/title/kind/readiness/
    priority is non-sensitive catalogue metadata (no student data, no
    join codes). Originally faculty/admin-only when only the "start a
    class" picker used it; the shared chat UI now also needs it for
    students to populate their experiment selector.
    """
    from backend.scope.ontology import PRIORITY

    plugins = sorted(
        all_plugins(),
        key=lambda p: (PRIORITY.get(p.id, "P1"), p.id),
    )
    return {
        "experiments": [
            {
                "id": p.id,
                "title": p.title,
                "kind": p.kind,
                "ready": p.is_ready,
                "manual_reference": p.manual_reference,
                "priority": PRIORITY.get(p.id, "P1"),
            }
            for p in plugins
        ]
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_classroom(
    body: CreateClassroomRequest,
    principal: Principal = Depends(require_faculty_or_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    key = body.idempotency_key or idempotency.derive_key("create_classroom", body.name)
    try:
        claim = await idempotency.claim(
            db, user_id=principal.id, scope="create_classroom", key=key
        )
    except idempotency.DuplicateInFlight as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not claim.fresh:
        return claim.replayed_response or {}

    classroom = await classroom_service.create_classroom(
        db, creator_id=principal.id, name=body.name, creator_is_faculty=principal.is_faculty
    )
    await audit.record(
        db, audit.CLASSROOM_CREATED, user_id=principal.id, classroom_id=classroom.id,
        detail={"name": classroom.name},
    )
    payload = await _classroom_payload(db, classroom, include_codes=True)
    await idempotency.complete(db, claim, payload)
    await db.commit()
    return payload


@router.get("")
async def list_all_classrooms(
    include_archived: bool = False,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Admin-only: every classroom, without needing membership in any."""
    stmt = select(Classroom)
    if not include_archived:
        stmt = stmt.where(Classroom.archived_at.is_(None))
    rows = list((await db.scalars(stmt)).all())
    return {"classrooms": [await _classroom_payload(db, c, include_codes=True) for c in rows]}


@router.get("/mine")
async def my_classrooms(
    include_archived: bool = False,
    scope: FacultyScope = Depends(faculty_or_admin_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = list(
        (await db.scalars(scope.select_classrooms(include_archived=include_archived))).all()
    )
    return {"classrooms": [await _classroom_payload(db, c, include_codes=True) for c in rows]}


@router.get("/enrolled")
async def enrolled_classrooms(
    principal: Principal = Depends(require_student),
    scope: StudentScope = Depends(student_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """A student sees classrooms they're enrolled in as a student, plus any
    classroom they've been promoted to classroom-scoped co-faculty in
    (their own STUDENT membership there is deactivated on promotion, so
    `active_classroom_ids()` alone would miss it -- unioned in below)."""
    student_ids = set(await scope.active_classroom_ids())
    co_faculty_ids = set(
        await db.scalars(
            select(ClassroomMembership.classroom_id).where(
                ClassroomMembership.user_id == principal.id,
                ClassroomMembership.role == ClassroomRole.FACULTY,
                ClassroomMembership.active.is_(True),
            )
        )
    )
    ids = student_ids | co_faculty_ids
    if not ids:
        return {"classrooms": []}
    rows = list(
        (
            await db.scalars(
                select(Classroom).where(Classroom.id.in_(ids), Classroom.archived_at.is_(None))
            )
        ).all()
    )
    out = []
    for c in rows:
        payload = await _classroom_payload(db, c, include_codes=False)
        payload["co_faculty"] = c.id in co_faculty_ids
        out.append(payload)
    return {"classrooms": out}


@router.post("/join")
async def join(
    body: JoinRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Students join with the student code, faculty with the faculty code.
    Admin never joins -- their access is global (brief §8).
    """
    if principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin does not need to join a classroom.",
        )

    key = body.idempotency_key or idempotency.derive_key("join", principal.id, body.join_code)
    try:
        claim = await idempotency.claim(db, user_id=principal.id, scope="join", key=key)
    except idempotency.DuplicateInFlight as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not claim.fresh:
        return claim.replayed_response or {}

    user = (await db.scalars(select(User).where(User.id == principal.id))).first()
    try:
        classroom = await classroom_service.join_classroom(
            db, user=user, join_code=body.join_code
        )
    except classroom_service.WrongCodeRole as exc:
        await idempotency.release(db, claim)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except classroom_service.JoinClosed as exc:
        await idempotency.release(db, claim)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except classroom_service.ClassroomError as exc:
        await idempotency.release(db, claim)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await audit.record(
        db, audit.MEMBERSHIP_JOINED, user_id=principal.id, classroom_id=classroom.id,
        detail={"role": principal.role.value},
    )
    payload = await _classroom_payload(db, classroom, include_codes=False)
    await idempotency.complete(db, claim, payload)
    await db.commit()
    return payload


@router.patch("/{classroom_id}")
async def rename_classroom(
    classroom_id: str,
    body: RenameClassroomRequest,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    classroom = await _get_classroom_or_404(db, classroom_id)
    old_name = classroom.name
    try:
        await classroom_service.rename_classroom(db, classroom, name=body.name)
    except classroom_service.ClassroomError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await audit.record(
        db, audit.CLASSROOM_RENAMED, user_id=principal.id, classroom_id=classroom.id,
        detail={"from": old_name, "to": classroom.name},
    )
    await db.commit()
    return await _classroom_payload(db, classroom, include_codes=True)


@router.delete("/{classroom_id}")
async def archive_classroom(
    classroom_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """"Delete" a class: archive it. Any live session is ended, the class
    leaves every list and can no longer be joined or started -- and every
    session, prompt, mark and summary is kept (see `Classroom.archived_at`)."""
    classroom = await _get_classroom_or_404(db, classroom_id)
    await classroom_service.archive_classroom(db, classroom, archived_by=principal.id)
    await audit.record(
        db, audit.CLASSROOM_ARCHIVED, user_id=principal.id, classroom_id=classroom.id,
        detail={"name": classroom.name},
    )
    await db.commit()
    return await _classroom_payload(db, classroom, include_codes=True)


@router.post("/{classroom_id}/restore")
async def restore_classroom(
    classroom_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    classroom = await _get_classroom_or_404(db, classroom_id)
    await classroom_service.restore_classroom(db, classroom)
    await audit.record(
        db, audit.CLASSROOM_RESTORED, user_id=principal.id, classroom_id=classroom.id,
        detail={"name": classroom.name},
    )
    await db.commit()
    return await _classroom_payload(db, classroom, include_codes=True)


@router.patch("/{classroom_id}/join-open")
async def set_join_open(
    classroom_id: str,
    body: JoinOpenRequest,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    classroom = await _get_classroom_or_404(db, classroom_id)
    await classroom_service.set_join_open(db, classroom, open_=body.join_open)
    await db.commit()
    return {"id": classroom.id, "join_open": classroom.join_open}


@router.post("/{classroom_id}/regenerate-code")
async def regenerate_code(
    classroom_id: str,
    body: RegenerateCodeRequest,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    classroom = await _get_classroom_or_404(db, classroom_id)
    await classroom_service.regenerate_join_code(db, classroom, which=body.which)
    await audit.record(
        db, audit.JOIN_CODE_REGENERATED, user_id=principal.id, classroom_id=classroom.id,
        detail={"which": body.which},
    )
    await db.commit()
    return await _classroom_payload(db, classroom, include_codes=True)


@router.get("/{classroom_id}/roster")
async def roster(
    classroom_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _get_classroom_or_404(db, classroom_id)
    rows = await classroom_service.roster_with_users(db, classroom_id)
    return {
        "students": [
            {"id": user.id, "email": user.email, "name": user.name,
             "joined_at": membership.joined_at.isoformat()}
            for membership, user in rows
        ]
    }


@router.get("/{classroom_id}/faculty")
async def faculty_roster(
    classroom_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _get_classroom_or_404(db, classroom_id)
    rows = await classroom_service.faculty_roster_with_users(db, classroom_id)
    from backend.auth.roles import role_for_email

    result = []
    for membership, user in rows:
        platform_role = (
            user.role_override if user.role_override is not None else role_for_email(user.email)
        )
        result.append({
            "id": user.id, "email": user.email, "name": user.name,
            "joined_at": membership.joined_at.isoformat(),
            # A co-faculty's platform role is still "student" -- lets the
            # frontend show a "Demote" button only for promoted rows, never
            # for a genuine faculty peer (admin-only removal for those).
            "promoted": platform_role == Role.STUDENT,
        })
    return {"faculty": result}


class PromoteRequest(BaseModel):
    student_user_id: str


class DemoteRequest(BaseModel):
    user_id: str


@router.post("/{classroom_id}/promote", status_code=status.HTTP_201_CREATED)
async def promote_to_class_faculty(
    classroom_id: str,
    body: PromoteRequest,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _get_classroom_or_404(db, classroom_id)
    try:
        await classroom_service.promote_student_to_class_faculty(
            db, classroom_id, target_user_id=body.student_user_id
        )
    except classroom_service.NotEnrolled as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await audit.record(
        db, audit.CLASS_FACULTY_PROMOTED, user_id=principal.id, classroom_id=classroom_id,
        detail={"target_user_id": body.student_user_id},
    )
    await db.commit()
    return {"promoted": True}


@router.post("/{classroom_id}/demote")
async def demote_from_class_faculty(
    classroom_id: str,
    body: DemoteRequest,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _get_classroom_or_404(db, classroom_id)
    try:
        await classroom_service.demote_class_faculty_to_student(
            db, classroom_id, target_user_id=body.user_id
        )
    except classroom_service.NotCoFacultyEligible as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except classroom_service.NotEnrolled as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await audit.record(
        db, audit.CLASS_FACULTY_DEMOTED, user_id=principal.id, classroom_id=classroom_id,
        detail={"target_user_id": body.user_id},
    )
    await db.commit()
    return {"demoted": True}


@router.delete("/{classroom_id}/faculty/{user_id}")
async def remove_faculty_member(
    classroom_id: str,
    user_id: str,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Admin-only: faculty cannot remove each other, only admin can."""
    await classroom_service.remove_faculty(db, classroom_id, user_id=user_id)
    await audit.record(
        db, audit.MEMBERSHIP_REMOVED, user_id=principal.id, classroom_id=classroom_id,
        detail={"removed_user_id": user_id, "role": "faculty"},
    )
    await db.commit()
    return {"removed": True}


@router.get("/{classroom_id}/active-session")
async def active_session(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Any authenticated member (student/faculty/admin) may check whether a
    session is active -- used by the frontend to know when to stop letting
    the student act inside a session that just ended.

    Membership-gated (found missing and fixed in a security pass): the
    docstring always said "member" but the implementation never checked
    membership, so any authenticated user could query any classroom_id --
    including one they have no relationship to -- and learn whether a
    session is active and which experiment is running. Low-severity (no
    student PII), but a real cross-classroom information-disclosure gap
    inconsistent with every other route in this file.
    """
    if principal.is_admin:
        pass
    elif await classroom_service.can_act_as_faculty(db, principal, classroom_id):
        pass
    elif principal.is_student:
        if not await StudentScope(db, principal.id).is_enrolled(classroom_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
        )

    session = await classroom_service.get_active_session(db, classroom_id)
    if session is None:
        return {"active": False}
    return {
        "active": True,
        "session_id": session.id,
        "experiment_id": session.experiment_id,
        "started_at": session.started_at.isoformat(),
    }


@router.post("/{classroom_id}/sessions/start", status_code=status.HTTP_201_CREATED)
async def start_class_session(
    classroom_id: str,
    body: StartSessionRequest,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _get_classroom_or_404(db, classroom_id)
    try:
        session = await classroom_service.start_session(
            db, classroom_id, experiment_id=body.experiment_id, started_by=principal.id
        )
    except classroom_service.SessionAlreadyActive as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except classroom_service.ClassroomError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await audit.record(
        db, audit.SESSION_STARTED, user_id=principal.id, classroom_id=classroom_id,
        class_session_id=session.id, detail={"experiment_id": session.experiment_id},
    )
    await db.commit()
    return {"session_id": session.id, "experiment_id": session.experiment_id}


@router.post("/{classroom_id}/sessions/{session_id}/end")
async def end_class_session(
    classroom_id: str,
    session_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _get_classroom_or_404(db, classroom_id)
    session = await classroom_service.get_active_session(db, classroom_id)
    if session is None or session.id != session_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That session is not active."
        )
    await classroom_service.end_session(db, session, ended_by=principal.id)
    await audit.record(
        db, audit.SESSION_ENDED, user_id=principal.id, classroom_id=classroom_id,
        class_session_id=session.id,
    )
    await db.commit()

    # No separate "generate summary" click required (brief §19/§28).
    from backend.summaries import enqueue_for_session

    await enqueue_for_session(db, class_session_id=session.id, requested_by=principal.id)

    return {"session_id": session.id, "status": "ended"}
