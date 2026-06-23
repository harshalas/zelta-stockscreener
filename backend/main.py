from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
import yfinance as yf

load_dotenv()

from cache_service import market_cache
from database import get_database_verification_snapshot, init_db, save_scan_results
from news_harvester import harvest_and_pipeline_news
from scanner import MarketScannerService

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # runs once when server starts
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
scanner_service = MarketScannerService()


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
    cache_key = "screener:morning:matched"

    cached_alerts = market_cache.get_cached_feed(cache_key)
    if cached_alerts:
        return {
            "status": "morning_scan_complete",
            "source": "cache",
            "alerts": cached_alerts,
        }

    alerts = scanner_service.run_morning_screener(
        request.tickers, request.volatility_threshold
    )
    save_scan_results(alerts)
    
    if alerts:
        market_cache.cache_morning_alerts(alerts)
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