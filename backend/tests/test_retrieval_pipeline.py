"""End-to-end pipeline: normalise -> classify -> retrieve -> rerank ->
generate -> cite -> validate.

Uses a small synthetic fixture corpus rather than the real (absent)
manual. The fixture text is deliberately generic placeholder content --
these tests exercise the *plumbing* (routing, filtering, citation,
statuses), not any factual claim about chemistry, and none of it is
golden-dataset material.
"""

from __future__ import annotations

import pytest

from backend.retrieval.chunks import Chunk, ContentType
from backend.retrieval.index import HybridIndex
from backend.retrieval.pipeline import answer_question
from backend.scope.statuses import AnswerStatus
from backend.sources.tiers import SourceTier


def _chunk(
    cid: str,
    text: str,
    *,
    tier: SourceTier = SourceTier.OFFICIAL_MANUAL,
    experiment_id: str | None = "exp07",
    page: int = 12,
    content_type: ContentType = ContentType.GENERAL,
) -> Chunk:
    return Chunk(
        chunk_id=cid, text=text, document_id="iachy102_manual_2026_27",
        document_title="IACHY102 manual", tier=tier, source_version="2026-27",
        page=page, experiment_id=experiment_id, content_type=content_type,
    )


FIXTURE_CHUNKS = [
    _chunk(
        "orbital1",
        "After the optimisation job completes, open the output file and locate "
        "the HOMO and LUMO orbital energies listed near the end.",
        experiment_id="exp07", content_type=ContentType.SOFTWARE_STEP,
    ),
    _chunk(
        "orbital2",
        "Click the Orbitals tab in Gabedit to visualise the orbital contribution "
        "for the selected molecular orbital.",
        experiment_id="exp07", content_type=ContentType.SOFTWARE_STEP,
    ),
    _chunk(
        "kinetics1",
        "The pseudo first order rate constant for the acid-catalysed hydrolysis "
        "of ethyl acetate is obtained from the slope of the titration data.",
        experiment_id="exp02",
    ),
    _chunk(
        "colorimetry1",
        "Prepare Ni2+ standard solutions and record the absorbance of each for "
        "the calibration curve before measuring the unknown sample.",
        experiment_id="exp03",
    ),
    _chunk(
        "adjacent_dft",
        "Density functional theory approximates the electron density rather than "
        "solving the full wavefunction, which is why basis set choice affects "
        "convergence behaviour in practice.",
        tier=SourceTier.CURATED_ADJACENT, experiment_id="exp07",
    ),
]


@pytest.fixture
def fixture_index() -> HybridIndex:
    return HybridIndex(FIXTURE_CHUNKS)


# ---------------------------------------------------------------------------
# The headline cases
# ---------------------------------------------------------------------------


async def test_direct_question_with_evidence_is_supported_and_cited(fixture_index):
    result = await answer_question(
        "where do i find the homo lumo orbital energy", index=fixture_index, use_llm=False
    )
    assert result.status is AnswerStatus.IN_SCOPE_SUPPORTED
    assert result.citations
    assert all(c.tier is SourceTier.OFFICIAL_MANUAL for c in result.citations)
    assert not result.supplementary
    assert "output file" in result.text.lower() or "orbital" in result.text.lower()


async def test_qualitative_experiment_is_answered_from_its_own_material_not_refused(fixture_index):
    """Exp7/8 policy: their whole source material is a handful of chunks, so
    the generic keyword grounding bar wrongly refuses natural troubleshooting
    phrasings. An in-scope question is answered from the experiment's own
    passages (the model is still bound to say what they do not cover)."""
    result = await answer_question(
        "how do i fix an obscure orca convergence error nobody documents",
        active_experiment="exp07",
        index=fixture_index,
        use_llm=False,
    )
    assert result.status is AnswerStatus.IN_SCOPE_SUPPORTED
    assert result.citations


async def test_out_of_scope_question_is_refused_before_any_retrieval(fixture_index):
    result = await answer_question("what is the best gpu for gaming", index=fixture_index, use_llm=False)
    assert result.status is AnswerStatus.OUT_OF_SCOPE
    assert not result.citations
    assert not result.passages


async def test_adjacent_question_uses_supplementary_material_and_labels_it(fixture_index):
    result = await answer_question(
        "why does basis set choice affect convergence physically",
        active_experiment="exp07",
        index=fixture_index,
        use_llm=False,
    )
    assert result.status is AnswerStatus.ADJACENT_SUPPORTED
    assert result.supplementary
    assert result.citations
    assert result.citations[0].tier is SourceTier.CURATED_ADJACENT
    assert "supplementary" in result.text.lower()


async def test_adjacent_exp07_question_without_background_is_still_answered_from_the_procedure():
    """Exp7 policy: no 'I do not have a source I trust' refusal for an
    in-experiment question. Without background material the answer is
    built from the experiment's own procedure, and the model is still
    bound to say what that material does not cover."""
    index = HybridIndex([c for c in FIXTURE_CHUNKS if c.tier is not SourceTier.CURATED_ADJACENT])
    result = await answer_question(
        "why does basis set choice affect convergence physically",
        active_experiment="exp07",
        index=index,
        use_llm=False,
    )
    assert result.status is AnswerStatus.IN_SCOPE_SUPPORTED
    assert result.citations
    assert all(c.tier is not SourceTier.CURATED_ADJACENT for c in result.citations)

async def test_experiment_filtering_prevents_cross_contamination(fixture_index):
    """A question routed to experiment 7 must not be answered from
    experiment 3's colorimetry material, even asking about 'calibration'-
    adjacent ideas that share surface vocabulary."""
    result = await answer_question(
        "orca ka homo output kaha milega", index=fixture_index, use_llm=False
    )
    assert result.decision.experiment_id == "exp07"
    for citation in result.citations:
        assert citation.chunk_id in {"orbital1", "orbital2"}


async def test_messy_hinglish_question_is_answered_like_its_clean_equivalent(fixture_index):
    clean = await answer_question("where do i find the homo orbital energy", index=fixture_index, use_llm=False)
    messy = await answer_question("orbital energy ka homo kaha milega", index=fixture_index, use_llm=False)
    assert clean.status == messy.status == AnswerStatus.IN_SCOPE_SUPPORTED
    assert clean.decision.experiment_id == messy.decision.experiment_id == "exp07"


async def test_empty_corpus_is_retrieval_insufficient_not_out_of_scope():
    result = await answer_question(
        "where is the homo orbital energy", active_experiment="exp07",
        index=HybridIndex([]), use_llm=False,
    )
    assert result.status is AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT


async def test_llm_unavailable_falls_back_to_extractive_answer(fixture_index):
    """No LLM is configured in the test environment (see conftest.py), so
    use_llm=True must still produce a deterministic extractive answer
    rather than raising or hanging on a network call."""
    result = await answer_question(
        "where do i find the homo lumo orbital energy", index=fixture_index, use_llm=True
    )
    assert result.status is AnswerStatus.IN_SCOPE_SUPPORTED
    assert result.answer_source == "extractive"
    assert result.text


# ---------------------------------------------------------------------------
# Response validation as an internal contract
# ---------------------------------------------------------------------------


async def test_every_citation_references_a_retrieved_chunk(fixture_index):
    result = await answer_question(
        "where do i find the homo lumo orbital energy", index=fixture_index, use_llm=False
    )
    retrieved_ids = {p.chunk.chunk_id for p in result.passages}
    for citation in result.citations:
        assert citation.chunk_id in retrieved_ids


async def test_non_answering_statuses_never_carry_citations(fixture_index):
    for message in ("what is the best gpu for gaming", "some obscure unanswerable orca crash"):
        result = await answer_question(message, active_experiment="exp07", index=fixture_index, use_llm=False)
        if not result.status.answerable:
            assert result.citations == ()


async def test_off_topic_message_is_refused_mid_session_not_answered_as_a_gap(fixture_index):
    """Regression from scripts/demo_exp7.py: a multi-turn session that has
    been asking about experiment 7 must still refuse a message with no
    connection to it, rather than reporting it as an experiment-7
    retrieval gap because the session carried an active experiment."""
    on_topic = await answer_question(
        "where do i find the homo lumo orbital energy", index=fixture_index, use_llm=False
    )
    assert on_topic.decision.experiment_id == "exp07"

    off_topic = await answer_question(
        "what is the best gpu for gaming",
        active_experiment=on_topic.decision.experiment_id,
        index=fixture_index,
        use_llm=False,
    )
    assert off_topic.status is AnswerStatus.OUT_OF_SCOPE
    assert off_topic.decision.experiment_id is None
    assert not off_topic.citations


def test_leaked_passage_references_are_stripped_without_touching_layout():
    from backend.retrieval.pipeline import _strip_passage_refs

    assert _strip_passage_refs("opens it (Passage 5). Then") == "opens it. Then"
    assert _strip_passage_refs("steps [3] and [1, 5] go (Passage [2], [3]) ok") == "steps go ok"
    nested = "1.  **Open** Gabedit\n    *   nested item [4]\nnext"
    assert _strip_passage_refs(nested) == "1.  **Open** Gabedit\n    *   nested item\nnext"
    assert _strip_passage_refs("Step 5 of 6 costs 5 eV") == "Step 5 of 6 costs 5 eV"
