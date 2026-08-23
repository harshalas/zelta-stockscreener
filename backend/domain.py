import json
import re
from enum import StrEnum


TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,9}$")
ASSESSMENTS = {"bullish", "neutral", "bearish"}


class AnalysisJobStatus(StrEnum):
    QUEUED = "queued"
    GATHERING_DATA = "gathering_data"
    READING_NEWS = "reading_news"
    CALCULATING_RISK = "calculating_risk"
    COMPLETE = "complete"
    FAILED = "failed"


ANALYSIS_JOB_TRANSITIONS = {
    AnalysisJobStatus.QUEUED: {
        AnalysisJobStatus.GATHERING_DATA,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.GATHERING_DATA: {
        AnalysisJobStatus.READING_NEWS,
        AnalysisJobStatus.CALCULATING_RISK,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.READING_NEWS: {
        AnalysisJobStatus.CALCULATING_RISK,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.CALCULATING_RISK: {
        AnalysisJobStatus.COMPLETE,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.COMPLETE: set(),
    AnalysisJobStatus.FAILED: set(),
}


def validate_analysis_job_transition(
    current: AnalysisJobStatus | str,
    next_status: AnalysisJobStatus | str,
) -> AnalysisJobStatus:
    current_status = AnalysisJobStatus(current)
    target_status = AnalysisJobStatus(next_status)
    if target_status not in ANALYSIS_JOB_TRANSITIONS[current_status]:
        raise ValueError(
            f"Analysis job cannot transition from {current_status.value} "
            f"to {target_status.value}."
        )
    return target_status


def normalize_ticker(value: str) -> str:
    normalized = value.strip().upper()
    if not TICKER_PATTERN.fullmatch(normalized):
        raise ValueError("Ticker may contain only letters, numbers, dots, and hyphens.")
    return normalized


def morning_screener_cache_key(tickers: list[str], threshold: float) -> str:
    normalized = sorted({normalize_ticker(ticker) for ticker in tickers})
    return f"screener:morning:{','.join(normalized)}:{threshold:g}"


def parse_assessment(raw_output: str) -> tuple[str, dict]:
    cleaned = raw_output.strip().removeprefix("```json").removesuffix("```").strip()
    parsed = json.loads(cleaned)
    assessment = str(parsed["final_bias"]).lower()
    if assessment not in ASSESSMENTS:
        raise ValueError("Unsupported assessment")
    return assessment, parsed

