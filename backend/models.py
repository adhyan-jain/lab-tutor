"""SQLAlchemy ORM models.

Storage is continuous: messages, submissions and Socratic attempts are
written as they happen and tagged with (student, classroom, class_session,
experiment). A `ClassSession` is the unit of "one lab meeting" -- it is
created when faculty/admin starts a class and closed when they end it.
Historical activity points at the session it happened in, not merely at
the classroom's current experiment, so a repeated experiment across two
different sessions produces independent records.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    """Platform identity. Derived server-side from the verified OAuth email
    (admin allowlist checked first, then domain) -- never trusted from the
    `User.role` column, a cookie, or any request body. See
    backend/auth/roles.py.
    """

    STUDENT = "student"
    FACULTY = "faculty"
    ADMIN = "admin"


class ClassroomRole(str, enum.Enum):
    """Classroom membership role. Distinct from platform Role: ADMIN is a
    platform identity, not something a classroom membership row can hold --
    admin authority is global and does not require joining a classroom.
    """

    STUDENT = "student"
    FACULTY = "faculty"


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    ENDED = "ended"


class ActorType(str, enum.Enum):
    """Tags who actually produced a piece of activity, independent of which
    route/table it landed in. Lets summaries/analytics exclude faculty and
    admin test/demo activity from real student participation data, and lets
    a diagnostic dashboard tell a demonstrator's test submission apart from
    a real student's. Server-set from the authenticated principal's
    platform role at write time -- never client-supplied.
    """

    STUDENT = "student"
    FACULTY_TEST = "faculty_test"
    ADMIN_TEST = "admin_test"


class ChatMessageKind(str, enum.Enum):
    SOCRATIC = "socratic"
    QA = "qa"
    DIAGNOSTIC = "diagnostic"



class DiagnosisStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    ESCALATED = "escalated"
    INVALID = "invalid"  # extraction/validation rejected the submission


class RemedialAction(str, enum.Enum):
    NONE = "none"
    FIX_IN_PLACE = "fix_in_place"
    REDO_STEP = "redo_step"
    RESTART = "restart"
    AWAIT_REVIEW = "await_review"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    # Student registration number. Optional for everyone -- never blocks
    # onboarding (see `onboarded` below and backend/api/auth_routes.py).
    # Not unique: formats vary and duplicates are tolerated (product
    # decision).
    reg_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # True once the user has been through the one-time onboarding form
    # (name confirm/edit + optional reg_no for students). Deliberately
    # NOT derived from "is name non-empty" -- Google's OAuth identity
    # always supplies a name (falling back to the email prefix if none),
    # so that would never be false and onboarding would never show.
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    # Persisted for display/audit only. Authorisation ALWAYS re-derives the
    # role from the verified email (admin allowlist, then domain) on the
    # request -- never from here.
    role: Mapped[Role] = mapped_column(Enum(Role), index=True)
    # Admin-set override of the domain-derived role (see
    # backend/api/admin_routes.py). NULL means "no override -- derive from
    # email as usual". When set, current_user() uses this value directly
    # instead of calling role_for_email(), every request -- same
    # never-trust-a-stale-value guarantee, just sourced from a DB column an
    # admin explicitly set instead of purely the email domain.
    role_override: Mapped[Role | None] = mapped_column(Enum(Role), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Classroom(Base):
    """A persistent classroom for one lab section, spanning the semester.

    Membership (who's a student/faculty here) lives in
    `ClassroomMembership`, not on this row -- a classroom has no single
    "owner"; any number of faculty are peers. The classroom's "current
    experiment" is whatever its currently-ACTIVE `ClassSession` says, not a
    field on this row -- see `ClassSession`.
    """

    __tablename__ = "classrooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    # Two independent high-entropy codes (see classrooms/service.py). Never
    # exposed to the role that doesn't own them (faculty_join_code is never
    # returned on a student-reachable response).
    student_join_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    faculty_join_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    join_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ClassroomMembership(Base):
    """Who participates in a classroom, and how.

    Replaces the old student-only `Enrollment` table and the old
    single-owner `Classroom.owner_id` column. Any number of FACULTY rows
    may exist for one classroom -- all are peers with equal operational
    authority. ADMIN is never a membership role: admin authority is
    platform-wide and does not require joining.
    """

    __tablename__ = "classroom_memberships"
    __table_args__ = (
        UniqueConstraint("classroom_id", "user_id", "role", name="uq_membership"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[ClassroomRole] = mapped_column(Enum(ClassroomRole), index=True)
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClassSession(Base):
    """One lab meeting: an experiment snapshotted and made active for a
    classroom, from start to end.

    At most one ACTIVE session may exist per classroom -- enforced at the
    DB layer by a genuine partial unique index (`status = 'active'`),
    which both Postgres and SQLite support, so the guarantee holds in the
    test harness too, not only in production. The application-level
    check-then-insert in `classrooms/service.py::start_session` is a fast
    path/friendly-error layer on top of this; the index is what actually
    prevents two concurrent starts from both succeeding. Every route that
    used to trust `Classroom.active_experiment_id` now resolves the
    classroom's current ACTIVE session instead, and rejects if none is
    active or if the request names a session that has since ended -- this
    is what makes a stale browser tab's request fail after faculty ends
    class.
    """

    __tablename__ = "class_sessions"
    __table_args__ = (
        Index("ix_class_sessions_active_lookup", "classroom_id", "status"),
        # SQLAlchemy's generic Enum type stores the member's .name (here,
        # "ACTIVE"), not its .value ("active") -- verified against the
        # actual stored row rather than assumed. The predicate must match
        # that or the index silently never applies to any row.
        Index(
            "uq_one_active_session_per_classroom",
            "classroom_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    ended_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    # Nullable only for rows backfilled before ClassSession existed. Every
    # new submission is written with this set from server-resolved session
    # state -- never client input for a real student submission (faculty/
    # admin test submissions may pass an explicit override; see
    # api/diagnostic_routes.py).
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    # Copied from the session's experiment at submit time.
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType), default=ActorType.STUDENT, index=True
    )
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    reported_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    diagnosis: Mapped["Diagnosis | None"] = relationship(back_populates="submission")


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id"), unique=True, index=True
    )
    # Denormalised so student-scoped queries need no join.
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )

    status: Mapped[DiagnosisStatus] = mapped_column(Enum(DiagnosisStatus), index=True)
    # 1, 2 or 3 -- which tier produced this outcome. 3 means "abstained".
    tier: Mapped[int] = mapped_column(Integer, index=True)
    signature_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[RemedialAction] = mapped_column(
        Enum(RemedialAction), default=RemedialAction.NONE
    )
    # Natural-language rendering. Produced by the LLM phrasing layer from
    # the already-determined diagnosis above, or by a deterministic
    # fallback template when inference is unavailable.
    phrased_text: Mapped[str] = mapped_column(Text, default="")
    phrasing_source: Mapped[str] = mapped_column(String(32), default="template")
    # True only for experiments whose plugin is explicitly low-confidence
    # (the LLM-assisted qualitative ordering check -- see ARCHITECTURE.md).
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    submission: Mapped[Submission] = relationship(back_populates="diagnosis")


class SocraticSession(Base):
    __tablename__ = "socratic_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType), default=ActorType.STUDENT, index=True
    )
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    # The student's own accumulated readings, built up step by step. Tier 1
    # verifies each step against this; it is the only data the final reveal
    # is computed from.
    student_data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Set by server-side step verification only. The answer gate consults
    # this -- and nothing else -- to decide whether a reveal may happen.
    all_steps_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class SocraticAttempt(Base):
    __tablename__ = "socratic_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("socratic_sessions.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    submitted_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    # 0 = no hint needed; 1..3 = position on the adaptive hint ladder.
    hint_level: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatThread(Base):
    """A user's chat thread for a classroom and experiment."""

    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ChatMessage(Base):
    """Continuous transcript storage. Written as messages happen.

    `kind` distinguishes Socratic in-step chat (`session_id` set, tied to
    one SocraticSession) from normal Q&A (`session_id` null -- a Q&A
    conversation is not tied to a Socratic step machine). Both kinds always
    carry `class_session_id` so summaries and history can query one
    class meeting's transcript without caring which kind produced it.
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_threads.id"), nullable=True, index=True
    )
    kind: Mapped[ChatMessageKind] = mapped_column(
        Enum(ChatMessageKind), default=ChatMessageKind.SOCRATIC, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("socratic_sessions.id"), nullable=True, index=True
    )
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType), default=ActorType.STUDENT, index=True
    )
    author: Mapped[str] = mapped_column(String(16))  # "student" | "tutor"
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)



class SummaryJob(Base):
    __tablename__ = "summary_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    experiment_id: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentSummary(Base):
    """Professor-visible only. Never returned on any student-facing route.

    Identity is (student, class_session) -- not (student, classroom,
    experiment) -- so a repeated experiment across two different sessions
    produces independent summaries instead of colliding.
    """

    __tablename__ = "student_summaries"
    __table_args__ = (
        UniqueConstraint("student_id", "class_session_id", name="uq_summary_session"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    # A flagged transcript is still surfaced to the professor, never
    # silently dropped from the batch.
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("summary_jobs.id"), nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExperimentMarks(Base):
    """Faculty/admin-entered pre- and post-test scores for one student's
    attempt at one experiment, for the pilot's before/after evaluation
    (does Socratic-mode use measurably improve outcomes?). Entirely
    separate from Tier 1 diagnosis -- these are exam marks a human
    enters by hand, never computed or judged by this system.

    Keyed by (student, classroom, experiment) rather than class_session:
    a repeat/make-up session for the same experiment updates the same
    pre/post pair instead of creating a second ungraded row, since the
    unit of analysis for the paper is "this student's gain on this
    experiment," not "this particular lab meeting."
    """

    __tablename__ = "experiment_marks"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "classroom_id", "experiment_id", name="uq_experiment_marks"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(String(64), index=True)
    pre_test_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    pre_test_max: Mapped[float] = mapped_column(Float, default=20.0)
    post_test_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_test_max: Mapped[float] = mapped_column(Float, default=20.0)
    entered_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    diagnosis_id: Mapped[str] = mapped_column(ForeignKey("diagnoses.id"), index=True)
    classroom_id: Mapped[str] = mapped_column(ForeignKey("classrooms.id"), index=True)
    class_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """Queryable from the professor/TA/admin dashboard.

    Every diagnosis, every Tier 3 escalation and every auth failure lands
    here with a timestamp and (where known) a user id. Never logs secrets
    or raw join codes -- only event identifiers and non-sensitive detail.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    classroom_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    class_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class IdempotencyRecord(Base):
    """Server-side single-fire enforcement for state-changing endpoints.

    Client-side button disabling cannot survive a network retry or a
    second browser tab, so every costly action also claims a key here.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("user_id", "scope", "key", name="uq_idempotency"),
        Index("ix_idem_lookup", "user_id", "scope", "key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36))
    scope: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="in_flight")  # in_flight|done
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
