from datetime import datetime, timezone
from math import sqrt

import pandas as pd

from analysis_models import AnalysisResult, PriceRiskRange, SourceEvidence, TechnicalIndicators


class DeterministicAnalysisEngine:
    """Produces an explainable assessment from market data without an LLM."""

    MINIMUM_SESSIONS = 50
    NEWS_UNAVAILABLE_WARNING = "News sentiment has not been evaluated for this analysis."
    SENTIMENT_WEIGHT = 0.3

    def analyze(
        self,
        ticker: str,
        records: list[dict],
        *,
        now: datetime | None = None,
    ) -> AnalysisResult:
        generated_at = now or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        frame = self._prepare_frame(records)
        if len(frame) < self.MINIMUM_SESSIONS:
            return AnalysisResult(
                ticker=ticker.upper(),
                status="insufficient_data",
                assessment="Neutral",
                confidence=0,
                technical_score=0,
                risk_level="Unknown",
                reasons=[
                    f"At least {self.MINIMUM_SESSIONS} trading sessions are required; "
                    f"only {len(frame)} were available."
                ],
                indicators=TechnicalIndicators(),
                indicators_used=[],
                data_timestamp=self._latest_timestamp(frame),
                generated_at=generated_at,
                warnings=["No assessment was generated because market data is incomplete."],
            )

        indicators = self._calculate_indicators(frame)
        score, signals = self._score(indicators)
        assessment = "Bullish" if score >= 0.25 else "Bearish" if score <= -0.25 else "Neutral"
        data_timestamp = self._latest_timestamp(frame)
        age_days = (generated_at.date() - data_timestamp.date()).days
        is_stale = age_days > 4

        warnings = [self.NEWS_UNAVAILABLE_WARNING]
        status = "news_unavailable"
        if is_stale:
            status = "market_data_delayed"
            warnings.insert(0, f"Market data is {age_days} days old.")

        annualized_volatility = indicators.annualized_volatility or 0
        risk_level = (
            "Low"
            if annualized_volatility < 0.30
            else "Medium"
            if annualized_volatility < 0.60
            else "High"
        )
        risk_range = None
        if indicators.current_price is not None and indicators.atr_14 is not None:
            risk_range = PriceRiskRange(
                lower=round(max(0, indicators.current_price - (2 * indicators.atr_14)), 2),
                upper=round(indicators.current_price + (2 * indicators.atr_14), 2),
            )

        confidence = self._confidence(signals, score, stale=is_stale)
        return AnalysisResult(
            ticker=ticker.upper(),
            status=status,
            assessment=assessment,
            confidence=confidence,
            technical_score=round(score, 3),
            overall_score=round(score, 3),
            risk_level=risk_level,
            risk_range=risk_range,
            reasons=self._plain_language_reasons(indicators),
            indicators=indicators,
            indicators_used=[
                "20-day and 50-day moving averages",
                "5-day price movement",
                "14-day relative strength index",
                "20-day trading volume comparison",
                "20-day annualized volatility",
                "14-day average true range",
            ],
            data_timestamp=data_timestamp,
            generated_at=generated_at,
            warnings=warnings,
        )

    def blend_sentiment(
        self,
        result: AnalysisResult,
        *,
        sentiment_score: float | None,
        chunk_count: int,
        sources: list[SourceEvidence],
    ) -> AnalysisResult:
        """Fold a vector-similarity news-sentiment score into a technical-only result.

        This is intentionally a separate step from `analyze`, not baked into
        it: scoring sentiment requires news that has already been harvested
        and embedded (a network round trip), which the fast
        `/analysis/preview` endpoint deliberately skips. Only the full
        analysis-job worker calls this, after its "reading_news" stage, so
        the cheap synchronous preview path never pays that cost.

        `technical_score` is left untouched so callers can always see the
        pure-technical figure the engine computed; `overall_score` is what
        actually drives `assessment` once sentiment is folded in.
        """
        if sentiment_score is None or chunk_count == 0:
            return result

        overall_score = max(
            -1.0,
            min(
                1.0,
                (1 - self.SENTIMENT_WEIGHT) * result.technical_score
                + self.SENTIMENT_WEIGHT * sentiment_score,
            ),
        )
        assessment = (
            "Bullish" if overall_score >= 0.25 else "Bearish" if overall_score <= -0.25 else "Neutral"
        )

        technical_leans_same_way = (result.technical_score > 0) == (sentiment_score > 0)
        agreement_bonus = 0.05 if technical_leans_same_way and sentiment_score != 0 else 0.0
        confidence = round(min(0.95, result.confidence + agreement_bonus), 2)

        status = "complete" if result.status == "news_unavailable" else result.status
        warnings = [warning for warning in result.warnings if warning != self.NEWS_UNAVAILABLE_WARNING]

        sentiment_label = (
            "bullish" if sentiment_score > 0.1 else "bearish" if sentiment_score < -0.1 else "mixed"
        )
        reasons = [
            *result.reasons,
            f"Recent news coverage ({chunk_count} article{'s' if chunk_count != 1 else ''}) "
            f"skews {sentiment_label}.",
        ]

        return result.model_copy(
            update={
                "status": status,
                "assessment": assessment,
                "confidence": confidence,
                "overall_score": round(overall_score, 3),
                "macro_sentiment_score": round(sentiment_score, 3),
                "reasons": reasons,
                "indicators_used": [
                    *result.indicators_used,
                    "News sentiment (vector similarity to labeled reference headlines)",
                ],
                "sources": sources,
                "warnings": warnings,
            }
        )

    @staticmethod
    def _prepare_frame(records: list[dict]) -> pd.DataFrame:
        frame = pd.DataFrame(records)
        required = {"date", "close", "high", "low", "volume"}
        if frame.empty or not required.issubset(frame.columns):
            return pd.DataFrame(columns=sorted(required))
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
        for column in ("close", "high", "low", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna(subset=list(required)).sort_values("date").drop_duplicates("date")

    @staticmethod
    def _latest_timestamp(frame: pd.DataFrame) -> datetime | None:
        if frame.empty or "date" not in frame:
            return None
        value = frame["date"].max()
        return value.to_pydatetime() if not pd.isna(value) else None

    @staticmethod
    def _calculate_indicators(frame: pd.DataFrame) -> TechnicalIndicators:
        close = frame["close"]
        returns = close.pct_change()
        delta = close.diff()
        gains = delta.clip(lower=0).rolling(14).mean()
        losses = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gains / losses.replace(0, float("nan"))
        rsi = 100 - (100 / (1 + rs))
        if losses.iloc[-1] == 0:
            rsi_value = 100.0 if gains.iloc[-1] > 0 else 50.0
        else:
            rsi_value = float(rsi.iloc[-1])

        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                frame["high"] - frame["low"],
                (frame["high"] - previous_close).abs(),
                (frame["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        volume_average = frame["volume"].tail(20).mean()

        return TechnicalIndicators(
            current_price=round(float(close.iloc[-1]), 2),
            daily_change_pct=round(float((close.iloc[-1] / close.iloc[-2] - 1) * 100), 2),
            five_day_change_pct=round(float((close.iloc[-1] / close.iloc[-6] - 1) * 100), 2),
            sma_20=round(float(close.tail(20).mean()), 2),
            sma_50=round(float(close.tail(50).mean()), 2),
            rsi_14=round(rsi_value, 2),
            volume_ratio_20d=round(float(frame["volume"].iloc[-1] / volume_average), 2),
            annualized_volatility=round(float(returns.tail(20).std() * sqrt(252)), 4),
            atr_14=round(float(true_range.tail(14).mean()), 2),
        )

    @staticmethod
    def _score(indicators: TechnicalIndicators) -> tuple[float, list[int]]:
        signals: list[int] = []
        score = 0.0

        trend = 1 if indicators.sma_20 > indicators.sma_50 else -1 if indicators.sma_20 < indicators.sma_50 else 0
        score += trend * 0.30
        signals.append(trend)

        price_trend = 1 if indicators.current_price > indicators.sma_20 else -1 if indicators.current_price < indicators.sma_20 else 0
        score += price_trend * 0.20
        signals.append(price_trend)

        movement = 1 if indicators.five_day_change_pct >= 2 else -1 if indicators.five_day_change_pct <= -2 else 0
        score += movement * 0.25
        signals.append(movement)

        rsi_signal = 1 if 55 <= indicators.rsi_14 <= 70 else -1 if 30 <= indicators.rsi_14 <= 45 else 0
        if indicators.rsi_14 > 75:
            rsi_signal = -1
        elif indicators.rsi_14 < 25:
            rsi_signal = 1
        score += rsi_signal * 0.15
        signals.append(rsi_signal)

        if indicators.volume_ratio_20d >= 1.5 and movement:
            score += movement * 0.10

        return max(-1.0, min(1.0, score)), signals

    @staticmethod
    def _confidence(signals: list[int], score: float, *, stale: bool) -> float:
        non_zero = [signal for signal in signals if signal]
        agreement = 0.5
        if non_zero:
            agreement = max(non_zero.count(1), non_zero.count(-1)) / len(non_zero)
        freshness = 0 if stale else 1
        confidence = 0.35 + (0.25 * freshness) + (0.25 * agreement) + (0.15 * abs(score))
        return round(min(confidence, 0.95), 2)

    @staticmethod
    def _plain_language_reasons(indicators: TechnicalIndicators) -> list[str]:
        trend = (
            "The recent price trend is above its longer-term average."
            if indicators.sma_20 > indicators.sma_50
            else "The recent price trend is below its longer-term average."
            if indicators.sma_20 < indicators.sma_50
            else "The recent and longer-term price trends are aligned."
        )
        movement = (
            f"The price rose {abs(indicators.five_day_change_pct):.1f}% over the last five trading sessions."
            if indicators.five_day_change_pct > 0.5
            else f"The price fell {abs(indicators.five_day_change_pct):.1f}% over the last five trading sessions."
            if indicators.five_day_change_pct < -0.5
            else "The price was mostly unchanged over the last five trading sessions."
        )
        volume = (
            "Recent trading volume is unusually high."
            if indicators.volume_ratio_20d >= 1.5
            else "Recent trading volume is close to its normal range."
        )
        strength = (
            "Recent price gains may be overextended."
            if indicators.rsi_14 > 75
            else "Recent price losses may be overextended."
            if indicators.rsi_14 < 25
            else "Recent price strength is not at an extreme."
        )
        return [trend, movement, volume, strength]
