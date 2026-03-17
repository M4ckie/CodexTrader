from __future__ import annotations

import unittest

from codextrader.models import DailyBrief, MarketSnapshot, TickerSnapshot
from codextrader.openai_strategy import (
    _build_brief_prompt,
    _extract_json_array,
    _normalize_brief_decisions,
    _normalize_signals,
)


def _brief() -> DailyBrief:
    return DailyBrief(
        generated_at="2026-03-16T21:00:00+00:00",
        market=MarketSnapshot(as_of="2026-03-16", indices={"SPY": 1.0}, regime_summary="Risk-on"),
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


class OpenAIStrategyRefactorTests(unittest.TestCase):
    def test_extract_json_array_handles_embedded_json(self) -> None:
        payload = _extract_json_array('analysis... [{"ticker":"AAPL","action":"BUY","confidence":0.9,"score":0.8,"reason":"trend"}] trailing')
        self.assertEqual(payload[0]["ticker"], "AAPL")

    def test_extract_json_array_rejects_missing_json(self) -> None:
        with self.assertRaises(ValueError):
            _extract_json_array("no array present here")

    def test_normalize_signals_filters_invalid_actions_and_clamps_confidence(self) -> None:
        signals = _normalize_signals(
            [
                {"ticker": "aapl", "action": "buy", "confidence": 1.4, "score": 0.8, "reason": "trend"},
                {"ticker": "msft", "action": "ignore", "confidence": 0.5, "score": 0.1, "reason": "bad"},
            ]
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].ticker, "AAPL")
        self.assertEqual(signals[0].confidence, 1.0)

    def test_normalize_brief_decisions_enforces_buy_cap(self) -> None:
        decisions = _normalize_brief_decisions(
            [
                {"ticker": "AAPL", "action": "BUY", "confidence": 0.9, "score": 0.8, "reason": "one"},
                {"ticker": "MSFT", "action": "BUY", "confidence": 0.8, "score": 0.7, "reason": "two"},
                {"ticker": "NVDA", "action": "SELL", "confidence": 0.7, "score": -0.6, "reason": "risk"},
            ],
            max_new_trades=1,
        )
        actions = {item.ticker: item.action for item in decisions}
        self.assertEqual(actions["AAPL"], "BUY")
        self.assertEqual(actions["MSFT"], "HOLD")
        self.assertEqual(actions["NVDA"], "SELL")

    def test_build_brief_prompt_contains_max_new_trades_and_brief_payload(self) -> None:
        prompt = _build_brief_prompt(_brief(), 2)
        self.assertIn('"max_new_trades":2', prompt)
        self.assertIn('"ticker":"AAPL"', prompt)
