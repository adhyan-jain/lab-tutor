"""The structured shape a router decision must take.

Nothing here decides anything by itself -- see `backend/router/router.py`'s
module docstring for the authority boundary. This module only defines what
counts as a *well-formed* decision; `route_message` is what decides
whether to trust one at all.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field, field_validator


class RouterMode(str, enum.Enum):
    QA = "qa"
    SOCRATIC = "socratic"
    DIAGNOSTIC = "diagnostic"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"


class RouterDecision(BaseModel):
    """One routing decision for one chat turn.

    `retrieval_query` is the one field with a side effect beyond routing:
    when set, it is what gets searched/classified instead of the
    student's raw message, so a contextual follow-up ("why?") can be
    expanded using conversation history into something the retrieval
    index can actually match. It never changes what the student is shown
    to have asked (that stays `body.message`, untouched), and it never
    supplies new facts -- only a better restatement of the same question.
    """

    mode: RouterMode
    experiment_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_retrieval: bool = True
    retrieval_query: str | None = None
    rationale: str = ""

    @field_validator("needs_retrieval")
    @classmethod
    def _clarification_never_retrieves(cls, v: bool, info) -> bool:
        if info.data.get("mode") == RouterMode.CLARIFICATION:
            return False
        return v
