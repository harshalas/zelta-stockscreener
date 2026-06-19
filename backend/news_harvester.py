import os
import finnhub
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

finnhub_client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY"))

def fetch_news(ticker: str) -> list[dict]:
    now = datetime.utcnow()
    from_date = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    try:
        articles = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
    except Exception as e:
        print(f"Error fetching news for {ticker}: {e}")
        return []

    cleaned = []
    for article in articles:
        cleaned.append({
            "ticker": ticker,
            "headline": article.get("headline", ""),
            "summary": article.get("summary", ""),
            "url": article.get("url", ""),
            "published_at": datetime.fromtimestamp(article.get("datetime", 0))
        })

    print(f"Fetched {len(cleaned)} articles for {ticker}")
    return cleaned