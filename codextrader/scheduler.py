"""Daily scheduler for end-of-day paper trading runs."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
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
    log_dir: Path
    poll_seconds: int = 30


def _scenario_list(raw: list[str] | None) -> list[str]:
    if raw:
        return raw
    scenarios = get_scenarios()
    if scenarios:
        return list(scenarios.keys())
    return [default_scenario_name()] if default_scenario_name() else []


def _scheduler_status_path(log_dir: Path) -> Path:
    return log_dir / "scheduler_status.json"


def _setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("codextrader.scheduler")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(log_dir / "scheduler.log", maxBytes=500_000, backupCount=3)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def _write_status(log_dir: Path, payload: dict) -> None:
    path = _scheduler_status_path(log_dir)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_once(config: SchedulerConfig) -> None:
    logger = _setup_logger(config.log_dir)
    started_at = datetime.now(ZoneInfo(config.timezone_name)).isoformat()
    status = {
        "state": "running",
        "started_at": started_at,
        "provider": config.provider,
        "scenarios": config.scenarios,
        "schedule_time": config.schedule_time,
        "timezone": config.timezone_name,
        "last_successful_run": None,
        "last_failed_run": None,
        "last_error": None,
        "last_results": [],
    }
    existing_status = _scheduler_status_path(config.log_dir)
    if existing_status.exists():
        previous = json.loads(existing_status.read_text(encoding="utf-8"))
        status["last_successful_run"] = previous.get("last_successful_run")
        status["last_failed_run"] = previous.get("last_failed_run")
        status["last_error"] = previous.get("last_error")
        status["last_results"] = previous.get("last_results", [])
    _write_status(config.log_dir, status)

    results = []
    for scenario_name in config.scenarios:
        output_dir = config.output_root / scenario_name
        logger.info("[scheduler] running scenario=%s provider=%s", scenario_name, config.provider)
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
        result = {
            "scenario": scenario_name,
            "market_as_of": brief.market.as_of,
            "decisions": len(decisions),
            "executed_trades": len(execution["executed_trades"]),
            "execution_file": str(paths["execution"]),
            "completed_at": datetime.now(ZoneInfo(config.timezone_name)).isoformat(),
        }
        results.append(result)
        logger.info(
            "[scheduler] completed scenario=%s market_as_of=%s decisions=%s executed=%s execution_file=%s",
            scenario_name,
            brief.market.as_of,
            len(decisions),
            len(execution["executed_trades"]),
            paths["execution"],
        )
    status.update(
        {
            "state": "idle",
            "last_successful_run": datetime.now(ZoneInfo(config.timezone_name)).isoformat(),
            "last_error": None,
            "last_results": results,
        }
    )
    _write_status(config.log_dir, status)


def run_forever(config: SchedulerConfig) -> None:
    logger = _setup_logger(config.log_dir)
    tz = ZoneInfo(config.timezone_name)
    last_run_date = ""
    hour, minute = [int(part) for part in config.schedule_time.split(":", 1)]

    logger.info(
        "[scheduler] started timezone=%s time=%s scenarios=%s provider=%s",
        config.timezone_name,
        config.schedule_time,
        ",".join(config.scenarios),
        config.provider,
    )
    _write_status(
        config.log_dir,
        {
            "state": "idle",
            "started_at": datetime.now(tz).isoformat(),
            "provider": config.provider,
            "scenarios": config.scenarios,
            "schedule_time": config.schedule_time,
            "timezone": config.timezone_name,
            "last_successful_run": None,
            "last_failed_run": None,
            "last_error": None,
            "last_results": [],
        },
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
                logger.error("[scheduler] run failed: %s", exc)
                traceback.print_exc()
                status_path = _scheduler_status_path(config.log_dir)
                current = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
                current.update(
                    {
                        "state": "idle",
                        "last_failed_run": datetime.now(tz).isoformat(),
                        "last_error": str(exc),
                    }
                )
                _write_status(config.log_dir, current)
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
    log_dir: Path,
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
        log_dir=log_dir,
        poll_seconds=poll_seconds,
    )
