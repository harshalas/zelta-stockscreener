import os
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


def store_article(article: dict, db):
    full_text = f"{article['headline']}. {article.get('summary', '')}"
    chunks = chunk_text(full_text)
    cursor = db.cursor()

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
            article.get("published_at"),
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
            store_article(article, db)
    except Exception as e:
        db.rollback()
        print(f"Error processing ticker: {e}")
    finally:
        db.close()
        print(f"Ticker processed: {ticker}")