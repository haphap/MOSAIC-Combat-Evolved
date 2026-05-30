"""Tests for the opt-in path-aware MiroFish scorer (Plan §11.8.1, 7M.2 prereq).

Terminal scoring (default) collapses each path to its cumulative return, blind
to drawdown / path shape. Path-aware scoring grades the direction-adjusted
equity curve with a max-drawdown penalty. These tests lock:
  1. terminal (default) is byte-identical to the pre-existing scorer;
  2. path-aware discriminates a drawdown round-trip from a smooth climb of the
     SAME terminal return;
  3. on real swarm output, path-aware rankings diverge from terminal — i.e. the
     swarm's reflexive path structure now reaches the training signal.
"""

from __future__ import annotations

import importlib.util
import unittest

_HAS_NUMPY = importlib.util.find_spec("numpy") is not None

if _HAS_NUMPY:
    from mosaic.mirofish import score_recommendation
    from mosaic.mirofish.swarm import LocalSwarmEngine

_BUY = {"recommendation": "BUY", "tickers": ["X"], "conviction": 0.5}


def _scn(prices, cum):
    return {"price_paths": {"X": {"ticker": "X", "prices": prices, "cumulative_return": cum}}}


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
class TestPathAwareScorer(unittest.TestCase):
    def test_terminal_default_unchanged(self):
        """Default path_aware=False must equal explicit terminal scoring."""
        scn = _scn([100, 75, 90, 110], 0.10)
        self.assertEqual(
            score_recommendation(_BUY, scn),
            score_recommendation(_BUY, scn, path_aware=False),
        )

    def test_smooth_two_point_path_matches_terminal(self):
        """A monotone long path has no drawdown → path-aware == terminal."""
        scn = _scn([100, 112], 0.12)
        self.assertAlmostEqual(
            score_recommendation(_BUY, scn),
            score_recommendation(_BUY, scn, path_aware=True),
            places=6,
        )

    def test_path_aware_penalises_drawdown_roundtrip(self):
        """Same +10% terminal, but the round-trip through -25% scores lower."""
        smooth = _scn([100, 103, 106, 110], 0.10)
        roundtrip = _scn([100, 75, 90, 110], 0.10)
        # Terminal is blind to the difference.
        self.assertEqual(score_recommendation(_BUY, smooth), score_recommendation(_BUY, roundtrip))
        # Path-aware is not.
        s_pa = score_recommendation(_BUY, smooth, path_aware=True)
        r_pa = score_recommendation(_BUY, roundtrip, path_aware=True)
        # smooth climb: no drawdown → path-aware ≈ terminal (float epsilon aside)
        self.assertAlmostEqual(s_pa, score_recommendation(_BUY, smooth), places=6)
        self.assertLess(r_pa, s_pa)

    def test_hold_no_conviction_change_under_path_aware(self):
        """HOLD (sign 0) → path-aware is a no-op, equals terminal scoring."""
        hold = {"recommendation": "HOLD", "tickers": ["X"], "conviction": 0.5}
        scn = _scn([100, 75, 110], 0.10)
        self.assertEqual(
            score_recommendation(hold, scn, path_aware=True),
            score_recommendation(hold, scn),
        )

    def test_path_aware_diverges_from_terminal_on_swarm(self):
        """On real swarm scenarios, path-aware ranks differently than terminal
        for at least one scenario — proof the path structure reaches the signal
        (otherwise 7M.2 memory would be unexploitable)."""
        rec = {"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.5}
        eng = LocalSwarmEngine()
        scns = eng.generate_all_scenarios(num_days=30, seed=7)
        diverged = False
        for s in scns:
            t = score_recommendation(rec, s)
            p = score_recommendation(rec, s, path_aware=True)
            if abs(t - p) > 1e-6:
                diverged = True
                break
        self.assertTrue(diverged)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
