"""A new chat is a genuinely independent conversation.

Student -> Experiment -> Thread A / Thread B / ...: Thread A's history, concept
state, pending follow-up and walkthrough progress never reach Thread B, and the
model context for B is built from B's own messages only.

The browser-side race (a reply from chat A landing in chat B when "New chat" is
tapped mid-stream) is a frontend bug and is covered by a live browser check, not
by these backend tests; what these prove is that the server never mixes threads.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from backend.auth import session as session_cookie
from backend.config import reload_settings
from backend.models import ChatThread, WalkthroughProgress
from backend.tests.test_walkthrough_api import _classroom, _send, _student

pytestmark = pytest.mark.asyncio


def auth(token: str) -> dict[str, str]:
    return {"Cookie": f"{session_cookie.COOKIE_NAME}={token}"}


@pytest.fixture
def phone_llm(fake_llm, monkeypatch):
    """The model, with a distinct reply per call so any leak is detectable.
    Phone-only mode is the default and is left on."""
    counter = {"n": 0}

    def reply(user: str) -> str:
        counter["n"] += 1
        return f"Geometry optimization adjusts atom positions to lower the calculated energy. [REPLY-{counter['n']}]"

    fake_llm.reply = reply
    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: fake_llm)
    monkeypatch.setenv("LABTUTOR_ROUTER_ENABLED", "false")
    monkeypatch.delenv("LABTUTOR_WALKTHROUGH", raising=False)
    monkeypatch.delenv("LABTUTOR_PHONE_ONLY", raising=False)
    reload_settings()
    yield fake_llm
    monkeypatch.delenv("LABTUTOR_ROUTER_ENABLED", raising=False)
    reload_settings()


async def _new_thread(client, token, classroom_id) -> str:
    resp = await client.post(
        "/api/chat/threads",
        json={"classroom_id": classroom_id, "experiment_id": "exp07", "title": "New chat"},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _messages(client, token, thread_id) -> list[dict]:
    resp = await client.get(f"/api/chat/threads/{thread_id}/messages", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["messages"]


async def _setup(client, make_user, tag):
    classroom_id, code, _ = await _classroom(client, make_user, tag)
    user, token = await _student(client, make_user, code, f"s.{tag}@vitstudent.ac.in")
    return classroom_id, user, token


# ---- TEST 1 ---------------------------------------------------------------


async def test_1_a_new_thread_starts_with_zero_messages(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "iso1")
    a = await _new_thread(client, token, classroom_id)
    for q in ("Why do we optimize molecular geometry?", "Because lower energy?", "What is a basis set?"):
        await _send(client, token, classroom_id, q, a)
    assert len(await _messages(client, token, a)) == 6
    b = await _new_thread(client, token, classroom_id)
    assert b != a
    assert await _messages(client, token, b) == []


# ---- TEST 2 ---------------------------------------------------------------


async def test_2_a_message_in_b_leaves_a_unchanged(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "iso2")
    a = await _new_thread(client, token, classroom_id)
    await _send(client, token, classroom_id, "Why do we optimize molecular geometry?", a)
    before = await _messages(client, token, a)
    b = await _new_thread(client, token, classroom_id)
    await _send(client, token, classroom_id, "What is HOMO?", b)
    assert await _messages(client, token, a) == before
    assert len(await _messages(client, token, b)) == 2


# ---- TEST 3 ---------------------------------------------------------------


async def test_3_the_model_context_for_b_contains_nothing_from_a(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "iso3")
    a = await _new_thread(client, token, classroom_id)
    await _send(client, token, classroom_id, "Tell me about zebracorn optimization quirks in geometry", a)
    await _send(client, token, classroom_id, "because of the lower energy marker-zz", a)
    a_prompts = len(phone_llm.calls)
    b = await _new_thread(client, token, classroom_id)
    await _send(client, token, classroom_id, "What is HOMO?", b)
    b_prompts = "\n".join(c["system"] + "\n" + c["user"] for c in phone_llm.calls[a_prompts:])
    assert phone_llm.calls[a_prompts:], "thread B should have reached the model"
    for leaked in ("zebracorn", "marker-zz", "REPLY-1", "REPLY-2", "lower energy marker"):
        assert leaked not in b_prompts, leaked


# ---- TEST 4 ---------------------------------------------------------------


async def test_4_no_server_side_conversation_state_is_ever_sent_to_openai():
    """LabTutor builds each model request from its own thread's messages. It
    never uses previous_response_id or a Conversations API id, so a new thread
    cannot inherit one. Proved on the real request construction."""
    from backend.llm import client as llm_client
    from backend.tests.test_llm_budget import _Chunk, _Stream, _backend

    seen: list[dict] = []

    async def create(**kw):
        seen.append(kw)
        return _Stream([_Chunk("ok")])

    backend = _backend(create)
    for _ in range(2):  # two different "threads" through the same backend
        await backend._complete_streaming(system="s", user="u", max_tokens=10, queue=asyncio.Queue())
    assert len(seen) == 2
    for kwargs in seen:
        assert not ({"previous_response_id", "conversation", "conversation_id", "store"} & set(kwargs))
    import inspect
    import pathlib

    src = pathlib.Path(inspect.getsourcefile(llm_client)).read_text(encoding="utf-8")
    assert "previous_response_id" not in src and "conversations." not in src


# ---- TEST 5 ---------------------------------------------------------------


async def test_5_switching_a_b_a_shows_each_threads_own_history(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "iso5")
    a = await _new_thread(client, token, classroom_id)
    b = await _new_thread(client, token, classroom_id)
    await _send(client, token, classroom_id, "Why do we optimize molecular geometry?", a)
    await _send(client, token, classroom_id, "What is HOMO?", b)
    await _send(client, token, classroom_id, "What is a basis set?", b)
    a1, b1 = await _messages(client, token, a), await _messages(client, token, b)
    assert [m["content"] for m in a1 if m["author"] == "student"] == ["Why do we optimize molecular geometry?"]
    assert [m["content"] for m in b1 if m["author"] == "student"] == ["What is HOMO?", "What is a basis set?"]
    # A -> B -> A again: byte-identical
    assert await _messages(client, token, a) == a1
    assert await _messages(client, token, b) == b1
    assert not ({m["id"] for m in a1} & {m["id"] for m in b1})


# ---- TEST 6 ---------------------------------------------------------------


async def test_6_a_new_chat_made_mid_reply_never_receives_the_old_reply(client, make_user, phone_llm):
    classroom_id, _, token = await _setup(client, make_user, "iso6")
    a = await _new_thread(client, token, classroom_id)
    slow = phone_llm.complete

    async def slow_complete(**kwargs):
        await asyncio.sleep(0.3)
        return await slow(**kwargs)

    phone_llm.complete = slow_complete

    async def send_a():
        return await _send(client, token, classroom_id, "Why do we optimize molecular geometry?", a)

    async def new_chat_meanwhile():
        await asyncio.sleep(0.05)  # A's reply is still being generated
        b = await _new_thread(client, token, classroom_id)
        snapshots = [await _messages(client, token, b)]
        await asyncio.sleep(0.5)  # A's reply lands in the meantime
        snapshots.append(await _messages(client, token, b))
        return b, snapshots

    _, (b, snaps) = await asyncio.gather(send_a(), new_chat_meanwhile())
    assert snaps == [[], []]  # B stayed empty before and after A's reply arrived
    assert len(await _messages(client, token, a)) == 2  # and A got its own reply


# ---- TEST 7 ---------------------------------------------------------------


async def test_7_a_socratic_follow_up_in_a_does_not_exist_in_b(client, make_user, db, phone_llm):
    classroom_id, user, token = await _setup(client, make_user, "iso7")
    a = await _new_thread(client, token, classroom_id)
    out = await _send(client, token, classroom_id, "What is geometry optimization?", a)
    assert "Think about this" in out["message"]["content"]  # A now has a pending follow-up
    b = await _new_thread(client, token, classroom_id)
    rows = (await db.scalars(select(ChatThread).where(ChatThread.user_id == user.id))).all()
    state_b = next(t for t in rows if t.id == b).state or {}
    assert not state_b.get("pending") and not state_b.get("concepts")
    # B's first message is a different topic: it gets its own follow-up, not A's
    out_b = await _send(client, token, classroom_id, "What is HOMO?", b)
    rows = (
        await db.scalars(
            select(ChatThread).where(ChatThread.user_id == user.id).execution_options(populate_existing=True)
        )
    ).all()
    pending_b = next(t for t in rows if t.id == b).state["pending"]
    pending_a = next(t for t in rows if t.id == a).state["pending"]
    assert pending_b["concept_id"] == "homo" and pending_a["concept_id"] == "geometry_optimization"
    assert "optimi" not in out_b["message"]["content"].split("Think about this")[-1].lower()
    # no walkthrough/guided session was started in either thread by merely asking
    assert (await db.scalars(select(WalkthroughProgress).where(WalkthroughProgress.student_id == user.id))).all() == []
