"""Daily scheduler for end-of-day paper trading runs."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .artifacts import SchedulerRunResultArtifact, SchedulerStatusArtifact, read_json_file, write_json_file
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


def _write_status(log_dir: Path, payload: SchedulerStatusArtifact) -> None:
    write_json_file(_scheduler_status_path(log_dir), payload.to_dict())


def run_once(config: SchedulerConfig) -> None:
    logger = _setup_logger(config.log_dir)
    started_at = datetime.now(ZoneInfo(config.timezone_name)).isoformat()
    status = SchedulerStatusArtifact(
        state="running",
        started_at=started_at,
        provider=config.provider,
        scenarios=config.scenarios,
        schedule_time=config.schedule_time,
        timezone=config.timezone_name,
    )
    existing_status = _scheduler_status_path(config.log_dir)
    if existing_status.exists():
        previous = SchedulerStatusArtifact.from_dict(read_json_file(existing_status))
        status = SchedulerStatusArtifact(
            state=status.state,
            started_at=status.started_at,
            provider=status.provider,
            scenarios=status.scenarios,
            schedule_time=status.schedule_time,
            timezone=status.timezone,
            last_successful_run=previous.last_successful_run,
            last_failed_run=previous.last_failed_run,
            last_error=previous.last_error,
            last_results=previous.last_results,
        )
    _write_status(config.log_dir, status)

    results: list[SchedulerRunResultArtifact] = []
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
        result = SchedulerRunResultArtifact(
            scenario=scenario_name,
            market_as_of=brief.market.as_of,
            decisions=len(decisions),
            executed_trades=len(execution["executed_trades"]),
            execution_file=str(paths["execution"]),
            completed_at=datetime.now(ZoneInfo(config.timezone_name)).isoformat(),
        )
        results.append(result)
        logger.info(
            "[scheduler] completed scenario=%s market_as_of=%s decisions=%s executed=%s execution_file=%s",
            scenario_name,
            brief.market.as_of,
            len(decisions),
            len(execution["executed_trades"]),
            paths["execution"],
        )
    status = SchedulerStatusArtifact(
        state="idle",
        started_at=status.started_at,
        provider=status.provider,
        scenarios=status.scenarios,
        schedule_time=status.schedule_time,
        timezone=status.timezone,
        last_successful_run=datetime.now(ZoneInfo(config.timezone_name)).isoformat(),
        last_failed_run=status.last_failed_run,
        last_error=None,
        last_results=results,
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
        SchedulerStatusArtifact(
            state="idle",
            started_at=datetime.now(tz).isoformat(),
            provider=config.provider,
            scenarios=config.scenarios,
            schedule_time=config.schedule_time,
            timezone=config.timezone_name,
        ),
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
                current = (
                    SchedulerStatusArtifact.from_dict(read_json_file(status_path))
                    if status_path.exists()
                    else SchedulerStatusArtifact(
                        state="idle",
                        started_at=datetime.now(tz).isoformat(),
                        provider=config.provider,
                        scenarios=config.scenarios,
                        schedule_time=config.schedule_time,
                        timezone=config.timezone_name,
                    )
                )
                _write_status(
                    config.log_dir,
                    SchedulerStatusArtifact(
                        state="idle",
                        started_at=current.started_at,
                        provider=current.provider,
                        scenarios=current.scenarios,
                        schedule_time=current.schedule_time,
                        timezone=current.timezone,
                        last_successful_run=current.last_successful_run,
                        last_failed_run=datetime.now(tz).isoformat(),
                        last_error=str(exc),
                        last_results=current.last_results,
                    ),
                )
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
