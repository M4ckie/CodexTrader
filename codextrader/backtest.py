"""Backtesting engine for the offline trading bot."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .config import BotConfig
from .models import BacktestResult, EquityPoint, Position, Trade
from .openai_strategy import score_with_openai
from .strategy import rank_signals


def _equity(cash: float, positions: dict[str, Position], latest_prices: dict[str, float]) -> float:
    invested = sum(position.shares * latest_prices[position.ticker] for position in positions.values())
    return cash + invested


def _max_drawdown(equity_curve: list[EquityPoint]) -> float:
    peak = 0.0
    worst = 0.0
    for point in equity_curve:
        peak = max(peak, point.equity)
        if peak > 0:
            worst = min(worst, (point.equity - peak) / peak)
    return worst


def _annualized_return(start_value: float, end_value: float, trading_days: int) -> float:
    if start_value <= 0 or end_value <= 0 or trading_days <= 0:
        return 0.0
    years = trading_days / 252.0
    return (end_value / start_value) ** (1 / years) - 1 if years > 0 else 0.0


def run_backtest(
    market_data: dict[str, list],
    cfg: BotConfig,
    strategy_provider: str = "heuristic",
    openai_model: str = "gpt-4.1-mini",
) -> BacktestResult:
    """Run the strategy over aligned candle series."""
    tickers = sorted(market_data.keys())
    if not tickers:
        raise ValueError("No market data loaded.")

    series_length = min(len(series) for series in market_data.values())
    cash = cfg.initial_cash
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []

    for index in range(25, series_length):
        market_slice = {ticker: market_data[ticker][: index + 1] for ticker in tickers}
        latest_prices = {ticker: market_data[ticker][index].close for ticker in tickers}
        current_date = market_data[tickers[0]][index].date

        # Exit rules first.
        for ticker in list(positions.keys()):
            position = positions[ticker]
            price = latest_prices[ticker]
            position.peak_price = max(position.peak_price, price)
            take_profit_price = position.entry_price * (1 + cfg.take_profit_pct)
            stop_price = max(position.entry_price * (1 - cfg.stop_loss_pct), position.peak_price * (1 - cfg.stop_loss_pct))

            if price <= stop_price or price >= take_profit_price:
                fill_price = price * (1 - cfg.slippage_pct)
                proceeds = fill_price * position.shares - cfg.commission
                pnl = (fill_price - position.entry_price) * position.shares - cfg.commission
                cash += proceeds
                trades.append(
                    Trade(
                        date=current_date,
                        ticker=ticker,
                        action="SELL",
                        shares=position.shares,
                        price=fill_price,
                        cash_after=cash,
                        pnl=pnl,
                        reason="risk exit",
                    )
                )
                del positions[ticker]

        if strategy_provider == "openai":
            signals = score_with_openai(market_slice, openai_model)
        else:
            signals = rank_signals(market_slice, cfg)

        for signal in signals:
            if signal.action == "SELL" and signal.ticker in positions:
                position = positions[signal.ticker]
                fill_price = latest_prices[signal.ticker] * (1 - cfg.slippage_pct)
                proceeds = fill_price * position.shares - cfg.commission
                pnl = (fill_price - position.entry_price) * position.shares - cfg.commission
                cash += proceeds
                trades.append(
                    Trade(
                        date=current_date,
                        ticker=signal.ticker,
                        action="SELL",
                        shares=position.shares,
                        price=fill_price,
                        cash_after=cash,
                        pnl=pnl,
                        reason=f"model exit: {signal.reason}",
                    )
                )
                del positions[signal.ticker]

        open_slots = cfg.max_positions - len(positions)
        if open_slots > 0:
            buy_candidates = [signal for signal in signals if signal.action == "BUY" and signal.ticker not in positions]
            for signal in buy_candidates[:open_slots]:
                max_position_value = _equity(cash, positions, latest_prices) * cfg.position_size_pct
                fill_price = latest_prices[signal.ticker] * (1 + cfg.slippage_pct)
                shares = int((max_position_value - cfg.commission) / fill_price)
                if shares <= 0:
                    continue

                total_cost = shares * fill_price + cfg.commission
                if total_cost > cash:
                    shares = int((cash - cfg.commission) / fill_price)
                    total_cost = shares * fill_price + cfg.commission
                if shares <= 0 or total_cost > cash:
                    continue

                cash -= total_cost
                positions[signal.ticker] = Position(
                    ticker=signal.ticker,
                    shares=shares,
                    entry_price=fill_price,
                    entry_date=current_date,
                    reason=signal.reason,
                    peak_price=fill_price,
                )
                trades.append(
                    Trade(
                        date=current_date,
                        ticker=signal.ticker,
                        action="BUY",
                        shares=shares,
                        price=fill_price,
                        cash_after=cash,
                        reason=f"model entry: {signal.reason}",
                    )
                )

        total_equity = _equity(cash, positions, latest_prices)
        invested = total_equity - cash
        equity_curve.append(EquityPoint(date=current_date, equity=total_equity, cash=cash, invested=invested))

    winning_trades = [trade for trade in trades if trade.action == "SELL" and trade.pnl > 0]
    losing_trades = [trade for trade in trades if trade.action == "SELL" and trade.pnl <= 0]
    ending_equity = equity_curve[-1].equity if equity_curve else cfg.initial_cash
    total_return = (ending_equity / cfg.initial_cash) - 1
    realized_pnl = sum(trade.pnl for trade in trades if trade.action == "SELL")
    summary = {
        "initial_cash": round(cfg.initial_cash, 2),
        "ending_equity": round(ending_equity, 2),
        "strategy_provider": strategy_provider,
        "openai_model": openai_model if strategy_provider == "openai" else None,
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(_annualized_return(cfg.initial_cash, ending_equity, len(equity_curve)) * 100, 2),
        "max_drawdown_pct": round(_max_drawdown(equity_curve) * 100, 2),
        "trade_count": len(trades),
        "closed_trades": len(winning_trades) + len(losing_trades),
        "win_rate_pct": round((len(winning_trades) / max(1, len(winning_trades) + len(losing_trades))) * 100, 2),
        "realized_pnl": round(realized_pnl, 2),
        "open_positions": sorted(positions.keys()),
    }
    return BacktestResult(summary=summary, trades=trades, equity_curve=equity_curve)


def save_result(result: BacktestResult, output_path: Path) -> None:
    """Persist summary, trades, and equity curve as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": result.summary,
        "trades": [trade.__dict__ for trade in result.trades],
        "equity_curve": [point.__dict__ for point in result.equity_curve],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
