"""Daily scheduler for end-of-day paper trading runs."""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import default_scenario_name, get_scenarios
from .daily_pipeline import run_end_of_day_decision


@dataclass(frozen=True)
class SchedulerConfig:
    provider: str
    scenarios: list[str]
    openai_model: str
    max_new_trades: int | None
    data_dir: Path
    output_root: Path
    portfolio_dir: Path
    schedule_time: str
    timezone_name: str
    poll_seconds: int = 30


def _scenario_list(raw: list[str] | None) -> list[str]:
    if raw:
        return raw
    scenarios = get_scenarios()
    return [default_scenario_name()] if scenarios else []


def run_once(config: SchedulerConfig) -> None:
    for scenario_name in config.scenarios:
        output_dir = config.output_root / scenario_name
        print(f"[scheduler] running scenario={scenario_name} provider={config.provider}")
        brief, decisions, paths, execution = run_end_of_day_decision(
            tickers=None,
            provider_name=config.provider,
            data_dir=config.data_dir,
            output_dir=output_dir,
            openai_model=config.openai_model,
            max_new_trades=config.max_new_trades,
            scenario_name=scenario_name,
            portfolio_dir=config.portfolio_dir,
        )
        print(
            f"[scheduler] completed scenario={scenario_name} "
            f"market_as_of={brief.market.as_of} decisions={len(decisions)} "
            f"executed={len(execution['executed_trades'])} execution_file={paths['execution']}"
        )


def run_forever(config: SchedulerConfig) -> None:
    tz = ZoneInfo(config.timezone_name)
    last_run_date = ""
    hour, minute = [int(part) for part in config.schedule_time.split(":", 1)]

    print(
        f"[scheduler] started timezone={config.timezone_name} "
        f"time={config.schedule_time} scenarios={','.join(config.scenarios)} provider={config.provider}"
    )

    while True:
        now = datetime.now(tz)
        today = now.date().isoformat()
        should_run = now.hour > hour or (now.hour == hour and now.minute >= minute)
        if should_run and today != last_run_date:
            try:
                run_once(config)
                last_run_date = today
            except Exception as exc:  # pragma: no cover - operational path
                print(f"[scheduler] run failed: {exc}")
                traceback.print_exc()
                last_run_date = today
        time.sleep(config.poll_seconds)


def make_scheduler_config(
    provider: str,
    scenarios: list[str] | None,
    openai_model: str,
    max_new_trades: int | None,
    data_dir: Path,
    output_root: Path,
    portfolio_dir: Path,
    schedule_time: str,
    timezone_name: str,
    poll_seconds: int = 30,
) -> SchedulerConfig:
    return SchedulerConfig(
        provider=provider,
        scenarios=_scenario_list(scenarios),
        openai_model=openai_model,
        max_new_trades=max_new_trades,
        data_dir=data_dir,
        output_root=output_root,
        portfolio_dir=portfolio_dir,
        schedule_time=schedule_time,
        timezone_name=timezone_name,
        poll_seconds=poll_seconds,
    )
