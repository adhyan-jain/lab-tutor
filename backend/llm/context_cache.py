"""Versioned, native Vertex/Gemini context caching.

What is cached: the *stable* part of a prompt -- the system instruction and
the experiment's authoritative source material. Never anything that varies
per student or per message (history, question, session state).

How versioning works: a cache is looked up by a deterministic name
`labtutor-{scope}-{fingerprint16}` where the fingerprint is a SHA-256 over
everything that shapes the cached text (system prompt, source passages with
their provenance, model, location, policy version). Editing the manual
changes the text, so the old cache simply stops being selected and a new
one is created -- no manual invalidation, and no cache id lives in code,
the image or the environment.

Lifecycle: single-flight per fingerprint inside a process; list-before-
create plus "oldest create_time wins" across Cloud Run instances (no
Redis); creation never blocks a student's request (that request goes out
uncached, still as one generation); TTL with renew-on-use; caches from an
older source version expire by TTL rather than being deleted, so a rolling
deploy cannot pull a cache out from under an instance still using it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from google.genai import types as genai_types

log = logging.getLogger(__name__)

#: Bump when the *shape* of what is cached changes in a way the text hash
#: would not notice (e.g. a change to how the cache is consumed).
POLICY_VERSION = "1"
NAME_PREFIX = "labtutor"
#: A cache this close to expiry is treated as gone rather than risked.
EXPIRY_MARGIN_SECONDS = 60
#: After a failed create, don't try again for this long (avoid hammering).
CREATE_BACKOFF_SECONDS = 60


@dataclass(frozen=True)
class CacheRequest:
    """One prompt split into its stable and dynamic halves."""

    scope: str  # e.g. "exp07" -- a cache is only ever used for its own scope
    system: str  # stable system instruction
    context_text: str  # stable source material
    dynamic_user: str  # per-message content; never cached
    #: Ids/tiers/versions of the passages in `context_text`, hashed into the
    #: fingerprint alongside the text itself.
    provenance: str = ""

    def fingerprint(self, *, model: str, location: str) -> str:
        payload = json.dumps(
            {
                "policy": POLICY_VERSION,
                "scope": self.scope,
                "model": model,
                "location": location,
                "system": self.system,
                "context": self.context_text,
                "provenance": self.provenance,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def inline_user(self) -> str:
        """The same prompt without a cache: stable block first, dynamic last."""
        return f"{self.context_text}\n\n{self.dynamic_user}"


def cache_display_name(scope: str, fingerprint: str) -> str:
    return f"{NAME_PREFIX}-{scope}-{fingerprint[:16]}"


@dataclass
class _Entry:
    name: str
    expire_at: float  # epoch seconds
    renewing: bool = False


@dataclass
class ContextCacheManager:
    client: object  # google.genai.Client
    model: str
    location: str
    ttl_seconds: int
    _entries: dict[str, _Entry] = field(default_factory=dict)
    _inflight: dict[str, asyncio.Task] = field(default_factory=dict)
    _failed_until: dict[str, float] = field(default_factory=dict)
    #: Counters for tests and logs.
    creates: int = 0
    lists: int = 0

    # -- request path ------------------------------------------------------

    def fingerprint(self, req: CacheRequest) -> str:
        return req.fingerprint(model=self.model, location=self.location)

    async def resolve(self, req: CacheRequest) -> str | None:
        """The cache resource name if one is usable *right now*, else None.

        Never waits on the network. When no cache is known, creation is
        started in the background (once per fingerprint) and this request
        proceeds uncached.
        """
        fp = self.fingerprint(req)
        entry = self._entries.get(fp)
        now = time.time()
        if entry is not None:
            remaining = entry.expire_at - now
            if remaining > EXPIRY_MARGIN_SECONDS:
                if remaining < self.ttl_seconds / 2 and not entry.renewing:
                    entry.renewing = True
                    asyncio.create_task(self._renew(fp, entry))
                return entry.name
            self._entries.pop(fp, None)
            log.info("Context cache expired scope=%s ref=%s; will recreate", req.scope, fp[:8])

        if fp not in self._inflight and now >= self._failed_until.get(fp, 0.0):
            log.info("Context cache miss scope=%s ref=%s; creating in the background", req.scope, fp[:8])
            self._inflight[fp] = asyncio.create_task(self._create_guarded(req, fp))
        return None

    def invalidate(self, fp: str) -> None:
        """Forget a cache the server says is gone (expired/deleted)."""
        self._entries.pop(fp, None)

    # -- creation ----------------------------------------------------------

    async def _create_guarded(self, req: CacheRequest, fp: str) -> None:
        try:
            await self.ensure(req)
        except Exception as exc:  # never let a cache problem reach a student
            self._failed_until[fp] = time.time() + CREATE_BACKOFF_SECONDS
            log.warning(
                "Context cache unavailable for %s (%s); serving uncached",
                req.scope,
                type(exc).__name__,
            )
        finally:
            self._inflight.pop(fp, None)

    async def ensure(self, req: CacheRequest) -> str:
        """Find or create the cache for this fingerprint and remember it.

        Blocking variant, for warm-up and the CLI. Safe to call from many
        instances at once: whichever cache has the oldest create_time wins
        and a loser deletes its own duplicate.
        """
        fp = self.fingerprint(req)
        display = cache_display_name(req.scope, fp)
        found = await self._find(display)
        was_created = found is None
        if found is None:
            created = await self.client.aio.caches.create(  # type: ignore[attr-defined]
                model=self.model,
                config=genai_types.CreateCachedContentConfig(
                    display_name=display,
                    system_instruction=req.system,
                    contents=[
                        genai_types.Content(
                            role="user", parts=[genai_types.Part(text=req.context_text)]
                        )
                    ],
                    ttl=f"{self.ttl_seconds}s",
                ),
            )
            self.creates += 1
            found = await self._find(display) or created
            if found.name != created.name:
                try:
                    await self.client.aio.caches.delete(name=created.name)  # type: ignore[attr-defined]
                except Exception:  # best effort; it expires by TTL anyway
                    log.info("Could not delete duplicate context cache; it will expire by TTL")
        self._entries[fp] = _Entry(
            name=found.name, expire_at=_expire_epoch(found, self.ttl_seconds)
        )
        log.info(
            "Context cache ready scope=%s ref=%s event=%s",
            req.scope, fp[:8], "created" if was_created else "reused",
        )
        return found.name

    async def _find(self, display_name: str):
        """The oldest live cache with this display name for this model."""
        self.lists += 1
        now = time.time()
        matches = []
        pager = await self.client.aio.caches.list()  # type: ignore[attr-defined]
        async for item in pager:
            if item.display_name != display_name:
                continue
            if not str(item.model or "").endswith(self.model):
                continue
            if _expire_epoch(item, 0) - now <= EXPIRY_MARGIN_SECONDS:
                continue
            matches.append(item)
        if not matches:
            return None
        return min(matches, key=lambda c: c.create_time.timestamp() if c.create_time else 0.0)

    async def _renew(self, fp: str, entry: _Entry) -> None:
        try:
            updated = await self.client.aio.caches.update(  # type: ignore[attr-defined]
                name=entry.name,
                config=genai_types.UpdateCachedContentConfig(ttl=f"{self.ttl_seconds}s"),
            )
            entry.expire_at = _expire_epoch(updated, self.ttl_seconds)
        except Exception:
            log.info("Context cache renewal failed; it will be recreated when it lapses")
        finally:
            entry.renewing = False

    # -- maintenance (CLI) -------------------------------------------------

    async def list_caches(self) -> list:
        pager = await self.client.aio.caches.list()  # type: ignore[attr-defined]
        return [c async for c in pager if str(c.display_name or "").startswith(NAME_PREFIX + "-")]

    async def delete_stale(self, keep_display_names: set[str]) -> list[str]:
        deleted = []
        for item in await self.list_caches():
            if item.display_name not in keep_display_names:
                await self.client.aio.caches.delete(name=item.name)  # type: ignore[attr-defined]
                deleted.append(item.display_name)
        return deleted


def _expire_epoch(cached, default_ttl: int) -> float:
    expire = getattr(cached, "expire_time", None)
    if expire is not None:
        return expire.timestamp()
    return time.time() + default_ttl


# -- dev tooling ---------------------------------------------------------------
# python -m backend.llm.context_cache --list
# python -m backend.llm.context_cache --refresh [--delete-stale]


async def _cli(args: argparse.Namespace) -> int:
    from backend.config import get_settings
    from backend.llm.client import get_backend
    from backend.retrieval.stable_context import build_cache_request, cacheable_experiments

    backend = get_backend()
    backend = getattr(backend, "primary", backend)
    manager = getattr(backend, "cache_manager", None)
    if manager is None:
        print("Context caching is off or the backend is not Vertex (LABTUTOR_LLM_CONTEXT_CACHE).")
        return 1

    if args.list:
        for item in await manager.list_caches():
            print(item.display_name, item.expire_time)
        return 0

    keep: set[str] = set()
    for experiment_id in cacheable_experiments():
        req = build_cache_request(experiment_id)
        fp = manager.fingerprint(req)
        keep.add(cache_display_name(experiment_id, fp))
        await manager.ensure(req)
        print(f"{experiment_id}: ready (fingerprint {fp[:16]}, model {get_settings().vertex_model})")
    if args.delete_stale:
        for name in await manager.delete_stale(keep):
            print("deleted stale cache", name)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage LabTutor's Vertex context caches")
    parser.add_argument("--list", action="store_true", help="list LabTutor caches")
    parser.add_argument("--refresh", action="store_true", help="create/verify current caches")
    parser.add_argument(
        "--delete-stale",
        action="store_true",
        help="with --refresh: delete caches that do not match the current sources",
    )
    args = parser.parse_args()
    if not (args.list or args.refresh):
        parser.error("pass --list or --refresh")
    raise SystemExit(asyncio.run(_cli(args)))


if __name__ == "__main__":
    main()
