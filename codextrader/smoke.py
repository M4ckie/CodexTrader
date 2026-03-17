"""Lightweight smoke checks for CodexTrader deployments."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .artifact_repository import ArtifactRepository
from .app_meta import APP_NAME, APP_VERSION, DASHBOARD_PAGES
from .config import default_scenario_name, get_scenario, get_scenarios, scenario_file_path
from .news_scraper import scrape_public_headlines
from .portfolio import load_portfolio


def _git_sha(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _check_http(url: str) -> dict:
    try:
        with urlopen(url, timeout=10) as response:
            body = response.read(4096).decode("utf-8", errors="ignore")
            return {
                "status": "pass" if response.status == 200 else "fail",
                "details": {
                    "url": url,
                    "http_status": response.status,
                    "contains_streamlit_marker": "streamlit" in body.lower(),
                },
            }
    except URLError as exc:
        return {
            "status": "fail",
            "details": {
                "url": url,
                "error": str(exc),
            },
        }


def run_smoke_check(
    output_dir: Path,
    portfolio_dir: Path,
    scenario_name: str | None = None,
    url: str | None = None,
    news_ticker: str | None = None,
) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    selected_scenario = scenario_name or default_scenario_name()
    repository = ArtifactRepository(output_dir)

    checks: list[dict] = []
    scenarios = get_scenarios()
    scenario = get_scenario(selected_scenario)
    checks.append(
        {
            "name": "scenario_config",
            "status": "pass" if selected_scenario in scenarios else "fail",
            "details": {
                "scenario": selected_scenario,
                "scenario_file": str(scenario_file_path()),
                "scenario_count": len(scenarios),
            },
        }
    )

    checks.append(
        {
            "name": "dashboard_pages",
            "status": "pass" if "Brief History" in DASHBOARD_PAGES else "fail",
            "details": {
                "pages": DASHBOARD_PAGES,
            },
        }
    )

    portfolio = load_portfolio(portfolio_dir, selected_scenario)
    checks.append(
        {
            "name": "portfolio_state",
            "status": "pass",
            "details": {
                "cash": portfolio.cash,
                "positions": len(portfolio.positions),
                "pending_orders": len(portfolio.pending_orders),
                "trade_log_entries": len(portfolio.trade_log),
                "equity_history_entries": len(portfolio.equity_history),
                "initial_cash": scenario.bot.initial_cash,
            },
        }
    )

    scheduler_status_path = output_dir / "scheduler" / "scheduler_status.json"
    if scheduler_status_path.exists():
        scheduler_status = repository.load_scheduler_status()
        checks.append(
            {
                "name": "scheduler_status",
                "status": "pass",
                "details": {
                    "path": str(scheduler_status_path),
                    "state": scheduler_status.state if scheduler_status else None,
                    "last_successful_run": scheduler_status.last_successful_run if scheduler_status else None,
                    "last_error": scheduler_status.last_error if scheduler_status else None,
                },
            }
        )
    else:
        checks.append(
            {
                "name": "scheduler_status",
                "status": "warn",
                "details": {
                    "path": str(scheduler_status_path),
                    "message": "No scheduler status file found.",
                },
            }
        )

    execution_payload, execution_path = repository.find_latest_execution(selected_scenario)
    if execution_payload and execution_path:
        execution_payload_dict = execution_payload.to_dict()
        required_keys = {"scenario", "market_as_of", "generated_at", "decisions", "portfolio_context"}
        missing_keys = sorted(required_keys - set(execution_payload_dict))
        checks.append(
            {
                "name": "latest_execution",
                "status": "pass" if not missing_keys else "fail",
                "details": {
                    "path": str(execution_path),
                    "tickers": execution_payload.tickers,
                    "decisions": len(execution_payload.decisions),
                    "executed_trades": len(execution_payload.executed_trades),
                    "placed_orders": len(execution_payload.placed_orders),
                    "has_memory": bool(execution_payload.portfolio_context.get("memory")),
                    "has_review": bool(execution_payload.portfolio_context.get("review")),
                    "missing_keys": missing_keys,
                },
            }
        )
    else:
        checks.append(
            {
                "name": "latest_execution",
                "status": "warn",
                "details": {
                    "message": f"No daily_execution.json found for scenario {selected_scenario}.",
                },
            }
        )

    if url:
        http_check = _check_http(url)
        http_check["name"] = "dashboard_http"
        checks.append(http_check)

    if news_ticker:
        try:
            headlines = scrape_public_headlines(news_ticker, max_items=3)
            checks.append(
                {
                    "name": "news_scraper",
                    "status": "pass" if headlines else "warn",
                    "details": {
                        "ticker": news_ticker,
                        "headline_count": len(headlines),
                        "sources": sorted({item.source for item in headlines}),
                        "urls_present": sum(1 for item in headlines if item.url),
                    },
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": "news_scraper",
                    "status": "fail",
                    "details": {
                        "ticker": news_ticker,
                        "error": str(exc),
                    },
                }
            )

    overall_status = "pass"
    if any(check["status"] == "fail" for check in checks):
        overall_status = "fail"
    elif any(check["status"] == "warn" for check in checks):
        overall_status = "warn"

    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "git_sha": _git_sha(repo_root),
        "scenario": selected_scenario,
        "output_dir": str(output_dir),
        "portfolio_dir": str(portfolio_dir),
        "status": overall_status,
        "checks": checks,
    }
