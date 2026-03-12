"""Shared dataclasses for market data, signals, and backtest output."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candle:
    date: str
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class Signal:
    ticker: str
    score: float
    confidence: float
    action: str
    reason: str


@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    entry_date: str
    reason: str
    peak_price: float


@dataclass(frozen=True)
class Trade:
    date: str
    ticker: str
    action: str
    shares: int
    price: float
    cash_after: float
    pnl: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class EquityPoint:
    date: str
    equity: float
    cash: float
    invested: float


@dataclass
class BacktestResult:
    summary: dict
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    published_at: str
    url: str = ""
    sentiment: str = "neutral"


@dataclass(frozen=True)
class FilingItem:
    form: str
    filed_at: str
    description: str


@dataclass(frozen=True)
class TickerSnapshot:
    ticker: str
    as_of: str
    open: float
    high: float
    low: float
    close: float
    day_change_pct: float
    week_change_pct: float
    month_change_pct: float
    sma_20: float
    sma_50: float
    volatility_20_pct: float
    avg_volume_20: float
    avg_dollar_volume_20: float
    latest_volume: int
    relative_volume: float
    market_cap: float | None = None
    pe_ratio: float | None = None
    earnings_date: str | None = None
    sector: str | None = None
    asset_type: str = "stock"
    headlines: list[NewsItem] = field(default_factory=list)
    filings: list[FilingItem] = field(default_factory=list)


@dataclass(frozen=True)
class MarketSnapshot:
    as_of: str
    indices: dict[str, float]
    regime_summary: str


@dataclass(frozen=True)
class DailyBrief:
    generated_at: str
    market: MarketSnapshot
    tickers: list[TickerSnapshot]
    portfolio_context: dict


@dataclass
class PortfolioState:
    scenario: str
    cash: float
    positions: dict[str, dict]
    pending_orders: list[dict] = field(default_factory=list)
    trade_log: list[dict] = field(default_factory=list)
    equity_history: list[dict] = field(default_factory=list)
    last_updated: str = ""
