"""Phone-only gate: every student-facing question is answerable with only a
phone and this page. No Gabedit, ORCA, Avogadro, screen, output file or
software step may be required or implied."""

from __future__ import annotations

import pytest

from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.knowledge.phone_safe import external_dependency, is_phone_safe, why_not_phone_safe
from backend.socratic_engine.knowledge.types import PHONE_SOURCES, ConceptQuestion
from backend.socratic_engine.walkthrough import controller as ctl
from backend.tests.concept_answers import GOOD

K = get_knowledge("exp07")


def q(ask: str, source: str = "CONCEPTUAL_REASONING") -> ConceptQuestion:
    return ConceptQuestion(id="t", concept_id="homo", qtype="WHY", ask=ask, source=source)


# TEST A / B / C -- accepted: theory, conceptual why, transfer
@pytest.mark.parametrize(
    "ask,source",
    [
        ("What is the molecular formula of methane?", "THEORY"),
        ("Methane is CH4. How many atoms are present in one molecule?", "THEORY"),
        ("Why does methane adopt a tetrahedral geometry?", "CONCEPTUAL_REASONING"),
        ("Why is geometry optimization useful?", "CONCEPTUAL_REASONING"),
        ("What does HOMO represent?", "THEORY"),
        ("Why can two computational methods give slightly different results?", "CONCEPTUAL_REASONING"),
        ("What is the purpose of a basis set?", "THEORY"),
        ("Would the same reason for geometry optimization apply to a different molecule? Why?", "CONCEPTUAL_REASONING"),
        ("How might your reasoning change for a different molecule?", "CONCEPTUAL_REASONING"),
    ],
)
def test_theory_reasoning_and_transfer_questions_are_accepted(ask, source):
    assert is_phone_safe(q(ask, source)), why_not_phone_safe(q(ask, source))


# TEST D / E / F / G -- rejected: screen, Gabedit, ORCA output, Avogadro
@pytest.mark.parametrize(
    "ask",
    [
        "Look at your screen and count the atoms.",
        "Before we move on, one fact from your screen, please. Count the atoms now in the drawing area, carbon and hydrogens together. How many?",
        "What do you see in Gabedit?",
        "Look at the structure in Gabedit.",
        "Check the ORCA output and tell me the energy.",
        "Look at the ORCA output and find the final energy.",
        "Open Avogadro and inspect the HOMO.",
        "Open the HOMO visualization. What do the colored lobes show?",
        "Run the calculation and tell me what you observe.",
        "Click the molecule and see what changes.",
        "Compare your optimized and unoptimized structures. What changed?",
        "Read the energy from the output.",
        "Check your terminal.",
        "Tell me what appears on your screen.",
        "Select methane and tell me what happens.",
        "Run the second basis-set calculation and tell me how the orbital energy changed.",
        "Looking across your runs, what pattern do you notice?",
        "What did you see on your laptop?",
    ],
)
def test_questions_that_need_external_software_or_a_screen_are_rejected(ask):
    assert external_dependency(ask) is not None
    assert not is_phone_safe(q(ask))


# TEST H -- information LabTutor itself provides, then asks the student to interpret it
def test_a_question_that_states_its_own_information_is_accepted():
    question = q(
        "Suppose the calculated C-H bond length changes from 1.10 angstrom to 1.09 angstrom after optimization. What changed?",
        "GIVEN_DATA_INTERPRETATION",
    )
    assert is_phone_safe(question), why_not_phone_safe(question)


def test_external_source_metadata_blocks_a_question_even_with_clean_wording():
    for source in ("EXTERNAL_OBSERVATION", "PROCEDURAL_EXTERNAL_ACTION"):
        assert not is_phone_safe(q("What pattern do you notice?", source))
    assert PHONE_SOURCES == {"THEORY", "CONCEPTUAL_REASONING", "GIVEN_DATA_INTERPRETATION"}


# The authored content itself
def test_every_question_in_the_phone_only_flows_is_safe():
    in_flows = {qid for stage in K.stages for qid in stage.questions} | set(K.assessment)
    unsafe = {qid: why_not_phone_safe(K.question_by_id[qid]) for qid in in_flows if not is_phone_safe(K.question_by_id[qid])}
    assert unsafe == {}


def test_the_only_unsafe_question_is_the_one_that_needs_the_students_own_results():
    unsafe = {x.id for x in K.questions if not is_phone_safe(x)}
    assert unsafe == {"q_pattern_interpret"}
    assert K.question_by_id["q_pattern_interpret"].source == "EXTERNAL_OBSERVATION"


def test_all_other_student_facing_authored_text_is_clean():
    texts = []
    texts += [c.description for c in K.concepts]
    texts += [t for m in K.misconceptions for t in (m.probe, m.correction)]
    texts += [t for s in K.stages for t in (s.title, s.context)]
    assert [(t, external_dependency(t)) for t in texts if external_dependency(t)] == []


# TEST I -- a whole session using only the website
def _run_phone_session(answer_for):
    state = ctl.new_state("stu", mode="concept")
    msgs = [ctl.start(state).reply]
    asked = []
    for _ in range(80):
        if state.status == "done":
            break
        if state.phase == "concept":
            qid = state.concept["question_id"]
        elif state.phase == "assess":
            qid = state.assess["queue"][state.assess["i"]]
        else:  # pragma: no cover - the session never idles
            raise AssertionError(state.phase)
        asked.append(qid)
        msgs.append(ctl.take_turn(state, answer_for(qid)).reply)
    return state, msgs, asked


def test_i_a_complete_session_never_needs_anything_outside_the_page():
    state, msgs, asked = _run_phone_session(lambda qid: GOOD[qid])
    assert state.status == "done" and len(asked) >= 15
    assert [(i, external_dependency(m)) for i, m in enumerate(msgs) if external_dependency(m)] == []
    assert all(is_phone_safe(K.question_by_id[qid]) for qid in asked)
    assert "q_pattern_interpret" not in asked  # the software-only question is never asked


def test_i_even_a_struggling_session_never_needs_anything_outside_the_page():
    state, msgs, _ = _run_phone_session(lambda qid: "hmm not sure what that means")
    assert state.status == "done"
    assert [(i, external_dependency(m)) for i, m in enumerate(msgs) if external_dependency(m)] == []


def test_i_a_misconception_filled_session_stays_phone_safe():
    wrong = "geometry optimization just makes the molecule look nicer and HOMO is the orbital with the most electrons"
    state, msgs, _ = _run_phone_session(lambda qid: wrong)
    assert state.status == "done"
    assert [m for m in msgs if external_dependency(m)] == []


def test_no_software_step_title_or_numbered_step_card_ever_appears_in_phone_mode():
    from backend.socratic_engine.walkthrough.exp07_script import SCRIPT

    _, msgs, _ = _run_phone_session(lambda qid: GOOD[qid])
    joined = "\n".join(msgs)
    assert "of 27" not in joined and "Step 1 of" not in joined
    for step in SCRIPT.steps:
        assert f"**{step.title}**" not in joined
