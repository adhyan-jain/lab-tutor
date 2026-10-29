"""One class session can cover several experiments.

Faculty pick a set when starting; students may open a chat for any experiment in
the set and no other. The first pick is the session's primary `experiment_id`
(reports and exports key on it), so a single-experiment session behaves exactly
as before.
"""

from __future__ import annotations

import pytest

from backend.auth import session as session_cookie

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


async def _classroom_with_student(client, make_user, tag: str):
    _, prof = await make_user(f"prof.{tag}@vit.ac.in")
    created = await client.post("/api/classrooms", json={"name": "Multi"}, headers=auth(prof))
    classroom_id = created.json()["id"]
    _, student = await make_user(f"{tag}.stu@vitstudent.ac.in")
    await client.post(
        "/api/classrooms/join",
        json={"join_code": created.json()["student_join_code"]},
        headers=auth(student),
    )
    return classroom_id, prof, student


async def _open_thread(client, token, classroom_id, experiment_id):
    return await client.post(
        "/api/chat/threads",
        json={"classroom_id": classroom_id, "experiment_id": experiment_id, "title": "New chat"},
        headers=auth(token),
    )


async def test_start_with_several_experiments_reports_the_full_set(client, make_user):
    classroom_id, prof, _ = await _classroom_with_student(client, make_user, "multi_start")
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_ids": ["exp02", "exp04"]},
        headers=auth(prof),
    )
    assert started.status_code == 201, started.text
    assert started.json()["experiment_id"] == "exp02"
    assert started.json()["experiment_ids"] == ["exp02", "exp04"]

    active = await client.get(f"/api/classrooms/{classroom_id}/active-session", headers=auth(prof))
    assert active.json()["experiment_ids"] == ["exp02", "exp04"]


async def test_student_can_open_any_experiment_in_the_set_but_no_other(client, make_user):
    classroom_id, prof, student = await _classroom_with_student(client, make_user, "multi_gate")
    await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_ids": ["exp02", "exp04"]},
        headers=auth(prof),
    )
    for allowed in ("exp02", "exp04"):
        resp = await _open_thread(client, student, classroom_id, allowed)
        assert resp.status_code == 201, (allowed, resp.text)

    blocked = await _open_thread(client, student, classroom_id, "exp07")
    assert blocked.status_code == 400
    assert "exp02" in blocked.json()["detail"] and "exp04" in blocked.json()["detail"]


async def test_single_experiment_session_is_unchanged(client, make_user):
    classroom_id, prof, student = await _classroom_with_student(client, make_user, "single_exp")
    started = await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_id": "exp02"},
        headers=auth(prof),
    )
    assert started.json()["experiment_ids"] == ["exp02"]
    assert (await _open_thread(client, student, classroom_id, "exp02")).status_code == 201
    assert (await _open_thread(client, student, classroom_id, "exp04")).status_code == 400


async def test_unknown_or_empty_experiment_sets_are_rejected(client, make_user):
    classroom_id, prof, _ = await _classroom_with_student(client, make_user, "multi_bad")
    for body in ({}, {"experiment_ids": []}, {"experiment_ids": ["exp02", "exp999"]}):
        resp = await client.post(
            f"/api/classrooms/{classroom_id}/sessions/start", json=body, headers=auth(prof)
        )
        assert resp.status_code == 400, (body, resp.text)


async def test_student_thread_list_spans_experiments_unless_filtered(client, make_user):
    classroom_id, prof, student = await _classroom_with_student(client, make_user, "multi_list")
    await client.post(
        f"/api/classrooms/{classroom_id}/sessions/start",
        json={"experiment_ids": ["exp02", "exp04"]},
        headers=auth(prof),
    )
    for exp in ("exp02", "exp04"):
        assert (await _open_thread(client, student, classroom_id, exp)).status_code == 201

    everything = await client.get(f"/api/chat/threads?classroom_id={classroom_id}", headers=auth(student))
    assert {t["experiment_id"] for t in everything.json()["threads"]} == {"exp02", "exp04"}

    only_04 = await client.get(
        f"/api/chat/threads?classroom_id={classroom_id}&experiment_id=exp04", headers=auth(student)
    )
    assert [t["experiment_id"] for t in only_04.json()["threads"]] == ["exp04"]
