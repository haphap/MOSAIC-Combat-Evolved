from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_schema_validation_report,
    validate_json_schema_artifact,
)
from mosaic.rke.cli import main
from mosaic.rke.schema_validation import (
    SUPPORTED_JSON_SCHEMA_KEYWORDS,
    iter_json_schema_keywords,
    validate_report_intelligence_semantics,
    validate_rule_pack_schema_artifact,
)


REQUIRED_SCHEMA_FILES = {
    "source_metadata.schema.json",
    "source_grounded_claim.schema.json",
    "hypothesis.schema.json",
    "data_availability_matrix.schema.json",
    "rule_pack.schema.yaml",
    "parameter_prior.schema.json",
    "validation_experiment_v2.schema.json",
    "production_patch.schema.json",
    "confidence_policy.schema.yaml",
    "rule_aggregation_policy.schema.yaml",
    "report_intelligence_feature_flags.schema.json",
    "report_intelligence_report_metadata.schema.json",
    "report_intelligence_forecast_claim.schema.json",
    "report_intelligence_analytical_footprint.schema.json",
    "report_intelligence_report_forecast_ledger.schema.json",
    "report_intelligence_markdown_coverage_summary.schema.json",
    "report_intelligence_industry_etf_proxy_map.schema.json",
    "report_intelligence_industry_etf_proxy_pit_availability.schema.json",
    "report_intelligence_report_outcome_label.schema.json",
    "report_intelligence_outcome_labeling_readiness.schema.json",
    "report_intelligence_source_performance_profile.schema.json",
    "report_intelligence_viewpoint_performance_profile.schema.json",
    "report_intelligence_method_performance_profile.schema.json",
    "report_intelligence_metric_candidate.schema.json",
    "report_intelligence_monitoring_report.schema.json",
    "report_intelligence_method_pattern.schema.json",
    "report_intelligence_tool_coverage_match.schema.json",
    "report_intelligence_tool_gap.schema.json",
    "report_intelligence_data_acquisition_proposal.schema.json",
    "report_intelligence_tool_design_proposal.schema.json",
    "report_intelligence_analysis_recipe.schema.json",
    "report_intelligence_recipe_paper_trading_run.schema.json",
    "report_intelligence_recipe_paper_trading_summary.schema.json",
    "report_intelligence_confidence_impact_observation.schema.json",
    "report_intelligence_confidence_impact_monitor.schema.json",
    "report_intelligence_prompt_mutation_candidate.schema.json",
    "report_intelligence_weighted_research_context.schema.json",
    "report_intelligence_runtime_tool_gap_observation.schema.json",
    "report_intelligence_runtime_safety_audit.schema.json",
    "report_intelligence_pit_leakage_audit.schema.json",
    "report_intelligence_extraction_provenance_audit.schema.json",
    "report_intelligence_statistical_robustness_audit.schema.json",
    "report_intelligence_tool_feasibility_audit.schema.json",
    "report_intelligence_recipe_validation_audit.schema.json",
    "report_intelligence_patch_v1_5_coverage_report.schema.json",
}

REQUIRED_POLICY_DOCS = {
    "validation_policy.md",
    "claim_extraction_guidelines.md",
    "confidence_policy.md",
    "compliance_policy.md",
}
REQUIRED_PLAN_DOCS = {
    "master_plan_v1_1.md",
    "rke_phase_minus_1_plan.md",
}


def _copy_report_intelligence_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "registry/report_intelligence"
    shutil.copytree(Path("registry/report_intelligence"), registry)
    return registry


def test_phase1_schema_artifacts_exist():
    schema_dir = Path("schemas")

    assert {path.name for path in schema_dir.iterdir()} >= REQUIRED_SCHEMA_FILES


def test_master_plan_policy_docs_exist():
    docs_dir = Path("docs")
    plans_dir = docs_dir / "plans"

    assert {path.name for path in docs_dir.iterdir()} >= REQUIRED_POLICY_DOCS
    assert {path.name for path in plans_dir.iterdir()} >= REQUIRED_PLAN_DOCS


def test_json_schema_artifacts_are_parseable_and_have_required_fields():
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["type"] == "object"
        assert schema.get("required"), f"{path} must declare required fields"


def test_json_schema_artifacts_only_use_supported_validator_keywords():
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        unsupported = set(iter_json_schema_keywords(schema)) - SUPPORTED_JSON_SCHEMA_KEYWORDS
        assert not unsupported, f"{path} uses unsupported schema keywords: {sorted(unsupported)}"


def test_yaml_policy_schema_artifacts_pin_master_plan_defaults():
    confidence = Path("schemas/confidence_policy.schema.yaml").read_text(encoding="utf-8")
    aggregation = Path("schemas/rule_aggregation_policy.schema.yaml").read_text(encoding="utf-8")
    rule_pack = Path("schemas/rule_pack.schema.yaml").read_text(encoding="utf-8")

    assert "safe_default_function" in confidence
    assert "final_confidence_max: 0.50" in confidence
    assert "single_rule_max_adjustment: 0.05" in aggregation
    assert "conflict_object_required" in aggregation
    assert "<layer>.<agent>.<rule_type>.<serial>" in rule_pack


def test_schema_validation_report_accepts_current_registry():
    report = build_schema_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert len(report.records) >= 15
    assert {
        "schemas/source_metadata.schema.json",
        "schemas/source_grounded_claim.schema.json",
        "schemas/validation_experiment_v2.schema.json",
        "schemas/rule_pack.schema.yaml",
        "schemas/confidence_policy.schema.yaml",
        "schemas/report_intelligence_forecast_claim.schema.json",
        "schemas/report_intelligence_runtime_guard_rules",
        "schemas/report_intelligence_alpha_decay_monitoring_rules",
        "schemas/report_intelligence_tooling_readiness_rules",
        "schemas/report_intelligence_patch_v1_5_coverage_rules",
    } <= {record.schema_path for record in report.records}


def test_report_intelligence_tooling_readiness_requires_reviewable_proposals(
    tmp_path: Path,
):
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    empty_jsonl_files = (
        "forecast_claims.jsonl",
        "analytical_footprints.jsonl",
        "report_forecast_ledger.jsonl",
        "method_patterns.jsonl",
        "analysis_recipes.jsonl",
        "weighted_research_contexts.jsonl",
        "runtime_tool_gap_observations.jsonl",
        "data_acquisition_proposals.jsonl",
        "tool_design_proposals.jsonl",
    )
    for name in empty_jsonl_files:
        (registry / name).write_text("", encoding="utf-8")
    (registry / "outcome_labeling_readiness.json").write_text(
        json.dumps(
            {
                "forecast_claim_count": 0,
                "forecast_ledger_count": 0,
                "ready_for_outcome_labeling_count": 0,
                "standard_blocked_count": 0,
                "proxy_label_ready_count": 0,
                "proxy_label_only_ready_count": 0,
                "blocked_count": 0,
                "ready_forecast_claim_ids": [],
                "standard_blocked_forecast_claim_ids": [],
                "proxy_label_ready_forecast_claim_ids": [],
                "proxy_label_only_ready_forecast_claim_ids": [],
                "blocked_forecast_claim_ids": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (registry / "feature_flags.json").write_text(
        json.dumps(
            {
                "flags": {"report_weighting_enabled": False},
                "rollout_mode": "extraction_only",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (registry / "tool_gaps.jsonl").write_text(
        json.dumps(
            {
                "tool_gap_id": "TG-HIGH",
                "gap_type": "missing_metric",
                "metric_candidate_id": "METRIC-X",
                "method_pattern_ids": ["METHOD-X"],
                "target_agents": ["macro.central_bank"],
                "research_origin": {},
                "priority_bucket": "high",
                "priority_reasons": ["missing_or_partial_data_blocks_named_agent"],
                "blocking_issues": ["requires_engineering_review"],
                "owner": "data_engineering",
                "status": "proposal_pending",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    tooling_record = next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_tooling_readiness_rules"
    )

    assert not tooling_record.accepted
    assert any("missing data acquisition proposal" in item for item in tooling_record.failures)
    assert any("missing tool design proposal" in item for item in tooling_record.failures)


def test_report_intelligence_runtime_guard_rejects_production_rollout_flags(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    feature_flags_path = registry / "feature_flags.json"
    feature_flags = json.loads(feature_flags_path.read_text(encoding="utf-8"))
    feature_flags["rollout_mode"] = "production"
    feature_flags["flags"]["production_use_of_weighted_reports"] = True
    feature_flags_path.write_text(
        json.dumps(feature_flags, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    runtime_record = next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_runtime_guard_rules"
    )

    assert not runtime_record.accepted
    assert any(
        "production_use_of_weighted_reports must remain false" in item
        for item in runtime_record.failures
    )
    assert any("rollout_mode must not exceed shadow_tooling" in item for item in runtime_record.failures)


def test_report_intelligence_runtime_guard_requires_shadow_tooling_flags(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    feature_flags_path = registry / "feature_flags.json"
    feature_flags = json.loads(feature_flags_path.read_text(encoding="utf-8"))
    feature_flags["rollout_mode"] = "shadow_tooling"
    feature_flags["flags"]["shadow_tool_runtime_enabled"] = False
    feature_flags_path.write_text(
        json.dumps(feature_flags, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    runtime_record = next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_runtime_guard_rules"
    )

    assert not runtime_record.accepted
    assert "shadow_tooling requires shadow_tool_runtime_enabled" in runtime_record.failures


def test_report_intelligence_runtime_guard_requires_no_decision_impact_label(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    feature_flags_path = registry / "feature_flags.json"
    feature_flags = json.loads(feature_flags_path.read_text(encoding="utf-8"))
    feature_flags["runtime_behavior"] = "shadow tooling"
    feature_flags_path.write_text(
        json.dumps(feature_flags, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    runtime_record = next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_runtime_guard_rules"
    )

    assert not runtime_record.accepted
    assert (
        "feature_flags.runtime_behavior must state no agent decision impact"
        in runtime_record.failures
    )


def test_report_intelligence_runtime_safety_audit_must_be_accepted(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    audit_path = registry / "runtime_safety_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["accepted"] = False
    audit["blocker_count"] = 1
    audit["blockers"] = ["shadow output changed sizing"]
    audit["checks"][0]["accepted"] = False
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    audit_record = next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_runtime_safety_audit_rules"
    )

    assert not audit_record.accepted
    assert "runtime_safety_audit accepted must be true" in audit_record.failures
    assert any("check must be accepted" in item for item in audit_record.failures)


def test_report_intelligence_pit_leakage_audit_must_be_accepted(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    audit_path = registry / "pit_leakage_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["accepted"] = False
    audit["blocker_count"] = 1
    audit["blockers"] = ["source profile used future outcome"]
    audit["checks"][1]["accepted"] = False
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    audit_record = next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_pit_leakage_audit_rules"
    )

    assert not audit_record.accepted
    assert "pit_leakage_audit accepted must be true" in audit_record.failures
    assert any("check must be accepted" in item for item in audit_record.failures)


def test_report_intelligence_extraction_provenance_audit_must_be_accepted(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    audit_path = registry / "extraction_provenance_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["accepted"] = False
    audit["blocker_count"] = 1
    audit["blockers"] = ["source_grounded claim missing source_span_ids"]
    audit["checks"][1]["accepted"] = False
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    audit_record = next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_extraction_provenance_audit_rules"
    )

    assert not audit_record.accepted
    assert (
        "extraction_provenance_audit accepted must be true"
        in audit_record.failures
    )
    assert any("check must be accepted" in item for item in audit_record.failures)


def test_report_intelligence_statistical_robustness_audit_must_be_accepted(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    audit_path = registry / "statistical_robustness_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["accepted"] = False
    audit["blocker_count"] = 1
    audit["blockers"] = ["overlapping windows counted as independent samples"]
    audit["checks"][3]["accepted"] = False
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    audit_record = next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_statistical_robustness_audit_rules"
    )

    assert not audit_record.accepted
    assert (
        "statistical_robustness_audit accepted must be true"
        in audit_record.failures
    )
    assert any("check must be accepted" in item for item in audit_record.failures)


def test_report_intelligence_tool_feasibility_audit_must_be_accepted(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    audit_path = registry / "tool_feasibility_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["accepted"] = False
    audit["blocker_count"] = 1
    audit["blockers"] = ["missing tool gap has no output schema"]
    audit["checks"][4]["accepted"] = False
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    audit_record = next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_tool_feasibility_audit_rules"
    )

    assert not audit_record.accepted
    assert "tool_feasibility_audit accepted must be true" in audit_record.failures
    assert any("check must be accepted" in item for item in audit_record.failures)


def test_report_intelligence_recipe_validation_audit_must_be_accepted(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    audit_path = registry / "recipe_validation_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["accepted"] = False
    audit["blocker_count"] = 1
    audit["blockers"] = ["candidate jumped to production"]
    audit["checks"][2]["accepted"] = False
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    audit_record = next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_recipe_validation_audit_rules"
    )

    assert not audit_record.accepted
    assert "recipe_validation_audit accepted must be true" in audit_record.failures
    assert any("check must be accepted" in item for item in audit_record.failures)


def test_report_intelligence_alpha_decay_monitoring_requires_metric_contract(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitoring_path = registry / "monitoring_report.json"
    monitoring = json.loads(monitoring_path.read_text(encoding="utf-8"))
    monitoring["alpha_decay_monitoring"]["required_decay_metrics"] = [
        "rolling_after_cost_alpha"
    ]
    monitoring["alpha_decay_monitoring"]["unmonitored_production_recipe_ids"] = [
        "RECIPE-CB-UNMONITORED"
    ]
    monitoring_path.write_text(
        json.dumps(monitoring, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    records = validate_report_intelligence_semantics(tmp_path)
    monitoring_record = next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_alpha_decay_monitoring_rules"
    )

    assert not monitoring_record.accepted
    assert any("missing required decay metrics" in item for item in monitoring_record.failures)
    assert any("unmonitored recipes" in item for item in monitoring_record.failures)


def test_schema_validation_rejects_missing_required_field(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/sources"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "source_metadata.schema.json").write_text(
        Path("schemas/source_metadata.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (artifact_dir / "central_bank_sources.jsonl").write_text(
        json.dumps(
            {
                "source_id": "SRC-X",
                "source_type": "official",
                "publish_date": "2026-06-06",
                "ingest_time": "2026-06-06T00:00:00+00:00",
                "license_status": "approved",
                "point_in_time_available": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/source_metadata.schema.json",
        artifact_path="registry/sources/central_bank_sources.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("source_hash" in failure for failure in record.failures)


def test_schema_validation_enforces_numeric_minimum(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/report_intelligence"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "minimum.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "Minimum fixture",
                "type": "object",
                "required": ["count"],
                "properties": {
                    "count": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "minimum.json").write_text(
        json.dumps({"count": -1}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/minimum.schema.json",
        artifact_path="registry/report_intelligence/minimum.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any("below minimum" in failure for failure in record.failures)


def test_schema_validation_reports_malformed_json_schema(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/sources"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "source_metadata.schema.json").write_text("{", encoding="utf-8")
    (artifact_dir / "central_bank_sources.jsonl").write_text(
        json.dumps({"source_id": "SRC-X"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/source_metadata.schema.json",
        artifact_path="registry/sources/central_bank_sources.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert record.item_count == 1
    assert any("source_metadata.schema.json must contain valid JSON" in failure for failure in record.failures)


def test_schema_validation_reports_malformed_jsonl_artifact(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/sources"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "source_metadata.schema.json").write_text(
        Path("schemas/source_metadata.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (artifact_dir / "central_bank_sources.jsonl").write_text("{\n", encoding="utf-8")

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/source_metadata.schema.json",
        artifact_path="registry/sources/central_bank_sources.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert record.item_count == 0
    assert any(
        "registry/sources/central_bank_sources.jsonl row 1 must contain valid JSON" in failure
        for failure in record.failures
    )


def test_schema_validation_reports_malformed_json_artifact(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/data_availability"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "data_availability_matrix.schema.json").write_text(
        Path("schemas/data_availability_matrix.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (artifact_dir / "central_bank_data_availability.json").write_text("{", encoding="utf-8")

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/data_availability_matrix.schema.json",
        artifact_path="registry/data_availability/central_bank_data_availability.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert record.item_count == 0
    assert (
        "registry/data_availability/central_bank_data_availability.json must contain valid JSON"
        in record.failures[0]
    )


def test_report_intelligence_forecast_schema_rejects_unprovenanced_failure_modes(
    tmp_path: Path,
):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/report_intelligence"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "report_intelligence_forecast_claim.schema.json").write_text(
        Path("schemas/report_intelligence_forecast_claim.schema.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (artifact_dir / "forecast_claims.jsonl").write_text(
        json.dumps(
            {
                "benchmark": {},
                "claim_id": "CLAIM-X",
                "claim_provenance": "source_grounded",
                "claim_text": "资金面改善支持风险偏好。",
                "direction": "positive",
                "extraction_quality": {},
                "extractor": {},
                "failure_modes": ["资金面重新收紧"],
                "forecast_claim_id": "FC-X",
                "forecast_testability": "insufficient_mapping",
                "forecast_type": "macro",
                "horizon": {},
                "report_id": "RPT-X",
                "signal_datetime": "2026-06-06",
                "source_id": "SRC-X",
                "source_span_ids": ["SRC-X:span"],
                "target": {},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_forecast_claim.schema.json",
        artifact_path="registry/report_intelligence/forecast_claims.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("failure_modes[0]: expected object" in failure for failure in record.failures)


def test_rule_pack_schema_validation_rejects_non_object_artifact(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    rule_dir = tmp_path / "registry/rule_packs"
    schema_dir.mkdir(parents=True)
    rule_dir.mkdir(parents=True)
    (schema_dir / "rule_pack.schema.yaml").write_text(
        Path("schemas/rule_pack.schema.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    artifact_path = "registry/rule_packs/bad_rule_pack.json"
    (tmp_path / artifact_path).write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    record = validate_rule_pack_schema_artifact(tmp_path, artifact_path)

    assert not record.accepted
    assert record.failures == ("$: expected object",)


def test_rule_pack_schema_validation_reports_malformed_json_artifact(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    rule_dir = tmp_path / "registry/rule_packs"
    schema_dir.mkdir(parents=True)
    rule_dir.mkdir(parents=True)
    (schema_dir / "rule_pack.schema.yaml").write_text(
        Path("schemas/rule_pack.schema.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    artifact_path = "registry/rule_packs/bad_rule_pack.json"
    (tmp_path / artifact_path).write_text("{", encoding="utf-8")

    record = validate_rule_pack_schema_artifact(tmp_path, artifact_path)

    assert not record.accepted
    assert record.item_count == 0
    assert "registry/rule_packs/bad_rule_pack.json must contain valid JSON" in record.failures[0]


def test_rule_pack_schema_validation_rejects_non_object_rule(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    rule_dir = tmp_path / "registry/rule_packs"
    schema_dir.mkdir(parents=True)
    rule_dir.mkdir(parents=True)
    (schema_dir / "rule_pack.schema.yaml").write_text(
        Path("schemas/rule_pack.schema.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    artifact_path = "registry/rule_packs/bad_rule_pack.json"
    (tmp_path / artifact_path).write_text(
        json.dumps(
            {
                "agent_id": "macro.central_bank",
                "rule_pack_id": "macro.central_bank.bad.v1",
                "rules": {"bad_rule": ["not", "an", "object"]},
                "version": "v1",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    record = validate_rule_pack_schema_artifact(tmp_path, artifact_path)

    assert not record.accepted
    assert "$.rules.bad_rule: expected object" in record.failures


def test_schema_status_cli_writes_report(capsys):
    code = main(("schema-status", "--root", "."))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert Path("registry/schemas/rke_schema_validation_report.json").exists()


def test_schema_status_cli_reports_malformed_artifact(tmp_path: Path, capsys):
    schema_dir = tmp_path / "schemas"
    registry_dir = tmp_path / "registry"
    schema_dir.mkdir()
    for path in Path("schemas").iterdir():
        if path.is_file():
            (schema_dir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    shutil.copytree(Path("registry"), registry_dir, dirs_exist_ok=True)
    (tmp_path / "registry/sources/central_bank_sources.jsonl").write_text("{\n", encoding="utf-8")

    code = main(("schema-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert output["failure_count"] >= 1
