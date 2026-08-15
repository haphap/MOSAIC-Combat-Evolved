from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.capability_preservation import (
    ACTIVE_TRACK_TAG_FIELDS,
    _execution_release,
    assert_knot_action,
    build_default_contract_artifacts,
    build_knot_capability_use_aggregate,
    canonical_binding_id,
    canonical_tool_environment_hash,
    evaluate_counterevidence,
    is_mature_sample_eligible,
    load_active_capability_fixed_point,
    load_capability_contract_bundle,
    rollout_blockers,
    tool_result_fingerprint,
    validate_accepted_output_track_tags,
    validate_capability_contract_bundle,
    validate_evidence_claim_graph_v2,
    validate_capability_full_bundle,
    validate_knot_capability_use_aggregate,
    validate_preservation_manifest,
    validate_public_safe_projection,
    validate_tool_config_hash,
)
from mosaic.rke.schema_validation import validate_json_schema_artifact


ROOT = Path(__file__).parents[1]
REGISTRY_ROOT = ROOT / "registry" / "prompt_checks" / "capability_preservation"


def _load(name: str) -> dict:
    return json.loads((REGISTRY_ROOT / name).read_text(encoding="utf-8"))


def _bundle() -> dict:
    return load_capability_contract_bundle(ROOT)


def _active_tool_manifest() -> dict:
    return json.loads(
        (ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )


def _binding_body(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "binding_id"}


def _reseal(manifest: dict) -> None:
    body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    manifest["manifest_hash"] = canonical_hash(body)


def test_generated_contract_artifacts_are_current_and_deterministic():
    expected = build_default_contract_artifacts(ROOT)
    assert expected == {name: _load(name) for name in expected}


def test_execution_release_follows_content_addressed_pointer_with_archive_history(
    tmp_path: Path,
):
    archive_root = (
        tmp_path / "registry" / "prompt_checks" / "execution_behavior_releases"
    )
    archive_root.mkdir(parents=True)
    release_id = f"execution-behavior-release:{'1' * 64}"
    body = {
        "schema_version": "execution_behavior_release_manifest_v4",
        "execution_behavior_release_id": release_id,
    }
    release_hash = canonical_hash(body)
    archive_ref = (
        "registry/prompt_checks/execution_behavior_releases/"
        f"{'1' * 64}--{release_hash.removeprefix('sha256:')}.json"
    )
    (tmp_path / archive_ref).write_text(
        json.dumps({**body, "execution_behavior_release_hash": release_hash}),
        encoding="utf-8",
    )
    (archive_root / "historical.json").write_text("{}", encoding="utf-8")
    pointer_path = (
        tmp_path / "registry" / "prompt_checks" / "prompt_release_contract_ref_v2.json"
    )
    pointer = {
        "schema_version": "prompt_release_contract_ref_v2",
        "sources": {
            "execution_behavior_release_archive": {
                "path": archive_ref,
                "release_id": release_id,
                "release_hash": release_hash,
            }
        },
    }
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    assert _execution_release(tmp_path) == (release_id, release_hash)

    pointer["sources"]["execution_behavior_release_archive"]["release_hash"] = (
        "sha256:" + "0" * 64
    )
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(ValueError, match="content-addressed execution release path"):
        _execution_release(tmp_path)


def test_active_capability_fixed_point_uses_validated_v2_authority():
    fixed_point = load_active_capability_fixed_point(ROOT)
    bundle = _bundle()

    assert fixed_point == {
        "execution_behavior_release_hash": bundle["knot_audit_capability_track_v2"][
            "execution_behavior_release_hash"
        ],
        "knot_coverage_manifest_v2_hash": bundle["knot_coverage_manifest_v2"][
            "manifest_hash"
        ],
    }


def test_active_capability_fixed_point_rejects_tampered_v2_track(tmp_path: Path):
    registry = tmp_path / "registry" / "prompt_checks"
    registry.mkdir(parents=True)
    shutil.copytree(REGISTRY_ROOT, registry / "capability_preservation")
    shutil.copy2(
        ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json",
        registry / "agent_tool_contract_manifest_v1.json",
    )
    track_path = (
        registry
        / "capability_preservation"
        / "knot_audit_capability_track_v2.json"
    )
    track = json.loads(track_path.read_text(encoding="utf-8"))
    track["execution_behavior_release_hash"] = "sha256:" + "0" * 64
    track_path.write_text(json.dumps(track), encoding="utf-8")

    with pytest.raises(ValueError, match="fixed-point mismatch"):
        load_active_capability_fixed_point(tmp_path)


def test_migration_golden_freezes_25_agents_26_stages_and_23_capabilities():
    bundle = _bundle()
    golden = bundle["baseline_runtime_manifest"]
    preservation = bundle["preservation_manifest"]

    assert golden["schema_version"] == "runtime_agent_manifest_v2"
    assert golden["runtime_agent_count"] == len(golden["agents"]) == 25
    assert golden["runtime_stage_count"] == sum(
        len(agent["stages"]) for agent in golden["agents"]
    ) == 26
    assert preservation["baseline_commit"] == (
        "b9ab1e444f691fb42e2caba81a345898482f22d8"
    )
    assert preservation["baseline_agent_count"] == 25
    assert preservation["baseline_stage_count"] == 26
    assert preservation["baseline_capability_count"] == 23
    assert len(preservation["capabilities"]) == 23
    assert len({row["semantic_capability_id"] for row in preservation["capabilities"]}) == 23

    dispositions = [row["disposition"] for row in preservation["capabilities"]]
    assert dispositions.count("preserved") == 5
    assert dispositions.count("partial") == 18
    market_breadth = next(
        row
        for row in preservation["capabilities"]
        if row["semantic_capability_id"] == "market_breadth"
    )
    assert market_breadth["disposition"] == "partial"
    assert market_breadth["consumer_closure"] == "open"
    assert market_breadth["current_owners"] == []
    assert market_breadth["replacement_tools"] == []
    assert market_breadth["equivalence_evidence_refs"] == []
    assert set(dispositions) <= {
        "preserved",
        "equivalent",
        "partial",
        "scope_reduction_approved",
        "removed_approved",
        "introduced",
    }
    assert len(preservation["introduced_roles"]) == 6
    assert preservation["introduced_capabilities"]
    assert all(
        row["disposition"] == "introduced"
        for row in preservation["introduced_capabilities"]
    )
    assert len(preservation["output_compatibility_inventory"]) == 25
    assert all(
        row["compatibility"] == "partial"
        and row["consumer_closure"] == "open"
        for row in preservation["output_compatibility_inventory"]
    )


@pytest.mark.parametrize(
    ("schema_name", "artifact_name"),
    [
        (
            "agent_capability_preservation_manifest_v1.schema.json",
            "agent_capability_preservation_manifest_v1.json",
        ),
        (
            "agent_capability_binding_manifest_v1.schema.json",
            "agent_capability_binding_manifest_v1.json",
        ),
        (
            "staged_agent_tool_contract_manifest_v2.schema.json",
            "staged_agent_tool_contract_manifest_v2.json",
        ),
        ("tool_environment_manifest_v1.schema.json", "tool_environment_manifest_v1.json"),
        (
            "knot_tool_coverage_manifest_v1.schema.json",
            "knot_tool_coverage_manifest_v1.json",
        ),
        (
            "accepted_output_capability_track_v1.schema.json",
            "accepted_output_capability_track_v1.json",
        ),
    ],
)
def test_public_manifests_validate_against_their_json_schemas(
    schema_name: str, artifact_name: str
):
    record = validate_json_schema_artifact(
        root=ROOT,
        schema_path=f"schemas/{schema_name}",
        artifact_path=(
            "registry/prompt_checks/capability_preservation/" + artifact_name
        ),
        artifact_kind="json",
    )
    assert record.accepted, record.failures


def test_partial_and_unapproved_reductions_block_rollout():
    manifest = copy.deepcopy(_bundle()["preservation_manifest"])
    blockers = rollout_blockers(manifest)
    assert len(blockers) == 43
    assert len([code for code in blockers if code.startswith("capability_partial:")]) == 18
    assert len([code for code in blockers if code.startswith("output_partial:")]) == 25

    row = next(item for item in manifest["capabilities"] if item["disposition"] == "partial")
    row["disposition"] = "scope_reduction_approved"
    _reseal(manifest)
    with pytest.raises(ValueError, match="approval"):
        validate_preservation_manifest(manifest)

    row["approval_record"] = {
        "decision_id": "decision:scope:001",
        "actor": "product-owner",
        "decided_at": "2026-08-08T09:00:00+00:00",
        "lost_domain": ["bounded-example-domain"],
        "consumer_closure": "open",
        "rollback_ref": "rollback:scope:001",
        "pi_review_ref": "pi-review:scope:001",
    }
    _reseal(manifest)
    with pytest.raises(ValueError, match="consumer closure"):
        validate_preservation_manifest(manifest)

    row["approval_record"]["consumer_closure"] = "closed"
    _reseal(manifest)
    validate_preservation_manifest(manifest)


def test_binding_and_knot_coverage_exactly_close_over_current_tool_surface():
    artifacts = build_default_contract_artifacts(ROOT)
    route_manifest = json.loads(
        (ROOT / "registry/data_sources/agent_data_route_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    composite_route = next(
        row
        for row in route_manifest["routes"]
        if row["route_id"] == "composite.cn_rates"
    )
    curve_rows = [
        row
        for row in artifacts["agent_capability_binding_manifest_v1.json"]["bindings"]
        if row["tool_id"] == "get_yield_curve_cn"
    ]
    assert {
        (row["agent_id"], row["stage"], tuple(row["source_route_ids"]))
        for row in curve_rows
    } == {
        ("financials", "financials", ("composite.cn_rates",)),
        ("druckenmiller", "druckenmiller", ("composite.cn_rates",)),
    }
    assert {row["route_contract_hash"] for row in curve_rows} == {
        canonical_hash({"routes": [composite_route]})
    }
    bundle = _bundle()
    current = _active_tool_manifest()
    validate_capability_contract_bundle(bundle, current_tool_manifest=current)

    bindings = bundle["binding_manifest"]["bindings"]
    staged_tools = bundle["staged_tool_contract_manifest"]["tools"]
    coverage = bundle["knot_coverage_manifest"]["coverage"]
    binding_ids = [row["binding_id"] for row in bindings]
    assert len(binding_ids) == len(set(binding_ids))
    assert set(binding_ids) == {row["binding_id"] for row in coverage}
    assert all(row["binding_id"] == canonical_binding_id(_binding_body(row)) for row in bindings)

    active_surface = {
        (agent["agent_id"], stage, tool)
        for agent in current["agents"]
        for stage in agent["execution_stages"]
        for tool in agent["allowed_tools"]
    }
    bound_surface = {
        (row["agent_id"], row["stage"], row["tool_id"]) for row in bindings
    }
    assert active_surface == bound_surface
    assert active_surface == {
        (row["agent_id"], row["stage"], row["tool_id"])
        for row in staged_tools
    }
    assert all(row["source_route_ids"] for row in bindings)
    assert all(row["source_route_ids"] for row in staged_tools)
    assert {
        binding_id
        for row in staged_tools
        for binding_id in row["capability_binding_ids"]
    } == set(binding_ids)


def test_composite_and_multi_binding_semantics_are_not_collapsed_to_tool_count():
    bindings = _bundle()["binding_manifest"]["bindings"]
    semiconductor = {
        row["semantic_capability_id"]
        for row in bindings
        if row["agent_id"] == "semiconductor"
        and row["tool_id"] == "get_sector_research_snapshot"
    }
    assert {
        "stock_data",
        "technical_indicators",
        "income_statement",
        "cashflow_statement",
        "fundamentals",
    } <= semiconductor

    rates_bindings = [
        row for row in bindings if row["semantic_capability_id"] == "rates_credit"
    ]
    assert {row["tool_id"] for row in rates_bindings} == {
        "get_central_bank_snapshot",
        "get_us_financial_conditions_snapshot",
    }


def test_five_way_drift_and_missing_duplicate_or_orphan_rows_fail_closed():
    bundle = _bundle()
    current = _active_tool_manifest()

    missing = copy.deepcopy(bundle)
    missing["knot_coverage_manifest"]["coverage"].pop()
    _reseal(missing["knot_coverage_manifest"])
    with pytest.raises(ValueError, match="KNOT coverage exact closure"):
        validate_capability_contract_bundle(missing, current_tool_manifest=current)

    duplicate = copy.deepcopy(bundle)
    duplicate["binding_manifest"]["bindings"].append(
        copy.deepcopy(duplicate["binding_manifest"]["bindings"][0])
    )
    _reseal(duplicate["binding_manifest"])
    with pytest.raises(ValueError, match="duplicate binding"):
        validate_capability_contract_bundle(duplicate, current_tool_manifest=current)

    orphan = copy.deepcopy(bundle)
    orphan_row = orphan["binding_manifest"]["bindings"][0]
    orphan_row["semantic_capability_id"] = "unknown_semantic_capability"
    orphan_row["binding_id"] = canonical_binding_id(_binding_body(orphan_row))
    _reseal(orphan["binding_manifest"])
    with pytest.raises(ValueError, match="orphan semantic"):
        validate_capability_contract_bundle(orphan, current_tool_manifest=current)

    drift = copy.deepcopy(current)
    drift["agents"][0]["allowed_tools"] = ["get_us_macro_snapshot"]
    with pytest.raises(ValueError, match="active tool surface"):
        validate_capability_contract_bundle(bundle, current_tool_manifest=drift)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("argument_schema_hash", "sha256:" + "1" * 64),
        ("route_contract_hash", "sha256:" + "2" * 64),
        ("semantic_capability_id", "eu_macro"),
        ("output_semantics_hash", "sha256:" + "3" * 64),
    ],
)
def test_binding_argument_route_capability_and_output_drift_fail_closed(
    field: str, value: str
):
    bundle = copy.deepcopy(_bundle())
    current = _active_tool_manifest()
    row = bundle["binding_manifest"]["bindings"][0]
    row[field] = value
    row["binding_id"] = canonical_binding_id(_binding_body(row))
    _reseal(bundle["binding_manifest"])
    with pytest.raises(ValueError, match="binding whitelist/argument/route/capability"):
        validate_capability_contract_bundle(bundle, current_tool_manifest=current)


def test_staged_route_query_contract_and_consumer_drift_fail_closed():
    current = _active_tool_manifest()

    staged_drift = copy.deepcopy(_bundle())
    staged_drift["staged_tool_contract_manifest"]["tools"][0][
        "route_contract_hash"
    ] = "sha256:" + "4" * 64
    _reseal(staged_drift["staged_tool_contract_manifest"])
    with pytest.raises(ValueError, match="staged agent tool/route/query"):
        validate_capability_contract_bundle(staged_drift, current_tool_manifest=current)

    consumer_drift = copy.deepcopy(_bundle())
    inventory = consumer_drift["preservation_manifest"][
        "output_compatibility_inventory"
    ][0]
    owner = inventory["current_owners"][0]
    inventory["current_output_schema_fields_by_owner"][owner].append("forged_field")
    _reseal(consumer_drift["preservation_manifest"])
    with pytest.raises(ValueError, match="output consumer inventory current runtime drift"):
        validate_capability_contract_bundle(consumer_drift, current_tool_manifest=current)


def test_tool_config_hash_has_one_canonical_environment_authority():
    environment = copy.deepcopy(_bundle()["tool_environment_manifest"])
    expected = canonical_tool_environment_hash(environment)
    validate_tool_config_hash(expected, environment)
    with pytest.raises(ValueError, match="toolConfigHash"):
        validate_tool_config_hash("sha256:" + "0" * 64, environment)

    changed = copy.deepcopy(environment)
    changed["environments"][0]["privacy_contract_hash"] = "sha256:" + "1" * 64
    assert canonical_tool_environment_hash(changed) != expected


def test_capture_time_track_tags_are_strict_and_legacy_is_read_only():
    bundle = _bundle()
    tags = bundle["accepted_output_capability_track"]
    assert tags["schema_version"] == "accepted_output_capability_track_v1"
    assert tags["tool_environment_hash"] == canonical_tool_environment_hash(
        bundle["tool_environment_manifest"]
    )
    assert tags["capability_binding_manifest_hash"] == bundle["binding_manifest"][
        "manifest_hash"
    ]
    assert tags["knot_coverage_manifest_hash"] == bundle["knot_coverage_manifest"][
        "manifest_hash"
    ]

    validate_accepted_output_track_tags(tags, legacy_read_only=False)
    assert set(tags) == {"schema_version", *ACTIVE_TRACK_TAG_FIELDS}

    missing = dict(tags)
    missing.pop("knot_coverage_manifest_hash")
    with pytest.raises(ValueError, match="capture-time track tags"):
        validate_accepted_output_track_tags(missing, legacy_read_only=False)
    assert validate_accepted_output_track_tags({}, legacy_read_only=True) == "LEGACY_READ_ONLY"

    forged = dict(tags)
    forged["capability_bundle_hash"] = "sha256:" + "2" * 64
    with pytest.raises(ValueError, match="capability bundle hash"):
        validate_accepted_output_track_tags(forged, legacy_read_only=False)


def test_active_release_vnext_binds_the_complete_fixed_point():
    release = {
        "schema_version": "capability_full_bundle_v1",
        "prompt_hash": "sha256:" + "1" * 64,
        "execution_behavior_release_hash": "sha256:" + "2" * 64,
        "production_variant_roster_hash": "sha256:" + "3" * 64,
        "runtime_agent_manifest_hash": "sha256:" + "4" * 64,
        "agent_tool_manifest_hash": "sha256:" + "5" * 64,
        "tool_environment_hash": "sha256:" + "6" * 64,
        "capability_binding_manifest_hash": "sha256:" + "7" * 64,
        "knot_coverage_manifest_hash": "sha256:" + "8" * 64,
        "knot_audit_capability_track_hash": "sha256:" + "a" * 64,
        "private_companion_pin_hash": "sha256:" + "9" * 64,
    }
    body = dict(release)
    release["full_bundle_hash"] = canonical_hash(body)
    validate_capability_full_bundle(release)

    for field in (
        "tool_environment_hash",
        "capability_binding_manifest_hash",
        "knot_coverage_manifest_hash",
        "private_companion_pin_hash",
    ):
        invalid = dict(release)
        invalid.pop(field)
        with pytest.raises(ValueError, match="full-bundle"):
            validate_capability_full_bundle(invalid)


def test_tool_result_fingerprint_and_v2_claim_lineage_are_deterministic():
    bundle = _bundle()
    binding = bundle["binding_manifest"]["bindings"][0]
    capability_track = bundle["accepted_output_capability_track"]
    canonical_args = {"as_of": "2026-08-08"}
    payload = {"close": 10.0}
    build_receipt_hash = "sha256:" + "1" * 64
    fingerprint = tool_result_fingerprint(
        semantic_capability_id=binding["semantic_capability_id"],
        binding_id=binding["binding_id"],
        tool_id=binding["tool_id"],
        canonical_args=canonical_args,
        payload=payload,
        build_receipt_hash=build_receipt_hash,
        tool_environment_hash=capability_track["tool_environment_hash"],
    )
    assert fingerprint == tool_result_fingerprint(
        semantic_capability_id=binding["semantic_capability_id"],
        binding_id=binding["binding_id"],
        tool_id=binding["tool_id"],
        canonical_args={"as_of": "2026-08-08"},
        payload={"close": 10.0},
        build_receipt_hash=build_receipt_hash,
        tool_environment_hash=capability_track["tool_environment_hash"],
    )

    rule = {
        "rule_version": "counterevidence_rule_v1",
        "dimension": "directional_strength",
        "polarity_extractor_version": "signed_numeric_v1",
        "aggregation": "max_strength_v1",
        "comparison": "support_minus_contradiction",
        "threshold": 0.25,
        "unknown_policy": "abstain",
    }
    graph = {
        "schema_version": "evidence_claim_graph_v2",
        "run_id": "run:test",
        "agent_id": binding["agent_id"],
        "stage": binding["stage"],
        "capability_track": copy.deepcopy(capability_track),
        "counterevidence_rule": rule,
        "tool_results": [
            {
                "fingerprint": fingerprint,
                "semantic_capability_id": binding["semantic_capability_id"],
                "binding_id": binding["binding_id"],
                "tool_id": binding["tool_id"],
                "canonical_args_hash": canonical_hash(canonical_args),
                "payload_hash": canonical_hash(payload),
                "build_receipt_hash": build_receipt_hash,
                "tool_environment_hash": capability_track["tool_environment_hash"],
                "status": "SUCCEEDED",
            }
        ],
        "evidence_edges": [
            {
                "edge_id": "edge:1",
                "claim_id": "claim:1",
                "tool_result_fingerprint": fingerprint,
                "relation": "supports",
                "polarity": "supporting",
                "comparison_value": 0.8,
            },
            {
                "edge_id": "edge:2",
                "claim_id": "claim:1",
                "tool_result_fingerprint": fingerprint,
                "relation": "contradicts",
                "polarity": "contradicting",
                "comparison_value": 0.2,
            },
        ],
        "accepted_claims": [
            {
                "claim_id": "claim:1",
                "accepted": True,
                "comparison_witness": {
                    "supporting_edge_ids": ["edge:1"],
                    "contradicting_edge_ids": ["edge:2"],
                    "supporting_value": 0.8,
                    "contradicting_value": 0.2,
                },
                "resolution_code": "rebutted_with_evidence",
            }
        ],
    }
    validate_evidence_claim_graph_v2(graph, bundle=bundle)

    broken = copy.deepcopy(graph)
    broken["tool_results"][0]["fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        validate_evidence_claim_graph_v2(broken, bundle=bundle)

    forged_resolution = copy.deepcopy(graph)
    forged_resolution["accepted_claims"][0]["resolution_code"] = "qualified"
    with pytest.raises(ValueError, match="resolution"):
        validate_evidence_claim_graph_v2(forged_resolution, bundle=bundle)

    forged_witness = copy.deepcopy(graph)
    forged_witness["accepted_claims"][0]["comparison_witness"][
        "supporting_value"
    ] = 0.7
    with pytest.raises(ValueError, match="witness"):
        validate_evidence_claim_graph_v2(forged_witness, bundle=bundle)

    forged_polarity = copy.deepcopy(graph)
    forged_polarity["evidence_edges"][0]["polarity"] = "contradicting"
    with pytest.raises(ValueError, match="polarity"):
        validate_evidence_claim_graph_v2(forged_polarity, bundle=bundle)


@pytest.mark.parametrize(
    ("supporting", "contradicting", "expected"),
    [
        (0.8, 0.2, "rebutted_with_evidence"),
        (0.8, 0.75, "qualified"),
        (0.2, 0.8, "reversed"),
        (None, 0.8, "abstained"),
    ],
)
def test_counterevidence_resolution_is_versioned_and_deterministic(
    supporting: float | None, contradicting: float, expected: str
):
    rule = {
        "rule_version": "counterevidence_rule_v1",
        "dimension": "directional_strength",
        "polarity_extractor_version": "signed_numeric_v1",
        "aggregation": "max_strength_v1",
        "comparison": "support_minus_contradiction",
        "threshold": 0.25,
        "unknown_policy": "abstain",
    }
    assert evaluate_counterevidence(rule, supporting, contradicting) == expected


def test_knot_aggregate_distinguishes_four_model_controllable_gaps():
    binding_id = _bundle()["binding_manifest"]["bindings"][0]["binding_id"]
    aggregate = build_knot_capability_use_aggregate(
        binding_id=binding_id,
        observations=[
            {"eligible": True, "ready": True, "called": False},
            {"eligible": True, "ready": True, "called": True, "succeeded": False},
            {
                "eligible": True,
                "ready": True,
                "called": True,
                "succeeded": True,
                "used_in_accepted_evidence": False,
            },
            {
                "eligible": True,
                "ready": True,
                "called": True,
                "succeeded": True,
                "used_in_accepted_evidence": True,
                "counterevidence_available": True,
                "counterevidence_handled": False,
            },
            {"eligible": True, "ready": False, "runtime_blocker": "SOURCE_UNAVAILABLE"},
        ],
    )
    assert aggregate["gap_counts"] == {
        "not_called": 1,
        "call_failed": 1,
        "succeeded_not_used": 1,
        "counterevidence_ignored": 1,
    }
    assert aggregate["runtime_blocker_count"] == 1
    assert aggregate["model_controllable_gap_count"] == 4
    validate_knot_capability_use_aggregate(aggregate)

    forged = copy.deepcopy(aggregate)
    forged["ready_count"] += 1
    forged["aggregate_hash"] = canonical_hash(
        {key: value for key, value in forged.items() if key != "aggregate_hash"}
    )
    with pytest.raises(ValueError, match="count conservation"):
        validate_knot_capability_use_aggregate(forged)


def test_binding_id_changes_with_argument_or_output_semantics():
    row = _binding_body(_bundle()["binding_manifest"]["bindings"][0])
    original = canonical_binding_id(row)
    changed_args = copy.deepcopy(row)
    changed_args["argument_domain_selector_hash"] = "sha256:" + "a" * 64
    changed_output = copy.deepcopy(row)
    changed_output["output_semantics_hash"] = "sha256:" + "b" * 64
    assert canonical_binding_id(changed_args) != original
    assert canonical_binding_id(changed_output) != original


def test_maturity_gate_binds_calendar_label_receipt_and_cutoff():
    sample = {
        "matured_at": "2026-08-07T16:00:00+00:00",
        "outcome_contract_hash": "sha256:" + "1" * 64,
        "trading_calendar_hash": "sha256:" + "2" * 64,
        "label_receipt_hash": "sha256:" + "3" * 64,
    }
    assert is_mature_sample_eligible(
        sample,
        cutoff_at="2026-08-08T00:00:00+00:00",
        outcome_contract_hash="sha256:" + "1" * 64,
    )
    assert not is_mature_sample_eligible(
        sample,
        cutoff_at="2026-08-07T00:00:00+00:00",
        outcome_contract_hash="sha256:" + "1" * 64,
    )
    missing_receipt = dict(sample)
    missing_receipt["label_receipt_hash"] = None
    assert not is_mature_sample_eligible(
        missing_receipt,
        cutoff_at=datetime(2026, 8, 8, tzinfo=timezone.utc).isoformat(),
        outcome_contract_hash="sha256:" + "1" * 64,
    )


@pytest.mark.parametrize(
    "key",
    ["abstract", "claim_text", "source_span_ids", "report_title", "query_text"],
)
def test_public_knot_projection_rejects_report_and_private_prose(key: str):
    with pytest.raises(ValueError, match="private or licensed"):
        validate_public_safe_projection({"binding_id": "binding:test", key: "not-public"})
    validate_public_safe_projection(
        {
            "binding_id": "binding:test",
            "eligible_count": 1,
            "opaque_failure_refs": ["failure:opaque:1"],
        }
    )


@pytest.mark.parametrize(
    "action",
    [
        "GENERATE_CANDIDATE",
        "RUN_EXPERIMENT",
        "JUDGE_EXPERIMENT",
        "PROMOTE_DECISION",
        "STAGE_PROMPT_RELEASE",
        "START_PROMPT_CANARY",
        "ACTIVATE_PROMPT_RELEASE",
    ],
)
def test_transition_freeze_blocks_new_knot_evolution(action: str):
    with pytest.raises(ValueError, match="KNOT evolution frozen"):
        assert_knot_action(action, _bundle()["preservation_manifest"])
    assert (
        assert_knot_action(
            "USE_ACTIVE_CHAMPION", _bundle()["preservation_manifest"]
        )
        is None
    )
