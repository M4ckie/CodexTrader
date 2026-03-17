from __future__ import annotations

import unittest

from codextrader.providers import _build_price_snapshot


class ProviderHelperTests(unittest.TestCase):
    def test_build_price_snapshot_computes_shared_metrics(self) -> None:
        closes = [float(value) for value in range(100, 160)]
        volumes = [1_000_000 + (value * 1000) for value in range(60)]

        snapshot = _build_price_snapshot(
            ticker="AAPL",
            as_of="2026-03-16",
            open_price=158.0,
            high_price=161.0,
            low_price=157.0,
            closes=closes,
            volumes=volumes,
            market_cap=3_000_000_000_000.0,
            sector="Technology",
        )

        self.assertEqual(snapshot.ticker, "AAPL")
        self.assertEqual(snapshot.close, 159.0)
        self.assertGreater(snapshot.sma_20, snapshot.sma_50)
        self.assertGreater(snapshot.avg_dollar_volume_20, 0)
        self.assertGreater(snapshot.relative_volume, 0)
