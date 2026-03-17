from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codextrader.artifact_repository import ArtifactRepository
from codextrader.artifacts import (
    EquityPointArtifact,
    ExecutionReportArtifact,
    PendingOrderArtifact,
    PortfolioArtifact,
    SchedulerRunResultArtifact,
    SchedulerStatusArtifact,
    TradeArtifact,
    write_json_file,
)
from codextrader.models import DailyBrief, MarketSnapshot, PortfolioState, Signal, TickerSnapshot


def _sample_brief() -> DailyBrief:
    return DailyBrief(
        generated_at="2026-03-16T21:00:00+00:00",
        market=MarketSnapshot(as_of="2026-03-16", indices={"SPY": 1.2}, regime_summary="Risk-on"),
        tickers=[
            TickerSnapshot(
                ticker="AAPL",
                as_of="2026-03-16",
                open=100.0,
                high=105.0,
                low=99.0,
                close=104.0,
                day_change_pct=1.0,
                week_change_pct=2.0,
                month_change_pct=3.0,
                sma_20=98.0,
                sma_50=95.0,
                volatility_20_pct=2.5,
                avg_volume_20=1_000_000,
                avg_dollar_volume_20=104_000_000,
                latest_volume=1_200_000,
                relative_volume=1.2,
            )
        ],
        portfolio_context={"scenario": "balanced_100k", "cash": 100000.0},
    )


class ArtifactRoundTripTests(unittest.TestCase):
    def test_portfolio_artifact_round_trip(self) -> None:
        portfolio = PortfolioState(
            scenario="balanced_100k",
            cash=99000.0,
            positions={"AAPL": {"shares": 10, "entry_price": 100.0, "entry_date": "2026-03-16", "reason": "trend"}},
            pending_orders=[{"ticker": "MSFT", "action": "BUY", "shares": 3, "reason": "setup", "placed_at": "2026-03-16"}],
            trade_log=[{"date": "2026-03-16", "ticker": "AAPL", "action": "BUY", "shares": 10, "price": 100.0, "cash_after": 99000.0}],
            equity_history=[{"date": "2026-03-16", "equity": 100500.0, "cash": 99000.0, "invested": 1500.0, "position_count": 1}],
            last_updated="2026-03-16",
        )
        artifact = PortfolioArtifact.from_portfolio_state(portfolio)

        restored = PortfolioArtifact.from_dict(artifact.to_dict()).to_portfolio_state()

        self.assertEqual(restored.scenario, portfolio.scenario)
        self.assertEqual(restored.positions, portfolio.positions)
        self.assertEqual(restored.pending_orders, portfolio.pending_orders)
        self.assertEqual(restored.trade_log[0]["ticker"], "AAPL")
        self.assertEqual(restored.trade_log[0]["pnl"], 0.0)
        self.assertEqual(restored.trade_log[0]["reason"], "")
        self.assertEqual(restored.equity_history, portfolio.equity_history)

    def test_execution_and_scheduler_artifacts_round_trip(self) -> None:
        brief = _sample_brief()
        decisions = [Signal(ticker="AAPL", score=0.7, confidence=0.8, action="BUY", reason="trend")]
        execution = {
            "executed_trades": [{"date": "2026-03-16", "ticker": "AAPL", "action": "BUY", "shares": 10, "price": 100.0, "cash_after": 99000.0}],
            "placed_orders": [{"ticker": "AAPL", "action": "BUY", "shares": 10, "reason": "trend", "placed_at": "2026-03-16"}],
            "portfolio_context": {
                "equity_history": [{"date": "2026-03-16", "equity": 100500.0, "cash": 99000.0, "invested": 1500.0, "position_count": 1}],
                "memory": {"win_rate": 0.5},
            },
        }

        report = ExecutionReportArtifact.from_run_data(brief, decisions, execution, "balanced_100k")
        restored_report = ExecutionReportArtifact.from_dict(report.to_dict())
        self.assertEqual(restored_report.scenario, "balanced_100k")
        self.assertEqual(restored_report.tickers, ["AAPL"])
        self.assertEqual(len(restored_report.executed_trades), 1)

        status = SchedulerStatusArtifact(
            state="idle",
            started_at="2026-03-16T21:00:00-04:00",
            provider="local",
            scenarios=["balanced_100k"],
            schedule_time="16:35",
            timezone="America/New_York",
            last_successful_run="2026-03-16T21:10:00-04:00",
            last_results=[
                SchedulerRunResultArtifact(
                    scenario="balanced_100k",
                    market_as_of="2026-03-16",
                    decisions=3,
                    executed_trades=1,
                    execution_file="output/scheduled_runs/balanced_100k/daily_execution.json",
                    completed_at="2026-03-16T21:10:00-04:00",
                )
            ],
        )
        restored_status = SchedulerStatusArtifact.from_dict(status.to_dict())
        self.assertEqual(restored_status.scenarios, ["balanced_100k"])
        self.assertEqual(restored_status.last_results[0].decisions, 3)


class ArtifactRepositoryTests(unittest.TestCase):
    def test_repository_loads_latest_execution_history_and_scheduler_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            old_dir = output_dir / "scheduled_runs" / "balanced_100k"
            new_dir = output_dir / "scheduled_runs" / "small_1000"
            old_dir.mkdir(parents=True)
            new_dir.mkdir(parents=True)

            old_report = ExecutionReportArtifact(
                scenario="balanced_100k",
                generated_at="2026-03-15T21:00:00+00:00",
                market_as_of="2026-03-15",
                brief_portfolio_context={},
                portfolio_context={},
                decisions=[],
                executed_trades=[],
                placed_orders=[],
                equity_history=[],
                tickers=["AAPL"],
            )
            new_report = ExecutionReportArtifact(
                scenario="balanced_100k",
                generated_at="2026-03-16T21:00:00+00:00",
                market_as_of="2026-03-16",
                brief_portfolio_context={},
                portfolio_context={},
                decisions=[],
                executed_trades=[],
                placed_orders=[],
                equity_history=[],
                tickers=["MSFT"],
            )
            write_json_file(old_dir / "daily_execution.json", old_report.to_dict())
            write_json_file(new_dir / "daily_execution.json", new_report.to_dict())
            write_json_file(output_dir / "scheduler" / "scheduler_status.json", SchedulerStatusArtifact(
                state="idle",
                started_at="2026-03-16T21:00:00-04:00",
                provider="local",
                scenarios=["balanced_100k", "small_1000"],
                schedule_time="16:35",
                timezone="America/New_York",
            ).to_dict())

            repo = ArtifactRepository(output_dir)
            latest, _ = repo.find_latest_execution("balanced_100k")
            history = repo.load_execution_history("balanced_100k")
            status = repo.load_scheduler_status()

            self.assertIsNotNone(latest)
            self.assertEqual(latest.market_as_of, "2026-03-16")
            self.assertEqual(len(history), 2)
            self.assertIsNotNone(status)
            self.assertEqual(status.scenarios, ["balanced_100k", "small_1000"])
