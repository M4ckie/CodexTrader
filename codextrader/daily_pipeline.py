"""End-of-day briefing and OpenAI decision pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from .config import ScenarioConfig, default_scenario_name, get_scenario
from .brief_builder import build_daily_brief, render_brief_json, render_brief_markdown
from .memory import build_portfolio_memory
from .models import DailyBrief, Signal
from .openai_strategy import decide_from_brief
from .portfolio import build_portfolio_context, execute_daily_decisions, load_portfolio, save_portfolio
from .providers import make_research_provider
from .universe import select_candidates


def _load_scenario(name: str) -> ScenarioConfig:
    return get_scenario(name)


def discover_candidates(
    provider_name: str,
    data_dir: Path,
    scenario_name: str | None = None,
    tickers: list[str] | None = None,
) -> list:
    scenario_key = scenario_name or default_scenario_name()
    scenario = _load_scenario(scenario_key)
    provider = make_research_provider(provider_name, data_dir)
    source_tickers = tickers or provider.available_tickers(scenario.universe)
    snapshots = []
    for ticker in source_tickers:
        try:
            snapshots.append(provider.build_ticker_snapshot(ticker))
        except RuntimeError as exc:
            message = str(exc)
            if "25 requests per day" in message:
                break
            if "1 request per second" in message:
                continue
            if "insufficient history" in message.lower():
                continue
            raise
    return select_candidates(snapshots, scenario.universe, scenario.avoid_earnings_within_days)


def collect_daily_brief(
    tickers: list[str] | None,
    provider_name: str,
    data_dir: Path,
    scenario_name: str | None = None,
    portfolio_context: dict | None = None,
) -> DailyBrief:
    provider = make_research_provider(provider_name, data_dir)
    market_snapshot = provider.build_market_snapshot()
    ticker_snapshots = discover_candidates(
        provider_name=provider_name,
        data_dir=data_dir,
        scenario_name=scenario_name or default_scenario_name(),
        tickers=tickers,
    )
    return build_daily_brief(market_snapshot, ticker_snapshots, portfolio_context=portfolio_context)


def save_brief(brief: DailyBrief, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "daily_brief.json"
    md_path = output_dir / "daily_brief.md"
    json_path.write_text(render_brief_json(brief), encoding="utf-8")
    md_path.write_text(render_brief_markdown(brief), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def save_decisions(decisions: list[Signal], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [decision.__dict__ for decision in decisions]
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_execution_report(
    brief: DailyBrief,
    decisions: list[Signal],
    execution: dict,
    scenario_name: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": scenario_name,
        "generated_at": brief.generated_at,
        "market_as_of": brief.market.as_of,
        "brief_portfolio_context": brief.portfolio_context,
        "portfolio_context": execution["portfolio_context"],
        "decisions": [decision.__dict__ for decision in decisions],
        "executed_trades": execution["executed_trades"],
        "placed_orders": execution.get("placed_orders", []),
        "equity_history": execution["portfolio_context"].get("equity_history", []),
        "tickers": [snapshot.ticker for snapshot in brief.tickers],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_review_report(portfolio, output_path: Path) -> None:
    from .memory import build_review_artifact

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build_review_artifact(portfolio), indent=2), encoding="utf-8")


def run_end_of_day_decision(
    tickers: list[str] | None,
    provider_name: str,
    data_dir: Path,
    output_dir: Path,
    openai_model: str,
    max_new_trades: int | None,
    scenario_name: str | None = None,
    portfolio_dir: Path | None = None,
    portfolio_context: dict | None = None,
) -> tuple[DailyBrief, list[Signal], dict[str, Path], dict]:
    scenario_key = scenario_name or default_scenario_name()
    scenario = _load_scenario(scenario_key)
    portfolio_base_dir = portfolio_dir or (output_dir / "portfolios")
    portfolio = load_portfolio(portfolio_base_dir, scenario_key)
    effective_portfolio_context = portfolio_context
    if effective_portfolio_context is None:
        effective_portfolio_context = {
            "scenario": portfolio.scenario,
            "cash": round(portfolio.cash, 2),
            "positions": list(portfolio.positions.keys()),
            "position_count": len(portfolio.positions),
            "last_updated": portfolio.last_updated,
            "memory": build_portfolio_memory(portfolio),
            "mode": "paper",
        }
    brief = collect_daily_brief(
        tickers,
        provider_name,
        data_dir,
        scenario_name=scenario_key,
        portfolio_context=effective_portfolio_context,
    )
    paths = save_brief(brief, output_dir)
    decisions = decide_from_brief(
        brief,
        model=openai_model,
        max_new_trades=max_new_trades if max_new_trades is not None else scenario.max_new_trades,
    )
    decision_path = output_dir / "daily_decisions.json"
    save_decisions(decisions, decision_path)
    paths["decisions"] = decision_path
    execution = execute_daily_decisions(portfolio, brief, decisions)
    portfolio_path = save_portfolio(portfolio_base_dir, portfolio)
    paths["portfolio"] = portfolio_path
    execution_path = output_dir / "daily_execution.json"
    save_execution_report(brief, decisions, execution, scenario_key, execution_path)
    paths["execution"] = execution_path
    review_path = output_dir / "daily_review.json"
    save_review_report(portfolio, review_path)
    paths["review"] = review_path
    return brief, decisions, paths, execution


def get_portfolio_status(scenario_name: str | None, portfolio_dir: Path, brief: DailyBrief | None = None) -> dict:
    portfolio = load_portfolio(portfolio_dir, scenario_name or default_scenario_name())
    if brief is None:
        return {
            "scenario": portfolio.scenario,
            "cash": round(portfolio.cash, 2),
            "positions": list(portfolio.positions.keys()),
            "position_count": len(portfolio.positions),
            "last_updated": portfolio.last_updated,
            "trade_count": len(portfolio.trade_log),
        }
    return build_portfolio_context(portfolio, brief)
