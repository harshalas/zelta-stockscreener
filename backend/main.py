from contextlib import asynccontextmanager
from typing import List
from uuid import UUID
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import yfinance as yf
import asyncio
import psycopg2
import os

load_dotenv()

from cache_service import market_cache
from analysis_engine import DeterministicAnalysisEngine
from analysis_models import AnalysisResult
from database import (
    get_database_verification_snapshot,
    get_performance_summary,
    init_db,
    save_prediction,
    save_scan_results,
)
from news_harvester import harvest_and_pipeline_news
from scanner import MarketScannerService
from auth import CurrentUser, get_current_user
from config import get_settings
from migrations import run_migrations
from product_repository import (
    add_watchlist_item,
    create_analysis_job,
    get_analysis_job,
    get_or_create_default_watchlist,
    remove_watchlist_item,
)
from domain import morning_screener_cache_key, normalize_ticker, parse_assessment
from analysis_job_worker import run_analysis_job

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # runs once when server starts
    run_migrations()
    yield

app = FastAPI(
    lifespan=lifespan,
    title="Zelta Stockscreener API",
    description=(
        "Use these endpoints in Swagger UI to verify live market fetches, "
        "news ingestion, scanner output, and database persistence without "
        "running shell scripts."
    ),
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
scanner_service = MarketScannerService()
analysis_engine = DeterministicAnalysisEngine()

class WatchlistRequest(BaseModel):
    tickers: List[str] = Field(
        ...,
        examples=[["PLTR", "AAPL", "NVDA"]],
        description="Tickers to scan in the batch run.",
    )
    volatility_threshold: float = Field(
        1.0,
        examples=[1.0],
        description="Minimum annualized volatility required for a ticker to be included in alerts.",
    )


class WatchlistItemRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    company_name: str | None = Field(None, max_length=200)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        return normalize_ticker(value)


class AnalysisJobRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return normalize_ticker(value)


@app.get("/health", tags=["operations"])
async def health_check():
    checks = {"database": "unavailable", "redis": "unavailable"}
    try:
        with psycopg2.connect(settings.postgres_url, connect_timeout=3) as db:
            with db.cursor() as cursor:
                cursor.execute("SELECT 1")
        checks["database"] = "available"
    except psycopg2.Error:
        pass

    try:
        market_cache.client.ping()
        checks["redis"] = "available"
    except Exception:
        pass

    healthy = checks["database"] == "available"
    return {
        "status": "healthy" if healthy else "degraded",
        "checks": checks,
    }


@app.get("/api/v1/watchlist", tags=["watchlist"])
async def get_watchlist(user: CurrentUser = Depends(get_current_user)):
    return get_or_create_default_watchlist(user.id)


@app.post("/api/v1/watchlist/items", status_code=status.HTTP_201_CREATED, tags=["watchlist"])
async def add_stock(request: WatchlistItemRequest, user: CurrentUser = Depends(get_current_user)):
    item = add_watchlist_item(user.id, request.ticker, request.company_name)
    if not item:
        raise HTTPException(status_code=409, detail=f"{request.ticker} is already in your watchlist.")
    return item


@app.delete("/api/v1/watchlist/items/{ticker}", status_code=status.HTTP_204_NO_CONTENT, tags=["watchlist"])
async def remove_stock(ticker: str, user: CurrentUser = Depends(get_current_user)):
    try:
        normalized = normalize_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not remove_watchlist_item(user.id, normalized):
        raise HTTPException(status_code=404, detail="Watchlist item not found.")


@app.post("/api/v1/analysis-jobs", status_code=status.HTTP_202_ACCEPTED, tags=["analysis"])
async def queue_analysis(
    request: AnalysisJobRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    job = create_analysis_job(user.id, request.ticker)
    background_tasks.add_task(run_analysis_job, job["id"], user.id, request.ticker)
    return job


@app.get("/api/v1/analysis-jobs/{job_id}", tags=["analysis"])
async def read_analysis_job(job_id: UUID, user: CurrentUser = Depends(get_current_user)):
    job = get_analysis_job(user.id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return job


@app.get(
    "/api/v1/analysis/preview/{ticker}",
    response_model=AnalysisResult,
    tags=["analysis"],
    summary="Generate an explainable technical assessment",
)
async def preview_analysis(ticker: str, user: CurrentUser = Depends(get_current_user)):
    try:
        normalized = normalize_ticker(ticker)
        price_data = await asyncio.to_thread(
            scanner_service.fetch_yfinance_data,
            normalized,
            "6mo",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Market data is currently unavailable. Try again later.",
        ) from exc

    return analysis_engine.analyze(normalized, price_data)

@app.get(
    "/api/v1/test-ticker/{symbol}",
    summary="Verify live yfinance connectivity",
    description=(
        "Use this endpoint in Swagger to confirm the API can reach yfinance and "
        "retrieve the latest close price for a symbol. This route uses the smart "
        "intraday Redis cache and returns source=cache or source=live_api."
    ),
)
async def test_ticker(symbol: str):
    symbol_upper = symbol.upper()
    cache_key = f"ticker:live:{symbol_upper}"

    cached_data = market_cache.get_cached_feed(cache_key)
    if cached_data:
        return {
            "ticker": symbol_upper,
            "source": "cache",
            "live_price": cached_data.get("live_price") if isinstance(cached_data, dict) else cached_data,
        }

    ticker = yf.Ticker(symbol_upper)
    history = ticker.history(period="1d")
    current_price = float(history["Close"].iloc[-1])
    live_payload = {"ticker": symbol_upper, "live_price": current_price}
    market_cache.cache_intraday_ticker_smart(symbol_upper, live_payload)

    return {"ticker": symbol_upper, "source": "live_api", "live_price": current_price}


@app.post(
    "/api/v1/harvest/{ticker}",
    summary="Verify news ingestion and vector storage",
    description=(
        "Fetch Finnhub news for the ticker, chunk it, embed it, and store it in "
        "PostgreSQL. This endpoint uses the news Redis cache and returns "
        "source=cache or source=live_api."
    ),
)
async def harvest_news(ticker: str):
    ticker_upper = ticker.upper()
    cache_key = f"news:feed:{ticker_upper}"

    cached_data = market_cache.get_cached_feed(cache_key)
    if cached_data:
        return {
            "status": cached_data.get("status", "complete") if isinstance(cached_data, dict) else "complete",
            "ticker": ticker_upper,
            "source": "cache",
            "articles_processed": cached_data.get("articles_processed") if isinstance(cached_data, dict) else cached_data,
        }

    response = harvest_and_pipeline_news(ticker_upper)
    market_cache.cache_news_feed(ticker_upper, response)
    return {**response, "source": "live_api"}


@app.get(
    "/api/v1/scan/history/{symbol}",
    summary="Review computed scanner history",
    description=(
        "Return the rolling volatility and volume-ratio series calculated from "
        "recent yfinance data. This endpoint uses the historical Redis cache and "
        "returns source=cache or source=live_api."
    ),
)
async def get_single_ticker_history(symbol: str):
    symbol_upper = symbol.upper()
    cache_key = f"ticker:history:{symbol_upper}"

    cached_data = market_cache.get_cached_feed(cache_key)
    if cached_data:
        return {
            "ticker": symbol_upper,
            "source": "cache",
            "historical_timeline": cached_data,
        }

    price_data = scanner_service.fetch_yfinance_data(symbol_upper, period="3mo")
    if len(price_data) < 20:
        return {"error": f"Insufficient historical data for {symbol_upper}."}

    timeline = scanner_service.get_historical_metrics_series(price_data)
    market_cache.cache_historical_timeline(symbol_upper, timeline)

    return {
        "ticker": symbol_upper,
        "source": "live_api",
        "historical_timeline": timeline,
    }


@app.post(
    "/api/v1/scan/morning-screener",
    summary="Run the morning screener",
    description=(
        "Pull yfinance data for the submitted tickers, compute annualized "
        "volatility and volume ratio, filter the tickers that meet the threshold, "
        "save the results to PostgreSQL, and cache the full alert snapshot in Redis."
    ),
)
async def morning_batch_screener(request: WatchlistRequest):
    normalized_tickers = sorted({normalize_ticker(ticker) for ticker in request.tickers})
    cache_key = morning_screener_cache_key(normalized_tickers, request.volatility_threshold)

    cached_alerts = market_cache.get_cached_feed(cache_key)
    if cached_alerts:
        return {
            "status": "morning_scan_complete",
            "source": "cache",
            "alerts": cached_alerts,
        }

    alerts = scanner_service.run_morning_screener(
        normalized_tickers, request.volatility_threshold
    )
    save_scan_results(alerts)
    
    if alerts:
        market_cache.set_market_feed(cache_key, alerts, ttl_seconds=900)
        return {
            "status": "morning_scan_complete",
            "source": "live_api",
            "alerts": alerts,
        }
    else:
        return {
            "status": "no_matches",
            "source": "live_api",
            "alerts": [],
            "message": "No tickers matched the volatility threshold.",
        }


@app.get(
    "/api/v1/verification/database",
    summary="Verify database persistence",
    description=(
        "Return row counts and the most recent stored scan/news rows so you can "
        "confirm data was written successfully from within Swagger UI. Add the "
        "optional ticker query parameter to verify one symbol, such as BMO. This "
        "endpoint also uses a short Redis cache so repeated Swagger checks are faster."
    ),
)
async def verify_database(limit: int = 10, ticker: str | None = None):
    cache_key = f"verification:database:{ticker.upper() if ticker else 'all'}:{limit}"

    cached_data = market_cache.get_cached_feed(cache_key)
    if cached_data:
        return {**cached_data, "source": "cache"}

    response = get_database_verification_snapshot(limit=limit, ticker=ticker)
    market_cache.set_market_feed(cache_key, response, ttl_seconds=60)
    return {**response, "source": "live_api"}


@app.get("/api/v1/anomalies")
async def get_volume_anomalies(tickers: str = "AAPL,MSFT,GOOGL", threshold: float = 1.5):
    """
    Detect volume spikes that exceed the Average Daily Volume (ADV) multiplier threshold.
    
    Query Parameters:
    - tickers: Comma-separated list of stock symbols (default: "AAPL,MSFT,GOOGL")
    - threshold: ADV multiplier threshold (default: 1.5)
    
    Returns: List of detected volume anomalies with historical context.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    
    if not ticker_list:
        return {
            "status": "error",
            "message": "No valid tickers provided",
            "detected_count": 0,
            "anomalies": {}
        }
    
    anomalies = scanner_service.detect_volume_anomalies(ticker_list, threshold)
    
    return {
        "status": "anomaly_detection_complete",
        "threshold_multiplier": threshold,
        "detected_count": len(anomalies),
        "anomalies": anomalies,
    }

@app.post(
    "/api/v1/analyse/{ticker}",
    tags=["experiments"],
    deprecated=True,
    summary="Run the legacy multi-agent experiment",
)
async def analyse_ticker(ticker: str, user: CurrentUser = Depends(get_current_user)):
    from functools import partial

    from agents import run_agent_analysis

    price_data = scanner_service.fetch_yfinance_data(ticker.upper(), period="3mo")
    if len(price_data) < 20:
        return {"error": f"Insufficient data for {ticker}"}

    metrics = scanner_service.calculate_volatility_and_volume(price_data)
    atr = scanner_service.calculate_atr(ticker.upper())
    current_price = metrics.get("current_close", 0)

    market_data = {
        "current_price": current_price,
        "volume_spike_ratio": metrics.get("volume_spike_ratio"),
        "annualized_volatility": metrics.get("annualized_volatility"),
        "atr_14": atr,
    }

    db = psycopg2.connect(os.getenv("POSTGRES_URL"))
    cursor = db.cursor()
    cursor.execute("""
        SELECT content_chunk FROM news_articles
        WHERE ticker = %s
        ORDER BY created_at DESC
        LIMIT 10
    """, (ticker.upper(),))
    rows = cursor.fetchall()
    cursor.close()
    db.close()

    news_chunks = [row[0] for row in rows]

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        partial(run_agent_analysis, ticker.upper(), market_data, news_chunks)
    )

    raw_output = result.get("ai_analysis", "")
    try:
        bias, parsed_output = parse_assessment(raw_output)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Analysis failed because the model returned an invalid result. Try again.",
        ) from exc
    real_stop_loss = scanner_service.calculate_stop_loss(current_price, atr, bias)

    market_data["calculated_stop_loss"] = real_stop_loss
    result.update(
        {
            "final_bias": parsed_output["final_bias"],
            "confidence_score": parsed_output.get("confidence_score"),
            "risk_rationale": parsed_output.get("risk_rationale"),
            "calculated_stop_loss": real_stop_loss,
        }
    )

    save_prediction(ticker.upper(), market_data, result)

    return result

@app.get("/api/v1/risk/{ticker}")
async def get_risk_metrics(ticker: str, bias: str = "bullish"):
    price_data = scanner_service.fetch_yfinance_data(ticker.upper(), period="1mo")
    if len(price_data) < 14:
        return {"error": f"Insufficient data for {ticker}"}

    metrics = scanner_service.calculate_volatility_and_volume(price_data)
    current_price = metrics.get("current_close", 0)
    atr = scanner_service.calculate_atr(ticker.upper())
    stop_loss = scanner_service.calculate_stop_loss(current_price, atr, bias)
    profit_target = scanner_service.calculate_profit_target(current_price, atr, bias)

    return {
        "ticker": ticker.upper(),
        "current_price": current_price,
        "atr_14": atr,
        "bias": bias,
        "stop_loss": stop_loss,
        "profit_target": profit_target,
        "risk_reward_ratio": "3:1"
    }

@app.get("/api/v1/predictions")
async def get_all_predictions():
    db = psycopg2.connect(os.getenv("POSTGRES_URL"))
    cursor = db.cursor()
    cursor.execute("""
        SELECT ticker, current_price, volume_spike_ratio, atr_14, 
               raw_agent_output, backtest_status, created_at
        FROM predictions
        ORDER BY created_at DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    cursor.close()
    db.close()

    predictions = []
    for row in rows:
        predictions.append({
            "ticker": row[0],
            "current_price": float(row[1]) if row[1] else None,
            "volume_spike_ratio": float(row[2]) if row[2] else None,
            "atr_14": float(row[3]) if row[3] else None,
            "ai_analysis": row[4],
            "backtest_status": row[5],
            "created_at": row[6].isoformat() if row[6] else None
        })

    return {"predictions": predictions}


@app.get(
    "/api/v1/predictions/performance",
    tags=["analysis"],
    summary="Backtested accuracy of past predictions",
    description=(
        "Aggregates every prediction backtest_engine.py has graded: hit-rate "
        "(how often the directional call was right) and average absolute "
        "error, plus how many predictions are still pending their 5-day "
        "evaluation window."
    ),
)
async def get_predictions_performance():
    return get_performance_summary()
