from datetime import date, timedelta
from uuid import uuid4

import psycopg2
import pytest

import backtest_engine
from config import get_settings


def test_grade_prediction_marks_correct_direction_and_low_error():
    prediction = {"id": 1, "ticker": "AAPL", "current_price": 100.0, "predicted_price": 110.0, "target_eval_date": date.today()}
    result = backtest_engine.grade_prediction(prediction, fetch_price=lambda ticker, as_of: 112.0)

    assert result is not None
    assert result.is_correct_direction is True
    assert result.absolute_error_pct == pytest.approx(2.0)  # |112-110|/100 * 100


def test_grade_prediction_marks_wrong_direction():
    # Model predicted a rise (110 > 100) but the stock actually fell.
    prediction = {"id": 2, "ticker": "MSFT", "current_price": 100.0, "predicted_price": 110.0, "target_eval_date": date.today()}
    result = backtest_engine.grade_prediction(prediction, fetch_price=lambda ticker, as_of: 95.0)

    assert result is not None
    assert result.is_correct_direction is False
    assert result.absolute_error_pct == pytest.approx(15.0)


def test_grade_prediction_returns_none_when_no_market_data_available():
    prediction = {"id": 3, "ticker": "NEWLY-LISTED", "current_price": 10.0, "predicted_price": 11.0, "target_eval_date": date.today()}
    result = backtest_engine.grade_prediction(prediction, fetch_price=lambda ticker, as_of: None)
    assert result is None


def _insert_due_prediction(ticker: str, *, current_price: float, predicted_price: float, days_ago: int = 5) -> int:
    with psycopg2.connect(get_settings().postgres_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO predictions (ticker, current_price, predicted_price, target_eval_date)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (ticker, current_price, predicted_price, date.today() - timedelta(days=days_ago)),
        )
        return cursor.fetchone()[0]


def test_run_grades_due_predictions_end_to_end(require_postgres):
    ticker = f"TEST{uuid4().hex[:6].upper()}"
    prediction_id = _insert_due_prediction(ticker, current_price=100.0, predicted_price=105.0)

    graded = backtest_engine.run(fetch_price=lambda t, as_of: 108.0)

    graded_ids = {item.prediction_id for item in graded}
    assert prediction_id in graded_ids

    with psycopg2.connect(get_settings().postgres_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_evaluated, is_correct_direction, actual_close_price FROM predictions WHERE id = %s",
            (prediction_id,),
        )
        row = cursor.fetchone()
        assert row[0] is True
        assert row[1] is True
        assert float(row[2]) == pytest.approx(108.0)


def test_run_skips_predictions_not_yet_due(require_postgres):
    ticker = f"TEST{uuid4().hex[:6].upper()}"
    future_id = _insert_due_prediction(ticker, current_price=50.0, predicted_price=55.0, days_ago=-2)

    graded = backtest_engine.run(fetch_price=lambda t, as_of: 60.0)

    assert future_id not in {item.prediction_id for item in graded}
