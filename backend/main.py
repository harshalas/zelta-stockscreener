from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
import yfinance as yf

load_dotenv()

from database import init_db, save_scan_results
from news_harvester import harvest_and_pipeline_news
from scanner import MarketScannerService

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # runs once when server starts
    yield

app = FastAPI(lifespan=lifespan)
scanner_service = MarketScannerService()


class WatchlistRequest(BaseModel):
    tickers: List[str]
    volatility_threshold: float = 1.0


@app.get("/api/v1/test-ticker/{symbol}")
async def test_ticker(symbol: str):
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="1d")
    current_price = history["Close"].iloc[-1]
    return {"ticker": symbol, "live_price": float(current_price)}


@app.post("/api/v1/harvest/{ticker}")
async def harvest_news(ticker: str):
    return harvest_and_pipeline_news(ticker)


@app.get("/api/v1/scan/history/{symbol}")
async def get_single_ticker_history(symbol: str):
    price_data = scanner_service.fetch_yfinance_data(symbol, period="3mo")
    if len(price_data) < 20:
        return {"error": f"Insufficient historical data for {symbol}."}

    timeline = scanner_service.get_historical_metrics_series(price_data)
    return {"ticker": symbol.upper(), "historical_timeline": timeline}


@app.post("/api/v1/scan/morning-screener")
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