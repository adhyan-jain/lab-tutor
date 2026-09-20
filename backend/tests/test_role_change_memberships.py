"""Setting a user's platform role to student must make them a student everywhere.

Regression: a faculty-domain user who held a faculty membership kept it after
an admin set their role to student, so they were missing from the student
roster and their prompts were tagged faculty-test traffic, and therefore
absent from prompt counts and every other student metric.
"""

from __future__ import annotations

import pytest

from backend.auth import session as session_cookie

pytestmark = pytest.mark.asyncio

ADMIN_EMAIL = "adhyanjain2006@gmail.com"  # the default admin allowlist


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


@pytest.fixture
def llm(fake_llm, monkeypatch):
    fake_llm.reply = "HOMO is the highest occupied molecular orbital."
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    return fake_llm


async def _class_with_faculty_member(client, make_user):
    """A class run by one professor, plus a second @vit.ac.in user who joined
    with the FACULTY code (so holds a faculty membership)."""
    _, prof = await make_user("prof.owner@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "Sec A"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": "exp07"},
        headers=auth(prof),
    )
    assert started.status_code == 201
    member, member_token = await make_user("jag.member@vit.ac.in", "Jag Member")
    joined = await client.post(
        "/api/classrooms/join",
        json={"join_code": created.json()["faculty_join_code"]},
        headers=auth(member_token),
    )
    assert joined.status_code == 200
    return prof, classroom_id, created.json(), member, member_token


async def _set_role(client, admin_token, user_id, role):
    return await client.patch(
        f"/api/admin/users/{user_id}/role", json={"role": role}, headers=auth(admin_token)
    )


async def test_setting_student_moves_the_users_faculty_membership_to_student(client, make_user):
    prof, cid, _, member, _ = await _class_with_faculty_member(client, make_user)
    _, admin = await make_user(ADMIN_EMAIL, "Admin")

    resp = await _set_role(client, admin, member.id, "student")
    assert resp.status_code == 200
    assert resp.json()["moved_to_student_in"] == [cid]

    students = await client.get(f"/api/classrooms/{cid}/roster", headers=auth(prof))
    assert "jag.member@vit.ac.in" in [s["email"] for s in students.json()["students"]]
    faculty = await client.get(f"/api/classrooms/{cid}/faculty", headers=auth(prof))
    assert "jag.member@vit.ac.in" not in [f["email"] for f in faculty.json()["faculty"]]


async def test_prompts_after_the_change_count_as_student_prompts(client, make_user, llm):
    prof, cid, _, member, member_token = await _class_with_faculty_member(client, make_user)
    _, admin = await make_user(ADMIN_EMAIL, "Admin")
    await _set_role(client, admin, member.id, "student")

    sent = await client.post(
        "/api/chat/messages",
        json={"classroom_id": cid, "experiment_id": "exp07", "message": "What is HOMO?"},
        headers=auth(member_token),
    )
    assert sent.status_code == 200, sent.text

    activity = await client.get(f"/api/dashboard/classrooms/{cid}/activity", headers=auth(prof))
    assert activity.status_code == 200
    row = next(s for s in activity.json()["students"] if s["email"] == "jag.member@vit.ac.in")
    assert row["prompts_total"] == 1


async def test_before_the_change_the_same_prompt_is_faculty_test_traffic(client, make_user, llm):
    """Documents why the change matters: as faculty their prompts are excluded."""
    prof, cid, _, member, member_token = await _class_with_faculty_member(client, make_user)
    await client.post(
        "/api/chat/messages",
        json={"classroom_id": cid, "experiment_id": "exp07", "message": "What is HOMO?"},
        headers=auth(member_token),
    )
    activity = await client.get(f"/api/dashboard/classrooms/{cid}/activity", headers=auth(prof))
    assert activity.json()["totals"]["prompts"] == 0


async def test_setting_student_on_a_user_with_no_faculty_membership_changes_nothing_else(
    client, make_user
):
    _, cid, _, _, _ = await _class_with_faculty_member(client, make_user)
    plain, _ = await make_user("plain.user@vit.ac.in", "Plain")
    _, admin = await make_user(ADMIN_EMAIL, "Admin")
    resp = await _set_role(client, admin, plain.id, "student")
    assert resp.status_code == 200 and resp.json()["moved_to_student_in"] == []


async def test_setting_faculty_does_not_touch_memberships(client, make_user):
    _, cid, _, member, _ = await _class_with_faculty_member(client, make_user)
    _, admin = await make_user(ADMIN_EMAIL, "Admin")
    resp = await _set_role(client, admin, member.id, "faculty")
    assert resp.status_code == 200 and resp.json()["moved_to_student_in"] == []


async def test_an_overridden_faculty_domain_user_can_join_with_a_student_code(client, make_user):
    prof, cid, created, _, _ = await _class_with_faculty_member(client, make_user)
    other, other_token = await make_user("other.override@vit.ac.in", "Other")
    _, admin = await make_user(ADMIN_EMAIL, "Admin")

    before = await client.post(
        "/api/classrooms/join", json={"join_code": created["student_join_code"]}, headers=auth(other_token)
    )
    assert before.status_code == 403  # still a faculty-domain account

    await _set_role(client, admin, other.id, "student")
    after = await client.post(
        "/api/classrooms/join", json={"join_code": created["student_join_code"]}, headers=auth(other_token)
    )
    assert after.status_code == 200


async def test_the_role_change_and_each_move_are_audited(client, make_user, db):
    from sqlalchemy import select

    from backend.models import AuditLog

    _, cid, _, member, _ = await _class_with_faculty_member(client, make_user)
    _, admin = await make_user(ADMIN_EMAIL, "Admin")
    await _set_role(client, admin, member.id, "student")
    events = set((await db.scalars(select(AuditLog.event))).all())
    assert {"admin.role_changed", "classroom.faculty_demoted"} <= events
