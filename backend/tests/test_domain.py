import pytest

from domain import (
    AnalysisJobStatus,
    morning_screener_cache_key,
    normalize_ticker,
    parse_assessment,
    validate_analysis_job_transition,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("fngu", "FNGU")],
)
def test_normalize_ticker(value, expected):
    assert normalize_ticker(value) == expected


@pytest.mark.parametrize("value", ["", "AAPL!", "TOO-LONG-TICKER", "../AAPL"])
def test_normalize_ticker_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_ticker(value)


def test_screener_cache_key_isolated_by_inputs():
    assert morning_screener_cache_key(["MSFT", "AAPL"], 1.5) == "screener:morning:AAPL,MSFT:1.5"
    assert morning_screener_cache_key(["AAPL"], 1.5) != morning_screener_cache_key(["AAPL"], 2)


@pytest.mark.parametrize("assessment", ["Bullish", "Neutral", "Bearish"])
def test_parse_assessment_accepts_all_supported_results(assessment):
    parsed_assessment, payload = parse_assessment(f'{{"final_bias":"{assessment}"}}')
    assert parsed_assessment == assessment.lower()
    assert payload["final_bias"] == assessment


def test_parse_assessment_rejects_unstructured_model_output():
    with pytest.raises(ValueError):
        parse_assessment("Looks bullish to me")


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        ("queued", "gathering_data"),
        ("gathering_data", "reading_news"),
        ("gathering_data", "calculating_risk"),
        ("reading_news", "calculating_risk"),
        ("calculating_risk", "complete"),
        ("queued", "failed"),
    ],
)
def test_analysis_job_accepts_forward_and_failure_transitions(current, next_status):
    assert validate_analysis_job_transition(current, next_status) == AnalysisJobStatus(next_status)


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        ("queued", "complete"),
        ("calculating_risk", "gathering_data"),
        ("complete", "failed"),
        ("failed", "queued"),
    ],
)
def test_analysis_job_rejects_invalid_or_terminal_transitions(current, next_status):
    with pytest.raises(ValueError, match="cannot transition"):
        validate_analysis_job_transition(current, next_status)

