// Typed fetch helpers for the Zelta FastAPI backend. Every shape here is
// taken directly from the backend source (analysis_models.py, domain.py,
// product_repository.py, database.py) rather than guessed, so a change on
// one side is easy to diff against the other.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AnalysisJobStatus =
  | "queued"
  | "gathering_data"
  | "reading_news"
  | "calculating_risk"
  | "complete"
  | "failed";

export type Assessment = "Bullish" | "Neutral" | "Bearish";
export type RiskLevel = "Low" | "Medium" | "High" | "Unknown";

export interface SourceEvidence {
  title: string;
  url: string;
  published_at: string | null;
}

export interface TechnicalIndicators {
  current_price: number | null;
  daily_change_pct: number | null;
  five_day_change_pct: number | null;
  sma_20: number | null;
  sma_50: number | null;
  rsi_14: number | null;
  volume_ratio_20d: number | null;
  annualized_volatility: number | null;
  atr_14: number | null;
}

export interface PriceRiskRange {
  lower: number;
  upper: number;
}

export interface AnalysisResult {
  ticker: string;
  status:
    | "complete"
    | "insufficient_data"
    | "news_unavailable"
    | "market_data_delayed"
    | "failed";
  assessment: Assessment;
  confidence: number;
  technical_score: number;
  macro_sentiment_score: number | null;
  overall_score: number;
  risk_level: RiskLevel;
  risk_range: PriceRiskRange | null;
  reasons: string[];
  indicators: TechnicalIndicators;
  indicators_used: string[];
  data_timestamp: string | null;
  generated_at: string;
  sources: SourceEvidence[];
  warnings: string[];
  model_version: string;
  disclaimer: string;
}

export interface AnalysisJob {
  id: string;
  ticker: string;
  status: AnalysisJobStatus;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: AnalysisResult | null;
}

export interface WatchlistItem {
  id: string;
  ticker: string;
  company_name: string | null;
  created_at: string;
}

export interface Watchlist {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  items: WatchlistItem[];
}

export interface PerformanceSummary {
  evaluated_count: number;
  pending_count: number;
  correct_count: number;
  hit_rate: number | null;
  avg_absolute_error_pct: number | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  accessToken: string | null,
  init?: RequestInit
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // body wasn't JSON -- fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export function createAnalysisJob(
  accessToken: string,
  ticker: string
): Promise<AnalysisJob> {
  return request<AnalysisJob>("/api/v1/analysis-jobs", accessToken, {
    method: "POST",
    body: JSON.stringify({ ticker }),
  });
}

export function getAnalysisJob(
  accessToken: string,
  jobId: string
): Promise<AnalysisJob> {
  return request<AnalysisJob>(`/api/v1/analysis-jobs/${jobId}`, accessToken);
}

export function getWatchlist(accessToken: string): Promise<Watchlist> {
  return request<Watchlist>("/api/v1/watchlist", accessToken);
}

export function addWatchlistItem(
  accessToken: string,
  ticker: string,
  companyName?: string
): Promise<WatchlistItem> {
  return request<WatchlistItem>("/api/v1/watchlist/items", accessToken, {
    method: "POST",
    body: JSON.stringify({ ticker, company_name: companyName ?? null }),
  });
}

export function removeWatchlistItem(
  accessToken: string,
  ticker: string
): Promise<void> {
  return request<void>(
    `/api/v1/watchlist/items/${encodeURIComponent(ticker)}`,
    accessToken,
    { method: "DELETE" }
  );
}

export function getPerformanceSummary(): Promise<PerformanceSummary> {
  return request<PerformanceSummary>("/api/v1/predictions/performance", null);
}

/** Human-readable label for each state in the analysis job state machine. */
export const JOB_STATUS_LABEL: Record<AnalysisJobStatus, string> = {
  queued: "Queued",
  gathering_data: "Pulling market data",
  reading_news: "Reading recent news",
  calculating_risk: "Scoring risk",
  complete: "Complete",
  failed: "Failed",
};

/** Polls an analysis job until it reaches a terminal state (complete/failed). */
export async function pollAnalysisJob(
  accessToken: string,
  jobId: string,
  onUpdate: (job: AnalysisJob) => void,
  { intervalMs = 1500, timeoutMs = 120000 } = {}
): Promise<AnalysisJob> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const job = await getAnalysisJob(accessToken, jobId);
    onUpdate(job);
    if (job.status === "complete" || job.status === "failed") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Timed out waiting for analysis to finish.");
}
