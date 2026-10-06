"""Concept state + deterministic pedagogical policy (no model involved)."""

import ast
from pathlib import Path

import pytest

from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.pedagogy import policy, state as st

K = get_knowledge("exp07")


def Q(qid):
    return K.question_by_id[qid]


# ---------------------------------------------------------------- classify


def test_cosmetic_optimisation_is_a_misconception():
    c = policy.classify_answer(Q("q_opt_why"), "Geometry optimization makes the molecule look nicer.", K, step_id="r1_run")
    assert (c.label, c.misconception_id) == ("MISCONCEPTION", "opt_is_cosmetic")


def test_negated_misconception_is_not_flagged():
    c = policy.classify_answer(
        Q("q_opt_why"), "It is not just to make it look nicer; it lowers the energy of the geometry.", K, step_id="r1_run")
    assert c.label != "MISCONCEPTION"


def test_homo_most_electrons_is_a_misconception():
    c = policy.classify_answer(Q("q_homo_meaning"), "HOMO is the orbital with the most electrons", K, step_id="p5_homo_lumo")
    assert c.misconception_id == "homo_most_electrons"


def test_basis_set_different_molecule_is_a_misconception():
    c = policy.classify_answer(Q("q_method_why"), "different basis sets are different molecules", K, step_id="t1_set")
    assert c.misconception_id == "basis_is_new_molecule"


def test_correct_partial_unclear():
    full = "It lowers the energy so the geometry is at its minimum before the orbital calculation, which makes it more accurate"
    assert policy.classify_answer(Q("q_opt_why"), full, K).label == "CORRECT"
    assert policy.classify_answer(Q("q_opt_why"), "Energy.", K).label == "PARTIAL"
    c = policy.classify_answer(Q("q_opt_why"), "idk", K)
    assert c.label == "UNCLEAR" and c.dont_know


# ---------------------------------------------------------------- state


def test_state_progression_and_audit_trail():
    s = st.ConceptStates()
    s.tick()
    st.apply_classification(s, "geometry_optimization", "MISCONCEPTION", question_id="q_opt_why",
                            misconception_id="opt_is_cosmetic")
    assert s.get("geometry_optimization").state == "ATTEMPTED"
    st.apply_classification(s, "geometry_optimization", "PARTIAL", question_id="q_opt_why")
    assert s.get("geometry_optimization").state == "PARTIALLY_UNDERSTOOD"
    st.apply_classification(s, "geometry_optimization", "CORRECT", question_id="q_opt_observe")
    rec = s.get("geometry_optimization")
    assert rec.state == "UNDERSTOOD"
    assert [h["to"] for h in rec.history] == ["ATTEMPTED", "PARTIALLY_UNDERSTOOD", "UNDERSTOOD"]
    assert all(h["source"] == "deterministic" for h in rec.history)


def test_mastered_only_via_understood():
    s = st.ConceptStates()
    st.mark_mastered(s, "homo")
    assert s.get("homo").state == "UNKNOWN"
    st.apply_classification(s, "homo", "CORRECT")
    st.mark_mastered(s, "homo")
    assert s.get("homo").state == "MASTERED"


def test_partial_never_regresses_understanding():
    s = st.ConceptStates()
    st.apply_classification(s, "homo", "CORRECT")
    st.apply_classification(s, "homo", "PARTIAL")
    assert s.get("homo").state == "UNDERSTOOD"


def test_advisory_is_clamped():
    s = st.ConceptStates()
    st.apply_advisory(s, "homo", "CORRECT")
    assert s.get("homo").state == "ATTEMPTED"  # one level up at most
    st.apply_advisory(s, "homo", "CORRECT")
    st.apply_advisory(s, "homo", "CORRECT")
    st.apply_advisory(s, "homo", "CORRECT")
    rec = s.get("homo")
    assert rec.state == "PARTIALLY_UNDERSTOOD"  # ceiling
    assert all(h["source"] == "llm_advisory" for h in rec.history)


def test_advisory_never_lowers_or_ignores_unclear():
    s = st.ConceptStates()
    st.apply_classification(s, "homo", "CORRECT")
    st.apply_advisory(s, "homo", "MISCONCEPTION")
    st.apply_advisory(s, "homo", "UNCLEAR")
    assert s.get("homo").state == "UNDERSTOOD"


def test_roundtrip_serialisation():
    s = st.ConceptStates()
    s.tick()
    st.apply_classification(s, "homo", "PARTIAL", question_id="q_homo_meaning", question_type="INTERPRETATION")
    again = st.ConceptStates.from_dict(s.to_dict())
    assert again.to_dict() == s.to_dict()
    assert st.ConceptStates.from_dict(None).seq == 0


# ---------------------------------------------------------------- policy


def test_procedural_step_never_intervenes():
    s = st.ConceptStates()
    assert policy.decide(K, "b1_open", s).action == "none"
    assert policy.decide(K, "p2_single_point", s).action == "none"


def test_checkpoint_raises_card_for_unknown_core_concept():
    s = st.ConceptStates()
    d = policy.decide(K, "r1_run", s)
    assert d.action == "card_question" and d.concept_id == "geometry_optimization"
    assert d.question.qtype == "PREDICTION"


def test_blocked_suppresses_intervention():
    assert policy.decide(K, "r1_run", st.ConceptStates(), blocked=True).action == "none"


def test_understood_concept_is_not_raised_again():
    s = st.ConceptStates()
    for cid in ("geometry_optimization", "molecular_energy"):
        st.apply_classification(s, cid, "CORRECT")
    assert policy.decide(K, "r1_run", s).action == "none"
    assert policy.decide(K, "r3_energies", s).action == "none"


def test_cooldown_counts_turns_not_time():
    s = st.ConceptStates()
    s.tick()
    st.apply_classification(s, "geometry_optimization", "PARTIAL", question_id="q_opt_predict")
    assert policy.decide(K, "r1_run", s).concept_id != "geometry_optimization"
    for _ in range(policy.CONCEPT_COOLDOWN_TURNS):
        s.tick()
    assert policy.decide(K, "r1_run", s).concept_id == "geometry_optimization"


def test_question_type_follows_state_and_never_repeats():
    s = st.ConceptStates()
    rec = s.get("geometry_optimization")
    q1 = policy.choose_question(K, "r1_run", "geometry_optimization", rec)
    assert q1.qtype == "PREDICTION"
    st.apply_classification(s, "geometry_optimization", "UNCLEAR", question_id=q1.id, question_type=q1.qtype)
    q2 = policy.choose_question(K, "r1_run", "geometry_optimization", rec)
    assert q2.id != q1.id and q2.qtype == "WHY"


def test_mastered_concept_gets_transfer_question():
    s = st.ConceptStates()
    st.apply_classification(s, "geometry_optimization", "CORRECT")
    st.mark_mastered(s, "geometry_optimization")
    q = policy.choose_question(K, "r1_run", "geometry_optimization", s.get("geometry_optimization"))
    assert q.qtype == "TRANSFER"


def test_followups_scaffold_probe_then_explain():
    s = st.ConceptStates()
    q = Q("q_opt_why")
    mis = policy.Classification("MISCONCEPTION", "opt_is_cosmetic")
    rec = st.apply_classification(s, "geometry_optimization", "MISCONCEPTION", question_id=q.id,
                                  misconception_id="opt_is_cosmetic")
    f = policy.next_after_answer(K, q, mis, rec)
    assert f.kind == "probe" and "quantity" in f.text
    rec = st.apply_classification(s, "geometry_optimization", "MISCONCEPTION", question_id=q.id,
                                  misconception_id="opt_is_cosmetic")
    assert policy.next_after_answer(K, q, mis, rec).kind == "explain"
    assert policy.next_after_answer(K, q, policy.Classification("CORRECT"), rec).kind == "advance"


# ---------------------------------------------------------------- hard rule


@pytest.mark.parametrize("module", ["state.py", "policy.py"])
def test_pedagogy_imports_no_llm_code(module):
    src = (Path(__file__).parents[1] / "socratic_engine" / "pedagogy" / module).read_text(encoding="utf-8")
    banned = ("llm", "openai", "retrieval", "rag", "anthropic", "vertex")
    for node in ast.walk(ast.parse(src)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for n in names:
            assert not any(part in banned for part in n.split(".")), n


# ------------------------------------------------- authored keys stay honest

from backend.tests.concept_answers import GOOD  # noqa: E402


def test_every_question_has_a_model_answer_that_classifies_correct():
    assert set(GOOD) == set(K.question_by_id)
    for qid, answer in GOOD.items():
        c = policy.classify_answer(K.question_by_id[qid], answer, K)
        assert c.label == "CORRECT", (qid, c)


def test_concept_with_only_interpretation_questions_is_still_raised():
    s = st.ConceptStates()
    q = policy.choose_question(K, "p5_homo_lumo", "homo", s.get("homo"), policy.POST_STEP_TYPES)
    assert q is not None and q.id == "q_homo_meaning"
    # but never as a pre-step prediction, and never a TRANSFER question early
    assert policy.choose_question(K, "p5_homo_lumo", "homo", s.get("homo"), policy.PRE_STEP_TYPES) is None
    assert policy.choose_question(K, "r1_run", "geometry_optimization", s.get("geometry_optimization"),
                                  frozenset({"TRANSFER"})) is None


def test_homo_most_electrons_is_caught_even_without_the_word_homo():
    for answer in ("the orbital with the most electrons", "it is the one that has the highest number of electrons"):
        c = policy.classify_answer(Q("q_homo_meaning"), answer, K, step_id="")
        assert c.misconception_id == "homo_most_electrons", answer
    # and a correct answer is not mistaken for it
    ok = policy.classify_answer(Q("q_homo_meaning"), "highest occupied molecular orbital, by energy", K)
    assert ok.misconception_id is None
