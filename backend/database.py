import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values, RealDictCursor
from datetime import date, datetime, timedelta

from config import get_settings

load_dotenv()


def _connect():
    return psycopg2.connect(get_settings().postgres_url)


def init_db():
    """
    Creates all required tables if they don't already exist.
    Runs automatically on server startup.
    """
    db = _connect()
    cursor = db.cursor()
    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            id SERIAL PRIMARY KEY,
            ticker TEXT NOT NULL,
            headline TEXT NOT NULL,
            summary TEXT,
            url TEXT,
            published_at TIMESTAMP,
            content_chunk TEXT NOT NULL,
            embedding vector(1536),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS news_embedding_idx 
        ON news_articles USING ivfflat (embedding vector_cosine_ops);
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolios (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            shares NUMERIC NOT NULL,
            avg_cost NUMERIC NOT NULL,
            added_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_scans (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(10) NOT NULL,
            scan_date DATE NOT NULL,
            close_price NUMERIC(10, 4),
            annualized_volatility NUMERIC(6, 4),
            volume_spike_ratio NUMERIC(6, 4),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, scan_date)
        );
    """)

    cursor.execute("""
        ALTER TABLE market_scans
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            ticker TEXT NOT NULL,
            current_price NUMERIC(10,4),
            predicted_price NUMERIC(10,4),       -- The AI's price target forecast
            volume_spike_ratio NUMERIC(6,4),
            atr_14 NUMERIC(10,4),
            final_bias TEXT,
            confidence_score NUMERIC(4,3),
            calculated_stop_loss NUMERIC(10,4),
            risk_rationale TEXT,
            raw_agent_output TEXT,

            -- Backtesting Metrics
            target_eval_date DATE,                 -- Created_at + 5 Days
            actual_close_price NUMERIC(10,4),      -- Real price from yfinance
            absolute_error_pct NUMERIC(6,2),       -- MAPE margin
            is_correct_direction BOOLEAN,           -- Directional hit/miss flag
            is_evaluated BOOLEAN DEFAULT FALSE,     -- Operational state tracking

            backtest_status TEXT DEFAULT 'pending',
            actual_outcome TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    db.commit()
    cursor.close()
    db.close()
    print("Database tables initialised successfully.")


def save_scan_results(alerts: dict):
    """
    Saves morning scanner results to the market_scans table.
    Updates existing records if the same ticker was already scanned today.
    """
    if not alerts:
        return

    query = """
        INSERT INTO market_scans (ticker, scan_date, close_price, annualized_volatility, volume_spike_ratio)
        VALUES %s
        ON CONFLICT (ticker, scan_date)
        DO UPDATE SET
            close_price = EXCLUDED.close_price,
            annualized_volatility = EXCLUDED.annualized_volatility,
            volume_spike_ratio = EXCLUDED.volume_spike_ratio,
            updated_at = CURRENT_TIMESTAMP;
    """

    today = datetime.now().date()
    records = []
    for ticker, data in alerts.items():
        summary = data.get("latest_summary", {})
        records.append(
            (
                ticker.upper(),
                today,
                summary.get("current_close"),
                summary.get("annualized_volatility"),
                summary.get("volume_spike_ratio"),
            )
        )

    db = _connect()
    try:
        cursor = db.cursor()
        execute_values(cursor, query, records)
        db.commit()
        cursor.close()
        print(f"Saved {len(records)} scan results to database.")
    except Exception as e:
        db.rollback()
        print(f"Error saving scan results: {e}")
    finally:
        db.close()


def get_database_verification_snapshot(limit: int = 10, ticker: str | None = None):
    """Return a compact snapshot of recently stored rows for Swagger-based verification."""
    db = _connect()
    cursor = db.cursor()

    try:
        ticker_filter = ticker.upper() if ticker else None

        if ticker_filter:
            cursor.execute(
                "SELECT COUNT(*) FROM market_scans WHERE ticker = %s;", (ticker_filter,)
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM market_scans;")
        market_scan_count = cursor.fetchone()[0]

        if ticker_filter:
            cursor.execute(
                "SELECT COUNT(*) FROM news_articles WHERE ticker = %s;",
                (ticker_filter,),
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM news_articles;")
        news_article_count = cursor.fetchone()[0]

        if ticker_filter:
            cursor.execute(
                """
                SELECT ticker, scan_date, close_price, annualized_volatility, volume_spike_ratio, created_at, updated_at
                FROM market_scans
                WHERE ticker = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT %s;
                """,
                (ticker_filter, limit),
            )
        else:
            cursor.execute(
                """
                SELECT ticker, scan_date, close_price, annualized_volatility, volume_spike_ratio, created_at, updated_at
                FROM market_scans
                ORDER BY updated_at DESC, id DESC
                LIMIT %s;
                """,
                (limit,),
            )
        recent_market_scans = [
            {
                "ticker": row[0],
                "scan_date": row[1].isoformat() if row[1] else None,
                "close_price": float(row[2]) if row[2] is not None else None,
                "annualized_volatility": float(row[3]) if row[3] is not None else None,
                "volume_spike_ratio": float(row[4]) if row[4] is not None else None,
                "created_at": row[5].isoformat() if row[5] else None,
                "updated_at": row[6].isoformat() if row[6] else None,
            }
            for row in cursor.fetchall()
        ]

        if ticker_filter:
            cursor.execute(
                """
                SELECT ticker, headline, created_at
                FROM news_articles
                WHERE ticker = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s;
                """,
                (ticker_filter, limit),
            )
        else:
            cursor.execute(
                """
                SELECT ticker, headline, created_at
                FROM news_articles
                ORDER BY created_at DESC, id DESC
                LIMIT %s;
                """,
                (limit,),
            )
        recent_news_articles = [
            {
                "ticker": row[0],
                "headline": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
            }
            for row in cursor.fetchall()
        ]

        return {
            "ticker_filter": ticker_filter,
            "market_scans": {
                "count": market_scan_count,
                "recent_rows": recent_market_scans,
            },
            "news_articles": {
                "count": news_article_count,
                "recent_rows": recent_news_articles,
            },
        }
    finally:
        cursor.close()
        db.close()


def save_prediction(ticker: str, market_data: dict, agent_result: dict):
    db = _connect()
    cursor = db.cursor()

    # Pre-calculate evaluation target (5 calendar days out)
    target_date = (datetime.utcnow() + timedelta(days=5)).date()

    cursor.execute(
        """
        INSERT INTO predictions 
        (
            ticker, current_price, predicted_price, volume_spike_ratio, atr_14, 
            final_bias, confidence_score, calculated_stop_loss, risk_rationale,
            raw_agent_output, target_eval_date
        ) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """,
        (
            ticker,
            float(market_data.get("current_price") or 0),
            (
                float(agent_result["predicted_price"])
                if agent_result.get("predicted_price") is not None
                else None
            ),
            float(market_data.get("volume_spike_ratio") or 0),
            float(market_data.get("atr_14") or 0),
            agent_result.get("final_bias"),
            (
                float(agent_result["confidence_score"])
                if agent_result.get("confidence_score") is not None
                else None
            ),
            (
                float(agent_result["calculated_stop_loss"])
                if agent_result.get("calculated_stop_loss") is not None
                else None
            ),
            agent_result.get("risk_rationale"),
            agent_result.get("ai_analysis"),
            target_date,
        ),
    )

    generated_id = cursor.fetchone()[0]
    db.commit()
    cursor.close()
    db.close()

    return generated_id


def _parse_embedding(raw: str | list[float]) -> list[float]:
    """psycopg2 has no built-in pgvector type, so a `vector` column comes back
    as its Postgres text form, e.g. "[0.01,-0.02,...]". Parse that back into
    floats; if some future driver upgrade already hands us a list, pass it
    through untouched."""
    if isinstance(raw, list):
        return [float(value) for value in raw]
    return [float(value) for value in raw.strip("[]").split(",") if value]


def has_fresh_news(ticker: str, *, within_minutes: int = 120) -> bool:
    """True if we've harvested this ticker recently enough to skip re-harvesting.

    Keeps the analysis-job worker from calling Finnhub + re-embedding the
    same headlines (and growing news_articles unnecessarily) every time
    someone re-runs an analysis on the same stock within a couple of hours.
    """
    db = _connect()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT 1 FROM news_articles
            WHERE ticker = %s AND created_at >= NOW() - (%s || ' minutes')::INTERVAL
            LIMIT 1
            """,
            (ticker.upper(), within_minutes),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def fetch_recent_news_chunks(ticker: str, *, limit: int = 15, lookback_days: int = 7) -> list["NewsChunk"]:
    """Pull the most recent embedded news chunks for a ticker.

    Used by sentiment_engine.score_news -- this is read-only and returns
    plain NewsChunk records; it does no scoring itself.
    """
    from sentiment_engine import NewsChunk

    db = _connect()
    cursor = db.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT headline, url, published_at, embedding
            FROM news_articles
            WHERE ticker = %s AND created_at >= NOW() - (%s || ' days')::INTERVAL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (ticker.upper(), lookback_days, limit),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        db.close()

    return [
        NewsChunk(
            headline=row["headline"],
            url=row["url"],
            published_at=row["published_at"],
            embedding=_parse_embedding(row["embedding"]),
        )
        for row in rows
        if row["embedding"] is not None
    ]


def fetch_due_predictions(as_of: date) -> list[dict]:
    """Predictions whose 5-day evaluation window has arrived and that made
    a directional call worth grading (Neutral calls have no predicted_price
    and are intentionally excluded -- there's nothing to check them against).
    """
    db = _connect()
    cursor = db.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT id, ticker, current_price, predicted_price, target_eval_date
            FROM predictions
            WHERE is_evaluated = FALSE
              AND target_eval_date IS NOT NULL
              AND target_eval_date <= %s
              AND predicted_price IS NOT NULL
              AND current_price IS NOT NULL
            ORDER BY target_eval_date
            """,
            (as_of,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        db.close()


def record_backtest_result(
    prediction_id: int,
    *,
    actual_close_price: float,
    absolute_error_pct: float,
    is_correct_direction: bool,
) -> None:
    db = _connect()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE predictions
            SET actual_close_price = %s,
                absolute_error_pct = %s,
                is_correct_direction = %s,
                is_evaluated = TRUE
            WHERE id = %s
            """,
            (actual_close_price, absolute_error_pct, is_correct_direction, prediction_id),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def get_performance_summary() -> dict:
    """Aggregate hit-rate and average error across every graded prediction.

    This is the number that actually answers "does the model work" --
    everything else in the pipeline is inputs and process; this is the
    output that matters.
    """
    db = _connect()
    cursor = db.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_evaluated) AS evaluated_count,
                COUNT(*) FILTER (WHERE NOT is_evaluated) AS pending_count,
                COUNT(*) FILTER (WHERE is_evaluated AND is_correct_direction) AS correct_count,
                AVG(absolute_error_pct) FILTER (WHERE is_evaluated) AS avg_absolute_error_pct
            FROM predictions
            WHERE target_eval_date IS NOT NULL
            """
        )
        row = dict(cursor.fetchone())
    finally:
        cursor.close()
        db.close()

    evaluated = row["evaluated_count"] or 0
    correct = row["correct_count"] or 0
    avg_error = (
        float(row["avg_absolute_error_pct"]) if row["avg_absolute_error_pct"] is not None else None
    )
    return {
        "evaluated_count": evaluated,
        "pending_count": row["pending_count"] or 0,
        "correct_count": correct,
        "hit_rate": round(correct / evaluated, 3) if evaluated else None,
        "avg_absolute_error_pct": round(avg_error, 2) if avg_error is not None else None,
    }
