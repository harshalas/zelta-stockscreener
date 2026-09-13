import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from analysis_models import AnalysisResult
from config import get_settings
from domain import AnalysisJobStatus, validate_analysis_job_transition


def _connection():
    return psycopg2.connect(get_settings().postgres_url)


def get_or_create_default_watchlist(user_id: str) -> dict:
    with _connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            INSERT INTO watchlists (user_id, name) VALUES (%s, 'My Watchlist')
            ON CONFLICT (user_id, name) DO UPDATE SET updated_at = watchlists.updated_at
            RETURNING id, name, created_at, updated_at
            """,
            (user_id,),
        )
        watchlist = dict(cursor.fetchone())
        cursor.execute(
            """
            SELECT id, ticker, company_name, created_at
            FROM watchlist_items WHERE watchlist_id = %s ORDER BY created_at, ticker
            """,
            (watchlist["id"],),
        )
        watchlist["items"] = [dict(row) for row in cursor.fetchall()]
        return watchlist


def add_watchlist_item(user_id: str, ticker: str, company_name: str | None) -> dict | None:
    watchlist = get_or_create_default_watchlist(user_id)
    with _connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            INSERT INTO watchlist_items (watchlist_id, ticker, company_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (watchlist_id, ticker) DO NOTHING
            RETURNING id, ticker, company_name, created_at
            """,
            (watchlist["id"], ticker, company_name),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def remove_watchlist_item(user_id: str, ticker: str) -> bool:
    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM watchlist_items item
            USING watchlists watchlist
            WHERE item.watchlist_id = watchlist.id
              AND watchlist.user_id = %s
              AND item.ticker = %s
            """,
            (user_id, ticker),
        )
        return cursor.rowcount > 0


def create_analysis_job(user_id: str, ticker: str) -> dict:
    job_id = uuid4()
    with _connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            INSERT INTO analysis_jobs (id, user_id, ticker)
            VALUES (%s, %s, %s)
            RETURNING id, ticker, status, error_code, error_message,
                      created_at, updated_at, started_at, completed_at
            """,
            (str(job_id), user_id, ticker),
        )
        return dict(cursor.fetchone())


def get_analysis_job(user_id: str, job_id: UUID) -> dict | None:
    with _connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT aj.id, aj.ticker, aj.status, aj.error_code, aj.error_message,
                   aj.created_at, aj.updated_at, aj.started_at, aj.completed_at,
                   p.result_payload AS result
            FROM analysis_jobs aj
            LEFT JOIN predictions p ON p.analysis_job_id = aj.id
            WHERE aj.id = %s AND aj.user_id = %s
            ORDER BY p.created_at DESC NULLS LAST
            LIMIT 1
            """,
            (str(job_id), user_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def transition_analysis_job(
    job_id: UUID,
    next_status: AnalysisJobStatus | str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict:
    with _connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT status FROM analysis_jobs WHERE id = %s FOR UPDATE",
            (str(job_id),),
        )
        row = cursor.fetchone()
        if not row:
            raise KeyError(f"Analysis job {job_id} was not found.")

        target = validate_analysis_job_transition(row["status"], next_status)
        if target == AnalysisJobStatus.FAILED and not error_message:
            raise ValueError("A failed analysis job must include an error message.")

        cursor.execute(
            """
            UPDATE analysis_jobs
            SET status = %s,
                error_code = CASE WHEN %s = 'failed' THEN %s ELSE NULL END,
                error_message = CASE WHEN %s = 'failed' THEN %s ELSE NULL END,
                started_at = CASE
                    WHEN %s = 'gathering_data' THEN COALESCE(started_at, NOW())
                    ELSE started_at
                END,
                completed_at = CASE
                    WHEN %s IN ('complete', 'failed') THEN NOW()
                    ELSE completed_at
                END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, ticker, status, error_code, error_message,
                      created_at, updated_at, started_at, completed_at
            """,
            (
                target.value,
                target.value,
                error_code,
                target.value,
                error_message,
                target.value,
                target.value,
                str(job_id),
            ),
        )
        return dict(cursor.fetchone())


def _directional_levels(result: AnalysisResult) -> tuple[float | None, float | None]:
    """(predicted_price, stop_loss) implied by the model's own risk range.

    Bullish: target is the top of the range, stop-loss protects the bottom.
    Bearish: target is the bottom of the range, stop-loss protects the top.
    Neutral: no directional call was made, so there's nothing to grade later
    -- both come back None and the backtest engine skips the row.
    """
    if result.risk_range is None:
        return None, None
    if result.assessment == "Bullish":
        return result.risk_range.upper, result.risk_range.lower
    if result.assessment == "Bearish":
        return result.risk_range.lower, result.risk_range.upper
    return None, None


def save_analysis_result(
    *,
    user_id: str,
    job_id: UUID,
    ticker: str,
    current_price: float | None,
    volume_spike_ratio: float | None,
    result: AnalysisResult,
) -> int:
    """Persist a completed AnalysisResult so it can be read back by
    get_analysis_job and later graded by backtest_engine.py."""
    predicted_price, stop_loss = _directional_levels(result)
    target_eval_date = (datetime.now(timezone.utc) + timedelta(days=5)).date()

    with _connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO predictions (
                ticker, user_id, analysis_job_id, current_price, predicted_price,
                volume_spike_ratio, atr_14, final_bias, confidence_score,
                calculated_stop_loss, risk_rationale, model_version, result_status,
                source_evidence, warnings, result_payload, input_data_timestamp,
                target_eval_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                ticker,
                user_id,
                str(job_id),
                current_price,
                predicted_price,
                volume_spike_ratio,
                result.indicators.atr_14,
                result.assessment.lower(),
                result.confidence,
                stop_loss,
                " ".join(result.reasons),
                result.model_version,
                result.status,
                Json([source.model_dump(mode="json") for source in result.sources]),
                Json(result.warnings),
                Json(json.loads(result.model_dump_json())),
                result.data_timestamp,
                target_eval_date,
            ),
        )
        return cursor.fetchone()[0]
