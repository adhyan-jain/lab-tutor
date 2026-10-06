"""Flatten pedagogical events in stored chat metadata into research rows.

Pure: takes a message's `metadata_json` and returns spreadsheet rows. Two
event kinds are recorded by the walkthrough controller:

- `intervention`: a conceptual moment was opened (which concept, question
  type, when, whether a concept card was shown, the concept's state at that
  moment);
- `pedagogy`: a student's answer was classified (classification, misconception,
  state before/after, source, whether a model phrased the reply).

Nothing here touches the database or a model, and no student identifier beyond
what the caller passes in is added.
"""

from __future__ import annotations

from typing import Any

HEADER = [
    "Student email", "Experiment", "Class session", "Time", "Event", "Step", "When",
    "Concept", "Question", "Question type", "Classification", "Misconception",
    "State before", "State after", "Source", "Model-phrased", "Advisory classification",
    "Verdict", "Answer (final assessment only)",
]


def rows_for_message(
    email: str, experiment_id: str, class_session_id: str | None, created_at: str, meta: dict[str, Any] | None
) -> list[list[Any]]:
    wt = (meta or {}).get("walkthrough")
    if not isinstance(wt, dict):
        return []
    base = [email, experiment_id, class_session_id or "", created_at]
    rows: list[list[Any]] = []
    iv = wt.get("intervention")
    if isinstance(iv, dict):
        rows.append(
            base + [
                "intervention", iv.get("step_id", ""), iv.get("when", ""), iv.get("concept_id", ""),
                iv.get("question_id", ""), iv.get("question_type", ""), "", "",
                iv.get("concept_state", ""), "", "deterministic", False, "", "", "",
            ]
        )
    ped = wt.get("pedagogy")
    if isinstance(ped, dict):
        rows.append(
            base + [
                "answer", wt.get("step_id", ""), ped.get("when", ""), ped.get("concept_id", ""),
                ped.get("question_id", ""), ped.get("question_type", ""),
                ped.get("classification", ""), ped.get("misconception_id") or "",
                ped.get("state_before", ""), ped.get("state_after", ""), ped.get("source", ""),
                bool(ped.get("realised")), ped.get("advisory") or "", wt.get("verdict", ""),
                ped.get("answer", "") if ped.get("when") == "final" else "",
            ]
        )
    return rows
