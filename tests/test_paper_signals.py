"""Tests for the slim backtest signal builder (Plan §4.1 / Phase 8 刀2)."""

from __future__ import annotations

import unittest

from mosaic.backtest.signals import BacktestSignal, build_state_backtest_signal


class TestBuildStateSignal(unittest.TestCase):
    def test_returns_attached_signal_dict_verbatim(self):
        sig = {"ticker": "510300.SH", "decision_date": "d", "source": "agent",
               "source_section": "x", "rating": "BUY", "target_weight_pct": 30.0}
        out = build_state_backtest_signal({"backtest_signal": sig})
        self.assertEqual(out, sig)
        # round-trips through the dataclass (suggest_order does BacktestSignal(**dict))
        self.assertEqual(BacktestSignal(**out).target_weight_pct, 30.0)

    def test_prefers_backtest_over_portfolio_over_trader(self):
        out = build_state_backtest_signal({
            "backtest_signal": {"ticker": "A", "decision_date": "", "source": "", "source_section": "", "rating": "BUY"},
            "portfolio_backtest_signal": {"ticker": "B", "decision_date": "", "source": "", "source_section": "", "rating": "SELL"},
        })
        self.assertEqual(out["ticker"], "A")

    def test_rating_only_fallback_uses_default_weight(self):
        out = build_state_backtest_signal({
            "asset_of_interest": "510300.SH",
            "final_allocation_decision": "我们建议买入 (BUY)",
            "trade_date": "2026-05-30",
        })
        self.assertEqual(out["ticker"], "510300.SH")
        self.assertEqual(out["rating"], "BUY")
        self.assertEqual(out["target_weight_pct"], 35.0)  # _DEFAULT_TARGET_WEIGHT_PCT[BUY]
        self.assertEqual(out["source"], "state_fallback")

    def test_empty_state_defaults_to_hold(self):
        out = build_state_backtest_signal({})
        self.assertEqual(out["rating"], "HOLD")
        self.assertEqual(out["target_weight_pct"], 15.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
