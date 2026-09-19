"""Faculty/admin dashboard routes.

Every route is faculty-or-admin-gated. Faculty routes are additionally
membership-scoped: `FacultyScope` restricts each query to classrooms this
account is an active FACULTY member of, so one section's staff cannot
read another's. Admin bypasses membership scoping (global authority) but
never bypasses the role check itself.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend import audit, idempotency
from backend.auth import Principal, classroom_faculty_scope, current_user
from backend.classrooms import roster_with_users
from backend.data_access import FacultyScope
from backend.db import get_session
from backend.models import (
    ActorType,
    AuditLog,
    ChatMessage,
    ClassSession,
    Diagnosis,
    Escalation,
    LoginSession,
    SocraticAttempt,
    SocraticSession,
    StudentSummary,
    Submission,
    SummaryJob,
    User,
)
from backend.summaries import run_job, start_job_for_session, track_background_task
from backend.summaries.coverage import compute_topic_coverage
from backend.summaries.trajectory import build_trajectory

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class GenerateSummariesRequest(BaseModel):
    #: Named students to regenerate. Empty means "only those not yet done",
    #: which is what makes re-triggering free.
    refresh_student_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ResolveRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


async def _classroom_or_404(
    db: AsyncSession, principal: Principal, scope: FacultyScope, classroom_id: str
):
    from backend.models import Classroom

    if principal.is_admin:
        classroom = (
            await db.scalars(select(Classroom).where(Classroom.id == classroom_id))
        ).first()
    else:
        classroom = await scope.get_classroom(classroom_id)
    if classroom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Classroom not found"
        )
    return classroom


def _scoped_select(principal: Principal, scope: FacultyScope, model):
    """Admin sees everything; faculty only their own classrooms' rows."""
    if principal.is_admin:
        return select(model)
    return scope.select(model)


@router.get("/classrooms/{classroom_id}/submissions")
async def submissions(
    classroom_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """All submissions in a classroom with pass/fail/escalated status."""
    await _classroom_or_404(db, principal, scope, classroom_id)

    stmt = _scoped_select(principal, scope, Submission).where(
        Submission.classroom_id == classroom_id
    )
    rows = list((await db.scalars(stmt)).all())
    diag_rows = list(
        (
            await db.scalars(
                _scoped_select(principal, scope, Diagnosis).where(
                    Diagnosis.classroom_id == classroom_id
                )
            )
        ).all()
    )
    diagnoses = {d.submission_id: d for d in diag_rows}
    emails = {
        u.id: u.email
        for u in (await db.scalars(select(User))).all()
    }

    out = []
    for submission in sorted(rows, key=lambda s: s.created_at, reverse=True):
        diagnosis = diagnoses.get(submission.id)
        record = {
            "submission_id": submission.id,
            "student_id": submission.student_id,
            "student_email": emails.get(submission.student_id, ""),
            "experiment_id": submission.experiment_id,
            "actor_type": submission.actor_type.value,
            "created_at": submission.created_at.isoformat(),
            "status": diagnosis.status.value if diagnosis else "pending",
            "tier": diagnosis.tier if diagnosis else None,
            "signature": diagnosis.signature_code if diagnosis else None,
            "expected_value": diagnosis.expected_value if diagnosis else None,
            "reported_value": submission.reported_value,
            "explanation": diagnosis.phrased_text if diagnosis else "",
            "low_confidence": diagnosis.low_confidence if diagnosis else False,
        }
        if status_filter and record["status"] != status_filter:
            continue
        out.append(record)
    return {"submissions": out}


@router.get("/classrooms/{classroom_id}/escalations")
async def escalations(
    classroom_id: str,
    unresolved_only: bool = Query(default=True),
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The Tier 3 review queue -- the cases needing a human during the pilot."""
    await _classroom_or_404(db, principal, scope, classroom_id)
    stmt = _scoped_select(principal, scope, Escalation).where(
        Escalation.classroom_id == classroom_id
    )
    if unresolved_only:
        stmt = stmt.where(Escalation.resolved.is_(False))
    rows = list((await db.scalars(stmt)).all())

    diagnoses = {
        d.id: d
        for d in (
            await db.scalars(
                _scoped_select(principal, scope, Diagnosis).where(
                    Diagnosis.classroom_id == classroom_id
                )
            )
        ).all()
    }
    emails = {u.id: u.email for u in (await db.scalars(select(User))).all()}

    return {
        "escalations": [
            {
                "id": e.id,
                "student_id": e.student_id,
                "student_email": emails.get(e.student_id, ""),
                "reason": e.reason,
                "resolved": e.resolved,
                "created_at": e.created_at.isoformat(),
                "expected_value": (
                    diagnoses[e.diagnosis_id].expected_value
                    if e.diagnosis_id in diagnoses
                    else None
                ),
                "reported_value": (
                    diagnoses[e.diagnosis_id].reported_value
                    if e.diagnosis_id in diagnoses
                    else None
                ),
                "experiment_id": (
                    diagnoses[e.diagnosis_id].detail.get("experiment")
                    if e.diagnosis_id in diagnoses
                    else None
                ),
            }
            for e in sorted(rows, key=lambda e: e.created_at, reverse=True)
        ]
    }


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str,
    body: ResolveRequest,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    if principal.is_admin:
        escalation = (
            await db.scalars(select(Escalation).where(Escalation.id == escalation_id))
        ).first()
    else:
        escalation = await scope.get(Escalation, escalation_id)
    if escalation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escalation not found"
        )
    escalation.resolved = True
    escalation.resolved_by = principal.id
    escalation.resolution_note = body.note or None
    await audit.record(
        db, audit.ESCALATION_RESOLVED, user_id=principal.id,
        classroom_id=escalation.classroom_id,
        detail={"escalation_id": escalation.id, "note": body.note or ""},
    )
    await db.commit()
    return {"id": escalation.id, "resolved": True}


@router.get("/audit")
async def audit_log(
    event: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Diagnoses, escalations and auth failures, newest first.

    Scoped: a faculty account sees only events tagged with a classroom_id
    it belongs to, plus its own account-level events (classroom_id null,
    e.g. its own auth failures). Only admin sees every classroom's events.
    Previously this route had no ownership predicate at all -- a
    cross-classroom information leak, fixed here.
    """
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if event:
        stmt = stmt.where(AuditLog.event == event)
    if not principal.is_admin:
        member_ids = list((await db.scalars(scope._member_classroom_ids())).all())
        stmt = stmt.where(
            (AuditLog.classroom_id.in_(member_ids))
            | (AuditLog.classroom_id.is_(None) & (AuditLog.user_id == principal.id))
        )
    rows = list((await db.scalars(stmt)).all())
    return {
        "events": [
            {
                "id": r.id,
                "event": r.event,
                "user_id": r.user_id,
                "classroom_id": r.classroom_id,
                "class_session_id": r.class_session_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post(
    "/classrooms/{classroom_id}/sessions/{class_session_id}/summaries",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_summaries(
    classroom_id: str,
    class_session_id: str,
    body: GenerateSummariesRequest,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Manual (re)generation for a specific class session. Ending a class
    already triggers this automatically (see classroom_routes.py) -- this
    route exists for backfill/refresh, not as a required extra click.
    """
    await _classroom_or_404(db, principal, scope, classroom_id)
    session_row = (
        await db.scalars(select(ClassSession).where(ClassSession.id == class_session_id))
    ).first()
    if session_row is None or session_row.classroom_id != classroom_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Class session not found"
        )

    key = body.idempotency_key or idempotency.derive_key(
        "summaries", class_session_id, sorted(body.refresh_student_ids)
    )
    try:
        claim = await idempotency.claim(
            db, user_id=principal.id, scope="summaries", key=key
        )
    except idempotency.DuplicateInFlight as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not claim.fresh:
        return claim.replayed_response or {}

    roster = await roster_with_users(db, classroom_id)
    student_ids = [user.id for _, user in roster]

    if body.refresh_student_ids:
        await scope.purge_summaries(class_session_id, body.refresh_student_ids)

    job = await start_job_for_session(
        db,
        class_session_id=class_session_id,
        classroom_id=classroom_id,
        experiment_id=session_row.experiment_id,
        requested_by=principal.id,
        student_ids=student_ids,
    )
    payload = {"job_id": job.id, "total": job.total, "status": job.status}
    await idempotency.complete(db, claim, payload)
    await db.commit()

    import asyncio

    from backend.config import get_settings

    task = asyncio.create_task(run_job(job.id, student_ids, workers=get_settings().summary_workers))
    track_background_task(task)
    return payload


@router.get("/summaries/jobs/{job_id}")
async def summary_job_status(
    job_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Progress for the visible status indicator."""
    job = (await db.scalars(select(SummaryJob).where(SummaryJob.id == job_id))).first()
    if job is None or not (principal.is_admin or await scope.is_member(job.classroom_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "total": job.total,
        "completed": job.completed,
        "skipped": job.skipped,
        "error": job.error,
    }


@router.get("/classrooms/{classroom_id}/sessions")
async def list_class_sessions(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Every class meeting (ended or active) for this classroom, newest
    first -- the picker the summaries/history tab needs once a session has
    ended and `/active-session` no longer names it. There was previously
    no way for the frontend to discover a past session's id at all.
    """
    await _classroom_or_404(db, principal, scope, classroom_id)
    rows = list(
        (
            await db.scalars(
                select(ClassSession)
                .where(ClassSession.classroom_id == classroom_id)
                .order_by(ClassSession.started_at.desc())
            )
        ).all()
    )
    return {
        "sessions": [
            {
                "id": s.id,
                "experiment_id": s.experiment_id,
                "status": s.status.value,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            }
            for s in rows
        ]
    }


@router.get("/classrooms/{classroom_id}/sessions/{class_session_id}/summaries")
async def list_summaries(
    classroom_id: str,
    class_session_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Faculty/admin-visible only. No student route returns these."""
    await _classroom_or_404(db, principal, scope, classroom_id)
    rows = list(
        (
            await db.scalars(
                select(StudentSummary).where(
                    StudentSummary.classroom_id == classroom_id,
                    StudentSummary.class_session_id == class_session_id,
                )
            )
        ).all()
    )
    emails = {u.id: u.email for u in (await db.scalars(select(User))).all()}
    return {
        "summaries": [
            {
                "student_id": s.student_id,
                "student_email": emails.get(s.student_id, ""),
                "experiment_id": s.experiment_id,
                "text": s.text,
                "flagged": s.flagged,
                "flag_reason": s.flag_reason,
                "generated_at": s.generated_at.isoformat(),
            }
            for s in sorted(rows, key=lambda s: emails.get(s.student_id, ""))
        ]
    }


@router.get("/classrooms/{classroom_id}/students/{student_id}/coverage")
async def student_coverage(
    classroom_id: str,
    student_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Rough, deterministic per-experiment engagement indicator -- NOT a
    grade, never LLM-produced (see backend/summaries/coverage.py)."""
    await _classroom_or_404(db, principal, scope, classroom_id)
    rows = await compute_topic_coverage(db, classroom_id, student_id)
    return {"student_id": student_id, "topics": [r.as_dict() for r in rows]}


@router.get("/classrooms/{classroom_id}/coverage")
async def classroom_coverage(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Whole-class rollup: one row per (student, experiment) with any
    recorded activity."""
    classroom = await _classroom_or_404(db, principal, scope, classroom_id)
    roster = await roster_with_users(db, classroom.id)
    out = []
    for _membership, user in roster:
        rows = await compute_topic_coverage(db, classroom_id, user.id)
        out.append(
            {
                "student_id": user.id,
                "student_email": user.email,
                "student_name": user.name,
                "topics": [r.as_dict() for r in rows],
            }
        )
    return {"students": out}


def _aware(value):
    """SQLite hands back naive datetimes for tz-aware columns; Postgres
    doesn't. Normalise so durations can be computed either way."""
    import datetime as dt

    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


@router.get("/classrooms/{classroom_id}/activity")
async def classroom_activity(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Everything the research export holds, as JSON for the Activity &
    Data page: per-student rollup (logins, time on system, prompt counts,
    model latency/tokens) plus the raw login-session rows. Same access
    rule as the export -- faculty of this classroom, or admin."""
    classroom = await _classroom_or_404(db, principal, scope, classroom_id)
    roster = await roster_with_users(db, classroom.id)
    users_by_id = {user.id: user for _membership, user in roster}

    login_rows = list(
        (
            await db.scalars(
                select(LoginSession)
                .where(LoginSession.user_id.in_(users_by_id.keys()))
                .order_by(LoginSession.login_at.desc())
            )
        ).all()
    )
    sessions_out = []
    per_student: dict[str, dict] = {
        uid: {
            "student_id": uid,
            "name": u.name,
            "email": u.email,
            "reg_no": u.reg_no,
            "logins": 0,
            "last_login_at": None,
            "last_seen_at": None,
            "active_seconds": 0,
            "prompts_total": 0,
            "prompts_by_kind": {},
            "experiments": set(),
            "_latencies": [],
            "_responses": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        for uid, u in users_by_id.items()
    }
    for row in login_rows:
        login_at = _aware(row.login_at)
        end = _aware(row.logout_at) or _aware(row.last_seen_at)
        duration = max(0, int((end - login_at).total_seconds())) if end else 0
        stat = per_student[row.user_id]
        stat["logins"] += 1
        stat["active_seconds"] += duration
        if stat["last_login_at"] is None or login_at.isoformat() > stat["last_login_at"]:
            stat["last_login_at"] = login_at.isoformat()
        seen = _aware(row.last_seen_at)
        if seen and (stat["last_seen_at"] is None or seen.isoformat() > stat["last_seen_at"]):
            stat["last_seen_at"] = seen.isoformat()
        u = users_by_id[row.user_id]
        sessions_out.append(
            {
                "student_id": row.user_id,
                "name": u.name,
                "email": u.email,
                "reg_no": u.reg_no,
                "login_at": login_at.isoformat(),
                "logout_at": _aware(row.logout_at).isoformat() if row.logout_at else None,
                "last_seen_at": seen.isoformat() if seen else None,
                "duration_seconds": duration,
                "end_reason": row.end_reason or "inferred timeout",
            }
        )

    for count in await FacultyScope(db, principal.id).prompt_counts(classroom_id):
        stat = per_student.get(count.student_id)
        if stat is None:
            continue
        stat["prompts_total"] += count.count
        stat["prompts_by_kind"][count.kind] = stat["prompts_by_kind"].get(count.kind, 0) + count.count
        stat["experiments"].add(count.experiment_id)

    tutor_rows = (
        await db.scalars(
            select(ChatMessage).where(
                ChatMessage.classroom_id == classroom_id,
                ChatMessage.actor_type == ActorType.STUDENT,
                ChatMessage.author == "tutor",
            )
        )
    ).all()
    for msg in tutor_rows:
        stat = per_student.get(msg.student_id)
        if stat is None:
            continue
        meta = msg.metadata_json or {}
        if isinstance(meta.get("llm_latency_ms"), (int, float)):
            stat["_latencies"].append(meta["llm_latency_ms"])
        if isinstance(meta.get("response_ms"), (int, float)):
            stat["_responses"].append(meta["response_ms"])
        stat["prompt_tokens"] += meta.get("prompt_tokens") or 0
        stat["completion_tokens"] += meta.get("completion_tokens") or 0

    def _avg(values: list) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    students_out = []
    for stat in per_student.values():
        stat["avg_llm_latency_ms"] = _avg(stat.pop("_latencies"))
        stat["avg_response_ms"] = _avg(stat.pop("_responses"))
        stat["experiments"] = sorted(stat["experiments"])
        students_out.append(stat)
    students_out.sort(key=lambda s: (-s["prompts_total"], s["name"] or s["email"]))

    all_lat = [s["avg_llm_latency_ms"] for s in students_out if s["avg_llm_latency_ms"] is not None]
    totals = {
        "students": len(students_out),
        "students_with_activity": sum(1 for s in students_out if s["prompts_total"] or s["logins"]),
        "logins": sum(s["logins"] for s in students_out),
        "prompts": sum(s["prompts_total"] for s in students_out),
        "active_seconds": sum(s["active_seconds"] for s in students_out),
        "prompt_tokens": sum(s["prompt_tokens"] for s in students_out),
        "completion_tokens": sum(s["completion_tokens"] for s in students_out),
        "avg_llm_latency_ms": _avg(all_lat),
    }
    return {
        "classroom": {"id": classroom.id, "name": classroom.name},
        "totals": totals,
        "students": students_out,
        "sessions": sessions_out[:500],
    }


async def _trajectory_rows_for_classroom(
    db: AsyncSession, classroom_id: str
) -> list[tuple[str, str, object]]:
    """One (student_id, class_session_id, Trajectory) tuple per pair with
    any recorded activity, across every class session this classroom has
    ever run -- the same deterministic counting `backend/summaries/jobs.py`
    does for one session's summary job, just rolled up across all of them
    for the research export. Skips empty pairs (a student who never
    touched that particular session) so the sheet isn't mostly blank rows.
    """
    sessions = list(
        (
            await db.scalars(
                select(ClassSession).where(ClassSession.classroom_id == classroom_id)
            )
        ).all()
    )
    roster = await roster_with_users(db, classroom_id)
    rows: list[tuple[str, str, object]] = []
    for class_session in sessions:
        for _membership, user in roster:
            attempts = list(
                (
                    await db.scalars(
                        select(SocraticAttempt)
                        .join(SocraticSession, SocraticSession.id == SocraticAttempt.session_id)
                        .where(
                            SocraticAttempt.student_id == user.id,
                            SocraticSession.class_session_id == class_session.id,
                            SocraticSession.actor_type == ActorType.STUDENT,
                        )
                    )
                ).all()
            )
            messages = list(
                (
                    await db.scalars(
                        select(ChatMessage).where(
                            ChatMessage.student_id == user.id,
                            ChatMessage.class_session_id == class_session.id,
                            ChatMessage.actor_type == ActorType.STUDENT,
                        )
                    )
                ).all()
            )
            submissions = list(
                (
                    await db.scalars(
                        select(Submission).where(
                            Submission.student_id == user.id,
                            Submission.class_session_id == class_session.id,
                            Submission.actor_type == ActorType.STUDENT,
                        )
                    )
                ).all()
            )
            diagnoses = list(
                (
                    await db.scalars(
                        select(Diagnosis).where(
                            Diagnosis.student_id == user.id,
                            Diagnosis.class_session_id == class_session.id,
                        )
                    )
                ).all()
            )
            session_row = (
                await db.scalars(
                    select(SocraticSession).where(
                        SocraticSession.student_id == user.id,
                        SocraticSession.class_session_id == class_session.id,
                    )
                )
            ).first()
            traj = build_trajectory(
                user.id,
                attempts=attempts,
                messages=messages,
                submissions=submissions,
                diagnoses=diagnoses,
                all_steps_complete=bool(session_row and session_row.all_steps_complete),
            )
            if not traj.is_empty:
                rows.append((user.id, class_session.id, traj))
    return rows


@router.get("/classrooms/{classroom_id}/research-export.xlsx")
async def research_export(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """One workbook combining everything a research write-up on this
    tool's effectiveness needs: who used it and for how long (Sessions),
    how much they engaged (Prompt counts), the deterministic learning-
    trajectory counts (Trajectory -- the same numbers that already back
    the LLM-phrased per-student summaries, just surfaced as data instead
    of prose), and the pre/post-test scores (Marks, reusing the marks
    endpoint's own export logic so faculty get one download instead of
    two).
    """
    from backend.api import marks_routes

    classroom = await _classroom_or_404(db, principal, scope, classroom_id)
    roster = await roster_with_users(db, classroom.id)
    users_by_id = {user.id: user for _membership, user in roster}

    workbook = Workbook()

    roster_sheet = workbook.active
    roster_sheet.title = "Roster"
    roster_sheet.append(["Student name", "Student email", "Reg no", "Joined at"])
    for membership, user in roster:
        roster_sheet.append(
            [user.name, user.email, user.reg_no, membership.joined_at.isoformat()]
        )

    sessions_sheet = workbook.create_sheet("Sessions")
    sessions_sheet.append(
        ["Student name", "Student email", "Login at", "Logout at", "Last seen at", "End reason"]
    )
    login_sessions = list(
        (
            await db.scalars(
                select(LoginSession)
                .where(LoginSession.user_id.in_(users_by_id.keys()))
                .order_by(LoginSession.login_at)
            )
        ).all()
    )
    for row in login_sessions:
        user = users_by_id.get(row.user_id)
        sessions_sheet.append(
            [
                user.name if user else row.user_id,
                user.email if user else "",
                row.login_at.isoformat(),
                row.logout_at.isoformat() if row.logout_at else None,
                row.last_seen_at.isoformat(),
                row.end_reason or "inferred timeout",
            ]
        )

    prompts_sheet = workbook.create_sheet("Prompt counts")
    prompts_sheet.append(
        ["Student name", "Student email", "Experiment", "Class session", "Kind", "Count"]
    )
    faculty_scope = FacultyScope(db, principal.id)
    for count in await faculty_scope.prompt_counts(classroom_id):
        user = users_by_id.get(count.student_id)
        prompts_sheet.append(
            [
                user.name if user else count.student_id,
                user.email if user else "",
                count.experiment_id,
                count.class_session_id,
                count.kind,
                count.count,
            ]
        )

    trajectory_sheet = workbook.create_sheet("Trajectory")
    trajectory_sheet.append(
        [
            "Student name", "Student email", "Class session", "Completed",
            "Total attempts", "Steps attempted", "Steps passed",
            "Passed first try", "Self-corrected", "Told directly",
            "Total hints", "Max attempts on one step",
            "Student messages", "Submissions", "Diagnoses failed", "Diagnoses escalated",
        ]
    )
    for student_id, class_session_id, traj in await _trajectory_rows_for_classroom(
        db, classroom_id
    ):
        user = users_by_id.get(student_id)
        trajectory_sheet.append(
            [
                user.name if user else student_id,
                user.email if user else "",
                class_session_id,
                traj.completed,
                traj.total_attempts,
                traj.steps_attempted,
                traj.steps_passed,
                traj.first_try_steps,
                traj.self_corrected_steps,
                traj.told_directly_steps,
                traj.total_hints,
                traj.max_attempts_on_one_step,
                traj.student_messages,
                traj.submissions,
                traj.diagnoses_failed,
                traj.diagnoses_escalated,
            ]
        )

    marks_sheet = workbook.create_sheet("Marks")
    marks_sheet.append(
        [
            "Experiment", "Student name", "Student email",
            "Pre-test", "Pre-test max", "Post-test", "Post-test max", "Gain",
        ]
    )
    by_experiment = await marks_routes._all_marks_by_experiment(db, classroom_id)
    for experiment_id, rows in sorted(by_experiment.items()):
        for row in sorted(rows, key=lambda r: users_by_id.get(r.student_id).email if users_by_id.get(r.student_id) else ""):
            user = users_by_id.get(row.student_id)
            gain = (
                row.post_test_marks - row.pre_test_marks
                if row.pre_test_marks is not None and row.post_test_marks is not None
                else None
            )
            marks_sheet.append(
                [
                    experiment_id,
                    user.name if user else row.student_id,
                    user.email if user else "",
                    row.pre_test_marks,
                    row.pre_test_max,
                    row.post_test_marks,
                    row.post_test_max,
                    gain,
                ]
            )

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"labtutor_research_export_{classroom.name.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
