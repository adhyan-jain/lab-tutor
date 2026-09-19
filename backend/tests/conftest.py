"""Shared fixtures.

Tests run against SQLite so the suite needs no services in CI. The
production target is Postgres; the ORM layer is the same either way, and
nothing under test depends on a Postgres-specific feature.

No test makes a real network call. `FakeBackend` stands in for the
inference backend, which also lets a test script exactly what a
compromised or misbehaving model would return -- the interesting case for
the injection tests.
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLDEN = REPO_ROOT / "golden_dataset"


def load_golden(*parts: str) -> dict:
    path = GOLDEN.joinpath(*parts)
    if not path.exists():
        pytest.skip(f"Golden dataset file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session", autouse=True)
def _test_environment(tmp_path_factory):
    """Point config at a scratch database and known domains."""
    import os

    db_path = tmp_path_factory.mktemp("db") / "labtutor_test.sqlite"
    os.environ.update(
        LABTUTOR_DATABASE_URL=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        LABTUTOR_SESSION_SECRET="test-secret-not-for-production",
        LABTUTOR_ENV="development",
        LABTUTOR_STUDENT_DOMAINS="vitstudent.ac.in",
        LABTUTOR_FACULTY_DOMAINS="vit.ac.in",
        LABTUTOR_LLM_BACKEND="hosted",
        LABTUTOR_LLM_BASE_URL="",
        LABTUTOR_LLM_API_KEY="",
        LABTUTOR_LLM_MODEL="",
        LABTUTOR_MANUAL_PDF=str(REPO_ROOT / "manual" / "IACHY102_manual.md"),
    )
    from backend.config import reload_settings

    reload_settings()
    yield


class FakeBackend:
    """Scriptable stand-in for an LLM backend."""

    name = "fake"

    def __init__(self, reply: str = "A determined result was described.") -> None:
        self.reply = reply
        self.calls: list[dict[str, str]] = []
        self.available = True

    async def complete(self, *, system: str, user: str, max_tokens: int | None = None):
        from backend.llm import telemetry
        from backend.llm.client import LLMReply, LLMUnavailable

        telemetry.record_call()
        self.calls.append({"system": system, "user": user})
        if not self.available:
            raise LLMUnavailable("fake backend is offline")
        reply = self.reply(user) if callable(self.reply) else self.reply
        return LLMReply(text=reply, backend=self.name, model="fake-model")

    async def health(self) -> bool:
        return self.available

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]["user"] if self.calls else ""

    @property
    def all_prompt_text(self) -> str:
        return "\n".join(c["system"] + "\n" + c["user"] for c in self.calls)


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a FakeBackend everywhere `get_backend` is used."""
    backend = FakeBackend()

    def _get_backend():
        return backend

    for module in (
        "backend.llm.client",
        "backend.llm",
        "backend.rag.phrasing",
        "backend.rag.qualitative",
        "backend.socratic_engine.chat",
        "backend.summaries.jobs",
        "backend.router.router",
    ):
        try:
            monkeypatch.setattr(f"{module}.get_backend", _get_backend, raising=False)
        except AttributeError:  # pragma: no cover
            pass
    return backend


@pytest_asyncio.fixture
async def db() -> AsyncIterator:
    """A fresh schema per test."""
    import asyncio

    from backend.db import create_all, dispose_engine, get_engine, get_sessionmaker
    from backend.models import Base

    await dispose_engine()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await create_all()

    async with get_sessionmaker()() as session:
        yield session

    # Drain any fire-and-forget background tasks a route may have started
    # (e.g. `enqueue_for_session`'s auto-triggered summary generation on
    # class-session end) before tearing down. On the shared test SQLite
    # file, an in-flight task from THIS test racing the NEXT test's
    # `DROP TABLE` reset produced real `database is locked` errors --
    # found via this session's own test run, not a hypothetical.
    from backend.summaries.jobs import _background_tasks

    pending = [t for t in _background_tasks if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    await dispose_engine()


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator:
    """ASGI client sharing the test's database session factory."""
    import httpx

    from backend.main import create_app

    app = create_app()
    # The app's lifespan would recreate tables; the `db` fixture already did.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest.fixture
def make_user(db):
    """Create a user row and return (user, session_cookie_value)."""
    from backend.auth import session as session_cookie
    from backend.auth.roles import role_for_email
    from backend.models import User

    async def _make(email: str, name: str = "Test User") -> tuple[User, str]:
        user = User(
            google_sub=f"sub-{email}",
            email=email,
            name=name,
            role=role_for_email(email),
        )
        db.add(user)
        await db.flush()
        await db.commit()
        return user, session_cookie.issue(user.id, user.email)

    return _make


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from backend import ratelimit

    ratelimit.reset_for_tests()
    yield
    ratelimit.reset_for_tests()
