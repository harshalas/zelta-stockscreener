from datetime import datetime, timedelta, timezone

import pytest

from sentiment_engine import (
    NewsChunk,
    SentimentAnchors,
    cosine_similarity,
    score_embedding,
    score_news,
)


BULLISH_DIRECTION = [1.0, 0.0, 0.0]
BEARISH_DIRECTION = [0.0, 1.0, 0.0]
NEUTRAL_DIRECTION = [0.0, 0.0, 1.0]

ANCHORS = SentimentAnchors(
    bullish_centroid=BULLISH_DIRECTION,
    bearish_centroid=BEARISH_DIRECTION,
    model="test-model",
    bullish_phrases=["beats earnings"],
    bearish_phrases=["misses earnings"],
    generated_at="2026-01-01T00:00:00+00:00",
)


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_rejects_mismatched_dimensions():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_cosine_similarity_zero_vector_does_not_divide_by_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_score_embedding_leans_bullish_for_bullish_aligned_vector():
    score = score_embedding(BULLISH_DIRECTION, ANCHORS)
    assert score == pytest.approx(1.0)


def test_score_embedding_leans_bearish_for_bearish_aligned_vector():
    score = score_embedding(BEARISH_DIRECTION, ANCHORS)
    assert score == pytest.approx(-1.0)


def test_score_embedding_is_near_zero_for_unrelated_vector():
    score = score_embedding(NEUTRAL_DIRECTION, ANCHORS)
    assert score == pytest.approx(0.0)


def test_score_news_returns_unavailable_with_no_anchors():
    chunk = NewsChunk(headline="x", url=None, published_at=None, embedding=BULLISH_DIRECTION)
    result = score_news([chunk], anchors=None)
    assert result.available is False
    assert result.score is None
    assert result.chunk_count == 0


def test_score_news_returns_unavailable_with_no_chunks():
    result = score_news([], anchors=ANCHORS)
    assert result.available is False


def test_score_news_averages_multiple_chunks():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    chunks = [
        NewsChunk(headline="bullish 1", url=None, published_at=now, embedding=BULLISH_DIRECTION),
        NewsChunk(headline="bullish 2", url=None, published_at=now, embedding=BULLISH_DIRECTION),
    ]
    result = score_news(chunks, anchors=ANCHORS, now=now)
    assert result.available is True
    assert result.chunk_count == 2
    assert result.score == pytest.approx(1.0)


def test_score_news_weighs_recent_headlines_more_than_stale_ones():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    fresh_bullish = NewsChunk(
        headline="fresh bullish", url=None, published_at=now, embedding=BULLISH_DIRECTION
    )
    stale_bearish = NewsChunk(
        headline="stale bearish",
        url=None,
        published_at=now - timedelta(days=30),
        embedding=BEARISH_DIRECTION,
    )
    result = score_news([fresh_bullish, stale_bearish], anchors=ANCHORS, now=now, half_life_days=3.0)
    assert result.available is True
    # The 30-day-old bearish headline should barely move the needle against
    # today's bullish one.
    assert result.score > 0.9


def test_score_news_top_chunks_are_sorted_by_impact():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    strong = NewsChunk(headline="strong", url=None, published_at=now, embedding=BULLISH_DIRECTION)
    weak = NewsChunk(headline="weak", url=None, published_at=now, embedding=NEUTRAL_DIRECTION)
    result = score_news([weak, strong], anchors=ANCHORS, now=now, top_n=2)
    assert result.top_chunks[0].chunk.headline == "strong"
