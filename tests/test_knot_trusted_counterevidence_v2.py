from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.capability_preservation import (
    build_binding_signal_projection_v1,
    build_claim_comparison_specs_v1,
    build_default_contract_artifacts,
    compare_binding_projection_v1,
    validate_trusted_counterevidence_evaluation_v2,
)


ROOT = Path(__file__).resolve().parents[1]


def _authority_fixture() -> tuple[dict, dict, dict, str, str]:
    artifacts = build_default_contract_artifacts(ROOT)
    coverage = artifacts["knot_tool_coverage_manifest_v2.json"]
    row = coverage["coverage"][0]
    payload = json.dumps(
        {"growth_change": 0.5, "summary": "private prose", "trend": "up"},
        sort_keys=True,
        separators=(",", ":"),
    )
    binding_ref = {
        "binding_id": row["binding_id"],
        "semantic_capability_id": row["semantic_capability_id"],
        "coverage_row_hash": row["coverage_row_hash"],
        "binding_result_fingerprint": "sha256:" + "1" * 64,
    }
    event = {
        "schema_version": "server_tool_result_event_v1",
        "result_event_id": "tool_evt_test",
        "status": "SUCCEEDED",
        "payload_hash": canonical_hash({"text": payload}),
        "binding_refs": [binding_ref],
    }
    return row, event, binding_ref, payload, canonical_hash(event)


def test_v2_coverage_and_audit_track_close_all_192_bindings():
    artifacts = build_default_contract_artifacts(ROOT)
    binding = artifacts["agent_capability_binding_manifest_v1.json"]
    coverage = artifacts["knot_tool_coverage_manifest_v2.json"]
    track = artifacts["knot_audit_capability_track_v2.json"]

    binding_ids = [row["binding_id"] for row in binding["bindings"]]
    coverage_ids = [row["binding_id"] for row in coverage["coverage"]]
    assert len(binding_ids) == len(coverage_ids) == 192
    assert len(set(coverage_ids)) == 192
    assert sorted(binding_ids) == coverage_ids
    assert all(
        row["signal_selector_contract_hash"]
        == canonical_hash(row["signal_selector_contract"])
        and row["claim_comparison_spec_contract_hash"]
        == canonical_hash(row["claim_comparison_spec_contract"])
        and row["trusted_comparator_contract_hash"]
        == canonical_hash(row["trusted_comparator_contract"])
        for row in coverage["coverage"]
    )
    assert track["knot_coverage_manifest_v2_hash"] == coverage["manifest_hash"]


def test_capture_time_signal_projection_is_deterministic_and_prose_free():
    row, event, binding_ref, payload, event_hash = _authority_fixture()
    projection = build_binding_signal_projection_v1(
        event=event,
        result_event_hash=event_hash,
        binding_ref=binding_ref,
        payload_text=payload,
        coverage_row=row,
    )

    assert projection["projection_status"] == "PROJECTED"
    assert projection == build_binding_signal_projection_v1(
        event=event,
        result_event_hash=event_hash,
        binding_ref=binding_ref,
        payload_text=payload,
        coverage_row=row,
    )
    assert {signal["dimension"] for signal in projection["signals"]} == {
        f"{row['semantic_capability_id']}:growth_change",
        f"{row['semantic_capability_id']}:trend",
    }
    assert "private prose" not in json.dumps(projection, sort_keys=True)


def test_v1_signal_projection_rejects_unsupported_v2_events():
    row, event, binding_ref, payload, _ = _authority_fixture()
    event["schema_version"] = "server_tool_result_event_v2"

    with pytest.raises(ValueError, match="not projection eligible"):
        build_binding_signal_projection_v1(
            event=event,
            result_event_hash=canonical_hash(event),
            binding_ref=binding_ref,
            payload_text=payload,
            coverage_row=row,
        )


def test_unstructured_payload_is_explicit_unknown():
    row, event, binding_ref, _, _ = _authority_fixture()
    payload = json.dumps({"summary": "no structured direction"})
    event["payload_hash"] = canonical_hash({"text": payload})
    event_hash = canonical_hash(event)

    projection = build_binding_signal_projection_v1(
        event=event,
        result_event_hash=event_hash,
        binding_ref=binding_ref,
        payload_text=payload,
        coverage_row=row,
    )

    assert projection["projection_status"] == "UNKNOWN"
    assert projection["signals"] == []
    assert projection["unknown_reason"] == "NO_TRUSTED_SIGNAL"


def test_claim_spec_and_counterevidence_are_server_derived_on_one_dimension():
    row, event, binding_ref, payload, event_hash = _authority_fixture()
    projection = build_binding_signal_projection_v1(
        event=event,
        result_event_hash=event_hash,
        binding_ref=binding_ref,
        payload_text=payload,
        coverage_row=row,
    )
    accepted_output = {
        "claims": [
            {
                "claim_id": "claim:1",
                "statement": "free text is not evaluated",
                "structured_conclusion": {"trend": "down"},
            }
        ]
    }
    specs = build_claim_comparison_specs_v1(
        accepted_output=accepted_output,
        accepted_output_hash=canonical_hash(accepted_output),
        coverage_row=row,
    )
    assert len(specs) == 1
    assert specs[0]["spec_status"] == "READY"
    assert specs[0]["dimension"] == f"{row['semantic_capability_id']}:trend"
    assert specs[0]["target_polarity"] == "negative"

    evaluation = compare_binding_projection_v1(
        projection=projection,
        claim_spec=specs[0],
    )
    assert evaluation["evaluation_status"] == "EVALUATED"
    assert evaluation["resolution_code"] == "reversed"
    assert evaluation["counterevidence_available"] is True
    assert evaluation["counterevidence_handled"] is True
    validate_trusted_counterevidence_evaluation_v2(
        evaluation,
        projection=projection,
        claim_spec=specs[0],
    )

    forged = copy.deepcopy(evaluation)
    forged["comparison_value"] = 1.0
    with pytest.raises(ValueError, match="shape"):
        validate_trusted_counterevidence_evaluation_v2(
            forged,
            projection=projection,
            claim_spec=specs[0],
        )


def test_dimension_unknown_abstains_instead_of_guessing():
    row, event, binding_ref, payload, event_hash = _authority_fixture()
    projection = build_binding_signal_projection_v1(
        event=event,
        result_event_hash=event_hash,
        binding_ref=binding_ref,
        payload_text=payload,
        coverage_row=row,
    )
    accepted_output = {
        "claims": [
            {
                "claim_id": "claim:unknown",
                "statement": "unsupported prose",
                "structured_conclusion": {"confidence": 0.99},
            }
        ]
    }
    spec = build_claim_comparison_specs_v1(
        accepted_output=accepted_output,
        accepted_output_hash=canonical_hash(accepted_output),
        coverage_row=row,
    )[0]
    evaluation = compare_binding_projection_v1(
        projection=projection,
        claim_spec=spec,
    )

    assert spec["spec_status"] == "UNKNOWN"
    assert evaluation["evaluation_status"] == "UNKNOWN"
    assert evaluation["resolution_code"] == "abstained"
    assert evaluation["counterevidence_available"] is False
    assert evaluation["counterevidence_handled"] is False
