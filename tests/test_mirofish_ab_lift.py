"""A/B-lift gate tests (Plan §11.8.1) — locks the measured findings as a
regression guard. Asserts the robust *direction* of each finding (which holds
across sample sizes), not fragile point magnitudes.
"""

from __future__ import annotations

import importlib.util
import unittest

_HAS_NUMPY = importlib.util.find_spec("numpy") is not None

if _HAS_NUMPY:
    from mosaic.mirofish.ab_lift import measure_lift


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed (.[data] extra)")
class TestAbLift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = measure_lift(n_seeds=150, num_days=30)

    def test_deterministic(self):
        self.assertEqual(self.d, measure_lift(n_seeds=150, num_days=30))

    def test_swarm_has_exploitable_forward_signal_montecarlo_lacks(self):
        """The decisive lift result: drift-demeaned early→post-window return
        correlation is materially positive under the swarm (exploitable by a
        memory model) and ≈ 0 under i.i.d. Monte-Carlo."""
        mc = self.d["forward_signal"]["montecarlo"]["early_vs_forward_corr"]
        sw = self.d["forward_signal"]["swarm"]["early_vs_forward_corr"]
        self.assertLess(abs(mc), 0.08)      # MC: no continuation once drift removed
        self.assertGreater(sw, 0.05)        # swarm: positive forward signal
        self.assertGreater(sw - mc, 0.04)   # and a clear gap

    def test_swarm_compresses_discrimination(self):
        """Honest counter-finding: the swarm's price-impact damping COMPRESSES
        terminal-score spread between good and bad policies vs Monte-Carlo — so
        today's scorer turns the forward signal into a *flatter* training
        gradient, not a sharper one."""
        mc = self.d["regimes"]["montecarlo+terminal"]["discrimination"]
        sw = self.d["regimes"]["swarm+terminal"]["discrimination"]
        self.assertLess(sw, mc)

    def test_swarm_path_aware_reorders_policies(self):
        """Only swarm+path_aware reorders the policy ranking vs the
        montecarlo+terminal baseline (rank corr < 1) — i.e. the regime grades
        agents differently; the other regimes preserve the baseline order."""
        self.assertEqual(self.d["regimes"]["montecarlo+path_aware"]["rank_corr_vs_baseline"], 1.0)
        self.assertEqual(self.d["regimes"]["swarm+terminal"]["rank_corr_vs_baseline"], 1.0)
        self.assertLess(self.d["regimes"]["swarm+path_aware"]["rank_corr_vs_baseline"], 1.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
