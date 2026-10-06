"""Experiment 07 -- Build atoms/molecules; orbital visualization; orbital
contributions (Gabedit -> ORCA -> Avogadro; CH4 and O2).

STATUS: implemented via `ComputationSanityPlugin` (IACHY102 manual,
p.39-42). See that class's docstring in `registry.py` for the full
rationale. Short version: this experiment has no formula to recompute
and no second conformer to compare against (unlike Experiment 8), so
there is nothing for a `DeterministicPlugin` or `QualitativeOrderingPlugin`
to do. What Tier 1 *can* check, with no chemistry knowledge beyond two
facts that hold for any molecule/method/basis set:

* geometry optimisation must not increase the energy;
* the LUMO must be higher in energy than the HOMO.

A clean run (neither fact violated) is a PASS: the student's own numbers
are internally consistent, which is the determinate thing Tier 1 can
honestly confirm. This does not verify the method/basis-set choice
itself -- that still needs a human eye for the write-up -- only that
what the student reported does not contradict itself. A violation of
either fact is a determinate, signature-backed finding (FAIL_WITH_
SIGNATURE), never escalated. Escalation (NOT_APPLICABLE) is now reserved
for the case where neither pair of values was reported at all, so Tier 1
has nothing to check.
"""

from __future__ import annotations

from backend.tier1_compute.experiments.registry import ComputationSanityPlugin, register
from backend.tier1_compute.shared.types import StepSpec

EXPERIMENT_ID = "exp07"

STEPS: tuple[StepSpec, ...] = (
    StepSpec(
        index=0,
        key="geometry_and_optimization",
        prompt=(
            "Build the molecule in Gabedit, generate the ORCA input, run "
            "the optimisation, and report the energy before and after "
            "optimisation."
        ),
        hints=(
            "Check the end of the ORCA output file for the job-completion "
            "message before reading off an energy.",
            "Compare the two energies you reported -- optimisation should "
            "never leave the molecule at a higher energy than it started.",
            "Your post-optimisation energy is higher than the pre-"
            "optimisation one, which usually means the job did not "
            "actually converge; re-run the optimisation.",
        ),
    ),
    StepSpec(
        index=1,
        key="orbital_energies",
        prompt=(
            "Run the orbital calculation on the optimised geometry and "
            "report the HOMO and LUMO energies you read from the output "
            "(and in Avogadro)."
        ),
        hints=(
            "Double-check you opened the optimised-geometry output, not "
            "the original drawn structure, before reading orbital "
            "energies.",
            "HOMO means Highest Occupied, LUMO means Lowest Unoccupied -- "
            "check which of your two numbers is actually higher.",
            "Your reported LUMO is not higher than your reported HOMO, "
            "which points at the two values being swapped or the "
            "calculation not having converged.",
        ),
        is_final=True,
    ),
)

register(
    ComputationSanityPlugin(
        id=EXPERIMENT_ID,
        title="Build atoms and molecules; orbital contributions (Gabedit/ORCA/Avogadro)",
        manual_reference="IACHY102 manual, p.39-42",
        step_specs=STEPS,
    )
)
