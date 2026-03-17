"""Typed persistence artifacts for portfolios, executions, and scheduler state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import DailyBrief, PortfolioState, Signal


@dataclass(frozen=True)
class PendingOrderArtifact:
    ticker: str
    action: str
    shares: int = 0
    reason: str = ""
    placed_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PendingOrderArtifact":
        return cls(
            ticker=str(payload.get("ticker", "")),
            action=str(payload.get("action", "")),
            shares=int(payload.get("shares", 0) or 0),
            reason=str(payload.get("reason", "")),
            placed_at=str(payload.get("placed_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeArtifact:
    date: str
    ticker: str
    action: str
    shares: int
    price: float
    cash_after: float
    pnl: float = 0.0
    reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TradeArtifact":
        return cls(
            date=str(payload.get("date", "")),
            ticker=str(payload.get("ticker", "")),
            action=str(payload.get("action", "")),
            shares=int(payload.get("shares", 0) or 0),
            price=float(payload.get("price", 0.0) or 0.0),
            cash_after=float(payload.get("cash_after", 0.0) or 0.0),
            pnl=float(payload.get("pnl", 0.0) or 0.0),
            reason=str(payload.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EquityPointArtifact:
    date: str
    equity: float
    cash: float
    invested: float
    position_count: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EquityPointArtifact":
        return cls(
            date=str(payload.get("date", "")),
            equity=float(payload.get("equity", 0.0) or 0.0),
            cash=float(payload.get("cash", 0.0) or 0.0),
            invested=float(payload.get("invested", 0.0) or 0.0),
            position_count=int(payload.get("position_count", 0) or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioArtifact:
    scenario: str
    cash: float
    positions: dict[str, dict[str, Any]]
    pending_orders: list[PendingOrderArtifact] = field(default_factory=list)
    trade_log: list[TradeArtifact] = field(default_factory=list)
    equity_history: list[EquityPointArtifact] = field(default_factory=list)
    last_updated: str = ""

    @classmethod
    def from_portfolio_state(cls, portfolio: PortfolioState) -> "PortfolioArtifact":
        return cls(
            scenario=portfolio.scenario,
            cash=portfolio.cash,
            positions=portfolio.positions,
            pending_orders=[PendingOrderArtifact.from_dict(item) for item in portfolio.pending_orders],
            trade_log=[TradeArtifact.from_dict(item) for item in portfolio.trade_log],
            equity_history=[EquityPointArtifact.from_dict(item) for item in portfolio.equity_history],
            last_updated=portfolio.last_updated,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PortfolioArtifact":
        return cls(
            scenario=str(payload["scenario"]),
            cash=float(payload["cash"]),
            positions=dict(payload.get("positions", {})),
            pending_orders=[PendingOrderArtifact.from_dict(item) for item in payload.get("pending_orders", [])],
            trade_log=[TradeArtifact.from_dict(item) for item in payload.get("trade_log", [])],
            equity_history=[EquityPointArtifact.from_dict(item) for item in payload.get("equity_history", [])],
            last_updated=str(payload.get("last_updated", "")),
        )

    def to_portfolio_state(self) -> PortfolioState:
        return PortfolioState(
            scenario=self.scenario,
            cash=self.cash,
            positions=self.positions,
            pending_orders=[item.to_dict() for item in self.pending_orders],
            trade_log=[item.to_dict() for item in self.trade_log],
            equity_history=[item.to_dict() for item in self.equity_history],
            last_updated=self.last_updated,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "cash": self.cash,
            "positions": self.positions,
            "pending_orders": [item.to_dict() for item in self.pending_orders],
            "trade_log": [item.to_dict() for item in self.trade_log],
            "equity_history": [item.to_dict() for item in self.equity_history],
            "last_updated": self.last_updated,
        }


@dataclass(frozen=True)
class ExecutionReportArtifact:
    scenario: str
    generated_at: str
    market_as_of: str
    brief_portfolio_context: dict[str, Any]
    portfolio_context: dict[str, Any]
    decisions: list[dict[str, Any]]
    executed_trades: list[TradeArtifact]
    placed_orders: list[PendingOrderArtifact]
    equity_history: list[EquityPointArtifact]
    tickers: list[str]

    @classmethod
    def from_run_data(
        cls,
        brief: DailyBrief,
        decisions: list[Signal],
        execution: dict[str, Any],
        scenario_name: str,
    ) -> "ExecutionReportArtifact":
        return cls(
            scenario=scenario_name,
            generated_at=brief.generated_at,
            market_as_of=brief.market.as_of,
            brief_portfolio_context=dict(brief.portfolio_context),
            portfolio_context=dict(execution["portfolio_context"]),
            decisions=[decision.__dict__ for decision in decisions],
            executed_trades=[TradeArtifact.from_dict(item) for item in execution.get("executed_trades", [])],
            placed_orders=[PendingOrderArtifact.from_dict(item) for item in execution.get("placed_orders", [])],
            equity_history=[
                EquityPointArtifact.from_dict(item)
                for item in execution.get("portfolio_context", {}).get("equity_history", [])
            ],
            tickers=[snapshot.ticker for snapshot in brief.tickers],
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionReportArtifact":
        return cls(
            scenario=str(payload.get("scenario", "")),
            generated_at=str(payload.get("generated_at", "")),
            market_as_of=str(payload.get("market_as_of", "")),
            brief_portfolio_context=dict(payload.get("brief_portfolio_context", {})),
            portfolio_context=dict(payload.get("portfolio_context", {})),
            decisions=list(payload.get("decisions", [])),
            executed_trades=[TradeArtifact.from_dict(item) for item in payload.get("executed_trades", [])],
            placed_orders=[PendingOrderArtifact.from_dict(item) for item in payload.get("placed_orders", [])],
            equity_history=[EquityPointArtifact.from_dict(item) for item in payload.get("equity_history", [])],
            tickers=[str(item) for item in payload.get("tickers", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "generated_at": self.generated_at,
            "market_as_of": self.market_as_of,
            "brief_portfolio_context": self.brief_portfolio_context,
            "portfolio_context": self.portfolio_context,
            "decisions": self.decisions,
            "executed_trades": [item.to_dict() for item in self.executed_trades],
            "placed_orders": [item.to_dict() for item in self.placed_orders],
            "equity_history": [item.to_dict() for item in self.equity_history],
            "tickers": self.tickers,
        }


@dataclass(frozen=True)
class SchedulerRunResultArtifact:
    scenario: str
    market_as_of: str
    decisions: int
    executed_trades: int
    execution_file: str
    completed_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchedulerRunResultArtifact":
        return cls(
            scenario=str(payload.get("scenario", "")),
            market_as_of=str(payload.get("market_as_of", "")),
            decisions=int(payload.get("decisions", 0) or 0),
            executed_trades=int(payload.get("executed_trades", 0) or 0),
            execution_file=str(payload.get("execution_file", "")),
            completed_at=str(payload.get("completed_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchedulerStatusArtifact:
    state: str
    started_at: str
    provider: str
    scenarios: list[str]
    schedule_time: str
    timezone: str
    last_successful_run: str | None = None
    last_failed_run: str | None = None
    last_error: str | None = None
    last_results: list[SchedulerRunResultArtifact] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchedulerStatusArtifact":
        return cls(
            state=str(payload.get("state", "")),
            started_at=str(payload.get("started_at", "")),
            provider=str(payload.get("provider", "")),
            scenarios=[str(item) for item in payload.get("scenarios", [])],
            schedule_time=str(payload.get("schedule_time", "")),
            timezone=str(payload.get("timezone", "")),
            last_successful_run=payload.get("last_successful_run"),
            last_failed_run=payload.get("last_failed_run"),
            last_error=payload.get("last_error"),
            last_results=[SchedulerRunResultArtifact.from_dict(item) for item in payload.get("last_results", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "started_at": self.started_at,
            "provider": self.provider,
            "scenarios": self.scenarios,
            "schedule_time": self.schedule_time,
            "timezone": self.timezone,
            "last_successful_run": self.last_successful_run,
            "last_failed_run": self.last_failed_run,
            "last_error": self.last_error,
            "last_results": [item.to_dict() for item in self.last_results],
        }


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
