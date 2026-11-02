"""Tier 2: hand-curated library of known non-numeric mistakes.

Consulted only when Tier 1 finds a genuine inconsistency but no numeric
signature explains it. These are procedural errors that leave no
characteristic fingerprint in the numbers -- an unrinsed burette produces
a wrong result that looks arithmetically ordinary.

Scope for this build, deliberately:

* **Static.** Entries are written by hand and reviewed by a human. The
  library does not learn, does not grow from observed cases, and has no
  ML component. TA-driven curation is deferred (ARCHITECTURE.md §2).
* **Small.** Five to ten entries per experiment, maximum. A large
  keyword-matched library starts producing confident wrong attributions,
  which is worse for a student than an honest escalation.

The entries below are *generic wet-lab* mistakes that hold across
titrimetric and colorimetric experiments. Per-experiment entries need the
IACHY102 manual and a demonstrator's judgment about what this cohort
actually gets wrong -- see `EXPERIMENT_SEEDS` and README "Known
limitations".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.tier1_compute.shared.types import Action


@dataclass(frozen=True)
class ExceptionEntry:
    code: str
    title: str
    #: Stated as a fact for the phrasing layer to render, like a Tier 1
    #: signature detail.
    detail: str
    action: Action
    #: Case-insensitive patterns matched against the student's own remarks.
    patterns: tuple[str, ...] = ()
    #: Experiment ids this applies to. Empty means "any experiment".
    experiment_ids: frozenset[str] = frozenset()
    #: Who added it, so attributions stay auditable.
    curated_by: str = "seed"

    def applies_to(self, experiment_id: str) -> bool:
        return not self.experiment_ids or experiment_id in self.experiment_ids

    def matches(self, remarks: str) -> bool:
        if not remarks or not self.patterns:
            return False
        return any(re.search(p, remarks, re.IGNORECASE) for p in self.patterns)


@dataclass(frozen=True)
class Tier2Match:
    entry: ExceptionEntry
    matched_on: str


#: Generic entries. Reviewed and kept short on purpose.
GENERIC_ENTRIES: tuple[ExceptionEntry, ...] = (
    ExceptionEntry(
        code="burette_not_rinsed",
        title="Burette not rinsed with the titrant",
        detail=(
            "A burette rinsed only with water still holds enough of it to dilute "
            "the titrant, so every titre comes out larger than it should be."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\brins", r"\bwash(ed)?\b.*burette", r"burette.*water"),
    ),
    ExceptionEntry(
        code="air_bubble_in_burette",
        title="Air bubble left in the burette tip",
        detail=(
            "An air bubble that clears during the titration adds its volume to "
            "the reading without any titrant having been delivered."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\bbubble", r"\bair\b.*\b(tip|jet|burette)\b"),
    ),
    ExceptionEntry(
        code="indicator_omitted_or_excess",
        title="Indicator omitted, added late, or added in excess",
        detail=(
            "Too much indicator consumes titrant of its own, and indicator added "
            "after titration has begun means the early colour change was missed."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\bindicator\b", r"\bphenolphthalein\b", r"\bmethyl orange\b"),
    ),
    ExceptionEntry(
        code="solution_not_made_to_mark",
        title="Standard solution not made up to the graduation mark",
        detail=(
            "If the volumetric flask was not filled exactly to the mark, the "
            "standard's stated concentration is not its real one, and every "
            "result computed from it inherits that error."
        ),
        action=Action.RESTART,
        patterns=(r"\bmark\b", r"\bmeniscus\b", r"\bmade up\b", r"\btop(ped)? up\b"),
    ),
    ExceptionEntry(
        code="parallax_on_reading",
        title="Burette read at an angle",
        detail=(
            "Reading the meniscus from above or below the eye level of the "
            "liquid shifts every reading in the same direction."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\bparallax\b", r"\beye level\b", r"\bread from (above|below)\b"),
    ),
    ExceptionEntry(
        code="electrode_not_rinsed",
        title="Electrode not rinsed between measurements",
        detail=(
            "Carry-over on an unrinsed electrode contaminates the next solution "
            "and drags its reading toward the previous one."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\belectrode\b", r"\bprobe\b", r"\bcarry.?over\b"),
    ),
    ExceptionEntry(
        code="cuvette_contaminated",
        title="Cuvette smudged, scratched, or not blanked",
        detail=(
            "Fingerprints on the optical faces, or a colorimeter that was not "
            "zeroed against the blank, shift every absorbance by roughly the "
            "same amount."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\bcuvette\b", r"\bblank\b", r"\bzero(ed)?\b", r"\bfingerprint"),
    ),
    ExceptionEntry(
        code="temperature_not_equilibrated",
        title="Readings taken before the solution reached temperature",
        detail=(
            "Conductance and rate measurements drift until the solution has "
            "equilibrated, so early readings sit systematically off the curve."
        ),
        action=Action.REDO_STEP,
        patterns=(r"\btemperature\b", r"\bthermostat", r"\bwater bath\b", r"\bwarm"),
    ),
)

#: Per-experiment entries. Populated during manual transcription, with a
#: demonstrator naming the mistakes this cohort actually makes.
EXPERIMENT_SEEDS: dict[str, tuple[ExceptionEntry, ...]] = {}

MAX_ENTRIES_PER_EXPERIMENT = 10


def entries_for(experiment_id: str) -> tuple[ExceptionEntry, ...]:
    seeded = EXPERIMENT_SEEDS.get(experiment_id, ())
    generic = tuple(e for e in GENERIC_ENTRIES if e.applies_to(experiment_id))
    combined = seeded + generic
    if len(combined) > MAX_ENTRIES_PER_EXPERIMENT:
        # Experiment-specific entries win the cap: they are more precise
        # than the generic ones and less likely to misattribute.
        combined = combined[:MAX_ENTRIES_PER_EXPERIMENT]
    return combined


def lookup(experiment_id: str, *, remarks: str, context: dict[str, Any] | None = None) -> Tier2Match | None:
    """First matching entry, or None.

    Returning None is the expected outcome for most cases and is not a
    failure -- it hands the case to Tier 3, which is the honest answer
    when nothing in a curated list actually fits.
    """
    for entry in entries_for(experiment_id):
        if entry.matches(remarks):
            return Tier2Match(entry=entry, matched_on=remarks[:200])
    return None
