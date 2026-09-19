"""Source tier definitions and precedence rules.

See the package docstring for what each tier means and why.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class SourceTier(str, enum.Enum):
    """Authority tiers, highest first. Ordering is by `rank`, not by name."""

    OFFICIAL_MANUAL = "A"
    OFFICIAL_SUPPLEMENTARY = "B"
    CURATED_ADJACENT = "C"
    MODEL_KNOWLEDGE = "D"

    @property
    def rank(self) -> int:
        """Lower is more authoritative."""
        return _RANKS[self]

    @property
    def label(self) -> str:
        """Short human-readable name, used in citations and in the UI."""
        return _LABELS[self]


_RANKS: dict[SourceTier, int] = {
    SourceTier.OFFICIAL_MANUAL: 0,
    SourceTier.OFFICIAL_SUPPLEMENTARY: 1,
    SourceTier.CURATED_ADJACENT: 2,
    SourceTier.MODEL_KNOWLEDGE: 3,
}

_LABELS: dict[SourceTier, str] = {
    SourceTier.OFFICIAL_MANUAL: "official manual",
    SourceTier.OFFICIAL_SUPPLEMENTARY: "official course material",
    SourceTier.CURATED_ADJACENT: "supplementary (not the manual)",
    SourceTier.MODEL_KNOWLEDGE: "general model knowledge",
}


class Usage(str, enum.Enum):
    """What a retrieved passage is about to be used for.

    Which tiers are permitted depends on the question being answered, not
    only on what happened to be retrieved.
    """

    #: Procedure, formula, table, numbering, software step, official
    #: expected relationship. The manual's exclusive territory.
    EXPERIMENT_INSTRUCTION = "experiment_instruction"
    #: Interpretation or background that is adjacent to the experiment.
    ADJACENT_EXPLANATION = "adjacent_explanation"
    #: Describing what a supplied script or notebook itself does.
    SUPPLIED_ARTEFACT = "supplied_artefact"


#: Which tiers may supply the substance of an answer, per usage.
#:
#: Tier D appears in none of them. That is the point: the model may
#: phrase any of these, and may supply the substance of none.
_PERMITTED: dict[Usage, tuple[SourceTier, ...]] = {
    Usage.EXPERIMENT_INSTRUCTION: (
        SourceTier.OFFICIAL_MANUAL,
        SourceTier.OFFICIAL_SUPPLEMENTARY,
    ),
    Usage.ADJACENT_EXPLANATION: (
        SourceTier.OFFICIAL_MANUAL,
        SourceTier.OFFICIAL_SUPPLEMENTARY,
        SourceTier.CURATED_ADJACENT,
    ),
    Usage.SUPPLIED_ARTEFACT: (
        SourceTier.OFFICIAL_SUPPLEMENTARY,
        SourceTier.OFFICIAL_MANUAL,
    ),
}


def permitted_tiers_for(usage: Usage) -> tuple[SourceTier, ...]:
    """Tiers allowed to supply substance for this kind of answer.

    Note that `EXPERIMENT_INSTRUCTION` excludes Tier C. A student asking
    how to run the official procedure must not be handed a general
    explainer's version of it, however good the explainer is.
    """
    return _PERMITTED[usage]


def is_retrievable(tier: SourceTier) -> bool:
    """Whether this tier can appear in a retrieval index at all.

    Tier D cannot: there is no document to index, and pretending there is
    one is how a model's guess acquires a citation.
    """
    return tier is not SourceTier.MODEL_KNOWLEDGE


def requires_supplementary_label(tier: SourceTier) -> bool:
    """Whether an answer from this tier must be visibly marked as not-the-manual.

    Tier B (official course material beyond the manual transcription
    itself, e.g. a fuller source PDF/DOCX) is still not the manual, and a
    citation that renders identically to a tier-A one would silently
    misrepresent that -- so it gets a label too, distinct from tier C's.
    """
    return tier in (SourceTier.OFFICIAL_SUPPLEMENTARY, SourceTier.CURATED_ADJACENT)


def outranks(a: SourceTier, b: SourceTier) -> bool:
    return a.rank < b.rank


@dataclass(frozen=True)
class SourceDocument:
    """One ingestible document and its provenance.

    `version` is what makes re-ingestion safe: chunk IDs are derived from
    (document_id, version, locator), so re-ingesting a revised manual
    produces new IDs rather than silently overwriting passages that no
    longer say what they used to.
    """

    document_id: str
    tier: SourceTier
    filename: str
    title: str
    version: str
    #: Experiments this document covers. Empty means "not
    #: experiment-scoped" (e.g. a general safety appendix).
    experiments: tuple[str, ...] = ()
    #: Set when the file is expected but absent, so the ingester can
    #: report a blocked source instead of an empty one.
    present: bool = False
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not is_retrievable(self.tier):
            raise ValueError(
                f"{self.document_id}: tier D is not a document tier. Model "
                "knowledge cannot be ingested, indexed or cited."
            )
        if not self.version:
            raise ValueError(f"{self.document_id}: a source document needs a version")


def citation_for(
    document: SourceDocument, *, page: int | None = None, section: str = ""
) -> str:
    """A citation string that never misrepresents which tier it came from.

    Tier C citations say so in the citation itself, not only in
    surrounding UI chrome, because the citation is the part that gets
    screenshotted and quoted back.
    """
    parts = [document.title]
    if section:
        parts.append(section)
    if page is not None:
        parts.append(f"p. {page}")
    base = ", ".join(parts)
    if document.tier is SourceTier.CURATED_ADJACENT:
        return f"{base} — supplementary material, not the IACHY102 manual"
    if document.tier is SourceTier.OFFICIAL_SUPPLEMENTARY:
        return f"{base} — official supplementary material, not the IACHY102 manual itself"
    return base


@dataclass(frozen=True)
class SourceConflict:
    """A Tier B statement that contradicts Tier A.

    Never resolved automatically. The brief is explicit that a Tier B
    implementation contradicting Tier A must be flagged rather than
    silently preferred, and a system that picks a winner is a system that
    hides the disagreement from the person who can actually settle it.
    """

    experiment_id: str
    topic: str
    manual_statement: str
    supplementary_statement: str
    manual_citation: str
    supplementary_citation: str

    def render(self) -> str:
        return (
            f"Conflict on '{self.topic}' for {self.experiment_id}: the manual "
            f"({self.manual_citation}) and the supplied course material "
            f"({self.supplementary_citation}) disagree. The manual takes "
            "precedence, and this needs a human to reconcile."
        )


def detect_conflicts(
    claims: list[tuple[SourceDocument, str, str, str]],
) -> list[SourceConflict]:
    """Find topics where Tier A and Tier B assert different things.

    `claims` are ``(document, experiment_id, topic, statement)`` tuples,
    normally produced during ingestion from sections that were tagged
    with the same topic key.

    Comparison is by normalised exact text. This deliberately catches only
    flat contradictions rather than trying to judge semantic equivalence:
    a cheap detector that a human reviews beats a clever one that decides
    on its own which source was right.
    """
    by_topic: dict[tuple[str, str], dict[SourceTier, tuple[SourceDocument, str]]] = {}
    for document, experiment_id, topic, statement in claims:
        key = (experiment_id, topic)
        by_topic.setdefault(key, {})[document.tier] = (document, statement)

    conflicts: list[SourceConflict] = []
    for (experiment_id, topic), per_tier in sorted(by_topic.items()):
        a = per_tier.get(SourceTier.OFFICIAL_MANUAL)
        b = per_tier.get(SourceTier.OFFICIAL_SUPPLEMENTARY)
        if a is None or b is None:
            continue
        if _normalise(a[1]) == _normalise(b[1]):
            continue
        conflicts.append(
            SourceConflict(
                experiment_id=experiment_id,
                topic=topic,
                manual_statement=a[1],
                supplementary_statement=b[1],
                manual_citation=citation_for(a[0]),
                supplementary_citation=citation_for(b[0]),
            )
        )
    return conflicts


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())
