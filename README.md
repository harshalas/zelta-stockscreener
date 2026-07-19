# Zelta Stockscreener

Algorithmic Sentiment & Liquidity Screener.

## What is implemented

- FastAPI backend for live ticker checks, news harvesting, scan history, batch screening, and database verification.
- Scanner logic that pulls yfinance data, computes annualized volatility and volume ratio, and stores qualifying scans in PostgreSQL.
- Finnhub news ingestion with text chunking and OpenAI embeddings stored in pgvector.
- Next.js frontend scaffold.
- Supabase JWT verification for protected product endpoints.
- User-owned watchlist persistence and analysis-job status records.
- Versioned SQL migrations, health reporting, explicit CORS origins, and request timeouts for news ingestion.

## Current product status

The backend product foundation is under construction. Authentication verification, watchlist CRUD,
and analysis-job records now exist, but there is not yet a background worker or usable frontend.
Creating a job currently records it as `queued`; it will not run until the worker is added.


## Backend configuration

1. Copy `backend/.env.example` to `backend/.env` and replace every required value.
2. Create a Supabase project and set `SUPABASE_URL`. The API verifies access tokens against the
   project's JWKS endpoint and fails closed when authentication is not configured.
3. Install pinned dependencies with `pip install -r backend/requirements-dev.txt`.
4. Start PostgreSQL and Redis with `docker compose up -d`.
5. Start the API from `backend` with `uvicorn main:app --reload`.
6. Check `GET /health` before exercising product routes.

Database migrations run at API startup and are tracked in `schema_migrations`.

### Protected product endpoints

All routes below require `Authorization: Bearer <supabase-access-token>`:

- `GET /api/v1/watchlist`
- `POST /api/v1/watchlist/items`
- `DELETE /api/v1/watchlist/items/{ticker}`
- `POST /api/v1/analysis-jobs`
- `GET /api/v1/analysis-jobs/{job_id}`

Run focused unit tests from `backend` with `pytest`.

## Run the backend

1. Start PostgreSQL and Redis with Docker Compose.
2. Set the required environment variables, especially `POSTGRES_URL`, `FINNHUB_API_KEY`, and `OPENAI_API_KEY`.
3. Start the FastAPI server.
4. Open [http://localhost:8000/docs](http://localhost:8000/docs).

## Verify in Swagger UI

Use the built-in docs instead of shell scripts to confirm each stage of the pipeline.

1. `GET /api/v1/test-ticker/{symbol}`
	- Confirms the backend can reach yfinance and fetch a live close price.
	- Example: `PLTR`

2. `GET /api/v1/scan/history/{symbol}`
	- Shows the computed volatility and volume-ratio history for a ticker.
	- Example: `PLTR`

3. `POST /api/v1/harvest/{ticker}`
	- Pulls Finnhub news, chunks the text, embeds it, and stores it in PostgreSQL.
	- Example: `PLTR`

4. `POST /api/v1/scan/morning-screener`
	- Runs the batch scanner, filters tickers by the volatility threshold, and saves results to PostgreSQL.
	- Example body:

	```json
	{
	  "tickers": ["PLTR", "AAPL", "NVDA"],
	  "volatility_threshold": 1.0
	}
	```

5. `GET /api/v1/verification/database`
	- Confirms data persistence by returning row counts and recent rows from `market_scans` and `news_articles`.

## Cache behavior in Swagger

The API returns a `source` field on cache-aware endpoints so you can tell whether the response came from Redis or was fetched live.

| Endpoint | Cache key pattern | TTL | Notes |
|---|---|---|---|
| `GET /api/v1/test-ticker/{symbol}` | `ticker:live:{symbol}` | 15s during market hours / 12h overnight | Smart intraday cache for live price checks |
| `GET /api/v1/scan/history/{symbol}` | `ticker:history:{symbol}` | 1h | Historical metric timeline cached between refreshes |
| `POST /api/v1/scan/morning-screener` | `screener:morning:matched` | 15m | Batch alert payload cached after scan |
| `POST /api/v1/harvest/{ticker}` | `news:feed:{symbol}` | 30m | News ingestion result cached to avoid duplicate fetches |
| `GET /api/v1/verification/database` | `verification:database:{ticker or all}:{limit}` | 60s | Short cache for repeated verification checks |

## Database verification

When `/api/v1/verification/database` returns recent rows, the storage path is working end to end.

## Frontend

The frontend is currently a placeholder shell and does not yet render the full dashboard described in the timeline.

### Volume Anomaly Detection
- **Endpoint:** `GET /api/v1/anomalies`
- **Query params:** `tickers` (comma-separated), `threshold` (default: 1.5)
- **Example:** `GET /api/v1/anomalies?tickers=TSLA,NVDA&threshold=1.5`


### July 1st - 15th:

Updates:

Product foundation:
- Added Supabase JWT verification for protected endpoints.
- Added user-owned watchlists and watchlist items.
-Added persistent analysis-job records with ownership checks.
- Added feedback and prediction metadata fields.
- Added protected watchlist CRUD and analysis-job APIs.

Database:
- Added versioned SQL migration runner.
- Added product-foundation migration.
- Added migration repairing legacy prediction schemas.
- Fixed structured prediction persistence.
- Stopped saving nonexistent predictions as predicted_price=0.
- Persisted bias, confidence, stop-loss, rationale, and raw output.

Reliability:
-Added /health for PostgreSQL and Redis.
- Added Docker health checks.
- Added explicit CORS configuration.
- Added Finnhub request timeouts.
- Made vector-pipeline failures visible.
- Removed the fallback that converted malformed output into Bullish.
- Isolated screener caches by tickers and threshold.
- Prevented local model configuration from overwriting production credentials.
- Normalized NumPy risk values before PostgreSQL persistence.


July 16th - 18th:

We replaced the three-agent workflow as the core analysis strategy with a deterministic engine that does not require local AI or a managed AI API. It evaluates moving averages, five-day movement, RSI, trading volume, volatility, and ATR to produce an explainable assessment.

Each result now contains:

- Bullish, Neutral, or Bearish assessment
- Technical score and confidence
- Plain-language reasons
- Risk level and price-risk range
- Indicators used
- Market-data timestamp
- Missing-news and stale-data warnings
- Model version
- Financial-information disclaimer

The old CrewAI endpoint remains available as a deprecated experiment but is no longer loaded during normal backend startup. CrewAI was also removed from production requirements.
