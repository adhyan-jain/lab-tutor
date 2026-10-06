from .types import (  # noqa: F401
    QUESTION_TYPES,
    Concept,
    ConceptQuestion,
    ExperimentKnowledge,
    Misconception,
    StepKnowledge,
    build,
)

_REGISTRY: dict[str, ExperimentKnowledge] = {}


def get_knowledge(experiment_id: str) -> ExperimentKnowledge | None:
    """Knowledge model for an experiment, or None if none is authored yet."""
    if not _REGISTRY:
        from .exp07 import KNOWLEDGE as EXP07

        _REGISTRY[EXP07.experiment_id] = EXP07
    return _REGISTRY.get(experiment_id)
