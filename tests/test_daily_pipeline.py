from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codextrader.artifacts import ExecutionReportArtifact
from codextrader.daily_pipeline import DailyRunArtifacts, generate_daily_run_artifacts, persist_daily_run
from codextrader.models import DailyBrief, MarketSnapshot, PortfolioState, Signal, TickerSnapshot


def _brief() -> DailyBrief:
    return DailyBrief(
        generated_at="2026-03-16T21:00:00+00:00",
        market=MarketSnapshot(as_of="2026-03-16", indices={}, regime_summary="Mixed"),
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
        portfolio_context={"scenario": "balanced_100k"},
    )


class DailyPipelineRefactorTests(unittest.TestCase):
    def test_generate_daily_run_artifacts_uses_split_orchestration(self) -> None:
        portfolio = PortfolioState(
            scenario="balanced_100k",
            cash=100000.0,
            positions={},
            pending_orders=[],
            trade_log=[],
            equity_history=[],
            last_updated="",
        )
        brief = _brief()
        decisions = [Signal(ticker="AAPL", score=0.6, confidence=0.9, action="BUY", reason="trend")]
        execution = {
            "executed_trades": [],
            "placed_orders": [{"ticker": "AAPL", "action": "BUY", "shares": 10, "reason": "trend", "placed_at": "2026-03-16"}],
            "portfolio_context": {"equity_history": [], "review": {"summary": "ok"}},
        }
        with (
            patch("codextrader.daily_pipeline.load_portfolio", return_value=portfolio),
            patch("codextrader.daily_pipeline.collect_daily_brief", return_value=brief),
            patch("codextrader.daily_pipeline.decide_from_brief", return_value=decisions),
            patch("codextrader.daily_pipeline.execute_daily_decisions", return_value=execution),
        ):
            artifacts, returned_portfolio = generate_daily_run_artifacts(
                tickers=None,
                provider_name="local",
                data_dir=Path("data/market"),
                openai_model="gpt-4.1-mini",
                max_new_trades=None,
                scenario_name="balanced_100k",
                portfolio_dir=Path("output/portfolios"),
            )

        self.assertIs(returned_portfolio, portfolio)
        self.assertEqual(artifacts.brief, brief)
        self.assertEqual(artifacts.decisions, decisions)
        self.assertEqual(artifacts.execution_report.scenario, "balanced_100k")
        self.assertEqual(artifacts.execution_report.tickers, ["AAPL"])

    def test_persist_daily_run_writes_expected_files(self) -> None:
        portfolio = PortfolioState(
            scenario="balanced_100k",
            cash=100000.0,
            positions={},
            pending_orders=[],
            trade_log=[],
            equity_history=[],
            last_updated="2026-03-16",
        )
        brief = _brief()
        decisions = [Signal(ticker="AAPL", score=0.6, confidence=0.9, action="BUY", reason="trend")]
        execution = {
            "executed_trades": [],
            "placed_orders": [],
            "portfolio_context": {"equity_history": [], "review": {"summary": "ok"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "scheduled_runs" / "balanced_100k"
            portfolio_dir = Path(tmp) / "portfolios"
            run_artifacts = DailyRunArtifacts(
                brief=brief,
                decisions=decisions,
                execution=execution,
                execution_report=ExecutionReportArtifact.from_run_data(brief, decisions, execution, "balanced_100k"),
                review_report={"summary": "ok"},
            )

            persisted = persist_daily_run(run_artifacts, portfolio, output_dir, portfolio_dir)

            self.assertTrue((output_dir / "daily_brief.json").exists())
            self.assertTrue((output_dir / "daily_brief.md").exists())
            self.assertTrue((output_dir / "daily_decisions.json").exists())
            self.assertTrue((output_dir / "daily_execution.json").exists())
            self.assertTrue((output_dir / "daily_review.json").exists())
            self.assertTrue(persisted.portfolio_path.exists())
