"""Environment-driven configuration.

Every deployment-varying value lives here and is read from the
environment. Nothing in this module hardcodes a domain, a provider, or
a credential -- see `.env.example` for the full key list.
"""

from __future__ import annotations

import functools
from typing import Literal

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_domains(raw: str | list[str]) -> list[str]:
    """Normalise a comma-separated domain list to lowercase, no leading '@'."""
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)
    return [p.strip().lower().lstrip("@") for p in parts if p and p.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- core ---
    public_url: str = Field("http://localhost:3000", alias="LABTUTOR_PUBLIC_URL")
    session_secret: str = Field("dev-insecure-secret", alias="LABTUTOR_SESSION_SECRET")
    env: Literal["development", "production"] = Field("development", alias="LABTUTOR_ENV")

    # --- database ---
    postgres_user: str = Field("labtutor", alias="POSTGRES_USER")
    postgres_password: str = Field("labtutor", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("labtutor", alias="POSTGRES_DB")
    postgres_host: str = Field("localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    # Overrides the assembled Postgres URL entirely. Tests use sqlite here.
    database_url_override: str | None = Field(None, alias="LABTUTOR_DATABASE_URL")

    # --- role domains ---
    # Configurable so an additional/corrected domain never requires a code
    # change. Role determination reads ONLY these (backend/auth/roles.py).
    # NoDecode: these arrive as a plain comma-separated string, not JSON, so
    # pydantic-settings must hand the raw value to the validator below
    # rather than trying to parse it as a list literal first.
    student_domains: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["vitstudent.ac.in"], alias="LABTUTOR_STUDENT_DOMAINS"
    )
    faculty_domains: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["vit.ac.in"], alias="LABTUTOR_FACULTY_DOMAINS"
    )
    # Platform administrator allowlist, checked BEFORE domain-role
    # resolution (backend/auth/roles.py). Admin is a platform identity, not
    # a classroom membership -- it does not require joining a classroom.
    admin_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["adhyanjain2006@gmail.com"], alias="LABTUTOR_ADMIN_EMAILS"
    )

    # --- oauth ---
    google_client_id: str = Field("", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field("", alias="GOOGLE_CLIENT_SECRET")

    # --- database pool ---
    # Per-process pool size. A single Docker Compose container running
    # multiple uvicorn workers -- or several Cloud Run instances -- each
    # get their OWN pool, since `db.py`'s engine is a per-process global,
    # so the real ceiling is workers/instances multiplied by these two.
    # Defaults match the pre-Cloud-Run sizing; a smaller-tier Cloud SQL
    # deployment overrides both via env vars (see infra/deployment docs).
    db_pool_size: int = Field(20, alias="LABTUTOR_DB_POOL_SIZE")
    db_max_overflow: int = Field(10, alias="LABTUTOR_DB_MAX_OVERFLOW")

    # --- llm ---
    llm_backend: Literal["hosted", "ollama", "vertex"] = Field(
        "hosted", alias="LABTUTOR_LLM_BACKEND"
    )
    llm_base_url: str = Field("", alias="LABTUTOR_LLM_BASE_URL")
    llm_api_key: str = Field("", alias="LABTUTOR_LLM_API_KEY")
    llm_model: str = Field("", alias="LABTUTOR_LLM_MODEL")
    llm_timeout_seconds: float = Field(30.0, alias="LABTUTOR_LLM_TIMEOUT_SECONDS")
    llm_max_tokens: int = Field(1200, alias="LABTUTOR_LLM_MAX_TOKENS")
    llm_temperature: float = Field(0.7, alias="LABTUTOR_LLM_TEMPERATURE")
    #: Caps how many LLM calls run at once, across every caller
    #: (Socratic chat, diagnostic phrasing, the Exp8 qualitative note).
    #: Found missing this session: nothing previously bounded this, so
    #: ~70 concurrent students each hitting a slow/degrading provider
    #: could put ~70 simultaneous requests in flight, each independently
    #: waiting out the full timeout -- compare `summaries/jobs.py`,
    #: which already bounds its own batch fan-out with a semaphore for
    #: the same reason.
    #: This is a PER-PROCESS limit, not a project-wide one: with Cloud Run
    #: `maxScale` N the real ceiling is N x this. The project's Vertex
    #: quota (a per-minute request budget) is enforced by Google, not
    #: here -- this only stops one instance from opening unbounded
    #: connections and lets excess work fail over to the extractive
    #: fallback instead of queueing for minutes.
    llm_max_concurrency: int = Field(20, alias="LABTUTOR_LLM_MAX_CONCURRENCY")
    #: How long a request may wait for a concurrency slot before it gives
    #: up on the model and takes the extractive fallback.
    llm_queue_timeout_seconds: float = Field(10.0, alias="LABTUTOR_LLM_QUEUE_TIMEOUT_SECONDS")
    #: The single retry owner is `VertexBackend._generate`. Retries only on
    #: 429/5xx, exponential backoff with jitter, bounded by both an attempt
    #: count and a wall-clock budget so a student never waits unbounded.
    llm_max_attempts: int = Field(3, alias="LABTUTOR_LLM_MAX_ATTEMPTS")
    llm_retry_initial_seconds: float = Field(1.0, alias="LABTUTOR_LLM_RETRY_INITIAL_SECONDS")
    llm_retry_max_seconds: float = Field(8.0, alias="LABTUTOR_LLM_RETRY_MAX_SECONDS")
    llm_retry_budget_seconds: float = Field(25.0, alias="LABTUTOR_LLM_RETRY_BUDGET_SECONDS")
    #: Gemini 2.5 "thinking" token budget per request. -1 = model default
    #: (dynamic); 0 = off; N = at most N. Hidden reasoning is billed and adds
    #: seconds of wait that the visible token count does not show.
    llm_thinking_budget: int = Field(-1, alias="LABTUTOR_LLM_THINKING_BUDGET")
    #: Native Vertex context caching of an experiment's stable prompt
    #: (system prompt + source material). Off unless enabled: dev usually
    #: doesn't want cache objects created in a shared project. Versioning is
    #: automatic (content fingerprint); see backend/llm/context_cache.py.
    llm_context_cache_enabled: bool = Field(False, alias="LABTUTOR_LLM_CONTEXT_CACHE")
    #: Comma-separated experiment ids whose stable context may be cached.
    llm_context_cache_scopes: str = Field("exp07", alias="LABTUTOR_LLM_CONTEXT_CACHE_SCOPES")
    #: Long enough to cover a class session (renewed on use), never indefinite.
    llm_context_cache_ttl_seconds: int = Field(10800, alias="LABTUTOR_LLM_CONTEXT_CACHE_TTL_SECONDS")
    ollama_base_url: str = Field("http://localhost:11434", alias="LABTUTOR_OLLAMA_BASE_URL")
    ollama_model: str = Field("qwen2.5:7b", alias="LABTUTOR_OLLAMA_MODEL")
    #: Some local models (e.g. qwen3) default to an internal "thinking"
    #: pass before the visible reply. Measured during this session's
    #: evaluation run: with `llm_max_tokens` at its default (400) that
    #: reasoning pass alone can consume the whole budget, leaving zero
    #: tokens for the actual reply -- chat.py then silently falls back to
    #: the fixed hint template (empty LLM text is treated as unavailable).
    #: Default off for reliability; a deployment that wants the model's
    #: reasoning (and raises llm_max_tokens accordingly) can opt in.
    ollama_think: bool = Field(False, alias="LABTUTOR_OLLAMA_THINK")
    llm_auto_fallback: bool = Field(True, alias="LABTUTOR_LLM_AUTO_FALLBACK")

    # Vertex AI Gemini (the pilot's production backend). Authenticates via
    # Application Default Credentials -- the Cloud Run service account's
    # identity -- never an API key. `vertex_project` left blank lets the
    # client fall back to ADC's own default project when unset (local
    # dev); a real deployment sets it explicitly.
    vertex_project: str = Field("", alias="LABTUTOR_VERTEX_PROJECT")
    vertex_location: str = Field("asia-south1", alias="LABTUTOR_VERTEX_LOCATION")
    vertex_model: str = Field("gemini-2.5-flash", alias="LABTUTOR_VERTEX_MODEL")

    # --- conversational router ---
    # A model-driven routing decision layered in front of the deterministic
    # QA/Socratic/diagnostic dispatch in chat_routes.py -- see
    # backend/router/. Purely additive: any failure (unavailable backend,
    # malformed output, low confidence) falls back to the pre-existing
    # keyword-based dispatch unchanged, so this is a zero-risk kill switch.
    #: Off by default: a message must cost at most one generation, and the
    #: router is a second one. Interaction mode (Q&A / Socratic /
    #: diagnostic / clarification) is picked by deterministic code and
    #: stated to the single answering call instead.
    router_enabled: bool = Field(False, alias="LABTUTOR_ROUTER_ENABLED")
    #: Below this, a router decision is treated the same as a router
    #: failure -- "not sure" and "failed" get identical, safe handling.
    router_min_confidence: float = Field(0.4, alias="LABTUTOR_ROUTER_MIN_CONFIDENCE")
    #: Deliberately much shorter than `llm_timeout_seconds`. Found live: a
    #: contended/slow backend previously let the router's own attempt run
    #: the full domain-call timeout before failing, then the deterministic
    #: fallback made its own full-length call on top of that -- up to
    #: double the per-turn latency in exactly the degraded-backend case
    #: this system is supposed to degrade gracefully from. Routing is an
    #: enhancement, not core functionality, so it should fail fast and
    #: hand off to the deterministic dispatch rather than eat into the
    #: same budget as the answer itself.
    router_timeout_seconds: float = Field(8.0, alias="LABTUTOR_ROUTER_TIMEOUT_SECONDS")

    # --- retrieval ---
    # Points at the markdown transcription (manual/IACHY102_manual.md), not
    # a PDF binary -- see manual/README.md. `build_index` in
    # backend/rag/retrieval.py dispatches on the file extension.
    manual_pdf: str = Field("manual/IACHY102_manual.md", alias="LABTUTOR_MANUAL_PDF")

    # --- rate limits ---
    ratelimit_socratic_per_minute: int = Field(12, alias="LABTUTOR_RATELIMIT_SOCRATIC_PER_MINUTE")
    ratelimit_submit_per_hour: int = Field(30, alias="LABTUTOR_RATELIMIT_SUBMIT_PER_HOUR")
    ratelimit_qa_per_minute: int = Field(12, alias="LABTUTOR_RATELIMIT_QA_PER_MINUTE")

    # --- summaries ---
    summary_workers: int = Field(4, alias="LABTUTOR_SUMMARY_WORKERS")

    @field_validator("student_domains", "faculty_domains", mode="before")
    @classmethod
    def _norm_domains(cls, v):
        return _split_domains(v)

    @field_validator("admin_emails", mode="before")
    @classmethod
    def _norm_admin_emails(cls, v):
        raw = v.split(",") if isinstance(v, str) else list(v)
        return [p.strip().lower() for p in raw if p and p.strip()]

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cookie_secure(self) -> bool:
        return self.env == "production"


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear the settings cache and every settings-derived cache that does
    not automatically follow it.

    Found during this session's evaluation-script work: `rag.retrieval`'s
    manual index and `llm.client`'s backend instance each cache
    themselves behind their own module-level global, populated from
    `get_settings()` at first use and invalidated only by their own
    separately-named reset function (`reset_index_cache`,
    `reset_backend_cache`). A caller who changes `LABTUTOR_MANUAL_PDF` or
    `LABTUTOR_LLM_BACKEND` and calls only `reload_settings()` -- the
    obviously-named thing to call -- would silently keep serving the
    stale index/backend built under the old settings. This script
    happened not to hit that (it set env vars before either subsystem
    had been touched), but it is a real footgun for the next caller.
    `db.get_engine`'s cache is deliberately NOT cascaded here: disposing
    it is async (`db.dispose_engine`) and cannot run from this sync
    function without an event loop; callers that change
    `LABTUTOR_DATABASE_URL` at runtime must still call that themselves
    (as `backend/tests/conftest.py`'s `db` fixture already does).
    """
    get_settings.cache_clear()
    settings = get_settings()

    from backend.rag.retrieval import reset_index_cache

    reset_index_cache()

    from backend.llm.client import reset_backend_cache, reset_concurrency_limit

    reset_backend_cache()
    reset_concurrency_limit()

    return settings
