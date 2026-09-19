"""Audit logging.

Every diagnosis, every Tier 3 escalation and every auth failure is
recorded with a timestamp and, where one is known, a user id. The
professor/TA dashboard queries this table directly
(`GET /api/dashboard/audit`).

Writes are best-effort: an audit failure must never take down the request
it was describing, so exceptions are logged and swallowed. That trade-off
is deliberate and worth knowing about -- this log is for review and for
the semester's evaluation work, not for anything that must be
tamper-evident.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AuditLog

log = logging.getLogger(__name__)

# Event names, kept in one place so dashboard filters cannot drift.
DIAGNOSIS_MADE = "diagnosis.made"
TIER3_ESCALATION = "tier3.escalation"
AUTH_FAILURE = "auth.failure"
AUTH_SUCCESS = "auth.success"
ANSWER_GATE_REDACTION = "answer_gate.redaction"
REVEAL_GRANTED = "socratic.reveal"
RATE_LIMITED = "ratelimit.blocked"
#: A student reported an injury, asked whether something was safe, or
#: said something a hint will not fix. Staff need to be able to see these.
STUDENT_FLAG = "socratic.student_flag"
SUMMARY_JOB = "summary.job"
IDEMPOTENT_REPLAY = "idempotency.replay"
CLASSROOM_CREATED = "classroom.created"
CLASSROOM_RENAMED = "classroom.renamed"
CLASSROOM_ARCHIVED = "classroom.archived"
CLASSROOM_RESTORED = "classroom.restored"
#: Faculty opened a student's full chat transcript for a past session.
TRANSCRIPT_VIEWED = "report.transcript_viewed"
MEMBERSHIP_JOINED = "classroom.membership_joined"
MEMBERSHIP_REMOVED = "classroom.membership_removed"
JOIN_CODE_REGENERATED = "classroom.join_code_regenerated"
SESSION_STARTED = "class_session.started"
SESSION_ENDED = "class_session.ended"
ROLE_CHANGED = "admin.role_changed"
CLASS_FACULTY_PROMOTED = "classroom.faculty_promoted"
CLASS_FACULTY_DEMOTED = "classroom.faculty_demoted"
PROFILE_COMPLETED = "auth.profile_completed"
ESCALATION_RESOLVED = "tier3.resolved"
MARKS_ENTERED = "marks.entered"


async def record(
    session: AsyncSession,
    event: str,
    *,
    user_id: str | None = None,
    classroom_id: str | None = None,
    class_session_id: str | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = False,
) -> None:
    try:
        session.add(
            AuditLog(
                event=event,
                user_id=user_id,
                classroom_id=classroom_id,
                class_session_id=class_session_id,
                detail=detail or {},
            )
        )
        await session.flush()
        if commit:
            await session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        log.error("Failed to write audit event %s: %s", event, exc)
