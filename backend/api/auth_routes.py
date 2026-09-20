"""OAuth sign-in/out routes."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

import datetime as dt

from backend import audit
from backend import classrooms as classroom_service
from backend.auth import Principal, current_user
from backend.auth import oauth, session as session_cookie
from backend.auth.roles import DomainNotPermitted
from backend.config import get_settings
from backend.db import get_session
from backend.models import LoginSession, Role, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _me_payload(user: User, principal: Principal, *, staff_membership: bool = False) -> dict:
    # `user.name`/`user.reg_no`, not `principal.name` -- the Principal is
    # built once when the `current_user` dependency resolves, before this
    # request's own handler (e.g. complete_profile) may have just mutated
    # the row; re-reading straight from `user` here always reflects the
    # write this same request just made.
    return {
        "id": principal.id,
        "email": principal.email,
        "name": user.name,
        "role": principal.role.value,
        "reg_no": user.reg_no,
        # A student is not onboarded until they have a registration number,
        # including students who signed up back when it was optional.
        "profile_complete": bool(user.onboarded)
        and (principal.role != Role.STUDENT or bool(user.reg_no)),
        # What the UI may offer. Presentation only: every staff route still
        # re-checks access on the server. `settings` covers platform faculty,
        # admin, and a student promoted to co-faculty in some class.
        "capabilities": {
            "settings": principal.role in (Role.FACULTY, Role.ADMIN) or staff_membership,
            "admin": principal.role == Role.ADMIN,
        },
    }


_REG_NO_RE = re.compile(r"^[A-Za-z0-9]{5,20}$")


@router.get("/login")
async def login() -> RedirectResponse:
    try:
        url, state = oauth.build_authorize_url()
    except oauth.OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    settings = get_settings()
    response.set_cookie(
        session_cookie.OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=oauth.STATE_MAX_AGE_SECONDS,
        path="/",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_session),
):
    """Server-side domain verification happens here, before any session."""
    expected = request.cookies.get(session_cookie.OAUTH_STATE_COOKIE, "")
    if not oauth.verify_state(state, expected):
        await audit.record(
            db, audit.AUTH_FAILURE, detail={"reason": "bad_oauth_state"}, commit=True
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sign-in state"
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorisation code"
        )

    try:
        identity = await oauth.exchange_code(code)
    except oauth.OAuthError as exc:
        await audit.record(
            db, audit.AUTH_FAILURE, detail={"reason": "exchange_failed", "error": str(exc)},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Sign-in with Google failed"
        ) from exc

    # The email comes from Google's response, never from the client.
    try:
        role = oauth.role_or_reject(identity)
    except DomainNotPermitted:
        await audit.record(
            db,
            audit.AUTH_FAILURE,
            detail={
                "reason": "domain_rejected",
                "email": identity.email,
                "email_verified": identity.email_verified,
            },
            commit=True,
        )
        log.warning("Rejected sign-in from disallowed domain: %s", identity.email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This service is limited to institutional accounts.",
        ) from None

    user = (
        await db.scalars(select(User).where(User.google_sub == identity.subject))
    ).first()
    if user is None:
        user = User(
            google_sub=identity.subject,
            email=identity.email,
            name=identity.name,
            role=role,
        )
        db.add(user)
    else:
        user.email = identity.email
        # `name` is user-editable via POST /api/auth/complete-profile once
        # set -- don't clobber it with Google's profile name on every
        # subsequent login, only backfill it if still empty.
        if not user.name:
            user.name = identity.name
        user.role = role
    await db.flush()

    await audit.record(
        db, audit.AUTH_SUCCESS, user_id=user.id, detail={"role": role.value}
    )
    db.add(LoginSession(user_id=user.id))
    await db.commit()

    settings = get_settings()
    response = RedirectResponse(
        f"{settings.public_url.rstrip('/')}/", status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(
        session_cookie.COOKIE_NAME,
        session_cookie.issue(user.id, user.email),
        **session_cookie.cookie_kwargs(),
    )
    response.delete_cookie(session_cookie.OAUTH_STATE_COOKIE, path="/")
    return response


@router.post("/logout")
async def logout(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    open_session = (
        await db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == principal.id, LoginSession.logout_at.is_(None))
            .order_by(LoginSession.login_at.desc())
        )
    ).first()
    if open_session is not None:
        open_session.logout_at = dt.datetime.now(dt.timezone.utc)
        open_session.end_reason = "logout"
        await db.commit()

    response = JSONResponse({"ok": True})
    response.delete_cookie(session_cookie.COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    user = (await db.scalars(select(User).where(User.id == principal.id))).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")
    return _me_payload(
        user, principal, staff_membership=await classroom_service.has_any_faculty_membership(db, user.id)
    )


class CompleteProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    reg_no: str | None = Field(default=None, max_length=64)


@router.post("/complete-profile")
async def complete_profile(
    body: CompleteProfileRequest,
    principal: Principal = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Lets a signed-in user set/edit their display name and (for students)
    registration number. Not restricted to first-use only -- also how a
    user corrects a typo later."""
    user = (await db.scalars(select(User).where(User.id == principal.id))).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")
    reg_no = (body.reg_no or "").strip().upper()
    if principal.role == Role.STUDENT:
        if not reg_no:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Your registration number is required.",
            )
        if not _REG_NO_RE.match(reg_no):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Enter your registration number using letters and digits only (e.g. 21BCE1234).",
            )
        user.reg_no = reg_no
    else:
        user.reg_no = reg_no or None
    user.name = body.name.strip()
    user.onboarded = True
    await audit.record(db, audit.PROFILE_COMPLETED, user_id=user.id, detail={"role": principal.role.value})
    await db.commit()
    return _me_payload(
        user, principal, staff_membership=await classroom_service.has_any_faculty_membership(db, user.id)
    )
