from datetime import datetime, timedelta, timezone

from analysis_engine import DeterministicAnalysisEngine
from analysis_models import SourceEvidence


def market_records(prices: list[float], *, end: datetime | None = None) -> list[dict]:
    end = end or datetime.now(timezone.utc)
    records = []
    for index, price in enumerate(prices):
        date = end - timedelta(days=len(prices) - index - 1)
        records.append(
            {
                "date": date.date().isoformat(),
                "open": price - 0.25,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 2_000_000 if index == len(prices) - 1 else 1_000_000,
            }
        )
    return records


def test_rising_market_is_bullish():
    prices = [100 + (index * 0.75) for index in range(70)]

    result = DeterministicAnalysisEngine().analyze("aapl", market_records(prices))

    assert result.assessment == "Bullish"
    assert result.technical_score >= 0.25
    assert result.status == "news_unavailable"
    assert result.risk_range.lower < result.indicators.current_price < result.risk_range.upper
    assert result.sources == []
    assert "News sentiment" in result.warnings[0]


def test_falling_market_is_bearish():
    prices = [160 - (index * 0.75) for index in range(70)]

    result = DeterministicAnalysisEngine().analyze("MSFT", market_records(prices))

    assert result.assessment == "Bearish"
    assert result.technical_score <= -0.25


def test_flat_market_is_neutral():
    prices = [100.0 for _ in range(70)]

    result = DeterministicAnalysisEngine().analyze("NVDA", market_records(prices))

    assert result.assessment == "Neutral"
    assert result.technical_score == 0


def test_insufficient_data_does_not_generate_an_assessment():
    result = DeterministicAnalysisEngine().analyze(
        "TSLA",
        market_records([100 + index for index in range(20)]),
    )

    assert result.status == "insufficient_data"
    assert result.assessment == "Neutral"
    assert result.confidence == 0
    assert result.indicators.current_price is None


def test_stale_data_is_visible_in_the_result():
    now = datetime.now(timezone.utc)
    prices = [100 + (index * 0.5) for index in range(70)]

    result = DeterministicAnalysisEngine().analyze(
        "AMD",
        market_records(prices, end=now - timedelta(days=10)),
        now=now,
    )

    assert result.status == "market_data_delayed"
    assert result.confidence < 0.75
    assert "10 days old" in result.warnings[0]


def test_blend_sentiment_is_a_no_op_when_sentiment_is_unavailable():
    prices = [100 + (index * 0.75) for index in range(70)]
    engine = DeterministicAnalysisEngine()
    technical_only = engine.analyze("AAPL", market_records(prices))

    blended = engine.blend_sentiment(
        technical_only, sentiment_score=None, chunk_count=0, sources=[]
    )

    assert blended == technical_only


def test_blend_sentiment_can_flip_a_borderline_technical_call_to_bearish():
    # A flat/neutral technical read (score == 0) plus strongly bearish news
    # should be enough to push the overall call to Bearish, while the raw
    # technical_score field stays untouched so both components stay visible.
    prices = [100.0 for _ in range(70)]
    engine = DeterministicAnalysisEngine()
    technical_only = engine.analyze("NVDA", market_records(prices))
    assert technical_only.technical_score == 0

    source = SourceEvidence(title="Company misses estimates", url="https://example.com/a")
    blended = engine.blend_sentiment(
        technical_only, sentiment_score=-0.9, chunk_count=3, sources=[source]
    )

    assert blended.technical_score == 0  # untouched
    assert blended.macro_sentiment_score == -0.9
    assert blended.overall_score < -0.25
    assert blended.assessment == "Bearish"
    assert blended.status == "complete"
    assert blended.sources == [source]
    assert not any("News sentiment has not been evaluated" in w for w in blended.warnings)
    assert any("skews bearish" in reason for reason in blended.reasons)


def test_blend_sentiment_keeps_stale_status_and_warning():
    now = datetime.now(timezone.utc)
    prices = [100 + (index * 0.5) for index in range(70)]
    engine = DeterministicAnalysisEngine()
    stale = engine.analyze("AMD", market_records(prices, end=now - timedelta(days=10)), now=now)

    blended = engine.blend_sentiment(stale, sentiment_score=0.8, chunk_count=2, sources=[])

    # Sentiment doesn't erase a market-data staleness warning -- that's a
    # separate, still-true problem.
    assert blended.status == "market_data_delayed"
    assert any("10 days old" in warning for warning in blended.warnings)
