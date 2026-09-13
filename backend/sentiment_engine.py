"""Deterministic news-sentiment scoring from stored embeddings.

Design intent: the old backend/agents.py pipeline asked an LLM to read
headlines and decide "bullish or bearish". That call is slow, costs money on
every request, and is non-deterministic (the same input can produce a
different verdict twice). This module replaces that judgment call with
linear algebra over embeddings we already compute during news harvesting
(see vector_pipeline.py): cosine similarity between a news chunk's embedding
and a small set of pre-embedded "bullish" / "bearish" reference phrases.

No network call and no LLM inference happens here. The only network/API
cost in the whole sentiment path is the one-time embedding of the news
article itself (already paid for by news_harvester.py) and the one-time,
offline embedding of the reference anchor phrases
(see scripts/generate_sentiment_anchors.py). Scoring at request time is a
handful of dot products.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ANCHORS_PATH = Path(__file__).parent / "sentiment_anchors.json"

# How quickly older news stops mattering. A 3-day half-life means a headline
# from 3 days ago counts half as much as one from today, and one from 6 days
# ago counts a quarter as much.
DEFAULT_HALF_LIFE_DAYS = 3.0


@dataclass(frozen=True)
class SentimentAnchors:
    """Pre-embedded reference vectors for 'bullish' and 'bearish' language."""

    bullish_centroid: list[float]
    bearish_centroid: list[float]
    model: str
    bullish_phrases: list[str]
    bearish_phrases: list[str]
    generated_at: str


@dataclass(frozen=True)
class NewsChunk:
    """One embedded, stored news chunk pulled back from PostgreSQL."""

    headline: str
    url: str | None
    published_at: datetime | None
    embedding: list[float]


@dataclass(frozen=True)
class ChunkScore:
    chunk: NewsChunk
    score: float
    weight: float


@dataclass(frozen=True)
class SentimentAssessment:
    """Result of scoring a ticker's recent news against the anchors."""

    score: float | None
    chunk_count: int
    top_chunks: list[ChunkScore]

    @property
    def available(self) -> bool:
        return self.score is not None and self.chunk_count > 0


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"Embedding dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_anchors(path: Path | None = None) -> SentimentAnchors | None:
    """Load pre-computed anchor centroids.

    Returns None (not an exception) when the file hasn't been generated yet
    -- callers treat "no anchors" exactly like "no news": sentiment is simply
    not evaluated for this run, same as any other missing-data case.
    """
    target = path or DEFAULT_ANCHORS_PATH
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    return SentimentAnchors(
        bullish_centroid=payload["bullish_centroid"],
        bearish_centroid=payload["bearish_centroid"],
        model=payload["model"],
        bullish_phrases=payload["bullish_phrases"],
        bearish_phrases=payload["bearish_phrases"],
        generated_at=payload["generated_at"],
    )


def score_embedding(embedding: list[float], anchors: SentimentAnchors) -> float:
    """Score one embedding in [-1, 1]: positive leans bullish, negative bearish."""
    bullish_similarity = cosine_similarity(embedding, anchors.bullish_centroid)
    bearish_similarity = cosine_similarity(embedding, anchors.bearish_centroid)
    return max(-1.0, min(1.0, bullish_similarity - bearish_similarity))


def _recency_weight(published_at: datetime | None, *, now: datetime, half_life_days: float) -> float:
    if published_at is None:
        return 0.5  # unknown publish time: weight as moderately stale
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - published_at).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life_days)


def score_news(
    chunks: list[NewsChunk],
    anchors: SentimentAnchors | None,
    *,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    top_n: int = 3,
) -> SentimentAssessment:
    """Aggregate per-chunk scores into one recency-weighted sentiment score."""
    if not anchors or not chunks:
        return SentimentAssessment(score=None, chunk_count=0, top_chunks=[])

    evaluation_time = now or datetime.now(timezone.utc)
    scored: list[ChunkScore] = []
    for chunk in chunks:
        score = score_embedding(chunk.embedding, anchors)
        weight = _recency_weight(chunk.published_at, now=evaluation_time, half_life_days=half_life_days)
        scored.append(ChunkScore(chunk=chunk, score=score, weight=weight))

    total_weight = sum(item.weight for item in scored)
    if total_weight == 0:
        aggregate = sum(item.score for item in scored) / len(scored)
    else:
        aggregate = sum(item.score * item.weight for item in scored) / total_weight

    top_chunks = sorted(scored, key=lambda item: abs(item.score) * item.weight, reverse=True)[:top_n]
    return SentimentAssessment(
        score=round(max(-1.0, min(1.0, aggregate)), 3),
        chunk_count=len(chunks),
        top_chunks=top_chunks,
    )
