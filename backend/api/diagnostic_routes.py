"""Diagnostic-mode routes: submit a finished record, get a diagnosis back.

Faculty and admin may also submit test records here (brief §12), through
the exact same Tier1/2/3 pipeline -- never a parallel implementation.
Every submission is stamped with `actor_type` so a demonstrator's test
submission can never be mistaken for a real student's.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit, idempotency, ratelimit
from backend import classrooms as classroom_service
from backend.auth import Principal, current_user
from backend.data_access import FacultyScope, StudentScope
from backend.db import get_session
from backend.extraction import extract_submission
from backend.models import (
    ActorType,
    Diagnosis,
    DiagnosisStatus,
    Escalation,
    RemedialAction,
    Submission,
)
from backend.pipeline import run_diagnosis
from backend.tier1_compute.experiments import UnknownExperimentError, get_plugin

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/submissions", tags=["diagnostic"])


class SubmissionRequest(BaseModel):
    classroom_id: str
    #: Raw form fields. For a real student submission the experiment is
    #: NOT taken from here -- it comes from the classroom's active class
    #: session, so a student cannot submit against a different one.
    #: Faculty/admin test submissions may set this explicitly when there
    #: is no active session to reproduce against.
    experiment_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    reported_value: Any = None
    remarks: str = ""
    idempotency_key: str | None = Field(default=None, max_length=128)


async def _actor_type_for(db: AsyncSession, principal: Principal, classroom_id: str) -> ActorType:
    if principal.is_admin:
        return ActorType.ADMIN_TEST
    if principal.is_faculty:
        return ActorType.FACULTY_TEST
    if await classroom_service.can_act_as_faculty(db, principal, classroom_id):
        return ActorType.FACULTY_TEST
    return ActorType.STUDENT


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit(
    body: SubmissionRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    actor_type = await _actor_type_for(db, principal, body.classroom_id)

    limit = ratelimit.check_submission(principal.id)
    if not limit.allowed:
        await audit.record(
            db, audit.RATE_LIMITED, user_id=principal.id,
            detail={"scope": "submission"}, commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions; wait a moment before trying again.",
            headers={"Retry-After": str(int(limit.retry_after_seconds) + 1)},
        )

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
                detail="No active class session is set for this classroom yet.",
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
                detail="No active class session; name experiment_id explicitly for a test submission.",
            )
        class_session_id = active.id if (active and experiment_id in active.allowed_experiments) else None

    try:
        plugin = get_plugin(experiment_id)
    except UnknownExperimentError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    key = body.idempotency_key or idempotency.derive_key(
        "submit", principal.id, body.classroom_id, experiment_id, sorted(body.data.items()),
        body.reported_value,
    )
    try:
        claim = await idempotency.claim(
            db, user_id=principal.id, scope="submit", key=key
        )
    except idempotency.DuplicateInFlight as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not claim.fresh:
        await audit.record(
            db, audit.IDEMPOTENT_REPLAY, user_id=principal.id,
            classroom_id=body.classroom_id, detail={"scope": "submit"}, commit=True,
        )
        return claim.replayed_response or {}

    # --- extraction -------------------------------------------------------
    # Structured (dict) fields pass through untouched: Experiments 7 and 8
    # report a mapping of conformer -> energy, which is not a scalar or a
    # series and must not be handed to the numeric parser.
    structured_keys = tuple(k for k, v in body.data.items() if isinstance(v, dict))
    series_keys = tuple(
        k for k, v in body.data.items() if isinstance(v, (list, tuple))
    )
    numeric_keys = tuple(
        k for k in body.data if k not in structured_keys and k not in series_keys
    )
    extracted = extract_submission(
        body.data, numeric_fields=numeric_keys, series_fields=series_keys
    )
    for skey in structured_keys:
        extracted.values[skey] = body.data[skey]

    reported: float | None = None
    if body.reported_value is not None:
        from backend.extraction import ExtractionError, parse_number

        try:
            reported = parse_number(body.reported_value, "reported_value")
        except ExtractionError as exc:
            extracted.errors.append(str(exc))

    submission = Submission(
        student_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        experiment_id=experiment_id,
        actor_type=actor_type,
        raw_payload={"data": body.data, "reported_value": body.reported_value,
                     "remarks": body.remarks},
        reported_value=reported,
    )
    db.add(submission)
    await db.flush()

    if not extracted.ok:
        diagnosis = Diagnosis(
            submission_id=submission.id,
            student_id=principal.id,
            classroom_id=body.classroom_id,
            class_session_id=class_session_id,
            status=DiagnosisStatus.INVALID,
            tier=1,
            reported_value=reported,
            detail={"errors": extracted.errors},
            # Set explicitly: the column default is only applied on insert,
            # and this row is serialised into the response before flushing.
            action=RemedialAction.FIX_IN_PLACE,
            phrased_text="This submission could not be checked: "
            + "; ".join(extracted.errors),
        )
        db.add(diagnosis)
        payload = _diagnosis_payload(submission, diagnosis)
        await idempotency.complete(db, claim, payload)
        await audit.record(
            db, audit.DIAGNOSIS_MADE, user_id=principal.id,
            classroom_id=body.classroom_id,
            detail={"status": "invalid", "experiment": experiment_id},
        )
        await db.commit()
        return payload

    # --- tiers 1-3, then phrasing ----------------------------------------
    outcome = await run_diagnosis(
        plugin,
        inputs=extracted.values,
        reported_value=reported,
        remarks=body.remarks,
        student_text=body.remarks,
    )

    diagnosis = Diagnosis(
        submission_id=submission.id,
        student_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        status=outcome.status,
        tier=outcome.tier,
        signature_code=outcome.signature_code,
        expected_value=outcome.expected_value,
        reported_value=outcome.reported_value,
        detail=outcome.detail,
        action=outcome.action,
        phrased_text=outcome.phrased_text,
        phrasing_source=outcome.phrasing_source,
        low_confidence=outcome.low_confidence,
    )
    db.add(diagnosis)
    await db.flush()

    # Anything that tells the caller to wait for a demonstrator must
    # actually reach one. That includes a Tier 3 abstention and also a
    # determinate finding whose remedy is review -- a violated conformer
    # ordering on Experiments 7/8 is a FAIL, not an escalation, but its
    # action is await_review, and a student told to wait for someone who
    # never sees the case is worse than no diagnosis at all. Faculty/admin
    # test submissions still escalate the same way, so the tester sees
    # exactly what a student would trigger.
    needs_human = outcome.escalated or outcome.action is RemedialAction.AWAIT_REVIEW
    if needs_human:
        db.add(
            Escalation(
                diagnosis_id=diagnosis.id,
                classroom_id=body.classroom_id,
                class_session_id=class_session_id,
                student_id=principal.id,
                reason=outcome.escalate_reason
                or (
                    "Diagnosed, but the remedy is human review: "
                    f"{outcome.signature_code or 'unspecified'}"
                ),
            )
        )
        await audit.record(
            db, audit.TIER3_ESCALATION, user_id=principal.id,
            classroom_id=body.classroom_id,
            class_session_id=class_session_id,
            detail={"experiment": experiment_id, "reason": outcome.escalate_reason},
        )

    await audit.record(
        db, audit.DIAGNOSIS_MADE, user_id=principal.id,
        classroom_id=body.classroom_id,
        class_session_id=class_session_id,
        detail={
            "experiment": experiment_id,
            "status": outcome.status.value,
            "tier": outcome.tier,
            "signature": outcome.signature_code,
            "phrasing_source": outcome.phrasing_source,
            "actor_type": actor_type.value,
        },
    )

    payload = _diagnosis_payload(submission, diagnosis, citation=outcome.citation)
    await idempotency.complete(db, claim, payload)
    await db.commit()
    return payload


def _diagnosis_payload(
    submission: Submission, diagnosis: Diagnosis, citation: str = ""
) -> dict:
    """What a caller sees. Never includes another student's anything."""
    return {
        "submission_id": submission.id,
        "experiment_id": submission.experiment_id,
        "status": diagnosis.status.value,
        "tier": diagnosis.tier,
        "action": diagnosis.action.value,
        "explanation": diagnosis.phrased_text,
        "citation": citation,
        "low_confidence": diagnosis.low_confidence,
    }


@router.get("/mine")
async def my_submissions(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    scope = StudentScope(db, principal.id)
    submissions = await scope.all(Submission)
    diagnoses = {d.submission_id: d for d in await scope.all(Diagnosis)}
    return {
        "submissions": [
            {
                "id": s.id,
                "experiment_id": s.experiment_id,
                "created_at": s.created_at.isoformat(),
                "status": (
                    diagnoses[s.id].status.value if s.id in diagnoses else "pending"
                ),
                "explanation": (
                    diagnoses[s.id].phrased_text if s.id in diagnoses else ""
                ),
            }
            for s in sorted(submissions, key=lambda s: s.created_at, reverse=True)
        ]
    }


@router.get("/{submission_id}")
async def get_submission(
    submission_id: str,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Scoped fetch.

    Another user's id returns 404 because the row is never selected -- the
    owner predicate is part of the query, not a check afterwards.
    """
    scope = StudentScope(db, principal.id)
    submission = await scope.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    diagnoses = await scope.all(Diagnosis, Diagnosis.submission_id == submission_id)
    diagnosis = diagnoses[0] if diagnoses else None
    return {
        "id": submission.id,
        "experiment_id": submission.experiment_id,
        "created_at": submission.created_at.isoformat(),
        "reported_value": submission.reported_value,
        "status": diagnosis.status.value if diagnosis else "pending",
        "explanation": diagnosis.phrased_text if diagnosis else "",
        "action": diagnosis.action.value if diagnosis else "none",
    }
