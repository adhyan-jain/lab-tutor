"""Stub plugin for experiments that don't fit the measured-vs-expected
numeric pattern (referred to in planning as "Experiments 7 and 8" —
orbital/hybridization visualization and conformational analysis;
re-verify the real experiment numbers/names against the manual before
wiring this up).

These experiments verify computational method choice, not measurement
correctness, so there is no numeric expected value to recompute and no
numeric signature to detect. This plugin always escalates straight to
Tier 3 (human review). Do NOT attempt to build real Tier 1 diagnosis
for these experiments — that is an explicit non-goal, not a pilot cut.

TODO: implement the actual always-escalate wiring once the Tier 3
escalation interface exists (see backend/tier3_escalation).
"""

# TODO: implement
