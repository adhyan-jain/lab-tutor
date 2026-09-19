"""The stable (cacheable) half of an experiment's answer prompt.

For the whole-workflow experiments (Exp7/8) the complete source material is
small enough to hand to the model every time. Building it here, in one
deterministic order, gives both the native Vertex context cache and the
uncached fallback the *same* text, and puts it first in the prompt so the
part that varies per message is always last.

Nothing student-specific ever enters this text: it is built from the
retrieval index alone.
"""

from __future__ import annotations

import logging

from backend.config import get_settings
from backend.llm.context_cache import CacheRequest
from backend.retrieval.chunks import Chunk
from backend.sources.tiers import SourceTier

log = logging.getLogger(__name__)

TIER_TAGS = {
    SourceTier.OFFICIAL_MANUAL: "lab manual",
    SourceTier.OFFICIAL_SUPPLEMENTARY: "official course material",
    SourceTier.CURATED_ADJACENT: "background explainer, not the manual",
}

_OFFICIAL = (SourceTier.OFFICIAL_MANUAL, SourceTier.OFFICIAL_SUPPLEMENTARY)


def cacheable_experiments() -> tuple[str, ...]:
    """Experiments whose stable context may be cached (env-configured)."""
    raw = get_settings().llm_context_cache_scopes
    return tuple(sorted({s.strip() for s in raw.split(",") if s.strip()}))


def experiment_chunks(experiment_id: str, index) -> list[Chunk]:
    """Official material in document order, then background, in index order.

    Only chunks attributed to exactly this experiment: an Exp7 prompt can
    never contain (or be cached with) Exp8's material.
    """
    mine = [c for c in index.chunks if c.experiment_id == experiment_id]
    official = [c for c in mine if c.tier in _OFFICIAL]
    background = [c for c in mine if c.tier is SourceTier.CURATED_ADJACENT]
    return official + background


def format_passages(chunks: list[Chunk]) -> str:
    block = "\n---\n".join(
        f"[{i + 1}] ({TIER_TAGS.get(c.tier, 'source')}) {c.text}" for i, c in enumerate(chunks)
    )
    return (
        "RETRIEVED PASSAGES (the complete source material for this experiment, "
        "in document order; each is tagged with where it comes from):\n"
        f"<<<PASSAGES\n{block}\nPASSAGES>>>"
    )


def provenance_of(chunks: list[Chunk]) -> str:
    return "\n".join(
        f"{c.chunk_id}|{c.document_id}|{c.tier.value}|{c.source_version}" for c in chunks
    )


def build_cache_request(
    experiment_id: str,
    *,
    dynamic_user: str = "",
    index=None,
    system: str | None = None,
) -> CacheRequest:
    if index is None:
        from backend.retrieval.index import get_index

        index = get_index()
    if system is None:
        from backend.retrieval.pipeline import SYSTEM_PROMPT

        system = SYSTEM_PROMPT
    chunks = experiment_chunks(experiment_id, index)
    return CacheRequest(
        scope=experiment_id,
        system=system,
        context_text=format_passages(chunks),
        dynamic_user=dynamic_user,
        provenance=provenance_of(chunks),
    )


async def warm_up_context_caches() -> None:
    """Create/verify the caches at startup, off the request path."""
    from backend.llm.client import get_backend

    if not get_settings().llm_context_cache_enabled:
        return
    backend = get_backend()
    backend = getattr(backend, "primary", backend)
    manager = getattr(backend, "cache_manager", None)
    if manager is None:
        return
    for experiment_id in cacheable_experiments():
        try:
            await manager.ensure(build_cache_request(experiment_id))
        except Exception as exc:
            log.warning(
                "Context cache warm-up failed for %s (%s)", experiment_id, type(exc).__name__
            )
