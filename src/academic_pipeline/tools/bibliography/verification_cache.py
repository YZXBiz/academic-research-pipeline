"""SQLite verification cache for citation resolvers (cross-run speed)."""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

from academic_pipeline.models.citation_verification import ResolverOutcome, ResolverStatus


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from academic_pipeline.models.citation_verification import CitedWork

    Resolver = Callable[[CitedWork], Awaitable[ResolverOutcome]]


DEFAULT_TTL = 90 * 24 * 3600


class VerificationCache:
    """Local SQLite store of resolver outcomes keyed by (resolver, work identity)."""

    def __init__(self, path: str | Path) -> None:
        """Open (or create) the cache database at path."""
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, outcome TEXT NOT NULL, ts REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str, *, ttl: float = DEFAULT_TTL, now: float | None = None) -> ResolverOutcome | None:
        """Return a non-expired cached outcome, or None."""
        row = self._conn.execute("SELECT outcome, ts FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        outcome_json, ts = row
        if (now if now is not None else time.time()) - ts > ttl:
            return None
        return ResolverOutcome.model_validate_json(outcome_json)

    def put(self, key: str, outcome: ResolverOutcome, *, now: float | None = None) -> None:
        """Store an outcome."""
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, outcome, ts) VALUES (?, ?, ?)",
            (key, outcome.model_dump_json(), now if now is not None else time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


def _cache_key(name: str, work: CitedWork) -> str:
    return f"{name}::{work.doi or ''}::{work.arxiv_id or ''}::{work.isbn or ''}::{work.title}"


def cached_resolver(name: str, resolver: Resolver, cache: VerificationCache, *, ttl: float = DEFAULT_TTL) -> Resolver:
    """Wrap a resolver so MATCHED/UNMATCHED outcomes are cached; transient ones never are."""

    async def _r(work: CitedWork) -> ResolverOutcome:
        key = _cache_key(name, work)
        hit = cache.get(key, ttl=ttl)
        if hit is not None:
            return hit
        outcome = await resolver(work)
        if outcome.status in (ResolverStatus.MATCHED, ResolverStatus.UNMATCHED):
            cache.put(key, outcome)
        return outcome

    return _r


def cached_resolvers(
    resolvers: Mapping[str, Resolver], cache: VerificationCache, *, ttl: float = DEFAULT_TTL
) -> dict[str, Resolver]:
    """Wrap every resolver with the cache."""
    return {name: cached_resolver(name, resolver, cache, ttl=ttl) for name, resolver in resolvers.items()}
