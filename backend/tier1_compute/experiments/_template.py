"""Template for a per-experiment Tier 1 plugin.

Each real experiment plugin in this folder should be a thin config
file that wires the experiment's manual-derived formula, tolerance,
and expected data shape into one of the shared checker types in
`tier1_compute/shared/` (direct_formula, calibration_curve,
endpoint_detection, regression_slope).

Do NOT put ad-hoc bespoke math directly in a plugin file if it can be
expressed through a shared checker type — that defeats the point of
the templated plugin system. If an experiment genuinely doesn't fit
any shared checker type, that's a signal to add a new shared checker
type, not to hand-roll one-off logic per experiment.

TODO: implement real plugin files once:
  1. The BACHY105 manual is confirmed present at the repo root.
  2. The pilot experiment count/list is confirmed with the team
     (see the scope-conflict TODO in docs/ARCHITECTURE.md).
"""

# TODO: implement
