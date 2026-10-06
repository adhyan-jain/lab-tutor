"""Conceptual moments inside the Exp7 walkthrough: the controller's use of
the pedagogy policy. All deterministic, no model."""

from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.walkthrough import controller as ctl
from backend.socratic_engine.walkthrough.exp07_script import SCRIPT
from backend.tests.concept_answers import GOOD
from backend.tests.test_walkthrough_controller import at_step, good_answer, run_to_end


def drive(state, until, limit=600):
    """Take good-answer turns until `until(state, result)` is true."""
    for _ in range(limit):
        last = ctl.take_turn(state, good_answer(state))
        if until(state, last):
            return last
        if state.status == "done":
            break
    raise AssertionError("condition never met")


def concept_turns(results):
    return [r for r in results if r.ui.get("kind") == "concept"]


def enter_concept(step_id="o5_check_input"):
    """Complete the step before r1_run so its prediction moment opens."""
    state = at_step(step_id)
    r = drive(state, lambda s, r: s.phase == "concept")
    return state, r


def full_run():
    state = ctl.new_state("stu")
    return state, [ctl.start(state), *run_to_end(state)]


def test_prediction_is_asked_before_the_optimisation_step():
    state, r = enter_concept()
    assert state.step_id == "r1_run" and state.concept["when"] == "pre"
    assert r.ui["question_type"] == "PREDICTION" and r.ui["concept_id"] == "geometry_optimization"
    assert "concept_card" in r.ui and "Geometry optimization" in r.reply  # core + unknown -> card
    assert "Start the optimisation" not in r.reply  # the step card waits


def test_procedural_steps_are_never_interrupted():
    _, results = full_run()
    interrupted = {r.events["step_id"] for r in concept_turns(results)}
    for sid in ("b1_open", "b2_draw", "b4_save", "o1_open_file", "o2_orca_dialog", "p2_single_point", "p3_run_sp"):
        assert sid not in interrupted


def test_correct_answer_acknowledges_and_continues_to_the_step():
    state, _ = enter_concept()
    r = ctl.take_turn(state, GOOD["q_opt_predict"])
    assert r.events["verdict"] == "concept_correct"
    assert r.events["pedagogy"]["classification"] == "CORRECT"
    assert state.phase == "step" and state.concept is None
    assert "Start the optimisation" in r.reply
    assert ctl._cs(state).get("geometry_optimization").state == "UNDERSTOOD"


def test_misconception_is_probed_not_corrected_outright():
    state, _ = enter_concept()
    r = ctl.take_turn(state, "geometry optimization makes the molecule look nicer")
    assert r.events["verdict"] == "concept_probe"
    assert r.events["pedagogy"]["misconception_id"] == "opt_is_cosmetic"
    assert "What quantity is the calculation actually trying to make smaller" in r.reply
    assert state.phase == "concept"  # still waiting on the student
    assert "lowers the calculated total energy" not in r.reply  # answer not revealed


def test_partial_answer_gets_a_scaffold_then_an_explanation_after_repeated_misses():
    state, _ = enter_concept()
    r1 = ctl.take_turn(state, "energy")
    assert r1.events["verdict"] == "concept_scaffold" and state.phase == "concept"
    assert ctl._cs(state).get("geometry_optimization").state == "PARTIALLY_UNDERSTOOD"
    r2 = ctl.take_turn(state, "energy")
    assert r2.events["verdict"] == "concept_explained"
    assert state.phase == "step"
    assert "Here is the short version" in r2.reply


def test_stuck_student_is_not_blocked_just_told_and_moved_on():
    state, _ = enter_concept()
    r = ctl.take_turn(state, "just tell me")
    assert r.events["verdict"] == "concept_explained" and state.phase == "step"


def test_skipping_is_always_allowed_and_leaves_no_understanding_evidence():
    state, _ = enter_concept()
    r = ctl.take_turn(state, "Skip this question")
    assert r.events["verdict"] == "concept_skipped" and state.phase == "step"
    assert ctl._cs(state).get("geometry_optimization").state == "INTRODUCED"
    assert "concept:geometry_optimization" in state.skipped


def test_side_question_goes_to_qa_and_returns_to_the_question():
    state, _ = enter_concept()
    r = ctl.take_turn(state, "What is ORCA and why does it need a basis set at all?")
    assert r.reply is None and r.events["verdict"] == "side_question"
    assert state.phase == "concept"
    assert "Back to my question" in r.resume_line


def test_each_question_is_asked_at_most_once_and_understood_concepts_are_not_retested():
    _, results = full_run()
    asked = [r.events["intervention"]["question_id"] for r in results if "intervention" in r.events]
    assert asked and len(asked) == len(set(asked))
    # geometry_optimization is understood after its first correct answer,
    # so neither optimisation follow-up is asked
    assert "q_opt_observe" not in asked and "q_opt_why" not in asked


def test_a_student_who_never_asks_still_meets_the_core_concepts():
    state, results = full_run()
    steps = {r.events["step_id"] for r in concept_turns(results)}
    assert {"r1_run", "p1_open_opt", "p5_homo_lumo", "t1_set"} & steps
    assert ctl._cs(state).get("geometry_optimization").state in ("UNDERSTOOD", "MASTERED")


def test_each_step_is_raised_at_most_once_even_in_the_repeated_tables_loop():
    state, results = full_run()
    keys = [
        (r.events["intervention"]["step_id"], r.events["intervention"]["when"])
        for r in results
        if "intervention" in r.events
    ]
    assert keys and len(keys) == len(set(keys)) == len(state.intervened)


def test_troubleshooting_blocks_the_moment():
    state = at_step("o5_check_input")
    state.troubleshooting = True
    assert ctl._concept_moment(state, "post", "", resume="advance") is None


def test_concept_state_and_moment_survive_a_json_round_trip():
    state, _ = enter_concept()
    again = ctl.WalkState.from_dict(state.to_dict())
    assert again.phase == "concept" and again.concept == state.concept
    assert again.concepts == state.concepts
    r = ctl.take_turn(again, GOOD["q_opt_predict"])
    assert r.events["verdict"] == "concept_correct"


def test_resume_shows_the_open_question():
    state, _ = enter_concept()
    r = ctl.show_current(state, "Here is where you are.")
    assert "A quick prediction" in r.reply and r.ui["kind"] == "concept"


def test_old_states_without_concept_fields_still_load():
    old = ctl.new_state("stu").to_dict()
    for k in ("concepts", "intervened", "concept"):
        old.pop(k)
    s = ctl.WalkState.from_dict(old)
    assert s.concepts == {} and s.intervened == [] and s.concept is None


def test_every_knowledge_step_exists_in_the_script():
    assert {s.step_id for s in get_knowledge("exp07").steps} <= set(SCRIPT.by_id)


# ------------------------------------------------------- final assessment


def at_assessment():
    """Run a good student to the point the assessment opens."""
    state = ctl.new_state("stu")
    ctl.start(state)
    for _ in range(900):
        r = ctl.take_turn(state, good_answer(state))
        if state.phase == "assess":
            return state, r
    raise AssertionError("assessment never opened")


def test_assessment_opens_after_the_last_step_and_asks_the_authored_questions():
    state, r = at_assessment()
    k = get_knowledge("exp07")
    assert state.status == "active" and state.assess["queue"] == list(k.assessment)
    assert "whole experiment" in r.reply and "Final reflection 1 of 9" in r.reply
    assert r.ui["kind"] == "assessment" and r.ui["progress"]["total"] == 9


def test_assessment_covers_concepts_and_transfer_not_procedure():
    k = get_knowledge("exp07")
    types = {k.question_by_id[q].qtype for q in k.assessment}
    assert "TRANSFER" in types
    concepts = {k.question_by_id[q].concept_id for q in k.assessment}
    assert {"geometry_optimization", "optimized_geometry", "homo", "method_comparison",
            "orbital_contribution", "electronic_structure", "molecular_orbitals"} <= concepts


def test_completing_the_assessment_finishes_the_experiment_with_a_summary():
    state, _ = at_assessment()
    last = None
    while state.status != "done":
        last = ctl.take_turn(state, good_answer(state))
    assert state.assessed and state.assess is None
    assert last.events["assessment_done"] is True
    assert "Ideas you explained well" in last.reply and "Ask me anything" in last.reply
    assert ctl.take_turn(state, "hello").reply is None  # passes through to Q&A afterwards


def test_each_assessment_answer_is_recorded_with_classification_and_the_raw_answer():
    state, _ = at_assessment()
    r = ctl.take_turn(state, good_answer(state))
    ped = r.events["pedagogy"]
    assert ped["when"] == "final" and ped["classification"] == "CORRECT" and ped["answer"]


def test_a_wrong_assessment_answer_gets_the_key_idea_and_the_next_question():
    state, _ = at_assessment()
    r = ctl.take_turn(state, "hmm the software figures it out somehow")
    assert r.events["pedagogy"]["classification"] == "UNCLEAR"
    assert "The key idea:" in r.reply and "Final reflection 2 of 9" in r.reply


def test_assessment_questions_are_skippable_and_never_block_finishing():
    state, _ = at_assessment()
    for _ in range(9):
        r = ctl.take_turn(state, "Skip this question")
    assert state.status == "done" and state.assessed
    assert len([s for s in state.skipped if s.startswith("assess:")]) == 9


def test_a_correct_transfer_answer_masters_an_understood_concept():
    state, _ = at_assessment()
    while state.status != "done":
        ctl.take_turn(state, good_answer(state))
    cs = ctl._cs(state)
    assert cs.get("geometry_optimization").state == "MASTERED"  # understood earlier, then transfer-correct


def test_assessment_is_never_asked_twice_and_survives_a_round_trip_mid_way():
    state, _ = at_assessment()
    ctl.take_turn(state, good_answer(state))
    again = ctl.WalkState.from_dict(state.to_dict())
    assert again.phase == "assess" and again.assess["i"] == 1
    r = ctl.take_turn(again, good_answer(again))
    assert "Final reflection 3 of 9" in r.reply
    again.assessed = True
    again.assess = None
    again.phase = "step"
    assert ctl._begin_assessment(again, "")[1]["kind"] == "done"


def test_side_question_during_assessment_goes_to_qa_and_returns():
    state, _ = at_assessment()
    r = ctl.take_turn(state, "Can you explain what ORCA actually computes in this calculation?")
    assert r.reply is None and "Back to the final question" in r.resume_line
    assert state.assess["i"] == 0


# ---------------------------------------------------------- research rows


def test_research_rows_capture_interventions_and_classified_answers():
    from backend.socratic_engine.pedagogy import export

    state, opening = enter_concept()
    rows = export.rows_for_message("s@x", "exp07", "cs1", "t0", {"walkthrough": opening.events})
    assert [r[4] for r in rows] == ["intervention"]
    assert rows[0][7] == "geometry_optimization" and rows[0][9] == "PREDICTION" and len(rows[0]) == len(export.HEADER)

    answered = ctl.take_turn(state, "geometry optimization makes the molecule look nicer")
    rows = export.rows_for_message("s@x", "exp07", None, "t1", {"walkthrough": answered.events})
    assert rows[0][4] == "answer" and rows[0][10] == "MISCONCEPTION" and rows[0][11] == "opt_is_cosmetic"
    assert rows[0][12] == "UNKNOWN" or rows[0][12] == "INTRODUCED"
    assert rows[0][13] == "ATTEMPTED" and rows[0][14] == "deterministic" and len(rows[0]) == len(export.HEADER)


def test_research_rows_ignore_messages_without_pedagogy_and_hide_answers_outside_final():
    from backend.socratic_engine.pedagogy import export

    assert export.rows_for_message("s", "exp07", None, "t", {"type": "qa"}) == []
    state, _ = at_assessment()
    r = ctl.take_turn(state, good_answer(state))
    final = export.rows_for_message("s", "exp07", None, "t", {"walkthrough": r.events})[0]
    assert final[-1]  # the raw answer is kept only for the final assessment
    state2, _ = enter_concept()
    mid = ctl.take_turn(state2, GOOD["q_opt_predict"])
    assert export.rows_for_message("s", "exp07", None, "t", {"walkthrough": mid.events})[0][-1] == ""


# ------------------------------------------- interpreting the student's own data


def test_pattern_question_waits_for_six_recorded_runs_and_shows_the_students_table():
    state = ctl.new_state("stu")
    ctl.start(state)
    seen = []
    for _ in range(900):
        r = ctl.take_turn(state, good_answer(state))
        iv = r.events.get("intervention")
        if iv and iv["question_id"] == "q_pattern_interpret":
            seen.append((ctl._rows_recorded(state), r.reply))
        if state.status == "done":
            break
    assert len(seen) == 1
    rows, reply = seen[0]
    assert rows >= 6
    assert "**Your results so far:**" in reply and reply.count("| methane |") == 6
    assert "| Molecule | Method | Basis | HOMO (eV) | LUMO (eV) | Gap (eV) |" in reply


def test_data_view_uses_only_the_students_own_numbers():
    state = ctl.new_state("stu")
    assert ctl._data_view(state, "q_pattern_interpret") == ""  # nothing recorded -> nothing shown
    state.facts["e_first"], state.facts["e_final"] = -40.0, -40.5
    assert "first energy -40 Eh, last energy -40.5 Eh (change -0.500000 Eh)" in ctl._data_view(state, "q_energy_lower")
    assert ctl._data_view(state, "q_homo_meaning") == ""


def test_energy_observation_shows_the_students_before_and_after_energies():
    _, results = full_run()
    energy = [r for r in results if r.events.get("intervention", {}).get("question_id") == "q_energy_lower"]
    assert energy and "**Your numbers:**" in energy[0].reply


def test_final_ch4_vs_o2_question_shows_both_molecules_numbers():
    state, _ = at_assessment()
    state.assess["i"] = state.assess["queue"].index("q_compare_ch4_o2")
    text, _ = ctl._assess_message(state)
    assert "| methane |" in text and "| oxygen |" in text.lower().replace("oxygen (o2)", "oxygen")
