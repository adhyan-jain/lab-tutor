"""The SSE chat endpoint must not depend on the request-scoped DB session.

FastAPI closes a yield-dependency before a StreamingResponse body runs, and the
worker task outlives the handler. Reusing the request session there failed on
SQLite ("Cannot operate on a closed database") and held an idle pooled
connection per stream everywhere. The worker now owns its own session.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import session as session_cookie
from backend.db import get_engine, get_session
from backend.main import app
from backend.tests.test_walkthrough_api import _classroom, _student, counting_llm  # noqa: F401

pytestmark = pytest.mark.asyncio


def _events(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


class _PoisonedSession(AsyncSession):
    """A request session that blows up if used after its dependency exited."""

    closed_by_dependency = False

    async def execute(self, *args, **kwargs):
        if self.closed_by_dependency:
            raise RuntimeError("request-scoped session reused after the dependency closed it")
        return await super().execute(*args, **kwargs)


async def test_stream_endpoint_works_after_the_request_session_is_closed(client, make_user, counting_llm):  # noqa: F811
    classroom_id, code, _ = await _classroom(client, make_user, "stream")
    _, token = await _student(client, make_user, code, "s1.stream@vitstudent.ac.in")

    async def poisoned():
        session = _PoisonedSession(get_engine(), expire_on_commit=False)
        try:
            yield session
        finally:
            session.closed_by_dependency = True
            await session.close()

    app.dependency_overrides[get_session] = poisoned
    try:
        resp = await client.post(
            "/api/chat/messages/stream",
            json={"classroom_id": classroom_id, "experiment_id": "exp07", "message": "guide me through this experiment"},
            headers={"Cookie": f"{session_cookie.COOKIE_NAME}={token}"},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 200
    events = _events(resp.text)
    assert events[-1]["type"] == "done", events[-1]
    assert events[-1]["message"]["metadata"]["type"] == "walkthrough"
    assert "quick guess" in events[-1]["message"]["content"].lower()


async def test_stream_endpoint_reports_errors_as_an_event_not_a_crash(client, make_user, counting_llm):  # noqa: F811
    _, token = await make_user("s2.stream@vitstudent.ac.in")
    resp = await client.post(
        "/api/chat/messages/stream",
        json={"classroom_id": "does-not-exist", "experiment_id": "exp07", "message": "hello"},
        headers={"Cookie": f"{session_cookie.COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 200
    assert _events(resp.text)[-1]["type"] == "error"
