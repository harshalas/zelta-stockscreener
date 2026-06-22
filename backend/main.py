from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
import yfinance as yf

load_dotenv()

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
        "retrieve the latest close price for a symbol."
    ),
)
async def test_ticker(symbol: str):
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="1d")
    current_price = history["Close"].iloc[-1]
    return {"ticker": symbol, "live_price": float(current_price)}


@app.post(
    "/api/v1/harvest/{ticker}",
    summary="Verify news ingestion and vector storage",
    description=(
        "Fetch Finnhub news for the ticker, chunk it, embed it, and store it in "
        "PostgreSQL. Use the database verification endpoint afterward to confirm "
        "rows were written."
    ),
)
async def harvest_news(ticker: str):
    return harvest_and_pipeline_news(ticker)


@app.get(
    "/api/v1/scan/history/{symbol}",
    summary="Review computed scanner history",
    description=(
        "Return the rolling volatility and volume-ratio series calculated from "
        "recent yfinance data. This helps verify the metric pipeline before the "
        "batch screener is run."
    ),
)
async def get_single_ticker_history(symbol: str):
    price_data = scanner_service.fetch_yfinance_data(symbol, period="3mo")
    if len(price_data) < 20:
        return {"error": f"Insufficient historical data for {symbol}."}

    timeline = scanner_service.get_historical_metrics_series(price_data)
    return {"ticker": symbol.upper(), "historical_timeline": timeline}


@app.post(
    "/api/v1/scan/morning-screener",
    summary="Run the morning screener",
    description=(
        "Pull yfinance data for the submitted tickers, compute annualized "
        "volatility and volume ratio, filter the tickers that meet the threshold, "
        "and save the results to PostgreSQL."
    ),
)
async def morning_batch_screener(request: WatchlistRequest):
    alerts = scanner_service.run_morning_screener(
        request.tickers, request.volatility_threshold
    )
    save_scan_results(alerts)
    return {
        "status": "morning_scan_complete",
        "volatility_threshold_used": request.volatility_threshold,
        "matched_count": len(alerts),
        "alerts": alerts,
    }


@app.get(
    "/api/v1/verification/database",
    summary="Verify database persistence",
    description=(
        "Return row counts and the most recent stored scan/news rows so you can "
        "confirm data was written successfully from within Swagger UI. Add the "
        "optional ticker query parameter to verify one symbol, such as BMO."
    ),
)
async def verify_database(limit: int = 10, ticker: str | None = None):
    return get_database_verification_snapshot(limit=limit, ticker=ticker)