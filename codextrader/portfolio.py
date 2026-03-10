"""Persistent paper portfolio state and daily execution."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import ScenarioConfig, get_scenario
from .models import DailyBrief, PortfolioState, Signal


def _scenario(name: str) -> ScenarioConfig:
    return get_scenario(name)


def _portfolio_path(base_dir: Path, scenario_name: str) -> Path:
    return base_dir / f"{scenario_name}_portfolio.json"


def load_portfolio(base_dir: Path, scenario_name: str) -> PortfolioState:
    path = _portfolio_path(base_dir, scenario_name)
    if not path.exists():
        cfg = _scenario(scenario_name)
        return PortfolioState(
            scenario=scenario_name,
            cash=cfg.bot.initial_cash,
            positions={},
            trade_log=[],
            equity_history=[],
            last_updated="",
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    return PortfolioState(
        scenario=payload["scenario"],
        cash=float(payload["cash"]),
        positions=payload.get("positions", {}),
        trade_log=payload.get("trade_log", []),
        equity_history=payload.get("equity_history", []),
        last_updated=payload.get("last_updated", ""),
    )


def save_portfolio(base_dir: Path, portfolio: PortfolioState) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = _portfolio_path(base_dir, portfolio.scenario)
    path.write_text(json.dumps(asdict(portfolio), indent=2), encoding="utf-8")
    return path


def build_portfolio_context(portfolio: PortfolioState, brief: DailyBrief) -> dict:
    prices = {snapshot.ticker: snapshot.close for snapshot in brief.tickers}
    invested = 0.0
    open_positions = []
    for ticker, position in portfolio.positions.items():
        mark = prices.get(ticker, position["entry_price"])
        market_value = mark * position["shares"]
        invested += market_value
        open_positions.append(
            {
                "ticker": ticker,
                "shares": position["shares"],
                "entry_price": position["entry_price"],
                "mark_price": round(mark, 2),
                "unrealized_pnl": round((mark - position["entry_price"]) * position["shares"], 2),
            }
        )

    return {
        "scenario": portfolio.scenario,
        "cash": round(portfolio.cash, 2),
        "invested": round(invested, 2),
        "equity": round(portfolio.cash + invested, 2),
        "positions": open_positions,
        "position_count": len(open_positions),
        "last_updated": portfolio.last_updated,
        "equity_history": portfolio.equity_history,
        "mode": "paper",
    }


def _record_equity_snapshot(portfolio: PortfolioState, brief: DailyBrief) -> None:
    context = build_portfolio_context(portfolio, brief)
    snapshot = {
        "date": brief.market.as_of or datetime.now(timezone.utc).date().isoformat(),
        "cash": context["cash"],
        "invested": context["invested"],
        "equity": context["equity"],
        "position_count": context["position_count"],
    }
    if portfolio.equity_history and portfolio.equity_history[-1]["date"] == snapshot["date"]:
        portfolio.equity_history[-1] = snapshot
    else:
        portfolio.equity_history.append(snapshot)


def _apply_risk_exits(portfolio: PortfolioState, brief: DailyBrief) -> list[dict]:
    cfg = _scenario(portfolio.scenario).bot
    prices = {snapshot.ticker: snapshot.close for snapshot in brief.tickers}
    now = brief.market.as_of or datetime.now(timezone.utc).date().isoformat()
    trades = []

    for ticker in list(portfolio.positions.keys()):
        position = portfolio.positions[ticker]
        price = prices.get(ticker)
        if not price or price <= 0:
            continue

        peak_price = max(float(position.get("peak_price", position["entry_price"])), price)
        position["peak_price"] = round(peak_price, 2)
        stop_price = max(
            float(position["entry_price"]) * (1 - cfg.stop_loss_pct),
            peak_price * (1 - cfg.stop_loss_pct),
        )
        take_profit_price = float(position["entry_price"]) * (1 + cfg.take_profit_pct)

        if price <= stop_price or price >= take_profit_price:
            proceeds = position["shares"] * price - cfg.commission
            pnl = (price - position["entry_price"]) * position["shares"] - cfg.commission
            portfolio.cash += proceeds
            del portfolio.positions[ticker]
            reason = "risk stop" if price <= stop_price else "take profit"
            trade = {
                "date": now,
                "ticker": ticker,
                "action": "SELL",
                "shares": position["shares"],
                "price": round(price, 2),
                "pnl": round(pnl, 2),
                "reason": reason,
                "cash_after": round(portfolio.cash, 2),
            }
            portfolio.trade_log.append(trade)
            trades.append(trade)
    return trades


def execute_daily_decisions(
    portfolio: PortfolioState,
    brief: DailyBrief,
    decisions: list[Signal],
) -> dict:
    cfg = _scenario(portfolio.scenario).bot
    prices = {snapshot.ticker: snapshot.close for snapshot in brief.tickers}
    now = brief.market.as_of or datetime.now(timezone.utc).date().isoformat()
    trades = _apply_risk_exits(portfolio, brief)

    invested = sum(
        portfolio.positions[ticker]["shares"] * prices.get(ticker, portfolio.positions[ticker]["entry_price"])
        for ticker in portfolio.positions
    )
    equity = portfolio.cash + invested

    for decision in decisions:
        ticker = decision.ticker
        price = prices.get(ticker)
        if not price or price <= 0:
            continue

        if decision.action == "SELL" and ticker in portfolio.positions:
            position = portfolio.positions.pop(ticker)
            proceeds = position["shares"] * price - cfg.commission
            pnl = (price - position["entry_price"]) * position["shares"] - cfg.commission
            portfolio.cash += proceeds
            trade = {
                "date": now,
                "ticker": ticker,
                "action": "SELL",
                "shares": position["shares"],
                "price": round(price, 2),
                "pnl": round(pnl, 2),
                "reason": decision.reason,
                "cash_after": round(portfolio.cash, 2),
            }
            portfolio.trade_log.append(trade)
            trades.append(trade)

    available_slots = max(0, cfg.max_positions - len(portfolio.positions))
    for decision in [item for item in decisions if item.action == "BUY"][:available_slots]:
        ticker = decision.ticker
        if ticker in portfolio.positions:
            continue
        price = prices.get(ticker)
        if not price or price <= 0:
            continue

        target_value = equity * cfg.position_size_pct
        shares = int((target_value - cfg.commission) / price)
        if shares <= 0:
            continue
        cost = shares * price + cfg.commission
        if cost > portfolio.cash:
            shares = int((portfolio.cash - cfg.commission) / price)
            cost = shares * price + cfg.commission
        if shares <= 0 or cost > portfolio.cash:
            continue

        portfolio.cash -= cost
        portfolio.positions[ticker] = {
            "shares": shares,
            "entry_price": round(price, 2),
            "entry_date": now,
            "reason": decision.reason,
            "peak_price": round(price, 2),
        }
        trade = {
            "date": now,
            "ticker": ticker,
            "action": "BUY",
            "shares": shares,
            "price": round(price, 2),
            "pnl": 0.0,
            "reason": decision.reason,
            "cash_after": round(portfolio.cash, 2),
        }
        portfolio.trade_log.append(trade)
        trades.append(trade)

    portfolio.last_updated = now
    _record_equity_snapshot(portfolio, brief)
    context = build_portfolio_context(portfolio, brief)
    return {"executed_trades": trades, "portfolio_context": context}
