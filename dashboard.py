"""Streamlit dashboard for CodexTrader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from codextrader.artifact_repository import ArtifactRepository
from codextrader.app_meta import APP_NAME, DASHBOARD_PAGES
from codextrader.config import get_scenario, get_scenarios, scenario_file_path
from codextrader.env import load_dotenv
from codextrader.portfolio import load_portfolio


load_dotenv()

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
PORTFOLIO_DIR = OUTPUT_DIR / "portfolios"
ARTIFACTS = ArtifactRepository(OUTPUT_DIR)

st.set_page_config(page_title=APP_NAME, page_icon="CT", layout="wide")

def _load_latest_brief_markdown(execution_path: Path | None) -> str | None:
    return ARTIFACTS.load_brief_markdown(execution_path)


def _load_brief_payload(execution_path: Path | None) -> dict | None:
    return ARTIFACTS.load_brief_payload(execution_path)


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


def _pending_orders_frame(orders: list[dict]) -> pd.DataFrame:
    if not orders:
        return pd.DataFrame(columns=["ticker", "action", "shares", "placed_at", "reason"])
    return pd.DataFrame(orders)


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


def _memory_payload(execution_payload) -> dict | None:
    if not execution_payload:
        return None
    return execution_payload.portfolio_context.get("memory")


def _brief_portfolio_context(execution_payload, execution_path: Path | None) -> dict | None:
    if execution_payload and execution_payload.brief_portfolio_context:
        return execution_payload.brief_portfolio_context
    brief_payload = _load_brief_payload(execution_path)
    if not brief_payload:
        return None
    return brief_payload.get("portfolio_context")


def _review_payload(execution_payload) -> dict | None:
    if not execution_payload:
        return None
    return execution_payload.portfolio_context.get("review")


def _history_index_frame(history) -> pd.DataFrame:
    rows = []
    for payload, path in history:
        rows.append(
            {
                "market_as_of": payload.market_as_of,
                "generated_at": payload.generated_at,
                "decisions": len(payload.decisions),
                "executed_trades": len(payload.executed_trades),
                "placed_orders": len(payload.placed_orders),
                "path": str(path),
            }
        )
    return pd.DataFrame(rows)


def _scenario_comparison_frame(scenarios: dict, repository: ArtifactRepository) -> pd.DataFrame:
    rows = []
    for name, scenario_cfg in scenarios.items():
        portfolio = load_portfolio(PORTFOLIO_DIR, name)
        execution_payload, _ = repository.find_latest_execution(name)
        latest_equity = portfolio.cash
        latest_market_as_of = None
        candidate_count = 0
        candidates = ""
        decisions = 0
        executed = 0
        if execution_payload:
            latest_equity = execution_payload.portfolio_context.get("equity", latest_equity)
            latest_market_as_of = execution_payload.market_as_of
            candidate_count = len(execution_payload.tickers)
            candidates = ", ".join(execution_payload.tickers[:6])
            decisions = len(execution_payload.decisions)
            executed = len(execution_payload.executed_trades)
        rows.append(
            {
                "Scenario": name,
                "Description": scenario_cfg.description,
                "Cash": round(portfolio.cash, 2),
                "Equity": round(latest_equity, 2),
                "Open Positions": len(portfolio.positions),
                "Pending Orders": len(portfolio.pending_orders),
                "Trades Logged": len(portfolio.trade_log),
                "Last Run": latest_market_as_of or "none",
                "Candidates": candidate_count,
                "Decisions": decisions,
                "Executed Trades": executed,
                "Universe Max": scenario_cfg.universe.max_universe_size,
                "Min Price": scenario_cfg.universe.min_price,
                "Min Market Cap": scenario_cfg.universe.min_market_cap,
                "Min Dollar Vol": scenario_cfg.universe.min_avg_dollar_volume,
                "Top Tickers": candidates,
            }
        )
    return pd.DataFrame(rows).sort_values(["Equity", "Scenario"], ascending=[False, True])


scenarios = get_scenarios()
scenario_name = st.sidebar.selectbox("Scenario", options=list(scenarios.keys()))
scenario = get_scenario(scenario_name)
page = st.sidebar.radio("Page", DASHBOARD_PAGES)
st.sidebar.caption(f"Scenario file: {scenario_file_path()}")

portfolio = load_portfolio(PORTFOLIO_DIR, scenario_name)
execution_payload, execution_path = ARTIFACTS.find_latest_execution(scenario_name)
execution_history = ARTIFACTS.load_execution_history(scenario_name)
brief_markdown = _load_latest_brief_markdown(execution_path)
scheduler_status = ARTIFACTS.load_scheduler_status()
brief_portfolio_context = _brief_portfolio_context(execution_payload, execution_path)

if page == "Scenario Compare":
    st.title(f"{APP_NAME} Scenario Compare", anchor="scenario-compare")
    comparison_df = _scenario_comparison_frame(scenarios, ARTIFACTS)
    a, b, c, d = st.columns(4)
    a.metric("Scenario Count", len(comparison_df))
    b.metric("Best Equity", f"${comparison_df['Equity'].max():,.2f}" if not comparison_df.empty else "$0.00")
    c.metric("Most Open Positions", int(comparison_df["Open Positions"].max()) if not comparison_df.empty else 0)
    d.metric("Most Candidates", int(comparison_df["Candidates"].max()) if not comparison_df.empty else 0)

    st.subheader("Scenario Summary", anchor="scenario-summary")
    st.dataframe(comparison_df, width="stretch", hide_index=True)

    if not comparison_df.empty:
        chart_df = comparison_df.set_index("Scenario")[["Equity", "Cash", "Open Positions", "Candidates"]]
        st.subheader("Quick Compare", anchor="scenario-compare-chart")
        st.bar_chart(chart_df[["Equity", "Cash"]], height=320)
        st.bar_chart(chart_df[["Open Positions", "Candidates"]], height=260)

if page == "Overview":
    st.title(f"{APP_NAME} Dashboard: {scenario_name}", anchor=f"dashboard-{scenario_name}")
    left, mid, right, far = st.columns(4)
    invested = 0.0
    if execution_payload:
        invested = execution_payload.portfolio_context.get("invested", 0.0)
        equity = execution_payload.portfolio_context.get("equity", portfolio.cash)
    else:
        equity = portfolio.cash
    left.metric("Cash", f"${portfolio.cash:,.2f}")
    mid.metric("Invested", f"${invested:,.2f}")
    right.metric("Equity", f"${equity:,.2f}")
    far.metric("Open Positions", len(portfolio.positions))

    st.subheader("Scheduler Status", anchor=f"scheduler-status-{scenario_name}")
    if scheduler_status:
        a, b, c = st.columns(3)
        a.metric("State", scheduler_status.state or "unknown")
        b.metric("Last Success", scheduler_status.last_successful_run or "never")
        c.metric("Next Daily Time", f"{scheduler_status.schedule_time or 'n/a'} {scheduler_status.timezone}".strip())
        if scheduler_status.last_error:
            st.error(f"Last scheduler error: {scheduler_status.last_error}")
    else:
        st.info("No scheduler status file found yet.")

    st.subheader("Open Positions", anchor=f"open-positions-{scenario_name}")
    positions_df = _positions_frame(portfolio.positions)
    if positions_df.empty:
        st.info("No open positions for this scenario.")
    else:
        st.dataframe(positions_df, width="stretch", hide_index=True)

    st.subheader("Pending Orders", anchor=f"pending-orders-{scenario_name}")
    pending_df = _pending_orders_frame(portfolio.pending_orders)
    if pending_df.empty:
        st.info("No pending next-session orders.")
    else:
        st.dataframe(pending_df, width="stretch", hide_index=True)

    st.subheader("Latest Run", anchor=f"latest-run-{scenario_name}")
    if execution_payload:
        st.write(f"Market as of: `{execution_payload.market_as_of}`")
        st.write(f"Candidates: {', '.join(execution_payload.tickers)}")
        if execution_payload.executed_trades:
            st.dataframe(
                _trades_frame([item.to_dict() for item in execution_payload.executed_trades]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No trades executed on the latest run.")
        if execution_payload.placed_orders:
            st.write("Placed for next session:")
            st.dataframe(
                _pending_orders_frame([item.to_dict() for item in execution_payload.placed_orders]),
                width="stretch",
                hide_index=True,
            )
    else:
        st.info("No daily execution report found yet for this scenario.")

    st.subheader("Equity History", anchor=f"equity-history-{scenario_name}")
    equity_df = _equity_history_frame(portfolio.equity_history)
    if equity_df.empty:
        st.info("No equity history yet.")
    elif len(equity_df) == 1:
        st.dataframe(equity_df, width="stretch", hide_index=True)
    else:
        st.line_chart(equity_df.set_index("date")[["equity", "cash"]], height=280)

if page == "Decisions":
    st.title(f"Decisionmaking: {scenario_name}", anchor=f"decisionmaking-{scenario_name}")
    if execution_payload:
        if brief_portfolio_context:
            st.subheader("Portfolio Context Sent To Model", anchor=f"brief-context-{scenario_name}")
            st.json(brief_portfolio_context, expanded=False)

        st.subheader("Portfolio State After Latest Execution", anchor=f"post-execution-context-{scenario_name}")
        st.json(execution_payload.portfolio_context, expanded=False)

        memory = _memory_payload(execution_payload)
        if memory:
            st.subheader("Portfolio Memory After Latest Execution", anchor=f"post-execution-memory-{scenario_name}")
            st.json(memory, expanded=False)
        decisions = execution_payload.decisions
        if decisions:
            st.subheader("Latest Model Decisions", anchor=f"latest-decisions-{scenario_name}")
            st.dataframe(pd.DataFrame(decisions), width="stretch", hide_index=True)
        else:
            st.info("No decisions recorded in the latest run.")
        st.subheader("Latest Brief Sent To Model", anchor=f"latest-brief-{scenario_name}")
        if brief_markdown:
            st.markdown(brief_markdown)
        else:
            st.info("No brief markdown found for the latest run.")
    else:
        st.info("Run `daily-run` first to populate decisions and briefing data.")

if page == "Trade Log":
    st.title(f"Trade Log: {scenario_name}", anchor=f"trade-log-{scenario_name}")
    trades_df = _trades_frame(portfolio.trade_log)
    if trades_df.empty:
        st.info("No trades have been executed for this scenario.")
    else:
        st.dataframe(trades_df, width="stretch", hide_index=True)
        if "pnl" in trades_df.columns:
            st.subheader("Realized P&L by Trade", anchor=f"realized-pnl-{scenario_name}")
            pnl_df = trades_df[trades_df["action"] == "SELL"][["ticker", "pnl"]]
            if pnl_df.empty:
                st.info("No closed trades yet.")
            else:
                st.bar_chart(pnl_df.set_index("ticker"))
        st.subheader("Trade Timeline", anchor=f"trade-timeline-{scenario_name}")
        trades_timeline = trades_df.copy()
        trades_timeline["date"] = pd.to_datetime(trades_timeline["date"])
        st.dataframe(trades_timeline.sort_values("date", ascending=False), width="stretch", hide_index=True)

if page == "Brief History":
    st.title(f"Brief History: {scenario_name}", anchor=f"brief-history-{scenario_name}")
    if not execution_history:
        st.info("No historical brief/execution files found for this scenario yet.")
    else:
        index_df = _history_index_frame(execution_history)
        st.subheader("Available Runs", anchor=f"available-runs-{scenario_name}")
        st.dataframe(index_df, width="stretch", hide_index=True)

        labels = [
            f"{payload.market_as_of or 'unknown-date'} | decisions={len(payload.decisions)} | executed={len(payload.executed_trades)}"
            for payload, _ in execution_history
        ]
        selected_label = st.selectbox("Select historical run", options=labels)
        selected_index = labels.index(selected_label)
        selected_payload, selected_path = execution_history[selected_index]

        st.subheader("Selected Run Summary", anchor=f"selected-run-summary-{scenario_name}")
        st.json(
            {
                "market_as_of": selected_payload.market_as_of,
                "generated_at": selected_payload.generated_at,
                "execution_path": str(selected_path),
                "tickers": selected_payload.tickers,
            },
            expanded=False,
        )

        selected_brief_context = _brief_portfolio_context(selected_payload, selected_path)
        if selected_brief_context:
            st.subheader("Portfolio Context Sent To Model", anchor=f"selected-brief-context-{scenario_name}")
            st.json(selected_brief_context, expanded=False)

        st.subheader("Portfolio State After Execution", anchor=f"selected-post-execution-{scenario_name}")
        st.json(selected_payload.portfolio_context, expanded=False)

        review = _review_payload(selected_payload)
        if review:
            st.subheader("Review Sent With Brief", anchor=f"selected-review-{scenario_name}")
            st.json(review, expanded=False)

        st.subheader("Decisions", anchor=f"selected-decisions-{scenario_name}")
        decisions = selected_payload.decisions
        if decisions:
            st.dataframe(pd.DataFrame(decisions), width="stretch", hide_index=True)
        else:
            st.info("No decisions recorded for this run.")

        st.subheader("Executed Trades", anchor=f"selected-executed-trades-{scenario_name}")
        executed = [item.to_dict() for item in selected_payload.executed_trades]
        if executed:
            st.dataframe(_trades_frame(executed), width="stretch", hide_index=True)
        else:
            st.info("No trades executed in this run.")

        placed = [item.to_dict() for item in selected_payload.placed_orders]
        st.subheader("Placed Orders", anchor=f"selected-placed-orders-{scenario_name}")
        if placed:
            st.dataframe(_pending_orders_frame(placed), width="stretch", hide_index=True)
        else:
            st.info("No next-session orders were placed in this run.")

        brief_path = selected_path.parent / "daily_brief.md"
        st.subheader("Brief Markdown", anchor=f"selected-brief-markdown-{scenario_name}")
        if brief_path.exists():
            st.markdown(brief_path.read_text(encoding="utf-8"))
        else:
            st.info("No markdown brief found for this historical run.")

if page == "Scenario Config":
    st.title(f"Scenario Config: {scenario_name}", anchor=f"scenario-config-{scenario_name}")
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
