"""Data provider adapters for end-of-day briefing."""

from __future__ import annotations

import json
import os
import ssl
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

from .config import UniverseConfig
from .data import load_market_data
from .models import FilingItem, MarketSnapshot, NewsItem, TickerSnapshot
from .news_scraper import scrape_public_headlines


def _safe_pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous


def _optional_float(value) -> float | None:
    if value in (None, "", "None", "null", "NULL", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_get(url: str, headers: dict[str, str] | None = None) -> dict | list:
    request = urllib.request.Request(url, headers=headers or {})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_price_snapshot(
    *,
    ticker: str,
    as_of: str,
    open_price: float,
    high_price: float,
    low_price: float,
    closes: list[float],
    volumes: list[int],
    market_cap: float | None = None,
    pe_ratio: float | None = None,
    earnings_date: str | None = None,
    sector: str | None = None,
    asset_type: str = "stock",
    headlines: list[NewsItem] | None = None,
    filings: list[FilingItem] | None = None,
) -> TickerSnapshot:
    sma_20 = statistics.fmean(closes[-20:])
    sma_50 = statistics.fmean(closes[-50:])
    avg_volume_20 = statistics.fmean(volumes[-20:])
    volatility_20_pct = statistics.pstdev(closes[-20:]) / sma_20 * 100 if sma_20 else 0.0
    current_close = closes[-1]
    latest_volume = volumes[-1]
    relative_volume = latest_volume / avg_volume_20 if avg_volume_20 else 1.0
    return TickerSnapshot(
        ticker=ticker,
        as_of=as_of,
        open=round(open_price, 2),
        high=round(high_price, 2),
        low=round(low_price, 2),
        close=round(current_close, 2),
        day_change_pct=round(_safe_pct_change(closes[-1], closes[-2]) * 100, 2),
        week_change_pct=round(_safe_pct_change(closes[-1], closes[-6]) * 100, 2),
        month_change_pct=round(_safe_pct_change(closes[-1], closes[-21]) * 100, 2),
        sma_20=round(sma_20, 2),
        sma_50=round(sma_50, 2),
        volatility_20_pct=round(volatility_20_pct, 2),
        avg_volume_20=round(avg_volume_20, 0),
        avg_dollar_volume_20=round(avg_volume_20 * current_close, 0),
        latest_volume=latest_volume,
        relative_volume=round(relative_volume, 2),
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        earnings_date=earnings_date,
        sector=sector,
        asset_type=asset_type,
        headlines=headlines or [],
        filings=filings or [],
    )


class ResearchProvider(ABC):
    """Contract for a source of end-of-day market context."""

    @abstractmethod
    def build_market_snapshot(self) -> MarketSnapshot:
        raise NotImplementedError

    @abstractmethod
    def build_ticker_snapshot(self, ticker: str) -> TickerSnapshot:
        raise NotImplementedError

    @abstractmethod
    def available_tickers(self, universe_config: UniverseConfig | None = None) -> list[str]:
        raise NotImplementedError


class LocalCsvResearchProvider(ResearchProvider):
    """Build snapshots from local CSV data."""

    def __init__(self, data_dir: Path):
        self.market_data = load_market_data(data_dir)

    def build_market_snapshot(self) -> MarketSnapshot:
        index_map: dict[str, float] = {}
        positive = 0
        negative = 0
        as_of = ""
        for ticker in ["SPY", "QQQ", "IWM"]:
            if ticker in self.market_data and len(self.market_data[ticker]) >= 2:
                candles = self.market_data[ticker]
                as_of = candles[-1].date
                change = _safe_pct_change(candles[-1].close, candles[-2].close) * 100
                index_map[ticker] = round(change, 2)
                if change >= 0:
                    positive += 1
                else:
                    negative += 1

        if not index_map:
            first_series = next(iter(self.market_data.values()))
            as_of = first_series[-1].date

        if positive >= 2:
            regime = "Risk-on close with broad index strength."
        elif negative >= 2:
            regime = "Risk-off close with broad index weakness."
        else:
            regime = "Mixed market close without a clear broad regime."

        return MarketSnapshot(as_of=as_of, indices=index_map, regime_summary=regime)

    def available_tickers(self, universe_config: UniverseConfig | None = None) -> list[str]:
        return sorted(ticker for ticker in self.market_data.keys() if ticker not in {"SPY", "QQQ", "IWM"})

    def build_ticker_snapshot(self, ticker: str) -> TickerSnapshot:
        history = self.market_data[ticker]
        if len(history) < 50:
            raise ValueError(f"Not enough history for {ticker}. Need at least 50 rows.")

        closes = [c.close for c in history]
        volumes = [c.volume for c in history]
        current = history[-1]
        avg_volume_20 = statistics.fmean(volumes[-20:])
        synthetic_market_cap = max(5_000_000_000.0, current.close * avg_volume_20 * 320)
        sma_20 = statistics.fmean(closes[-20:])
        sma_50 = statistics.fmean(closes[-50:])

        direction = "bullish" if current.close > sma_20 > sma_50 else "bearish" if current.close < sma_20 < sma_50 else "mixed"
        headlines = scrape_public_headlines(ticker)
        if not headlines:
            headlines = [
                NewsItem(
                    title=f"{ticker} synthetic daily recap",
                    summary=f"{ticker} closed at {current.close:.2f} with a {direction} trend structure in local research data.",
                    source="local-sim",
                    published_at=current.date,
                    url="",
                    sentiment="positive" if direction == "bullish" else "negative" if direction == "bearish" else "neutral",
                )
            ]

        return _build_price_snapshot(
            ticker=ticker,
            as_of=current.date,
            open_price=current.open,
            high_price=current.high,
            low_price=current.low,
            closes=closes,
            volumes=volumes,
            market_cap=round(synthetic_market_cap, 0),
            sector="Synthetic",
            asset_type="stock",
            headlines=headlines,
            filings=[],
        )


class AlphaVantageResearchProvider(ResearchProvider):
    """Alpha Vantage based provider for prices, fundamentals, and news."""

    base_url = "https://www.alphavantage.co/query"

    def __init__(self) -> None:
        self.api_key = os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            raise RuntimeError("ALPHAVANTAGE_API_KEY is not set.")
        self._top_movers_cache: dict | None = None
        self._last_request_at = 0.0

    def _query(self, **params: str) -> dict:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        query = urllib.parse.urlencode({**params, "apikey": self.api_key})
        data = _json_get(f"{self.base_url}?{query}")
        self._last_request_at = time.monotonic()
        if isinstance(data, dict) and data.get("Information"):
            info = data["Information"]
            if "1 request per second" in info:
                time.sleep(1.2)
                data = _json_get(f"{self.base_url}?{query}")
                self._last_request_at = time.monotonic()
                if not (isinstance(data, dict) and data.get("Information")):
                    return data
            raise RuntimeError(info)
        return data

    def _top_movers(self) -> dict:
        if self._top_movers_cache is None:
            data = self._query(function="TOP_GAINERS_LOSERS")
            if not isinstance(data, dict):
                raise RuntimeError("Unexpected Alpha Vantage top movers response.")
            self._top_movers_cache = data
        return self._top_movers_cache

    def build_market_snapshot(self) -> MarketSnapshot:
        movers = self._top_movers()
        top_gainers = movers.get("top_gainers", [])
        top_losers = movers.get("top_losers", [])
        most_active = movers.get("most_actively_traded", [])
        as_of = str(movers.get("last_updated", ""))
        regime = "Mixed market close from Alpha Vantage top movers."
        if len(top_gainers) > len(top_losers):
            regime = "Risk-on close with more upside leadership than downside leadership."
        elif len(top_losers) > len(top_gainers):
            regime = "Risk-off close with heavier downside leadership."
        if most_active:
            regime += f" Most active leadership count: {len(most_active)}."
        return MarketSnapshot(as_of=as_of, indices={}, regime_summary=regime)

    def available_tickers(self, universe_config: UniverseConfig | None = None) -> list[str]:
        config = universe_config or UniverseConfig()
        movers = self._top_movers()
        ordered_sources = (
            movers.get("top_gainers", []),
            movers.get("most_actively_traded", []),
            movers.get("top_losers", []),
        )
        request_safe_cap = 8
        tickers: list[str] = []
        for source in ordered_sources:
            for item in source:
                symbol = str(item.get("ticker", "")).upper().strip()
                if symbol and symbol not in tickers:
                    tickers.append(symbol)
                if len(tickers) >= min(config.max_brief_candidates, request_safe_cap):
                    return tickers
        return tickers

    def build_ticker_snapshot(self, ticker: str) -> TickerSnapshot:
        daily = self._query(function="TIME_SERIES_DAILY", symbol=ticker, outputsize="compact")
        overview = self._query(function="OVERVIEW", symbol=ticker)

        series = daily.get("Time Series (Daily)", {})
        dates = sorted(series.keys())
        if len(dates) < 50:
            raise RuntimeError(f"Alpha Vantage returned insufficient history for {ticker}.")

        closes = [float(series[date_key]["4. close"]) for date_key in dates]
        volumes = [int(series[date_key]["5. volume"]) for date_key in dates]
        current_date = dates[-1]
        current_close = closes[-1]
        mover_context = self._classify_alpha_mover(ticker)
        headlines = [
            NewsItem(
                title=f"{ticker} Alpha Vantage daily setup",
                summary=mover_context,
                source="Alpha Vantage",
                published_at=current_date,
                url="",
                sentiment="positive" if "gainer" in mover_context.lower() else "negative" if "loser" in mover_context.lower() else "neutral",
            )
        ]

        return _build_price_snapshot(
            ticker=ticker,
            as_of=current_date,
            open_price=float(series[current_date]["1. open"]),
            high_price=float(series[current_date]["2. high"]),
            low_price=float(series[current_date]["3. low"]),
            closes=closes,
            volumes=volumes,
            market_cap=_optional_float(overview.get("MarketCapitalization")),
            pe_ratio=_optional_float(overview.get("PERatio")),
            earnings_date=overview.get("LatestQuarter"),
            sector=overview.get("Sector"),
            asset_type="ETF" if overview.get("AssetType", "").upper() == "ETF" else "stock",
            headlines=headlines,
            filings=[],
        )

    def _classify_alpha_mover(self, ticker: str) -> str:
        movers = self._top_movers()
        for label, items in (
            ("top gainer", movers.get("top_gainers", [])),
            ("most active", movers.get("most_actively_traded", [])),
            ("top loser", movers.get("top_losers", [])),
        ):
            for item in items:
                if str(item.get("ticker", "")).upper().strip() == ticker:
                    change = item.get("change_percentage", "")
                    return f"{ticker} appeared in Alpha Vantage {label} list with daily change {change}."
        return f"{ticker} selected from Alpha Vantage end-of-day universe."


class FmpResearchProvider(ResearchProvider):
    """Financial Modeling Prep based provider."""

    base_url = "https://financialmodelingprep.com/stable"

    def __init__(self) -> None:
        self.api_key = os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise RuntimeError("FMP_API_KEY is not set.")

    def _query(self, path: str, **params: str) -> dict | list:
        query = urllib.parse.urlencode({**params, "apikey": self.api_key})
        return _json_get(f"{self.base_url}{path}?{query}")

    def build_market_snapshot(self) -> MarketSnapshot:
        indices = {}
        as_of = ""
        regime = "Market snapshot unavailable from provider."
        try:
            quotes = self._query("/quote", symbol="SPY,QQQ,IWM")
            for item in quotes:
                indices[item["symbol"]] = round(float(item.get("changesPercentage", 0.0)), 2)
                as_of = item.get("timestamp", as_of)
            regime = "Mixed market close."
            if sum(1 for value in indices.values() if value >= 0) >= 2:
                regime = "Risk-on close with broad ETF participation."
            elif sum(1 for value in indices.values() if value < 0) >= 2:
                regime = "Risk-off close with broad ETF weakness."
        except urllib.error.HTTPError as exc:
            if exc.code != 402:
                raise
        return MarketSnapshot(as_of=str(as_of), indices=indices, regime_summary=regime)

    def available_tickers(self, universe_config: UniverseConfig | None = None) -> list[str]:
        config = universe_config or UniverseConfig()
        tickers: list[str] = []

        try:
            params = {
                "marketCapMoreThan": str(int(config.min_market_cap)),
                "priceMoreThan": str(config.min_price),
                "volumeMoreThan": str(int(config.min_avg_dollar_volume / max(config.min_price, 1.0))),
                "isActivelyTrading": "true",
                "limit": str(config.max_universe_size),
            }
            if not config.include_etfs:
                params["isEtf"] = "false"

            screener = self._query("/company-screener", **params)
            for item in screener if isinstance(screener, list) else []:
                symbol = str(item.get("symbol", "")).upper().strip()
                if symbol and symbol not in tickers:
                    tickers.append(symbol)
        except urllib.error.HTTPError as exc:
            if exc.code != 402:
                raise

        if len(tickers) < config.max_brief_candidates:
            for path in ("/actively-trading-list",):
                try:
                    actives = self._query(path)
                except urllib.error.HTTPError as exc:
                    if exc.code == 402:
                        continue
                    raise

                for item in actives if isinstance(actives, list) else []:
                    symbol = str(item.get("symbol", "")).upper().strip()
                    if symbol and symbol not in tickers:
                        tickers.append(symbol)
                    if len(tickers) >= config.max_universe_size:
                        break
                if len(tickers) >= config.max_brief_candidates:
                    break

        return tickers[: config.max_universe_size]

    def build_ticker_snapshot(self, ticker: str) -> TickerSnapshot:
        history = self._query(f"/historical-price-eod/full", symbol=ticker, limit="90")
        try:
            profile = self._query("/profile", symbol=ticker)
        except urllib.error.HTTPError as exc:
            if exc.code != 402:
                raise
            profile = []
        try:
            news = self._query("/news/stock", symbols=ticker, limit="3")
        except urllib.error.HTTPError as exc:
            if exc.code != 402:
                raise
            news = []
        entries = history if isinstance(history, list) else history.get("historical", [])
        entries = list(reversed(entries))
        if len(entries) < 50:
            raise RuntimeError(f"FMP returned insufficient history for {ticker}.")

        closes = [float(item["close"]) for item in entries]
        volumes = [int(item.get("volume", 0)) for item in entries]
        current = entries[-1]
        profile_item = profile[0] if profile else {}

        return _build_price_snapshot(
            ticker=ticker,
            as_of=current["date"],
            open_price=float(current["open"]),
            high_price=float(current["high"]),
            low_price=float(current["low"]),
            closes=closes,
            volumes=volumes,
            market_cap=_optional_float(profile_item.get("mktCap")),
            pe_ratio=_optional_float(profile_item.get("pe")),
            earnings_date=profile_item.get("lastDiv"),
            sector=profile_item.get("sector"),
            asset_type="ETF" if str(profile_item.get("isEtf", "")).lower() == "true" else "stock",
            headlines=[
                NewsItem(
                    title=item.get("title", ""),
                    summary=item.get("text", ""),
                    source=item.get("site", "FMP"),
                    published_at=item.get("publishedDate", ""),
                    url=item.get("url", ""),
                )
                for item in news[:3]
            ],
            filings=[],
        )


class SecFilingsProvider:
    """Pull recent SEC submissions metadata."""

    base_url = "https://data.sec.gov/submissions"

    def __init__(self) -> None:
        self.user_agent = os.getenv("SEC_USER_AGENT", "CodexTrader research contact@example.com")

    def recent_filings(self, cik: str) -> list[FilingItem]:
        cik_padded = cik.zfill(10)
        data = _json_get(
            f"{self.base_url}/CIK{cik_padded}.json",
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
        )
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        items = []
        for form, filed_at in list(zip(forms, dates))[:5]:
            items.append(FilingItem(form=form, filed_at=filed_at, description=f"Recent SEC filing: {form}"))
        return items


def make_research_provider(provider_name: str, data_dir: Path) -> ResearchProvider:
    if provider_name == "local":
        return LocalCsvResearchProvider(data_dir)
    if provider_name == "alphavantage":
        return AlphaVantageResearchProvider()
    if provider_name == "fmp":
        return FmpResearchProvider()
    raise ValueError(f"Unsupported provider: {provider_name}")
