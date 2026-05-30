"""Tests for the 7M.2 memory prototype (Plan §11.8.1).

Locks (a) LocalAgentMemory's online-correlation correctness + determinism, and
(b) the two ROBUST measured findings — memory learns the swarm≫MC forward-signal
split online, and is correspondingly more selective under the swarm. The
*verdict* (selectivity yields no capture lift over a stateless heuristic) is a
magnitude claim documented in §11.8.1, not asserted as a brittle threshold here.
"""

from __future__ import annotations

import importlib.util
import unittest

_HAS_NUMPY = importlib.util.find_spec("numpy") is not None

if _HAS_NUMPY:
    from mosaic.mirofish.memory import LocalAgentMemory, measure_memory_lift


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
class TestLocalAgentMemory(unittest.TestCase):
    def test_learns_positive_correlation(self):
        m = LocalAgentMemory()
        for x in range(-10, 11):
            m.remember("ctx", float(x), float(x))  # perfectly correlated
        r, n = m.recall("ctx")
        self.assertAlmostEqual(r, 1.0, places=6)
        self.assertEqual(n, 21)

    def test_learns_negative_and_zero(self):
        m = LocalAgentMemory()
        for x in range(-10, 11):
            m.remember("neg", float(x), float(-x))
        self.assertAlmostEqual(m.recall("neg")[0], -1.0, places=6)
        # constant outcome → undefined variance → 0 (no spurious signal)
        m2 = LocalAgentMemory()
        for x in range(-10, 11):
            m2.remember("flat", float(x), 1.0)
        self.assertEqual(m2.recall("flat")[0], 0.0)

    def test_cold_recall_is_zero(self):
        self.assertEqual(LocalAgentMemory().recall("unknown"), (0.0, 0))


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
class TestMemoryLift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = measure_memory_lift(n_seeds=150, num_days=30)

    def test_deterministic(self):
        self.assertEqual(self.d, measure_memory_lift(n_seeds=150, num_days=30))

    def test_memory_learns_the_regime_split_online(self):
        """Online learned correlation recovers the A/B-lift split: swarm
        materially positive, Monte-Carlo ≈ 0."""
        mc = self.d["engines"]["montecarlo"]["mean_learned_corr"]
        sw = self.d["engines"]["swarm"]["mean_learned_corr"]
        self.assertLess(abs(mc), 0.05)
        self.assertGreater(sw, 0.06)
        self.assertGreater(sw - mc, 0.04)

    def test_memory_is_more_selective_under_swarm(self):
        """The point of memory: it acts where there's an edge (swarm) and holds
        back where there isn't (MC). Stateless always acts."""
        mc_act = self.d["engines"]["montecarlo"]["memory_activity"]
        sw_act = self.d["engines"]["swarm"]["memory_activity"]
        self.assertEqual(self.d["engines"]["swarm"]["stateless_activity"], 1.0)
        self.assertGreater(sw_act, mc_act)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
