"""`/api/auth/me` tells the UI whether to offer Settings and Platform admin.

Presentation only -- every staff route still re-checks access on the server --
but a promoted co-faculty student must get Settings, and a plain student must not.
"""

from __future__ import annotations

import pytest

from backend.auth import session as session_cookie

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


async def _caps(client, token):
    resp = await client.get("/api/auth/me", headers=auth(token))
    assert resp.status_code == 200
    return resp.json()["capabilities"]


async def test_a_plain_student_has_no_settings(client, make_user):
    _, token = await make_user("plain.student@vitstudent.ac.in")
    assert await _caps(client, token) == {"settings": False, "admin": False}


async def test_faculty_get_settings_but_not_platform_admin(client, make_user):
    _, token = await make_user("some.prof@vit.ac.in")
    assert await _caps(client, token) == {"settings": True, "admin": False}


async def test_admin_gets_both(client, make_user):
    _, token = await make_user("adhyanjain2006@gmail.com")
    assert await _caps(client, token) == {"settings": True, "admin": True}


async def test_a_student_promoted_to_co_faculty_gets_settings(client, make_user):
    _, prof = await make_user("owner.prof@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "Sec"}, headers=auth(prof))
    cid, code = created.json()["id"], created.json()["student_join_code"]
    student, token = await make_user("future.cofaculty@vitstudent.ac.in")
    await client.post("/api/classrooms/join", json={"join_code": code}, headers=auth(token))
    assert (await _caps(client, token))["settings"] is False

    promoted = await client.post(
        f"/api/classrooms/{cid}/promote", json={"student_user_id": student.id}, headers=auth(prof)
    )
    assert promoted.status_code == 201
    assert await _caps(client, token) == {"settings": True, "admin": False}


async def test_complete_profile_also_returns_capabilities(client, make_user):
    _, token = await make_user("onboarding.prof@vit.ac.in")
    resp = await client.post(
        "/api/auth/complete-profile", json={"name": "Dr Onboard", "reg_no": None}, headers=auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["settings"] is True
