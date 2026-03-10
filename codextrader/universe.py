"""Scenario-aware universe selection and candidate ranking."""

from __future__ import annotations

from .config import UniverseConfig
from .models import TickerSnapshot


def _passes_filters(snapshot: TickerSnapshot, config: UniverseConfig, earnings_buffer_days: int) -> bool:
    if config.market_scope != "us_equities":
        return False
    if snapshot.close < config.min_price:
        return False
    if snapshot.market_cap is not None and snapshot.market_cap < config.min_market_cap:
        return False
    if snapshot.avg_dollar_volume_20 < config.min_avg_dollar_volume:
        return False
    if not config.include_etfs and snapshot.asset_type.upper() == "ETF":
        return False
    if earnings_buffer_days > 0 and snapshot.earnings_date:
        # Date-aware earnings exclusion can be added when provider coverage is reliable.
        pass
    return True


def rank_candidate(snapshot: TickerSnapshot) -> float:
    trend_component = 0.0
    if snapshot.close > snapshot.sma_20 > snapshot.sma_50:
        trend_component = 1.0
    elif snapshot.close < snapshot.sma_20 < snapshot.sma_50:
        trend_component = -0.8

    momentum_component = (snapshot.week_change_pct * 0.35) + (snapshot.month_change_pct * 0.45)
    volume_component = min(snapshot.relative_volume, 3.0) * 1.3
    volatility_penalty = snapshot.volatility_20_pct * 0.18
    day_component = snapshot.day_change_pct * 0.15
    return trend_component + momentum_component + volume_component + day_component - volatility_penalty


def select_candidates(
    snapshots: list[TickerSnapshot],
    config: UniverseConfig,
    earnings_buffer_days: int,
) -> list[TickerSnapshot]:
    filtered = [snapshot for snapshot in snapshots if _passes_filters(snapshot, config, earnings_buffer_days)]
    ranked = sorted(filtered, key=rank_candidate, reverse=True)
    return ranked[: config.max_brief_candidates]
