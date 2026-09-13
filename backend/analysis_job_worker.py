"""Drives one analysis_jobs row from `queued` to `complete`/`failed`.

This is the piece the project was missing: POST /api/v1/analysis-jobs would
create a row and just leave it at status='queued' forever, because nothing
ever called into scanner.py / analysis_engine.py / sentiment_engine.py to
actually produce a result. main.py now calls `run_analysis_job` via
FastAPI's BackgroundTasks right after creating the job (see
`queue_analysis` in main.py) so the 202 response returns immediately and
the work happens after.

Why BackgroundTasks and not Celery/RQ: this project's own early planning
notes already laid out the right sequencing for this -- "Phase 1: a
standalone script/synchronous call. Phase 2: wrap it in FastAPI
BackgroundTasks. Phase 3: only move to Celery once you're actually
streaming live data at a scale that needs multiple workers." A single
Render free-tier instance serving a personal watchlist doesn't need a
message broker; it needs the job to actually run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Sequence
from uuid import UUID

from analysis_engine import DeterministicAnalysisEngine
from analysis_models import AnalysisResult, SourceEvidence
from database import fetch_recent_news_chunks, has_fresh_news
from domain import AnalysisJobStatus
from news_harvester import harvest_and_pipeline_news
from product_repository import save_analysis_result, transition_analysis_job
from scanner import MarketScannerService
from sentiment_engine import NewsChunk, SentimentAnchors, load_anchors, score_news

logger = logging.getLogger(__name__)


@dataclass
class AnalysisJobDependencies:
    """Everything the worker needs, as plain callables.

    Injected so tests can run the full queued->complete pipeline without a
    network connection, a Finnhub key, or an OpenAI key -- see
    tests/test_analysis_job_worker.py.
    """

    fetch_price_data: Callable[[str, str], list[dict]]
    has_fresh_news: Callable[[str], bool]
    harvest_news: Callable[[str], dict]
    fetch_news_chunks: Callable[[str], Sequence[NewsChunk]]
    load_anchors: Callable[[], SentimentAnchors | None]
    analysis_engine: DeterministicAnalysisEngine

    @classmethod
    def live(cls) -> "AnalysisJobDependencies":
        scanner = MarketScannerService()
        return cls(
            fetch_price_data=lambda ticker, period: scanner.fetch_yfinance_data(ticker, period),
            has_fresh_news=has_fresh_news,
            harvest_news=harvest_and_pipeline_news,
            fetch_news_chunks=fetch_recent_news_chunks,
            load_anchors=load_anchors,
            analysis_engine=DeterministicAnalysisEngine(),
        )


def run_analysis_job(
    job_id: UUID,
    user_id: str,
    ticker: str,
    *,
    deps: AnalysisJobDependencies | None = None,
) -> AnalysisResult | None:
    """Execute one job. Returns the final result on success, None on failure.

    On failure the reason is written onto the analysis_jobs row itself
    (via transition_analysis_job's error_code/error_message columns) --
    GET /api/v1/analysis-jobs/{id} is how a caller finds out what happened,
    not this return value.
    """
    dependencies = deps or AnalysisJobDependencies.live()

    try:
        transition_analysis_job(job_id, AnalysisJobStatus.GATHERING_DATA)
        price_data = dependencies.fetch_price_data(ticker, "6mo")
        technical_result = dependencies.analysis_engine.analyze(ticker, price_data)

        transition_analysis_job(job_id, AnalysisJobStatus.READING_NEWS)
        if not dependencies.has_fresh_news(ticker):
            try:
                dependencies.harvest_news(ticker)
            except Exception:
                # A Finnhub/embedding hiccup shouldn't fail the whole job --
                # we fall back to a technical-only result, same as a ticker
                # that genuinely has no recent coverage.
                logger.warning(
                    "News harvesting failed for %s; continuing technical-only.",
                    ticker,
                    exc_info=True,
                )

        transition_analysis_job(job_id, AnalysisJobStatus.CALCULATING_RISK)
        chunks = dependencies.fetch_news_chunks(ticker)
        anchors = dependencies.load_anchors()
        sentiment = score_news(list(chunks), anchors)
        sources = [
            SourceEvidence(
                title=item.chunk.headline,
                url=item.chunk.url or "",
                published_at=item.chunk.published_at,
            )
            for item in sentiment.top_chunks
            if item.chunk.url
        ]
        final_result = dependencies.analysis_engine.blend_sentiment(
            technical_result,
            sentiment_score=sentiment.score,
            chunk_count=sentiment.chunk_count,
            sources=sources,
        )

        save_analysis_result(
            user_id=user_id,
            job_id=job_id,
            ticker=ticker,
            current_price=final_result.indicators.current_price,
            volume_spike_ratio=final_result.indicators.volume_ratio_20d,
            result=final_result,
        )

        transition_analysis_job(job_id, AnalysisJobStatus.COMPLETE)
        return final_result
    except Exception as exc:  # noqa: BLE001 - this is the job's top-level guard
        logger.exception("Analysis job %s for %s failed", job_id, ticker)
        try:
            transition_analysis_job(
                job_id,
                AnalysisJobStatus.FAILED,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )
        except Exception:
            logger.exception("Could not record failure for job %s either", job_id)
        return None
