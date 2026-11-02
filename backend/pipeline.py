"""Diagnostic-mode pipeline.

Implements exactly the flow in ARCHITECTURE.md §1.2:

    extraction -> Tier 1 recompute -> (match: confirm)
                                   -> (mismatch: signature detection
                                       -> Tier 2 lookup
                                       -> Tier 3 escalate if unresolved)
    -> RAG-grounded phrasing of the determined diagnosis
    -> action mapping -> student output + dashboard entry

The ordering is the point. Every tier that can decide has decided before
any model is called, so the phrasing step receives a finished verdict and
can only affect the wording.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend import tier3_escalation as tier3
from backend.answer_gate import filter_outbound
from backend.models import DiagnosisStatus, RemedialAction
from backend.rag.phrasing import phrase_diagnosis
from backend.tier1_compute.experiments.registry import (
    ExperimentPlugin,
    ManualNotTranscribedError,
    QualitativeOrderingPlugin,
)
from backend.tier1_compute.shared.types import Action, Outcome, Tier1Result
from backend.tier2_exceptions import lookup as tier2_lookup

log = logging.getLogger(__name__)

_ACTION_MAP: dict[Action, RemedialAction] = {
    Action.NONE: RemedialAction.NONE,
    Action.FIX_IN_PLACE: RemedialAction.FIX_IN_PLACE,
    Action.REDO_STEP: RemedialAction.REDO_STEP,
    Action.RESTART: RemedialAction.RESTART,
    Action.AWAIT_REVIEW: RemedialAction.AWAIT_REVIEW,
}


@dataclass
class DiagnosisOutcome:
    """Everything the API layer needs to persist and return."""

    status: DiagnosisStatus
    tier: int
    action: RemedialAction
    signature_code: str | None = None
    expected_value: float | None = None
    reported_value: float | None = None
    phrased_text: str = ""
    phrasing_source: str = "template"
    citation: str = ""
    low_confidence: bool = False
    escalate_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def escalated(self) -> bool:
        return self.status is DiagnosisStatus.ESCALATED


async def run_diagnosis(
    plugin: ExperimentPlugin,
    *,
    inputs: dict[str, Any],
    reported_value: float | None,
    remarks: str = "",
    student_text: str = "",
) -> DiagnosisOutcome:
    """Run the full diagnostic pipeline for one submission."""

    # --- Tier 1 -----------------------------------------------------------
    try:
        result = plugin.check(inputs, reported_value)
    except ManualNotTranscribedError as exc:
        # No plugin means no diagnosis. Escalating is the honest outcome;
        # guessing would be the alternative.
        log.warning("No Tier 1 plugin for %s: %s", plugin.id, exc)
        return DiagnosisOutcome(
            status=DiagnosisStatus.ESCALATED,
            tier=3,
            action=RemedialAction.AWAIT_REVIEW,
            escalate_reason=tier3.REASON_PLUGIN_UNAVAILABLE,
            phrased_text=(
                "This experiment is not yet set up for automatic checking, so "
                "your submission has been sent to a demonstrator."
            ),
            detail={"experiment": plugin.id, "error": str(exc)},
        )

    low_confidence = isinstance(plugin, QualitativeOrderingPlugin)

    if result.outcome is Outcome.PASS:
        outcome = DiagnosisOutcome(
            status=DiagnosisStatus.PASS,
            tier=1,
            action=RemedialAction.NONE,
            expected_value=result.expected_value,
            reported_value=result.reported_value,
            detail=result.detail,
        )
    elif result.outcome is Outcome.INVALID:
        outcome = DiagnosisOutcome(
            status=DiagnosisStatus.INVALID,
            tier=1,
            action=RemedialAction.FIX_IN_PLACE,
            detail=result.detail | {"errors": result.errors},
        )
    elif result.outcome is Outcome.FAIL_WITH_SIGNATURE:
        outcome = DiagnosisOutcome(
            status=DiagnosisStatus.FAIL,
            tier=1,
            action=_ACTION_MAP[result.action()],
            signature_code=result.signature_code,
            expected_value=result.expected_value,
            reported_value=result.reported_value,
            low_confidence=low_confidence,
            detail=result.detail,
        )
    elif result.outcome is Outcome.NOT_APPLICABLE:
        outcome = DiagnosisOutcome(
            status=DiagnosisStatus.ESCALATED,
            tier=3,
            action=RemedialAction.AWAIT_REVIEW,
            low_confidence=True,
            escalate_reason=tier3.REASON_QUALITATIVE,
            detail=result.detail,
        )
    else:
        # --- Tier 2 -------------------------------------------------------
        match = tier2_lookup(plugin.id, remarks=remarks)
        if match is not None:
            outcome = DiagnosisOutcome(
                status=DiagnosisStatus.FAIL,
                tier=2,
                action=_ACTION_MAP[match.entry.action],
                signature_code=match.entry.code,
                expected_value=result.expected_value,
                reported_value=result.reported_value,
                detail=result.detail | {"tier2_entry": match.entry.title},
            )
            # Give the phrasing layer the curated explanation as the fact
            # to render, exactly as a Tier 1 signature would be.
            result = Tier1Result(
                outcome=Outcome.FAIL_WITH_SIGNATURE,
                expected_value=result.expected_value,
                reported_value=result.reported_value,
                signature=_as_signature(match),
                detail=result.detail,
            )
        else:
            # --- Tier 3 ---------------------------------------------------
            decision = tier3.escalate(tier3.REASON_NO_SIGNATURE)
            outcome = DiagnosisOutcome(
                status=DiagnosisStatus.ESCALATED,
                tier=3,
                action=RemedialAction.AWAIT_REVIEW,
                expected_value=result.expected_value,
                reported_value=result.reported_value,
                escalate_reason=decision.reason,
                detail=result.detail,
            )

    # --- Phrasing (never changes the verdict above) -----------------------
    phrased = await phrase_diagnosis(
        result,
        experiment_title=plugin.title,
        student_text=student_text,
        retrieval_query=f"{plugin.title} {result.signature_code or ''}".strip(),
    )
    # Every student-facing message leaves through the answer gate, this
    # one included. Diagnostic mode legitimately discloses the recomputed
    # value -- the student has finished -- so numbers are left alone and
    # only sanitisation applies. Routing it here anyway is what makes the
    # gate the single outbound choke point rather than a Socratic-only
    # detail.
    gated = filter_outbound(phrased.text, mode="diagnostic")

    outcome.phrased_text = gated.text
    outcome.phrasing_source = phrased.source
    outcome.citation = phrased.citation
    return outcome


def _as_signature(match):
    from backend.tier1_compute.shared.types import SignatureHit

    return SignatureHit(
        code=match.entry.code,
        detail=match.entry.detail,
        evidence={"tier": 2, "entry": match.entry.title},
    )
