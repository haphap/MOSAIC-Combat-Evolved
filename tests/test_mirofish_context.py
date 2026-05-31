"""Tests for Phase 7M Step 1: MiroFish context derivation + persistence.

``derive_context`` is pure stdlib (no numpy) so these run deps-light.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mosaic.mirofish.context import derive_context
from mosaic.scorecard.store import ScorecardStore


def _scn(t, csi, name="S", p=0.2):
    return {
        "scenario_type": t,
        "scenario_name": name,
        "probability": p,
        "final_state": {
            "regime": "RISK_OFF" if csi < -0.10 else ("RISK_ON" if csi > 0.10 else "NEUTRAL"),
            "narrative": "n",
            "csi300_return": csi,
        },
        "price_paths": {"000300.SH": {"cumulative_return": csi}},
    }


_SET = [
    _scn("base", 0.02, "Base", 0.5),
    _scn("bull", 0.18, "Bull", 0.2),
    _scn("bear", -0.12, "Bear", 0.2),
    _scn("tail_down", -0.35, "Crash", 0.05),
    _scn("tail_up", 0.30, "Melt-up", 0.05),
]


class TestDeriveContext(unittest.TestCase):
    def test_regime_and_csi_from_base(self):
        ctx = derive_context(_SET)
        self.assertEqual(ctx["regime"], "NEUTRAL")
        self.assertEqual(ctx["csi300_return"], 0.02)
        self.assertEqual(ctx["n_scenarios"], 5)

    def test_hct_is_largest_abs_move(self):
        # tail_down -0.35 has the largest |move| → SHORT
        ctx = derive_context(_SET)
        self.assertEqual(ctx["hct_direction"], "SHORT")
        self.assertEqual(ctx["hct_csi300_return"], -0.35)

    def test_tail_summary_from_tail_down(self):
        ctx = derive_context(_SET)
        self.assertIn("Crash", ctx["tail_summary"])
        self.assertIn("-35.0%", ctx["tail_summary"])

    def test_hct_long_when_upside_dominates(self):
        ctx = derive_context([_scn("base", 0.01), _scn("tail_up", 0.40)])
        self.assertEqual(ctx["hct_direction"], "LONG")

    def test_degrades_to_none_cleanly(self):
        # All-zero moves → no direction; no tail_down → no tail summary.
        # Locks the contract Step 2's formatter must handle.
        ctx = derive_context([_scn("base", 0.0), _scn("bull", 0.0)])
        self.assertIsNone(ctx["hct_direction"])
        self.assertIsNone(ctx["tail_summary"])


class TestContextStore(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.store = ScorecardStore(db_path=Path(self._td.name) / "s.db")

    def tearDown(self):
        self._td.cleanup()

    def test_save_then_get_latest(self):
        self.assertIsNone(self.store.get_latest_mirofish_context())
        ctx = derive_context(_SET)
        self.store.save_mirofish_context(date="2026-05-30", context=ctx)
        got = self.store.get_latest_mirofish_context()
        self.assertEqual(got["date"], "2026-05-30")
        self.assertEqual(got["regime"], "NEUTRAL")
        self.assertEqual(got["hct_direction"], "SHORT")
        # get returns the same shape save derived (+ date/created_at provenance).
        self.assertEqual(set(got), set(ctx) | {"date", "created_at"})
        self.assertNotIn("detail_json", got)
        self.assertEqual(got["hct_csi300_return"], ctx["hct_csi300_return"])

    def test_upsert_idempotent_and_latest_wins(self):
        self.store.save_mirofish_context(date="2026-05-29", context=derive_context(_SET))
        self.store.save_mirofish_context(
            date="2026-05-30", context=derive_context([_scn("base", 0.40)])
        )
        got = self.store.get_latest_mirofish_context()
        self.assertEqual(got["date"], "2026-05-30")  # newest by date
        # re-save same date → still one row for it
        self.store.save_mirofish_context(date="2026-05-30", context=derive_context(_SET))
        with self.store._connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM mirofish_context WHERE date='2026-05-30'"
            ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_as_of_date_bounds_lookup_no_lookahead(self):
        self.store.save_mirofish_context(date="2026-05-20", context=derive_context([_scn("base", -0.05)]))
        self.store.save_mirofish_context(date="2026-05-30", context=derive_context([_scn("base", 0.40)]))
        # A backtest replaying 2026-05-25 must NOT see the 2026-05-30 context.
        got = self.store.get_latest_mirofish_context(as_of_date="2026-05-25")
        self.assertEqual(got["date"], "2026-05-20")
        # No bound → newest wins.
        self.assertEqual(self.store.get_latest_mirofish_context()["date"], "2026-05-30")
        # as_of before any row → None.
        self.assertIsNone(self.store.get_latest_mirofish_context(as_of_date="2026-01-01"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
