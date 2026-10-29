"""Experiment 04 -- Analysis of iron in carbon steel by potentiometry
(IACHY102 manual, p.28-32).

STATUS: implemented, with tolerance/peak-quality DEFAULTS the manual does not
state (see below) -- not a manual-verified worked example. The manual prints
no numeric example (both titration tables, p.30-32, are blank), so there is
no Category 1 golden case; the tests use synthetic data built by inverting
the manual's own formulas.

The manual's formulas, transcribed exactly:

    5Fe2+ + MnO4- + 8H+ -> 5Fe3+ + Mn2+ + 4H2O
    endpoint: the volume at the maximum of DeltaE/DeltaV against the average
              volume (equivalently the steepest point of the EMF-vs-volume
              S-curve)
    N(steel)  = 0.05 N * V(KMnO4 at endpoint) / 20 mL
    Fe (g/100 mL) = N(steel) * 55.85 * 100 / 1000

The student records titrant volume and EMF; the DeltaE/DeltaV series is
computed here (`first_derivative`) so a slip in the student's own difference
column cannot decide the endpoint. The peak is refined by parabolic
interpolation, so the endpoint is not quantised to the dosed volumes.

`tolerance`, `min_points` and `min_prominence` are deliberate
engineering defaults for a self-consistency check, not manual-derived values
-- revisit if a worked example or course-stated tolerance surfaces:

* endpoint volume: 0.15 mL absolute (about one dosing increment near the
  endpoint) or 2 % relative;
* final Fe content: 5 % relative, as for the other titration experiments;
* no `max_increment` check: the coarse-increments signature looks at the
  widest gap anywhere in the run, which would wrongly flag the normal
  practice of big early additions and fine ones near the jump;
* `min_prominence=20` mV/mL: a derivative peak shallower than this above
  the median is not a resolved S-curve jump.
"""

from __future__ import annotations

from typing import Any

from backend.tier1_compute.experiments.registry import DeterministicPlugin, register
from backend.tier1_compute.shared import (
    PEAK,
    EndpointDetectionChecker,
    StepSpec,
    Tolerance,
    first_derivative,
)

EXPERIMENT_ID = "exp04"

#: Constants printed in the manual's calculation (p.28-32).
TITRANT_NORMALITY = 0.05  # N KMnO4
ALIQUOT_ML = 20.0  # mL of the steel solution titrated
FE_EQUIVALENT_WEIGHT = 55.85  # g/equiv


def iron_g_per_100ml(endpoint_ml: float, inputs: dict[str, Any] | None = None) -> float:
    """N(steel) = 0.05 * V / 20, then Fe (g/100 mL) = N * 55.85 * 100 / 1000."""
    n_steel = TITRANT_NORMALITY * endpoint_ml / ALIQUOT_ML
    return n_steel * FE_EQUIVALENT_WEIGHT * 100.0 / 1000.0


_COMMON = dict(
    x_key="kmno4_volume_ml",
    y_key="emf_mv",
    geometry=PEAK,
    series_transform=first_derivative,
    min_points=6,  # DEFAULT -- enough readings to bracket and refine a peak
    min_prominence=20.0,  # DEFAULT, mV/mL -- see module docstring
)

ENDPOINT_CHECKER = EndpointDetectionChecker(
    tolerance=Tolerance(abs_tol=0.15, rel_tol=0.02),  # DEFAULT
    label="KMnO4 volume at the potentiometric endpoint (mL)",
    **_COMMON,
)

FINAL_CHECKER = EndpointDetectionChecker(
    tolerance=Tolerance(rel_tol=0.05),  # DEFAULT
    derive=iron_g_per_100ml,
    label="iron content of the steel solution (g per 100 mL)",
    **_COMMON,
)

STEPS: tuple[StepSpec, ...] = (
    StepSpec(
        index=0,
        key="titration_readings",
        prompt=(
            "Record the EMF (mV) after each addition of KMnO4, together with "
            "the total volume of KMnO4 added. Use smaller additions near the "
            "jump."
        ),
        requires=("kmno4_volume_ml", "emf_mv"),
        hints=(
            "Check you recorded the cumulative volume added, not the size "
            "of each separate addition.",
            "Near the equivalence point the EMF changes quickly; if your "
            "additions there are large you cannot tell where the jump is.",
            "Your volume readings are not in increasing order, or an EMF "
            "reading is missing for one of them -- re-check the table row "
            "by row.",
        ),
    ),
    StepSpec(
        index=1,
        key="endpoint_volume",
        prompt=(
            "Find the endpoint: compute DeltaE/DeltaV against the average "
            "volume and read the volume at its sharp maximum (or the steepest "
            "point of the EMF-vs-volume curve)."
        ),
        requires=("kmno4_volume_ml", "emf_mv"),
        tolerance=Tolerance(abs_tol=0.15, rel_tol=0.02),
        hints=(
            "Check you divided each EMF change by the matching volume "
            "change, and assigned it to the average of the two volumes.",
            "The endpoint is where DeltaE/DeltaV is largest, not where the "
            "EMF itself is largest.",
            "The volume you picked is not at the top of your own "
            "DeltaE/DeltaV column -- re-read which row holds the maximum.",
        ),
    ),
    StepSpec(
        index=2,
        key="iron_content",
        prompt=(
            "Calculate the normality of the steel solution from the "
            "endpoint volume, then the iron content in g per 100 mL."
        ),
        requires=("kmno4_volume_ml", "emf_mv"),
        tolerance=Tolerance(rel_tol=0.05),
        hints=(
            "Check you used the aliquot volume that was actually titrated "
            "in the normality step.",
            "Convert normality to mass using the equivalent weight of iron, "
            "then scale to the stated volume.",
            "Your result is off by a power of ten, which usually means a "
            "mL/L slip in the final scaling step.",
        ),
        is_final=True,
    ),
)

register(
    DeterministicPlugin(
        id=EXPERIMENT_ID,
        title="Analysis of iron in carbon steel by potentiometry",
        manual_reference="IACHY102 manual, p.28-32",
        checker=FINAL_CHECKER,
        step_specs=STEPS,
        step_checkers={1: ENDPOINT_CHECKER, 2: FINAL_CHECKER},
    )
)
