"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  AnalysisJob,
  JOB_STATUS_LABEL,
  PerformanceSummary,
  Watchlist,
  addWatchlistItem,
  createAnalysisJob,
  getPerformanceSummary,
  getWatchlist,
  pollAnalysisJob,
  removeWatchlistItem,
} from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

// ---------------------------------------------------------------------------
// Small formatting helpers. Kept local since they're one-liners used only
// on this page -- pulling in a date/number library for this would be
// overkill for a screen this size.
// ---------------------------------------------------------------------------

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  return `$${value.toFixed(2)}`;
}

function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  return value.toFixed(2);
}

const ASSESSMENT_COLOR: Record<string, string> = {
  Bullish: "#4ade80",
  Bearish: "#f87171",
  Neutral: "#9ca3af",
};

/** score is -1..1. Returns the {left, width} (in %) of a fill bar drawn
 * from the 50% center mark out toward the score's sign. */
function scoreBarGeometry(score: number): { left: number; width: number } {
  const clamped = Math.max(-1, Math.min(1, score));
  const halfWidth = Math.abs(clamped / 2) * 100;
  return clamped >= 0
    ? { left: 50, width: halfWidth }
    : { left: 50 - halfWidth, width: halfWidth };
}

// ---------------------------------------------------------------------------
// Sign-in gate
// ---------------------------------------------------------------------------

function SignInGate({
  signInWithMagicLink,
}: {
  signInWithMagicLink: (email: string) => Promise<{ error: string | null }>;
}) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus("sending");
    setError(null);
    const { error: sendError } = await signInWithMagicLink(email);
    if (sendError) {
      setError(sendError);
      setStatus("error");
      return;
    }
    setStatus("sent");
  }

  return (
    <div className="flex items-center justify-center min-h-[80vh] px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold text-[#e2e4ea] tracking-widest mb-1">
          Zelta
        </h1>
        <p className="text-sm text-[#6b7280] mb-8">
          Technical + news-sentiment stock analysis. Sign in with your email
          to get a one-tap link -- no password to remember.
        </p>

        {status === "sent" ? (
          <div className="rounded-lg border border-[#2a2d35] bg-[#12141a] px-4 py-4 text-sm text-[#c8ccd6]">
            Check <span className="text-[#e2e4ea]">{email}</span> for a sign-in
            link. You can close this tab.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-[#2a2d35] bg-[#12141a] px-4 py-3 text-base text-[#e2e4ea] placeholder-[#4b5563] outline-none focus:border-[#4ade80]"
              autoComplete="email"
              inputMode="email"
            />
            <button
              type="submit"
              disabled={status === "sending"}
              className="w-full rounded-lg bg-[#4ade80] px-4 py-3 text-base font-medium text-[#0d0f14] disabled:opacity-50"
            >
              {status === "sending" ? "Sending..." : "Send sign-in link"}
            </button>
            {error && <p className="text-sm text-[#f87171]">{error}</p>}
          </form>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Performance strip -- the backtested accuracy number. Public, no auth
// needed, so it renders even before sign-in gates the rest of the app.
// ---------------------------------------------------------------------------

function PerformanceStrip() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getPerformanceSummary()
      .then(setSummary)
      .catch(() => setFailed(true));
  }, []);

  if (failed) return null;
  if (!summary) {
    return (
      <div className="px-4 py-2 text-xs text-[#4b5563] border-b border-[#2a2d35]">
        Loading model performance...
      </div>
    );
  }

  if (summary.evaluated_count === 0) {
    return (
      <div className="px-4 py-2 text-xs text-[#4b5563] border-b border-[#2a2d35]">
        No predictions have reached their 5-day evaluation window yet.
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4 px-4 py-2 text-xs border-b border-[#2a2d35] overflow-x-auto whitespace-nowrap">
      <span className="text-[#6b7280]">
        Backtested hit rate:{" "}
        <span className="text-[#e2e4ea] font-medium">
          {summary.hit_rate !== null ? `${(summary.hit_rate * 100).toFixed(0)}%` : "--"}
        </span>
      </span>
      <span className="text-[#6b7280]">
        Avg. error:{" "}
        <span className="text-[#e2e4ea] font-medium">
          {summary.avg_absolute_error_pct !== null
            ? `${summary.avg_absolute_error_pct.toFixed(1)}%`
            : "--"}
        </span>
      </span>
      <span className="text-[#6b7280]">
        Graded:{" "}
        <span className="text-[#e2e4ea] font-medium">{summary.evaluated_count}</span>
      </span>
      <span className="text-[#6b7280]">
        Pending:{" "}
        <span className="text-[#e2e4ea] font-medium">{summary.pending_count}</span>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analysis result card
// ---------------------------------------------------------------------------

function ResultCard({ job }: { job: AnalysisJob }) {
  const result = job.result;
  if (!result) return null;
  const color = ASSESSMENT_COLOR[result.assessment] ?? "#9ca3af";

  return (
    <div className="rounded-lg border border-[#2a2d35] bg-[#12141a] p-4 flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-[#6b7280] uppercase tracking-wide">
            {result.ticker}
          </p>
          <p className="text-2xl font-semibold" style={{ color }}>
            {result.assessment}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-[#6b7280]">confidence</p>
          <p className="text-lg text-[#e2e4ea]">
            {(result.confidence * 100).toFixed(0)}%
          </p>
        </div>
      </div>

      <div className="flex gap-6 text-sm">
        <div>
          <p className="text-[#6b7280]">Price</p>
          <p className="text-[#e2e4ea]">{formatPrice(result.indicators.current_price)}</p>
        </div>
        <div>
          <p className="text-[#6b7280]">5-day change</p>
          <p className="text-[#e2e4ea]">{formatPct(result.indicators.five_day_change_pct)}</p>
        </div>
        <div>
          <p className="text-[#6b7280]">Risk</p>
          <p className="text-[#e2e4ea]">{result.risk_level}</p>
        </div>
      </div>

      {/* Technical vs. sentiment score bars */}
      <div className="flex flex-col gap-2">
        <ScoreBar label="Technical" score={result.technical_score} />
        {result.macro_sentiment_score !== null && (
          <ScoreBar label="News sentiment" score={result.macro_sentiment_score} />
        )}
        <ScoreBar label="Overall" score={result.overall_score} />
      </div>

      {result.risk_range && (
        <div className="text-sm text-[#c8ccd6]">
          Directional range:{" "}
          <span className="text-[#e2e4ea]">
            {formatPrice(result.risk_range.lower)} - {formatPrice(result.risk_range.upper)}
          </span>
        </div>
      )}

      {result.reasons.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm text-[#c8ccd6]">
          {result.reasons.map((reason, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-[#4b5563]">-</span>
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      )}

      {result.warnings.length > 0 && (
        <div className="flex flex-col gap-1">
          {result.warnings.map((warning, i) => (
            <p key={i} className="text-xs text-[#facc15]">
              {warning}
            </p>
          ))}
        </div>
      )}

      {result.sources.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-[#2a2d35] pt-3">
          <p className="text-xs text-[#6b7280] uppercase tracking-wide mb-1">
            Sources
          </p>
          {result.sources.slice(0, 5).map((source, i) => (
            <a
              key={i}
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-[#93c5fd] truncate hover:underline"
            >
              {source.title}
            </a>
          ))}
        </div>
      )}

      <p className="text-xs text-[#4b5563] border-t border-[#2a2d35] pt-3">
        {result.disclaimer}
      </p>
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  const { left, width } = scoreBarGeometry(score);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 shrink-0 text-[#6b7280]">{label}</span>
      <div className="relative flex-1 h-2 rounded-full bg-[#1c1f27] overflow-hidden">
        <div className="absolute inset-y-0 left-1/2 w-px bg-[#2a2d35]" />
        <div
          className="absolute inset-y-0 h-2 rounded-full"
          style={{
            left: `${left}%`,
            width: `${width}%`,
            background: score >= 0 ? "#4ade80" : "#f87171",
          }}
        />
      </div>
      <span className="w-10 shrink-0 text-right text-[#c8ccd6]">
        {formatScore(score)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ticker analyzer -- creates a job, polls it, renders progress + result
// ---------------------------------------------------------------------------

function TickerAnalyzer({
  accessToken,
  initialTicker,
  onAnalyzed,
}: {
  accessToken: string;
  initialTicker?: string;
  onAnalyzed?: () => void;
}) {
  // The parent remounts this component (via `key`) whenever a new ticker is
  // picked from the watchlist, so `initialTicker` only needs to seed state
  // once per mount rather than being tracked as a changing prop.
  const [ticker, setTicker] = useState(initialTicker ?? "");
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const runAnalysis = useCallback(
    async (symbol: string) => {
      setSubmitting(true);
      setError(null);
      setJob(null);
      try {
        const created = await createAnalysisJob(accessToken, symbol);
        setJob(created);
        await pollAnalysisJob(accessToken, created.id, setJob);
        onAnalyzed?.();
      } catch (err) {
        // ApiError and the polling timeout error both carry a real message
        // (e.g. "Timed out waiting for analysis to finish.") -- surfacing
        // it beats a generic "try again" that hides what actually happened.
        setError(err instanceof Error ? err.message : "Analysis failed. Try again.");
      } finally {
        setSubmitting(false);
      }
    },
    [accessToken, onAnalyzed]
  );

  useEffect(() => {
    if (!initialTicker) return;
    // Deferred to a callback (rather than invoked synchronously in the
    // effect body) so the state updates inside runAnalysis happen outside
    // React's render phase -- see react-hooks/set-state-in-effect.
    const timer = setTimeout(() => runAnalysis(initialTicker), 0);
    return () => clearTimeout(timer);
    // Runs once per mount -- see the note on `ticker` state above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return;
    runAnalysis(symbol);
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Ticker, e.g. AAPL"
          className="flex-1 min-w-0 rounded-lg border border-[#2a2d35] bg-[#12141a] px-4 py-3 text-base text-[#e2e4ea] placeholder-[#4b5563] outline-none focus:border-[#4ade80] uppercase"
          maxLength={10}
        />
        <button
          type="submit"
          disabled={submitting}
          className="shrink-0 rounded-lg bg-[#4ade80] px-5 py-3 text-base font-medium text-[#0d0f14] disabled:opacity-50"
        >
          Analyze
        </button>
      </form>

      {job && job.status !== "complete" && job.status !== "failed" && (
        <div className="flex items-center gap-2 text-sm text-[#9ca3af]">
          <span className="inline-block h-2 w-2 rounded-full bg-[#4ade80] animate-pulse" />
          {JOB_STATUS_LABEL[job.status]}...
        </div>
      )}

      {job && job.status === "failed" && (
        <p className="text-sm text-[#f87171]">
          {job.error_message ?? "Analysis job failed."}
        </p>
      )}

      {error && <p className="text-sm text-[#f87171]">{error}</p>}

      {job && job.status === "complete" && <ResultCard job={job} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Watchlist
// ---------------------------------------------------------------------------

function WatchlistSection({
  accessToken,
  onSelectTicker,
}: {
  accessToken: string;
  onSelectTicker: (ticker: string) => void;
}) {
  const [watchlist, setWatchlist] = useState<Watchlist | null>(null);
  const [newTicker, setNewTicker] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getWatchlist(accessToken)
      .then(setWatchlist)
      .catch(() => setError("Couldn't load your watchlist."));
  }, [accessToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    const symbol = newTicker.trim().toUpperCase();
    if (!symbol) return;
    setError(null);
    try {
      await addWatchlistItem(accessToken, symbol);
      setNewTicker("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add ticker.");
    }
  }

  async function handleRemove(symbol: string) {
    setError(null);
    try {
      await removeWatchlistItem(accessToken, symbol);
      refresh();
    } catch {
      setError("Couldn't remove ticker.");
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-xs text-[#6b7280] uppercase tracking-wide">Watchlist</h2>
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          value={newTicker}
          onChange={(e) => setNewTicker(e.target.value)}
          placeholder="Add ticker"
          className="flex-1 min-w-0 rounded-lg border border-[#2a2d35] bg-[#12141a] px-3 py-2 text-sm text-[#e2e4ea] placeholder-[#4b5563] outline-none focus:border-[#4ade80] uppercase"
          maxLength={10}
        />
        <button
          type="submit"
          className="shrink-0 rounded-lg border border-[#2a2d35] px-3 py-2 text-sm text-[#c8ccd6]"
        >
          Add
        </button>
      </form>

      {error && <p className="text-xs text-[#f87171]">{error}</p>}

      {watchlist && watchlist.items.length === 0 && (
        <p className="text-sm text-[#4b5563]">No tickers yet.</p>
      )}

      <div className="flex flex-col gap-1">
        {watchlist?.items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between rounded-lg border border-[#2a2d35] px-3 py-2"
          >
            <button
              onClick={() => onSelectTicker(item.ticker)}
              className="text-sm text-[#e2e4ea] hover:text-[#4ade80]"
            >
              {item.ticker}
            </button>
            <button
              onClick={() => handleRemove(item.ticker)}
              className="text-xs text-[#4b5563] hover:text-[#f87171]"
              aria-label={`Remove ${item.ticker}`}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root page
// ---------------------------------------------------------------------------

export default function Home() {
  const { configured, loading, session, signInWithMagicLink, signOut } = useAuth();
  const [selectedTicker, setSelectedTicker] = useState<string | undefined>(undefined);
  const [selectionKey, setSelectionKey] = useState(0);

  function handleSelectTicker(ticker: string) {
    setSelectedTicker(ticker);
    setSelectionKey((key) => key + 1);
  }

  return (
    <main className="min-h-screen bg-[#0d0f14] text-[#c8ccd6] font-mono">
      <nav className="flex items-center justify-between px-4 h-11 border-b border-[#2a2d35] bg-[#0a0c10]">
        <span className="text-sm font-medium text-[#e2e4ea] tracking-widest">Zelta</span>
        {session ? (
          <button onClick={signOut} className="text-xs text-[#6b7280] hover:text-[#e2e4ea]">
            Sign out
          </button>
        ) : (
          <span className="text-xs text-[#6b7280]">dashboard</span>
        )}
      </nav>

      <PerformanceStrip />

      {!configured ? (
        <div className="px-4 py-8 text-sm text-[#facc15] max-w-lg mx-auto">
          Supabase isn&apos;t configured yet. Set NEXT_PUBLIC_SUPABASE_URL and
          NEXT_PUBLIC_SUPABASE_ANON_KEY in your environment (see
          .env.local.example) to enable sign-in.
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center min-h-[70vh] text-sm text-[#4b5563]">
          Loading...
        </div>
      ) : !session ? (
        <SignInGate signInWithMagicLink={signInWithMagicLink} />
      ) : (
        <div className="max-w-lg mx-auto px-4 py-6 flex flex-col gap-8">
          <TickerAnalyzer
            key={selectionKey}
            accessToken={session.access_token}
            initialTicker={selectedTicker}
          />
          <WatchlistSection
            accessToken={session.access_token}
            onSelectTicker={handleSelectTicker}
          />
        </div>
      )}
    </main>
  );
}
