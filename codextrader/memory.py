"""Compact portfolio memory summaries for model context."""

from __future__ import annotations

from collections import defaultdict

from .models import PortfolioState


def build_portfolio_memory(portfolio: PortfolioState, recent_trade_limit: int = 8) -> dict:
    closed_trades = [trade for trade in portfolio.trade_log if trade.get("action") == "SELL"]
    winning_trades = [trade for trade in closed_trades if float(trade.get("pnl", 0.0)) > 0]
    losing_trades = [trade for trade in closed_trades if float(trade.get("pnl", 0.0)) <= 0]

    symbol_pnl: dict[str, float] = defaultdict(float)
    reason_pnl: dict[str, float] = defaultdict(float)
    for trade in closed_trades:
        ticker = trade.get("ticker", "")
        pnl = float(trade.get("pnl", 0.0))
        symbol_pnl[ticker] += pnl
        reason = str(trade.get("reason", "")).strip() or "unspecified"
        reason_pnl[reason] += pnl

    best_symbols = sorted(symbol_pnl.items(), key=lambda item: item[1], reverse=True)[:3]
    worst_symbols = sorted(symbol_pnl.items(), key=lambda item: item[1])[:3]
    worst_reasons = sorted(reason_pnl.items(), key=lambda item: item[1])[:3]

    last_equity = portfolio.equity_history[-1]["equity"] if portfolio.equity_history else portfolio.cash
    start_equity = portfolio.equity_history[0]["equity"] if portfolio.equity_history else portfolio.cash
    total_return_pct = ((last_equity / start_equity) - 1) * 100 if start_equity else 0.0

    recent_trades = portfolio.trade_log[-recent_trade_limit:]
    recent_trade_notes = [
        {
            "date": trade.get("date"),
            "ticker": trade.get("ticker"),
            "action": trade.get("action"),
            "pnl": trade.get("pnl", 0.0),
            "reason": trade.get("reason", ""),
        }
        for trade in recent_trades
    ]

    lessons = []
    if worst_symbols:
        lessons.append(f"Recent weakest symbols: {', '.join(f'{ticker} ({pnl:.2f})' for ticker, pnl in worst_symbols if ticker)}.")
    if best_symbols:
        lessons.append(f"Recent strongest symbols: {', '.join(f'{ticker} ({pnl:.2f})' for ticker, pnl in best_symbols if ticker)}.")
    if worst_reasons and worst_reasons[0][1] < 0:
        lessons.append(f"Most costly recent pattern: {worst_reasons[0][0]} ({worst_reasons[0][1]:.2f}).")

    return {
        "closed_trades": len(closed_trades),
        "win_rate_pct": round((len(winning_trades) / max(1, len(closed_trades))) * 100, 2),
        "realized_pnl": round(sum(float(trade.get("pnl", 0.0)) for trade in closed_trades), 2),
        "total_return_pct": round(total_return_pct, 2),
        "recent_trades": recent_trade_notes,
        "best_symbols": [{"ticker": ticker, "pnl": round(pnl, 2)} for ticker, pnl in best_symbols if ticker],
        "worst_symbols": [{"ticker": ticker, "pnl": round(pnl, 2)} for ticker, pnl in worst_symbols if ticker],
        "lessons": lessons,
    }
