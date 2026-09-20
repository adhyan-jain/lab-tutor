"""Scoped data access -- the single place student/faculty isolation is
enforced.

The rule this module exists to make structural: **a student's data is
never fetched and then filtered in application code.** The owner
predicate is welded onto the SELECT before it reaches the database, so
a forgotten `if row.student_id != me` check cannot leak anything.

Endpoints serving student data must go through `StudentScope`. They must
not build their own `select(Submission)`; the tests in
`tests/test_data_isolation.py` cover the boundary.

Faculty access is scoped the same way, one level out: a faculty member
reaches student rows only through classrooms they hold an active
`ClassroomMembership(role=FACULTY)` row for -- never through ownership of
a single classroom column, since any number of faculty are peers on one
classroom. ADMIN is a platform role, not a classroom membership, and is
never routed through `FacultyScope`: admin routes query directly and
enforce nothing but `require_admin`, by design (admin has global
authority and does not need to join a classroom).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    ActorType,
    Base,
    ChatMessage,
    Classroom,
    ClassroomMembership,
    ClassroomRole,
    ClassSession,
    Diagnosis,
    Escalation,
    SocraticAttempt,
    SocraticSession,
    StudentSummary,
    Submission,
)

T = TypeVar("T", bound=Base)

#: Models that hold per-student data. Every one carries a `student_id`
#: column, which is what makes the scoping below uniform.
STUDENT_OWNED_MODELS: tuple[type[Base], ...] = (
    Submission,
    Diagnosis,
    SocraticSession,
    SocraticAttempt,
    ChatMessage,
    StudentSummary,
    Escalation,
)


class ScopeViolation(RuntimeError):
    """Raised when a query is built against a model this scope cannot own."""


@dataclass
class PromptCount:
    """One (student, experiment, class session, message kind) row's
    student-authored chat-message count. See `FacultyScope.prompt_counts`."""

    student_id: str
    experiment_id: str
    class_session_id: str | None
    kind: str
    count: int


class StudentScope:
    """Every query built here is filtered to one student id.

    Construct it from the authenticated session only -- never from a
    user id supplied in a path, query string or request body.
    """

    def __init__(self, session: AsyncSession, student_id: str) -> None:
        if not student_id:
            raise ScopeViolation("StudentScope requires a concrete student id")
        self._session = session
        self._student_id = student_id

    @property
    def student_id(self) -> str:
        return self._student_id

    def select(self, model: type[T]) -> Select[tuple[T]]:
        """A SELECT already constrained to this student.

        Raises for any model that has no `student_id` column rather than
        silently returning an unscoped query.
        """
        if model not in STUDENT_OWNED_MODELS:
            raise ScopeViolation(
                f"{model.__name__} is not student-owned; it cannot be fetched "
                "through StudentScope. Use an explicitly reviewed query."
            )
        return select(model).where(model.student_id == self._student_id)  # type: ignore[attr-defined]

    async def all(self, model: type[T], *criteria: Any) -> list[T]:
        stmt = self.select(model)
        for c in criteria:
            stmt = stmt.where(c)
        return list((await self._session.scalars(stmt)).all())

    async def get(self, model: type[T], obj_id: str) -> T | None:
        """Fetch one row by id **and** owner.

        A direct object reference to another student's row returns None
        here -- the row is not fetched at all, so there is nothing for a
        later check to forget.
        """
        stmt = self.select(model).where(model.id == obj_id)  # type: ignore[attr-defined]
        return (await self._session.scalars(stmt)).first()

    async def count(self, model: type[T], *criteria: Any) -> int:
        stmt = select(func.count()).select_from(model).where(
            model.student_id == self._student_id  # type: ignore[attr-defined]
        )
        for c in criteria:
            stmt = stmt.where(c)
        return int((await self._session.scalar(stmt)) or 0)

    async def is_enrolled(self, classroom_id: str) -> bool:
        stmt = select(func.count()).select_from(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.user_id == self._student_id,
            ClassroomMembership.role == ClassroomRole.STUDENT,
            ClassroomMembership.active.is_(True),
        )
        return int((await self._session.scalar(stmt)) or 0) > 0

    async def active_classroom_ids(self) -> list[str]:
        stmt = select(ClassroomMembership.classroom_id).where(
            ClassroomMembership.user_id == self._student_id,
            ClassroomMembership.role == ClassroomRole.STUDENT,
            ClassroomMembership.active.is_(True),
        )
        return list((await self._session.scalars(stmt)).all())


class FacultyScope:
    """Scopes faculty reads to classrooms the faculty member is an active
    member of.

    A faculty member is not granted blanket access to every student row;
    the membership predicate (`ClassroomMembership(role=FACULTY, active)`)
    is applied in the same query that selects the student data. Any
    number of faculty rows may exist for one classroom -- all are peers.
    """

    def __init__(self, session: AsyncSession, faculty_id: str) -> None:
        if not faculty_id:
            raise ScopeViolation("FacultyScope requires a concrete faculty id")
        self._session = session
        self._faculty_id = faculty_id

    @property
    def faculty_id(self) -> str:
        return self._faculty_id

    def _member_classroom_ids(self) -> Select[tuple[str]]:
        return select(ClassroomMembership.classroom_id).where(
            ClassroomMembership.user_id == self._faculty_id,
            ClassroomMembership.role == ClassroomRole.FACULTY,
            ClassroomMembership.active.is_(True),
        )

    def select_classrooms(self, *, include_archived: bool = False) -> Select[tuple[Classroom]]:
        stmt = select(Classroom).where(Classroom.id.in_(self._member_classroom_ids()))
        if not include_archived:
            stmt = stmt.where(Classroom.archived_at.is_(None))
        return stmt

    async def get_classroom(self, classroom_id: str) -> Classroom | None:
        # By id, an archived class is still reachable: its reports and
        # exports must stay readable after it disappears from the lists.
        stmt = self.select_classrooms(include_archived=True).where(Classroom.id == classroom_id)
        return (await self._session.scalars(stmt)).first()

    async def is_member(self, classroom_id: str) -> bool:
        return await self.get_classroom(classroom_id) is not None

    # Backwards-compatible alias used by earlier single-owner code paths.
    owns_classroom = is_member

    def select(self, model: type[T]) -> Select[tuple[T]]:
        """A SELECT constrained to classrooms this faculty member belongs to."""
        if not hasattr(model, "classroom_id"):
            raise ScopeViolation(
                f"{model.__name__} has no classroom_id; it cannot be scoped to faculty."
            )
        return select(model).where(
            model.classroom_id.in_(self._member_classroom_ids())  # type: ignore[attr-defined]
        )

    async def all(self, model: type[T], *criteria: Any) -> list[T]:
        stmt = self.select(model)
        for c in criteria:
            stmt = stmt.where(c)
        return list((await self._session.scalars(stmt)).all())

    async def get(self, model: type[T], obj_id: str) -> T | None:
        stmt = self.select(model).where(model.id == obj_id)  # type: ignore[attr-defined]
        return (await self._session.scalars(stmt)).first()

    async def active_session(self, classroom_id: str) -> ClassSession | None:
        """The classroom's currently-ACTIVE ClassSession, or None.

        Only meaningful for a classroom this faculty member belongs to --
        callers must check `is_member`/`get_classroom` first.
        """
        from backend.models import SessionStatus

        stmt = select(ClassSession).where(
            ClassSession.classroom_id == classroom_id,
            ClassSession.status == SessionStatus.ACTIVE,
        )
        return (await self._session.scalars(stmt)).first()

    async def faculty_roster(self, classroom_id: str) -> list[ClassroomMembership]:
        """Empty list for a classroom this faculty member does not belong to."""
        if not await self.is_member(classroom_id):
            return []
        stmt = select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.role == ClassroomRole.FACULTY,
            ClassroomMembership.active.is_(True),
        )
        return list((await self._session.scalars(stmt)).all())

    async def purge_summaries(self, class_session_id: str, student_ids: list[str]):
        """Used only by an explicit faculty-requested summary refresh."""
        if not student_ids:
            return
        await self._session.execute(
            delete(StudentSummary).where(
                StudentSummary.class_session_id == class_session_id,
                StudentSummary.student_id.in_(student_ids),
            )
        )

    async def prompt_counts(
        self,
        classroom_id: str,
        actor_types: tuple[ActorType, ...] = (ActorType.STUDENT,),
    ) -> list[PromptCount]:
        """Chat-message volume per student/experiment/class-session/kind.

        For research-paper "how many prompts did each student send"
        reporting. By default counts only genuine student-authored turns
        (`ActorType.STUDENT`, `author == "student"`) -- excludes faculty/
        admin test traffic and the tutor's own replies, same predicate
        `backend/summaries/coverage.py`'s `qa_messages` count uses. A
        caller that wants staff usage too (the Activity page) passes
        `actor_types` explicitly; research aggregates never do.

        Takes a bare `classroom_id`, not filtered through `self.select` --
        same trust boundary as `marks_routes.py`'s `_all_marks_by_experiment`
        and `dashboard_routes.py`'s per-classroom queries: the caller
        (`_classroom_or_404`) has already resolved that this account may
        see this classroom, including the admin case this scope's own
        membership predicate would otherwise incorrectly exclude.
        """
        stmt = (
            select(
                ChatMessage.student_id,
                ChatMessage.experiment_id,
                ChatMessage.class_session_id,
                ChatMessage.kind,
                func.count().label("count"),
            )
            .where(
                ChatMessage.classroom_id == classroom_id,
                ChatMessage.actor_type.in_(actor_types),
                ChatMessage.author == "student",
            )
            .group_by(
                ChatMessage.student_id,
                ChatMessage.experiment_id,
                ChatMessage.class_session_id,
                ChatMessage.kind,
            )
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            PromptCount(
                student_id=row.student_id,
                experiment_id=row.experiment_id,
                class_session_id=row.class_session_id,
                kind=row.kind.value,
                count=row.count,
            )
            for row in rows
        ]
