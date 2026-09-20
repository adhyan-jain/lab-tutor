"""Pre/post-test marks: entry, aggregate analytics, and Excel export.

Faculty/admin enter these by hand from a separate paper/offline test --
never computed or judged by this system. Kept entirely apart from Tier 1
diagnosis (see CLAUDE.md's hard rule): nothing here decides whether a
student's lab result is correct, it only stores and aggregates numbers a
human typed in. Gating mirrors dashboard_routes.py exactly: faculty is
membership-scoped via FacultyScope, admin bypasses scoping but never the
role check.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend import audit
from backend.auth import Principal, classroom_faculty_scope, current_user
from backend.classrooms import roster_with_users
from backend.data_access import FacultyScope
from backend.db import get_session
from backend.models import Classroom, ExperimentMarks, ExperimentMarksHistory, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/marks", tags=["marks"])


async def _classroom_or_404(
    db: AsyncSession, principal: Principal, scope: FacultyScope, classroom_id: str
) -> Classroom:
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


class MarksEntry(BaseModel):
    student_id: str
    pre_test_marks: float | None = None
    pre_test_max: float = Field(default=10.0, gt=0)
    post_test_marks: float | None = None
    post_test_max: float = Field(default=10.0, gt=0)


class SubmitMarksRequest(BaseModel):
    entries: list[MarksEntry] = Field(default_factory=list)


async def _existing_marks(
    db: AsyncSession, classroom_id: str, experiment_id: str
) -> dict[str, ExperimentMarks]:
    rows = list(
        (
            await db.scalars(
                select(ExperimentMarks).where(
                    ExperimentMarks.classroom_id == classroom_id,
                    ExperimentMarks.experiment_id == experiment_id,
                )
            )
        ).all()
    )
    return {r.student_id: r for r in rows}


@router.get("/classrooms/{classroom_id}/experiments/{experiment_id}")
async def get_marks(
    classroom_id: str,
    experiment_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Roster joined with any marks already entered for this experiment."""
    classroom = await _classroom_or_404(db, principal, scope, classroom_id)
    roster = await roster_with_users(db, classroom.id)
    marks_by_student = await _existing_marks(db, classroom_id, experiment_id)

    out = []
    for _membership, user in roster:
        row = marks_by_student.get(user.id)
        out.append(
            {
                "student_id": user.id,
                "student_name": user.name,
                "student_email": user.email,
                "pre_test_marks": row.pre_test_marks if row else None,
                "pre_test_max": row.pre_test_max if row else 10.0,
                "post_test_marks": row.post_test_marks if row else None,
                "post_test_max": row.post_test_max if row else 10.0,
            }
        )
    return {"experiment_id": experiment_id, "students": out}


@router.post("/classrooms/{classroom_id}/experiments/{experiment_id}")
async def submit_marks(
    classroom_id: str,
    experiment_id: str,
    body: SubmitMarksRequest,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Bulk upsert: one call saves the whole roster's marks for one
    experiment. Only students actually enrolled in this classroom may be
    written -- a stray/foreign student_id in the request body is ignored
    rather than silently creating an orphaned row.
    """
    classroom = await _classroom_or_404(db, principal, scope, classroom_id)
    roster = await roster_with_users(db, classroom.id)
    enrolled_ids = {user.id for _membership, user in roster}
    existing = await _existing_marks(db, classroom_id, experiment_id)

    saved = 0
    for entry in body.entries:
        if entry.student_id not in enrolled_ids:
            continue
        row = existing.get(entry.student_id)
        if row is None:
            row = ExperimentMarks(
                student_id=entry.student_id,
                classroom_id=classroom_id,
                experiment_id=experiment_id,
                entered_by=principal.id,
            )
            db.add(row)
            existing[entry.student_id] = row
        row.pre_test_marks = entry.pre_test_marks
        row.pre_test_max = entry.pre_test_max
        row.post_test_marks = entry.post_test_marks
        row.post_test_max = entry.post_test_max
        row.entered_by = principal.id
        # Append-only research record -- `row` above is the "current
        # value" upserted in place, but a repeat submission (typo fix,
        # re-grade) must not erase the prior attempt for research
        # validity. This is a separate insert every time, never updated.
        db.add(
            ExperimentMarksHistory(
                student_id=entry.student_id,
                classroom_id=classroom_id,
                experiment_id=experiment_id,
                pre_test_marks=entry.pre_test_marks,
                pre_test_max=entry.pre_test_max,
                post_test_marks=entry.post_test_marks,
                post_test_max=entry.post_test_max,
                entered_by=principal.id,
            )
        )
        saved += 1

    await audit.record(
        db,
        audit.MARKS_ENTERED,
        user_id=principal.id,
        classroom_id=classroom_id,
        detail={"experiment_id": experiment_id, "count": saved},
    )
    await db.commit()
    return {"experiment_id": experiment_id, "saved": saved}


def _experiment_stats(rows: list[ExperimentMarks]) -> dict:
    graded = [r for r in rows if r.pre_test_marks is not None and r.post_test_marks is not None]
    if not graded:
        return {
            "n": 0,
            "mean_pre": None,
            "mean_post": None,
            "mean_gain": None,
            "percent_improved": None,
            "std_gain": None,
        }
    # Normalise to a 0-100 scale first so pre/post pairs entered against
    # different max marks are still comparable in one aggregate.
    pre = np.array([100.0 * r.pre_test_marks / r.pre_test_max for r in graded])
    post = np.array([100.0 * r.post_test_marks / r.post_test_max for r in graded])
    gain = post - pre
    return {
        "n": len(graded),
        "mean_pre": float(np.mean(pre)),
        "mean_post": float(np.mean(post)),
        "mean_gain": float(np.mean(gain)),
        "percent_improved": float(100.0 * np.sum(gain > 0) / len(graded)),
        "std_gain": float(np.std(gain, ddof=0)),
    }


async def _all_marks_by_experiment(
    db: AsyncSession, classroom_id: str
) -> dict[str, list[ExperimentMarks]]:
    rows = list(
        (
            await db.scalars(
                select(ExperimentMarks).where(ExperimentMarks.classroom_id == classroom_id)
            )
        ).all()
    )
    by_experiment: dict[str, list[ExperimentMarks]] = {}
    for row in rows:
        by_experiment.setdefault(row.experiment_id, []).append(row)
    return by_experiment


@router.get("/classrooms/{classroom_id}/analytics")
async def marks_analytics(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Per-experiment pre/post aggregate, normalised to a 0-100 scale so
    experiments graded out of different maxima are comparable. Pure
    arithmetic over faculty-entered numbers -- no LLM involved.
    """
    await _classroom_or_404(db, principal, scope, classroom_id)
    by_experiment = await _all_marks_by_experiment(db, classroom_id)
    return {
        "experiments": [
            {"experiment_id": experiment_id, **_experiment_stats(rows)}
            for experiment_id, rows in sorted(by_experiment.items())
        ]
    }


@router.get("/classrooms/{classroom_id}/export.xlsx")
async def export_marks(
    classroom_id: str,
    principal: Principal = Depends(current_user),
    scope: FacultyScope = Depends(classroom_faculty_scope),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    classroom = await _classroom_or_404(db, principal, scope, classroom_id)
    by_experiment = await _all_marks_by_experiment(db, classroom_id)
    emails = {u.id: u.email for u in (await db.scalars(select(User))).all()}
    names = {u.id: u.name for u in (await db.scalars(select(User))).all()}

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Marks"
    sheet.append(
        [
            "Experiment", "Student name", "Student email",
            "Pre-test", "Pre-test max", "Post-test", "Post-test max", "Gain",
        ]
    )
    for experiment_id, rows in sorted(by_experiment.items()):
        for row in sorted(rows, key=lambda r: emails.get(r.student_id, "")):
            gain = (
                row.post_test_marks - row.pre_test_marks
                if row.pre_test_marks is not None and row.post_test_marks is not None
                else None
            )
            sheet.append(
                [
                    experiment_id,
                    names.get(row.student_id, ""),
                    emails.get(row.student_id, ""),
                    row.pre_test_marks,
                    row.pre_test_max,
                    row.post_test_marks,
                    row.post_test_max,
                    gain,
                ]
            )

    summary = workbook.create_sheet("Summary")
    summary.append(["Experiment", "N", "Mean pre (%)", "Mean post (%)", "Mean gain (%)", "% improved", "Std dev gain"])
    for experiment_id, rows in sorted(by_experiment.items()):
        stats = _experiment_stats(rows)
        summary.append(
            [
                experiment_id,
                stats["n"],
                stats["mean_pre"],
                stats["mean_post"],
                stats["mean_gain"],
                stats["percent_improved"],
                stats["std_gain"],
            ]
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"labtutor_marks_{classroom.name.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
