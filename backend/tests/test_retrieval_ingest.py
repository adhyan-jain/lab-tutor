"""Ingestion: chunking, provenance, and manifest-gated reporting."""

from __future__ import annotations

import pytest

from backend.retrieval import ingest
from backend.retrieval.chunks import ContentType
from backend.sources.manifest import ManifestEntry, get_manifest
from backend.sources.tiers import SourceDocument, SourceTier


def _entry(**overrides) -> ManifestEntry:
    document = SourceDocument(
        document_id=overrides.pop("document_id", "test_doc"),
        tier=overrides.pop("tier", SourceTier.OFFICIAL_MANUAL),
        filename=overrides.pop("filename", "manual/does_not_exist.pdf"),
        title=overrides.pop("title", "Test Document"),
        version=overrides.pop("version", "1.0"),
        experiments=overrides.pop("experiments", ()),
        present=overrides.pop("present", False),
    )
    return ManifestEntry(
        document=document,
        role=overrides.pop("role", "official_manual"),
        visual=overrides.pop("visual", True),
        indexable=overrides.pop("indexable", True),
        superseded_by=overrides.pop("superseded_by", None),
    )


# ---------------------------------------------------------------------------
# Reporting: blocked vs excluded vs ingested
# ---------------------------------------------------------------------------


def test_absent_document_is_reported_blocked_not_silently_empty():
    report = ingest.ingest_document(_entry(present=False))
    assert report.status == "blocked"
    assert report.chunk_count == 0
    assert "not present" in report.reason


def test_superseded_document_is_reported_excluded():
    report = ingest.ingest_document(_entry(superseded_by="newer_doc", present=True))
    assert report.status == "excluded"
    assert "superseded" in report.reason


def test_non_indexable_document_is_reported_excluded():
    report = ingest.ingest_document(_entry(indexable=False, present=True))
    assert report.status == "excluded"
    assert "non-indexable" in report.reason


def test_present_but_missing_on_disk_is_still_blocked_not_a_crash():
    report = ingest.ingest_document(
        _entry(present=True, filename="manual/definitely_not_here.pdf")
    )
    assert report.status == "blocked"


def test_manifest_documents_all_route_through_the_same_reporting(tmp_path):
    reports = ingest.ingest_all()
    ids = {r.document_id for r in reports}
    assert ids == {e.document_id for e in get_manifest()}
    for report in reports:
        assert report.status in ("blocked", "excluded", "ingested")


# ---------------------------------------------------------------------------
# Chunking mechanics (white-box: these are pure functions, not I/O)
# ---------------------------------------------------------------------------


def test_pack_respects_max_chars_and_keeps_paragraphs_intact():
    paragraphs = ["A" * 500, "B" * 500, "C" * 100]
    packed = ingest._pack(paragraphs, max_chars=900)
    assert len(packed) == 2
    assert packed[0] == "A" * 500
    assert "B" * 500 in packed[1] and "C" * 100 in packed[1]


def test_pack_never_splits_a_single_paragraph():
    huge = "X" * 5000
    packed = ingest._pack([huge], max_chars=900)
    assert packed == [huge]


def test_content_type_classification():
    assert ingest._classify_content("Table 3: calibration standards") == ContentType.TABLE
    assert ingest._classify_content("See Figure 2 below") == ContentType.FIGURE_CAPTION
    assert (
        ingest._classify_content("Click Optimize, then select the input file")
        == ContentType.SOFTWARE_STEP
    )
    assert ingest._classify_content("k = 0.014 min^-1 (t)") == ContentType.FORMULA
    assert (
        ingest._classify_content("Worked example: a student obtained...")
        == ContentType.WORKED_EXAMPLE
    )
    assert ingest._classify_content("This experiment studies reaction rates.") == ContentType.GENERAL


MD_SYNTHETIC = """\
## Assessed experiment set (p.7)

| # | Title |
|---|---|
| 1 | Thermodynamics |
| 2 | Kinetics |

## Experiment 1 — Thermodynamics (p.10-12)

Ecell measured across the Daniell cell; ΔG = -nFEcell.

## Experiment 2 — Kinetics (p.16-19)

Pseudo first order rate constant from the slope of log(Vinf - Vt) vs t.

## Summary: worked examples

| # | Has worked example |
|---|---|
| 1 | yes |
"""


class TestMarkdownExperimentHeadingSplit:
    """Regression coverage for a real live bug found and fixed this
    session: a multi-experiment markdown manual ingested as ONE page-1
    unit, so a short front-matter/summary table (dense in generic terms)
    consistently outranked the real per-experiment section, and every
    citation said "p. 1" no matter which experiment was actually asked
    about. Fixed by `_split_markdown_by_experiment_heading`; verified
    live against `manual/IACHY102_manual.md` before writing this test
    (Nernst-equation query top-ranked the front-matter summary table
    before the fix, Experiment 1's own section after)."""

    def test_front_matter_and_summary_tables_are_excluded(self, tmp_path):
        path = tmp_path / "synthetic_manual.md"
        path.write_text(MD_SYNTHETIC, encoding="utf-8")
        report = ingest.ingest_document(
            _entry(present=True, filename=str(path), role="official_manual")
        )
        assert report.status == "ingested"
        texts = [c.text for c in report.chunks]
        assert not any("Assessed experiment set" in t for t in texts)
        assert not any("worked examples" in t.lower() for t in texts)

    def test_each_experiment_heading_gets_its_own_page_and_attribution(self, tmp_path):
        path = tmp_path / "synthetic_manual.md"
        path.write_text(MD_SYNTHETIC, encoding="utf-8")
        report = ingest.ingest_document(
            _entry(present=True, filename=str(path), role="official_manual")
        )
        by_experiment = {c.experiment_id: c for c in report.chunks}
        assert by_experiment["exp01"].page == 10
        assert "Ecell" in by_experiment["exp01"].text
        assert by_experiment["exp02"].page == 16
        assert "rate constant" in by_experiment["exp02"].text

    def test_single_topic_file_with_no_experiment_heading_is_unaffected(self, tmp_path):
        """A curated adjacent-knowledge file has no "## Experiment N"
        structure at all -- must still ingest as one whole-file unit,
        the pre-existing (correct) behaviour for that source kind."""
        path = tmp_path / "exp07_orbital_background.md"
        path.write_text("## Background\n\nGeneral DFT theory notes.\n", encoding="utf-8")
        report = ingest.ingest_document(
            _entry(present=True, filename=str(path), role="curated_adjacent")
        )
        assert report.status == "ingested"
        assert report.page_count == 1
        assert report.chunks[0].page == 1

    def test_live_manual_citations_carry_real_page_numbers_not_page_one(self):
        """Live check against the actual shipped manual, not a fixture --
        the exact scenario the bug manifested in."""
        from backend.retrieval.index import get_index, reset_index_cache

        reset_index_cache()
        idx = get_index()
        exp01_chunks = [c for c in idx.chunks if c.experiment_id == "exp01"]
        assert exp01_chunks, "Experiment 1 should have at least one attributed chunk"
        assert all(c.page != 1 for c in exp01_chunks), (
            "Experiment 1's real content starts around p.10-15 in the manual; "
            "page=1 means the front-matter-collapse bug has regressed"
        )


def test_deterministic_chunk_ids_are_stable_across_calls():
    document = SourceDocument(
        document_id="doc1", tier=SourceTier.OFFICIAL_MANUAL, filename="f.pdf",
        title="Doc", version="1.0",
    )
    entry = _entry(document_id="doc1", present=True)
    a = ingest._chunk_page("Some procedure text here.", 3, document=document, entry=entry, image=None)
    b = ingest._chunk_page("Some procedure text here.", 3, document=document, entry=entry, image=None)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]


def test_chunk_id_changes_with_document_version():
    doc_v1 = SourceDocument(
        document_id="doc1", tier=SourceTier.OFFICIAL_MANUAL, filename="f.pdf",
        title="Doc", version="1.0",
    )
    doc_v2 = SourceDocument(
        document_id="doc1", tier=SourceTier.OFFICIAL_MANUAL, filename="f.pdf",
        title="Doc", version="2.0",
    )
    entry = _entry(document_id="doc1", present=True)
    a = ingest._chunk_page("Some text.", 1, document=doc_v1, entry=entry, image=None)
    b = ingest._chunk_page("Some text.", 1, document=doc_v2, entry=entry, image=None)
    assert a[0].chunk_id != b[0].chunk_id, (
        "a revised manual must produce new chunk IDs, not overwrite old ones"
    )


# ---------------------------------------------------------------------------
# Experiment attribution -- the anti-contamination rule
# ---------------------------------------------------------------------------


def test_single_experiment_document_attributes_every_chunk_to_it():
    document = SourceDocument(
        document_id="exp07_script", tier=SourceTier.OFFICIAL_SUPPLEMENTARY,
        filename="f.pdf", title="Exp7 script", version="1.0", experiments=("exp07",),
    )
    entry = _entry(document_id="exp07_script", present=True, experiments=("exp07",))
    chunks = ingest._chunk_page("Nothing chemistry-specific here at all.", 1, document=document, entry=entry, image=None)
    assert chunks[0].experiment_id == "exp07"


def test_manual_wide_document_attributes_by_strong_vocabulary():
    document = SourceDocument(
        document_id="manual", tier=SourceTier.OFFICIAL_MANUAL, filename="f.pdf",
        title="Manual", version="1.0", experiments=("exp07", "exp08", "exp02", "exp03"),
    )
    entry = _entry(document_id="manual", present=True, experiments=("exp07", "exp08", "exp02", "exp03"))
    homo_chunk = ingest._chunk_page(
        "Record the HOMO and LUMO orbital energies from the output file.",
        12, document=document, entry=entry, image=None,
    )
    assert homo_chunk[0].experiment_id == "exp07"

    kinetics_chunk = ingest._chunk_page(
        "The pseudo first order rate constant for ethyl acetate hydrolysis is calculated from the slope.",
        30, document=document, entry=entry, image=None,
    )
    assert kinetics_chunk[0].experiment_id == "exp02"


def test_ambiguous_manual_wide_chunk_is_left_unattributed_not_guessed():
    """Two computational experiments share vocabulary. A chunk hitting
    both must not be arbitrarily assigned to one of them."""
    document = SourceDocument(
        document_id="manual", tier=SourceTier.OFFICIAL_MANUAL, filename="f.pdf",
        title="Manual", version="1.0", experiments=("exp07", "exp08"),
    )
    entry = _entry(document_id="manual", present=True, experiments=("exp07", "exp08"))
    chunks = ingest._chunk_page(
        "Open Avogadro and run the optimisation before reading the energy.",
        5, document=document, entry=entry, image=None,
    )
    # Neither HOMO/LUMO nor staggered/chair vocabulary appears -- this is
    # generic software-workflow language shared by both, so it must stay
    # unattributed rather than land on whichever experiment happens first.
    assert chunks[0].experiment_id is None


def test_generic_wet_lab_sentence_does_not_get_attributed_to_a_computational_experiment():
    document = SourceDocument(
        document_id="manual", tier=SourceTier.OFFICIAL_MANUAL, filename="f.pdf",
        title="Manual", version="1.0", experiments=("exp02", "exp03"),
    )
    entry = _entry(document_id="manual", present=True, experiments=("exp02", "exp03"))
    chunks = ingest._chunk_page(
        "Record your observations in the table provided.",
        1, document=document, entry=entry, image=None,
    )
    assert chunks[0].experiment_id is None


# ---------------------------------------------------------------------------
# Filename-derived attribution hint (curated Tier C topic files)
# ---------------------------------------------------------------------------


def test_filename_hint_overrides_ambiguous_vocabulary():
    """A generic-sounding paragraph in a file named 'exp07_...' must still
    attribute to exp07, since it has none of exp07's distinctive terms."""
    document = SourceDocument(
        document_id="adjacent", tier=SourceTier.CURATED_ADJACENT, filename="d/",
        title="Adjacent", version="1.0", experiments=("exp02", "exp03", "exp07", "exp08"),
    )
    entry = _entry(document_id="adjacent", tier=SourceTier.CURATED_ADJACENT, present=True,
                    experiments=("exp02", "exp03", "exp07", "exp08"))
    chunks = ingest._chunk_page(
        "Check whether the job actually finished before concluding something is wrong.",
        1, document=document, entry=entry, image=None, experiment_hint="exp07",
    )
    assert chunks[0].experiment_id == "exp07"


def test_filename_hint_is_ignored_when_document_does_not_cover_that_experiment():
    document = SourceDocument(
        document_id="adjacent", tier=SourceTier.CURATED_ADJACENT, filename="d/",
        title="Adjacent", version="1.0", experiments=("exp02", "exp03"),
    )
    entry = _entry(document_id="adjacent", tier=SourceTier.CURATED_ADJACENT, present=True,
                    experiments=("exp02", "exp03"))
    chunks = ingest._chunk_page(
        "Generic troubleshooting text with no distinctive vocabulary.",
        1, document=document, entry=entry, image=None, experiment_hint="exp07",
    )
    assert chunks[0].experiment_id is None


def test_filename_experiment_hint_extraction():
    import pathlib

    assert ingest._filename_experiment_hint(pathlib.Path("exp07_orca_troubleshooting.md")) == "exp07"
    assert ingest._filename_experiment_hint(pathlib.Path("exp02-kinetics.md")) == "exp02"
    assert ingest._filename_experiment_hint(pathlib.Path("general_notes.md")) is None


def test_adjacent_knowledge_directory_ingests_with_correct_attribution():
    """Integration check against the real knowledge/adjacent/ directory
    committed to this repository."""
    entry = get_manifest().by_id("adjacent_knowledge_v1")
    report = ingest.ingest_document(entry)
    assert report.status == "ingested"
    assert report.chunk_count > 0
    unattributed = [c for c in report.chunks if c.experiment_id is None]
    assert not unattributed, (
        "every curated adjacent file names its experiment by filename "
        f"convention; unexpected unattributed chunks: {unattributed}"
    )
    assert {c.experiment_id for c in report.chunks} == {"exp02", "exp03", "exp07", "exp08"}
    assert all(c.tier == SourceTier.CURATED_ADJACENT for c in report.chunks)


def test_exp07_exp08_tier_b_supplementary_document_ingests_with_correct_attribution():
    """Integration check against the real sources/tier_b/ document added
    for the genuinely-new Exp7/Exp8 procedural detail (O2 build sequence,
    Gabedit version, ORCA run command) found outside the manual
    transcription."""
    entry = get_manifest().by_id("exp07_exp08_supplementary_v1")
    report = ingest.ingest_document(entry)
    assert report.status == "ingested"
    assert report.chunk_count > 0
    assert {c.experiment_id for c in report.chunks} == {"exp07", "exp08"}
    assert all(c.tier == SourceTier.OFFICIAL_SUPPLEMENTARY for c in report.chunks)


def test_tier_b_citation_is_visibly_distinct_from_tier_a():
    """The user's explicit requirement: supplied course material beyond
    the manual transcription must be cited as supplementary, not silently
    rendered identically to a manual citation."""
    from backend.sources.tiers import citation_for

    manual_doc = SourceDocument(
        document_id="manual", tier=SourceTier.OFFICIAL_MANUAL,
        filename="x.md", title="IACHY102 manual", version="1.0", present=True,
    )
    supplementary_doc = SourceDocument(
        document_id="supp", tier=SourceTier.OFFICIAL_SUPPLEMENTARY,
        filename="y.md", title="IACHY102 manual", version="1.0", present=True,
    )
    manual_citation = citation_for(manual_doc, page=39)
    supplementary_citation = citation_for(supplementary_doc, page=39)
    assert manual_citation != supplementary_citation
    assert "supplementary" in supplementary_citation.lower()
    assert "supplementary" not in manual_citation.lower()
