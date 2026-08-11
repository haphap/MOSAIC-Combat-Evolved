"""Tests for the ``data.*`` JSON-RPC handlers (Request #2).

Param-validation is dep-free (validate-first, before the lazy qlib_ingest
import). We do not run a real ingest (needs tushare/pyqlib + a token).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from mosaic.bridge.protocol import RpcError
from mosaic.bridge.tool_capabilities import capability_ledger_path
from mosaic.dataflows.agent_materialization import agent_data_materialization_db_path

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
    def test_source_preflight_evaluates_26_source_routes_and_seals_receipts(self):
        ledger = Mock()
        expected = {
            "schema_version": "agent_source_admission_v1",
            "status": "SOURCE_READY_PENDING_RUNTIME",
            "route_count": 26,
            "runtime_route_count": 4,
            "stage_count": 29,
        }
        with (
            patch.dict("os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "off"}),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ) as open_ledger,
            patch.object(
                dh, "evaluate_agent_source_admission", return_value=expected
            ) as evaluate,
            patch.object(
                dh,
                "_evaluation_timestamp",
                return_value="2026-07-01T08:00:00+00:00",
            ),
        ):
            result = dh.data_source_preflight(
                {"as_of": "2026-07-01", "all_agents": True}
            )

        open_ledger.assert_called_once_with(create=True)
        evaluate.assert_called_once_with(
            ledger=ledger,
            target_date="2026-07-01",
            evaluated_at="2026-07-01T08:00:00+00:00",
            require_production_license=False,
        )
        self.assertEqual(result, expected)

    def test_source_preflight_enforce_prepares_sources_before_evaluation(self):
        events = []
        ledger = Mock()
        capability_store = Mock()
        capability_store.prepare_source_admission.side_effect = (
            lambda **kwargs: events.append(("prepare", kwargs))
            or {"status": "SOURCE_PREPARED"}
        )

        def evaluate(**kwargs):
            events.append(("evaluate", kwargs))
            return {
                "schema_version": "agent_source_admission_v1",
                "status": "SOURCE_READY_PENDING_RUNTIME",
            }

        with (
            patch.dict("os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}),
            patch.object(dh, "get_capability_store", return_value=capability_store),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ),
            patch.object(dh, "evaluate_agent_source_admission", side_effect=evaluate),
            patch.object(
                dh,
                "_evaluation_timestamp",
                return_value="2026-07-01T08:00:00+00:00",
            ),
        ):
            result = dh.data_source_preflight(
                {"as_of": "2026-07-01", "all_agents": True}
            )

        self.assertEqual([event[0] for event in events], ["prepare", "evaluate"])
        self.assertTrue(events[1][1]["require_production_license"])
        capability_store.prepare_source_admission.assert_called_once_with(
            as_of="2026-07-01"
        )
        self.assertEqual(result["source_preparation"], {"status": "SOURCE_PREPARED"})

    def test_source_preflight_shadow_uses_one_isolated_namespace(self):
        shadow_root = Path("/tmp/mosaic-source-preflight-shadow")
        observed = {}
        capability_store = Mock()

        def get_store():
            observed["capability_path"] = capability_ledger_path()
            return capability_store

        def open_ledger(*, create):
            observed["materialization_path"] = agent_data_materialization_db_path()
            observed["create"] = create
            return Mock()

        with (
            patch.dict(
                "os.environ",
                {
                    "MOSAIC_ENSURE_SNAPSHOT_MODE": "shadow",
                    "MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT": str(shadow_root),
                },
            ),
            patch.object(dh, "get_capability_store", side_effect=get_store),
            patch.object(
                dh, "open_agent_data_materialization_ledger", side_effect=open_ledger
            ),
            patch.object(
                dh,
                "evaluate_agent_source_admission",
                return_value={
                    "schema_version": "agent_source_admission_v1",
                    "status": "BLOCKED",
                },
            ),
        ):
            result = dh.data_source_preflight(
                {"as_of": "2026-07-01", "all_agents": True}
            )

        self.assertEqual(
            observed,
            {
                "capability_path": (
                    shadow_root / "runtime" / "agent_tool_capabilities.sqlite3"
                ),
                "materialization_path": (
                    shadow_root / "agent_materialization" / "materialization.sqlite3"
                ),
                "create": True,
            },
        )
        capability_store.prepare_source_admission.assert_called_once_with(
            as_of="2026-07-01"
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_source_preflight_requires_explicit_all_agents(self):
        with self.assertRaises(RpcError):
            dh.data_source_preflight(
                {"as_of": "2026-07-01", "all_agents": False}
            )

    def test_source_backfill_prepares_and_seals_each_inclusive_date(self):
        route_id = "official.company_supply_chain_disclosures"
        capability_store = Mock()
        ledger = Mock()
        license_modes = []

        def eligibility(**kwargs):
            license_modes.append(kwargs["require_production_license"])
            target_date = kwargs["target_date"]
            receipt = Mock()
            receipt.receipt_hash = f"sha256:{target_date.replace('-', ''):0<64}"
            receipt.as_dict.return_value = {
                "status": "READY",
                "blockers": [],
            }
            return receipt

        with (
            patch.dict("os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}),
            patch.object(dh, "get_capability_store", return_value=capability_store),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ),
            patch.object(dh, "evaluate_route_eligibility", side_effect=eligibility),
        ):
            result = dh.data_source_backfill(
                {
                    "route_id": route_id,
                    "from": "2026-07-01",
                    "to": "2026-07-02",
                }
            )

        self.assertEqual(
            capability_store.prepare_source_admission.call_args_list,
            [
                call(as_of="2026-07-01", route_id=route_id),
                call(as_of="2026-07-02", route_id=route_id),
            ],
        )
        self.assertEqual(ledger.append_route_eligibility.call_count, 2)
        self.assertEqual(license_modes, [True, True])
        self.assertEqual(result["status"], "READY")
        self.assertEqual([row["target_date"] for row in result["dates"]], [
            "2026-07-01",
            "2026-07-02",
        ])

    def test_historical_source_backfill_is_shadow_only_and_passes_replay_cutoff(self):
        route_id = "tushare.eco_cal.cny"
        capability_store = Mock()
        ledger = Mock()
        receipt = Mock()
        receipt.receipt_hash = "sha256:" + "a" * 64
        receipt.as_dict.return_value = {"status": "READY", "blockers": []}
        events = []

        def prepare(**_kwargs):
            events.append("prepare")
            return {"status": "SOURCE_PREPARED"}

        def evaluation_timestamp():
            events.append("evaluation_clock")
            return "2026-08-10T15:00:00+08:00"

        def eligibility(**_kwargs):
            events.append("eligibility")
            return receipt

        capability_store.prepare_source_admission.side_effect = prepare

        with (
            patch.dict(
                "os.environ",
                {
                    "MOSAIC_ENSURE_SNAPSHOT_MODE": "shadow",
                    "MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT": "/tmp/historical-replay",
                },
            ),
            patch.object(dh, "get_capability_store", return_value=capability_store),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ),
            patch.object(
                dh, "_evaluation_timestamp", side_effect=evaluation_timestamp
            ),
            patch.object(dh, "evaluate_route_eligibility", side_effect=eligibility),
        ):
            result = dh.data_source_backfill(
                {
                    "route_id": route_id,
                    "from": "2026-07-01",
                    "to": "2026-07-01",
                    "historical_replay": True,
                }
            )

        capability_store.prepare_source_admission.assert_called_once_with(
            as_of="2026-07-01",
            route_id=route_id,
            historical_replay=True,
        )
        self.assertEqual(events, ["prepare", "evaluation_clock", "eligibility"])
        self.assertEqual(result["status"], "READY")

        with patch.dict(
            "os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}
        ):
            with self.assertRaisesRegex(RpcError, "historical replay.*shadow"):
                dh.data_source_backfill(
                    {
                        "route_id": route_id,
                        "from": "2026-07-01",
                        "to": "2026-07-01",
                        "historical_replay": True,
                    }
                )

    def test_source_backfill_rejects_runtime_route_and_reversed_range(self):
        with self.assertRaises(RpcError):
            dh.data_source_backfill(
                {
                    "route_id": "runtime.accepted_outputs",
                    "from": "2026-07-01",
                    "to": "2026-07-02",
                }
            )
        with self.assertRaises(RpcError):
            dh.data_source_backfill(
                {
                    "route_id": "tushare.a_share_breadth",
                    "from": "2026-07-02",
                    "to": "2026-07-01",
                }
            )

    def test_earliest_ready_date_reads_archive_without_creating_or_preparing(self):
        ledger = Mock()
        expected = {
            "schema_version": "agent_earliest_ready_date_v1",
            "status": "READY",
            "earliest_ready_date": "2026-06-30",
        }
        with (
            patch.dict("os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ) as opened,
            patch.object(
                dh, "earliest_agent_source_ready_date", return_value=expected
            ) as earliest,
            patch.object(
                dh,
                "_evaluation_timestamp",
                return_value="2026-07-04T08:00:00+00:00",
            ),
        ):
            result = dh.data_earliest_ready_date({"all_agents": True})

        opened.assert_called_once_with(create=False)
        earliest.assert_called_once_with(
            ledger=ledger,
            evaluated_at="2026-07-04T08:00:00+00:00",
        )
        self.assertEqual(result, expected)

    def test_earliest_ready_date_requires_explicit_all_agents(self):
        with self.assertRaises(RpcError):
            dh.data_earliest_ready_date({"all_agents": False})

    def test_cycle_open_uses_server_owned_fixed_point(self):
        ledger = Mock()
        expected = {"status": "OPEN"}
        timestamp = "2026-07-01T08:00:00+00:00"
        execution_hash = "sha256:" + "1" * 64
        knot_v2_hash = "sha256:" + "2" * 64
        with (
            patch.dict(
                "os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}
            ),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ),
            patch.object(
                dh,
                "load_active_capability_fixed_point",
                return_value={
                    "execution_behavior_release_hash": execution_hash,
                    "knot_coverage_manifest_v2_hash": knot_v2_hash,
                },
            ) as fixed_point,
            patch.object(dh, "open_agent_cycle", return_value=expected) as opened,
            patch.object(dh, "_evaluation_timestamp", return_value=timestamp),
        ):
            result = dh.data_cycle_open(
                {
                    "as_of": "2026-07-01",
                    "run_id": "daily-run-1",
                    "cohort": "cohort_default",
                    "mode": "enforce",
                    "cycle_kind": "PRODUCTION",
                    "lease_seconds": 7200,
                }
            )

        fixed_point.assert_called_once_with()
        opened.assert_called_once_with(
            ledger=ledger,
            target_date="2026-07-01",
            run_id="daily-run-1",
            cohort="cohort_default",
            mode="enforce",
            cycle_kind="PRODUCTION",
            execution_behavior_release_hash=execution_hash,
            knot_coverage_manifest_v2_hash=knot_v2_hash,
            opened_at=timestamp,
            lease_seconds=7200,
        )
        self.assertEqual(result, expected)

    def test_cycle_commit_and_abort_use_the_unified_ledger(self):
        ledger = Mock()
        state = {"trace_id": "daily-run-1"}
        timestamp = "2026-07-01T08:30:00+00:00"
        with (
            patch.dict(
                "os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}
            ),
            patch.object(
                dh, "open_agent_data_materialization_ledger", return_value=ledger
            ) as open_ledger,
            patch.object(
                dh, "commit_agent_cycle", return_value={"status": "COMMITTED"}
            ) as committed,
            patch.object(
                dh, "abort_agent_cycle", return_value={"status": "ABORTED"}
            ) as aborted,
            patch.object(dh, "_evaluation_timestamp", return_value=timestamp),
        ):
            self.assertEqual(
                dh.data_cycle_commit({"state": state})["status"], "COMMITTED"
            )
            self.assertEqual(
                dh.data_cycle_abort(
                    {"run_id": "daily-run-2", "reason": "STAGE_FAILURE"}
                )["status"],
                "ABORTED",
            )

        self.assertEqual(open_ledger.call_count, 2)
        committed.assert_called_once_with(
            ledger=ledger,
            state=state,
            committed_at=timestamp,
        )
        aborted.assert_called_once_with(
            ledger=ledger,
            run_id="daily-run-2",
            reason="STAGE_FAILURE",
            aborted_at=timestamp,
        )

    def test_shadow_cycle_lifecycle_uses_one_isolated_ledger(self):
        shadow_root = Path("/tmp/mosaic-cycle-shadow")
        expected_path = (
            shadow_root / "agent_materialization" / "materialization.sqlite3"
        )
        ledger = Mock()
        opened_paths = []

        def open_ledger(*, create):
            self.assertTrue(create)
            opened_paths.append(agent_data_materialization_db_path())
            return ledger

        with (
            patch.dict(
                "os.environ",
                {
                    "MOSAIC_ENSURE_SNAPSHOT_MODE": "shadow",
                    "MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT": str(shadow_root),
                },
            ),
            patch.object(
                dh, "open_agent_data_materialization_ledger", side_effect=open_ledger
            ),
            patch.object(
                dh,
                "load_active_capability_fixed_point",
                return_value={
                    "execution_behavior_release_hash": "sha256:" + "1" * 64,
                    "knot_coverage_manifest_v2_hash": "sha256:" + "2" * 64,
                },
            ),
            patch.object(dh, "open_agent_cycle", return_value={"status": "OPEN"}),
            patch.object(
                dh, "commit_agent_cycle", return_value={"status": "COMMITTED"}
            ),
            patch.object(
                dh, "abort_agent_cycle", return_value={"status": "ABORTED"}
            ),
        ):
            self.assertEqual(
                dh.data_cycle_open(
                    {
                        "as_of": "2026-07-01",
                        "run_id": "replay-run-1",
                        "cohort": "cohort_default",
                        "mode": "shadow",
                        "cycle_kind": "REPLAY",
                    }
                )["status"],
                "OPEN",
            )
            self.assertEqual(
                dh.data_cycle_commit({"state": {"trace_id": "replay-run-1"}})[
                    "status"
                ],
                "COMMITTED",
            )
            self.assertEqual(
                dh.data_cycle_abort(
                    {"run_id": "replay-run-2", "reason": "FAULT_INJECTION"}
                )["status"],
                "ABORTED",
            )

        self.assertEqual(opened_paths, [expected_path, expected_path, expected_path])

    def test_cycle_open_rejects_invalid_mode_before_loading_authority(self):
        base = {
            "as_of": "2026-07-01",
            "run_id": "daily-run-1",
            "cohort": "cohort_default",
            "mode": "off",
            "cycle_kind": "PRODUCTION",
        }
        with patch.object(dh, "load_active_capability_fixed_point") as fixed_point:
            with self.assertRaises(RpcError):
                dh.data_cycle_open(base)
        fixed_point.assert_not_called()

    def test_cycle_lifecycle_rejects_off_and_configured_mode_drift(self):
        with patch.dict(
            "os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "off"}
        ):
            with self.assertRaisesRegex(
                RpcError, "P1_ENSURE_MODE_DRIFT.*requires explicit"
            ):
                dh.data_cycle_commit({"state": {"trace_id": "off-run"}})
            with self.assertRaisesRegex(
                RpcError, "P1_ENSURE_MODE_DRIFT.*requires explicit"
            ):
                dh.data_cycle_abort(
                    {"run_id": "off-run", "reason": "MUST_NOT_OPEN"}
                )

        with patch.dict(
            "os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "shadow"}
        ):
            with self.assertRaisesRegex(
                RpcError, "P1_ENSURE_MODE_DRIFT.*does not match configured mode"
            ):
                dh.data_cycle_open(
                    {
                        "as_of": "2026-07-01",
                        "run_id": "production-run-in-shadow",
                        "cohort": "cohort_default",
                        "mode": "enforce",
                        "cycle_kind": "PRODUCTION",
                    }
                )

    def test_cycle_open_fails_closed_when_server_authority_is_invalid(self):
        params = {
            "as_of": "2026-07-01",
            "run_id": "daily-run-1",
            "cohort": "cohort_default",
            "mode": "enforce",
            "cycle_kind": "PRODUCTION",
        }
        with (
            patch.dict(
                "os.environ", {"MOSAIC_ENSURE_SNAPSHOT_MODE": "enforce"}
            ),
            patch.object(
                dh,
                "load_active_capability_fixed_point",
                side_effect=ValueError("active fixed point drift"),
            ),
            patch.object(dh, "open_agent_cycle") as opened,
        ):
            with self.assertRaisesRegex(RpcError, "active fixed point drift"):
                dh.data_cycle_open(params)
        opened.assert_not_called()

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

    def test_materialize_cycle_dry_run_never_opens_a_writer(self):
        ledger = Mock()
        ledger.materialize_cycle_dry_run.return_value = {
            "schema_version": "agent_cycle_materialization_dry_run_v1",
            "dry_run": True,
            "status": "BLOCKED",
            "stage_count": 29,
        }
        with patch.object(
            dh, "open_agent_data_materialization_ledger", return_value=ledger
        ) as open_ledger:
            result = dh.data_materialize_cycle_dry_run(
                {
                    "as_of": "2026-07-01",
                    "all_agents": True,
                    "dry_run": True,
                }
            )

        open_ledger.assert_called_once_with(create=False)
        ledger.materialize_cycle_dry_run.assert_called_once_with(as_of="2026-07-01")
        self.assertEqual(result["stage_count"], 29)

    def test_materialize_cycle_requires_explicit_dry_run_and_all_agents(self):
        with self.assertRaises(RpcError):
            dh.data_materialize_cycle_dry_run(
                {"as_of": "2026-07-01", "all_agents": True, "dry_run": False}
            )
        with self.assertRaises(RpcError):
            dh.data_materialize_cycle_dry_run(
                {"as_of": "2026-07-01", "all_agents": False, "dry_run": True}
            )

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
