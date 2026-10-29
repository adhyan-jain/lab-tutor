"""The MCQ follow-up questions authored from the course MCQ documents.

Each question is graded by the same deterministic matcher the tutor uses
(`pedagogy.policy.classify_answer`): the correct option, typed several ways,
must be CORRECT, and no wrong option may be. The correct letters come from the
answer keys in the MCQ documents (questions 1-20 of each).
"""

from __future__ import annotations

import pytest

from backend.socratic_engine.knowledge import get_knowledge
from backend.socratic_engine.knowledge.phone_safe import is_phone_safe, why_not_phone_safe
from backend.socratic_engine.pedagogy.policy import classify_answer

# MCQ_Kinetics_Ethyl_Acetate_Hydrolysis.docx, answer key for questions 1-20.
EXP02_KEY = {1: "b", 2: "a", 3: "b", 4: "b", 5: "b", 6: "b", 7: "b", 8: "b", 9: "b", 10: "b", 11: "b", 12: "b", 13: "c", 14: "a", 15: "a", 16: "b", 17: "b", 18: "c", 19: "a", 20: "c"}

# MCQ_Colorimetric_Estimation_Ni2plus.docx, answer key for questions 1-20.
EXP03_KEY = {1: "b", 2: "c", 3: "a", 4: "b", 5: "b", 6: "c", 7: "b", 8: "b", 9: "c", 10: "b", 11: "b", 12: "b", 13: "b", 14: "b", 15: "b", 16: "c", 17: "b", 18: "a", 19: "b", 20: "b"}

CASES = [("exp02", "q2_mcq", n, EXP02_KEY[n]) for n in EXP02_KEY] + [
    ("exp03", "q3_mcq", n, EXP03_KEY[n]) for n in EXP03_KEY
]


def _ids(case):
    return f"{case[0]}-q{case[2]}"


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_the_correct_option_passes_in_any_natural_form(case):
    exp, prefix, n, right = case
    knowledge = get_knowledge(exp)
    if knowledge is None:
        pytest.skip(f"{exp} has no authored knowledge module yet")
    q = knowledge.question_by_id[f"{prefix}{n}"]
    for form in (right, right.upper(), f"({right})", f"option {right}", f"{right})", f"answer {right}"):
        assert classify_answer(q, form, knowledge).label == "CORRECT", (q.id, form)


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_no_wrong_option_passes(case):
    exp, prefix, n, right = case
    knowledge = get_knowledge(exp)
    if knowledge is None:
        pytest.skip(f"{exp} has no authored knowledge module yet")
    q = knowledge.question_by_id[f"{prefix}{n}"]
    for wrong in set("abcd") - {right}:
        for form in (wrong, f"({wrong})", f"option {wrong}"):
            assert classify_answer(q, form, knowledge).label != "CORRECT", (q.id, form)


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_the_question_lists_every_option_and_is_phone_safe(case):
    exp, prefix, n, _ = case
    knowledge = get_knowledge(exp)
    if knowledge is None:
        pytest.skip(f"{exp} has no authored knowledge module yet")
    q = knowledge.question_by_id[f"{prefix}{n}"]
    for letter in "abcd":
        assert f"\n{letter}) " in q.ask, (q.id, letter)
    assert is_phone_safe(q), why_not_phone_safe(q)


def test_exp02_questions_are_reachable_from_a_stage():
    knowledge = get_knowledge("exp02")
    staged = {qid for s in knowledge.stages for qid in s.questions}
    missing = [f"q2_mcq{n}" for n in EXP02_KEY if f"q2_mcq{n}" not in staged]
    assert not missing, missing
