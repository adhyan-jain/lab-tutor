"""Detailed reports for a class's past sessions.

Faculty/admin only, and only for classrooms they may act on
(`require_classroom_faculty`). A student can never reach these routes, and a
session or student id that does not belong to the classroom in the URL is a
404, never a cross-class read. Opening a student's full transcript is
recorded in the audit log.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit
from backend.api.classroom_routes import require_classroom_faculty
from backend.auth import Principal
from backend.db import get_session
from backend.models import (
    ActorType,
    ChatMessage,
    ClassSession,
    Diagnosis,
    ExperimentMarks,
    SocraticAttempt,
    SocraticSession,
    StudentSummary,
    User,
)
from backend.tier1_compute.experiments import get_plugin

router = APIRouter(prefix="/api/classrooms", tags=["session-reports"])

#: The only message-metadata keys a report exposes -- research/QA facts, not
#: raw internals.
_META_KEYS = (
    "type",
    "status",
    "answer_source",
    "intent",
    "llm_latency_ms",
    "llm_calls",
    "retry_count",
    "fallback_used",
    "fallback_reason",
    "cache_hit",
    "tier",
)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _iso(value: dt.datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _experiment_title(experiment_id: str) -> str:
    try:
        return get_plugin(experiment_id).title
    except Exception:
        return experiment_id


async def _session_or_404(db: AsyncSession, classroom_id: str, session_id: str) -> ClassSession:
    row = (
        await db.scalars(
            select(ClassSession).where(
                ClassSession.id == session_id, ClassSession.classroom_id == classroom_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return row


@router.get("/{classroom_id}/sessions")
async def list_sessions(
    classroom_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    sessions = list(
        (
            await db.scalars(
                select(ClassSession)
                .where(ClassSession.classroom_id == classroom_id)
                .order_by(ClassSession.started_at.desc())
            )
        ).all()
    )
    counts = {
        row.class_session_id: (row.prompts, row.students)
        for row in (
            await db.execute(
                select(
                    ChatMessage.class_session_id,
                    func.count().label("prompts"),
                    func.count(func.distinct(ChatMessage.student_id)).label("students"),
                )
                .where(
                    ChatMessage.classroom_id == classroom_id,
                    ChatMessage.actor_type == ActorType.STUDENT,
                    ChatMessage.author == "student",
                    ChatMessage.class_session_id.is_not(None),
                )
                .group_by(ChatMessage.class_session_id)
            )
        ).all()
    }
    starter_ids = {s.started_by for s in sessions}
    names: dict[str, str] = {}
    if starter_ids:
        names = {
            u.id: (u.name or u.email)
            for u in (await db.scalars(select(User).where(User.id.in_(starter_ids)))).all()
        }
    out = []
    for s in sessions:
        prompts, students = counts.get(s.id, (0, 0))
        duration = None
        if s.ended_at is not None:
            duration = round((_aware(s.ended_at) - _aware(s.started_at)).total_seconds() / 60, 1)
        out.append(
            {
                "id": s.id,
                "experiment_id": s.experiment_id,
                "experiment_title": _experiment_title(s.experiment_id),
                "status": s.status.value,
                "started_at": _iso(s.started_at),
                "ended_at": _iso(s.ended_at),
                "duration_minutes": duration,
                "started_by": names.get(s.started_by, ""),
                "students": students,
                "prompts": prompts,
            }
        )
    return {"sessions": out}


@router.get("/{classroom_id}/sessions/{session_id}/report")
async def session_report(
    classroom_id: str,
    session_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    session = await _session_or_404(db, classroom_id, session_id)

    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.class_session_id == session_id,
                    ChatMessage.classroom_id == classroom_id,
                    ChatMessage.actor_type == ActorType.STUDENT,
                )
                .order_by(ChatMessage.created_at)
            )
        ).all()
    )
    student_msgs: dict[str, list[ChatMessage]] = defaultdict(list)
    tutor_stats: dict[str, dict] = defaultdict(
        lambda: {"replies": 0, "latency": [], "fallbacks": 0, "llm_calls": 0}
    )
    for m in messages:
        if m.author == "student":
            student_msgs[m.student_id].append(m)
            continue
        meta = m.metadata_json or {}
        stats = tutor_stats[m.student_id]
        stats["replies"] += 1
        if isinstance(meta.get("llm_latency_ms"), (int, float)):
            stats["latency"].append(meta["llm_latency_ms"])
        if meta.get("fallback_used"):
            stats["fallbacks"] += 1
        if isinstance(meta.get("llm_calls"), int):
            stats["llm_calls"] += meta["llm_calls"]

    attempts_by_student: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for student_id, passed in (
        await db.execute(
            select(SocraticAttempt.student_id, SocraticAttempt.passed)
            .join(SocraticSession, SocraticSession.id == SocraticAttempt.session_id)
            .where(
                SocraticSession.class_session_id == session_id,
                SocraticSession.classroom_id == classroom_id,
            )
        )
    ).all():
        attempts_by_student[student_id][0] += 1
        attempts_by_student[student_id][1] += 1 if passed else 0

    diagnoses_by_student: dict[str, list[dict]] = defaultdict(list)
    for d in (
        await db.scalars(
            select(Diagnosis)
            .where(Diagnosis.class_session_id == session_id, Diagnosis.classroom_id == classroom_id)
            .order_by(Diagnosis.created_at)
        )
    ).all():
        diagnoses_by_student[d.student_id].append(
            {
                "status": d.status.value,
                "tier": d.tier,
                "signature_code": d.signature_code,
                "action": d.action.value,
                "low_confidence": d.low_confidence,
                "created_at": _iso(d.created_at),
            }
        )

    summaries = {
        s.student_id: s
        for s in (
            await db.scalars(
                select(StudentSummary).where(
                    StudentSummary.class_session_id == session_id,
                    StudentSummary.classroom_id == classroom_id,
                )
            )
        ).all()
    }
    marks = {
        m.student_id: m
        for m in (
            await db.scalars(
                select(ExperimentMarks).where(
                    ExperimentMarks.classroom_id == classroom_id,
                    ExperimentMarks.experiment_id == session.experiment_id,
                )
            )
        ).all()
    }

    student_ids = set(student_msgs) | set(diagnoses_by_student) | set(summaries)
    users: dict[str, User] = {}
    if student_ids:
        users = {
            u.id: u for u in (await db.scalars(select(User).where(User.id.in_(student_ids)))).all()
        }

    rows = []
    for student_id in student_ids:
        user = users.get(student_id)
        sent = student_msgs.get(student_id, [])
        attempts = attempts_by_student.get(student_id, [0, 0])
        stats = tutor_stats.get(student_id)
        summary = summaries.get(student_id)
        student_marks = marks.get(student_id)
        rows.append(
            {
                "student_id": student_id,
                "name": (user.name if user else "") or (user.email if user else ""),
                "email": user.email if user else "",
                "reg_no": user.reg_no if user else None,
                "prompts": len(sent),
                "first_at": _iso(sent[0].created_at) if sent else None,
                "last_at": _iso(sent[-1].created_at) if sent else None,
                "tutor_replies": stats["replies"] if stats else 0,
                "avg_latency_ms": (
                    round(sum(stats["latency"]) / len(stats["latency"]), 1)
                    if stats and stats["latency"]
                    else None
                ),
                "fallback_replies": stats["fallbacks"] if stats else 0,
                "llm_calls": stats["llm_calls"] if stats else 0,
                "attempts": attempts[0],
                "attempts_passed": attempts[1],
                "diagnoses": diagnoses_by_student.get(student_id, []),
                "summary": summary.text if summary else None,
                "summary_flagged": bool(summary.flagged) if summary else False,
                "marks": (
                    {
                        "pre": student_marks.pre_test_marks,
                        "pre_max": student_marks.pre_test_max,
                        "post": student_marks.post_test_marks,
                        "post_max": student_marks.post_test_max,
                    }
                    if student_marks
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: (r["name"] or "").lower())

    return {
        "session": {
            "id": session.id,
            "experiment_id": session.experiment_id,
            "experiment_title": _experiment_title(session.experiment_id),
            "status": session.status.value,
            "started_at": _iso(session.started_at),
            "ended_at": _iso(session.ended_at),
        },
        "totals": {
            "students": len(rows),
            "prompts": sum(r["prompts"] for r in rows),
            "attempts": sum(r["attempts"] for r in rows),
            "diagnoses": sum(len(r["diagnoses"]) for r in rows),
            "fallback_replies": sum(r["fallback_replies"] for r in rows),
        },
        "students": rows,
    }


@router.get("/{classroom_id}/sessions/{session_id}/students/{student_id}/transcript")
async def student_transcript(
    classroom_id: str,
    session_id: str,
    student_id: str,
    principal: Principal = Depends(require_classroom_faculty),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _session_or_404(db, classroom_id, session_id)
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.class_session_id == session_id,
                    ChatMessage.classroom_id == classroom_id,
                    ChatMessage.student_id == student_id,
                    ChatMessage.actor_type == ActorType.STUDENT,
                )
                .order_by(ChatMessage.created_at)
            )
        ).all()
    )
    if not messages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No transcript found")
    user = (await db.scalars(select(User).where(User.id == student_id))).first()
    await audit.record(
        db,
        audit.TRANSCRIPT_VIEWED,
        user_id=principal.id,
        classroom_id=classroom_id,
        class_session_id=session_id,
        detail={"student_id": student_id},
    )
    await db.commit()
    return {
        "student": {
            "id": student_id,
            "name": (user.name if user else "") or (user.email if user else ""),
            "email": user.email if user else "",
            "reg_no": user.reg_no if user else None,
        },
        "messages": [
            {
                "id": m.id,
                "author": m.author,
                "kind": m.kind.value,
                "content": m.content,
                "created_at": _iso(m.created_at),
                "meta": {
                    k: (m.metadata_json or {})[k] for k in _META_KEYS if k in (m.metadata_json or {})
                },
                "citations": len((m.metadata_json or {}).get("citations") or []),
            }
            for m in messages
        ],
    }
