"""Tests for janus.* JSON-RPC handlers (Plan §11.7 Phase 6)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mosaic.bridge.protocol import RpcError  # noqa: F401
from mosaic.scorecard.store import ScorecardStore

# Prefer the package import (registers @method once); fall back to isolated exec
# only when the package __init__ can't import (no langchain). See test_prism.py.
try:
    from mosaic.bridge.handlers import janus as _janus
except Exception:
    _key = "mosaic.bridge.handlers.janus"
    if _key in sys.modules:
        _janus = sys.modules[_key]
    else:
        _HANDLER_PATH = (
            Path(__file__).resolve().parent.parent
            / "mosaic" / "bridge" / "handlers" / "janus.py"
        )
        _spec = importlib.util.spec_from_file_location(_key, str(_HANDLER_PATH))
        _janus = importlib.util.module_from_spec(_spec)
        sys.modules[_key] = _janus
        _spec.loader.exec_module(_janus)


class TestJanusHandlers(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.store = ScorecardStore(db_path=Path(self._tmpdir.name) / "scorecard.db")
        self._patch = patch.object(_janus, "_store", return_value=self.store)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def _add_cio(self, cohort, ticker, date, action, twp):
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO recommendations (cohort, agent, ticker, date, action, "
                "conviction, target_weight_pct) VALUES (?,?,?,?,?,?,?)",
                (cohort, "cio", ticker, date, action, None, twp),
            )

    def test_get_weights_covers_7_cohorts(self):
        r = _janus.janus_get_weights({"date": "2021-02-18"})
        self.assertEqual(len(r["cohort_weights"]), 7)
        self.assertAlmostEqual(sum(r["cohort_weights"].values()), 1.0, places=3)

    def test_regime_returns_dominant(self):
        r = _janus.janus_regime({"date": "2021-02-18"})
        self.assertIn("dominant_cohort", r)
        self.assertIn("regime_label", r)

    def test_run_daily_persists_and_blends(self):
        self._add_cio("crisis_2008", "600519.SH", "2008-09-15", "BUY", 80)
        r = _janus.janus_run_daily({"date": "2008-09-15"})
        self.assertEqual(r["date"], "2008-09-15")
        self.assertEqual(len(r["blended_recommendations"]), 1)
        hist = _janus.janus_get_history({"days": 10})
        self.assertEqual(len(hist["history"]), 1)

    def test_invalid_window_rejected(self):
        with self.assertRaises(RpcError):
            _janus.janus_get_weights({"window_days": 0})

    def test_invalid_days_rejected(self):
        with self.assertRaises(RpcError):
            _janus.janus_get_history({"days": "nope"})

    def test_methods_registered(self):
        from mosaic.bridge.registry import all_methods

        expected = {"janus.run_daily", "janus.get_weights", "janus.regime", "janus.get_history"}
        self.assertTrue(expected.issubset(set(all_methods())))


if __name__ == "__main__":
    unittest.main()
