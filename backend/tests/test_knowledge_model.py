"""Structural checks on the experiment knowledge model."""

from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.walkthrough.exp07_script import SCRIPT


def test_exp07_knowledge_is_consistent():
    k = get_knowledge("exp07")
    assert k is not None
    assert k.validate(known_step_ids=set(SCRIPT.by_id)) == []


def test_unknown_experiment_has_no_knowledge():
    assert get_knowledge("exp99") is None


def test_required_concepts_present():
    k = get_knowledge("exp07")
    for cid in ("molecular_geometry", "atomic_orbitals", "molecular_orbitals", "hybridization",
                "geometry_optimization", "molecular_energy", "electronic_structure", "homo",
                "lumo", "dft", "functional", "basis_set", "orbital_contribution",
                "optimized_geometry", "single_point", "method_comparison"):
        assert cid in k.concept_by_id


def test_every_question_type_is_authored():
    k = get_knowledge("exp07")
    assert {q.qtype for q in k.questions} == {
        "PREDICTION", "WHY", "CONSEQUENCE", "OBSERVATION", "INTERPRETATION", "TRANSFER"}


def test_no_reference_numbers_leak_into_authored_text():
    # The walkthrough withholds HOMO/LUMO reference values; so must this model.
    import re
    k = get_knowledge("exp07")
    text = " ".join(
        [c.description for c in k.concepts]
        + [s.why + s.expected_observation + s.possible_consequence for s in k.steps]
        + [q.ask + q.expected_reasoning + q.scaffold for q in k.questions]
    )
    assert not re.search(r"-?\d+\.\d+\s*(eV|Eh|hartree)", text, re.I)
