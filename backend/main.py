from news_harvester import fetch_news
from vector_pipeline import process_ticker
from fastapi import FastAPI
import yfinance as yf

app = FastAPI()

@app.get("/api/v1/test-ticker/{symbol}")
async def test_ticker(symbol: str):
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="1d")
    current_price = history['Close'].iloc[-1]
    return {"ticker": symbol, "live_price": float(current_price)}

@app.post("/api/v1/harvest/{ticker}")
async def harvest_news(ticker: str):
    articles = fetch_news(ticker.upper())
    if not articles:
        return {"status": "no articles found", "ticker": ticker}
    
    process_ticker(ticker.upper(), articles)
    return {
        "status": "complete",
        "ticker": ticker.upper(),
        "articles_processed": len(articles)
    }