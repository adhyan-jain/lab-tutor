"""Health endpoints for the backend and for LLM-backend connectivity."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from backend.config import get_settings
from backend.db import get_session
from backend.llm import get_backend
from backend.tier1_compute.experiments import all_plugins, ready_plugins

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    """Liveness plus database reachability.

    Deliberately does not call the LLM backend: a paid inference provider
    should not be probed by every load-balancer health check. Use
    `/health/llm` for that.
    """
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    plugins = all_plugins()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
        "experiments_registered": len(plugins),
        "experiments_ready": len(ready_plugins()),
    }


@router.get("/health/llm")
async def health_llm(response: Response) -> dict:
    """Inference-backend connectivity.

    Separate from `/health` so an inference outage does not make the
    container look dead and get restarted -- the app degrades to
    deterministic templates and keeps working.
    """
    settings = get_settings()
    backend = get_backend()
    ok = await backend.health()
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if ok else "unreachable",
        # The provider actually in use -- "openai" when GPT=true, whatever
        # LABTUTOR_LLM_BACKEND (or its fallback wrapper) says otherwise.
        "configured_backend": backend.name,
        "auto_fallback": settings.llm_auto_fallback,
        "degraded_behaviour": (
            "Diagnoses and hints are still produced from deterministic "
            "templates; only the natural-language wording is lost."
        ),
    }
