from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg2
import pytest

from analysis_engine import DeterministicAnalysisEngine
from analysis_job_worker import AnalysisJobDependencies, run_analysis_job
from config import get_settings
from sentiment_engine import NewsChunk, SentimentAnchors

BULLISH = [1.0, 0.0]
BEARISH = [0.0, 1.0]
TEST_ANCHORS = SentimentAnchors(
    bullish_centroid=BULLISH,
    bearish_centroid=BEARISH,
    model="test",
    bullish_phrases=["good news"],
    bearish_phrases=["bad news"],
    generated_at="2026-01-01T00:00:00+00:00",
)


def _rising_price_records(days: int = 70) -> list[dict]:
    end = datetime.now(timezone.utc)
    records = []
    for index in range(days):
        price = 100 + index * 0.75
        date = end - timedelta(days=days - index - 1)
        records.append(
            {
                "date": date.date().isoformat(),
                "open": price - 0.25,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 2_000_000 if index == days - 1 else 1_000_000,
            }
        )
    return records


def _insert_job(user_id: str, ticker: str) -> str:
    job_id = str(uuid4())
    with psycopg2.connect(get_settings().postgres_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO analysis_jobs (id, user_id, ticker) VALUES (%s, %s, %s)",
            (job_id, user_id, ticker),
        )
    return job_id


def _fake_deps(*, price_data=None, chunks=None, fail_price_fetch=False) -> AnalysisJobDependencies:
    def fetch_price_data(ticker, period):
        if fail_price_fetch:
            raise RuntimeError("yfinance is unreachable in this test")
        return price_data if price_data is not None else _rising_price_records()

    return AnalysisJobDependencies(
        fetch_price_data=fetch_price_data,
        has_fresh_news=lambda ticker: True,  # skip harvesting in tests
        harvest_news=lambda ticker: {"status": "complete", "articles_processed": 0},
        fetch_news_chunks=lambda ticker: chunks or [],
        load_anchors=lambda: TEST_ANCHORS,
        analysis_engine=DeterministicAnalysisEngine(),
    )


def test_worker_completes_a_job_with_no_news(require_postgres):
    user_id = f"test-user-{uuid4()}"
    job_id = _insert_job(user_id, "AAPL")

    result = run_analysis_job(job_id, user_id, "AAPL", deps=_fake_deps())

    assert result is not None
    assert result.assessment == "Bullish"
    assert result.macro_sentiment_score is None  # no news chunks supplied

    with psycopg2.connect(get_settings().postgres_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status FROM analysis_jobs WHERE id = %s", (job_id,))
        assert cursor.fetchone()[0] == "complete"

        cursor.execute(
            "SELECT final_bias, result_payload FROM predictions WHERE analysis_job_id = %s",
            (job_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "bullish"
        assert row[1]["assessment"] == "Bullish"


def test_worker_blends_in_bearish_news_and_still_completes(require_postgres):
    user_id = f"test-user-{uuid4()}"
    job_id = _insert_job(user_id, "MSFT")
    now = datetime.now(timezone.utc)
    chunks = [
        NewsChunk(headline="bad news for MSFT", url="https://example.com/1", published_at=now, embedding=BEARISH),
        NewsChunk(headline="more bad news", url="https://example.com/2", published_at=now, embedding=BEARISH),
    ]

    # Flat price series -> technical_score is 0, so a strongly bearish
    # sentiment score should be able to flip the overall call.
    flat_prices = _rising_price_records()
    for record in flat_prices:
        record["close"] = 100.0
        record["high"] = 101.0
        record["low"] = 99.0

    result = run_analysis_job(job_id, user_id, "MSFT", deps=_fake_deps(price_data=flat_prices, chunks=chunks))

    assert result is not None
    assert result.macro_sentiment_score == pytest.approx(-1.0)
    assert result.assessment == "Bearish"
    assert len(result.sources) == 2


def test_worker_marks_job_failed_when_price_fetch_raises(require_postgres):
    user_id = f"test-user-{uuid4()}"
    job_id = _insert_job(user_id, "BADTICKER")

    result = run_analysis_job(job_id, user_id, "BADTICKER", deps=_fake_deps(fail_price_fetch=True))

    assert result is None
    with psycopg2.connect(get_settings().postgres_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, error_message FROM analysis_jobs WHERE id = %s", (job_id,)
        )
        row = cursor.fetchone()
        assert row[0] == "failed"
        assert "unreachable" in row[1]
