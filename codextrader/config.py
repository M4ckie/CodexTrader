"""Scenario and strategy configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotConfig:
    initial_cash: float = 100_000.0
    max_positions: int = 4
    position_size_pct: float = 0.24
    buy_threshold: float = 0.55
    sell_threshold: float = -0.20
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.18
    slippage_pct: float = 0.001
    commission: float = 1.0
    confidence_scale: float = 1.6


@dataclass(frozen=True)
class UniverseConfig:
    market_scope: str = "us_equities"
    min_price: float = 10.0
    min_market_cap: float = 2_000_000_000.0
    min_avg_dollar_volume: float = 20_000_000.0
    include_etfs: bool = False
    max_universe_size: int = 60
    max_brief_candidates: int = 12


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    description: str
    bot: BotConfig
    universe: UniverseConfig
    max_new_trades: int
    avoid_earnings_within_days: int


DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "AMD", "META", "TSLA", "AMZN", "GOOGL"]
SCENARIO_FILE = Path("config/scenarios.json")


def _default_scenarios_payload() -> dict:
    return {
        "default_scenario": "balanced_100k",
        "scenarios": {
            "balanced_100k": {
                "description": "Default medium-risk end-of-day profile for a $100,000 account.",
                "bot": {
                    "initial_cash": 100_000.0,
                    "max_positions": 4,
                    "position_size_pct": 0.20,
                    "buy_threshold": 0.55,
                    "sell_threshold": -0.20,
                    "stop_loss_pct": 0.08,
                    "take_profit_pct": 0.18,
                    "slippage_pct": 0.001,
                    "commission": 1.0,
                    "confidence_scale": 1.6,
                },
                "universe": {
                    "market_scope": "us_equities",
                    "min_price": 10.0,
                    "min_market_cap": 2_000_000_000.0,
                    "min_avg_dollar_volume": 20_000_000.0,
                    "include_etfs": False,
                    "max_universe_size": 60,
                    "max_brief_candidates": 12,
                },
                "max_new_trades": 3,
                "avoid_earnings_within_days": 3,
            },
            "small_1000": {
                "description": "Smaller $1,000 account with tighter position count and more concentrated sizing.",
                "bot": {
                    "initial_cash": 1_000.0,
                    "max_positions": 3,
                    "position_size_pct": 0.30,
                    "buy_threshold": 0.52,
                    "sell_threshold": -0.18,
                    "stop_loss_pct": 0.10,
                    "take_profit_pct": 0.22,
                    "slippage_pct": 0.001,
                    "commission": 1.0,
                    "confidence_scale": 1.6,
                },
                "universe": {
                    "market_scope": "us_equities",
                    "min_price": 5.0,
                    "min_market_cap": 500_000_000.0,
                    "min_avg_dollar_volume": 10_000_000.0,
                    "include_etfs": False,
                    "max_universe_size": 80,
                    "max_brief_candidates": 10,
                },
                "max_new_trades": 2,
                "avoid_earnings_within_days": 1,
            },
            "conservative_100k": {
                "description": "Lower turnover and tighter risk controls for a larger account.",
                "bot": {
                    "initial_cash": 100_000.0,
                    "max_positions": 3,
                    "position_size_pct": 0.15,
                    "buy_threshold": 0.62,
                    "sell_threshold": -0.15,
                    "stop_loss_pct": 0.06,
                    "take_profit_pct": 0.14,
                    "slippage_pct": 0.001,
                    "commission": 1.0,
                    "confidence_scale": 1.6,
                },
                "universe": {
                    "market_scope": "us_equities",
                    "min_price": 15.0,
                    "min_market_cap": 10_000_000_000.0,
                    "min_avg_dollar_volume": 50_000_000.0,
                    "include_etfs": False,
                    "max_universe_size": 40,
                    "max_brief_candidates": 10,
                },
                "max_new_trades": 2,
                "avoid_earnings_within_days": 5,
            },
            "aggressive_100k": {
                "description": "Higher turnover and wider risk budget for a larger account.",
                "bot": {
                    "initial_cash": 100_000.0,
                    "max_positions": 6,
                    "position_size_pct": 0.24,
                    "buy_threshold": 0.48,
                    "sell_threshold": -0.25,
                    "stop_loss_pct": 0.10,
                    "take_profit_pct": 0.24,
                    "slippage_pct": 0.001,
                    "commission": 1.0,
                    "confidence_scale": 1.6,
                },
                "universe": {
                    "market_scope": "us_equities",
                    "min_price": 5.0,
                    "min_market_cap": 500_000_000.0,
                    "min_avg_dollar_volume": 10_000_000.0,
                    "include_etfs": False,
                    "max_universe_size": 80,
                    "max_brief_candidates": 15,
                },
                "max_new_trades": 4,
                "avoid_earnings_within_days": 1,
            },
        },
    }


def ensure_scenario_file() -> Path:
    if not SCENARIO_FILE.exists():
        SCENARIO_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCENARIO_FILE.write_text(json.dumps(_default_scenarios_payload(), indent=2), encoding="utf-8")
    return SCENARIO_FILE


def _scenario_from_payload(name: str, payload: dict) -> ScenarioConfig:
    return ScenarioConfig(
        name=name,
        description=payload["description"],
        bot=BotConfig(**payload["bot"]),
        universe=UniverseConfig(**payload["universe"]),
        max_new_trades=int(payload["max_new_trades"]),
        avoid_earnings_within_days=int(payload["avoid_earnings_within_days"]),
    )


def load_scenarios() -> tuple[str, dict[str, ScenarioConfig]]:
    path = ensure_scenario_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = {
        name: _scenario_from_payload(name, scenario_payload)
        for name, scenario_payload in payload.get("scenarios", {}).items()
    }
    default_name = payload.get("default_scenario") or next(iter(scenarios))
    if default_name not in scenarios:
        default_name = next(iter(scenarios))
    return default_name, scenarios


def scenario_names() -> list[str]:
    _, scenarios = load_scenarios()
    return sorted(scenarios.keys())


def default_scenario_name() -> str:
    default_name, _ = load_scenarios()
    return default_name


def get_scenarios() -> dict[str, ScenarioConfig]:
    _, scenarios = load_scenarios()
    return scenarios


def get_scenario(name: str) -> ScenarioConfig:
    default_name, scenarios = load_scenarios()
    return scenarios.get(name, scenarios[default_name])


def scenario_file_path() -> Path:
    return ensure_scenario_file()


def scenario_payload_for_display() -> dict:
    ensure_scenario_file()
    return json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))


def scenario_to_dict(scenario: ScenarioConfig) -> dict:
    return {
        "name": scenario.name,
        "description": scenario.description,
        "bot": asdict(scenario.bot),
        "universe": asdict(scenario.universe),
        "max_new_trades": scenario.max_new_trades,
        "avoid_earnings_within_days": scenario.avoid_earnings_within_days,
    }
