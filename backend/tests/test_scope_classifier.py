"""Scope classification, and the separation it exists to guarantee."""

from __future__ import annotations

import pytest

from backend.scope import ontology
from backend.scope.classifier import (
    EvidenceSummary,
    classify_scope,
    resolve_status,
)
from backend.scope.statuses import AnswerStatus, ScopeLevel, fallback_text
from backend.socratic_engine import triage

EMPTY = EvidenceSummary(corpus_unavailable=True)
OFFICIAL = EvidenceSummary(official_count=3, top_official_score=0.8)
SUPPLEMENTARY = EvidenceSummary(supplementary_count=2, top_supplementary_score=0.7)


# ---------------------------------------------------------------------------
# The central invariant
# ---------------------------------------------------------------------------

#: Messy, real-shaped questions that are unambiguously about our subject.
IN_SCOPE_QUESTIONS = [
    "how to do exp 7",
    "exp 7 mein orca input kaha se banau",
    "orca ka output kaha milega",
    "methane ka homo kaise dekhu",
    "why my orbital contribution not coming",
    "bhai gabedit me woh option kidhar hai",
    "what method use for ch4",
    "mera orca run nahi hora",
    "why chair is more stable",
    "ethyl acetate ka k kaise nikale",
    "ni2 calibration graph kaise banega",
    "how to create methane in gabedit",
    "where geometry draw",
    "how make ch4",
    "orca input generator kaha hai",
    "what if job completion message not there",
    "where output file comes",
    "how get final energy",
    "after optimization what next",
    "how calculate orbital contribution",
    "where HOMO LUMO",
    "avogadro me homo kaise dekhe",
    "which method and basis set",
    "staggered eclipsed energy difference",
    "cyclohexane chair boat konsa stable",
    "pseudo first order kya hota hai",
    "rgb se concentration kaise nikale",
    "beer lambert calibration curve",
]


@pytest.mark.parametrize("question", IN_SCOPE_QUESTIONS)
def test_no_evidence_ever_makes_an_in_scope_question_out_of_scope(question):
    """The invariant the whole scope model exists to hold.

    Retrieval finding nothing is a fact about our corpus. It is never a
    fact about the student's question, and it must never be reported as
    one.
    """
    decision = classify_scope(question)
    assert decision.level is not ScopeLevel.OUT_OF_SCOPE, decision.rationale

    for evidence in (EMPTY, EvidenceSummary(), EvidenceSummary(corpus_unavailable=True)):
        status = resolve_status(decision, evidence)
        assert status is not AnswerStatus.OUT_OF_SCOPE
        assert status in (
            AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT,
            AnswerStatus.ADJACENT_UNSUPPORTED,
        )
        assert status.is_retrieval_gap, (
            "an unanswered in-scope question is a gap in our coverage and "
            "must be logged as one"
        )


def test_scope_decision_does_not_depend_on_evidence_at_all():
    """`classify_scope` has no parameter for evidence. That is the point."""
    import inspect

    params = set(inspect.signature(classify_scope).parameters)
    assert "evidence" not in params
    assert not {p for p in params if "retriev" in p or "passage" in p or "chunk" in p}


# ---------------------------------------------------------------------------
# The brief's own worked examples (§12)
# ---------------------------------------------------------------------------


def test_brief_example_orca_input_generator_is_supported_when_evidence_exists():
    decision = classify_scope("exp 7 me orca input generator kidhar hai")
    assert decision.experiment_id == "exp07"
    assert resolve_status(decision, OFFICIAL) is AnswerStatus.IN_SCOPE_SUPPORTED


def test_brief_example_why_dft_works_is_adjacent():
    decision = classify_scope("why does DFT work physically?", active_experiment="exp07")
    assert decision.level is ScopeLevel.ADJACENT
    assert resolve_status(decision, SUPPLEMENTARY) is AnswerStatus.ADJACENT_SUPPORTED
    assert resolve_status(decision, EMPTY) is AnswerStatus.ADJACENT_UNSUPPORTED


def test_brief_example_best_gpu_is_out_of_scope():
    decision = classify_scope("what is the best GPU for gaming?")
    assert decision.level is ScopeLevel.OUT_OF_SCOPE
    assert resolve_status(decision, OFFICIAL) is AnswerStatus.OUT_OF_SCOPE


def test_brief_example_obscure_orca_crash_is_insufficient_not_out_of_scope():
    """The example the brief spells out in capitals."""
    decision = classify_scope(
        "manual me exact batao why my ORCA job crashes with this obscure error"
    )
    assert decision.level is not ScopeLevel.OUT_OF_SCOPE
    assert resolve_status(decision, EMPTY) is AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("where is HOMO LUMO in avogadro", "exp07"),
        ("orbital contribution table kaise bhare", "exp07"),
        ("methane optimisation orca", "exp07"),
        ("staggered vs eclipsed ethane energy", "exp08"),
        ("cyclohexane chair boat which is lower", "exp08"),
        ("dihedral angle conformer", "exp08"),
        ("ethyl acetate hydrolysis rate constant", "exp02"),
        ("pseudo first order kinetics titration", "exp02"),
        ("ni2+ absorbance calibration curve", "exp03"),
        ("rgb smartphone colorimetry unknown concentration", "exp03"),
    ],
)
def test_routes_to_the_right_experiment(question, expected):
    assert classify_scope(question).experiment_id == expected


def test_explicit_experiment_number_beats_term_evidence():
    """If the student says which experiment, believe them.

    They can see the manual; a term-frequency score cannot.
    """
    decision = classify_scope("exp 3 me staggered eclipsed ka matlab kya hai")
    assert decision.experiment_id == "exp03"
    assert decision.confidence == 1.0


def test_explicitly_named_unpopulated_experiment_still_routes():
    """We do not know what experiment 5 is. That is our gap, not a reason
    to ignore a student who told us which one they are on."""
    decision = classify_scope("exp 5 ka procedure batao")
    assert decision.experiment_id == "exp05"
    assert decision.level is not ScopeLevel.OUT_OF_SCOPE
    assert resolve_status(decision, EMPTY) is AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT


def test_shared_software_does_not_arbitrarily_pick_between_exp7_and_exp8():
    """"open avogadro" alone cannot separate the two computational
    experiments; the session's own experiment should win over a coin flip."""
    for active in ("exp07", "exp08"):
        decision = classify_scope("avogadro me optimisation kaise kare", active_experiment=active)
        assert decision.experiment_id == active


def test_in_domain_question_with_no_experiment_is_still_in_scope():
    """"what is a burette" names no experiment and is not off-topic."""
    decision = classify_scope("what is a burette")
    assert decision.level is ScopeLevel.DIRECT
    assert decision.experiment_id is None
    assert decision.in_domain_unrouted
    assert resolve_status(decision, EMPTY) is AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT


def test_anaphora_inherits_the_session_experiment():
    decision = classify_scope("what comes after this screen", active_experiment="exp07")
    assert decision.experiment_id == "exp07"
    assert decision.query.has_anaphora


def test_anaphora_without_a_session_does_not_invent_an_experiment():
    decision = classify_scope("what comes after this screen")
    assert decision.experiment_id is None


# ---------------------------------------------------------------------------
# Out-of-scope is precision-biased
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "what is the best GPU for gaming?",
        "who won the cricket match",
        "write me a python script",
        "tell me about bitcoin",
        "solve my calculus integration homework",
    ],
)
def test_clearly_unrelated_questions_are_refused(question):
    assert classify_scope(question).level is ScopeLevel.OUT_OF_SCOPE


@pytest.mark.parametrize(
    "question",
    [
        "is a gaming gpu faster at running orca",
        "can i use python to plot my calibration curve",
        "my laptop is slow when orca runs",
    ],
)
def test_out_of_domain_words_do_not_refuse_a_question_that_is_also_in_domain(question):
    """These contain refusal-triggering vocabulary and a real lab subject.
    Refusing them teaches the student the tool is broken."""
    assert classify_scope(question).level is not ScopeLevel.OUT_OF_SCOPE


def test_safety_short_circuit_is_preserved_and_not_reclassified():
    decision = classify_scope("acid went on my hand")
    assert decision.triage_intent is triage.Intent.SAFETY_INCIDENT
    assert decision.level is not ScopeLevel.OUT_OF_SCOPE


@pytest.mark.parametrize("active", [None, "exp07", "exp02", "exp08"])
def test_an_active_session_experiment_never_immunises_a_genuine_refusal(active):
    """Regression: a session left open on an experiment must not shield an
    unrelated later message from being refused. Found by running
    scripts/demo_exp7.py, where turn 15 ('what is the best gpu for
    gaming') was wrongly answered as an experiment-7 retrieval gap
    because the session's active_experiment from the prior turn was
    treated as evidence the message itself never provided."""
    decision = classify_scope("what is the best gpu for gaming", active_experiment=active)
    assert decision.level is ScopeLevel.OUT_OF_SCOPE
    assert decision.experiment_id is None


def test_out_of_scope_decision_never_depends_on_session_state():
    """classify_scope(message) and classify_scope(message, active_experiment=X)
    must agree on scope level for a message with no evidence of its own,
    whatever X is -- the level is a property of the message."""
    for message in ("what is the best gpu for gaming", "who won the cricket match"):
        baseline = classify_scope(message).level
        for active in ("exp02", "exp03", "exp07", "exp08"):
            assert classify_scope(message, active_experiment=active).level == baseline


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------


def test_conflict_always_escalates_regardless_of_evidence_quality():
    decision = classify_scope("which basis set for methane in exp 7")
    conflicted = EvidenceSummary(
        official_count=5, top_official_score=0.99, conflict=True
    )
    assert resolve_status(decision, conflicted) is AnswerStatus.NEEDS_HUMAN_REVIEW


def test_weak_evidence_does_not_count_as_support():
    """A passage that merely mentions the experiment number is not
    evidence for a claim about it."""
    decision = classify_scope("how do i get the final energy in exp 7")
    weak = EvidenceSummary(official_count=4, top_official_score=0.01)
    assert resolve_status(decision, weak) is AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT


def test_official_material_answers_an_adjacent_question_when_it_can():
    decision = classify_scope("why does DFT work physically?", active_experiment="exp07")
    assert decision.level is ScopeLevel.ADJACENT
    assert resolve_status(decision, OFFICIAL) is AnswerStatus.IN_SCOPE_SUPPORTED


def test_only_adjacent_supported_requires_the_supplementary_label():
    assert AnswerStatus.ADJACENT_SUPPORTED.requires_supplementary_label
    for status in AnswerStatus:
        if status is not AnswerStatus.ADJACENT_SUPPORTED:
            assert not status.requires_supplementary_label


def test_answering_statuses_require_a_citation():
    for status in AnswerStatus:
        assert status.requires_citation == status.answerable


def test_every_non_answering_status_has_deterministic_fallback_text():
    for status in AnswerStatus:
        if status.answerable:
            with pytest.raises(ValueError):
                fallback_text(status)
        else:
            text = fallback_text(status, experiment_label="experiment 7")
            assert text and len(text) > 40


def test_retrieval_insufficient_text_does_not_read_as_a_refusal():
    """A student who asked a good question must not be told they were
    off-topic."""
    text = fallback_text(
        AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT, experiment_label="experiment 7"
    )
    lowered = text.lower()
    assert "outside" not in lowered
    assert "fair one" in lowered or "fair" in lowered
    out_text = fallback_text(AnswerStatus.OUT_OF_SCOPE).lower()
    assert "outside" in out_text


# ---------------------------------------------------------------------------
# Ontology honesty
# ---------------------------------------------------------------------------


def test_all_ten_experiments_are_declared():
    assert len(ontology.all_topics()) == 10
    assert {t.id for t in ontology.all_topics()} == set(ontology.ALL_EXPERIMENT_IDS)


def test_all_ten_experiments_have_manual_sourced_subject_matter():
    """The IACHY102 manual (manual/IACHY102_manual.md) now covers all ten
    experiments, so all ten are routable -- vocabulary was taken from the
    manual's actual per-experiment sections (headings, reagents, named
    formulas/instruments), never invented. This replaces the old guard
    that asserted only the four Phase-1-brief experiments were routable,
    from before the manual existed."""
    routable = {t.id for t in ontology.routable_topics()}
    assert routable == set(ontology.ALL_EXPERIMENT_IDS)


def test_unpopulated_topics_say_so_in_their_title():
    for topic in ontology.unroutable_topics():
        assert "pending" in topic.title.lower()


def test_coverage_report_shows_full_coverage():
    report = ontology.coverage_report()
    assert report["experiments_declared"] == 10
    assert report["experiments_routable"] == 10
    assert report["pending_manual_ids"] == []
    assert report["blocked_by"] is None


@pytest.mark.parametrize(
    "question",
    [
        "why use DFT instead of Hartree-Fock",
        "what is a hybrid functional",
        "why is O2 a triplet",
        "what does the multiplicity setting do in the ORCA input",
    ],
)
def test_exp07_method_choice_vocabulary_routes_to_exp07(question):
    """Conceptual method-choice questions must reach exp07's evidence
    instead of scoring no experiment at all -- previously none of DFT,
    Hartree-Fock, hybrid functional, multiplicity, or triplet were
    registered anywhere in the ontology, so these legitimate questions
    would silently fail to find exp07's manual chunk."""
    decision = classify_scope(question, active_experiment=None)
    assert decision.experiment_id == "exp07"
