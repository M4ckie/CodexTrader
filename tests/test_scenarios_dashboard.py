from __future__ import annotations

import unittest

from codextrader.app_meta import DASHBOARD_PAGES
from codextrader.config import get_scenarios


class ScenarioDashboardTests(unittest.TestCase):
    def test_discovery_scenario_is_available(self) -> None:
        scenarios = get_scenarios()
        self.assertIn("discovery_100k", scenarios)
        discovery = scenarios["discovery_100k"]
        self.assertLess(discovery.universe.min_market_cap, scenarios["aggressive_100k"].universe.min_market_cap)
        self.assertGreater(discovery.universe.max_universe_size, scenarios["aggressive_100k"].universe.max_universe_size)

    def test_dashboard_includes_scenario_compare_page(self) -> None:
        self.assertIn("Scenario Compare", DASHBOARD_PAGES)
