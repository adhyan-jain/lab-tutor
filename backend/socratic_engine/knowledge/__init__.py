from .types import (  # noqa: F401
    QUESTION_TYPES,
    Concept,
    ConceptQuestion,
    ExperimentKnowledge,
    Misconception,
    Stage,
    StepKnowledge,
    build,
)

_REGISTRY: dict[str, ExperimentKnowledge] = {}


def get_knowledge(experiment_id: str) -> ExperimentKnowledge | None:
    """Knowledge model for an experiment, or None if none is authored yet."""
    if not _REGISTRY:
        from .exp02 import KNOWLEDGE as EXP02
        from .exp03 import KNOWLEDGE as EXP03
        from .exp04 import KNOWLEDGE as EXP04
        from .exp07 import KNOWLEDGE as EXP07

        for knowledge in (EXP02, EXP03, EXP04, EXP07):
            _REGISTRY[knowledge.experiment_id] = knowledge
    return _REGISTRY.get(experiment_id)
