"""What a student can ask: starter questions and learning modes per experiment.

Served with the experiment catalogue (GET /api/classrooms/experiments), so the
chat UI needs no extra request. Only advertises what the backend supports:
the guided key-ideas session (which is also what "Test my understanding"
starts) exists only where the phone-only Exp7 walkthrough runs.
"""

from __future__ import annotations

from backend.config import get_settings
from backend.socratic_engine.knowledge import get_knowledge

#: For an experiment with no authored starters. Both are ordinary in-scope
#: questions answered from that experiment's own material.
GENERIC_STARTERS = (
    "Explain the key concepts in this experiment",
    "What is the aim of this experiment?",
)

GUIDED_LEARNING = "Guide me through the key ideas"
CHECK_UNDERSTANDING = "Test my understanding"


def starter_questions(experiment_id: str) -> list[str]:
    knowledge = get_knowledge(experiment_id)
    if knowledge is not None and knowledge.starter_questions:
        return list(knowledge.starter_questions)
    return list(GENERIC_STARTERS)


def guided_learning_available(experiment_id: str) -> bool:
    settings = get_settings()
    return (
        get_knowledge(experiment_id) is not None
        and settings.phone_only
        and settings.walkthrough_enabled
    )
