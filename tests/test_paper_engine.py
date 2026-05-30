"""Tests for the ported PaperTradingEngine (Plan §4.1 / Phase 8 刀1).

Engine core: auth, account, buy/sell, T+1 lock, commission, positions/trades.
Price lookup is mocked so tests never touch the network. ``bcrypt`` (the
``.[trading]`` extra) is required; skip cleanly when absent.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HAS_BCRYPT = importlib.util.find_spec("bcrypt") is not None

if _HAS_BCRYPT:
    from mosaic.paper_trading.engine import PaperTradingEngine


@unittest.skipUnless(_HAS_BCRYPT, "bcrypt not installed (.[trading] extra)")
class TestPaperEngine(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        d = Path(self._td.name)
        self._sess = patch.object(PaperTradingEngine, "SESSION_PATH", d / "session.json")
        self._sess.start()
        self.db = d / "paper.db"
        # Deterministic price + name → no network.
        self._price = patch.object(PaperTradingEngine, "_get_current_price", return_value=10.0)
        self._name = patch.object(PaperTradingEngine, "_auto_fill_name", return_value="测试ETF")
        self._price.start()
        self._name.start()
        self.e = PaperTradingEngine(db_path=self.db)

    def tearDown(self):
        self._name.stop()
        self._price.stop()
        self._sess.stop()
        self._td.cleanup()

    def test_register_login_logout(self):
        self.e.register("alice", "pw")
        self.assertFalse(self.e.login("alice", "wrong"))
        self.assertTrue(self.e.login("alice", "pw"))
        self.assertEqual(self.e.current_user, "alice")
        self.assertEqual(self.e.logout(), "alice")
        self.assertEqual(self.e.current_user, "default")

    def test_register_rejects_default_and_dupes(self):
        with self.assertRaises(ValueError):
            self.e.register("default", "pw")
        self.e.register("bob", "pw")
        with self.assertRaises(ValueError):
            self.e.register("bob", "pw2")

    def test_buy_updates_cash_position_commission(self):
        self.e.register("alice", "pw")
        self.e.login("alice", "pw")
        self.e.reset_account(initial_cash=1_000_000.0)
        res = self.e.buy("510300.SH", 1000, user_id="alice")
        self.assertEqual(res["amount"], 10_000.0)
        self.assertEqual(res["commission"], 5.0)  # MIN_COMMISSION floor
        acct = self.e.get_account("alice")
        self.assertAlmostEqual(acct["cash"], 1_000_000.0 - 10_005.0)
        pos = self.e.get_positions("alice")
        self.assertEqual((pos[0]["ticker"], pos[0]["quantity"]), ("510300.SH", 1000))

    def test_t1_blocks_same_day_sell_then_unlocks(self):
        self.e.register("alice", "pw")
        self.e.login("alice", "pw")
        self.e.reset_account(initial_cash=1_000_000.0)
        self.e.buy("510300.SH", 1000, user_id="alice")
        with self.assertRaises(ValueError):
            self.e.sell("510300.SH", 1000, user_id="alice")  # available_qty == 0
        # Simulate a new trading day by clearing the unlock barrier.
        with self.e._connect() as conn:
            conn.execute("UPDATE account SET last_unlock_date = '2000-01-01' WHERE user_id='alice'")
        out = self.e.sell("510300.SH", 1000, user_id="alice")
        self.assertEqual(out["side"], "sell")
        self.assertEqual(self.e.get_positions("alice"), [])

    def test_validate_quantity_lot_size(self):
        self.e.register("alice", "pw")
        self.e.login("alice", "pw")
        with self.assertRaises(ValueError):
            self.e.buy("510300.SH", 150, user_id="alice")  # not a multiple of 100

    def test_suggest_order_is_stubbed_until_dao2(self):
        with self.assertRaises(NotImplementedError):
            self.e.suggest_order_from_signal("510300.SH", {}, user_id="default")

    def test_cross_user_access_is_blocked_for_reads_and_writes(self):
        """Both writes (buy) and reads (get_account/positions/trades) enforce
        the logged-in user: requesting another user's id raises PermissionError."""
        self.e.register("alice", "pw")
        self.e.register("mallory", "pw")
        self.e.login("alice", "pw")  # session = alice
        for op in (
            lambda: self.e.buy("510300.SH", 100, user_id="mallory"),
            lambda: self.e.get_account(user_id="mallory"),
            lambda: self.e.get_positions(user_id="mallory"),
            lambda: self.e.get_trades(user_id="mallory"),
        ):
            with self.assertRaises(PermissionError):
                op()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
