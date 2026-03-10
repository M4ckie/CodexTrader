"""AI-style signal model based on multiple market features."""

from __future__ import annotations

import math
import statistics

from .config import BotConfig
from .models import Candle, Signal


def _safe_pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def score_ticker(history: list[Candle], cfg: BotConfig) -> Signal | None:
    """Generate one signal from candle history."""
    if len(history) < 25:
        return None

    closes = [c.close for c in history]
    volumes = [c.volume for c in history]
    current = closes[-1]
    sma_5 = statistics.fmean(closes[-5:])
    sma_20 = statistics.fmean(closes[-20:])
    momentum_5 = _safe_pct_change(current, closes[-6])
    momentum_20 = _safe_pct_change(current, closes[-21])
    volatility_20 = statistics.pstdev(closes[-20:]) / sma_20 if sma_20 else 0.0
    trend_gap = _safe_pct_change(current, sma_20)
    volume_ratio = volumes[-1] / max(1, int(statistics.fmean(volumes[-20:])))

    raw_score = (
        momentum_5 * 0.9
        + momentum_20 * 1.4
        + trend_gap * 1.2
        + (volume_ratio - 1.0) * 0.12
        - volatility_20 * 0.8
        + (_safe_pct_change(sma_5, sma_20) * 0.8)
    )

    score = math.tanh(raw_score * cfg.confidence_scale * 4.0)
    confidence = _clamp((abs(score) + abs(momentum_20) * 2.0 + max(0.0, volume_ratio - 1.0) * 0.1), 0.05, 0.99)

    if score >= cfg.buy_threshold:
        action = "BUY"
    elif score <= cfg.sell_threshold:
        action = "SELL"
    else:
        action = "HOLD"

    reason = (
        f"mom5={momentum_5:.2%}, mom20={momentum_20:.2%}, "
        f"trend_gap={trend_gap:.2%}, vol20={volatility_20:.2%}, "
        f"volume_ratio={volume_ratio:.2f}"
    )
    return Signal(ticker=history[-1].ticker, score=score, confidence=confidence, action=action, reason=reason)


def rank_signals(market_slice: dict[str, list[Candle]], cfg: BotConfig) -> list[Signal]:
    """Score all tickers and return strongest signals first."""
    signals = []
    for history in market_slice.values():
        signal = score_ticker(history, cfg)
        if signal:
            signals.append(signal)

    return sorted(signals, key=lambda item: (item.action != "BUY", -abs(item.score), -item.confidence, item.ticker))
