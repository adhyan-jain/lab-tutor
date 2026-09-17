"""Pre/post-test marks: entry, permission gating, analytics, export.

Analytics numbers below are computed by hand in each test, not invented
at runtime -- see CLAUDE.md's testing philosophy.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from backend.auth import session as session_cookie
from backend.models import ExperimentMarks

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


async def _make_classroom_with_student(client, make_user, faculty_email="prof.marks@vit.ac.in"):
    _, faculty_token = await make_user(faculty_email, "Prof Marks")
    created = await client.post(
        "/api/classrooms", json={"name": "Marks Test Section"}, headers=auth(faculty_token)
    )
    assert created.status_code == 201
    classroom_id = created.json()["id"]
    student_code = created.json()["student_join_code"]

    student, student_token = await make_user("student.marks@vitstudent.ac.in", "Student One")
    joined = await client.post(
        "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student_token)
    )
    assert joined.status_code == 200
    return classroom_id, faculty_token, student, student_token


class TestMarksEntry:
    async def test_upsert_is_idempotent_and_updates_in_place(self, client, make_user, db):
        classroom_id, faculty_token, student, _ = await _make_classroom_with_student(
            client, make_user
        )

        body = {
            "entries": [
                {
                    "student_id": student.id,
                    "pre_test_marks": 10,
                    "pre_test_max": 20,
                    "post_test_marks": 12,
                    "post_test_max": 20,
                }
            ]
        }
        resp1 = await client.post(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            json=body,
            headers=auth(faculty_token),
        )
        assert resp1.status_code == 200
        assert resp1.json()["saved"] == 1

        body["entries"][0]["post_test_marks"] = 18
        resp2 = await client.post(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            json=body,
            headers=auth(faculty_token),
        )
        assert resp2.status_code == 200

        rows = list(
            (
                await db.scalars(
                    select(ExperimentMarks).where(
                        ExperimentMarks.classroom_id == classroom_id,
                        ExperimentMarks.experiment_id == "exp01",
                    )
                )
            ).all()
        )
        assert len(rows) == 1  # updated in place, not duplicated
        assert rows[0].post_test_marks == 18

    async def test_foreign_student_id_is_ignored(self, client, make_user):
        classroom_id, faculty_token, _student, _ = await _make_classroom_with_student(
            client, make_user
        )
        resp = await client.post(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            json={"entries": [{"student_id": "not-a-real-user", "pre_test_marks": 5}]},
            headers=auth(faculty_token),
        )
        assert resp.status_code == 200
        assert resp.json()["saved"] == 0


class TestMarksPermissions:
    async def test_student_is_forbidden(self, client, make_user):
        classroom_id, _faculty_token, _student, student_token = await _make_classroom_with_student(
            client, make_user
        )
        resp = await client.get(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            headers=auth(student_token),
        )
        assert resp.status_code == 403

    async def test_faculty_of_a_different_classroom_gets_404(self, client, make_user):
        classroom_id, _faculty_token, _student, _ = await _make_classroom_with_student(
            client, make_user
        )
        _, other_faculty_token = await make_user("other.prof@vit.ac.in", "Other Prof")
        resp = await client.get(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            headers=auth(other_faculty_token),
        )
        assert resp.status_code == 404

    async def test_admin_can_access_any_classroom(self, client, make_user):
        classroom_id, _faculty_token, _student, _ = await _make_classroom_with_student(
            client, make_user
        )
        _, admin_token = await make_user("adhyanjain2006@gmail.com", "Admin")
        resp = await client.get(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            headers=auth(admin_token),
        )
        assert resp.status_code == 200


class TestMarksAnalytics:
    async def test_mean_gain_and_percent_improved_match_hand_calculation(
        self, client, make_user
    ):
        """Two students, normalised to a 0-100 scale (both graded out of 20
        here, so normalisation is a no-op):
          student1: pre 10 -> post 15  (pre% 50, post% 75, gain +25)
          student2: pre 12 -> post 12  (pre% 60, post% 60, gain 0)
        mean_pre = (50+60)/2 = 55.0
        mean_post = (75+60)/2 = 67.5
        mean_gain = (25+0)/2 = 12.5
        percent_improved = 1/2 improved = 50.0
        """
        _, faculty_token = await make_user("prof.analytics@vit.ac.in", "Prof")
        created = await client.post(
            "/api/classrooms", json={"name": "Analytics Section"}, headers=auth(faculty_token)
        )
        classroom_id = created.json()["id"]
        student_code = created.json()["student_join_code"]

        s1, s1_token = await make_user("s1.analytics@vitstudent.ac.in", "S1")
        s2, s2_token = await make_user("s2.analytics@vitstudent.ac.in", "S2")
        for tok in (s1_token, s2_token):
            r = await client.post(
                "/api/classrooms/join", json={"join_code": student_code}, headers=auth(tok)
            )
            assert r.status_code == 200

        resp = await client.post(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            json={
                "entries": [
                    {
                        "student_id": s1.id,
                        "pre_test_marks": 10, "pre_test_max": 20,
                        "post_test_marks": 15, "post_test_max": 20,
                    },
                    {
                        "student_id": s2.id,
                        "pre_test_marks": 12, "pre_test_max": 20,
                        "post_test_marks": 12, "post_test_max": 20,
                    },
                ]
            },
            headers=auth(faculty_token),
        )
        assert resp.status_code == 200
        assert resp.json()["saved"] == 2

        analytics = await client.get(
            f"/api/marks/classrooms/{classroom_id}/analytics", headers=auth(faculty_token)
        )
        assert analytics.status_code == 200
        exp = analytics.json()["experiments"][0]
        assert exp["experiment_id"] == "exp01"
        assert exp["n"] == 2
        assert exp["mean_pre"] == pytest.approx(55.0)
        assert exp["mean_post"] == pytest.approx(67.5)
        assert exp["mean_gain"] == pytest.approx(12.5)
        assert exp["percent_improved"] == pytest.approx(50.0)


class TestMarksExport:
    async def test_export_produces_a_readable_workbook(self, client, make_user):
        classroom_id, faculty_token, student, _ = await _make_classroom_with_student(
            client, make_user
        )
        await client.post(
            f"/api/marks/classrooms/{classroom_id}/experiments/exp01",
            json={
                "entries": [
                    {
                        "student_id": student.id,
                        "pre_test_marks": 8, "pre_test_max": 20,
                        "post_test_marks": 14, "post_test_max": 20,
                    }
                ]
            },
            headers=auth(faculty_token),
        )

        resp = await client.get(
            f"/api/marks/classrooms/{classroom_id}/export.xlsx", headers=auth(faculty_token)
        )
        assert resp.status_code == 200
        workbook = load_workbook(io.BytesIO(resp.content))
        assert workbook.sheetnames == ["Marks", "Summary"]
        marks_sheet = workbook["Marks"]
        data_row = [cell.value for cell in marks_sheet[2]]
        assert data_row[0] == "exp01"
        assert data_row[3] == 8  # pre-test
        assert data_row[5] == 14  # post-test
