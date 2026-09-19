"""Classroom creation, joining, membership, and class-session lifecycle.

A classroom is persistent: one per lab section, created once and reused
all semester. What changes weekly is which `ClassSession` is ACTIVE for
it -- created when faculty/admin starts a class, closed when they end it.
Every submission and Socratic session is tagged from the resolved active
session, so students never type an experiment number and cannot submit
against a stale one once class has ended.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    ClassroomRole,
    ClassSession,
    Classroom,
    ClassroomMembership,
    Role,
    SessionStatus,
    User,
)
from backend.tier1_compute.experiments.registry import (
    UnknownExperimentError,
    get_plugin,
)

#: 20 base32 characters ~= 100 bits of entropy. A short code would be
#: enumerable: with ~70 students behind it, a guessable code lets an
#: outsider join a section and see its active experiment.
JOIN_CODE_BYTES = 13
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I/L/O/0/1


class ClassroomError(RuntimeError):
    pass


class JoinClosed(ClassroomError):
    pass


class WrongCodeRole(ClassroomError):
    """A student presented the faculty code, or vice versa. Never silently
    resolved to "the closest role" -- rejected outright."""


class NotEnrolled(ClassroomError):
    pass


class NotCoFacultyEligible(ClassroomError):
    """Demote target is not a classroom-promoted co-faculty (i.e. their
    platform role isn't STUDENT) -- refuse rather than touch a genuine
    faculty peer, which stays admin-only via `remove_faculty`."""


class SessionAlreadyActive(ClassroomError):
    pass


class NoActiveSession(ClassroomError):
    pass


def generate_join_code() -> str:
    """A 5-digit numeric PIN for classroom join."""
    return "".join(secrets.choice("0123456789") for _ in range(5))


@dataclass(frozen=True)
class ClassroomView:
    id: str
    name: str
    join_open: bool
    active_experiment_id: str | None
    student_count: int = 0


async def _unique_code(db: AsyncSession, column) -> str:
    for _ in range(50):
        code = generate_join_code()
        clash = (await db.scalars(select(Classroom).where(column == code))).first()
        if clash is None:
            return code
    raise ClassroomError("Could not generate a unique join code")  # pragma: no cover



async def create_classroom(
    db: AsyncSession, *, creator_id: str, name: str, creator_is_faculty: bool = True
) -> Classroom:
    """Create a classroom.

    If the creator is a faculty member, they're enrolled as its first
    faculty peer. If the creator is admin, no membership row is created --
    admin authority is global and does not require joining (brief §8).
    """
    student_code = await _unique_code(db, Classroom.student_join_code)
    faculty_code = await _unique_code(db, Classroom.faculty_join_code)

    classroom = Classroom(
        name=name.strip() or "Untitled section",
        student_join_code=student_code,
        faculty_join_code=faculty_code,
    )
    db.add(classroom)
    await db.flush()
    if creator_is_faculty:
        db.add(
            ClassroomMembership(
                classroom_id=classroom.id, user_id=creator_id, role=ClassroomRole.FACULTY
            )
        )
        await db.flush()
    return classroom


async def join_classroom(
    db: AsyncSession, *, user: User, join_code: str
) -> Classroom:
    """Join by whichever code matches, but only if it matches the caller's
    own platform role. A student code never admits faculty and vice versa
    -- there is no "closest role" fallback.
    """
    code = (join_code or "").strip().upper()

    classroom = (
        await db.scalars(
            select(Classroom).where(
                (Classroom.student_join_code == code)
                | (Classroom.faculty_join_code == code)
            )
        )
    ).first()
    if classroom is None or classroom.archived_at is not None:
        # An archived class is indistinguishable from a wrong code.
        raise ClassroomError("No classroom matches that code")

    if code == classroom.student_join_code:
        if user.role != Role.STUDENT:
            raise WrongCodeRole("This is a student join code")
        member_role = ClassroomRole.STUDENT
    else:
        if user.role != Role.FACULTY:
            raise WrongCodeRole("This is a faculty join code")
        member_role = ClassroomRole.FACULTY

    if member_role == ClassroomRole.STUDENT and not classroom.join_open:
        raise JoinClosed("Joining is closed for this classroom")

    existing = (
        await db.scalars(
            select(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom.id,
                ClassroomMembership.user_id == user.id,
                ClassroomMembership.role == member_role,
            )
        )
    ).first()
    if existing is not None:
        if not existing.active:
            existing.active = True
            existing.removed_at = None
            await db.flush()
        return classroom

    db.add(
        ClassroomMembership(classroom_id=classroom.id, user_id=user.id, role=member_role)
    )
    try:
        await db.flush()
    except IntegrityError:
        # Lost a race against a concurrent join from the same user (e.g. two
        # browser tabs each with their own idempotency key) -- the unique
        # constraint caught it; treat as already-joined, not a crash.
        await db.rollback()
        classroom = (
            await db.scalars(select(Classroom).where(Classroom.id == classroom.id))
        ).first()
    return classroom


async def regenerate_join_code(
    db: AsyncSession, classroom: Classroom, *, which: str
) -> Classroom:
    if which == "student":
        classroom.student_join_code = await _unique_code(db, Classroom.student_join_code)
    elif which == "faculty":
        classroom.faculty_join_code = await _unique_code(db, Classroom.faculty_join_code)
    else:
        raise ClassroomError("which must be 'student' or 'faculty'")
    await db.flush()
    return classroom


async def set_join_open(
    db: AsyncSession, classroom: Classroom, *, open_: bool
) -> Classroom:
    """Lock the roster once the section has joined."""
    classroom.join_open = open_
    await db.flush()
    return classroom


async def rename_classroom(db: AsyncSession, classroom: Classroom, *, name: str) -> Classroom:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ClassroomError("A classroom needs a name.")
    classroom.name = cleaned[:200]
    await db.flush()
    return classroom


async def archive_classroom(
    db: AsyncSession, classroom: Classroom, *, archived_by: str
) -> Classroom:
    """"Delete" a classroom: hide it and stop it running, keep every row.

    A live session is ended first so students cannot keep chatting into a
    class that has disappeared from the lists. Nothing else is touched --
    prompts, attempts, diagnoses, marks and summaries all stay, and the
    class is restorable.
    """
    from backend.models import _now

    if classroom.archived_at is not None:
        return classroom
    active = await get_active_session(db, classroom.id)
    if active is not None:
        await end_session(db, active, ended_by=archived_by)
    classroom.archived_at = _now()
    await db.flush()
    return classroom


async def restore_classroom(db: AsyncSession, classroom: Classroom) -> Classroom:
    classroom.archived_at = None
    await db.flush()
    return classroom


async def remove_faculty(
    db: AsyncSession, classroom_id: str, *, user_id: str
) -> None:
    stmt = select(ClassroomMembership).where(
        ClassroomMembership.classroom_id == classroom_id,
        ClassroomMembership.user_id == user_id,
        ClassroomMembership.role == ClassroomRole.FACULTY,
        ClassroomMembership.active.is_(True),
    )
    membership = (await db.scalars(stmt)).first()
    if membership is None:
        return
    from backend.models import _now

    membership.active = False
    membership.removed_at = _now()
    await db.flush()


async def _has_active_faculty_membership(
    db: AsyncSession, classroom_id: str, user_id: str
) -> bool:
    stmt = select(ClassroomMembership).where(
        ClassroomMembership.classroom_id == classroom_id,
        ClassroomMembership.user_id == user_id,
        ClassroomMembership.role == ClassroomRole.FACULTY,
        ClassroomMembership.active.is_(True),
    )
    return (await db.scalars(stmt)).first() is not None


async def has_any_faculty_membership(db: AsyncSession, user_id: str) -> bool:
    """True if the user has an active FACULTY membership in ANY classroom
    (genuine faculty peer or classroom-promoted co-faculty, anywhere) --
    used only to distinguish "a plain student with zero faculty capability"
    (403, wrong role entirely) from "co-faculty for a different classroom
    than the one requested" (404, right role wrong resource), the same
    403-vs-404 split every other route in this codebase already makes.
    """
    stmt = select(ClassroomMembership).where(
        ClassroomMembership.user_id == user_id,
        ClassroomMembership.role == ClassroomRole.FACULTY,
        ClassroomMembership.active.is_(True),
    )
    return (await db.scalars(stmt)).first() is not None


async def can_act_as_faculty(db: AsyncSession, principal, classroom_id: str) -> bool:
    """True for admin (global authority), for a genuine platform-faculty
    member of this classroom, and for a student who has been promoted to
    classroom-scoped co-faculty here -- both of the latter two are the
    exact same underlying membership row (`ClassroomMembership(role=
    FACULTY, active)`), so one check covers both. A co-faculty gets full
    faculty behaviour, but only for this one classroom_id.
    """
    if principal.is_admin:
        return True
    return await _has_active_faculty_membership(db, classroom_id, principal.id)


async def promote_student_to_class_faculty(
    db: AsyncSession, classroom_id: str, *, target_user_id: str
) -> None:
    """Classroom-scoped only: does not touch the target's platform Role.
    Converts their STUDENT membership in this classroom to FACULTY."""
    from backend.models import _now

    stmt = select(ClassroomMembership).where(
        ClassroomMembership.classroom_id == classroom_id,
        ClassroomMembership.user_id == target_user_id,
        ClassroomMembership.role == ClassroomRole.STUDENT,
        ClassroomMembership.active.is_(True),
    )
    student_membership = (await db.scalars(stmt)).first()
    if student_membership is None:
        raise NotEnrolled("User is not an active student member of this classroom")
    student_membership.active = False
    student_membership.removed_at = _now()

    existing_faculty = (
        await db.scalars(
            select(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom_id,
                ClassroomMembership.user_id == target_user_id,
                ClassroomMembership.role == ClassroomRole.FACULTY,
            )
        )
    ).first()
    if existing_faculty is not None:
        existing_faculty.active = True
        existing_faculty.removed_at = None
    else:
        db.add(
            ClassroomMembership(
                classroom_id=classroom_id, user_id=target_user_id, role=ClassroomRole.FACULTY
            )
        )
    await db.flush()


async def demote_class_faculty_to_student(
    db: AsyncSession, classroom_id: str, *, target_user_id: str
) -> None:
    """Only ever touches a promoted co-faculty (platform role STUDENT).
    A genuine platform-faculty peer can only be removed by an admin, via
    `remove_faculty` -- this function refuses to touch one."""
    from backend.auth.roles import role_for_email
    from backend.models import _now

    target = (await db.scalars(select(User).where(User.id == target_user_id))).first()
    if target is None:
        raise NotCoFacultyEligible("User not found")
    effective_role = (
        target.role_override if target.role_override is not None else role_for_email(target.email)
    )
    if effective_role != Role.STUDENT:
        raise NotCoFacultyEligible(
            "This user's platform role is not student -- demote a genuine "
            "faculty peer via admin removal instead."
        )

    stmt = select(ClassroomMembership).where(
        ClassroomMembership.classroom_id == classroom_id,
        ClassroomMembership.user_id == target_user_id,
        ClassroomMembership.role == ClassroomRole.FACULTY,
        ClassroomMembership.active.is_(True),
    )
    faculty_membership = (await db.scalars(stmt)).first()
    if faculty_membership is None:
        raise NotEnrolled("User is not an active co-faculty member of this classroom")
    faculty_membership.active = False
    faculty_membership.removed_at = _now()

    student_membership = (
        await db.scalars(
            select(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom_id,
                ClassroomMembership.user_id == target_user_id,
                ClassroomMembership.role == ClassroomRole.STUDENT,
            )
        )
    ).first()
    if student_membership is not None:
        student_membership.active = True
        student_membership.removed_at = None
    else:
        db.add(
            ClassroomMembership(
                classroom_id=classroom_id, user_id=target_user_id, role=ClassroomRole.STUDENT
            )
        )
    await db.flush()


# --- class session lifecycle ------------------------------------------------


async def get_active_session(db: AsyncSession, classroom_id: str) -> ClassSession | None:
    stmt = select(ClassSession).where(
        ClassSession.classroom_id == classroom_id,
        ClassSession.status == SessionStatus.ACTIVE,
    )
    return (await db.scalars(stmt)).first()


async def start_session(
    db: AsyncSession, classroom_id: str, *, experiment_id: str, started_by: str
) -> ClassSession:
    """Start a class. Validates the experiment, then inserts the ACTIVE
    session inside the same flush that would collide with a concurrent
    start -- two faculty pressing Start at once must not both succeed.
    """
    try:
        get_plugin(experiment_id)
    except UnknownExperimentError as exc:
        raise ClassroomError(str(exc)) from exc

    classroom = await db.get(Classroom, classroom_id)
    if classroom is not None and classroom.archived_at is not None:
        raise ClassroomError("This classroom is archived. Restore it before starting a class.")

    existing = await get_active_session(db, classroom_id)
    if existing is not None:
        raise SessionAlreadyActive(
            "A session is already active for this classroom. End it before "
            "starting a new one."
        )

    session = ClassSession(
        classroom_id=classroom_id,
        experiment_id=experiment_id,
        status=SessionStatus.ACTIVE,
        started_by=started_by,
    )
    db.add(session)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Postgres partial-unique-index race: the loser of two concurrent
        # starts lands here instead of silently creating a second ACTIVE
        # session. (SQLite, used only by the test harness, cannot express
        # a partial unique index; the check-then-insert above is this
        # code path's best-effort equivalent there -- a known test-fidelity
        # gap, not a production one.)
        await db.rollback()
        raise SessionAlreadyActive(
            "A session is already active for this classroom."
        ) from exc
    return session


async def end_session(
    db: AsyncSession, session: ClassSession, *, ended_by: str
) -> ClassSession:
    from backend.models import _now

    if session.status != SessionStatus.ACTIVE:
        raise NoActiveSession("This session is not active.")
    session.status = SessionStatus.ENDED
    session.ended_at = _now()
    session.ended_by = ended_by
    await db.flush()
    return session


async def require_active_session(db: AsyncSession, classroom_id: str) -> ClassSession:
    session = await get_active_session(db, classroom_id)
    if session is None:
        raise ClassroomError(
            "This classroom has no active class session right now. "
            "A demonstrator starts one before the session begins."
        )
    return session


async def student_count(db: AsyncSession, classroom_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(ClassroomMembership).where(
                ClassroomMembership.classroom_id == classroom_id,
                ClassroomMembership.role == ClassroomRole.STUDENT,
                ClassroomMembership.active.is_(True),
            )
        )
        or 0
    )


async def roster_with_users(
    db: AsyncSession, classroom_id: str
) -> list[tuple[ClassroomMembership, User]]:
    rows = await db.execute(
        select(ClassroomMembership, User)
        .join(User, User.id == ClassroomMembership.user_id)
        .where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.role == ClassroomRole.STUDENT,
            ClassroomMembership.active.is_(True),
        )
        .order_by(User.email)
    )
    return list(rows.all())


async def faculty_roster_with_users(
    db: AsyncSession, classroom_id: str
) -> list[tuple[ClassroomMembership, User]]:
    rows = await db.execute(
        select(ClassroomMembership, User)
        .join(User, User.id == ClassroomMembership.user_id)
        .where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.role == ClassroomRole.FACULTY,
            ClassroomMembership.active.is_(True),
        )
        .order_by(User.email)
    )
    return list(rows.all())
