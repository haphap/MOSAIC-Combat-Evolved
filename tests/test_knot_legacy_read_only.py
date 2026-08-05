from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from mosaic.bridge import handlers as _handlers  # noqa: F401
from mosaic.bridge.registry import all_methods
from mosaic.bridge.tool_capabilities import AgentToolCapabilityStore
from mosaic.scorecard import ScorecardStore
from mosaic.scorecard import knot_v2

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_knot_rpc_and_typescript_clients_are_retired() -> None:
    assert not any(method.startswith("darwinian.knot_") for method in all_methods())
    bridge_types = (ROOT / "mosaic-ts/src/bridge/types.ts").read_text(encoding="utf-8")
    assert 'client.call("darwinian.knot_' not in bridge_types


def test_active_runtime_paths_do_not_import_legacy_knot_authority() -> None:
    active_paths = [
        "mosaic-ts/src/agents/macro/_factory.ts",
        "mosaic-ts/src/agents/sector/_factory.ts",
        "mosaic-ts/src/agents/superinvestor/_factory.ts",
        "mosaic-ts/src/agents/decision/_factory.ts",
        "mosaic-ts/src/agents/helpers/agent_loop.ts",
        "mosaic-ts/src/agents/helpers/evidence_runtime.ts",
        "mosaic-ts/src/agents/helpers/strict_agent_validation.ts",
        "mosaic-ts/src/agents/prompts/runtime_prompt_preflight.ts",
        "mosaic-ts/src/agents/prompts/runtime_agent_spec.ts",
        "mosaic-ts/src/graph/layer4.ts",
        "mosaic-ts/src/cli/commands/daily-cycle.ts",
    ]
    forbidden = (
        "private_knot_runtime",
        "knot_research_runtime_binding",
        "formal_knot",
        "darwinian.knot_",
    )
    for relative_path in active_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert not any(marker in source for marker in forbidden), relative_path


def test_legacy_inventory_is_explicitly_read_only() -> None:
    inventory = json.loads(
        (ROOT / "registry/knot/legacy_read_only_v2.json").read_text(encoding="utf-8")
    )
    assert inventory["status"] == "legacy_read_only"
    assert inventory["active_runtime"] is False
    assert inventory["writes_enabled"] is False
    assert inventory["retired_rpc_prefixes"] == ["darwinian.knot_"]
    assert inventory["public_tombstones"] == [
        "mosaic/scorecard/knot_v2.py",
        "mosaic/autoresearch/domain_evaluator.py",
        "mosaic/autoresearch/domain_metrics.py",
    ]
    assert inventory["public_fail_closed_legacy_ports"] == [
        "mosaic/bridge/handlers/darwinian.py",
        "mosaic/bridge/tool_capabilities.py",
    ]


def test_public_legacy_module_rejects_direct_writes() -> None:
    with pytest.raises(RuntimeError, match="legacy_knot_protocol_read_only"):
        knot_v2.append_knot_research_score_record(None)


def test_scorecard_legacy_writer_ports_fail_closed(tmp_path: Path) -> None:
    store = ScorecardStore(db_path=tmp_path / "scorecard.db")
    probes: list[Callable[[], object]] = [
        lambda: store.publish_knot_nomination_audit(),
        lambda: store.preregister_knot_pair_assignment(),
        lambda: store.publish_knot_research_schedule(),
        lambda: store.freeze_knot_pair_input(),
        lambda: store.append_knot_research_score_record(),
        lambda: store.append_knot_sector_inference_cost_audit(),
        lambda: store.append_knot_control_dependency_result(),
        lambda: store.append_knot_cio_dependency_blocked_audit(),
        lambda: store.finalize_knot_pair(),
        lambda: store.publish_knot_promotion_revision(),
        lambda: store.publish_knot_promotion_batch(),
        lambda: store.publish_knot_rollback_revision(),
        lambda: store.register_knot_research_track(
            knot_nomination_audit_id="legacy",
            production_variant_roster_revision_id="legacy",
            target_evaluation_track_key_hash="legacy",
            mutation_definition={},
            created_at="2026-08-04T00:00:00Z",
        ),
        lambda: store.append_knot_pair_side_execution_result(
            knot_pair_id="legacy",
            pair_side="CHAMPION",
            graph_run_id="legacy",
            run_id="legacy",
            result_disposition="AGENT_FAILURE",
            recorded_at="2026-08-04T00:00:00Z",
        ),
        lambda: store.append_knot_cio_proposal_execution_result(
            knot_pair_id="legacy",
            pair_side="CHAMPION",
            graph_run_id="legacy",
            run_id="legacy",
            result_disposition="ACCEPTED",
            recorded_at="2026-08-04T00:00:00Z",
            validated_output={},
            strict_receipt_verifier=lambda _value: None,
        ),
    ]
    for probe in probes:
        with pytest.raises(RuntimeError, match="legacy_knot_protocol_read_only"):
            probe()


def test_capability_legacy_writer_ports_fail_closed(tmp_path: Path) -> None:
    store = AgentToolCapabilityStore(
        tmp_path / "capabilities.db",
        signing_key=b"test-signing-key-32-bytes-long!!!",
        signing_key_id="test-key-v1",
    )
    probes: list[Callable[[], object]] = [
        lambda: store.verify_and_reserve_knot_pair_root(
            pair_binding={},
            champion_envelope={},
            candidate_envelope={},
        ),
        lambda: store.classify_and_reserve_knot_regime(
            knot_research_track_id="legacy",
            research_slot_id="legacy",
            scheduled_sample_id="legacy",
            expected_as_of="2026-08-04",
            source_snapshot={},
        ),
        lambda: store.bind_knot_private_pair(
            pair_root_reservation_id="legacy",
            knot_pair_id="legacy",
            knot_pair_input_hash="legacy",
            sector_inference_budget_contract=None,
        ),
        lambda: store.record_knot_sector_model_usage(
            capability_envelope={},
            usage_report={},
        ),
        lambda: store.mint_knot_sector_inference_usage_receipt(binding={}),
        lambda: store.mint_knot_strict_output_validation_receipt(
            knot_pair_id="legacy",
            pair_side="CHAMPION",
            accepted_output_kind="legacy",
            accepted_output_record={},
            verified_claim_graph={},
            schema_binding={},
            schema_json={},
        ),
    ]
    for probe in probes:
        with pytest.raises(RuntimeError, match="legacy_knot_protocol_read_only"):
            probe()
