"""Admin role changes, classroom-scoped co-faculty promotion, default-to-
student for unmatched domains, and name/reg_no profile completion.

Covers the four capabilities added on top of the existing role model:
admin can change anyone's platform role anywhere in the db; a professor
can promote a student to co-faculty for their own classroom only (not a
platform-wide faculty grant); an unrecognised email domain now defaults to
STUDENT instead of being rejected; and every user has an editable name and
(for students) a registration number.
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


async def _make_classroom(client, faculty_token, experiment_id="ref01"):
    created = await client.post(
        "/api/classrooms", json={"name": "Role mgmt test"}, headers=auth(faculty_token)
    )
    assert created.status_code == 201, created.text
    classroom = created.json()
    if experiment_id is not None:
        started = await client.post(
            f"/api/classrooms/{classroom['id']}/sessions/start",
            json={"experiment_id": experiment_id},
            headers=auth(faculty_token),
        )
        assert started.status_code == 201, started.text
        classroom["active_session_id"] = started.json()["session_id"]
    return classroom


async def _enrol(client, student_token, join_code):
    joined = await client.post(
        "/api/classrooms/join", json={"join_code": join_code}, headers=auth(student_token)
    )
    assert joined.status_code == 200, joined.text
    return joined.json()


# --- admin: change anyone's platform role -----------------------------------


class TestAdminRoleChange:
    async def test_admin_promotes_a_student_to_admin(self, client, make_user):
        _, admin_a = await make_user("adhyanjain2006@gmail.com", "Admin A")
        _, admin_b = await make_user("second.admin@gmail.com", "Admin B")
        # admin_b starts as a plain student (unmatched domain -> STUDENT).
        me_before = await client.get("/api/auth/me", headers=auth(admin_b))
        assert me_before.json()["role"] == "student"
        target_id = me_before.json()["id"]

        resp = await client.patch(
            f"/api/admin/users/{target_id}/role",
            json={"role": "admin"},
            headers=auth(admin_a),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "admin"

        me_after = await client.get("/api/auth/me", headers=auth(admin_b))
        assert me_after.json()["role"] == "admin"

    async def test_admin_demotes_a_faculty_to_student(self, client, make_user):
        _, admin = await make_user("adhyanjain2006@gmail.com", "Admin")
        _, prof = await make_user("demote.me@vit.ac.in")
        me = await client.get("/api/auth/me", headers=auth(prof))
        assert me.json()["role"] == "faculty"

        resp = await client.patch(
            f"/api/admin/users/{me.json()['id']}/role",
            json={"role": "student"},
            headers=auth(admin),
        )
        assert resp.status_code == 200
        me_after = await client.get("/api/auth/me", headers=auth(prof))
        assert me_after.json()["role"] == "student"

    async def test_admin_cannot_change_their_own_role(self, client, make_user):
        _, admin = await make_user("adhyanjain2006@gmail.com", "Admin")
        me = await client.get("/api/auth/me", headers=auth(admin))
        resp = await client.patch(
            f"/api/admin/users/{me.json()['id']}/role",
            json={"role": "student"},
            headers=auth(admin),
        )
        assert resp.status_code == 400

    async def test_non_admin_cannot_use_the_role_route(self, client, make_user):
        _, prof = await make_user("plain.prof@vit.ac.in")
        _, student = await make_user("plain.student@vitstudent.ac.in")
        me = await client.get("/api/auth/me", headers=auth(student))
        resp = await client.patch(
            f"/api/admin/users/{me.json()['id']}/role",
            json={"role": "admin"},
            headers=auth(prof),
        )
        assert resp.status_code == 403

    async def test_admin_can_search_users(self, client, make_user):
        _, admin = await make_user("adhyanjain2006@gmail.com", "Admin")
        await make_user("findme.searchtest@vitstudent.ac.in", "Findme Person")
        resp = await client.get(
            "/api/admin/users", params={"q": "findme.searchtest"}, headers=auth(admin)
        )
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.json()["users"]]
        assert "findme.searchtest@vitstudent.ac.in" in emails

    async def test_admin_can_clear_a_role_override_back_to_domain_derived(
        self, client, make_user
    ):
        _, admin = await make_user("adhyanjain2006@gmail.com", "Admin")
        _, target = await make_user("cleartest@vitstudent.ac.in")
        target_id = (await client.get("/api/auth/me", headers=auth(target))).json()["id"]

        overridden = await client.patch(
            f"/api/admin/users/{target_id}/role",
            json={"role": "faculty"},
            headers=auth(admin),
        )
        assert overridden.status_code == 200
        assert (await client.get("/api/auth/me", headers=auth(target))).json()["role"] == "faculty"

        cleared = await client.delete(
            f"/api/admin/users/{target_id}/role-override", headers=auth(admin)
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["role_override"] is None
        # Back to domain-derived: @vitstudent.ac.in -> student.
        assert (await client.get("/api/auth/me", headers=auth(target))).json()["role"] == "student"

    async def test_admin_cannot_clear_their_own_override(self, client, make_user):
        _, admin = await make_user("adhyanjain2006@gmail.com", "Admin")
        me = await client.get("/api/auth/me", headers=auth(admin))
        resp = await client.delete(
            f"/api/admin/users/{me.json()['id']}/role-override", headers=auth(admin)
        )
        assert resp.status_code == 400


# --- default-to-student for an unmatched domain -----------------------------


class TestDefaultToStudent:
    async def test_unrecognised_domain_becomes_a_student_not_a_rejection(
        self, client, make_user
    ):
        _, token = await make_user("someone@gmail.com", "Someone")
        resp = await client.get("/api/auth/me", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["role"] == "student"


# --- name / reg_no profile completion ---------------------------------------


class TestProfileCompletion:
    async def test_student_profile_incomplete_until_reg_no_set(self, client, make_user):
        _, token = await make_user("needs.regno@vitstudent.ac.in")
        me = await client.get("/api/auth/me", headers=auth(token))
        assert me.json()["profile_complete"] is False

        resp = await client.post(
            "/api/auth/complete-profile",
            json={"name": "Real Name", "reg_no": "21BCE1234"},
            headers=auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_complete"] is True
        assert resp.json()["name"] == "Real Name"

    async def test_faculty_profile_never_needs_a_reg_no(self, client, make_user):
        _, token = await make_user("prof.noregno@vit.ac.in")
        me = await client.get("/api/auth/me", headers=auth(token))
        # Faculty still go through the one-time "confirm your name" step
        # (like every role does), just never asked for a reg_no.
        assert me.json()["profile_complete"] is False

        resp = await client.post(
            "/api/auth/complete-profile",
            json={"name": "Dr. Faculty", "reg_no": None},
            headers=auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_complete"] is True
        assert resp.json()["reg_no"] is None

    async def test_student_reg_no_is_mandatory(self, client, make_user):
        _, token = await make_user("mandatory.regno@vitstudent.ac.in")
        for blank in (None, "", "   "):
            resp = await client.post(
                "/api/auth/complete-profile",
                json={"name": "No Reg No Student", "reg_no": blank},
                headers=auth(token),
            )
            assert resp.status_code == 422, blank
        me = await client.get("/api/auth/me", headers=auth(token))
        assert me.json()["profile_complete"] is False

    async def test_student_reg_no_must_look_like_one(self, client, make_user):
        _, token = await make_user("badformat.regno@vitstudent.ac.in")
        for bad in ("abc", "21 BCE 1234", "21BCE-1234", "x" * 30):
            resp = await client.post(
                "/api/auth/complete-profile",
                json={"name": "Some Student", "reg_no": bad},
                headers=auth(token),
            )
            assert resp.status_code == 422, bad

    async def test_student_reg_no_is_stored_uppercase_and_trimmed(self, client, make_user):
        _, token = await make_user("upper.regno@vitstudent.ac.in")
        resp = await client.post(
            "/api/auth/complete-profile",
            json={"name": "Some Student", "reg_no": "  21bce1234 "},
            headers=auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["reg_no"] == "21BCE1234"
        assert resp.json()["profile_complete"] is True

    async def test_student_onboarded_before_the_rule_is_asked_again(self, client, make_user, db):
        from sqlalchemy import select

        from backend.models import User

        user, token = await make_user("legacy.regno@vitstudent.ac.in")
        row = (await db.scalars(select(User).where(User.id == user.id))).first()
        row.onboarded = True  # signed up while reg no was optional
        row.reg_no = None
        await db.commit()
        me = await client.get("/api/auth/me", headers=auth(token))
        assert me.json()["profile_complete"] is False

    async def test_name_persists_across_a_second_login_instead_of_being_overwritten(
        self, client, make_user, db
    ):
        from sqlalchemy import select

        from backend.auth.roles import role_for_email
        from backend.models import User

        user, token = await make_user("persist.name@vitstudent.ac.in", "Google Name")
        await client.post(
            "/api/auth/complete-profile",
            json={"name": "User Edited Name", "reg_no": "21BCE0001"},
            headers=auth(token),
        )

        # Simulate the callback's existing-user branch directly (same code
        # path a second real login would take).
        row = (await db.scalars(select(User).where(User.id == user.id))).first()
        if not row.name:
            row.name = "Google Name"
        row.role = role_for_email(row.email)
        await db.commit()

        me = await client.get("/api/auth/me", headers=auth(token))
        assert me.json()["name"] == "User Edited Name"


# --- classroom-scoped co-faculty promotion ----------------------------------


class TestClassCoFaculty:
    async def test_promote_grants_working_faculty_access_to_this_classroom_only(
        self, client, make_user, registered_experiment
    ):
        _, prof = await make_user("promoter@vit.ac.in")
        classroom = await _make_classroom(client, prof)
        _, alice = await make_user("alice.promote@vitstudent.ac.in")
        await _enrol(client, alice, classroom["student_join_code"])
        alice_id = (await client.get("/api/auth/me", headers=auth(alice))).json()["id"]

        # Not yet promoted: faculty-only roster route refuses.
        before = await client.get(
            f"/api/classrooms/{classroom['id']}/roster", headers=auth(alice)
        )
        assert before.status_code == 403

        promoted = await client.post(
            f"/api/classrooms/{classroom['id']}/promote",
            json={"student_user_id": alice_id},
            headers=auth(prof),
        )
        assert promoted.status_code == 201, promoted.text

        # Now Alice can act as faculty for THIS classroom.
        after = await client.get(
            f"/api/classrooms/{classroom['id']}/roster", headers=auth(alice)
        )
        assert after.status_code == 200

        # Her platform role is unaffected -- still "student" everywhere else.
        me = await client.get("/api/auth/me", headers=auth(alice))
        assert me.json()["role"] == "student"

    async def test_promotion_does_not_grant_access_to_a_different_classroom(
        self, client, make_user, registered_experiment
    ):
        _, prof_a = await make_user("classA.prof@vit.ac.in")
        _, prof_b = await make_user("classB.prof@vit.ac.in")
        classroom_a = await _make_classroom(client, prof_a)
        classroom_b = await _make_classroom(client, prof_b)
        _, alice = await make_user("alice.twoclass@vitstudent.ac.in")
        await _enrol(client, alice, classroom_a["student_join_code"])
        alice_id = (await client.get("/api/auth/me", headers=auth(alice))).json()["id"]

        await client.post(
            f"/api/classrooms/{classroom_a['id']}/promote",
            json={"student_user_id": alice_id},
            headers=auth(prof_a),
        )

        resp = await client.get(
            f"/api/classrooms/{classroom_b['id']}/roster", headers=auth(alice)
        )
        assert resp.status_code == 404

    async def test_demote_returns_the_co_faculty_to_a_student(
        self, client, make_user, registered_experiment
    ):
        _, prof = await make_user("demote.prof@vit.ac.in")
        classroom = await _make_classroom(client, prof)
        _, bob = await make_user("bob.demote@vitstudent.ac.in")
        await _enrol(client, bob, classroom["student_join_code"])
        bob_id = (await client.get("/api/auth/me", headers=auth(bob))).json()["id"]

        await client.post(
            f"/api/classrooms/{classroom['id']}/promote",
            json={"student_user_id": bob_id},
            headers=auth(prof),
        )
        demoted = await client.post(
            f"/api/classrooms/{classroom['id']}/demote",
            json={"user_id": bob_id},
            headers=auth(prof),
        )
        assert demoted.status_code == 200, demoted.text

        resp = await client.get(
            f"/api/classrooms/{classroom['id']}/roster", headers=auth(bob)
        )
        assert resp.status_code == 403

    async def test_demote_refuses_to_touch_a_genuine_faculty_peer(
        self, client, make_user
    ):
        _, prof_a = await make_user("peer.a@vit.ac.in")
        classroom = await _make_classroom(client, prof_a, experiment_id=None)
        _, prof_b = await make_user("peer.b@vit.ac.in")
        await client.post(
            "/api/classrooms/join",
            json={"join_code": classroom["faculty_join_code"]},
            headers=auth(prof_b),
        )
        prof_b_id = (await client.get("/api/auth/me", headers=auth(prof_b))).json()["id"]

        resp = await client.post(
            f"/api/classrooms/{classroom['id']}/demote",
            json={"user_id": prof_b_id},
            headers=auth(prof_a),
        )
        assert resp.status_code == 400

    async def test_promoted_students_own_test_activity_is_tagged_faculty_test(
        self, client, make_user, registered_experiment
    ):
        _, prof = await make_user("tagcheck.prof@vit.ac.in")
        classroom = await _make_classroom(client, prof)
        _, carol = await make_user("carol.tagcheck@vitstudent.ac.in")
        await _enrol(client, carol, classroom["student_join_code"])
        carol_id = (await client.get("/api/auth/me", headers=auth(carol))).json()["id"]

        await client.post(
            f"/api/classrooms/{classroom['id']}/promote",
            json={"student_user_id": carol_id},
            headers=auth(prof),
        )

        submitted = await client.post(
            "/api/submissions",
            json={
                "classroom_id": classroom["id"],
                "experiment_id": "ref01",
                "data": {},
                "reported_value": 1.0,
            },
            headers=auth(carol),
        )
        assert submitted.status_code == 201, submitted.text

        listing = await client.get(
            f"/api/dashboard/classrooms/{classroom['id']}/submissions",
            headers=auth(prof),
        )
        assert listing.status_code == 200
        found = [s for s in listing.json()["submissions"] if s["student_id"] == carol_id]
        assert found and found[0]["actor_type"] == "faculty_test"
