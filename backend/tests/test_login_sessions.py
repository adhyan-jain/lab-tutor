"""LoginSession lifecycle: created on login, closed on explicit logout,
left open (inferred timeout) otherwise. See CLAUDE.md's testing
philosophy -- these are behavioural assertions against the real routes,
not invented expected values.
"""

from __future__ import annotations

from sqlalchemy import select

import pytest

from backend.auth import session as session_cookie
from backend.models import LoginSession

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


async def test_logout_closes_the_open_login_session(client, make_user, db):
    user, token = await make_user("student.logout@vitstudent.ac.in", "Student Logout")
    # `make_user` issues a cookie directly and does not go through
    # `/api/auth/callback`, so it does not create a LoginSession either --
    # simulate the row `callback()` would have written on real sign-in.
    db.add(LoginSession(user_id=user.id))
    await db.commit()

    resp = await client.post("/api/auth/logout", headers=auth(token))
    assert resp.status_code == 200

    row = (
        await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
    ).first()
    assert row.logout_at is not None
    assert row.end_reason == "logout"


async def test_logout_with_no_open_session_still_clears_the_cookie(client, make_user):
    """A user with no LoginSession row at all (e.g. this session's own
    `make_user` fixture) must not get a 500 -- logout degrades to just
    clearing the cookie."""
    _user, token = await make_user("student.no-session@vitstudent.ac.in", "No Session")
    resp = await client.post("/api/auth/logout", headers=auth(token))
    assert resp.status_code == 200


async def test_heartbeat_updates_last_seen_at_on_an_open_session(client, make_user, db):
    import datetime as dt

    user, token = await make_user("student.heartbeat@vitstudent.ac.in", "Student Heartbeat")
    stale = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    db.add(LoginSession(user_id=user.id, login_at=stale, last_seen_at=stale))
    await db.commit()

    resp = await client.get("/api/auth/me", headers=auth(token))
    assert resp.status_code == 200

    row = (
        await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
    ).first()
    last_seen = row.last_seen_at.replace(tzinfo=dt.timezone.utc)
    assert last_seen > stale
    assert row.logout_at is None
