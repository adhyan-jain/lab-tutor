"""Hybrid retrieval with metadata filtering.

Implements three stages of the brief's nine-stage pipeline (§6):
**hybrid retrieval**, **source filtering**, and half of **reranking**
(the rest lives in `rerank.py`, which is a separate, business-rule-driven
pass rather than a scoring detail of the index).

## Why lexical + a local "semantic" layer, not an embeddings API

The corpus is one small, vocabulary-heavy domain document. The
project's existing retrieval module already made this call for the same
corpus and gave the reasoning (`backend/rag/retrieval.py`): no second
provider, no API key, no network hop, no cold-start cost for a machine
serving a lab section.

This module keeps that reasoning but adds the second half of "hybrid":
a **local TF-IDF cosine layer**, computed from the same index with no
external call. It is not a trained embedding model and this docstring
does not pretend otherwise -- it catches synonym-free semantic overlap
that pure term-matching BM25 can miss (shared vocabulary in a different
order, e.g. "output file location" vs "where does the output go"),
without adding a dependency. `backend/llm/client.py` already has a
provider-swappable interface; wiring a real embedding provider behind
`SemanticLayer` is a contained Phase 2 change (see
`docs/final_audit.md` item 4) that does not touch this module's
public surface.

## Source filtering, structurally

`search()` takes `experiment_id` and `usage`. A chunk is a candidate only
if:

* its tier is permitted for `usage` (`sources.tiers.permitted_tiers_for`)
  -- this is what stops a Tier C explainer from answering a direct
  procedural question; and
* its `experiment_id` is `None` (general material) or equal to the
  requested one -- this is what stops Experiment 3 colorimetry chunks
  from outscoring Experiment 7 orbital chunks merely for sharing the
  word "concentration" (brief §6's own example).

Both checks happen before scoring, not after, so a wrong-experiment
chunk cannot win on relevance and then be filtered out too late to
matter for `k`.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass

from backend.retrieval.chunks import Chunk
from backend.sources.tiers import SourceTier, Usage, permitted_tiers_for

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the
    to was were will with this these those which what when where how you your""".split()
)


def _tokenise(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    lexical_score: float = 0.0
    semantic_score: float = 0.0


class _Bm25:
    K1 = 1.5
    B = 0.75

    def __init__(self, docs_tokens: list[list[str]]) -> None:
        self._tokens = docs_tokens
        self._lengths = [len(t) for t in docs_tokens]
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._tf = [Counter(t) for t in docs_tokens]
        self._df: Counter[str] = Counter()
        for tokens in docs_tokens:
            self._df.update(set(tokens))
        self._n = len(docs_tokens)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))

    def score(self, index: int, query_terms: list[str]) -> float:
        length = self._lengths[index] or 1
        total = 0.0
        for term in query_terms:
            tf = self._tf[index].get(term, 0)
            if tf == 0:
                continue
            denom = tf + self.K1 * (1 - self.B + self.B * length / (self._avg_len or 1))
            total += self._idf(term) * (tf * (self.K1 + 1)) / denom
        return total

    def max_possible(self, query_terms: list[str]) -> float:
        """Rough upper bound, for normalising scores into [0, 1]."""
        return sum(self._idf(t) * (self.K1 + 1) for t in set(query_terms)) or 1.0


class _TfidfCosine:
    """The local "semantic" layer. See module docstring for what this is
    and is not."""

    def __init__(self, docs_tokens: list[list[str]]) -> None:
        self._df: Counter[str] = Counter()
        for tokens in docs_tokens:
            self._df.update(set(tokens))
        self._n = len(docs_tokens)
        self._vectors = [self._vectorise(t) for t in docs_tokens]

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1.0 + self._n / df)

    def _vectorise(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        vec = {t: (1 + math.log(c)) * self._idf(t) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def score(self, index: int, query_terms: list[str]) -> float:
        query_vec = self._vectorise(query_terms)
        doc_vec = self._vectors[index]
        if not query_vec or not doc_vec:
            return 0.0
        shared = set(query_vec) & set(doc_vec)
        return sum(query_vec[t] * doc_vec[t] for t in shared)


class HybridIndex:
    """Lexical (BM25) + local semantic (TF-IDF cosine) over a chunk set."""

    #: Relative weight of the lexical vs. semantic signal in the combined
    #: score. Lexical dominates because exact terminology ("HOMO",
    #: "6-31G", "Ni2+") is usually decisive in this domain; semantic
    #: overlap is the tie-breaker for paraphrased questions.
    LEXICAL_WEIGHT = 0.65
    SEMANTIC_WEIGHT = 0.35

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._tokens = [_tokenise(c.text) for c in chunks]
        self._bm25 = _Bm25(self._tokens)
        self._tfidf = _TfidfCosine(self._tokens)

    def __len__(self) -> int:
        return len(self.chunks)

    def search(
        self,
        query: str,
        *,
        usage: Usage,
        experiment_id: str | None = None,
        k: int = 5,
        allow_tiers: tuple[SourceTier, ...] | None = None,
    ) -> list[ScoredChunk]:
        """Top-k chunks for `query`, filtered before scoring.

        `allow_tiers` overrides `permitted_tiers_for(usage)` for callers
        that need a narrower set (e.g. Socratic mode excluding
        professor-facing material even where `usage` would otherwise
        permit it). Passing it never widens the permitted set.
        """
        query_terms = _tokenise(query)
        if not query_terms or not self.chunks:
            return []

        permitted = set(permitted_tiers_for(usage))
        if allow_tiers is not None:
            permitted &= set(allow_tiers)

        candidates = [
            i
            for i, chunk in enumerate(self.chunks)
            if chunk.tier in permitted
            and (chunk.experiment_id is None or chunk.experiment_id == experiment_id)
        ]
        if experiment_id is None:
            # No experiment context: do not silently include chunks
            # attributed to a *specific* experiment, which would let one
            # experiment's material answer an unrouted general question
            # by sheer corpus size. General (unattributed) chunks only.
            candidates = [i for i in candidates if self.chunks[i].experiment_id is None]

        if not candidates:
            return []

        max_lex = self._bm25.max_possible(query_terms)
        scored: list[ScoredChunk] = []
        for i in candidates:
            lex = self._bm25.score(i, query_terms) / max_lex
            sem = self._tfidf.score(i, query_terms)
            if lex <= 0 and sem <= 0:
                continue
            combined = self.LEXICAL_WEIGHT * min(lex, 1.0) + self.SEMANTIC_WEIGHT * sem
            scored.append(
                ScoredChunk(chunk=self.chunks[i], score=combined, lexical_score=lex, semantic_score=sem)
            )

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]


_index: HybridIndex | None = None
_index_lock = threading.Lock()


def build_index_from_chunks(chunks: list[Chunk]) -> HybridIndex:
    return HybridIndex(chunks)


def get_index() -> HybridIndex:
    """The process-wide index, built from everything `ingest_all` produces.

    Cached the same way the legacy `backend/rag/retrieval.py` caches its
    index, for the same reason: rebuilding a BM25/TF-IDF index per
    request is wasted work for a corpus that only changes when someone
    re-ingests.
    """
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                from backend.retrieval.ingest import ingest_all

                chunks: list[Chunk] = []
                for report in ingest_all():
                    chunks.extend(report.chunks)
                _index = HybridIndex(chunks)
    return _index


def reset_index_cache() -> None:
    global _index
    with _index_lock:
        _index = None
