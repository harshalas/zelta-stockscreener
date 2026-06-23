from contextlib import asynccontextmanager
from typing import List
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from agents import run_agent_analysis
from functools import partial
import asyncio
import yfinance as yf
import psycopg2
import os

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

@app.post("/api/v1/analyse/{ticker}")
async def analyse_ticker(ticker: str):
    price_data = scanner_service.fetch_yfinance_data(ticker.upper(), period="3mo")
    if len(price_data) < 20:
        return {"error": f"Insufficient data for {ticker}"}

    metrics = scanner_service.calculate_volatility_and_volume(price_data)

    market_data = {
        "current_price": metrics.get("current_close"),
        "volume_spike_ratio": metrics.get("volume_spike_ratio"),
        "annualized_volatility": metrics.get("annualized_volatility"),
        "atr_14": metrics.get("annualized_volatility", 1.0),
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

    # Run synchronous crew in a thread so it doesn't block the async event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        partial(run_agent_analysis, ticker.upper(), market_data, news_chunks)
    )

    return result