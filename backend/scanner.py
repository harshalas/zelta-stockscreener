import numpy as np
import pandas as pd
import yfinance as yf


class MarketScannerService:

    def calculate_volatility_and_volume(
        self, price_data: list, window: int = 20
    ):
        if len(price_data) < window:
            return {"error": "Not enough data points to compute metrics."}

        df = pd.DataFrame(price_data)
        df["returns"] = df["close"].pct_change()
        df["volatility"] = (
            df["returns"].rolling(window=window).std() * np.sqrt(252)
        )
        df["avg_volume"] = df["volume"].rolling(window=window).mean()
        df["volume_ratio"] = df["volume"] / df["avg_volume"]

        latest_metrics = df.iloc[-1].to_dict()
        return {
            "current_close": latest_metrics.get("close"),
            "annualized_volatility": latest_metrics.get("volatility"),
            "volume_spike_ratio": latest_metrics.get("volume_ratio"),
        }

    def get_historical_metrics_series(self, price_data: list, window: int = 20):
        if len(price_data) < window:
            return []

        df = pd.DataFrame(price_data)
        df["returns"] = df["close"].pct_change()
        df["volatility"] = (
            df["returns"].rolling(window=window).std() * np.sqrt(252)
        )
        df["avg_volume"] = df["volume"].rolling(window=window).mean()
        df["volume_ratio"] = df["volume"] / df["avg_volume"]

        df = df.dropna(subset=["volatility"])

        history_list = []
        for _, row in df.iterrows():
            history_list.append({
                "date": str(row.get("date", "")),
                "close": float(row["close"]),
                "volatility": (
                    float(row["volatility"])
                    if not pd.isna(row["volatility"])
                    else 0
                ),
                "volume_ratio": (
                    float(row["volume_ratio"])
                    if not pd.isna(row["volume_ratio"])
                    else 0
                ),
            })
        return history_list

    def fetch_yfinance_data(self, symbol: str, period: str = "1mo"):
        """Helper function to cleanly fetch and format historical records."""
        ticker = yf.Ticker(symbol.upper())
        history = ticker.history(period=period)

        if history.empty:
            return []

        return [
            {
                "date": idx.strftime("%Y-%m-%d"),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            }
            for idx, row in history.iterrows()
        ]

    def run_morning_screener(self, tickers: list, volatility_threshold: float):
        """Processes a target batch list and filters out low volatility assets."""
        screened_alerts = {}

        for symbol in tickers:
            price_data = self.fetch_yfinance_data(symbol, period="1mo")
            if len(price_data) < 20:
                continue

            latest_snapshot = self.calculate_volatility_and_volume(price_data)
            current_vol = latest_snapshot.get("annualized_volatility", 0)

            if current_vol >= volatility_threshold:
                full_timeline = self.get_historical_metrics_series(price_data)
                screened_alerts[symbol.upper()] = {
                    "latest_summary": latest_snapshot,
                    "historical_timeline": full_timeline,
                }

        return screened_alerts