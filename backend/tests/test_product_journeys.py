"""End-to-end product journeys through the CURRENT unified chat surface.

Distinct from test_e2e_journeys.py (which drives the old standalone
/api/socratic/* and /api/submissions routes directly) and
test_chat_routes.py (which tests individual chat behaviors in
isolation) -- this file ties the pieces together the way a real
session would: onboarding -> join -> multi-turn chat with Socratic
guidance and a diagnostic, multiple chats with separate history,
faculty promotion taking effect immediately, and admin global role
management.
"""

from __future__ import annotations

import pytest

from backend.auth import session as session_cookie
from backend.tests.reference_plugin import reference_plugin

pytestmark = pytest.mark.asyncio


@pytest.fixture
def registered_experiment(monkeypatch):
    from backend.tier1_compute.experiments import registry

    plugin = reference_plugin()
    monkeypatch.setitem(registry._REGISTRY, plugin.id, plugin)
    return plugin


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


async def test_full_student_product_journey(client, make_user, registered_experiment):
    # --- onboarding: first-ever login has no profile yet ---------------
    _, student = await make_user("journey.student@vitstudent.ac.in")
    me = await client.get("/api/auth/me", headers=auth(student))
    assert me.status_code == 200
    assert me.json()["profile_complete"] is False

    onboarded = await client.post(
        "/api/auth/complete-profile",
        json={"name": "Journey Student", "reg_no": "21BCE4321"},  # mandatory for students
        headers=auth(student),
    )
    assert onboarded.status_code == 200
    assert onboarded.json()["profile_complete"] is True
    assert onboarded.json()["reg_no"] == "21BCE4321"

    # --- classroom: faculty creates + starts a session -----------------
    _, prof = await make_user("journey.prof@vit.ac.in")
    created = await client.post(
        "/api/classrooms", json={"name": "Journey Section"}, headers=auth(prof)
    )
    classroom_id = created.json()["id"]
    student_code = created.json()["student_join_code"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": "ref01"},
        headers=auth(prof),
    )
    assert started.status_code == 201

    # --- join persists: /enrolled shows it without re-entering the code
    joined = await client.post(
        "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
    )
    assert joined.status_code == 200
    enrolled = await client.get("/api/classrooms/enrolled", headers=auth(student))
    assert any(c["id"] == classroom_id for c in enrolled.json()["classrooms"])

    # --- normal grounded Q&A, then a follow-up in the SAME thread ------
    ask1 = await client.post(
        "/api/chat/messages",
        json={
            "classroom_id": classroom_id,
            "experiment_id": "ref01",
            "message": "What is a titration used for?",
        },
        headers=auth(student),
    )
    assert ask1.status_code == 200
    thread_id = ask1.json()["thread_id"]
    assert ask1.json()["message"]["kind"] == "qa"

    ask2 = await client.post(
        "/api/chat/messages",
        json={
            "classroom_id": classroom_id,
            "experiment_id": "ref01",
            "thread_id": thread_id,
            "message": "Can you say more about that?",
        },
        headers=auth(student),
    )
    assert ask2.status_code == 200
    assert ask2.json()["thread_id"] == thread_id  # same conversation, retained context

    # --- Socratic guidance happens naturally: a guidance question first,
    # then the actual first-step data as a real, verified attempt -------
    guide = await client.post(
        "/api/chat/messages",
        json={
            "classroom_id": classroom_id,
            "experiment_id": "ref01",
            "message": "Can you guide me through this experiment?",
        },
        headers=auth(student),
    )
    assert guide.status_code == 200
    assert guide.json()["message"]["kind"] == "socratic"
    guide_meta = guide.json()["message"]["metadata"]
    assert guide_meta["current_step"] == 0
    assert guide_meta["complete"] is False

    attempt = await client.post(
        "/api/chat/messages",
        json={
            "classroom_id": classroom_id,
            "experiment_id": "ref01",
            "message": "standard_normality=0.1, standard_volume=25.0, value=2.5",
        },
        headers=auth(student),
    )
    assert attempt.status_code == 200
    attempt_meta = attempt.json()["message"]["metadata"]
    assert attempt_meta["type"] == "socratic"
    assert attempt_meta["passed"] is True
    assert attempt_meta["current_step"] == 1  # advanced deterministically

    # --- a second, separate chat for this same experiment: independent
    # history, does not see the first chat's messages -------------------
    second_thread = await client.post(
        "/api/chat/threads",
        json={"classroom_id": classroom_id, "experiment_id": "ref01"},
        headers=auth(student),
    )
    assert second_thread.status_code == 201
    second_thread_id = second_thread.json()["id"]
    assert second_thread_id != thread_id

    second_msgs = await client.get(
        f"/api/chat/threads/{second_thread_id}/messages", headers=auth(student)
    )
    assert second_msgs.json()["messages"] == []  # fresh, no leaked context

    first_msgs = await client.get(
        f"/api/chat/threads/{thread_id}/messages", headers=auth(student)
    )
    assert len(first_msgs.json()["messages"]) == 4  # the two Q&A turns only

    # --- chat list shows all of them ------------------------------------
    threads = await client.get(
        f"/api/chat/threads?classroom_id={classroom_id}&experiment_id=ref01",
        headers=auth(student),
    )
    thread_ids = {t["id"] for t in threads.json()["threads"]}
    assert {thread_id, second_thread_id, guide.json()["thread_id"]} <= thread_ids


async def test_faculty_promotion_takes_effect_immediately(client, make_user):
    _, prof = await make_user("promo.prof@vit.ac.in")
    created = await client.post(
        "/api/classrooms", json={"name": "Promotion Section"}, headers=auth(prof)
    )
    classroom_id = created.json()["id"]
    student_code = created.json()["student_join_code"]

    _, student = await make_user("promo.student@vitstudent.ac.in")
    await client.post(
        "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
    )
    student_id = (await client.get("/api/auth/me", headers=auth(student))).json()["id"]

    # Before promotion: no faculty capability for this classroom.
    before = await client.get(f"/api/classrooms/{classroom_id}/roster", headers=auth(student))
    assert before.status_code == 403

    promoted = await client.post(
        f"/api/classrooms/{classroom_id}/promote",
        json={"student_user_id": student_id},
        headers=auth(prof),
    )
    assert promoted.status_code == 201

    # Immediately after, on the SAME session/token (no re-login needed):
    # full faculty capability for this classroom.
    after = await client.get(f"/api/classrooms/{classroom_id}/roster", headers=auth(student))
    assert after.status_code == 200

    # Platform identity is untouched.
    me = await client.get("/api/auth/me", headers=auth(student))
    assert me.json()["role"] == "student"

    # Demotion immediately revokes it again.
    demoted = await client.post(
        f"/api/classrooms/{classroom_id}/demote",
        json={"user_id": student_id},
        headers=auth(prof),
    )
    assert demoted.status_code == 200
    revoked = await client.get(f"/api/classrooms/{classroom_id}/roster", headers=auth(student))
    assert revoked.status_code == 403


async def test_admin_global_role_management(client, make_user):
    _, admin = await make_user("adhyanjain2006@gmail.com", "Admin")
    _, someone = await make_user("random.person@gmail.com")  # unmatched domain -> student

    me_before = await client.get("/api/auth/me", headers=auth(someone))
    assert me_before.json()["role"] == "student"
    target_id = me_before.json()["id"]

    made_admin = await client.patch(
        f"/api/admin/users/{target_id}/role", json={"role": "admin"}, headers=auth(admin)
    )
    assert made_admin.status_code == 200
    assert (await client.get("/api/auth/me", headers=auth(someone))).json()["role"] == "admin"

    made_student = await client.patch(
        f"/api/admin/users/{target_id}/role", json={"role": "student"}, headers=auth(admin)
    )
    assert made_student.status_code == 200
    assert (await client.get("/api/auth/me", headers=auth(someone))).json()["role"] == "student"
