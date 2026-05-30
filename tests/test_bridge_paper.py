"""Tests for the ``paper.*`` JSON-RPC handlers (Plan Phase 8 刀1).

Param-validation runs dep-free (validate-first). Engine-routing tests need
``bcrypt`` (the ``.[trading]`` extra) and skip cleanly when absent.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mosaic.bridge.protocol import RpcError

# Prefer package import (registers @method once); fall back to isolated exec
# only when langchain is absent so param-validation tests still run dep-free.
# See test_bridge_mirofish.py / test_prism.py.
try:
    from mosaic.bridge.handlers import paper as ph
except Exception:
    _key = "mosaic.bridge.handlers.paper"
    if _key in sys.modules:
        ph = sys.modules[_key]
    else:
        _HANDLER_PATH = (
            Path(__file__).resolve().parent.parent
            / "mosaic" / "bridge" / "handlers" / "paper.py"
        )
        _spec = importlib.util.spec_from_file_location(_key, str(_HANDLER_PATH))
        ph = importlib.util.module_from_spec(_spec)
        sys.modules[_key] = ph
        _spec.loader.exec_module(ph)

_HAS_BCRYPT = importlib.util.find_spec("bcrypt") is not None


class TestPaperParamValidation(unittest.TestCase):
    """Run without bcrypt: bad params are rejected before the engine import."""

    def test_register_requires_strings(self):
        with self.assertRaises(RpcError):
            ph.paper_register({"username": "", "password": "pw"})
        with self.assertRaises(RpcError):
            ph.paper_register({"username": "a", "password": 123})

    def test_buy_requires_int_quantity(self):
        with self.assertRaises(RpcError):
            ph.paper_buy({"ticker": "510300.SH", "quantity": "100"})
        with self.assertRaises(RpcError):
            ph.paper_buy({"ticker": "510300.SH", "quantity": True})  # bool ≠ int

    def test_reset_requires_numeric_cash(self):
        with self.assertRaises(RpcError):
            ph.paper_reset_account({"initial_cash": "lots"})

    def test_get_trades_limit_positive(self):
        with self.assertRaises(RpcError):
            ph.paper_get_trades({"limit": 0})

    def test_suggest_requires_state_object(self):
        with self.assertRaises(RpcError):
            ph.paper_suggest_order_from_signal({"ticker": "510300.SH", "state": "x"})


@unittest.skipUnless(_HAS_BCRYPT, "bcrypt not installed (.[trading] extra)")
class TestPaperHandlerRouting(unittest.TestCase):
    def setUp(self):
        from mosaic.paper_trading.engine import PaperTradingEngine

        self._td = tempfile.TemporaryDirectory()
        d = Path(self._td.name)
        self.db = str(d / "paper.db")
        self._sess = patch.object(PaperTradingEngine, "SESSION_PATH", d / "session.json")
        self._price = patch.object(PaperTradingEngine, "_get_current_price", return_value=5.0)
        self._name = patch.object(PaperTradingEngine, "_auto_fill_name", return_value="ETF")
        self._sess.start()
        self._price.start()
        self._name.start()

    def tearDown(self):
        self._name.stop()
        self._price.stop()
        self._sess.stop()
        self._td.cleanup()

    def test_register_login_buy_flow(self):
        self.assertEqual(ph.paper_register({"username": "bob", "password": "pw", "db_path": self.db}),
                         {"username": "bob"})
        self.assertTrue(ph.paper_login({"username": "bob", "password": "pw", "db_path": self.db})["ok"])
        ph.paper_reset_account({"db_path": self.db, "user_id": "bob", "initial_cash": 500_000.0})
        res = ph.paper_buy({"db_path": self.db, "ticker": "159915.SZ", "quantity": 2000, "user_id": "bob"})
        self.assertEqual(res["side"], "buy")
        self.assertEqual(res["amount"], 10_000.0)
        self.assertEqual(len(ph.paper_get_positions({"db_path": self.db, "user_id": "bob"})), 1)

    def test_suggest_order_returns_buy_suggestion(self):
        ph.paper_register({"username": "bob", "password": "pw", "db_path": self.db})
        ph.paper_login({"username": "bob", "password": "pw", "db_path": self.db})
        ph.paper_reset_account({"db_path": self.db, "user_id": "bob", "initial_cash": 1_000_000.0})
        # price mocked at 5.0; 20% of 1M = 200k / 5 = 40000 shares.
        state = {"backtest_signal": {"ticker": "159915.SZ", "decision_date": "d",
                                     "source": "s", "source_section": "x",
                                     "rating": "BUY", "target_weight_pct": 20.0}}
        out = ph.paper_suggest_order_from_signal(
            {"db_path": self.db, "ticker": "159915.SZ", "state": state, "user_id": "bob"})
        self.assertEqual((out["side"], out["quantity"]), ("buy", 40000))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
