"""Experiment 02 -- Determination of reaction rate, order and molecularity:
acid-catalysed hydrolysis of ethyl acetate (IACHY102 manual, p.16-19).

STATUS: implemented, with tolerance/fit-quality DEFAULTS the manual does
not state (see below) -- not a manual-verified worked example. Unblocks
Socratic session-start for this experiment; see docs/final_audit.md for
why this differs from Experiment 1's fully manual-grounded checker.

The manual's own formulas (p.18), transcribed exactly:

    k1' = (2.303/t) * log10[(V_inf - V0) / (V_inf - Vt)]
    k1' = slope * 2.303   (from a plot of log10(V_inf - Vt) vs t)

where V0/Vt/V_inf are NaOH titre volumes at t=0, at time t, and at
completion. `RegressionSlopeChecker`'s `y_reference_key` mechanism (added
this session -- see backend/tier1_compute/shared/regression_slope.py)
handles this: the per-point transform needs the student's own V_inf
reading, not a manual constant, at every point.

One interpretive choice, not stated explicitly in the manual: the printed
"k1' = Slope x 2.303" has no minus sign, but the plotted quantity
log10(V_inf - Vt) DECREASES as t increases (Vt approaches V_inf), so its
slope is negative, while a rate constant is conventionally reported
positive. `slope_to_value` below applies `-slope * 2.303`, the standard
kinetics sign convention, not new chemistry -- flagged here rather than
silently baked in.

The manual gives no experiment-specific numeric tolerance or fit-quality
floor (unlike Experiment 1, it has no worked numeric example at all --
see manual/IACHY102_manual.md's summary table). `tolerance`,
`min_r_squared` and `min_points` below are therefore deliberate
engineering defaults for a self-consistency check, not manual-derived
values -- revisit if a worked example or course-stated tolerance ever
surfaces.
"""

from __future__ import annotations

import math

from backend.tier1_compute.experiments.registry import DeterministicPlugin, register
from backend.tier1_compute.shared import RegressionSlopeChecker, StepSpec, Tolerance

EXPERIMENT_ID = "exp02"


def _log_remaining_ester(vt: float, v_inf: float) -> float:
    """log10(V_inf - Vt) -- p.18. Undefined once Vt reaches V_inf."""
    return math.log10(v_inf - vt)


FINAL_CHECKER = RegressionSlopeChecker(
    x_key="time_min",
    y_key="titre_volume_ml",
    y_reference_key="titre_volume_at_completion_ml",
    reference_transform=_log_remaining_ester,
    slope_to_value=lambda slope: -slope * 2.303,
    tolerance=Tolerance(rel_tol=0.05),  # DEFAULT -- see module docstring
    min_r_squared=0.98,  # DEFAULT -- see module docstring
    min_points=4,  # DEFAULT floor; manual's own table uses 7 (p.19)
    expect_direction="increasing",  # NaOH titre rises as acetic acid forms
    label="rate constant k1' (ester hydrolysis)",
)

STEPS: tuple[StepSpec, ...] = (
    StepSpec(
        index=0,
        key="titration_readings",
        prompt=(
            "Record the NaOH titre volume at each time interval, and the "
            "titre volume once the reaction has gone to completion (V_inf)."
        ),
        requires=("time_min", "titre_volume_ml", "titre_volume_at_completion_ml"),
        hints=(
            "Check you kept the sample in ice before titrating, so the "
            "reaction does not keep going during the titration itself.",
            "V_inf should be noticeably larger than any of your timed "
            "readings -- check it was taken after the completion step, "
            "not accidentally one of the timed points.",
            "One of your timed readings is larger than V_inf, which is "
            "not physically possible for this reaction -- re-check which "
            "reading is which.",
        ),
    ),
    StepSpec(
        index=1,
        key="rate_constant",
        prompt="Plot log10(V_inf - Vt) against t and calculate k1' from the slope.",
        requires=(
            "time_min",
            "titre_volume_ml",
            "titre_volume_at_completion_ml",
        ),
        tolerance=Tolerance(rel_tol=0.05),
        hints=(
            "Check you plotted log10(V_inf - Vt), not Vt itself, against time.",
            "Your points do not sit close to a straight line -- check for "
            "a mistimed reading or a transcription error in one row.",
            "The slope you have used does not match your own plotted "
            "points; re-read the slope off your own line rather than "
            "recalculating it from two endpoints.",
        ),
        is_final=True,
    ),
)

register(
    DeterministicPlugin(
        id=EXPERIMENT_ID,
        title="Determination of reaction rate, order and molecularity - ester hydrolysis",
        manual_reference="IACHY102 manual, p.16-19",
        checker=FINAL_CHECKER,
        step_specs=STEPS,
        step_checkers={1: FINAL_CHECKER},
    )
)
