"""Rename / archive ("delete") classes, and per-session reports.

Deleting a class must never destroy research data: it archives. The report
routes are faculty-only, per class, and never cross a class boundary.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from backend.auth import session as session_cookie
from backend.models import AuditLog, ChatMessage, Classroom

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


@pytest.fixture
def llm(fake_llm, monkeypatch):
    fake_llm.reply = "HOMO is the highest occupied molecular orbital."
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    return fake_llm


async def _class_with_session(client, make_user, tag, experiment="exp07"):
    _, prof = await make_user(f"prof.{tag}@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": f"Class {tag}"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    code = created.json()["student_join_code"]
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": experiment},
        headers=auth(prof),
    )
    assert started.status_code == 201
    return prof, classroom_id, code, started.json()["session_id"]


async def _student_chats(client, make_user, tag, code, classroom_id, message="What is HOMO?"):
    user, student = await make_user(f"student.{tag}@vitstudent.ac.in", name=f"Student {tag}")
    await client.post("/api/classrooms/join", json={"join_code": code}, headers=auth(student))
    resp = await client.post(
        "/api/chat/messages",
        json={"classroom_id": classroom_id, "experiment_id": "exp07", "message": message},
        headers=auth(student),
    )
    assert resp.status_code == 200, resp.text
    return user, student


# --- rename -------------------------------------------------------------------


async def test_faculty_can_rename_a_class_and_the_name_is_cleaned(client, make_user):
    prof, cid, _, _ = await _class_with_session(client, make_user, "r1")
    resp = await client.patch(
        f"/api/classrooms/{cid}", json={"name": "  Sec   A   Morning  "}, headers=auth(prof)
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Sec A Morning"
    mine = await client.get("/api/classrooms/mine", headers=auth(prof))
    assert [c["name"] for c in mine.json()["classrooms"]] == ["Sec A Morning"]


async def test_blank_name_is_rejected(client, make_user):
    prof, cid, _, _ = await _class_with_session(client, make_user, "r2")
    resp = await client.patch(f"/api/classrooms/{cid}", json={"name": "   "}, headers=auth(prof))
    assert resp.status_code == 422


async def test_only_that_classes_faculty_can_rename_or_archive(client, make_user):
    prof, cid, code, _ = await _class_with_session(client, make_user, "r3")
    _, other_prof = await make_user("other.prof@vit.ac.in")
    await client.post("/api/classrooms", json={"name": "Elsewhere"}, headers=auth(other_prof))
    _, student = await make_user("stu.r3@vitstudent.ac.in")
    await client.post("/api/classrooms/join", json={"join_code": code}, headers=auth(student))

    rename = {"name": "x"}
    assert (await client.patch(f"/api/classrooms/{cid}", json=rename, headers=auth(other_prof))).status_code == 404
    assert (await client.delete(f"/api/classrooms/{cid}", headers=auth(other_prof))).status_code == 404
    assert (await client.patch(f"/api/classrooms/{cid}", json=rename, headers=auth(student))).status_code in (403, 404)
    assert (await client.delete(f"/api/classrooms/{cid}", headers=auth(student))).status_code in (403, 404)
    mine = await client.get("/api/classrooms/mine", headers=auth(prof))
    assert mine.json()["classrooms"][0]["name"] == "Class r3"  # untouched


# --- archive ("delete") --------------------------------------------------------


async def test_archiving_hides_the_class_but_keeps_every_row(client, make_user, llm, db):
    prof, cid, code, _ = await _class_with_session(client, make_user, "a1")
    await _student_chats(client, make_user, "a1", code, cid)
    before = (await db.scalar(select(func.count()).select_from(ChatMessage))) or 0
    assert before >= 2

    resp = await client.delete(f"/api/classrooms/{cid}", headers=auth(prof))
    assert resp.status_code == 200 and resp.json()["archived"] is True

    assert (await client.get("/api/classrooms/mine", headers=auth(prof))).json()["classrooms"] == []
    with_archived = await client.get("/api/classrooms/mine?include_archived=true", headers=auth(prof))
    assert [c["id"] for c in with_archived.json()["classrooms"]] == [cid]
    db.expire_all()
    assert (await db.scalar(select(func.count()).select_from(ChatMessage))) == before
    assert (await db.scalar(select(func.count()).select_from(Classroom))) == 1


async def test_archiving_ends_the_live_session_and_stops_the_students_chat(
    client, make_user, llm
):
    prof, cid, code, _ = await _class_with_session(client, make_user, "a2")
    _, student = await _student_chats(client, make_user, "a2", code, cid)
    await client.delete(f"/api/classrooms/{cid}", headers=auth(prof))

    resp = await client.post(
        "/api/chat/messages",
        json={"classroom_id": cid, "experiment_id": "exp07", "message": "still there?"},
        headers=auth(student),
    )
    assert resp.status_code >= 400
    enrolled = await client.get("/api/classrooms/enrolled", headers=auth(student))
    assert enrolled.json()["classrooms"] == []


async def test_archived_class_cannot_be_joined_or_started(client, make_user):
    prof, cid, code, _ = await _class_with_session(client, make_user, "a3")
    await client.delete(f"/api/classrooms/{cid}", headers=auth(prof))

    _, late = await make_user("late.a3@vitstudent.ac.in")
    join = await client.post("/api/classrooms/join", json={"join_code": code}, headers=auth(late))
    assert join.status_code == 404  # same as a wrong code

    start = await client.post(
        f"/api/classrooms/{cid}/sessions/start", json={"experiment_id": "exp07"}, headers=auth(prof)
    )
    assert start.status_code >= 400


async def test_restore_brings_the_class_back(client, make_user):
    prof, cid, _, _ = await _class_with_session(client, make_user, "a4")
    await client.delete(f"/api/classrooms/{cid}", headers=auth(prof))
    restored = await client.post(f"/api/classrooms/{cid}/restore", headers=auth(prof))
    assert restored.status_code == 200 and restored.json()["archived"] is False
    mine = await client.get("/api/classrooms/mine", headers=auth(prof))
    assert [c["id"] for c in mine.json()["classrooms"]] == [cid]
    started = await client.post(
        f"/api/classrooms/{cid}/sessions/start", json={"experiment_id": "exp07"}, headers=auth(prof)
    )
    assert started.status_code == 201


async def test_rename_and_archive_are_audited(client, make_user, db):
    prof, cid, _, _ = await _class_with_session(client, make_user, "a5")
    await client.patch(f"/api/classrooms/{cid}", json={"name": "Renamed"}, headers=auth(prof))
    await client.delete(f"/api/classrooms/{cid}", headers=auth(prof))
    await client.post(f"/api/classrooms/{cid}/restore", headers=auth(prof))
    events = set((await db.scalars(select(AuditLog.event).where(AuditLog.classroom_id == cid))).all())
    assert {"classroom.renamed", "classroom.archived", "classroom.restored"} <= events


# --- session reports ------------------------------------------------------------


async def test_session_list_and_report_show_the_students_and_their_prompts(
    client, make_user, llm
):
    prof, cid, code, sid = await _class_with_session(client, make_user, "s1")
    user, _ = await _student_chats(client, make_user, "s1", code, cid)
    await client.post(f"/api/classrooms/{cid}/sessions/{sid}/end", headers=auth(prof))

    listing = await client.get(f"/api/classrooms/{cid}/sessions", headers=auth(prof))
    assert listing.status_code == 200
    row = listing.json()["sessions"][0]
    assert row["id"] == sid and row["students"] == 1 and row["prompts"] == 1
    assert row["status"] == "ended" and row["duration_minutes"] is not None

    report = await client.get(f"/api/classrooms/{cid}/sessions/{sid}/report", headers=auth(prof))
    assert report.status_code == 200
    body = report.json()
    assert body["session"]["experiment_id"] == "exp07"
    assert body["totals"]["students"] == 1 and body["totals"]["prompts"] == 1
    student = body["students"][0]
    assert student["student_id"] == user.id and student["prompts"] == 1
    assert student["tutor_replies"] == 1 and student["llm_calls"] == 1


async def test_transcript_returns_the_full_conversation_and_is_audited(
    client, make_user, llm, db
):
    prof, cid, code, sid = await _class_with_session(client, make_user, "s2")
    user, _ = await _student_chats(client, make_user, "s2", code, cid, "What is HOMO?")
    resp = await client.get(
        f"/api/classrooms/{cid}/sessions/{sid}/students/{user.id}/transcript", headers=auth(prof)
    )
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert [m["author"] for m in msgs] == ["student", "tutor"]
    assert msgs[0]["content"] == "What is HOMO?"
    assert "HOMO is the highest occupied molecular orbital" in msgs[1]["content"]
    assert msgs[1]["meta"]["llm_calls"] == 1
    events = (await db.scalars(select(AuditLog.event).where(AuditLog.classroom_id == cid))).all()
    assert "report.transcript_viewed" in events


async def test_reports_still_work_after_the_class_is_archived(client, make_user, llm):
    prof, cid, code, sid = await _class_with_session(client, make_user, "s3")
    user, _ = await _student_chats(client, make_user, "s3", code, cid)
    await client.delete(f"/api/classrooms/{cid}", headers=auth(prof))
    report = await client.get(f"/api/classrooms/{cid}/sessions/{sid}/report", headers=auth(prof))
    assert report.status_code == 200 and report.json()["totals"]["prompts"] == 1
    transcript = await client.get(
        f"/api/classrooms/{cid}/sessions/{sid}/students/{user.id}/transcript", headers=auth(prof)
    )
    assert transcript.status_code == 200


async def test_students_and_other_classes_faculty_cannot_read_reports(client, make_user, llm):
    prof, cid, code, sid = await _class_with_session(client, make_user, "s4")
    user, student = await _student_chats(client, make_user, "s4", code, cid)
    _, other_prof = await make_user("other.s4@vit.ac.in")
    await client.post("/api/classrooms", json={"name": "Other"}, headers=auth(other_prof))

    urls = [
        f"/api/classrooms/{cid}/sessions",
        f"/api/classrooms/{cid}/sessions/{sid}/report",
        f"/api/classrooms/{cid}/sessions/{sid}/students/{user.id}/transcript",
    ]
    for url in urls:
        assert (await client.get(url, headers=auth(student))).status_code in (403, 404), url
        assert (await client.get(url, headers=auth(other_prof))).status_code == 404, url
        assert (await client.get(url)).status_code in (401, 403), url


async def test_a_session_or_student_from_another_class_is_a_404_not_a_leak(
    client, make_user, llm
):
    prof_a, cid_a, code_a, sid_a = await _class_with_session(client, make_user, "s5a")
    prof_b, cid_b, code_b, sid_b = await _class_with_session(client, make_user, "s5b")
    user_b, _ = await _student_chats(client, make_user, "s5b", code_b, cid_b)

    # faculty A asks class A's URL about class B's session / student
    assert (
        await client.get(f"/api/classrooms/{cid_a}/sessions/{sid_b}/report", headers=auth(prof_a))
    ).status_code == 404
    assert (
        await client.get(
            f"/api/classrooms/{cid_a}/sessions/{sid_a}/students/{user_b.id}/transcript",
            headers=auth(prof_a),
        )
    ).status_code == 404
