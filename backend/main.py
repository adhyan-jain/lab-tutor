"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.answer_gate import assert_gate_invariant
from backend.api import ROUTERS
from backend.config import get_settings
from backend.db import create_all, dispose_engine
from backend.tier1_compute.experiments import all_plugins, ready_plugins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("labtutor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Fail fast if the answer-gate guarantee has been weakened. Better to
    # refuse to start than to serve students with a gate that no longer
    # holds.
    assert_gate_invariant()

    if settings.env == "production" and settings.session_secret == "dev-insecure-secret":
        raise RuntimeError(
            "LABTUTOR_SESSION_SECRET is still the development default. "
            "Generate one with: openssl rand -hex 32"
        )

    if settings.env == "production":
        # Production schema is owned by Alembic (backend/migrations/),
        # not by this call: `create_all()` would build the tables
        # directly on a fresh database without ever stamping
        # `alembic_version`, so the very next `alembic upgrade head`
        # deploy fails with "table already exists." Run migrations as a
        # deploy step (`alembic upgrade head`) before starting the app.
        log.info("Production startup: schema is managed by Alembic migrations, not create_all().")
    else:
        # Dev/test convenience: build the schema straight from the
        # current models so a fresh checkout runs with zero setup steps.
        await create_all()

    total = len(all_plugins())
    ready = len(ready_plugins())
    from backend.llm.client import get_backend

    active_backend = get_backend().name
    log.info(
        "LabTutor starting: %d experiments registered, %d ready, LLM backend=%s",
        total, ready, active_backend,
    )
    if ready < total:
        log.warning(
            "%d experiment(s) are not usable yet -- their formulas have not been "
            "transcribed from the IACHY102 manual. Submissions against them will "
            "escalate to review rather than produce a diagnosis.",
            total - ready,
        )

    # Create/verify the native context caches off the request path so the
    # first student rarely pays for it. Never blocks startup; a failure is
    # logged and requests simply go out uncached.
    warm_up = None
    if settings.llm_context_cache_enabled:
        from backend.retrieval.stable_context import warm_up_context_caches

        warm_up = asyncio.create_task(warm_up_context_caches())

    yield
    if warm_up is not None and not warm_up.done():
        warm_up.cancel()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LabTutor",
        description=(
            "Chemistry lab learning support for IACHY102. Diagnosis is "
            "deterministic; language models only phrase what has already been "
            "decided."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()
