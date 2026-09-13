import os
from datetime import datetime, timezone

import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_db():
    return psycopg2.connect(os.getenv("POSTGRES_URL"))


def chunk_text(text: str, max_chars: int = 500) -> list[str]:
    words = text.split()
    chunks = []
    current = []
    count = 0

    for word in words:
        current.append(word)
        count += len(word) + 1
        if count >= max_chars:
            chunks.append(" ".join(current))
            current = []
            count = 0

    if current:
        chunks.append(" ".join(current))

    return chunks


def embed_text(text: str) -> list[float]:
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


def _parse_published_at(article: dict) -> datetime | None:
    """Finnhub's company-news payload stamps each article with a Unix-epoch
    "datetime" field, not "published_at" -- reading article.get("published_at")
    against a raw Finnhub article always returned None, which silently
    disabled the sentiment engine's recency weighting (every chunk fell back
    to the same "unknown publish time" weight). Accept an explicit
    "published_at" too, so callers that already pass a real datetime
    (tests, other future sources) aren't affected.
    """
    explicit = article.get("published_at")
    if isinstance(explicit, datetime):
        return explicit

    raw = explicit if explicit is not None else article.get("datetime")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def store_article(article: dict, db):
    full_text = f"{article['headline']}. {article.get('summary', '')}"
    chunks = chunk_text(full_text)
    cursor = db.cursor()
    published_at = _parse_published_at(article)

    for chunk in chunks:
        if not chunk.strip():
            continue

        embedding = embed_text(chunk)

        cursor.execute("""
            INSERT INTO news_articles
            (ticker, headline, summary, url, published_at, content_chunk, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            article["ticker"],
            article["headline"],
            article.get("summary", ""),
            article.get("url", ""),
            published_at,
            chunk,
            str(embedding)
        ))

    db.commit()
    cursor.close()
    print(f"Stored {len(chunks)} chunks for: {article['headline'][:60]}...")


def process_ticker(ticker: str, articles: list[dict]):
    print(f"Processing {len(articles)} articles for {ticker}...")
    db = get_db()
    try:
        for article in articles:
            # Finnhub's raw company-news articles never carry a "ticker"
            # key -- only the query symbol does, which process_ticker
            # already has. store_article used to assume article["ticker"]
            # existed and crashed with KeyError on every real harvest.
            article.setdefault("ticker", ticker)
            store_article(article, db)
    except Exception as e:
        db.rollback()
        print(f"Error processing ticker: {e}")
        raise
    finally:
        db.close()
        print(f"Ticker processed: {ticker}")
