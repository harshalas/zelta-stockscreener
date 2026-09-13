# Zelta Stockscreener

Algorithmic Sentiment & Liquidity Screener.

## What is implemented

- FastAPI backend for live ticker checks, news harvesting, scan history, batch screening, and database verification.
- Scanner logic that pulls yfinance data, computes annualized volatility and volume ratio, and stores qualifying scans in PostgreSQL.
- Finnhub news ingestion with text chunking and OpenAI embeddings stored in pgvector.
- A deterministic (non-LLM) technical analysis engine: SMA-20/50, RSI-14, 5-day momentum, volume ratio, volatility, and ATR combined into a Bullish/Neutral/Bearish assessment with plain-language reasons.
- A deterministic news-sentiment scorer: pre-embedded bullish/bearish reference phrases define centroid vectors, and live news chunks (already embedded by the ingestion pipeline above) are scored by cosine similarity to them. No LLM call happens at request time -- the "AI" here is the existing embeddings pipeline used mathematically, not generatively.
- An analysis-job worker that actually runs queued jobs end to end (`queued -> gathering_data -> reading_news -> calculating_risk -> complete/failed`), blends the sentiment score into the technical assessment, and persists the result.
- A backtest engine that grades every prediction against its real closing price 5 days later and exposes the resulting hit rate at `GET /api/v1/predictions/performance`.
- A responsive, installable Next.js PWA frontend: Supabase magic-link sign-in, a ticker analyzer that polls a job to completion, a watchlist, and a live accuracy strip -- installable to a phone home screen via `manifest.json` + a service worker.
- Supabase JWT verification for protected product endpoints.
- User-owned watchlist persistence and analysis-job status records.
- Versioned SQL migrations, health reporting, explicit CORS origins, and request timeouts for news ingestion.
- A `Dockerfile` for deploying the backend to Render's free web-service tier.

## Current product status

The core product loop works end to end: submit a ticker, a background job gathers price data and
recent news, scores both deterministically, blends them into one assessment, and the frontend polls
the job to a result. Predictions are graded automatically once they're 5 days old, and the running
accuracy is visible in the app. The legacy three-agent (CrewAI) pipeline still exists but is isolated
to `backend/agents.py` and `requirements-experiments.txt` -- it is not part of the normal request path.


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

`GET /api/v1/predictions/performance` is public (no auth) and returns the backtested hit rate.

Run focused unit tests from `backend` with `pytest`. Integration tests that touch PostgreSQL are
skipped automatically (see `backend/tests/conftest.py`) if no database is reachable.

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

A single-page Next.js app in `frontend/`, mobile-first by design (this is meant to be checked from a
phone, not just a desk):

- Supabase magic-link auth -- sign in with an email address, no password.
- A ticker analyzer that creates an analysis job and polls it to completion, rendering the
  assessment, confidence, technical vs. sentiment score breakdown, risk range, plain-language
  reasons, and source headlines.
- A watchlist (add/remove tickers, tap one to re-run its analysis).
- A live backtested-accuracy strip pulled from `/api/v1/predictions/performance`.
- Installable to a phone home screen: `frontend/src/app/manifest.json` + `frontend/public/sw.js`
  give it an app icon, standalone display mode, and an offline app shell. There is no native
  Android build (Capacitor was removed) -- a PWA reaches the same "check it from your phone"
  goal without maintaining a second native project.

### Frontend configuration

1. `cd frontend && npm install`
2. Copy `frontend/.env.local.example` to `frontend/.env.local` and fill in your Supabase project's
   URL/anon key and the backend's base URL.
3. `npm run dev` for local development, or `npm run build && npm start` to run a production build.

### Volume Anomaly Detection
- **Endpoint:** `GET /api/v1/anomalies`
- **Query params:** `tickers` (comma-separated), `threshold` (default: 1.5)
- **Example:** `GET /api/v1/anomalies?tickers=TSLA,NVDA&threshold=1.5`

## Deployment (free tier)

Everything below fits in each provider's free tier. This is deliberately four small services
instead of one big one: each does the one thing it's actually good at, and none of them costs
anything at this scale.

| Layer | Provider | Why |
|---|---|---|
| Postgres + pgvector + Auth | Supabase | You already need Supabase for JWT auth; its Postgres has `pgvector` built in, so it also serves as the one database, and there is nothing extra to run. |
| Redis cache | Upstash | Serverless Redis with a free tier; no server to manage. |
| Backend (FastAPI) | Render | Free web-service tier builds straight from `backend/Dockerfile`. |
| Frontend (Next.js) | Vercel | First-class Next.js support, free tier, deploys on every push. |

### 1. Supabase (Postgres + pgvector + Auth)

1. Create a project at [supabase.com](https://supabase.com).
2. In **Project Settings -> Database**, copy the connection string (use the pooled "Transaction"
   connection string for Render) -- this is your `POSTGRES_URL`.
3. In the SQL editor, run `CREATE EXTENSION IF NOT EXISTS vector;` once.
4. In **Project Settings -> API**, copy the **Project URL** (`SUPABASE_URL` for the backend,
   `NEXT_PUBLIC_SUPABASE_URL` for the frontend) and the **anon public key**
   (`NEXT_PUBLIC_SUPABASE_ANON_KEY` -- the frontend only, never the backend).
5. Under **Authentication -> URL Configuration**, add your deployed Vercel URL as a redirect URL so
   magic links work in production.
6. Under **Authentication -> Providers -> Email**, magic links ("OTP") are on by default -- no
   password provider needs to be enabled.

### 2. Upstash (Redis)

1. Create a free Redis database at [upstash.com](https://upstash.com).
2. Copy the `rediss://` connection string it gives you -- that's `REDIS_URL`. (The cache is a
   performance optimization, not a dependency the app requires to function: `/health` reports
   Redis as `unavailable` without breaking the rest of the API.)

### 3. Render (backend)

1. Create a new **Web Service**, point it at this repo, and set the root directory to `backend`
   so it builds `backend/Dockerfile`.
2. Set these environment variables on the service:

   | Variable | Value |
   |---|---|
   | `POSTGRES_URL` | Supabase pooled connection string from step 1 |
   | `REDIS_URL` | Upstash connection string from step 2 |
   | `FINNHUB_API_KEY` | Your Finnhub API key |
   | `OPENAI_API_KEY` | Your OpenAI API key (used for news embeddings) |
   | `SUPABASE_URL` | Supabase project URL from step 1 |
   | `SUPABASE_JWT_AUDIENCE` | `authenticated` |
   | `CORS_ORIGINS` | Your Vercel URL, e.g. `https://your-app.vercel.app` |
   | `MARKET_DATA_TIMEOUT_SECONDS` | `15` |
   | `NEWS_TIMEOUT_SECONDS` | `10` |

3. Deploy, then confirm `GET https://<your-render-url>/health` reports `"database": "available"`.
   Migrations run automatically on startup.
4. Run `python backend/scripts/generate_sentiment_anchors.py` once (locally, with `OPENAI_API_KEY`
   set) and commit the resulting `backend/sentiment_anchors.json` -- the sentiment scorer needs it
   at runtime and it doesn't change unless you edit the reference phrases.
5. (Optional, once there are graded-eligible predictions) schedule
   `python backend/backtest_engine.py` to run daily, e.g. with Render's Cron Jobs, so
   `/api/v1/predictions/performance` keeps updating.

### 4. Vercel (frontend)

1. Import this repo into Vercel and set the root directory to `frontend`.
2. Set these environment variables:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |
   | `NEXT_PUBLIC_API_URL` | Your Render backend URL, e.g. `https://your-api.onrender.com` |

3. Deploy. Open the deployed URL on a phone and use "Add to Home Screen" (Safari) or the install
   prompt (Chrome) to install it -- that's the PWA install path this project is built around.

### Smoke test after deploying

1. Open the Vercel URL, sign in with a real email, and follow the magic link.
2. Analyze a ticker (e.g. `AAPL`) and watch it move through queued -> gathering data -> reading
   news -> scoring risk -> a result card.
3. Add it to the watchlist, reload the page, and confirm it's still there (proves the DB write
   path).
4. Check `GET /api/v1/predictions/performance` -- `pending_count` should be at least 1 after the
   analysis above.


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


September Update:

Analysis pipeline:
- Added a deterministic news-sentiment scorer (`sentiment_engine.py`): cosine similarity between
  live news-chunk embeddings and pre-computed bullish/bearish centroid vectors, recency-weighted
  across chunks. No LLM call happens at request time -- it reuses the embeddings the ingestion
  pipeline already stores.
- Added `AnalysisResult.overall_score` and `blend_sentiment()`, which combines the technical score
  (70%) and sentiment score (30%) into one assessment, with an agreement-based confidence
  adjustment and a preserved audit trail of warnings.
- Added `analysis_job_worker.py`: analysis jobs actually run now, driven through the full
  `queued -> gathering_data -> reading_news -> calculating_risk -> complete/failed` state machine,
  with dependency injection for testability and graceful fallback to technical-only analysis if
  news harvesting fails.
- Added `backtest_engine.py` and `GET /api/v1/predictions/performance`: predictions are graded
  against their real closing price 5 days out, and the running hit rate is now queryable instead of
  sitting unused in the schema.

Fixes:
- Fixed a startup-crashing bug in `config.py`: `CORS_ORIGINS` was typed as `list[str]`, but
  pydantic-settings tries to JSON-decode env values for list-typed fields before any validator
  runs -- so the exact value `backend/.env.example` told developers to set crashed the app on
  import. Fixed by parsing it from a plain string via a computed property, with regression tests.

Frontend:
- Replaced the placeholder page with a working single-page app: Supabase magic-link auth, a ticker
  analyzer that polls jobs to completion, a watchlist, and a live accuracy strip.
- Removed Capacitor and the native Android project. Mobile access is now a responsive, installable
  PWA (`manifest.json` + a service worker) instead of a WebView wrapper -- same "check it from your
  phone" outcome, without maintaining a second native build.

Deployment:
- Added `backend/Dockerfile` for Render's free web-service tier, and documented a full free-tier
  deployment path (Supabase + Upstash + Render + Vercel)
