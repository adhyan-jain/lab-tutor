"""The source hierarchy must hold as code, not as intention."""

from __future__ import annotations

import json

import pytest

from backend.sources import (
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
from backend.sources.manifest import (
    ManifestError,
    current_manual,
    get_manifest,
    load_manifest,
    manifest_path,
)


def _doc(tier: SourceTier, **kw) -> SourceDocument:
    defaults = dict(
        document_id=f"doc_{tier.value}",
        tier=tier,
        filename="f.pdf",
        title=f"Document {tier.value}",
        version="1",
    )
    defaults.update(kw)
    return SourceDocument(**defaults)


# --- precedence -----------------------------------------------------------


def test_tier_a_outranks_every_other_tier():
    for other in (
        SourceTier.OFFICIAL_SUPPLEMENTARY,
        SourceTier.CURATED_ADJACENT,
        SourceTier.MODEL_KNOWLEDGE,
    ):
        assert outranks(SourceTier.OFFICIAL_MANUAL, other)
        assert not outranks(other, SourceTier.OFFICIAL_MANUAL)


def test_ranks_are_strictly_ordered_a_b_c_d():
    ranks = [t.rank for t in (
        SourceTier.OFFICIAL_MANUAL,
        SourceTier.OFFICIAL_SUPPLEMENTARY,
        SourceTier.CURATED_ADJACENT,
        SourceTier.MODEL_KNOWLEDGE,
    )]
    assert ranks == sorted(ranks) == [0, 1, 2, 3]


# --- tier D is not a source ----------------------------------------------


def test_model_knowledge_is_never_retrievable():
    assert not is_retrievable(SourceTier.MODEL_KNOWLEDGE)
    for tier in (
        SourceTier.OFFICIAL_MANUAL,
        SourceTier.OFFICIAL_SUPPLEMENTARY,
        SourceTier.CURATED_ADJACENT,
    ):
        assert is_retrievable(tier)


def test_a_tier_d_source_document_cannot_be_constructed():
    with pytest.raises(ValueError, match="tier D is not a document tier"):
        _doc(SourceTier.MODEL_KNOWLEDGE)


def test_model_knowledge_may_not_supply_substance_for_any_usage():
    for usage in Usage:
        assert SourceTier.MODEL_KNOWLEDGE not in permitted_tiers_for(usage)


def test_curated_adjacent_may_not_supply_experiment_instructions():
    """A general explainer must not stand in for the official procedure."""
    permitted = permitted_tiers_for(Usage.EXPERIMENT_INSTRUCTION)
    assert SourceTier.CURATED_ADJACENT not in permitted
    assert SourceTier.OFFICIAL_MANUAL in permitted


def test_curated_adjacent_may_supply_adjacent_explanations():
    assert SourceTier.CURATED_ADJACENT in permitted_tiers_for(Usage.ADJACENT_EXPLANATION)


# --- labelling ------------------------------------------------------------


def test_only_tier_a_is_exempt_from_a_supplementary_label():
    """Tier A (the manual itself) is the only tier that never needs the
    label. Tier B is official course material but still not the manual
    transcription, so it gets a label too, distinct from tier C's -- see
    `citation_for`."""
    assert requires_supplementary_label(SourceTier.CURATED_ADJACENT)
    assert requires_supplementary_label(SourceTier.OFFICIAL_SUPPLEMENTARY)
    assert not requires_supplementary_label(SourceTier.OFFICIAL_MANUAL)


def test_tier_c_citation_says_it_is_not_the_manual():
    """The disclaimer lives in the citation, because that is the part that
    survives being screenshotted and quoted back."""
    citation = citation_for(_doc(SourceTier.CURATED_ADJACENT), page=4)
    assert "not the IACHY102 manual" in citation


def test_tier_b_citation_says_it_is_not_the_manual_and_differs_from_tier_c():
    citation = citation_for(_doc(SourceTier.OFFICIAL_SUPPLEMENTARY), page=4)
    assert "not the IACHY102 manual" in citation
    assert citation != citation_for(_doc(SourceTier.CURATED_ADJACENT), page=4)


def test_tier_a_citation_carries_no_disclaimer():
    citation = citation_for(_doc(SourceTier.OFFICIAL_MANUAL), page=12, section="7.3")
    assert "supplementary" not in citation
    assert "p. 12" in citation and "7.3" in citation


# --- conflicts ------------------------------------------------------------


def test_tier_b_contradicting_tier_a_is_flagged_not_resolved():
    conflicts = detect_conflicts(
        [
            (_doc(SourceTier.OFFICIAL_MANUAL), "exp07", "basis_set", "Use 6-31G"),
            (_doc(SourceTier.OFFICIAL_SUPPLEMENTARY), "exp07", "basis_set", "Use def2-SVP"),
        ]
    )
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.experiment_id == "exp07"
    assert conflict.topic == "basis_set"
    # Both statements survive. Nothing was silently chosen.
    assert "6-31G" in conflict.manual_statement
    assert "def2-SVP" in conflict.supplementary_statement
    assert "needs a human" in conflict.render()


def test_agreeing_sources_produce_no_conflict():
    assert not detect_conflicts(
        [
            (_doc(SourceTier.OFFICIAL_MANUAL), "exp07", "basis_set", "Use 6-31G"),
            (_doc(SourceTier.OFFICIAL_SUPPLEMENTARY), "exp07", "basis_set", "use  6-31g "),
        ]
    )


def test_tier_c_disagreeing_with_tier_a_is_not_a_conflict():
    """Tier C is expected to say different things: it answers different
    questions. Only A-versus-B is a contradiction worth a human's time."""
    assert not detect_conflicts(
        [
            (_doc(SourceTier.OFFICIAL_MANUAL), "exp07", "basis_set", "Use 6-31G"),
            (_doc(SourceTier.CURATED_ADJACENT), "exp07", "basis_set", "Basis sets vary"),
        ]
    )


# --- manifest -------------------------------------------------------------


def test_repository_manifest_loads_and_validates():
    manifest = get_manifest()
    assert len(manifest) >= 4
    assert manifest.manifest_version


def test_exactly_one_current_manual_and_it_is_iachy102():
    entry = current_manual()
    assert "iachy102" in entry.document_id.lower()
    assert entry.tier is SourceTier.OFFICIAL_MANUAL


def test_superseded_bachy105_manual_is_declared_and_not_ingestible():
    """A stray copy of the old manual must be recognised and refused,
    which is only possible if it is declared."""
    entry = get_manifest().by_id("iachy102_manual_legacy_bachy105")
    assert entry.is_superseded
    assert not entry.ingestible


def test_golden_qa_is_never_ingestible():
    """A system that can retrieve its own test set scores well for the
    wrong reason."""
    entry = get_manifest().by_id("golden_qa_v1")
    assert entry.document.present
    assert not entry.indexable
    assert not entry.ingestible


def test_current_manual_is_present_and_not_silently_missing():
    """Before the manifest fix, this test guarded against a missing
    *current* manual being silently skipped by ingestion rather than
    reported as blocked. That scenario no longer exists: the document
    actually ingested (iachy102_manual_markdown) is declared and present.
    The original PDF and the legacy BACHY105 manual are absent but
    explicitly marked superseded, so neither shows up as a blocker (an
    unrelated, pre-existing pair of Tier B exp07 scripts are still
    legitimately blocked/absent and are not part of what this test
    guards)."""
    manifest = get_manifest()
    current = current_manual()
    assert current.document_id == "iachy102_manual_markdown"
    assert current.document.present
    blocked_ids = {e.document_id for e in manifest.blocked()}
    assert "iachy102_manual_2026_27_pdf" not in blocked_ids
    assert "iachy102_manual_legacy_bachy105" not in blocked_ids


def test_unknown_role_is_rejected(tmp_path):
    bad = json.loads(manifest_path().read_text(encoding="utf-8"))
    bad["documents"][0]["role"] = "vibes"
    target = tmp_path / "m.json"
    target.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ManifestError, match="unknown role"):
        load_manifest(target)


def test_two_current_manuals_are_rejected(tmp_path):
    bad = json.loads(manifest_path().read_text(encoding="utf-8"))
    for doc in bad["documents"]:
        doc.pop("superseded_by", None)
    target = tmp_path / "m.json"
    target.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ManifestError, match="Exactly one official_manual"):
        load_manifest(target)


def test_dangling_superseded_by_is_rejected(tmp_path):
    bad = json.loads(manifest_path().read_text(encoding="utf-8"))
    bad["documents"][1]["superseded_by"] = "does_not_exist"
    target = tmp_path / "m.json"
    target.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ManifestError, match="not declared in the manifest"):
        load_manifest(target)
