"""Tests for the ``data.*`` JSON-RPC handlers (Request #2).

Param-validation is dep-free (validate-first, before the lazy qlib_ingest
import). We do not run a real ingest (needs tushare/pyqlib + a token).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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


class TestAgentMaterializationStatus(unittest.TestCase):
    def test_source_status_is_read_only_and_forwards_strict_params(self):
        ledger = Mock()
        ledger.source_status.return_value = {
            "route_id": "tushare.eco_cal.cny",
            "as_of": "2026-07-01",
            "status": "BLOCKED",
            "blocker_codes": ["NO_CAPTURE_RECEIPT"],
            "capture_receipt_hash": None,
        }
        with patch.object(
            dh, "open_agent_data_materialization_ledger", return_value=ledger
        ) as open_ledger:
            result = dh.data_source_status(
                {"as_of": "2026-07-01", "route_id": "tushare.eco_cal.cny"}
            )

        open_ledger.assert_called_once_with(create=False)
        ledger.source_status.assert_called_once_with(
            as_of="2026-07-01", route_id="tushare.eco_cal.cny"
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_snapshot_status_forwards_agent_stage(self):
        ledger = Mock()
        ledger.snapshot_status.return_value = {"status": "BLOCKED"}
        with patch.object(
            dh, "open_agent_data_materialization_ledger", return_value=ledger
        ):
            result = dh.data_snapshot_status(
                {"as_of": "2026-07-01", "agent_id": "china", "stage": "china"}
            )

        ledger.snapshot_status.assert_called_once_with(
            as_of="2026-07-01", agent_id="china", stage="china"
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_materialize_requires_explicit_dry_run(self):
        with self.assertRaises(RpcError):
            dh.data_materialize_dry_run(
                {
                    "as_of": "2026-07-01",
                    "agent_id": "china",
                    "stage": "china",
                    "dry_run": False,
                }
            )

    def test_materialize_dry_run_never_opens_a_writer(self):
        ledger = Mock()
        ledger.materialize_dry_run.return_value = {
            "dry_run": True,
            "status": "BLOCKED",
        }
        with patch.object(
            dh, "open_agent_data_materialization_ledger", return_value=ledger
        ) as open_ledger:
            result = dh.data_materialize_dry_run(
                {
                    "as_of": "2026-07-01",
                    "agent_id": "china",
                    "stage": "china",
                    "dry_run": True,
                }
            )

        open_ledger.assert_called_once_with(create=False)
        ledger.materialize_dry_run.assert_called_once_with(
            as_of="2026-07-01", agent_id="china", stage="china"
        )
        self.assertTrue(result["dry_run"])

    def test_status_rejects_invalid_date_and_unknown_binding(self):
        with self.assertRaises(RpcError):
            dh.data_source_status(
                {"as_of": "July 1", "route_id": "tushare.eco_cal.cny"}
            )

        ledger = Mock()
        ledger.snapshot_status.side_effect = ValueError("unknown Agent/stage")
        with patch.object(
            dh, "open_agent_data_materialization_ledger", return_value=ledger
        ):
            with self.assertRaises(RpcError):
                dh.data_snapshot_status(
                    {"as_of": "2026-07-01", "agent_id": "china", "stage": "unknown"}
                )


if __name__ == "__main__":
    unittest.main()
