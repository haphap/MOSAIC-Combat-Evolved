from __future__ import annotations

import copy

import pytest

from mosaic.scorecard.accepted_output_contracts import _validate_knot_capture_v2
from mosaic.scorecard.canonical_json import canonical_hash


def _hash(char: str) -> str:
    return f"sha256:{char * 64}"


def _record() -> dict[str, object]:
    claim_body = {
        "claim_id": "claim:1",
        "evidence_ids": ["evidence:1"],
        "structured_conclusion": {"direction": "supportive"},
    }
    event = {
        "result_event_id": "tool_evt_accepted",
        "result_event_hash": _hash("1"),
        "result_authority_type": "SNAPSHOT_BUILD",
        "result_authority_hash": _hash("2"),
        "evidence_ids": ["evidence:1"],
        "binding_result_refs": [
            {
                "binding_id": f"binding:{'3' * 64}",
                "binding_result_fingerprint": _hash("4"),
            }
        ],
    }
    capture_body = {
        "schema_version": "accepted_knot_capture_v2",
        "accepted_lineage_evaluator_version": "accepted_claim_lineage_v3",
        "eligibility": "ELIGIBLE",
        "ineligibility_reasons": [],
        "accepted_claim_graph_hash": _hash("5"),
        "tool_environment_hash": _hash("6"),
        "execution_behavior_release_hash": _hash("7"),
        "capability_bundle_hash": _hash("8"),
        "knot_coverage_manifest_v2_hash": _hash("9"),
        "knot_audit_capability_track_v2_hash": _hash("a"),
        "result_event_refs": [event],
        "claim_specs": [
            {**claim_body, "claim_spec_hash": canonical_hash(claim_body)}
        ],
    }
    return {
        "accepted_output_id": "accepted:1",
        "knot_capture_v2": {
            **capture_body,
            "capture_hash": canonical_hash(capture_body),
        },
        "output": {
            "claim_graph_lineage": {
                "evidence": [
                    {
                        "evidence_id": "evidence:1",
                        "source_fingerprint": _hash("b"),
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
                        "statement": "private prose stays outside the KNOT capture",
                        "structured_conclusion": {"direction": "supportive"},
                    }
                ]
            },
        },
    }


def test_validates_public_safe_capture_time_knot_lineage() -> None:
    record = _record()

    _validate_knot_capture_v2(record)

    capture = record["knot_capture_v2"]
    assert isinstance(capture, dict)
    assert "private prose" not in str(capture)


def test_rejects_caller_injected_counterevidence_and_hash_tampering() -> None:
    record = _record()
    capture = record["knot_capture_v2"]
    assert isinstance(capture, dict)
    claim_specs = capture["claim_specs"]
    assert isinstance(claim_specs, list)
    forged = copy.deepcopy(record)
    forged_capture = forged["knot_capture_v2"]
    assert isinstance(forged_capture, dict)
    forged_specs = forged_capture["claim_specs"]
    assert isinstance(forged_specs, list)
    forged_spec = forged_specs[0]
    assert isinstance(forged_spec, dict)
    forged_spec["comparison_value"] = "supportive"
    body = {key: value for key, value in forged_capture.items() if key != "capture_hash"}
    forged_capture["capture_hash"] = canonical_hash(body)

    with pytest.raises(ValueError, match=r"claim_specs\[0\] fields"):
        _validate_knot_capture_v2(forged)

    tampered = _record()
    tampered_capture = tampered["knot_capture_v2"]
    assert isinstance(tampered_capture, dict)
    tampered_capture["tool_environment_hash"] = _hash("f")
    with pytest.raises(ValueError, match="capture hash"):
        _validate_knot_capture_v2(tampered)
