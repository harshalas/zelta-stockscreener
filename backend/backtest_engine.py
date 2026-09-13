"""Grade predictions whose 5-day evaluation window has arrived against what
the stock actually did, using real yfinance closes.

The `predictions` table has carried target_eval_date, actual_close_price,
absolute_error_pct, and is_correct_direction columns since this project's
July migrations -- but nothing ever populated them. This is that missing
piece, built exactly the way this project's own early planning notes said
to build it: "Phase 1: a standalone script, run manually, get the queries
and the accuracy math right before automating it."

Run it manually:

    cd backend
    python backtest_engine.py

Or on a schedule once a day (a Render Cron Job, a plain OS cron entry, a
GitHub Actions scheduled workflow -- anything that can run one command).
It's idempotent-ish: predictions are only graded once (is_evaluated flips
to true), so running it more often than needed just does no extra work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable

import yfinance as yf

from database import fetch_due_predictions, record_backtest_result

logger = logging.getLogger(__name__)

PriceFetcher = Callable[[str, date], float | None]


@dataclass(frozen=True)
class GradedPrediction:
    prediction_id: int
    ticker: str
    actual_close_price: float
    absolute_error_pct: float
    is_correct_direction: bool


def _default_price_fetcher(ticker: str, as_of: date) -> float | None:
    """Closing price at or shortly after `as_of` (falls back to the most
    recent available close if `as_of` hasn't traded yet, e.g. it's a
    weekend/holiday, or the script runs slightly before market close)."""
    history = yf.Ticker(ticker).history(start=as_of.isoformat(), period="5d")
    if history.empty:
        history = yf.Ticker(ticker).history(period="10d")
    if history.empty:
        return None
    return float(history["Close"].iloc[-1])


def grade_prediction(prediction: dict, *, fetch_price: PriceFetcher) -> GradedPrediction | None:
    """Returns None (rather than raising) when market data isn't available
    yet -- the prediction is simply left unevaluated and picked up on a
    later run, instead of the whole batch failing over one bad ticker."""
    actual_close_price = fetch_price(prediction["ticker"], prediction["target_eval_date"])
    if actual_close_price is None:
        logger.warning(
            "No market data yet for %s on %s; prediction %s stays unevaluated.",
            prediction["ticker"],
            prediction["target_eval_date"],
            prediction["id"],
        )
        return None

    current_price = float(prediction["current_price"])
    predicted_price = float(prediction["predicted_price"])

    # Error is expressed as a percentage of the price at prediction time,
    # not of the (possibly near-zero) predicted move -- that keeps the
    # metric stable and comparable across tickers of very different prices.
    absolute_error_pct = round(abs(actual_close_price - predicted_price) / current_price * 100, 2)
    predicted_up = predicted_price > current_price
    actual_up = actual_close_price > current_price

    return GradedPrediction(
        prediction_id=prediction["id"],
        ticker=prediction["ticker"],
        actual_close_price=actual_close_price,
        absolute_error_pct=absolute_error_pct,
        is_correct_direction=predicted_up == actual_up,
    )


def run(*, fetch_price: PriceFetcher = _default_price_fetcher, as_of: date | None = None) -> list[GradedPrediction]:
    due = fetch_due_predictions(as_of=as_of or date.today())
    graded: list[GradedPrediction] = []
    for prediction in due:
        result = grade_prediction(prediction, fetch_price=fetch_price)
        if result is None:
            continue
        record_backtest_result(
            result.prediction_id,
            actual_close_price=result.actual_close_price,
            absolute_error_pct=result.absolute_error_pct,
            is_correct_direction=result.is_correct_direction,
        )
        graded.append(result)
    return graded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run()
    print(f"Evaluated {len(results)} prediction(s) due for grading.")
    for item in results:
        verdict = "correct" if item.is_correct_direction else "wrong"
        print(
            f"  {item.ticker}: {verdict} direction, "
            f"{item.absolute_error_pct}% off target (actual close {item.actual_close_price})"
        )
