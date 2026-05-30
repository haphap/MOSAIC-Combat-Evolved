"""Tests for mirofish.* JSON-RPC handlers (Plan §11.8 Phase 7)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mosaic.bridge.protocol import RpcError  # noqa: F401
from mosaic.scorecard.store import ScorecardStore

# Scenario generation/scoring need numpy (declared in the .[data] extra). In a
# deps-light env, skip those bodies rather than ERROR — mirrors the live-Tushare
# skipUnless pattern. Param-validation tests run regardless (validate-first).
_HAS_NUMPY = importlib.util.find_spec("numpy") is not None

# Prefer package import (registers @method once); fall back to isolated exec
# only when langchain is absent. See test_prism.py / test_bridge_janus.py.
try:
    from mosaic.bridge.handlers import mirofish as _mf
except Exception:
    _key = "mosaic.bridge.handlers.mirofish"
    if _key in sys.modules:
        _mf = sys.modules[_key]
    else:
        _HANDLER_PATH = (
            Path(__file__).resolve().parent.parent
            / "mosaic" / "bridge" / "handlers" / "mirofish.py"
        )
        _spec = importlib.util.spec_from_file_location(_key, str(_HANDLER_PATH))
        _mf = importlib.util.module_from_spec(_spec)
        sys.modules[_key] = _mf
        _spec.loader.exec_module(_mf)


class TestMirofishHandlers(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.store = ScorecardStore(db_path=Path(self._tmpdir.name) / "scorecard.db")
        self._patch = patch.object(_mf, "_store", return_value=self.store)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
    def test_generate_scenarios(self):
        out = _mf.mirofish_generate_scenarios({"seed": 42, "num_days": 30})
        self.assertEqual(len(out["scenarios"]), 5)
        self.assertEqual(out["scenarios"][0]["scenario_type"], "base")

    def test_generate_rejects_bad_scenarios_param(self):
        with self.assertRaises(RpcError):
            _mf.mirofish_generate_scenarios({"scenarios": "bull"})

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
    def test_generate_reflexivity_flag(self):
        plain = _mf.mirofish_generate_scenarios({"seed": 42, "scenarios": ["bull"]})["scenarios"][0]
        refl = _mf.mirofish_generate_scenarios({"seed": 42, "scenarios": ["bull"], "reflexivity": True})["scenarios"][0]
        self.assertFalse(plain["reflexive"])
        self.assertTrue(refl["reflexive"])
        # Reflexive feedback changes the path.
        self.assertNotEqual(
            plain["price_paths"]["000300.SH"]["prices"],
            refl["price_paths"]["000300.SH"]["prices"],
        )

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
    def test_score_recommendation(self):
        # Construct a known-positive path so the assertion doesn't depend on a
        # noisy single random scenario path.
        scenario = {
            "price_paths": {
                "000300.SH": {
                    "ticker": "000300.SH",
                    "start_price": 3500.0,
                    "prices": [3500.0, 3920.0],
                    "cumulative_return": 0.12,
                    "volatility": 0.2,
                }
            }
        }
        r = _mf.mirofish_score_recommendation({
            "recommendation": {"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.7},
            "scenario": scenario,
        })
        self.assertGreater(r["score"], 0.5)

    def test_score_requires_objects(self):
        with self.assertRaises(RpcError):
            _mf.mirofish_score_recommendation({"recommendation": "BUY", "scenario": {}})

    def test_record_and_history(self):
        rid = _mf.mirofish_record_run({
            "agent": "druckenmiller", "scenario_type": "all",
            "n_scenarios": 5, "avg_score": 0.62, "date": "2024-06-30",
        })["id"]
        self.assertIsInstance(rid, int)
        hist = _mf.mirofish_get_history({"days": 10})["history"]
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["agent"], "druckenmiller")
        self.assertAlmostEqual(hist[0]["avg_score"], 0.62)

    def test_record_rejects_missing_agent(self):
        with self.assertRaises(RpcError):
            _mf.mirofish_record_run({"scenario_type": "all"})

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
    def test_engine_defaults_to_montecarlo_off(self):
        # No engine param → config default (montecarlo); swarm is OFF.
        out = _mf.mirofish_generate_scenarios({"seed": 42, "scenarios": ["bull"]})
        self.assertEqual(out["engine"], "montecarlo")
        self.assertNotIn("emergence", out["scenarios"][0])

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
    def test_engine_swarm_opt_in(self):
        out = _mf.mirofish_generate_scenarios({"seed": 42, "scenarios": ["bull"], "engine": "swarm"})
        self.assertEqual(out["engine"], "swarm")
        self.assertEqual(out["scenarios"][0]["engine"], "swarm")
        self.assertIn("emergence", out["scenarios"][0])

    def test_bad_engine_rejected(self):
        # Validates before the numpy-backed import → runs deps-light.
        with self.assertRaises(RpcError):
            _mf.mirofish_generate_scenarios({"engine": "oasis"})

    def test_config_default_engine_is_off(self):
        from mosaic.default_config import DEFAULT_CONFIG

        self.assertEqual(DEFAULT_CONFIG["mirofish"]["engine"], "montecarlo")

    def test_methods_registered(self):
        from mosaic.bridge.registry import all_methods

        expected = {
            "mirofish.generate_scenarios",
            "mirofish.score_recommendation",
            "mirofish.record_run",
            "mirofish.get_history",
        }
        self.assertTrue(expected.issubset(set(all_methods())))


if __name__ == "__main__":
    unittest.main()
