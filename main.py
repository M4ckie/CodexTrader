"""CLI for generating data and running the simulated trading bot."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from codextrader.backtest import run_backtest, save_result
from codextrader.config import (
    BotConfig,
    DEFAULT_TICKERS,
    default_scenario_name,
    get_scenario,
    get_scenarios,
    scenario_file_path,
    scenario_names,
)
from codextrader.data import generate_synthetic_dataset, load_market_data
from codextrader.daily_pipeline import collect_daily_brief, discover_candidates, run_end_of_day_decision, save_brief
from codextrader.env import load_dotenv
from codextrader.scheduler import make_scheduler_config, run_forever, run_once


def _build_parser() -> argparse.ArgumentParser:
    scenario_choices = scenario_names()
    default_scenario = default_scenario_name()
    parser = argparse.ArgumentParser(description="Offline AI-style stock trading bot research app")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-data", help="Create synthetic market CSVs")
    generate.add_argument("--output-dir", default="data/market", help="Directory for ticker CSV files")
    generate.add_argument("--days", type=int, default=280, help="Trading days per ticker")
    generate.add_argument("--seed", type=int, default=7, help="Random seed for deterministic generation")
    generate.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS, help="Ticker symbols to generate")

    backtest = subparsers.add_parser("backtest", help="Run the bot against CSV market data")
    backtest.add_argument("--data-dir", default="data/market", help="Directory containing ticker CSV files")
    backtest.add_argument("--initial-cash", type=float, default=100_000.0)
    backtest.add_argument("--max-positions", type=int, default=4)
    backtest.add_argument("--position-size-pct", type=float, default=0.24)
    backtest.add_argument("--buy-threshold", type=float, default=0.55)
    backtest.add_argument("--sell-threshold", type=float, default=-0.20)
    backtest.add_argument("--stop-loss-pct", type=float, default=0.08)
    backtest.add_argument("--take-profit-pct", type=float, default=0.18)
    backtest.add_argument("--strategy-provider", choices=["heuristic", "openai"], default="heuristic")
    backtest.add_argument("--openai-model", default="gpt-4.1-mini")
    backtest.add_argument("--output", default="output/backtest_report.json", help="Report path")

    brief = subparsers.add_parser("build-brief", help="Build an end-of-day brief from a provider")
    brief.add_argument("--provider", choices=["local", "alphavantage", "fmp"], default="local")
    brief.add_argument("--data-dir", default="data/market", help="Used by the local provider")
    brief.add_argument("--scenario", choices=scenario_choices, default=default_scenario)
    brief.add_argument("--tickers", nargs="+", help="Optional explicit tickers. If omitted, candidates are auto-selected.")
    brief.add_argument("--output-dir", default="output/daily_run", help="Where to write brief files")

    daily = subparsers.add_parser("daily-run", help="Build an end-of-day brief and ask OpenAI for decisions")
    daily.add_argument("--provider", choices=["local", "alphavantage", "fmp"], default="local")
    daily.add_argument("--data-dir", default="data/market", help="Used by the local provider")
    daily.add_argument("--scenario", choices=scenario_choices, default=default_scenario)
    daily.add_argument("--tickers", nargs="+", help="Optional explicit tickers. If omitted, candidates are auto-selected.")
    daily.add_argument("--output-dir", default="output/daily_run", help="Where to write brief and decision files")
    daily.add_argument("--portfolio-dir", default="output/portfolios", help="Where to persist scenario portfolio state")
    daily.add_argument("--openai-model", default="gpt-4.1-mini")
    daily.add_argument("--max-new-trades", type=int, help="Override the scenario default")

    scenarios = subparsers.add_parser("scenarios", help="List available portfolio scenarios")
    scenarios.add_argument("--verbose", action="store_true")
    scenarios.add_argument("--show-file", action="store_true")

    portfolio = subparsers.add_parser("portfolio-status", help="Show persisted paper portfolio state for a scenario")
    portfolio.add_argument("--scenario", choices=scenario_choices, default=default_scenario)
    portfolio.add_argument("--portfolio-dir", default="output/portfolios")

    schedule = subparsers.add_parser("schedule", help="Run the daily scheduler loop or one immediate scheduled cycle")
    schedule.add_argument("--provider", choices=["local", "alphavantage", "fmp"], default="alphavantage")
    schedule.add_argument("--scenario", dest="scenarios", nargs="+", choices=scenario_choices, help="Scenario names to run")
    schedule.add_argument("--data-dir", default="data/market")
    schedule.add_argument("--output-root", default="output/scheduled_runs")
    schedule.add_argument("--portfolio-dir", default="output/portfolios")
    schedule.add_argument("--log-dir", default="output/scheduler")
    schedule.add_argument("--openai-model", default="gpt-4.1-mini")
    schedule.add_argument("--max-new-trades", type=int)
    schedule.add_argument("--time", default="16:35", help="Daily schedule time in HH:MM")
    schedule.add_argument("--timezone", default="America/New_York")
    schedule.add_argument("--poll-seconds", type=int, default=30)
    schedule.add_argument("--run-now", action="store_true", help="Run one cycle immediately and exit")

    return parser


def cmd_generate_data(args: argparse.Namespace) -> None:
    written = generate_synthetic_dataset(
        output_dir=Path(args.output_dir),
        tickers=args.tickers,
        start_date=date(2024, 1, 2),
        days=args.days,
        seed=args.seed,
    )
    print(f"Generated {len(written)} ticker files in {args.output_dir}")


def cmd_backtest(args: argparse.Namespace) -> None:
    cfg = BotConfig(
        initial_cash=args.initial_cash,
        max_positions=args.max_positions,
        position_size_pct=args.position_size_pct,
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
    )
    market_data = load_market_data(Path(args.data_dir))
    result = run_backtest(
        market_data,
        cfg,
        strategy_provider=args.strategy_provider,
        openai_model=args.openai_model,
    )
    save_result(result, Path(args.output))

    summary = result.summary
    print("Backtest complete")
    print(f"Ending equity: ${summary['ending_equity']:.2f}")
    print(f"Total return: {summary['total_return_pct']:.2f}%")
    print(f"Annualized return: {summary['annualized_return_pct']:.2f}%")
    print(f"Max drawdown: {summary['max_drawdown_pct']:.2f}%")
    print(f"Closed trades: {summary['closed_trades']}")
    print(f"Win rate: {summary['win_rate_pct']:.2f}%")
    print(f"Report written to: {args.output}")


def cmd_build_brief(args: argparse.Namespace) -> None:
    scenario = get_scenario(args.scenario)
    candidates = discover_candidates(
        provider_name=args.provider,
        data_dir=Path(args.data_dir),
        scenario_name=args.scenario,
        tickers=args.tickers,
    )
    brief = collect_daily_brief(
        tickers=[snapshot.ticker for snapshot in candidates],
        provider_name=args.provider,
        data_dir=Path(args.data_dir),
        scenario_name=args.scenario,
        portfolio_context={
            "scenario": args.scenario,
            "cash": scenario.bot.initial_cash,
            "positions": [],
            "position_count": 0,
            "mode": "paper",
        },
    )
    paths = save_brief(brief, Path(args.output_dir))
    print("Brief complete")
    print(f"Scenario: {args.scenario}")
    print(f"Market as of: {brief.market.as_of}")
    print(f"Tickers covered: {len(brief.tickers)}")
    print("Selected candidates: " + ", ".join(snapshot.ticker for snapshot in brief.tickers))
    print(f"JSON brief: {paths['json']}")
    print(f"Markdown brief: {paths['markdown']}")


def cmd_daily_run(args: argparse.Namespace) -> None:
    brief, decisions, paths, execution = run_end_of_day_decision(
        tickers=args.tickers,
        provider_name=args.provider,
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        openai_model=args.openai_model,
        max_new_trades=args.max_new_trades,
        scenario_name=args.scenario,
        portfolio_dir=Path(args.portfolio_dir),
    )
    print("Daily run complete")
    print(f"Scenario: {args.scenario}")
    print(f"Market as of: {brief.market.as_of}")
    print(f"Decisions returned: {len(decisions)}")
    print("Candidates: " + ", ".join(snapshot.ticker for snapshot in brief.tickers))
    print(f"Executed trades: {len(execution['executed_trades'])}")
    print(f"Portfolio equity: {execution['portfolio_context']['equity']:.2f}")
    print(f"Brief JSON: {paths['json']}")
    print(f"Brief Markdown: {paths['markdown']}")
    print(f"Decisions JSON: {paths['decisions']}")
    print(f"Execution JSON: {paths['execution']}")
    print(f"Portfolio JSON: {paths['portfolio']}")


def cmd_scenarios(args: argparse.Namespace) -> None:
    scenarios = get_scenarios()
    for name, scenario in scenarios.items():
        print(f"{name}: {scenario.description}")
        if args.verbose:
            print(
                f"  max_new_trades={scenario.max_new_trades}, "
                f"max_positions={scenario.bot.max_positions}, "
                f"position_size_pct={scenario.bot.position_size_pct:.2f}, "
                f"min_price={scenario.universe.min_price:.2f}, "
                f"min_market_cap={scenario.universe.min_market_cap:.0f}, "
                f"min_avg_dollar_volume={scenario.universe.min_avg_dollar_volume:.0f}, "
                f"include_etfs={scenario.universe.include_etfs}, "
                f"max_universe_size={scenario.universe.max_universe_size}, "
                f"max_brief_candidates={scenario.universe.max_brief_candidates}"
            )
    if args.show_file:
        print(f"Scenario file: {scenario_file_path()}")


def cmd_portfolio_status(args: argparse.Namespace) -> None:
    from codextrader.daily_pipeline import get_portfolio_status

    status = get_portfolio_status(args.scenario, Path(args.portfolio_dir))
    print(f"Scenario: {status['scenario']}")
    print(f"Cash: {status['cash']:.2f}")
    print(f"Positions: {status['position_count']}")
    print(f"Tickers: {', '.join(status['positions']) if status['positions'] else 'none'}")
    print(f"Trades logged: {status['trade_count']}")
    print(f"Last updated: {status['last_updated'] or 'never'}")


def cmd_schedule(args: argparse.Namespace) -> None:
    config = make_scheduler_config(
        provider=args.provider,
        scenarios=args.scenarios,
        openai_model=args.openai_model,
        max_new_trades=args.max_new_trades,
        data_dir=Path(args.data_dir),
        output_root=Path(args.output_root),
        portfolio_dir=Path(args.portfolio_dir),
        schedule_time=args.time,
        timezone_name=args.timezone,
        log_dir=Path(args.log_dir),
        poll_seconds=args.poll_seconds,
    )
    if args.run_now:
        run_once(config)
    else:
        run_forever(config)


def main() -> None:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "generate-data":
        cmd_generate_data(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "build-brief":
        cmd_build_brief(args)
    elif args.command == "daily-run":
        cmd_daily_run(args)
    elif args.command == "scenarios":
        cmd_scenarios(args)
    elif args.command == "portfolio-status":
        cmd_portfolio_status(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
