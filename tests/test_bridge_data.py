"""Tests for the ``data.*`` JSON-RPC handlers (Request #2).

Param-validation is dep-free (validate-first, before the lazy qlib_ingest
import). We do not run a real ingest (needs tushare/pyqlib + a token).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from mosaic.bridge.protocol import RpcError

try:
    from mosaic.bridge.handlers import data as dh
except Exception:  # pragma: no cover - fallback when optional deps absent
    _key = "mosaic.bridge.handlers.data"
    if _key in sys.modules:
        dh = sys.modules[_key]
    else:
        _HANDLER_PATH = (
            Path(__file__).resolve().parent.parent
            / "mosaic" / "bridge" / "handlers" / "data.py"
        )
        _spec = importlib.util.spec_from_file_location(_key, str(_HANDLER_PATH))
        dh = importlib.util.module_from_spec(_spec)
        sys.modules[_key] = dh
        _spec.loader.exec_module(dh)


class TestDataParamValidation(unittest.TestCase):
    def test_incremental_rejects_bad_kind(self):
        with self.assertRaises(RpcError):
            dh.data_incremental({"kind": "bonds", "end": "2026-05-30"})

    def test_incremental_requires_end(self):
        with self.assertRaises(RpcError):
            dh.data_incremental({"kind": "stock"})

    def test_incremental_rejects_bad_timeout(self):
        with self.assertRaises(RpcError):
            dh.data_incremental({"kind": "stock", "end": "2026-05-30", "timeout": 0})
        with self.assertRaises(RpcError):
            dh.data_incremental({"kind": "stock", "end": "2026-05-30", "timeout": "fast"})

    def test_validate_rejects_bad_kind(self):
        with self.assertRaises(RpcError):
            dh.data_validate({"kind": "futures"})

    def test_validate_rejects_bad_gap_threshold(self):
        with self.assertRaises(RpcError):
            dh.data_validate({"kind": "stock", "gap_threshold": "tight"})

    def test_kind_defaults_to_stock_and_passes_validation(self):
        # Default kind is accepted; mock the ingest so the test is independent
        # of installed deps / on-disk datasets.
        import mosaic.dataflows.qlib_ingest as qi

        class _Outcome:
            returncode = 0
            qlib_dir = "/tmp/cn_data"

        captured = {}

        def _fake(*, end, kind, timeout, stream_stdout):
            captured.update(end=end, kind=kind)
            return _Outcome()

        orig = qi.ingest_incremental
        qi.ingest_incremental = _fake
        try:
            res = dh.data_incremental({"end": "2026-05-30"})
        finally:
            qi.ingest_incremental = orig
        self.assertEqual(captured["kind"], "stock")
        self.assertTrue(res["ok"])
        self.assertEqual(res["kind"], "stock")


if __name__ == "__main__":
    unittest.main()
