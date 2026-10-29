"""The Q&A chat route: /api/qa/ask and /api/qa/history.

Covers the gap flagged in docs/final_audit.md item 5 -- there was no
HTTP surface for the retrieval pipeline (backend/retrieval/pipeline.py)
at all. These tests exercise the route, not the pipeline's own grounding
guarantees (see test_retrieval.py / test_scope_classifier.py for those).
"""

from __future__ import annotations

import pytest

from backend.auth import session as session_cookie

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


async def _classroom_with_active_session(
    client, prof_token: str, experiment_id: str = "exp01"
) -> tuple[str, str, str]:
    created = await client.post(
        "/api/classrooms", json={"name": "QA classroom"}, headers=auth(prof_token)
    )
    classroom_id = created.json()["id"]
    student_code = created.json()["student_join_code"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": experiment_id},
        headers=auth(prof_token),
    )
    assert started.status_code == 201
    return classroom_id, student_code, started.json()["session_id"]


class TestStudentAsk:
    async def test_student_can_ask_during_active_session(self, client, make_user):
        _, prof = await make_user("prof.qa@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof)
        _, student = await make_user("student.qa@vitstudent.ac.in")
        joined = await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )
        assert joined.status_code == 200

        resp = await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "what is the Nernst equation"},
            headers=auth(student),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "reply" in body and isinstance(body["reply"], str) and body["reply"]
        assert "citations" in body
        assert "answer_source" in body

    async def test_student_without_active_session_is_rejected(self, client, make_user):
        _, prof = await make_user("prof.qa2@vit.ac.in")
        created = await client.post(
            "/api/classrooms", json={"name": "No session yet"}, headers=auth(prof)
        )
        classroom_id = created.json()["id"]
        student_code = created.json()["student_join_code"]
        _, student = await make_user("student.qa2@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        resp = await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "what is a burette"},
            headers=auth(student),
        )
        assert resp.status_code == 409

    async def test_student_not_enrolled_gets_404(self, client, make_user):
        _, prof = await make_user("prof.qa3@vit.ac.in")
        classroom_id, _, _ = await _classroom_with_active_session(client, prof)
        _, outsider = await make_user("outsider.qa@vitstudent.ac.in")

        resp = await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "hello"},
            headers=auth(outsider),
        )
        assert resp.status_code == 404

    async def test_stale_tab_rejected_after_session_ends(self, client, make_user):
        """A student's request must fail server-side once class has ended,
        even though the client never re-fetched classroom state."""
        _, prof = await make_user("prof.qa4@vit.ac.in")
        classroom_id, student_code, session_id = await _classroom_with_active_session(client, prof)
        _, student = await make_user("student.qa4@vitstudent.ac.in")
        await client.post(
            "/api/classrooms/join", json={"join_code": student_code}, headers=auth(student)
        )

        # Ask once while active -- should work.
        first = await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "what is a burette"},
            headers=auth(student),
        )
        assert first.status_code == 200

        ended = await client.post(
            f"/api/classrooms/{classroom_id}/sessions/{session_id}/end",
            headers=auth(prof),
        )
        assert ended.status_code == 200

        stale = await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "what is a burette"},
            headers=auth(student),
        )
        assert stale.status_code == 409


class TestFacultyAsk:
    async def test_faculty_can_ask_without_active_session(self, client, make_user):
        """Faculty must not need student mode -- and must not need an active
        class session either, since they may be testing between classes."""
        _, prof = await make_user("prof.qa5@vit.ac.in")
        created = await client.post(
            "/api/classrooms", json={"name": "Faculty QA"}, headers=auth(prof)
        )
        classroom_id = created.json()["id"]

        resp = await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "what is a burette"},
            headers=auth(prof),
        )
        assert resp.status_code == 200

    async def test_faculty_qa_is_stamped_faculty_test(self, client, make_user, db):
        from sqlalchemy import select

        from backend.models import ActorType, ChatMessage, ChatMessageKind

        _, prof = await make_user("prof.qa6@vit.ac.in")
        created = await client.post(
            "/api/classrooms", json={"name": "Faculty Stamp"}, headers=auth(prof)
        )
        classroom_id = created.json()["id"]
        await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "what is a burette"},
            headers=auth(prof),
        )
        rows = list(
            (
                await db.scalars(
                    select(ChatMessage).where(
                        ChatMessage.classroom_id == classroom_id,
                        ChatMessage.kind == ChatMessageKind.QA,
                    )
                )
            ).all()
        )
        assert rows
        assert all(r.actor_type is ActorType.FACULTY_TEST for r in rows)


class TestHistory:
    async def test_history_returns_only_callers_own_messages(self, client, make_user):
        _, prof = await make_user("prof.qa7@vit.ac.in")
        classroom_id, student_code, _ = await _classroom_with_active_session(client, prof)
        _, student_a = await make_user("student.qa7a@vitstudent.ac.in")
        _, student_b = await make_user("student.qa7b@vitstudent.ac.in")
        for token in (student_a, student_b):
            await client.post(
                "/api/classrooms/join", json={"join_code": student_code}, headers=auth(token)
            )

        await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "student a question"},
            headers=auth(student_a),
        )
        await client.post(
            "/api/qa/ask",
            json={"classroom_id": classroom_id, "message": "student b question"},
            headers=auth(student_b),
        )

        history_a = await client.get(
            f"/api/qa/history?classroom_id={classroom_id}", headers=auth(student_a)
        )
        assert history_a.status_code == 200
        contents = [m["content"] for m in history_a.json()["messages"]]
        assert "student a question" in contents
        assert "student b question" not in contents
