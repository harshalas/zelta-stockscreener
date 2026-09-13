from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AnalysisStatus = Literal[
    "complete",
    "insufficient_data",
    "news_unavailable",
    "market_data_delayed",
    "failed",
]
Assessment = Literal["Bullish", "Neutral", "Bearish"]
RiskLevel = Literal["Low", "Medium", "High", "Unknown"]


class SourceEvidence(BaseModel):
    title: str
    url: str
    published_at: datetime | None = None


class TechnicalIndicators(BaseModel):
    current_price: float | None = None
    daily_change_pct: float | None = None
    five_day_change_pct: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    rsi_14: float | None = None
    volume_ratio_20d: float | None = None
    annualized_volatility: float | None = None
    atr_14: float | None = None


class PriceRiskRange(BaseModel):
    lower: float
    upper: float


class AnalysisResult(BaseModel):
    ticker: str
    status: AnalysisStatus
    assessment: Assessment
    confidence: float = Field(ge=0, le=1)
    technical_score: float = Field(ge=-1, le=1)
    macro_sentiment_score: float | None = Field(None, ge=-1, le=1)
    overall_score: float = Field(ge=-1, le=1, default=0)
    risk_level: RiskLevel
    risk_range: PriceRiskRange | None = None
    reasons: list[str]
    indicators: TechnicalIndicators
    indicators_used: list[str]
    data_timestamp: datetime | None
    generated_at: datetime
    sources: list[SourceEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_version: str = "deterministic-v1"
    disclaimer: str = (
        "For informational purposes only. This is not financial advice or a "
        "recommendation to buy or sell any security."
    )
