"""Streamlit dashboard for CodexTrader."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from codextrader.config import get_scenario, get_scenarios, scenario_file_path
from codextrader.env import load_dotenv
from codextrader.portfolio import load_portfolio


load_dotenv()

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
PORTFOLIO_DIR = OUTPUT_DIR / "portfolios"
SCHEDULER_DIR = OUTPUT_DIR / "scheduler"

st.set_page_config(page_title="CodexTrader", page_icon="CT", layout="wide")


def _find_latest_execution(scenario_name: str) -> tuple[dict | None, Path | None]:
    candidates = sorted(OUTPUT_DIR.glob("**/daily_execution.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("scenario") == scenario_name:
            return payload, path
    return None, None


def _load_latest_brief_markdown(execution_path: Path | None) -> str | None:
    if execution_path is None:
        return None
    brief_path = execution_path.parent / "daily_brief.md"
    if not brief_path.exists():
        return None
    return brief_path.read_text(encoding="utf-8")


def _positions_frame(positions: dict) -> pd.DataFrame:
    rows = []
    for ticker, position in positions.items():
        rows.append(
            {
                "Ticker": ticker,
                "Shares": position["shares"],
                "Entry Price": position["entry_price"],
                "Entry Date": position["entry_date"],
                "Reason": position["reason"],
            }
        )
    return pd.DataFrame(rows)


def _trades_frame(trades: list[dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "pnl", "cash_after", "reason"])
    return pd.DataFrame(trades)


def _equity_history_frame(history: list[dict]) -> pd.DataFrame:
    if not history:
        return pd.DataFrame(columns=["date", "equity", "cash", "invested", "position_count"])
    frame = pd.DataFrame(history)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date")


def _load_scheduler_status() -> dict | None:
    path = SCHEDULER_DIR / "scheduler_status.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _memory_payload(execution_payload: dict | None) -> dict | None:
    if not execution_payload:
        return None
    return execution_payload.get("portfolio_context", {}).get("memory")


scenarios = get_scenarios()
scenario_name = st.sidebar.selectbox("Scenario", options=list(scenarios.keys()))
scenario = get_scenario(scenario_name)
page = st.sidebar.radio("Page", ["Overview", "Decisions", "Trade Log", "Scenario Config"])
st.sidebar.caption(f"Scenario file: {scenario_file_path()}")

portfolio = load_portfolio(PORTFOLIO_DIR, scenario_name)
execution_payload, execution_path = _find_latest_execution(scenario_name)
brief_markdown = _load_latest_brief_markdown(execution_path)
scheduler_status = _load_scheduler_status()

if page == "Overview":
    st.title(f"CodexTrader Dashboard: {scenario_name}")
    left, mid, right, far = st.columns(4)
    invested = 0.0
    if execution_payload:
        invested = execution_payload["portfolio_context"].get("invested", 0.0)
        equity = execution_payload["portfolio_context"].get("equity", portfolio.cash)
    else:
        equity = portfolio.cash
    left.metric("Cash", f"${portfolio.cash:,.2f}")
    mid.metric("Invested", f"${invested:,.2f}")
    right.metric("Equity", f"${equity:,.2f}")
    far.metric("Open Positions", len(portfolio.positions))

    st.subheader("Scheduler Status")
    if scheduler_status:
        a, b, c = st.columns(3)
        a.metric("State", scheduler_status.get("state", "unknown"))
        b.metric("Last Success", scheduler_status.get("last_successful_run") or "never")
        c.metric("Next Daily Time", f"{scheduler_status.get('schedule_time', 'n/a')} {scheduler_status.get('timezone', '')}".strip())
        if scheduler_status.get("last_error"):
            st.error(f"Last scheduler error: {scheduler_status['last_error']}")
    else:
        st.info("No scheduler status file found yet.")

    st.subheader("Open Positions")
    positions_df = _positions_frame(portfolio.positions)
    if positions_df.empty:
        st.info("No open positions for this scenario.")
    else:
        st.dataframe(positions_df, use_container_width=True, hide_index=True)

    st.subheader("Latest Run")
    if execution_payload:
        st.write(f"Market as of: `{execution_payload.get('market_as_of')}`")
        st.write(f"Candidates: {', '.join(execution_payload.get('tickers', []))}")
        if execution_payload.get("executed_trades"):
            st.dataframe(_trades_frame(execution_payload["executed_trades"]), use_container_width=True, hide_index=True)
        else:
            st.info("No trades executed on the latest run.")
    else:
        st.info("No daily execution report found yet for this scenario.")

    st.subheader("Equity History")
    equity_df = _equity_history_frame(portfolio.equity_history)
    if equity_df.empty:
        st.info("No equity history yet.")
    else:
        st.line_chart(equity_df.set_index("date")[["equity", "cash"]], height=280)

if page == "Decisions":
    st.title(f"Decisionmaking: {scenario_name}")
    if execution_payload:
        memory = _memory_payload(execution_payload)
        if memory:
            st.subheader("Portfolio Memory Sent To Model")
            st.json(memory, expanded=False)
        decisions = execution_payload.get("decisions", [])
        if decisions:
            st.subheader("Latest Model Decisions")
            st.dataframe(pd.DataFrame(decisions), use_container_width=True, hide_index=True)
        else:
            st.info("No decisions recorded in the latest run.")
        st.subheader("Latest Brief")
        if brief_markdown:
            st.markdown(brief_markdown)
        else:
            st.info("No brief markdown found for the latest run.")
    else:
        st.info("Run `daily-run` first to populate decisions and briefing data.")

if page == "Trade Log":
    st.title(f"Trade Log: {scenario_name}")
    trades_df = _trades_frame(portfolio.trade_log)
    if trades_df.empty:
        st.info("No trades have been executed for this scenario.")
    else:
        st.dataframe(trades_df, use_container_width=True, hide_index=True)
        if "pnl" in trades_df.columns:
            st.subheader("Realized P&L by Trade")
            pnl_df = trades_df[trades_df["action"] == "SELL"][["ticker", "pnl"]]
            if pnl_df.empty:
                st.info("No closed trades yet.")
            else:
                st.bar_chart(pnl_df.set_index("ticker"))
        st.subheader("Trade Timeline")
        trades_timeline = trades_df.copy()
        trades_timeline["date"] = pd.to_datetime(trades_timeline["date"])
        st.dataframe(trades_timeline.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

if page == "Scenario Config":
    st.title(f"Scenario Config: {scenario_name}")
    st.json(
        {
            "description": scenario.description,
            "bot": scenario.bot.__dict__,
            "universe": scenario.universe.__dict__,
            "max_new_trades": scenario.max_new_trades,
            "avoid_earnings_within_days": scenario.avoid_earnings_within_days,
        },
        expanded=True,
    )
