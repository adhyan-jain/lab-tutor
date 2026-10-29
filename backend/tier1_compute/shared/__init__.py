"""Shared, reusable checker types used by every per-experiment plugin.

There are four, and a plugin configures one or more of them rather than
implementing its own math:

* :class:`DirectFormulaChecker`      -- one formula, one comparison
* :class:`CalibrationCurveChecker`   -- fit standards, read off an unknown
* :class:`EndpointDetectionChecker`  -- peak or line-intersection endpoints
* :class:`RegressionSlopeChecker`    -- rate constants from a fitted slope

If an experiment genuinely fits none of these, add a fifth shared type --
do not hand-roll one-off math inside a plugin (see AGENTS.md,
`tier1-compute-builder`).
"""

from backend.tier1_compute.shared.base import Checker
from backend.tier1_compute.shared.calibration_curve import CalibrationCurveChecker
from backend.tier1_compute.shared.direct_formula import DirectFormulaChecker
from backend.tier1_compute.shared.endpoint_detection import (
    INTERSECTION,
    PEAK,
    EndpointDetectionChecker,
    first_derivative,
)
from backend.tier1_compute.shared.regression_slope import RegressionSlopeChecker
from backend.tier1_compute.shared.types import (
    Action,
    Outcome,
    SignatureHit,
    StepSpec,
    Tier1Result,
    Tolerance,
)

__all__ = [
    "Checker",
    "CalibrationCurveChecker",
    "DirectFormulaChecker",
    "EndpointDetectionChecker",
    "RegressionSlopeChecker",
    "PEAK",
    "INTERSECTION",
    "first_derivative",
    "Action",
    "Outcome",
    "SignatureHit",
    "StepSpec",
    "Tier1Result",
    "Tolerance",
]
