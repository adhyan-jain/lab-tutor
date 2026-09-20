"""FastAPI dependencies for authentication and role gating.

The rule these implement: **every role-gated endpoint re-checks the
caller's role, server-side, on that specific request.** Not at login, not
from a cookie claim, not from anything the client sent. `current_user`
loads the user row and re-derives the role from the verified email
against the environment's domain lists every single time.

That costs one indexed lookup per request and removes a whole class of
bug -- a role that was correct at login but should not be now, a cookie
edited by hand, a client that decided it was faculty.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import audit
from backend.auth import session as session_cookie
from backend.auth.roles import DomainNotPermitted, role_for_email
from backend.data_access import FacultyScope, StudentScope
from backend.db import get_session
from backend.models import LoginSession, Role, User

# Throttle for the `LoginSession.last_seen_at` heartbeat below -- writing on
# every request would double the write load of every authenticated
# endpoint for no research benefit; a per-minute resolution is more than
# enough to tell a real timeout apart from an explicit logout.
_HEARTBEAT_MIN_INTERVAL_SECONDS = 60

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, with a freshly re-derived role."""

    id: str
    email: str
    name: str
    role: Role

    @property
    def is_faculty(self) -> bool:
        return self.role is Role.FACULTY

    @property
    def is_student(self) -> bool:
        return self.role is Role.STUDENT

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


async def current_user(
    request: Request, db: AsyncSession = Depends(get_session)
) -> Principal:
    data = session_cookie.read(request.cookies.get(session_cookie.COOKIE_NAME))
    if not data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in"
        )

    user = (
        await db.scalars(select(User).where(User.id == data["uid"]))
    ).first()
    if user is None:
        await audit.record(
            db, audit.AUTH_FAILURE,
            detail={"reason": "session_user_missing", "uid": data["uid"]},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid"
        )

    # Re-derive, every request. `user.role` (plain column) is display
    # metadata only and never trusted. `user.role_override`, if an admin
    # has set one, IS trusted -- it's a deliberate server-side grant, re-
    # read from the DB on every request just like the domain-derived path,
    # so it carries the same never-trust-a-stale-value guarantee.
    if user.role_override is not None:
        await _touch_login_session(db, user.id)
        return Principal(id=user.id, email=user.email, name=user.name, role=user.role_override)

    try:
        role = role_for_email(user.email)
    except DomainNotPermitted:
        await audit.record(
            db, audit.AUTH_FAILURE,
            user_id=user.id,
            detail={"reason": "domain_no_longer_permitted", "email": user.email},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account's email domain is not permitted",
        ) from None

    await _touch_login_session(db, user.id)
    return Principal(id=user.id, email=user.email, name=user.name, role=role)


async def _touch_login_session(db: AsyncSession, user_id: str) -> None:
    """Bump the open `LoginSession.last_seen_at`, throttled -- see the
    module-level comment on `_HEARTBEAT_MIN_INTERVAL_SECONDS`."""
    open_session = (
        await db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user_id, LoginSession.logout_at.is_(None))
            .order_by(LoginSession.login_at.desc())
        )
    ).first()
    if open_session is None:
        return
    now = dt.datetime.now(dt.timezone.utc)
    last_seen = open_session.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=dt.timezone.utc)
    if (now - last_seen).total_seconds() >= _HEARTBEAT_MIN_INTERVAL_SECONDS:
        open_session.last_seen_at = now
        await db.commit()


async def attribute_login_session_to_classroom(
    db: AsyncSession, user_id: str, classroom_id: str
) -> None:
    """First-write-wins attribution of the open login session to a
    classroom, so a staff sign-in shows up against the class they actually
    used, without ever moving an already-attributed session to a second
    one in the same login."""
    open_session = (
        await db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user_id, LoginSession.logout_at.is_(None))
            .order_by(LoginSession.login_at.desc())
        )
    ).first()
    if open_session is not None and open_session.classroom_id is None:
        open_session.classroom_id = classroom_id
        await db.commit()


async def require_student(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    if not principal.is_student:
        await audit.record(
            db, audit.AUTH_FAILURE,
            user_id=principal.id,
            detail={"reason": "student_role_required", "actual": principal.role.value},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Students only"
        )
    return principal


async def require_faculty(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    if not principal.is_faculty:
        await audit.record(
            db, audit.AUTH_FAILURE,
            user_id=principal.id,
            detail={"reason": "faculty_role_required", "actual": principal.role.value},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Staff only"
        )
    return principal


async def require_admin(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    if not principal.is_admin:
        await audit.record(
            db, audit.AUTH_FAILURE,
            user_id=principal.id,
            detail={"reason": "admin_role_required", "actual": principal.role.value},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin only"
        )
    return principal


async def require_faculty_or_admin(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    if not (principal.is_faculty or principal.is_admin):
        await audit.record(
            db, audit.AUTH_FAILURE,
            user_id=principal.id,
            detail={"reason": "faculty_or_admin_role_required", "actual": principal.role.value},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Staff or admin only"
        )
    return principal


async def require_student_or_staff(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    """Any authenticated platform role. Used by routes (Socratic/diagnostic
    test access) where faculty and admin may act as a *test* user alongside
    real students -- the caller distinguishes them via `principal.role`,
    server-derived, and stamps `actor_type` accordingly. Never a substitute
    for classroom-membership scoping.
    """
    return principal


async def student_scope(
    principal: Principal = Depends(require_student),
    db: AsyncSession = Depends(get_session),
) -> StudentScope:
    """The only sanctioned way to read student data on a student route."""
    return StudentScope(db, principal.id)


async def faculty_scope(
    principal: Principal = Depends(require_faculty),
    db: AsyncSession = Depends(get_session),
) -> FacultyScope:
    return FacultyScope(db, principal.id)


async def faculty_or_admin_scope(
    principal: Principal = Depends(require_faculty_or_admin),
    db: AsyncSession = Depends(get_session),
) -> FacultyScope:
    """Same query-scoping object faculty use. For ADMIN, scope is bypassed
    at the route layer (admin sees all classrooms) -- callers must check
    `principal.is_admin` before relying on this scope's ownership filter.
    """
    return FacultyScope(db, principal.id)


async def require_faculty_or_admin_or_co_faculty(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    """Same 403-for-wrong-role / 404-for-wrong-classroom split every other
    route in this codebase makes, extended for classroom-scoped co-faculty:
    a plain student with zero faculty capability anywhere gets 403 here
    (matches existing tests' expectations), while a student promoted to
    co-faculty in *some* classroom passes this gate and then gets a
    classroom-specific 404 from `_classroom_or_404` if the resource they
    asked for belongs to a classroom they aren't promoted in.
    """
    if principal.is_faculty or principal.is_admin:
        return principal
    from backend.classrooms.service import has_any_faculty_membership

    if await has_any_faculty_membership(db, principal.id):
        return principal
    await audit.record(
        db, audit.AUTH_FAILURE,
        user_id=principal.id,
        detail={"reason": "faculty_or_admin_role_required", "actual": principal.role.value},
        commit=True,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Staff only"
    )


async def classroom_faculty_scope(
    principal: Principal = Depends(require_faculty_or_admin_or_co_faculty),
    db: AsyncSession = Depends(get_session),
) -> FacultyScope:
    """Like `faculty_or_admin_scope`, but also admits a student promoted to
    classroom-scoped co-faculty somewhere (see `require_faculty_or_admin_
    or_co_faculty`). `FacultyScope`'s own membership predicate
    (`ClassroomMembership(role=FACULTY, active)`) then naturally scopes
    each query/route to only the classroom(s) they're actually faculty in.
    """
    return FacultyScope(db, principal.id)
