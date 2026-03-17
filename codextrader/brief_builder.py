"""Builds compact end-of-day briefs for OpenAI."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from .models import DailyBrief, TickerSnapshot


def _ticker_summary(snapshot: TickerSnapshot) -> dict:
    return {
        "ticker": snapshot.ticker,
        "as_of": snapshot.as_of,
        "open": snapshot.open,
        "high": snapshot.high,
        "low": snapshot.low,
        "close": snapshot.close,
        "returns": {
            "day_pct": snapshot.day_change_pct,
            "week_pct": snapshot.week_change_pct,
            "month_pct": snapshot.month_change_pct,
        },
        "technicals": {
            "sma_20": snapshot.sma_20,
            "sma_50": snapshot.sma_50,
            "volatility_20_pct": snapshot.volatility_20_pct,
            "relative_volume": snapshot.relative_volume,
            "avg_dollar_volume_20": snapshot.avg_dollar_volume_20,
        },
        "fundamentals": {
            "market_cap": snapshot.market_cap,
            "pe_ratio": snapshot.pe_ratio,
            "earnings_date": snapshot.earnings_date,
            "sector": snapshot.sector,
            "asset_type": snapshot.asset_type,
        },
        "news": [
            {
                "title": item.title,
                "summary": item.summary,
                "source": item.source,
                "published_at": item.published_at,
                "url": item.url,
                "sentiment": item.sentiment,
            }
            for item in snapshot.headlines
        ],
        "filings": [
            {"form": item.form, "filed_at": item.filed_at, "description": item.description}
            for item in snapshot.filings
        ],
    }


def build_daily_brief(market_snapshot, ticker_snapshots: list[TickerSnapshot], portfolio_context: dict | None = None) -> DailyBrief:
    return DailyBrief(
        generated_at=datetime.now(timezone.utc).isoformat(),
        market=market_snapshot,
        tickers=ticker_snapshots,
        portfolio_context=portfolio_context or {},
    )


def render_brief_markdown(brief: DailyBrief) -> str:
    lines = []
    lines.append(f"# End Of Day Brief")
    lines.append("")
    lines.append(f"As of: {brief.market.as_of}")
    lines.append(f"Market regime: {brief.market.regime_summary}")
    if brief.market.indices:
        lines.append("Index moves:")
        for symbol, change in brief.market.indices.items():
            lines.append(f"- {symbol}: {change:.2f}%")
    if brief.portfolio_context:
        lines.append("")
        lines.append("Portfolio context:")
        for key, value in brief.portfolio_context.items():
            if key == "memory" and isinstance(value, dict):
                lines.append("- memory:")
                for memory_key, memory_value in value.items():
                    lines.append(f"  - {memory_key}: {memory_value}")
            else:
                lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("Ticker briefs:")
    for snapshot in brief.tickers:
        lines.append(f"## {snapshot.ticker}")
        lines.append(
            f"- Open {snapshot.open:.2f} | High {snapshot.high:.2f} | Low {snapshot.low:.2f} | Close {snapshot.close:.2f} | 1d {snapshot.day_change_pct:.2f}% | 5d {snapshot.week_change_pct:.2f}% | 20d {snapshot.month_change_pct:.2f}%"
        )
        lines.append(
            f"- SMA20 {snapshot.sma_20:.2f} | SMA50 {snapshot.sma_50:.2f} | Vol20 {snapshot.volatility_20_pct:.2f}% | RelVol {snapshot.relative_volume:.2f}"
        )
        lines.append(
            f"- Sector {snapshot.sector or 'n/a'} | Type {snapshot.asset_type} | PE {snapshot.pe_ratio if snapshot.pe_ratio is not None else 'n/a'} | MarketCap {snapshot.market_cap if snapshot.market_cap is not None else 'n/a'}"
        )
        lines.append(f"- AvgDollarVol20 {snapshot.avg_dollar_volume_20:.0f}")
        if snapshot.headlines:
            lines.append("- Headlines:")
            for item in snapshot.headlines[:3]:
                details = [item.source]
                if item.sentiment:
                    details.append(item.sentiment)
                if item.url:
                    details.append(item.url)
                lines.append(f"  - {item.title} ({' | '.join(details)})")
        if snapshot.filings:
            lines.append("- Filings:")
            for item in snapshot.filings[:3]:
                lines.append(f"  - {item.form} on {item.filed_at}: {item.description}")
    return "\n".join(lines)


def render_brief_json(brief: DailyBrief) -> str:
    payload = render_brief_payload(brief)
    return json.dumps(payload, indent=2)


def render_brief_payload(brief: DailyBrief) -> dict:
    return {
        "generated_at": brief.generated_at,
        "market": asdict(brief.market),
        "portfolio_context": brief.portfolio_context,
        "tickers": [_ticker_summary(snapshot) for snapshot in brief.tickers],
    }
