from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.dataflows.outcome_runtime_inputs import (
    EVENT_COVERAGE_SCHEMA_VERSION,
    OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
    OUTCOME_PROJECTION_SCHEMA_VERSION,
    expected_qualification_predicate_version,
    load_evaluation_opportunity_projection,
    load_realized_outcome_projection,
    load_verified_event_coverage,
    validate_evaluation_opportunity_members,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import (
    OUTCOME_CONTRACTS,
    OUTCOME_METRIC_SCHEMAS_HASH,
    OUTCOME_PROJECTION_SCHEMA_HASH,
    OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
    OUTCOME_REGISTRY_HASH,
)
from mosaic.scorecard.outcome_source_receipts import outcome_source_authority_pins


AS_OF = "2026-07-17T15:00:00+08:00"


def _write_hashed(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {**payload, "snapshot_hash": canonical_hash(payload)}
    path.write_text(json.dumps(record), encoding="utf-8")


def test_realized_outcome_schema_uses_no_conditional_keywords() -> None:
    schema = json.loads(
        Path("schemas/realized_outcome_projection_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert not {"if", "then", "else"} & keys(schema)


def _event_coverage() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        schedule = contract["sample_schedule"]
        if schedule["kind"] != "EVENT_TRIGGERED":
            continue
        result[agent_id] = {
            "coverage_status": "COMPLETE",
            "coverage_evidence_ids": [f"coverage:{agent_id}"],
            "event_registry_version": schedule["event_registry_version"],
            "event_priority_version": schedule["event_priority_version"],
            "candidates": [],
        }
    return result


def test_event_coverage_requires_hashed_exact_pit_roster(tmp_path: Path) -> None:
    root = tmp_path / "outcome-runtime"
    payload = {
        "schema_version": EVENT_COVERAGE_SCHEMA_VERSION,
        "as_of": AS_OF,
        "generated_at": "2026-07-17T14:59:00+08:00",
        "pit_status": "VERIFIED",
        "event_coverage": _event_coverage(),
    }
    path = root / "2026-07-17" / "event_coverage.json"
    _write_hashed(path, payload)
    assert load_verified_event_coverage(AS_OF, root=root) == payload["event_coverage"]

    corrupted = json.loads(path.read_text(encoding="utf-8"))
    corrupted["event_coverage"].pop(next(iter(corrupted["event_coverage"])))
    corrupted_without_hash = {
        key: value for key, value in corrupted.items() if key != "snapshot_hash"
    }
    corrupted["snapshot_hash"] = canonical_hash(corrupted_without_hash)
    path.write_text(json.dumps(corrupted), encoding="utf-8")
    with pytest.raises(ValueError, match="exact event-triggered"):
        load_verified_event_coverage(AS_OF, root=root)


@pytest.mark.parametrize("status", ["AVAILABLE", "GENERATION_FAILURE"])
def test_opportunity_projection_closes_required_sources_and_status(
    tmp_path: Path,
    status: str,
) -> None:
    root = tmp_path / "outcome-runtime"
    agent_id = "us_economy"
    source_evidence = {
        source_id: [f"evidence:{index}:{source_id}"]
        for index, source_id in enumerate(OUTCOME_CONTRACTS[agent_id]["required_source_ids"])
    }
    payload = {
        "schema_version": OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
        "agent_id": agent_id,
        "as_of": AS_OF,
        "generated_at": "2026-07-17T14:58:00+08:00",
        "pit_status": "VERIFIED",
        "projection_status": status,
        "qualification_predicate_version": expected_qualification_predicate_version(
            agent_id
        ),
        "member_refs": [{"event_id": "us-cpi-2026-06"}] if status == "AVAILABLE" else [],
        "source_evidence_by_required_source_id": source_evidence,
        "error_codes": [] if status == "AVAILABLE" else ["REQUIRED_DATA_UNAVAILABLE"],
    }
    _write_hashed(
        root / "2026-07-17" / "opportunities" / f"{agent_id}.json",
        payload,
    )
    assert load_evaluation_opportunity_projection(
        AS_OF,
        agent_id,
        root=root,
    )["projection_status"] == status


def test_missing_runtime_input_is_not_reinterpreted_as_no_event(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="unavailable"):
        load_verified_event_coverage(AS_OF, root=tmp_path)


def test_opportunity_member_domain_and_predicate_are_registry_owned(
    tmp_path: Path,
) -> None:
    root = tmp_path / "outcome-runtime"
    agent_id = "china"
    source_evidence = {
        source_id: [f"evidence:{index}:{source_id}"]
        for index, source_id in enumerate(OUTCOME_CONTRACTS[agent_id]["required_source_ids"])
    }
    payload = {
        "schema_version": OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
        "agent_id": agent_id,
        "as_of": AS_OF,
        "generated_at": "2026-07-17T14:58:00+08:00",
        "pit_status": "VERIFIED",
        "projection_status": "AVAILABLE",
        "qualification_predicate_version": expected_qualification_predicate_version(
            agent_id
        ),
        "member_refs": [{"forged": "cn-cpi-2026-06"}],
        "source_evidence_by_required_source_id": source_evidence,
        "error_codes": [],
    }
    path = root / "2026-07-17" / "opportunities" / f"{agent_id}.json"
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="must contain exactly 'event_id'"):
        load_evaluation_opportunity_projection(AS_OF, agent_id, root=root)

    payload["member_refs"] = [{"event_id": "cn-cpi-2026-06"}]
    payload["qualification_predicate_version"] = "caller-selected-predicate"
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="qualification predicate"):
        load_evaluation_opportunity_projection(AS_OF, agent_id, root=root)


@pytest.mark.parametrize(
    "agent_id",
    [
        "druckenmiller",
        "munger",
        "burry",
        "ackman",
        "alpha_discovery",
        "cro",
        "autonomous_execution",
        "cio",
    ],
)
def test_deferred_pre_run_projection_is_readiness_only(
    tmp_path: Path,
    agent_id: str,
) -> None:
    root = tmp_path / "outcome-runtime"
    contract = OUTCOME_CONTRACTS[agent_id]
    payload = {
        "schema_version": OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
        "agent_id": agent_id,
        "as_of": AS_OF,
        "generated_at": "2026-07-17T14:58:00+08:00",
        "pit_status": "VERIFIED",
        "projection_status": "AVAILABLE",
        "qualification_predicate_version": expected_qualification_predicate_version(
            agent_id
        ),
        "member_refs": [{"forged": "pre-run-member"}],
        "source_evidence_by_required_source_id": {
            source_id: [f"evidence:{source_id}"]
            for source_id in contract["required_source_ids"]
        },
        "error_codes": [],
    }
    path = root / "2026-07-17" / "opportunities" / f"{agent_id}.json"
    _write_hashed(path, payload)

    with pytest.raises(ValueError, match="readiness evidence only"):
        load_evaluation_opportunity_projection(AS_OF, agent_id, root=root)

    payload["member_refs"] = []
    _write_hashed(path, payload)
    assert load_evaluation_opportunity_projection(
        AS_OF, agent_id, root=root
    )["member_refs"] == []

    payload["qualification_predicate_version"] = "caller-selected-predicate"
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="qualification predicate"):
        load_evaluation_opportunity_projection(AS_OF, agent_id, root=root)


@pytest.mark.parametrize(
    "agent_id",
    [
        "druckenmiller",
        "munger",
        "burry",
        "ackman",
        "cro",
        "alpha_discovery",
        "autonomous_execution",
    ],
)
def test_final_empty_opportunity_remains_allowed_for_existing_roster(
    agent_id: str,
) -> None:
    assert validate_evaluation_opportunity_members(
        agent_id,
        expected_qualification_predicate_version(agent_id),
        [],
    ) == []


def test_cio_final_opportunity_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="cio cannot use an empty"):
        validate_evaluation_opportunity_members(
            "cio",
            expected_qualification_predicate_version("cio"),
            [],
        )


@pytest.mark.parametrize(
    ("agent_id", "member"),
    [
        (
            "energy",
            {
                "subindustry_id": "oil_gas",
                "security_shortlist_id": "sector-shortlist:oil-gas",
                "security_shortlist_hash": "sha256:" + "1" * 64,
                "security_ts_codes": ["600028.SH", "601857.SH"],
            },
        ),
        (
            "relationship_mapper",
            {
                "edge_candidate_id": "relationship-edge:1",
                "materiality_weight": 2.5,
            },
        ),
        (
            "munger",
            {"candidate_ref": "layer2-candidate:1", "ts_code": "600519.SH"},
        ),
        ("china", {"event_id": "cn-cpi-2026-06"}),
        (
            "cro",
            {
                "risk_candidate_id": "risk-candidate:1",
                "ts_code": "600000.SH",
                "proposed_target_weight": 0.1,
            },
        ),
        (
            "alpha_discovery",
            {"candidate_ref": "alpha-candidate:1", "ts_code": "600001.SH"},
        ),
        (
            "autonomous_execution",
            {
                "order_intent_id": "order-intent:1",
                "ts_code": "600002.SH",
                "action": "BUY",
                "requested_delta_weight": 0.05,
            },
        ),
        (
            "cio",
            {
                "controlled_target_set_id": "controlled-targets:1",
                "baseline_cash_weight": 0.8,
                "positions": [
                    {
                        "position_ref": "position:1",
                        "ts_code": "600003.SH",
                        "baseline_weight": 0.2,
                        "controlled_target_weight": 0.1,
                    }
                ],
            },
        ),
    ],
)
def test_opportunity_member_authority_uses_role_exact_shapes(
    agent_id: str,
    member: dict,
) -> None:
    assert validate_evaluation_opportunity_members(
        agent_id,
        expected_qualification_predicate_version(agent_id),
        [member],
    ) == [member]


@pytest.mark.parametrize(
    ("agent_id", "member", "error"),
    [
        ("energy", {"subindustry_id": "oil_gas"}, "must contain exactly"),
        (
            "energy",
            {
                "subindustry_id": "oil_gas",
                "security_shortlist_id": "sector-shortlist:oil-gas",
                "security_shortlist_hash": "not-a-hash",
                "security_ts_codes": [],
            },
            "must be lowercase sha256",
        ),
        (
            "energy",
            {
                "subindustry_id": "oil_gas",
                "security_shortlist_id": "sector-shortlist:oil-gas",
                "security_shortlist_hash": "sha256:" + "1" * 64,
                "security_ts_codes": ["600028.SH", "600028.SH"],
            },
            "security_ts_codes must be unique",
        ),
        (
            "relationship_mapper",
            {"edge_candidate_id": "relationship-edge:1", "materiality_weight": 0},
            "finite and positive",
        ),
        (
            "munger",
            {"candidate_ref": "layer2-candidate:1"},
            "must contain exactly",
        ),
        (
            "cro",
            {"risk_candidate_id": "risk:1", "ts_code": "600000.SH"},
            "must contain exactly",
        ),
        (
            "alpha_discovery",
            {"candidate_ref": "alpha:1", "ts_code": "NOT_A_TICKER"},
            "canonical A-share code",
        ),
        (
            "autonomous_execution",
            {
                "order_intent_id": "order:1",
                "ts_code": "600001.SH",
                "action": "BUY",
                "requested_delta_weight": -0.1,
            },
            "action/requested_delta_weight mismatch",
        ),
        (
            "cio",
            {
                "controlled_target_set_id": "controlled:1",
                "baseline_cash_weight": 0.9,
                "positions": [
                    {
                        "position_ref": "position:1",
                        "ts_code": "600002.SH",
                        "baseline_weight": 0.2,
                        "controlled_target_weight": 0.1,
                    }
                ],
            },
            "baseline weights must sum to one",
        ),
    ],
)
def test_opportunity_member_authority_rejects_incomplete_or_invalid_members(
    agent_id: str,
    member: dict,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        validate_evaluation_opportunity_members(
            agent_id,
            expected_qualification_predicate_version(agent_id),
            [member],
        )


@pytest.mark.parametrize(
    ("agent_id", "members"),
    [
        (
            "relationship_mapper",
            [
                {"edge_candidate_id": "edge:1", "materiality_weight": 1.0},
                {"edge_candidate_id": "edge:1", "materiality_weight": 2.0},
            ],
        ),
        (
            "munger",
            [
                {"candidate_ref": "candidate:1", "ts_code": "600001.SH"},
                {"candidate_ref": "candidate:1", "ts_code": "600002.SH"},
            ],
        ),
    ],
)
def test_opportunity_member_authority_rejects_duplicate_primary_identities(
    agent_id: str,
    members: list[dict],
) -> None:
    with pytest.raises(ValueError, match="identities must be unique"):
        validate_evaluation_opportunity_members(
            agent_id,
            expected_qualification_predicate_version(agent_id),
            members,
        )


def test_realized_outcome_projection_binds_owner_slot_due_and_pit_cutoff(
    tmp_path: Path,
) -> None:
    root = tmp_path / "outcome-runtime"
    agent_id = "china"
    contract = OUTCOME_CONTRACTS[agent_id]
    due_at = "2026-07-17T15:00:00+08:00"
    sample_id = "sample:china:2026-07-10"
    source_pins = outcome_source_authority_pins()
    identities = {
        "scheduled_sample_id": sample_id,
        "outcome_schedule_slot_id": "slot:china",
        "outcome_schedule_slot_hash": "sha256:" + "a" * 64,
        "evaluation_opportunity_set_id": "opportunity:china",
        "evaluation_opportunity_set_hash": "sha256:" + "b" * 64,
        "accepted_output_id": "accepted:china",
        "accepted_output_hash": "sha256:" + "e" * 64,
        "track_key_hash": "sha256:" + "c" * 64,
        "agent_id": agent_id,
        "opportunity_as_of": "2026-07-10T15:00:00+08:00",
        "outcome_due_at": due_at,
    }
    payload = {
        "schema_version": OUTCOME_PROJECTION_SCHEMA_VERSION,
        **identities,
        "metric_family": contract["metric_family"],
        "metric_schema_id": contract["metric_schema_id"],
        "realized_metric_schema_id": contract["realized_metric_schema_id"],
        "outcome_registry_hash": OUTCOME_REGISTRY_HASH,
        "metric_schemas_hash": OUTCOME_METRIC_SCHEMAS_HASH,
        "realized_metric_schemas_hash": OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
        "outcome_projection_schema_hash": OUTCOME_PROJECTION_SCHEMA_HASH,
        "source_authority_registry_hash": source_pins[
            "authority_registry_hash"
        ],
        "source_authority_registry_schema_hash": source_pins[
            "authority_registry_schema_hash"
        ],
        "source_receipt_schema_hash": source_pins["receipt_schema_hash"],
        "source_batch_schema_hash": source_pins["batch_schema_hash"],
        "generated_at": due_at,
        "pit_status": "VERIFIED",
        "source_batch_id": "outcome-source-batch:test",
        "source_batch_hash": "sha256:" + "f" * 64,
    }
    path = root / due_at[:10] / "realized_outcomes" / f"{sample_id}.json"
    _write_hashed(path, payload)
    assert load_realized_outcome_projection(
        **identities,
        cutoff_at=due_at,
        root=root,
    )["source_batch_id"] == "outcome-source-batch:test"

    payload["realized_metrics"] = {"role_path_metric": 0.1}
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="realized_metrics.*unexpected"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )

    payload.pop("realized_metrics")
    payload["raw_metrics"] = {
        "direction_sign": -1,
        "confidence": 0.01,
        "forecast_loss": 999,
    }
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="raw_metrics.*unexpected"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )

    payload.pop("raw_metrics")
    payload["normalization_reference"] = {
        "scale": 1e-12,
        "normalization_reference_hash": canonical_hash({"scale": 1e-12}),
    }
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="normalization_reference.*unexpected"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )

    payload.pop("normalization_reference")
    original_registry_hash = payload["outcome_registry_hash"]
    payload["outcome_registry_hash"] = "sha256:" + "0" * 64
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="outcome_registry_hash drift"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )
    payload["outcome_registry_hash"] = original_registry_hash

    payload["generated_at"] = "2026-07-17T14:59:59+08:00"
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="due_at <= generated_at"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )

    payload["generated_at"] = due_at
    payload["outcome_schedule_slot_hash"] = "sha256:" + "d" * 64
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="slot_hash drift"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )

    payload["outcome_schedule_slot_hash"] = identities[
        "outcome_schedule_slot_hash"
    ]
    payload["agent_id"] = "cio"
    _write_hashed(path, payload)
    with pytest.raises(ValueError, match="agent_id drift"):
        load_realized_outcome_projection(
            **identities,
            cutoff_at=due_at,
            root=root,
        )
