"""End-of-day briefing and OpenAI decision pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .artifacts import ExecutionReportArtifact, write_json_file
from .config import ScenarioConfig, default_scenario_name, get_scenario
from .brief_builder import build_daily_brief, render_brief_markdown, render_brief_payload
from .memory import build_portfolio_memory, build_review_artifact
from .models import DailyBrief, Signal
from .openai_strategy import decide_from_brief
from .portfolio import build_portfolio_context, execute_daily_decisions, load_portfolio, save_portfolio
from .providers import make_research_provider
from .universe import select_candidates


@dataclass(frozen=True)
class DailyRunArtifacts:
    brief: DailyBrief
    decisions: list[Signal]
    execution: dict
    execution_report: ExecutionReportArtifact
    review_report: dict


@dataclass(frozen=True)
class PersistedDailyRun:
    paths: dict[str, Path]
    portfolio_path: Path


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
    write_json_file(json_path, render_brief_payload(brief))
    md_path.write_text(render_brief_markdown(brief), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def save_decisions(decisions: list[Signal], output_path: Path) -> None:
    payload = [decision.__dict__ for decision in decisions]
    write_json_file(output_path, payload)


def save_execution_report(report: ExecutionReportArtifact, output_path: Path) -> None:
    write_json_file(output_path, report.to_dict())


def save_review_report(portfolio, output_path: Path) -> None:
    write_json_file(output_path, build_review_artifact(portfolio))


def generate_daily_run_artifacts(
    tickers: list[str] | None,
    provider_name: str,
    data_dir: Path,
    openai_model: str,
    max_new_trades: int | None,
    scenario_name: str | None = None,
    portfolio_dir: Path | None = None,
    portfolio_context: dict | None = None,
) -> tuple[DailyRunArtifacts, object]:
    scenario_key = scenario_name or default_scenario_name()
    scenario = _load_scenario(scenario_key)
    portfolio_base_dir = portfolio_dir or Path("output/portfolios")
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
    decisions = decide_from_brief(
        brief,
        model=openai_model,
        max_new_trades=max_new_trades if max_new_trades is not None else scenario.max_new_trades,
    )
    execution = execute_daily_decisions(portfolio, brief, decisions)
    review_report = build_portfolio_context(portfolio, brief).get("review", {})
    return (
        DailyRunArtifacts(
            brief=brief,
            decisions=decisions,
            execution=execution,
            execution_report=ExecutionReportArtifact.from_run_data(brief, decisions, execution, scenario_key),
            review_report=review_report,
        ),
        portfolio,
    )


def persist_daily_run(artifacts: DailyRunArtifacts, portfolio, output_dir: Path, portfolio_dir: Path) -> PersistedDailyRun:
    paths = save_brief(artifacts.brief, output_dir)
    decision_path = output_dir / "daily_decisions.json"
    save_decisions(artifacts.decisions, decision_path)
    paths["decisions"] = decision_path
    portfolio_path = save_portfolio(portfolio_dir, portfolio)
    paths["portfolio"] = portfolio_path
    execution_path = output_dir / "daily_execution.json"
    save_execution_report(artifacts.execution_report, execution_path)
    paths["execution"] = execution_path
    review_path = output_dir / "daily_review.json"
    write_json_file(review_path, artifacts.review_report)
    paths["review"] = review_path
    return PersistedDailyRun(paths=paths, portfolio_path=portfolio_path)


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
    portfolio_base_dir = portfolio_dir or (output_dir / "portfolios")
    artifacts, portfolio = generate_daily_run_artifacts(
        tickers=tickers,
        provider_name=provider_name,
        data_dir=data_dir,
        openai_model=openai_model,
        max_new_trades=max_new_trades,
        scenario_name=scenario_name,
        portfolio_dir=portfolio_base_dir,
        portfolio_context=portfolio_context,
    )
    persisted = persist_daily_run(artifacts, portfolio, output_dir, portfolio_base_dir)
    return artifacts.brief, artifacts.decisions, persisted.paths, artifacts.execution


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
