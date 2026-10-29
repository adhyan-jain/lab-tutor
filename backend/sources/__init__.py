"""Source hierarchy: which document is allowed to answer what.

Catalyst answers from several kinds of material, and they are not
interchangeable. A sentence from the official lab manual and a sentence
from a general chemistry explainer may both be true, but only one of
them is what the student will be assessed against, and only one of them
may be quoted as "the manual says".

Four tiers, in descending authority:

``A`` OFFICIAL_MANUAL
    The current IACHY102 manual. The authority for experiment numbering,
    scope, procedures, formulas, calculations, terminology, software
    workflow, tables, expected relationships, screenshots and worked
    examples. For a direct question about an experiment, Tier A wins.

``B`` OFFICIAL_SUPPLEMENTARY
    Scripts, notebooks and course documents officially supplied
    alongside an experiment. Authoritative about themselves (what the
    script does) but subordinate to Tier A about the experiment. When B
    contradicts A, the contradiction is *flagged*, never silently
    resolved in B's favour -- see `detect_conflicts`.

``C`` CURATED_ADJACENT
    Supplementary material written specifically to answer Level 2
    (adjacent) questions: broader theory, general software
    troubleshooting, background concepts. Real answers, but never the
    manual. Every Tier C answer carries a visible supplementary label;
    `requires_supplementary_label` is what enforces it.

``D`` MODEL_KNOWLEDGE
    What the language model knows on its own. It is **not a retrievable
    source** in this system and cannot be cited. It may phrase an answer
    grounded in A/B/C; it may never supply the substance of one. Asking
    the model to fill a gap in experimental instructions is the specific
    failure this tier exists to name and forbid.

The rules are encoded here rather than described in a prompt, because a
prompt is a request and this is a constraint.
"""

from __future__ import annotations

from backend.sources.tiers import (
    SourceConflict,
    SourceDocument,
    SourceTier,
    Usage,
    citation_for,
    detect_conflicts,
    is_retrievable,
    outranks,
    permitted_tiers_for,
    requires_supplementary_label,
)

__all__ = [
    "SourceConflict",
    "SourceDocument",
    "SourceTier",
    "Usage",
    "citation_for",
    "detect_conflicts",
    "is_retrievable",
    "outranks",
    "permitted_tiers_for",
    "requires_supplementary_label",
]
