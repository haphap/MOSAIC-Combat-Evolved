from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.bridge.tool_capabilities import AgentToolCapabilityStore
from mosaic.dataflows.frozen_adaptive_queries import FrozenAdaptiveQueryStore
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import build_l3_l4_preservation_overlay


ROOT = Path(__file__).parents[1]


def _request(*, materialization_request_id: str = "materialize-china") -> dict:
    return {
        "graph_run_id": "graph-1",
        "run_slot_id": "slot-china",
        "run_id": "run-1",
        "node_id": "node-china",
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-09",
        "materialization_request_id": materialization_request_id,
        "runtime_inputs": {"accepted_record_ids": ["record-1"]},
        "candidate_scope": None,
        "ttl_seconds": 60,
    }


def _trusted_finalizer(context: dict) -> dict:
    tool_ids = sorted(context["tool_payload_hashes"])
    return {
        "agent_id": context["agent_id"],
        "stage": context["stage"],
        "as_of": context["as_of"],
        "status": "READY",
        "tool_ids": tool_ids,
        "build_receipt_hashes": {
            tool_id: canonical_hash(
                {
                    "tool_id": tool_id,
                    "payload_hash": context["tool_payload_hashes"][tool_id],
                }
            )
            for tool_id in tool_ids
        },
        "materialization_attempt_receipt_hash": canonical_hash(
            {
                "materialization_request_id": context["materialization_request_id"],
                "tool_ids": tool_ids,
            }
        ),
        "cache_status": "MISS",
    }


def _store(tmp_path: Path) -> AgentToolCapabilityStore:
    return AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: datetime(2026, 7, 9, tzinfo=timezone.utc),
        stage_materialization_finalizer=_trusted_finalizer,
    )


def _materialize(tool_id: str, **_kwargs: object) -> str:
    return json.dumps({"tool": tool_id, "frozen": True}, sort_keys=True)


def _materialize_directional(tool_id: str, **_kwargs: object) -> str:
    return json.dumps(
        {"tool": tool_id, "trend": "up"},
        sort_keys=True,
    )


def _accepted_knot_record(
    *,
    prepared: dict,
    audit: dict,
    accepted_output_id: str = "accepted:knot-history:1",
) -> dict:
    claim = {
        "claim_id": "claim:1",
        "evidence_ids": ["evidence:1"],
        "structured_conclusion": {"trend": "down"},
    }
    capture_body = {
        "schema_version": "accepted_knot_capture_v2",
        "accepted_lineage_evaluator_version": "accepted_claim_lineage_v3",
        "eligibility": "ELIGIBLE",
        "ineligibility_reasons": [],
        "accepted_claim_graph_hash": canonical_hash({"graph": "accepted"}),
        "tool_environment_hash": audit["tool_environment_hash"],
        "execution_behavior_release_hash": audit[
            "execution_behavior_release_hash"
        ],
        "capability_bundle_hash": audit["capability_bundle_hash"],
        "knot_coverage_manifest_v2_hash": audit[
            "knot_coverage_manifest_v2_hash"
        ],
        "knot_audit_capability_track_v2_hash": audit[
            "knot_audit_capability_track_v2_hash"
        ],
        "result_event_refs": [
            {
                "result_event_id": audit["result_event_id"],
                "result_event_hash": audit["result_event_hash"],
                "result_authority_type": audit["result_authority_type"],
                "result_authority_hash": audit["result_authority_hash"],
                "evidence_ids": ["evidence:1"],
                "binding_result_refs": audit["binding_result_refs"],
            }
        ],
        "claim_specs": [
            {**claim, "claim_spec_hash": canonical_hash(claim)}
        ],
    }
    record = {
        "accepted_output_id": accepted_output_id,
        "graph_run_id": "graph-1",
        "run_slot_id": "slot-china",
        "agent_id": "china",
        "knot_capture_v2": {
            **capture_body,
            "capture_hash": canonical_hash(capture_body),
        },
        "output": {
            "claim_graph_lineage": {
                "evidence": [
                    {
                        "evidence_id": "evidence:1",
                        "source_fingerprint": audit["result_event_hash"],
                    }
                ],
                "claims": [
                    {"claim_id": "claim:1", "evidence_ids": ["evidence:1"]}
                ],
            },
            "payload": {
                "claims": [
                    {
                        "claim_id": "claim:1",
                        "statement": "private prose is outside history",
                        "structured_conclusion": claim["structured_conclusion"],
                    }
                ]
            },
        },
    }
    record["accepted_output_hash"] = canonical_hash(record)
    assert prepared["capability"]["manifest"]["run_slot_id"] == record["run_slot_id"]
    return record


def test_prepare_and_reissue_seal_knot_audit_contexts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize)
    reissued = store.issue_for_bundle(
        {
            "graph_run_id": "graph-1",
            "run_slot_id": "slot-china-reissue",
            "run_id": "run-2",
            "node_id": "node-china-reissue",
            "agent_id": "china",
            "stage": "china",
            "as_of": "2026-07-09",
            "snapshot_bundle_id": prepared["bundle"]["snapshot_bundle_id"],
            "snapshot_bundle_hash": prepared["bundle"]["snapshot_bundle_hash"],
            "ttl_seconds": 60,
        }
    )

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        bundle_row = conn.execute(
            "SELECT * FROM snapshot_bundle_audit_contexts"
        ).fetchone()
        capability_rows = conn.execute(
            "SELECT * FROM capability_audit_contexts ORDER BY created_at, capability_id"
        ).fetchall()

    assert bundle_row is not None
    bundle_context = json.loads(bundle_row["context_json"])
    assert bundle_context["schema_version"] == "snapshot_bundle_audit_context_v1"
    assert bundle_context["snapshot_bundle_id"] == prepared["bundle"]["snapshot_bundle_id"]
    assert bundle_context["snapshot_bundle_hash"] == prepared["bundle"]["snapshot_bundle_hash"]
    assert bundle_context["knot_v2_eligibility"] == "ELIGIBLE"
    assert set(bundle_context["build_receipt_hashes"]) == {
        "get_china_macro_snapshot"
    }
    assert bundle_context["materialization_attempt_receipt_hash"].startswith("sha256:")
    assert bundle_context["capability_binding_manifest_hash"].startswith("sha256:")
    assert bundle_context["tool_environment_hash"].startswith("sha256:")
    assert bundle_context["knot_coverage_manifest_hash"].startswith("sha256:")
    assert bundle_context["capability_bundle_hash"].startswith("sha256:")
    assert bundle_context["knot_coverage_manifest_v2_hash"].startswith("sha256:")
    assert bundle_context["knot_audit_capability_track_v2_hash"].startswith("sha256:")
    assert bundle_context["tool_contexts"] == sorted(
        bundle_context["tool_contexts"], key=lambda row: row["tool_id"]
    )
    assert bundle_context["tool_contexts"][0]["binding_refs"] == sorted(
        bundle_context["tool_contexts"][0]["binding_refs"],
        key=lambda row: row["binding_id"],
    )
    assert bundle_row["context_hash"] == canonical_hash(bundle_context)
    assert bundle_row["signing_key_id"] == "test-key-v1"
    assert bundle_row["signature"]

    assert len(capability_rows) == 2
    contexts = [json.loads(row["context_json"]) for row in capability_rows]
    assert {row["capability_id"] for row in contexts} == {
        prepared["capability"]["manifest"]["capability_id"],
        reissued["capability"]["manifest"]["capability_id"],
    }
    assert {row["run_slot_id"] for row in contexts} == {
        "slot-china",
        "slot-china-reissue",
    }
    assert {row["snapshot_bundle_audit_context_hash"] for row in contexts} == {
        bundle_row["context_hash"]
    }
    assert all(row["knot_v2_eligibility"] == "ELIGIBLE" for row in contexts)
    assert all(
        capability_rows[index]["context_hash"] == canonical_hash(contexts[index])
        for index in range(2)
    )

    with sqlite3.connect(store.db_path) as conn:
        for table in (
            "snapshot_bundle_audit_contexts",
            "capability_audit_contexts",
        ):
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.IntegrityError as exc:
                assert "append-only" in str(exc)
            else:  # pragma: no cover - the test must fail if the trigger is absent
                raise AssertionError(f"{table} is not append-only")


def test_snapshot_call_writes_server_owned_public_safe_result_event(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize)

    result = store.call_tool_result(
        prepared["capability"], "get_china_macro_snapshot", {}
    )

    assert json.loads(result["text"]) == {
        "frozen": True,
        "tool": "get_china_macro_snapshot",
    }
    assert set(result["audit"]) == {
        "schema_version",
        "result_event_id",
        "result_event_hash",
        "status",
        "result_authority_type",
        "result_authority_hash",
        "tool_environment_hash",
        "execution_behavior_release_hash",
        "capability_bundle_hash",
        "knot_coverage_manifest_v2_hash",
        "knot_audit_capability_track_v2_hash",
        "binding_result_refs",
    }
    assert result["audit"]["schema_version"] == "tool_call_audit_v1"
    assert result["audit"]["status"] == "SUCCEEDED"
    assert result["audit"]["result_authority_type"] == "SNAPSHOT_BUILD"
    assert result["audit"]["result_authority_hash"].startswith("sha256:")
    assert result["audit"]["binding_result_refs"]
    assert all(
        set(ref) == {"binding_id", "binding_result_fingerprint"}
        for ref in result["audit"]["binding_result_refs"]
    )
    assert "payload" not in json.dumps(result["audit"])
    assert "ticker" not in json.dumps(result["audit"])

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        event_row = conn.execute("SELECT * FROM tool_result_events").fetchone()
        projection_rows = conn.execute(
            "SELECT * FROM binding_signal_projections ORDER BY binding_id"
        ).fetchall()
    assert event_row is not None
    event = json.loads(event_row["event_json"])
    assert event["schema_version"] == "server_tool_result_event_v1"
    assert event["sequence"] == 1
    assert event["capability_id"] == prepared["capability"]["manifest"]["capability_id"]
    assert event["run_slot_id"] == "slot-china"
    assert event["agent_id"] == "china"
    assert event["stage"] == "china"
    assert event["tool_id"] == "get_china_macro_snapshot"
    assert event["call_mode"] == "SNAPSHOT"
    assert event["canonical_args_hash"] == canonical_hash({})
    assert event["payload_hash"] == canonical_hash({"text": result["text"]})
    assert event["status"] == "SUCCEEDED"
    assert event["result_authority"] == {
        "authority_hash": result["audit"]["result_authority_hash"],
        "authority_type": "SNAPSHOT_BUILD",
    }
    for field in (
        "tool_environment_hash",
        "execution_behavior_release_hash",
        "capability_bundle_hash",
        "knot_coverage_manifest_v2_hash",
        "knot_audit_capability_track_v2_hash",
    ):
        assert result["audit"][field] == event[field]
        assert result["audit"][field].startswith("sha256:")
    assert event["binding_refs"] == sorted(
        event["binding_refs"], key=lambda row: row["binding_id"]
    )
    assert event_row["result_event_hash"] == canonical_hash(event)
    assert result["audit"]["result_event_hash"] == event_row["result_event_hash"]
    assert len(projection_rows) == len(event["binding_refs"])
    projections = [json.loads(row["projection_json"]) for row in projection_rows]
    assert [row["binding_id"] for row in projections] == [
        row["binding_id"] for row in event["binding_refs"]
    ]
    assert all(row["result_event_id"] == event["result_event_id"] for row in projections)
    assert all(row["projection_status"] == "UNKNOWN" for row in projections)
    assert all(row["unknown_reason"] == "NO_TRUSTED_SIGNAL" for row in projections)
    assert all(
        projection_rows[index]["projection_hash"]
        == canonical_hash(
            {key: value for key, value in projection.items() if key != "projection_hash"}
        )
        for index, projection in enumerate(projections)
    )
    assert "get_china_macro_snapshot" not in json.dumps(projections)

    with sqlite3.connect(store.db_path) as conn:
        for statement in (
            "UPDATE tool_result_events SET status = 'FAILED'",
            "DELETE FROM tool_result_events",
            "UPDATE binding_signal_projections SET binding_id = 'binding:forged'",
            "DELETE FROM binding_signal_projections",
        ):
            try:
                conn.execute(statement)
            except sqlite3.IntegrityError as exc:
                assert "append-only" in str(exc)
            else:  # pragma: no cover - the test must fail if the trigger is absent
                raise AssertionError("tool_result_events is not append-only")


def test_accepted_output_materializes_server_owned_knot_v2_history(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize_directional)
    result = store.call_tool_result(
        prepared["capability"], "get_china_macro_snapshot", {}
    )
    accepted = _accepted_knot_record(prepared=prepared, audit=result["audit"])

    first = store.finalize_accepted_knot_history_v2(accepted)
    second = store.finalize_accepted_knot_history_v2(copy.deepcopy(accepted))

    assert first == second
    assert first["schema_version"] == "accepted_knot_history_materialization_v2"
    assert first["status"] == "MATERIALIZED"
    assert first["observation_count"] == len(result["audit"]["binding_result_refs"])
    assert first["evaluation_count"] == len(result["audit"]["binding_result_refs"])
    assert "private prose" not in json.dumps(first)

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        materializations = conn.execute(
            "SELECT * FROM accepted_knot_history_materializations_v2"
        ).fetchall()
        observations = conn.execute(
            "SELECT * FROM knot_binding_observations_v2 ORDER BY binding_id"
        ).fetchall()
        evaluations = conn.execute(
            "SELECT * FROM trusted_counterevidence_evaluations_v2 "
            "ORDER BY binding_id, claim_id"
        ).fetchall()

    assert len(materializations) == 1
    assert len(observations) == first["observation_count"]
    assert len(evaluations) == first["evaluation_count"]
    observation = json.loads(observations[0]["observation_json"])
    evaluation = json.loads(evaluations[0]["evaluation_json"])
    assert observation["eligible"] is True
    assert observation["ready"] is True
    assert observation["called"] is True
    assert observation["succeeded"] is True
    assert observation["used_in_accepted_evidence"] is True
    assert observation["counterevidence_available"] is True
    assert observation["counterevidence_handled"] is True
    assert evaluation["evaluation_status"] == "EVALUATED"
    assert evaluation["resolution_code"] == "reversed"
    assert "comparison_value" not in evaluation
    assert "private prose" not in json.dumps(observation)
    assert "private prose" not in json.dumps(evaluation)

    with sqlite3.connect(store.db_path) as conn:
        for table in (
            "accepted_knot_history_materializations_v2",
            "knot_binding_observations_v2",
            "trusted_counterevidence_evaluations_v2",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(f"DELETE FROM {table}")


def test_knot_v2_history_rejects_forged_event_and_excludes_legacy(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize_directional)
    result = store.call_tool_result(
        prepared["capability"], "get_china_macro_snapshot", {}
    )
    accepted = _accepted_knot_record(prepared=prepared, audit=result["audit"])
    forged = copy.deepcopy(accepted)
    forged_capture = forged["knot_capture_v2"]
    forged_capture["result_event_refs"][0]["result_event_hash"] = canonical_hash(
        {"forged": True}
    )
    forged_capture["capture_hash"] = canonical_hash(
        {key: value for key, value in forged_capture.items() if key != "capture_hash"}
    )
    forged["accepted_output_hash"] = canonical_hash(
        {key: value for key, value in forged.items() if key != "accepted_output_hash"}
    )

    with pytest.raises(ValueError, match="result event .* mismatch"):
        store.finalize_accepted_knot_history_v2(forged)

    legacy = {
        "accepted_output_id": "accepted:legacy:1",
        "graph_run_id": "graph-legacy",
        "run_slot_id": "slot-legacy",
        "agent_id": "china",
        "output": {},
    }
    legacy["accepted_output_hash"] = canonical_hash(legacy)
    exclusion = store.finalize_accepted_knot_history_v2(legacy)
    assert exclusion["status"] == "EXCLUDED"
    assert exclusion["exclusion_reasons"] == ["LEGACY_KNOT_CAPTURE_MISSING"]
    assert exclusion["observation_count"] == 0
    assert store.finalize_accepted_knot_history_v2(legacy) == exclusion

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM accepted_knot_history_materializations_v2"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM knot_binding_observations_v2"
        ).fetchone()[0] == 0


def test_knot_v2_history_partition_has_exact_192_binding_closure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize_directional)
    result = store.call_tool_result(
        prepared["capability"], "get_china_macro_snapshot", {}
    )
    accepted = _accepted_knot_record(prepared=prepared, audit=result["audit"])
    materialization = store.finalize_accepted_knot_history_v2(accepted)

    projection = store.build_knot_history_partition_v2(
        cutoff_at="2026-07-09T23:59:59+00:00"
    )

    assert projection["schema_version"] == "knot_training_history_partition_v2"
    assert projection["sample_count"] == 1
    assert projection["excluded_sample_count"] == 0
    assert projection["materialization_refs"] == [
        {
            "accepted_output_hash": accepted["accepted_output_hash"],
            "materialization_hash": materialization["materialization_hash"],
        }
    ]
    assert len(projection["binding_aggregates"]) == 192
    assert [row["binding_id"] for row in projection["binding_aggregates"]] == sorted(
        row["binding_id"] for row in projection["binding_aggregates"]
    )
    used = [
        row
        for row in projection["binding_aggregates"]
        if row["used_in_accepted_evidence_count"]
    ]
    assert len(used) == len(result["audit"]["binding_result_refs"])
    assert all(row["counterevidence_handled_count"] == 1 for row in used)
    assert projection["partition_hash"] == canonical_hash(
        {key: value for key, value in projection.items() if key != "partition_hash"}
    )
    assert "private prose" not in json.dumps(projection)

    before = store.build_knot_history_partition_v2(
        cutoff_at="2026-07-08T23:59:59+00:00"
    )
    assert before["sample_count"] == 0
    assert all(row["eligible_count"] == 0 for row in before["binding_aggregates"])


def test_adaptive_initial_call_uses_frozen_query_result_authority(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)
    frozen = FrozenAdaptiveQueryStore(
        tmp_path / "frozen.sqlite3", clock=lambda: now
    )
    prior_payload = json.dumps({"kind": "rke-prior", "shadow_only": True})
    prepared_query = frozen.prepare(
        agent_id="cro",
        stage="cro",
        preservation_stage="cro_review",
        as_of="2026-07-09",
        authorized_scope={
            "as_of": "2026-07-09",
            "accepted_candidate_tickers": ["600519.SH"],
            "accepted_output_set_hash": canonical_hash({"accepted": "l1-l3"}),
            "account_positions_policy_hash": canonical_hash(
                {"positions": "current"}
            ),
            "market_liquidity_vintage_hash": canonical_hash(
                {"market": "2026-07-09"}
            ),
        },
        initial_query_requests=[
            {
                "tool_id": "get_rke_research_context",
                "args": {
                    "agent_id": "cro",
                    "as_of": "2026-07-09",
                    "layer": "decision",
                    "max_items": 3,
                },
            }
        ],
        query_requests=[],
        preservation_overlay=build_l3_l4_preservation_overlay(ROOT),
        materializer=lambda tool_id, args: {
            "payload": prior_payload,
            "source_receipt_hashes": [
                canonical_hash({"tool_id": tool_id, "args": args})
            ],
        },
    )
    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.sqlite3",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
        clock=lambda: now,
        adaptive_query_store=frozen,
        adaptive_query_preparer=lambda **_kwargs: prepared_query,
        stage_materialization_finalizer=_trusted_finalizer,
    )
    request = {
        "graph_run_id": "graph-cro",
        "run_slot_id": "slot-cro",
        "run_id": "run-cro",
        "node_id": "node-cro",
        "agent_id": "cro",
        "stage": "cro",
        "as_of": "2026-07-09",
        "materialization_request_id": "materialize-cro",
        "runtime_inputs": {},
        "candidate_scope": {"scope_id": "scope-cro"},
        "ttl_seconds": 60,
    }
    prepared = store.prepare(request, materializer=_materialize)

    result = store.call_tool_result(
        prepared["capability"], "get_rke_research_context", {}
    )

    assert result["text"] == prior_payload
    assert result["audit"]["result_authority_type"] == "FROZEN_QUERY"
    frozen_result = frozen.read_initial_results(
        bundle_id=prepared_query["bundle_id"], agent_id="cro", stage="cro"
    )[0]
    assert result["audit"]["result_authority_hash"] == frozen_result[
        "result_authority"
    ]["authority_hash"]
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        event_row = conn.execute("SELECT * FROM tool_result_events").fetchone()
    assert event_row is not None
    event = json.loads(event_row["event_json"])
    assert event["call_mode"] == "INITIAL"
    assert event["canonical_args_hash"] == canonical_hash({})
    assert event["result_authority"] == {
        "authority_hash": frozen_result["result_authority"]["authority_hash"],
        "authority_type": "FROZEN_QUERY",
    }


def test_one_physical_result_projects_every_semantic_binding_ref(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    request = _request(materialization_request_id="materialize-central-bank")
    request.update(
        {
            "run_slot_id": "slot-central-bank",
            "node_id": "node-central-bank",
            "agent_id": "central_bank",
            "stage": "central_bank",
        }
    )
    prepared = store.prepare(request, materializer=_materialize)

    result = store.call_tool_result(
        prepared["capability"], "get_central_bank_snapshot", {}
    )

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        event = json.loads(
            conn.execute("SELECT event_json FROM tool_result_events").fetchone()[0]
        )
        projections = [
            json.loads(row["projection_json"])
            for row in conn.execute(
                "SELECT projection_json FROM binding_signal_projections ORDER BY binding_id"
            ).fetchall()
        ]
    assert len(event["binding_refs"]) == 3
    assert len(result["audit"]["binding_result_refs"]) == 3
    assert len(projections) == 3
    assert {row["binding_id"] for row in projections} == {
        row["binding_id"] for row in event["binding_refs"]
    }
    assert len({row["binding_result_fingerprint"] for row in projections}) == 3


def test_allowed_binding_rejections_write_enum_only_failed_events(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize)
    store.call_tool_result(
        prepared["capability"], "get_china_macro_snapshot", {}
    )

    with pytest.raises(ValueError, match="already been used"):
        store.call_tool_result(
            prepared["capability"], "get_china_macro_snapshot", {}
        )

    second = store.prepare(
        _request(materialization_request_id="materialize-china-2"),
        materializer=_materialize,
    )
    with pytest.raises(ValueError, match="accept no arguments"):
        store.call_tool_result(
            second["capability"],
            "get_china_macro_snapshot",
            {"as_of_date": "2099-01-01"},
        )

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tool_result_events ORDER BY recorded_at, result_event_id"
        ).fetchall()
    events = [json.loads(row["event_json"]) for row in rows]
    assert [event["status"] for event in events].count("SUCCEEDED") == 1
    failed = [event for event in events if event["status"] == "FAILED"]
    assert {event["error_code"] for event in failed} == {
        "ARGUMENT_SCHEMA_REJECTED",
        "CAPABILITY_TOOL_ALREADY_USED",
    }
    for event in failed:
        assert event["payload_hash"] is None
        assert event["result_authority"] is None
        assert all(
            "binding_result_fingerprint" not in ref
            for ref in event["binding_refs"]
        )
        serialized = json.dumps(event)
        assert "already been used" not in serialized
        assert "2099-01-01" not in serialized
    with sqlite3.connect(store.db_path) as conn:
        projection_count = conn.execute(
            "SELECT COUNT(*) FROM binding_signal_projections"
        ).fetchone()[0]
    succeeded_refs = sum(
        len(event["binding_refs"])
        for event in events
        if event["status"] == "SUCCEEDED"
    )
    assert projection_count == succeeded_refs


def test_whitelist_rejection_is_separate_from_knot_result_events(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prepared = store.prepare(_request(), materializer=_materialize)

    with pytest.raises(ValueError, match="not allowed"):
        store.call_tool_result(
            prepared["capability"],
            "get_private_unregistered_data",
            {"ticker": "SECRET.TICKER"},
        )

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT COUNT(*) FROM tool_result_events").fetchone()[0] == 0
        row = conn.execute("SELECT * FROM tool_security_rejections").fetchone()
    assert row is not None
    event = json.loads(row["event_json"])
    assert event["schema_version"] == "tool_security_rejection_event_v1"
    assert event["reason_code"] == "TOOL_NOT_ALLOWED"
    assert event["attempted_tool_id_hash"] == canonical_hash(
        {"tool_id": "get_private_unregistered_data"}
    )
    assert event["canonical_args_hash"] == canonical_hash(
        {"ticker": "SECRET.TICKER"}
    )
    serialized = json.dumps(event)
    assert "get_private_unregistered_data" not in serialized
    assert "SECRET.TICKER" not in serialized
