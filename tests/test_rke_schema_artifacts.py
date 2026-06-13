from __future__ import annotations

import json
import shutil
from hashlib import sha256
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
from mosaic.rke.report_intelligence import build_default_industry_etf_proxy_map_rows


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
    "report_intelligence_macro_regime_calendar.schema.json",
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
    "report_intelligence_evolution_refresh_history.schema.json",
    "report_intelligence_evolution_readiness_gate.schema.json",
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
    "rke_stock_report_outcome_and_evolution_plan.md",
    "rke_stock_report_outcome_and_evolution_status.md",
}
EXPECTED_PHASE_B_PATCH_COVERAGE_FAILURES = {
    "patch_v1_5_coverage_report accepted must be true",
    "patch_v1_5_coverage_report blocker_count must be zero",
    "patch_v1_5_coverage_report blocked_phase_ids must be empty",
    "patch_v1_5_coverage_report Phase B: accepted must be true",
    "patch_v1_5_coverage_report Phase B: status cannot be blocked",
    "patch_v1_5_coverage_report Phase B: failure_count must be zero",
    "patch_v1_5_coverage_report Phase D: accepted must be true",
    "patch_v1_5_coverage_report Phase D: status cannot be blocked",
    "patch_v1_5_coverage_report Phase D: failure_count must be zero",
    "patch_v1_5_coverage_report RI15-B-D1: accepted must be true",
    "patch_v1_5_coverage_report RI15-B-D1: status cannot be blocked",
    "patch_v1_5_coverage_report RI15-B-D2: accepted must be true",
    "patch_v1_5_coverage_report RI15-B-D2: status cannot be blocked",
    "patch_v1_5_coverage_report RI15-D-D1: accepted must be true",
    "patch_v1_5_coverage_report RI15-D-D1: status cannot be blocked",
}
EXPECTED_ANALYTICAL_FOOTPRINT_REVIEW_FAILURES = {
    "analytical_footprint_review_summary accepted must be true",
    "analytical_footprint_review_summary review_complete must be true",
    "analytical_footprint_review_summary quality_gate_passed must be true",
    "analytical_footprint_review_summary pending_rows must be zero",
    (
        "analytical_footprint_review_summary quality blockers: "
        "footprint_precision unavailable; span_support_precision unavailable; "
        "metric_mapping_accuracy unavailable; inferred_step_tagging_accuracy unavailable; "
        "unknown_on_ambiguity_rate unavailable; proprietary_leakage_free_rate unavailable"
    ),
}


def _assert_only_phase_b_patch_coverage_failures(report) -> None:
    failed_records = {
        record.schema_path: record for record in report.records if not record.accepted
    }
    assert set(failed_records) == {
        "schemas/report_intelligence_analytical_footprint_review_rules",
        "schemas/report_intelligence_patch_v1_5_coverage_rules",
    }
    assert (
        set(
            failed_records[
                "schemas/report_intelligence_analytical_footprint_review_rules"
            ].failures
        )
        == EXPECTED_ANALYTICAL_FOOTPRINT_REVIEW_FAILURES
    )
    assert (
        set(
            failed_records[
                "schemas/report_intelligence_patch_v1_5_coverage_rules"
            ].failures
        )
        == EXPECTED_PHASE_B_PATCH_COVERAGE_FAILURES
    )
    assert report.failure_count == (
        len(EXPECTED_ANALYTICAL_FOOTPRINT_REVIEW_FAILURES)
        + len(EXPECTED_PHASE_B_PATCH_COVERAGE_FAILURES)
    )


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


def test_stock_report_outcome_status_doc_matches_public_artifacts():
    status_text = Path(
        "docs/plans/rke_stock_report_outcome_and_evolution_status.md"
    ).read_text(encoding="utf-8")
    extraction_report = json.loads(
        Path("registry/report_intelligence/extraction_report.json").read_text(
            encoding="utf-8"
        )
    )
    progress_report = json.loads(
        Path("registry/review_batches/manual_review_progress_report.json").read_text(
            encoding="utf-8"
        )
    )
    evolution_gate = json.loads(
        Path("registry/report_intelligence/evolution_readiness_gate.json").read_text(
            encoding="utf-8"
        )
    )
    prompt_mutation_candidates = [
        json.loads(line)
        for line in Path(
            "registry/report_intelligence/prompt_mutation_candidates.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    operator_readiness = json.loads(
        Path("registry/handoffs/rke_operator_readiness_report.json").read_text(
            encoding="utf-8"
        )
    )
    gate_kinds = {gate["review_kind"] for gate in progress_report["gates"]}
    operator_check_ids = {check["check_id"] for check in operator_readiness["checks"]}

    outcome_count = extraction_report["outcome_label_rows"]
    industry_count = extraction_report["industry_etf_proxy_outcome_label_rows"]
    stock_count = extraction_report["stock_price_proxy_outcome_label_rows"]
    assert (
        f"{outcome_count} outcome labels: {industry_count} industry ETF proxy, "
        f"{stock_count} stock price proxy"
    ) in status_text
    assert {"gold_set", "footprint_review", "source_license", "lockbox"} <= gate_kinds
    assert "public baseline: gold-set 0/500" in status_text
    assert "analytical-footprint review 0/1001" in status_text
    assert "source license 17529/17529" in status_text
    assert "source license 17529/17529 already applied" in status_text
    assert "action_state=already_applied" in status_text
    assert "can_run_now=false" in status_text
    assert "private footprint review assist/workbook cover 1001 pending rows" in status_text
    assert "private gold-set evidence draft now covers 500 rows" in status_text
    assert "private evidence draft covers 1001 rows with 0 missing local markdown rows" in status_text
    assert "Synthetic pytest fixtures" in status_text
    assert "current target hashes" in status_text
    assert "500 rows still require manual claim text and boolean review decisions" in status_text
    assert "lockbox 0/1" in status_text
    assert "labelability_summary" in status_text
    assert "outcome_labeling_readiness.industry_etf_proxy_readiness" in status_text
    assert "124 labelable stock claims" in status_text
    assert "593 pending future windows" in status_text
    assert "qlib://..." in status_text
    assert "entry_lag_trading_days" in status_text
    assert "STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS" in status_text
    assert "11 shadow-only mutation candidates" in status_text
    assert "production_prompt_change_allowed=false" in status_text
    assert len(prompt_mutation_candidates) == 11
    assert {
        candidate["promotion_state"] for candidate in prompt_mutation_candidates
    } == {"shadow_candidate_only"}
    assert {
        candidate["production_prompt_change_allowed"]
        for candidate in prompt_mutation_candidates
    } == {False}
    assert {
        candidate["private_text_included"] for candidate in prompt_mutation_candidates
    } == {False}
    assert {
        candidate["manual_review_required"] for candidate in prompt_mutation_candidates
    } == {True}
    assert "operator readiness currently passes 18/18 checks" in status_text
    assert operator_readiness["accepted"] is True
    assert operator_readiness["passed_count"] == operator_readiness["check_count"] == 18
    assert {
        "blank_full_gold_set_import_is_rejected",
        "lockbox_upstream_cli_guard_enforced",
        "blank_bundle_dry_run_does_not_promote",
        "manual_review_runbook_promotion_policy_consistent",
        "manual_batch_promotion_inputs_separated",
        "promotion_gate_state_consistent",
    } <= operator_check_ids
    assert (
        f"blocked; {evolution_gate['blocker_count']} blockers remain"
        in status_text
    )
    for blocker in (
        "industry_proxy_claim_count_below_threshold",
        "paper_trading_validated_recipe_count_below_threshold",
    ):
        assert blocker not in evolution_gate["blockers"]
    assert "current gate thresholds are cleared" in status_text
    assert "20 validated recipes" in status_text
    assert "coverage_gate_status=passed" in status_text
    assert "report prose" in status_text
    assert "production trading decisions" in status_text


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

    assert not report.accepted
    _assert_only_phase_b_patch_coverage_failures(report)
    assert len(report.records) >= 15
    assert {
        "schemas/source_metadata.schema.json",
        "schemas/source_grounded_claim.schema.json",
        "schemas/validation_experiment_v2.schema.json",
        "schemas/rule_pack.schema.yaml",
        "schemas/confidence_policy.schema.yaml",
        "schemas/report_intelligence_forecast_claim.schema.json",
        "schemas/report_intelligence_runtime_guard_rules",
        "schemas/report_intelligence_industry_etf_mapping_contract_rules",
        "schemas/report_intelligence_markdown_coverage_privacy_rules",
        "schemas/report_intelligence_recipe_paper_trading_contract_rules",
        "schemas/report_intelligence_evolution_refresh_history_rules",
        "schemas/report_intelligence_evolution_readiness_gate_rules",
        "schemas/report_intelligence_gold_review_gate_rules",
        "schemas/report_intelligence_alpha_decay_monitoring_rules",
        "schemas/report_intelligence_tooling_readiness_rules",
        "schemas/report_intelligence_patch_v1_5_coverage_rules",
    } <= {record.schema_path for record in report.records}


def test_schema_validation_allows_missing_optional_private_jsonl(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir(parents=True)
    (schema_dir / "report_intelligence_report_outcome_label.schema.json").write_text(
        Path("schemas/report_intelligence_report_outcome_label.schema.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_report_outcome_label.schema.json",
        artifact_path="registry/report_intelligence/report_outcome_labels.jsonl",
        artifact_kind="jsonl",
        allow_empty=True,
    )

    assert record.accepted
    assert record.item_count == 0
    assert record.failures == ()


def test_analysis_recipe_required_data_requires_metric_prefix(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir(parents=True)
    (schema_dir / "report_intelligence_analysis_recipe.schema.json").write_text(
        Path("schemas/report_intelligence_analysis_recipe.schema.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    recipe = {
        "analysis_recipe_id": "RECIPE-RAW-DATA",
        "recipe_id": "RECIPE-RAW-DATA",
        "name": "raw data recipe",
        "method_pattern_id": "METHOD-RAW-DATA",
        "source_method_pattern_ids": ["METHOD-RAW-DATA"],
        "version": "0.1.0",
        "promotion_state": "shadow_candidate",
        "runtime_mode": "shadow_only",
        "required_tools": [],
        "required_data": ["stock_price"],
        "decision_scope": "raw_data_score",
        "entry_condition": "T+1_or_more_conservative_shadow_entry",
        "exit_condition": "fixed_horizon_shadow_exit",
        "risk_controls": ["no_production_order"],
        "expected_horizon_days": 60,
        "steps": [],
        "output_signal": {},
        "validation_status": "candidate",
        "promotion_requirements": [],
    }
    (registry / "analysis_recipes.jsonl").write_text(
        json.dumps(recipe, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_analysis_recipe.schema.json",
        artifact_path="registry/report_intelligence/analysis_recipes.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("required_data[0]" in failure for failure in record.failures)


def test_outcome_labeling_readiness_requires_proxy_channel_fields(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness.pop("stock_proxy_label_ready_count")
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_outcome_labeling_readiness.schema.json",
        artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any(
        "stock_proxy_label_ready_count: required" in failure
        for failure in record.failures
    )


def test_outcome_labeling_readiness_requires_stock_pit_realism_policy(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["stock_price_proxy_readiness"]["pit_realism_policy"].pop(
        "benchmark_alignment"
    )
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_outcome_labeling_readiness.schema.json",
        artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any("benchmark_alignment: required" in failure for failure in record.failures)


def test_outcome_labeling_readiness_rejects_proxy_llm_labeling(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["industry_etf_proxy_readiness"]["llm_outcome_labeling_allowed"] = True
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_outcome_labeling_readiness.schema.json",
        artifact_path="registry/report_intelligence/outcome_labeling_readiness.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any("llm_outcome_labeling_allowed" in failure for failure in record.failures)


def test_stock_price_proxy_readiness_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_report_intelligence_registry(tmp_path)

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert record.accepted
    assert record.item_count >= 220
    assert record.failures == ()


def test_stock_price_proxy_readiness_contract_accepts_audited_survivorship_state(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    pit_policy = readiness["stock_price_proxy_readiness"]["pit_realism_policy"]
    pit_policy["survivorship_unverified"] = False
    pit_policy["survivorship_status"] = "delisted_inclusive_universe_audit_passed"
    pit_policy["survivorship_basis"] = (
        "delisted-inclusive universe audit passed; qlib cn_data stock proxy labels "
        "may mark survivorship_safe only when label-level checks also use the audited status"
    )
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert record.accepted
    assert record.item_count >= 220
    assert record.failures == ()


def test_stock_price_proxy_readiness_contract_rejects_pit_policy_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    stock_readiness = readiness["stock_price_proxy_readiness"]
    stock_readiness["pit_realism_policy"]["survivorship_unverified"] = False
    stock_readiness["pit_realism_policy"]["survivorship_status"] = "survivorship_unverified"
    stock_readiness["pit_realism_policy"]["company_name_fuzzy_mapping_enabled"] = True
    stock_readiness["pit_realism_policy"]["entry_limit_locked_blocks_label"] = False
    stock_readiness["pit_realism_policy"][
        "exit_liquidity_unverified_blocks_label"
    ] = False
    stock_readiness["data_gap_counts"]["entry_limit_locked"] = 1
    stock_readiness["data_gap_counts"]["exit_liquidity_unverified"] = 1
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert not record.accepted
    assert any("survivorship_status" in failure for failure in record.failures)
    assert any("survivorship_basis" in failure for failure in record.failures)
    assert any(
        "company_name_fuzzy_mapping_enabled" in failure
        for failure in record.failures
    )
    assert any("entry_limit_locked_blocks_label" in failure for failure in record.failures)
    assert any(
        "exit_liquidity_unverified_blocks_label" in failure
        for failure in record.failures
    )
    assert any("entry_limit_locked" in failure for failure in record.failures)
    assert any("exit_liquidity_unverified" in failure for failure in record.failures)


def test_stock_price_proxy_readiness_contract_rejects_stock_code_policy_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    stock_readiness = readiness["stock_price_proxy_readiness"]
    stock_readiness["ordinary_stock_code_policy"]["allowed_prefixes"]["BJ"] = [
        "83",
        "92",
    ]
    stock_readiness["ordinary_stock_code_policy"]["rejected_code_families"] = [
        "index"
    ]
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert not record.accepted
    assert any("ordinary_stock_code_policy" in failure for failure in record.failures)


def test_stock_price_proxy_readiness_contract_rejects_count_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    stock_readiness = readiness["stock_price_proxy_readiness"]
    stock_readiness["labelable_window_count"] = -1
    stock_readiness["labelable_forecast_claim_ids"].append("FC-not-in-labels")
    readiness["stock_proxy_label_ready_count"] = 0
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert not record.accepted
    assert any("labelable_window_count" in failure for failure in record.failures)
    assert any("labelable_forecast_claim_ids" in failure for failure in record.failures)
    assert any("stock_proxy_label_ready_count" in failure for failure in record.failures)


def test_profile_outcome_layer_contract_accepts_current_public_artifacts(
    tmp_path: Path,
):
    _copy_report_intelligence_registry(tmp_path)

    record = _profile_outcome_layer_record(tmp_path)

    assert record.accepted
    assert record.item_count == 3114
    assert record.failures == ()


def test_profile_outcome_layer_contract_rejects_layer_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    profiles_path = registry / "source_performance_profiles.jsonl"
    profiles = [
        json.loads(line)
        for line in profiles_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    profile = next(
        row
        for row in profiles
        if row["outcome_layer_support"]["layer_summaries"]
    )
    support = profile["outcome_layer_support"]
    support["layer_count"] = 0
    support["mixed_layer_profile"] = False
    support["layer_keys"] = []
    support["layer_summaries"][0]["n_effective"] = 0.0
    support["layer_summaries"][0].pop("benchmark_family", None)
    profiles_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in profiles
        )
        + "\n",
        encoding="utf-8",
    )

    record = _profile_outcome_layer_record(tmp_path)

    assert not record.accepted
    assert any("layer_count: must match" in failure for failure in record.failures)
    assert any("benchmark_family" in failure for failure in record.failures)
    assert any("layer_keys: must match" in failure for failure in record.failures)
    assert any("n_effective: expected sum" in failure for failure in record.failures)


def test_extraction_report_contract_accepts_current_public_artifact(tmp_path: Path):
    _copy_report_intelligence_registry(tmp_path)

    record = _extraction_report_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count > 1000
    assert record.failures == ()


def test_extraction_report_contract_rejects_readiness_count_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    report_path = registry / "extraction_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["stock_price_proxy_labelable_window_rows"] += 1
    report["outcome_label_rows"] += 1
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _extraction_report_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "stock_price_proxy_labelable_window_rows" in failure
        for failure in record.failures
    )
    assert any("outcome_label_rows" in failure for failure in record.failures)


def test_extraction_report_contract_rejects_private_or_absolute_output(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    report_path = registry / "extraction_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["root"] = "/home/hap/Project/MOSAIC-RKE"
    report["outputs"]["summary"] = "/tmp/extraction_report.json"
    report["title"] = "private source title"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _extraction_report_contract_record(tmp_path)

    assert not record.accepted
    assert any("root" in failure for failure in record.failures)
    assert any("outputs.summary" in failure for failure in record.failures)
    assert any("private/source text field forbidden" in failure for failure in record.failures)


def test_recipe_paper_trading_summary_rejects_profile_weight_promotion(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    summary_path = registry / "recipe_paper_trading_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["validation_protocol"]["profile_weight_is_sufficient"] = True
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_recipe_paper_trading_summary.schema.json",
        artifact_path="registry/report_intelligence/recipe_paper_trading_summary.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any(
        "validation_protocol.profile_weight_is_sufficient" in failure
        for failure in record.failures
    )


def test_recipe_paper_trading_summary_requires_full_protocol(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    summary_path = registry / "recipe_paper_trading_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["validation_protocol"].pop("parameter_lock_policy", None)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_recipe_paper_trading_summary.schema.json",
        artifact_path="registry/report_intelligence/recipe_paper_trading_summary.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any(
        "validation_protocol.parameter_lock_policy: required" in failure
        for failure in record.failures
    )


def test_recipe_paper_trading_summary_requires_direct_pit_diagnostics(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    summary_path = registry / "recipe_paper_trading_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("direct_pit_binding_diagnostics", None)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_recipe_paper_trading_summary.schema.json",
        artifact_path="registry/report_intelligence/recipe_paper_trading_summary.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any(
        "direct_pit_binding_diagnostics: required" in failure
        for failure in record.failures
    )


def test_confidence_impact_observation_rejects_unknown_drift_status(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[0]["drift_status"] = "llm_self_scored_confidence"
    observations_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in observations
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_confidence_impact_observation.schema.json",
        artifact_path="registry/report_intelligence/confidence_impact_observations.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("drift_status" in failure for failure in record.failures)


def test_confidence_impact_observation_schema_requires_plan_fields(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[0].pop("after_cost_realized_alpha", None)
    observations_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in observations
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_confidence_impact_observation.schema.json",
        artifact_path="registry/report_intelligence/confidence_impact_observations.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any(
        "after_cost_realized_alpha: required" in item
        for item in record.failures
    )


def test_confidence_impact_observation_schema_requires_regime_monitor_fields(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[0].pop("regime_contribution_shares", None)
    observations_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in observations
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_confidence_impact_observation.schema.json",
        artifact_path="registry/report_intelligence/confidence_impact_observations.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any(
        "regime_contribution_shares: required" in item
        for item in record.failures
    )


def _proxy_outcome_contract_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_proxy_outcome_label_contract_rules"
    )


def _stock_price_proxy_readiness_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_stock_price_proxy_readiness_rules"
    )


def _extraction_report_contract_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_extraction_report_contract_rules"
    )


def _profile_outcome_layer_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_profile_outcome_layer_rules"
    )


def _recipe_paper_trading_contract_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_recipe_paper_trading_contract_rules"
    )


def _evolution_refresh_history_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_evolution_refresh_history_rules"
    )


def _evolution_readiness_gate_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_evolution_readiness_gate_rules"
    )


def _copy_gold_review_summary(tmp_path: Path) -> Path:
    gold_dir = tmp_path / "registry/gold_sets"
    gold_dir.mkdir(parents=True, exist_ok=True)
    summary_path = gold_dir / "tushare_research_reports.review_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "blockers": ["500 gold-set claim review rows still pending"],
                "metrics": None,
                "passed": False,
                "pending_claims": 500,
                "review_complete": False,
                "review_path": "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                "reviewed_claims": 0,
                "summary_id": "RKE-GOLD-SET-REVIEW-SUMMARY-20260606",
                "total_claims": 500,
                "total_documents": 50,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_path


def _gold_review_gate_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_gold_review_gate_rules"
    )


def _prompt_mutation_candidate_contract_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_prompt_mutation_candidate_contract_rules"
    )


def _manual_review_progress_privacy_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_manual_review_progress_privacy_rules"
    )


def _manual_review_progress_contract_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_manual_review_progress_rules"
    )


def _operator_readiness_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_operator_readiness_rules"
    )


def _operator_handoff_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_operator_handoff_rules"
    )


def _manual_review_bundle_manifest_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_manual_review_bundle_manifest_rules"
    )


def _promotion_dry_run_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path == "schemas/report_intelligence_promotion_dry_run_rules"
    )


def _production_promotion_gate_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_production_promotion_gate_rules"
    )


def _industry_etf_mapping_contract_record(tmp_path: Path):
    records = validate_report_intelligence_semantics(tmp_path)
    return next(
        record
        for record in records
        if record.schema_path
        == "schemas/report_intelligence_industry_etf_mapping_contract_rules"
    )


def _write_proxy_outcome_labels(tmp_path: Path, rows: list[dict[str, object]]) -> None:
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "report_outcome_labels.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_forecast_claims(tmp_path: Path, rows: list[dict[str, object]]) -> None:
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "forecast_claims.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _base_outcome_label(label_type: str) -> dict[str, object]:
    row: dict[str, object] = {
        "outcome_id": f"OUT-{label_type}",
        "forecast_claim_id": "FC-PROXY-CONTRACT",
        "forecast_family_id": "FF-PROXY-CONTRACT",
        "claim_window_set_id": f"WSET-{label_type}",
        "entry_datetime": "2026-01-03T00:00:00+08:00",
        "exit_datetime": "2026-01-08T00:00:00+08:00",
        "horizon_days": 5 if label_type == "stock_price_proxy" else 20,
        "relative_alpha": 0.01,
        "directional_hit": True,
        "after_cost_alpha": 0.008 if label_type == "stock_price_proxy" else 0.009,
        "overlap_group_id": f"OVL-{label_type}",
        "effective_n_weight": 0.2 if label_type == "stock_price_proxy" else 0.25,
        "pit_valid": True,
        "survivorship_safe": label_type != "stock_price_proxy",
        "label_type": label_type,
        "proxy_symbol": "000001.SZ"
        if label_type == "stock_price_proxy"
        else "SH512400",
        "benchmark_symbol": "SH510300",
        "benchmark_source": "cn_etf",
        "benchmark_family": "CSI300_ETF_PROXY",
        "benchmark_return": 0.01,
        "cost_model_id": "single_stock_round_trip_20bps_v1"
        if label_type == "stock_price_proxy"
        else "industry_etf_round_trip_10bps_v1",
        "entry_lag_trading_days": 1,
        "round_trip_cost": 0.002 if label_type == "stock_price_proxy" else 0.001,
        "directional_after_cost_return": 0.018
        if label_type == "stock_price_proxy"
        else 0.019,
        "relative_directional_hit": True,
        "outcome_label_source": "pit_stock_price_window"
        if label_type == "stock_price_proxy"
        else "pit_industry_etf_price_window",
        "llm_outcome_labeling_allowed": False,
        "performance_value_basis": "directional_after_cost_return",
        "direction_evaluated": "positive",
        "decision_basis": "directional_stock_return_and_relative_alpha"
        if label_type == "stock_price_proxy"
        else "absolute_proxy_return_direction",
        "window_role": "short",
        "source_horizon_days": 20,
        "source_horizon_bucket": "short",
        "claim_window_alignment": "within_source_horizon",
        "evaluation_policy": "stock_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
        if label_type == "stock_price_proxy"
        else "industry_etf_t_plus_1_multi_window_proxy_retains_long_horizon_evidence",
    }
    if label_type == "stock_price_proxy":
        row.update(
            {
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "stock_return": 0.02,
                "target_resolution_source": "metadata_ts_code",
                "metadata_ts_code": "000001.SZ",
                "llm_target_id": "",
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "entry_tradable": True,
                "exit_tradable": True,
                "entry_limit_locked": False,
                "exit_limit_locked": False,
                "entry_liquidity_check": "positive_volume_and_limit_lock_screen",
                "exit_liquidity_check": "positive_volume_and_limit_lock_screen",
            }
        )
    else:
        row.update(
            {
                "proxy_sector": "有色金属",
                "mapping_id": "IETF-PROXY-TEST",
                "mapping_version": 1,
                "mapping_confidence": "operator_seeded_exact_sector",
                "pit_availability_status": "available",
                "proxy_return": 0.02,
            }
        )
    return row


def test_report_outcome_label_schema_requires_proxy_contract_fields(
    tmp_path: Path,
):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir(parents=True)
    (schema_dir / "report_intelligence_report_outcome_label.schema.json").write_text(
        Path("schemas/report_intelligence_report_outcome_label.schema.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label.pop("benchmark_family")
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_report_outcome_label.schema.json",
        artifact_path="registry/report_intelligence/report_outcome_labels.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("benchmark_family: required" in failure for failure in record.failures)


def test_report_outcome_label_semantics_require_proxy_contract_fields(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label.pop("target_resolution_source")
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert record.item_count == 1
    assert any("target_resolution_source" in failure for failure in record.failures)


def test_report_outcome_label_semantics_accept_complete_proxy_contracts(
    tmp_path: Path,
):
    _write_proxy_outcome_labels(
        tmp_path,
        [
            _base_outcome_label("stock_price_proxy"),
            _base_outcome_label("industry_etf_proxy"),
        ],
    )

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == 2
    assert record.failures == ()


def test_report_outcome_label_semantics_trace_proxy_labels_to_forecast_claims(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    industry_label = _base_outcome_label("industry_etf_proxy")
    industry_label["forecast_claim_id"] = "FC-INDUSTRY-PROXY-CONTRACT"
    industry_label["claim_window_set_id"] = "WSET-industry-trace"
    _write_forecast_claims(
        tmp_path,
        [
            {
                "forecast_claim_id": stock_label["forecast_claim_id"],
                "claim_provenance": "source_grounded",
                "forecast_testability": "testable",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
                "source_span_ids": ["span-stock"],
            },
            {
                "forecast_claim_id": industry_label["forecast_claim_id"],
                "claim_provenance": "source_grounded",
                "forecast_testability": "testable",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
                "source_span_ids": ["span-industry"],
            },
        ],
    )
    _write_proxy_outcome_labels(tmp_path, [stock_label, industry_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted
    assert record.failures == ()


def test_report_outcome_label_semantics_reject_untraceable_stock_proxy_claim(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    missing_claim_label = dict(stock_label)
    missing_claim_label["outcome_id"] = "OUT-stock-missing-claim"
    missing_claim_label["forecast_claim_id"] = "FC-MISSING"
    missing_claim_label["claim_window_set_id"] = "WSET-stock-missing-claim"
    missing_claim_label["overlap_group_id"] = "OVL-stock-missing-claim"
    no_span_claim_label = dict(stock_label)
    no_span_claim_label["outcome_id"] = "OUT-stock-no-span-claim"
    no_span_claim_label["claim_window_set_id"] = "WSET-stock-no-span-claim"
    no_span_claim_label["overlap_group_id"] = "OVL-stock-no-span-claim"
    _write_forecast_claims(
        tmp_path,
        [
            {
                "forecast_claim_id": stock_label["forecast_claim_id"],
                "claim_provenance": "source_grounded",
                "forecast_testability": "testable",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
                "source_span_ids": [],
            },
        ],
    )
    _write_proxy_outcome_labels(tmp_path, [missing_claim_label, no_span_claim_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any("forecast_claim_id: not found" in failure for failure in record.failures)
    assert any(
        "stock proxy forecast claim must cite source_span_ids" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_bad_entry_exit_timing(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["exit_datetime"] = stock_label["entry_datetime"]
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any(
        "exit_datetime: must be after entry_datetime date" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_same_day_signal_entry(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    _write_forecast_claims(
        tmp_path,
        [
            {
                "forecast_claim_id": stock_label["forecast_claim_id"],
                "claim_provenance": "source_grounded",
                "forecast_testability": "testable",
                "signal_datetime": stock_label["entry_datetime"],
                "source_span_ids": ["span-stock"],
            },
        ],
    )
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any(
        "entry_datetime: must be after forecast signal_datetime date" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_cross_label_type_id_collisions(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    industry_label = _base_outcome_label("industry_etf_proxy")
    industry_label["claim_window_set_id"] = stock_label["claim_window_set_id"]
    industry_label["overlap_group_id"] = stock_label["overlap_group_id"]
    _write_proxy_outcome_labels(tmp_path, [stock_label, industry_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert record.item_count == 2
    assert any(
        "claim_window_set_id" in failure and "crosses label_type namespace" in failure
        for failure in record.failures
    )
    assert any(
        "overlap_group_id" in failure and "crosses label_type namespace" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_bad_window_policy_fields(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["horizon_days"] = 60
    stock_label["window_role"] = "short"
    stock_label["source_horizon_days"] = -1
    stock_label["claim_window_alignment"] = "llm_inferred_alignment"
    stock_label["decision_basis"] = "market_price_proxy"
    stock_label["evaluation_policy"] = "collapse_to_single_window"
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any("window_role: must be medium" in failure for failure in record.failures)
    assert any("source_horizon_days: must be >= 0" in failure for failure in record.failures)
    assert any("claim_window_alignment" in failure for failure in record.failures)
    assert any("decision_basis" in failure for failure in record.failures)
    assert any("evaluation_policy" in failure for failure in record.failures)


def test_report_outcome_label_semantics_reject_bad_effective_n_weights(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    industry_label = _base_outcome_label("industry_etf_proxy")
    stock_label["effective_n_weight"] = 0.9
    industry_label["effective_n_weight"] = 0.9
    _write_proxy_outcome_labels(tmp_path, [stock_label, industry_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any(
        "stock horizon_days=5" in failure and "must be 0.2" in failure
        for failure in record.failures
    )
    assert any(
        "industry window_role=short" in failure and "must be 0.25" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_window_set_weight_sum_above_one(
    tmp_path: Path,
):
    labels = []
    for horizon_days, window_role, weight in (
        (5, "short", 0.2),
        (20, "short", 0.25),
        (60, "medium", 0.25),
        (120, "long", 0.3),
        (120, "long", 0.3),
    ):
        label = _base_outcome_label("stock_price_proxy")
        label["outcome_id"] = f"OUT-stock_price_proxy-{horizon_days}-{len(labels)}"
        label["horizon_days"] = horizon_days
        label["window_role"] = window_role
        label["effective_n_weight"] = weight
        labels.append(label)
    _write_proxy_outcome_labels(tmp_path, labels)

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any(
        "effective_n_weight sum 1.300000 exceeds 1" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_accept_metadata_and_llm_stock_resolution(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["target_resolution_source"] = "metadata_and_llm_target_id"
    stock_label["metadata_ts_code"] = "000001.SZ"
    stock_label["llm_target_id"] = "000001.SZ"
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted
    assert record.failures == ()


def test_report_outcome_label_semantics_reject_bad_stock_target_resolution(
    tmp_path: Path,
):
    metadata_conflict = _base_outcome_label("stock_price_proxy")
    metadata_conflict["metadata_ts_code"] = "600000.SH"
    llm_conflict = _base_outcome_label("stock_price_proxy")
    llm_conflict["outcome_id"] = "OUT-stock-llm-conflict"
    llm_conflict["claim_window_set_id"] = "WSET-stock-llm-conflict"
    llm_conflict["overlap_group_id"] = "OVL-stock-llm-conflict"
    llm_conflict["target_resolution_source"] = "llm_target_id"
    llm_conflict["metadata_ts_code"] = "600000.SH"
    llm_conflict["llm_target_id"] = "000001.SZ"
    fund_like_proxy = _base_outcome_label("stock_price_proxy")
    fund_like_proxy["outcome_id"] = "OUT-stock-fund-like-proxy"
    fund_like_proxy["claim_window_set_id"] = "WSET-stock-fund-like-proxy"
    fund_like_proxy["overlap_group_id"] = "OVL-stock-fund-like-proxy"
    fund_like_proxy["proxy_symbol"] = "510300.SH"
    fund_like_proxy["metadata_ts_code"] = "510300.SH"
    _write_proxy_outcome_labels(
        tmp_path,
        [metadata_conflict, llm_conflict, fund_like_proxy],
    )

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any(
        "metadata_ts_code: must equal proxy_symbol" in failure
        for failure in record.failures
    )
    assert any(
        "conflicting ts_code cannot generate stock label" in failure
        for failure in record.failures
    )
    assert any(
        "proxy_symbol: must be ordinary stock ts_code" in failure
        for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_bad_benchmark_and_cost_policy(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["benchmark_symbol"] = "SH000300"
    stock_label["benchmark_source"] = "index"
    stock_label["benchmark_family"] = "CSI300_INDEX"
    stock_label["cost_model_id"] = "single_stock_round_trip_5bps_v1"
    stock_label["round_trip_cost"] = 0.0005
    stock_label["after_cost_alpha"] = 0.0095
    stock_label["directional_after_cost_return"] = 0.0195
    industry_label = _base_outcome_label("industry_etf_proxy")
    industry_label["cost_model_id"] = "industry_etf_round_trip_20bps_v1"
    industry_label["round_trip_cost"] = 0.002
    industry_label["after_cost_alpha"] = 0.008
    industry_label["directional_after_cost_return"] = 0.018
    _write_proxy_outcome_labels(tmp_path, [stock_label, industry_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any("benchmark_symbol: must be SH510300" in failure for failure in record.failures)
    assert any("benchmark_source: must be cn_etf" in failure for failure in record.failures)
    assert any(
        "benchmark_family: must be CSI300_ETF_PROXY" in failure
        for failure in record.failures
    )
    assert any(
        "cost_model_id: must be single_stock_round_trip_20bps_v1" in failure
        for failure in record.failures
    )
    assert any("round_trip_cost: must be 0.002" in failure for failure in record.failures)
    assert any(
        "cost_model_id: must be industry_etf_round_trip_10bps_v1" in failure
        for failure in record.failures
    )
    assert any("round_trip_cost: must be 0.001" in failure for failure in record.failures)


def test_report_outcome_label_semantics_reject_missing_label_type(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label.pop("label_type")
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert not record.accepted
    assert any("label_type" in failure for failure in record.failures)


def test_report_outcome_label_semantics_reject_unknown_label_type(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["label_type"] = "standard"
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert not record.accepted
    assert any("label_type" in failure for failure in record.failures)


def test_report_outcome_label_semantics_reject_proxy_math_mismatch(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["relative_alpha"] = 0.03
    stock_label["after_cost_alpha"] = 0.03
    stock_label["directional_hit"] = False
    stock_label["relative_directional_hit"] = False
    stock_label["directional_after_cost_return"] = 0.03
    stock_label["performance_value_basis"] = "relative_alpha"
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any("performance_value_basis" in failure for failure in record.failures)
    assert any("relative_alpha" in failure for failure in record.failures)
    assert any("after_cost_alpha" in failure for failure in record.failures)
    assert any("directional_hit" in failure for failure in record.failures)
    assert any("relative_directional_hit" in failure for failure in record.failures)
    assert any(
        "directional_after_cost_return" in failure for failure in record.failures
    )


def test_report_outcome_label_semantics_reject_invalid_stock_survivorship_check(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["survivorship_check"] = "unchecked"
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert not record.accepted
    assert any("survivorship_check" in failure for failure in record.failures)


def test_report_outcome_label_semantics_reject_untradable_stock_label(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label["entry_tradable"] = False
    stock_label["entry_limit_locked"] = True
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert not record.accepted
    assert any("entry_tradable" in failure for failure in record.failures)
    assert any("entry_limit_locked" in failure for failure in record.failures)


def test_report_outcome_label_semantics_reject_bad_target_price_fields(
    tmp_path: Path,
):
    stock_label = _base_outcome_label("stock_price_proxy")
    stock_label.update(
        {
            "target_price": 1.2,
            "target_price_hit": True,
            "target_price_entry_price": 1.0,
            "target_price_eval_price": 1.1,
            "target_price_source_grounded": False,
            "target_price_provenance": "",
            "target_price_hit_policy": "llm_judged_target_price",
        }
    )
    _write_proxy_outcome_labels(tmp_path, [stock_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert not record.accepted
    assert any("target_price_hit" in failure for failure in record.failures)
    assert any("target_price_source_grounded" in failure for failure in record.failures)
    assert any("target_price_provenance" in failure for failure in record.failures)
    assert any("target_price_hit_policy" in failure for failure in record.failures)


def test_industry_etf_mapping_contract_accepts_current_public_artifacts(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)

    record = _industry_etf_mapping_contract_record(tmp_path)
    mapping_rows = [
        json.loads(line)
        for line in (registry / "industry_etf_proxy_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    availability = json.loads(
        (registry / "industry_etf_proxy_pit_availability.json").read_text(
            encoding="utf-8"
        )
    )
    industry_label_count = sum(
        1
        for line in (registry / "report_outcome_labels.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and json.loads(line).get("label_type") == "industry_etf_proxy"
    )

    assert record.accepted
    assert len(mapping_rows) == 64
    assert record.item_count == (
        len(mapping_rows)
        + len(availability["mapping_records"])
        + industry_label_count
        + 1
    )
    assert record.failures == ()


def test_industry_etf_mapping_keeps_industrial_metals_proxy_on_sh560860(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    registry_rows = [
        json.loads(line)
        for line in (registry / "industry_etf_proxy_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    default_by_sector = {
        row["sector_name"]: row for row in build_default_industry_etf_proxy_map_rows()
    }
    registry_by_sector = {row["sector_name"]: row for row in registry_rows}

    assert default_by_sector["工业金属"]["etf_symbol"] == "SH560860"
    assert default_by_sector["工业金属"]["mapping_label"] == "工业有色ETF"
    assert registry_by_sector["工业金属"]["etf_symbol"] == "SH560860"


def test_industry_etf_mapping_covers_historical_industry_report_sectors(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    registry_rows = [
        json.loads(line)
        for line in (registry / "industry_etf_proxy_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    default_by_sector = {
        row["sector_name"]: row for row in build_default_industry_etf_proxy_map_rows()
    }
    registry_by_sector = {row["sector_name"]: row for row in registry_rows}
    expected = {
        "煤炭采选": "SH515220",
        "环保工程": "SH512580",
        "机械行业": "SH516960",
        "电子信息": "SH515260",
        "物流行业": "SH516910",
        "钢铁行业": "SH515210",
        "石油行业": "SH561360",
        "汽车整车": "SZ159512",
        "中药": "SH560080",
        "电力行业": "SZ159611",
        "酿酒行业": "SH512690",
        "文化传媒": "SH512980",
        "食品饮料": "SH515170",
        "互联网服务": "SZ159729",
    }

    for sector, etf_symbol in expected.items():
        assert default_by_sector[sector]["etf_symbol"] == etf_symbol
        assert registry_by_sector[sector]["etf_symbol"] == etf_symbol


def test_industry_etf_mapping_contract_requires_pit_availability_records(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["mapping_records"].pop()
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any("missing mapping_ids" in item for item in record.failures)
    assert any("pit_available_mapping_count mismatch" in item for item in record.failures)


def test_industry_etf_pit_availability_schema_requires_plan_fields(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["mapping_records"][0].pop("has_120d_window", None)
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_industry_etf_proxy_pit_availability.schema.json",
        artifact_path="registry/report_intelligence/industry_etf_proxy_pit_availability.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any("has_120d_window: required" in item for item in record.failures)


def test_industry_etf_mapping_contract_requires_plan_pit_record_fields(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["mapping_records"][0].pop("latest_calendar_date", None)
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any("latest_calendar_date: required" in item for item in record.failures)


def test_industry_etf_mapping_contract_rejects_local_calendar_paths(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["qlib_etf_dir_configured"] = "/home/hap/.qlib/qlib_data/cn_etf"
    availability["mapping_records"][0]["calendar_source"] = (
        "/home/hap/.qlib/qlib_data/cn_etf"
    )
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "calendar_source: must use public qlib source label" in item
        for item in record.failures
    )
    assert any(
        "qlib_etf_dir_configured: must use public qlib source label" in item
        for item in record.failures
    )


def test_industry_etf_mapping_contract_rejects_local_readiness_paths(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["industry_etf_proxy_readiness"]["qlib_etf_dir_configured"] = (
        "/home/hap/.qlib/qlib_data/cn_etf"
    )
    readiness["stock_price_proxy_readiness"]["qlib_stock_dir_configured"] = (
        "/home/hap/.qlib/qlib_data/cn_data"
    )
    readiness["stock_price_proxy_readiness"]["qlib_benchmark_dir_configured"] = (
        "/home/hap/.qlib/qlib_data/cn_etf"
    )
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "industry_etf_proxy_readiness.qlib_etf_dir_configured: "
        "must use public qlib source label" in item
        for item in record.failures
    )
    assert any(
        "stock_price_proxy_readiness.qlib_stock_dir_configured: "
        "must use public qlib source label" in item
        for item in record.failures
    )
    assert any(
        "stock_price_proxy_readiness.qlib_benchmark_dir_configured: "
        "must use public qlib source label" in item
        for item in record.failures
    )


def test_industry_etf_mapping_contract_rejects_labelability_readiness_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["labelability_summary"]["eligible_claim_count"] += 1
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "labelability_summary.eligible_claim_count: "
        "outcome_labeling_readiness mismatch" in item
        for item in record.failures
    )


def test_industry_etf_mapping_contract_rejects_labelability_gap_count_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["labelability_summary"]["data_gap_counts"] = {}
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "labelability_summary.data_gap_counts: outcome_labeling_readiness mismatch"
        in item
        for item in record.failures
    )


def test_industry_etf_mapping_contract_rejects_unavailable_mapping_label(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    mapping = json.loads(
        (registry / "industry_etf_proxy_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    for record in availability["mapping_records"]:
        if record["mapping_id"] == mapping["mapping_id"]:
            record["pit_available"] = False
            record["pit_gap_reasons"] = ["proxy_series_missing"]
            break
    availability["pit_available_mapping_count"] = sum(
        1
        for record in availability["mapping_records"]
        if record.get("pit_available") is True
    )
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    label = _base_outcome_label("industry_etf_proxy")
    label.update(
        {
            "benchmark_family": mapping["benchmark_family"],
            "benchmark_source": mapping["benchmark_source"],
            "benchmark_symbol": mapping["benchmark_symbol"],
            "cost_model_id": mapping["cost_model_id"],
            "mapping_confidence": mapping["mapping_confidence"],
            "mapping_id": mapping["mapping_id"],
            "mapping_version": mapping["mapping_version"],
            "pit_availability_status": "available",
            "proxy_sector": mapping["sector_name"],
            "proxy_symbol": mapping["etf_symbol"],
        }
    )
    _write_proxy_outcome_labels(tmp_path, [label])

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any("cannot label PIT-unavailable mapping" in item for item in record.failures)
    assert any("pit_availability_status" in item for item in record.failures)


def test_markdown_coverage_privacy_rules_reject_public_pdf_url(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["pdf_url"] = "https://example.invalid/private-report.pdf"
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path
        == "schemas/report_intelligence_markdown_coverage_privacy_rules"
    )

    assert not record.accepted
    assert any("pdf_url" in failure for failure in record.failures)


def test_markdown_coverage_privacy_rules_require_strata_blockers(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["selected_report_count"] = 0
    coverage["coverage_gate_blockers"] = [
        blocker
        for blocker in coverage["coverage_gate_blockers"]
        if blocker != "selected_report_count_below_p9_target"
    ]
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path
        == "schemas/report_intelligence_markdown_coverage_privacy_rules"
    )

    assert not record.accepted
    assert any(
        "selected_report_count_below_p9_target" in failure
        for failure in record.failures
    )


def test_markdown_coverage_privacy_rules_require_strata_missing_entries(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["time_bucket_counts"] = {
        key: value
        for key, value in coverage["time_bucket_counts"].items()
        if key != "recent_1y"
    }
    coverage["coverage_strata_missing"] = [
        item
        for item in coverage["coverage_strata_missing"]
        if item != "time_bucket:recent_1y"
    ]
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path
        == "schemas/report_intelligence_markdown_coverage_privacy_rules"
    )

    assert not record.accepted
    assert any("time_bucket:recent_1y" in failure for failure in record.failures)


def test_markdown_coverage_privacy_rules_require_sector_gap_entries(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["sector_bucket_counts"] = {"tiny_sector": 1}
    coverage["sector_bucket_coverage_gaps"] = []
    coverage["sector_bucket_below_min_count"] = 0
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path
        == "schemas/report_intelligence_markdown_coverage_privacy_rules"
    )

    assert not record.accepted
    assert any("sector_bucket:tiny_sector" in failure for failure in record.failures)
    assert any("sector_bucket_below_min_count" in failure for failure in record.failures)


def test_recipe_paper_trading_contract_accepts_current_public_artifacts(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)

    record = _recipe_paper_trading_contract_record(tmp_path)
    run_count = sum(
        1
        for line in (registry / "recipe_paper_trading_runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
    observation_count = sum(
        1
        for line in (registry / "confidence_impact_observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )

    assert record.accepted
    assert record.item_count == run_count + observation_count + 2
    assert record.failures == ()


def test_recipe_paper_trading_contract_rejects_confidence_bypass(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[0]["paper_trading_status"] = "passed"
    observations[0]["confidence_delta"] = 0.02
    observations[0]["production_decision_impact_allowed"] = True
    observations_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in observations
        )
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("paper_trading_status: mismatch" in item for item in record.failures)
    assert any("confidence_delta" in item for item in record.failures)
    assert any(
        "production_decision_impact_allowed" in item for item in record.failures
    )


def test_recipe_paper_trading_contract_rejects_missing_confidence_monitor_field(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[0].pop("calibration_error", None)
    observations_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in observations
        )
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "confidence_impact_observations row 1.calibration_error: required" in item
        for item in record.failures
    )


def test_recipe_paper_trading_contract_rejects_regime_monitor_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[0]["regime"] = "manual_override"
    observations[0]["regime_contribution_shares"] = {"manual_override": 1.0}
    observations_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in observations
        )
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "confidence_impact_observations row 1.regime: mismatch" in item
        for item in record.failures
    )
    assert any(
        "confidence_impact_observations row 1.regime_contribution_shares: mismatch"
        in item
        for item in record.failures
    )


def test_recipe_paper_trading_contract_rejects_monitor_action_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitor_path = registry / "confidence_impact_monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
    monitor["recommended_action_counts"] = {"keep_shadow": 4}
    monitor["tracked_recipe_ids"] = monitor["tracked_recipe_ids"][:-1]
    monitor_path.write_text(
        json.dumps(monitor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("recommended_action_counts mismatch" in item for item in record.failures)
    assert any("tracked_recipe_ids mismatch" in item for item in record.failures)


def test_recipe_paper_trading_contract_rejects_run_summary_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["paper_trading_status"] = "passed"
    runs[0]["validation_status"] = "blocked"
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("validation_status" in item for item in record.failures)
    assert any("passed run must have no blockers" in item for item in record.failures)
    assert any("validation_pass_count" in item for item in record.failures)


def test_recipe_paper_trading_contract_rejects_summary_protocol_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    summary_path = registry / "recipe_paper_trading_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["validation_protocol"]["out_of_sample_fraction"] = 0.5
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "validation_protocol.out_of_sample_fraction: must be 0.2" in item
        for item in record.failures
    )


def test_recipe_paper_trading_contract_rejects_preregistration_payload_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["decision_scope"] = "post_result_rewritten_scope"
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("pre_registration_hash: mismatch" in item for item in record.failures)


def test_recipe_paper_trading_contract_rejects_raw_required_data_persistence(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["required_data"] = [
        item.removeprefix("metric:") for item in runs[0]["required_data"]
    ]
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "required_data: must persist normalized" in item for item in record.failures
    )


def test_recipe_paper_trading_run_schema_requires_plan_metrics(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["metrics"].pop("alpha_decay_slope", None)
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/report_intelligence_recipe_paper_trading_run.schema.json",
        artifact_path="registry/report_intelligence/recipe_paper_trading_runs.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("metrics.alpha_decay_slope: required" in item for item in record.failures)


def test_recipe_paper_trading_contract_rejects_missing_plan_metric(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["metrics"].pop("calibration_error", None)
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("metrics.calibration_error: required" in item for item in record.failures)


def test_recipe_paper_trading_contract_rejects_passed_run_without_oos_alpha(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["paper_trading_status"] = "passed"
    runs[0]["validation_status"] = "passed"
    runs[0]["blocked_reasons"] = []
    metrics = runs[0]["metrics"]
    metrics["effective_n"] = 5.0
    metrics["cost_adjusted_alpha"] = 0.01
    metrics["out_of_sample_effective_n"] = 1.0
    metrics["out_of_sample_cost_adjusted_alpha"] = -0.001
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "out_of_sample_cost_adjusted_alpha" in item for item in record.failures
    )


def test_recipe_paper_trading_contract_rejects_instability_without_gap(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[0]["blocked_reasons"] = [
        *runs[0]["blocked_reasons"],
        "single_window_concentration",
    ]
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "instability blockers require recipe_instability_gap" in item
        for item in record.failures
    )


def test_patch_coverage_rules_reject_stale_public_corpus_counts(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "patch_v1_5_coverage_report.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["corpus_counts"]["method_pattern_rows"] = 0
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path == "schemas/report_intelligence_patch_v1_5_coverage_rules"
    )

    assert not record.accepted
    assert any(
        "corpus_counts.method_pattern_rows: expected" in failure
        for failure in record.failures
    )


def test_patch_coverage_rules_reject_stale_phase_g_paper_trading_counts(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "patch_v1_5_coverage_report.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    for row in coverage["phase_records"]:
        if row["phase_id"] == "G":
            row["evidence_counts"]["shadow_paper_trading_run_count"] = 0
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path == "schemas/report_intelligence_patch_v1_5_coverage_rules"
    )

    assert not record.accepted
    assert any(
        "Phase G: evidence_counts.shadow_paper_trading_run_count expected" in failure
        for failure in record.failures
    )


def test_evolution_refresh_history_rejects_accepted_aggregate_calibration_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    history_path = registry / "monitor_refresh_history.jsonl"
    rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0]["accepted"] = True
    rows[0]["blocked_recipe_count"] = 0
    rows[0]["blocker_counts"] = {}
    rows[0]["aggregate_calibration_drift_count"] = 1
    rows[0]["calibration_drift_rule_counts"] = {
        "negative_confidence_alpha_correlation": 1
    }
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )

    record = _evolution_refresh_history_record(tmp_path)

    assert not record.accepted
    assert any(
        "accepted: must match unvalidated confidence impact and aggregate calibration drift fields"
        in item
        for item in record.failures
    )


def test_evolution_refresh_history_rejects_stale_gap_distribution_state(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    history_path = registry / "gap_distribution_history.jsonl"
    rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0]["gap_counts"] = {"horizon": 10}
    rows[0]["total_gap_count"] = 1
    rows[0]["max_gap_name"] = "target"
    rows[0]["max_gap_share"] = 0.10
    rows[0]["stable"] = True
    rows[0]["accepted"] = True
    rows[0]["private_text_included"] = True
    history_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )

    record = _evolution_refresh_history_record(tmp_path)

    assert not record.accepted
    assert any("total_gap_count: expected 10" in item for item in record.failures)
    assert any("max_gap_name: expected horizon" in item for item in record.failures)
    assert any("max_gap_share: expected 1.0" in item for item in record.failures)
    assert any("stable: expected False" in item for item in record.failures)
    assert any("accepted: expected False" in item for item in record.failures)
    assert any("private_text_included: must be false" in item for item in record.failures)


def test_evolution_refresh_history_requires_data_vintage_hash(tmp_path: Path):
    cases = (
        ("monitor_refresh_history.jsonl", "monitor_refresh_history row 1"),
        ("audit_refresh_history.jsonl", "audit_refresh_history row 1"),
        ("gap_distribution_history.jsonl", "gap_distribution_history row 1"),
    )
    for filename, row_label in cases:
        case_dir = tmp_path / filename.replace(".jsonl", "")
        case_dir.mkdir()
        registry = _copy_report_intelligence_registry(case_dir)
        history_path = registry / filename
        rows = [
            json.loads(line)
            for line in history_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows[0].pop("data_vintage_hash", None)
        history_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
            + "\n",
            encoding="utf-8",
        )

        record = _evolution_refresh_history_record(case_dir)

        assert not record.accepted
        assert any(
            f"{row_label}.data_vintage_hash" in item for item in record.failures
        )


def test_evolution_readiness_gate_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_report_intelligence_registry(tmp_path)

    record = _evolution_readiness_gate_record(tmp_path)

    assert record.accepted
    assert record.item_count == 7
    assert record.failures == ()


def test_evolution_readiness_gate_contract_requires_all_checks(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["checks"] = [
        check for check in gate["checks"] if check["check_id"] != "RI-EVOL-05"
    ]
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any("missing check_ids: RI-EVOL-05" in item for item in record.failures)
    assert any("blockers mismatch with checks" in item for item in record.failures)


def test_evolution_readiness_gate_contract_rejects_blocker_count_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["blocker_count"] = 0
    gate["gate_status"] = "passed"
    gate["promotion_state"] = "ready_for_shadow_evolution_candidate"
    for check in gate["checks"]:
        if check.get("check_id") == "RI-EVOL-05":
            check["passed"] = True
            break
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any("blocker_count: expected" in item for item in record.failures)
    assert any("gate_status: expected blocked" in item for item in record.failures)
    assert any("passed: must be False based on blockers" in item for item in record.failures)


def test_evolution_readiness_gate_contract_rejects_tampered_outcome_thresholds(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    outcome_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-01"
    )
    outcome_check["evidence"]["stock_proxy_unique_claim_count"] = 1
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "RI-EVOL-01].evidence.stock_proxy_unique_claim_count: expected >= 30"
        in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_tampered_paper_trading_summary(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    paper_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-02"
    )
    after_cost = paper_check["evidence"]["after_cost_paper_trading_summary"]
    after_cost["status"] = "missing"
    after_cost["validated_recipe_count"] = 0
    after_cost["positive_after_cost_recipe_count"] = 0
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "RI-EVOL-02].evidence.after_cost_paper_trading_summary.status: expected computed"
        in item
        for item in record.failures
    )
    assert any(
        "after_cost_paper_trading_summary.validated_recipe_count: expected >= 20"
        in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_tampered_monitor_stability(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    monitor_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-03"
    )
    monitor_check["evidence"]["trailing_monitor_pass_count"] = 1
    monitor_check["evidence"]["unvalidated_confidence_impact_count"] = 1
    monitor_check["evidence"]["aggregate_calibration_drift_count"] = 1
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "RI-EVOL-03].evidence.trailing_monitor_pass_count: expected >= 3" in item
        for item in record.failures
    )
    assert any(
        "RI-EVOL-03].evidence.unvalidated_confidence_impact_count: expected 0"
        in item
        for item in record.failures
    )
    assert any(
        "RI-EVOL-03].evidence.aggregate_calibration_drift_count: expected 0" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_missing_current_audit_blocker(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    audit_check["evidence"]["schema_accepted"] = False
    audit_check["blockers"] = [
        blocker
        for blocker in audit_check["blockers"]
        if blocker != "current_schema_or_audit_gate_blocked"
    ]
    gate["blockers"] = sorted(
        {
            blocker
            for check in gate["checks"]
            for blocker in check.get("blockers", [])
        }
    )
    gate["blocker_count"] = len(gate["blockers"])
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "must include current_schema_or_audit_gate_blocked" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_stale_audit_dependency(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    audit_check["evidence"]["audit_history_dependency"] = {
        "blocking_components": [],
        "history_counts_only_passing_current_audits": True,
        "min_consecutive_audit_refreshes": 3,
        "next_action": "run_distinct_derived_refreshes_after_current_audits_pass",
        "refresh_without_current_audit_pass_can_satisfy_history": False,
        "status": "history_below_threshold",
        "trailing_audit_pass_count": 0,
    }
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "audit_history_dependency.blocking_components mismatch" in item
        for item in record.failures
    )
    assert any(
        "audit_history_dependency.status: expected current_gate_blocked" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_stale_audit_history_blocker(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    audit_check["evidence"]["trailing_audit_distinct_vintage_count"] = 3
    audit_check["evidence"]["trailing_audit_pass_count"] = 3
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "audit_refresh_history_below_threshold not allowed" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_tampered_gold_metrics(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gold_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-05"
    )
    original_blockers = set(gold_check["blockers"])
    gold_check["blockers"] = []
    gold_check["passed"] = True
    gold_check["evidence"]["gold_set_passed"] = True
    gold_check["evidence"]["review_complete"] = True
    gold_check["evidence"]["pending_claims"] = 0
    gold_check["evidence"]["reviewed_claims"] = 500
    gold_check["evidence"]["metrics"]["claim_precision"] = 0.50
    gold_check["evidence"]["metrics"]["unsupported_field_false_grounding_rate"] = 0.20
    gate["blockers"] = [
        blocker
        for blocker in gate["blockers"]
        if blocker not in original_blockers
    ]
    gate["blocker_count"] = len(gate["blockers"])
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "RI-EVOL-05].evidence.metrics.claim_precision: expected >= 0.85" in item
        for item in record.failures
    )
    assert any(
        "unsupported_field_false_grounding_rate: expected <= 0.05" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_unexplained_stock_conflicts(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gold_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-05"
    )
    original_blockers = set(gold_check["blockers"])
    gold_check["blockers"] = []
    gold_check["passed"] = True
    gold_check["evidence"]["gold_set_passed"] = True
    gold_check["evidence"]["review_complete"] = True
    gold_check["evidence"]["pending_claims"] = 0
    gold_check["evidence"]["reviewed_claims"] = 500
    gold_check["evidence"]["stock_target_conflict_count"] = 2
    gold_check["evidence"]["stock_target_conflict_reviewed_count"] = 1
    gold_check["evidence"]["stock_target_conflict_explained"] = False
    for metric, value in {
        "claim_precision": 0.90,
        "direction_accuracy": 0.90,
        "horizon_accuracy": 0.90,
        "source_span_support_precision": 0.95,
        "target_accuracy": 0.90,
        "unsupported_field_false_grounding_rate": 0.01,
        "variable_mapping_accuracy": 0.85,
    }.items():
        gold_check["evidence"]["metrics"][metric] = value
    gate["blockers"] = [
        blocker
        for blocker in gate["blockers"]
        if blocker not in original_blockers
    ]
    gate["blocker_count"] = len(gate["blockers"])
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "stock_target_conflict_explained: must be true when conflicts exist"
        in item
        for item in record.failures
    )
    assert any(
        "stock_target_conflict_reviewed_count: expected >= stock_target_conflict_count"
        in item
        for item in record.failures
    )


def test_gold_review_gate_contract_accepts_current_public_artifact(tmp_path: Path):
    _copy_gold_review_summary(tmp_path)

    record = _gold_review_gate_record(tmp_path)

    assert record.accepted
    assert record.item_count == 1
    assert record.failures == ()


def test_gold_review_gate_contract_rejects_false_pass(tmp_path: Path):
    summary_path = _copy_gold_review_summary(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["passed"] = True
    summary["blockers"] = []
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _gold_review_gate_record(tmp_path)

    assert not record.accepted
    assert any("blocked review requires blockers" in item for item in record.failures)
    assert any("passed: requires review_complete=true" in item for item in record.failures)
    assert any("passed: requires pending_claims=0" in item for item in record.failures)
    assert any("metrics: expected object" in item for item in record.failures)


def test_gold_review_gate_contract_rejects_count_or_metric_drift(tmp_path: Path):
    summary_path = _copy_gold_review_summary(tmp_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        {
            "blockers": [],
            "metrics": {
                "claim_precision": 0.50,
                "direction_accuracy": 0.90,
                "horizon_accuracy": 0.90,
                "source_span_support_precision": 0.95,
                "target_accuracy": 0.90,
                "unsupported_field_false_grounding_rate": 0.20,
                "variable_mapping_accuracy": 0.85,
            },
            "passed": True,
            "pending_claims": 0,
            "review_complete": True,
            "reviewed_claims": 499,
            "total_claims": 500,
            "total_documents": 49,
        }
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _gold_review_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "reviewed_claims + pending_claims must equal total_claims" in item
        for item in record.failures
    )
    assert any("reviewed_claims: expected >= 500" in item for item in record.failures)
    assert any("total_documents: expected >= 50" in item for item in record.failures)
    assert any("metrics.claim_precision: expected >= 0.85" in item for item in record.failures)
    assert any(
        "unsupported_field_false_grounding_rate: expected <= 0.05" in item
        for item in record.failures
    )


def _read_prompt_mutation_candidates(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_prompt_mutation_candidates(
    path: Path,
    rows: list[dict[str, object]],
) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def test_prompt_mutation_candidate_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_report_intelligence_registry(tmp_path)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == 11
    assert record.failures == ()


def test_prompt_mutation_candidate_contract_rejects_production_prompt_bypass(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidates[0]["production_prompt_change_allowed"] = True
    candidates[0]["promotion_state"] = "ready_for_production"
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("production_prompt_change_allowed: must be false" in item for item in record.failures)
    assert any("promotion_state: must remain shadow_candidate_only" in item for item in record.failures)


def test_prompt_mutation_candidate_contract_rejects_private_source_text(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidates[0]["private_text_included"] = True
    candidates[0]["claim_text"] = "private licensed report prose"
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("private_text_included: must be false" in item for item in record.failures)
    assert any("claim_text: private/source text field forbidden" in item for item in record.failures)


def test_prompt_mutation_candidate_contract_requires_manual_blocked_shadow_review(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidates[0]["manual_review_required"] = False
    candidates[0]["blocked_by"] = []
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("manual_review_required: must be true" in item for item in record.failures)
    assert any("blocked_by: required while evolution gate is blocked" in item for item in record.failures)


def test_prompt_mutation_candidate_contract_requires_full_validation_matrix(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidates[0]["validation_requirements"] = [
        requirement
        for requirement in candidates[0]["validation_requirements"]
        if requirement != "shadow_paper_trading_pass"
    ]
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("validation_requirements: must be" in item for item in record.failures)
    assert any("shadow_paper_trading_pass" in item for item in record.failures)


def test_prompt_mutation_candidate_contract_requires_existing_public_evidence(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidates[0]["evidence_refs"] = []
    candidates[1]["evidence_refs"] = [
        {
            "artifact_path": (
                "registry/report_intelligence/nonexistent_public_summary.json"
            )
        }
    ]
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("evidence_refs: at least one evidence ref required" in item for item in record.failures)
    assert any(
        "referenced public evidence artifact must exist" in item
        for item in record.failures
    )


def test_prompt_mutation_candidate_contract_rejects_private_evidence_paths(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidates[0]["evidence_refs"] = [
        {"artifact_path": "registry/report_intelligence/forecast_claims.jsonl"},
        {"artifact_path": "registry/report_intelligence/markdown/private.md"},
        {"artifact_path": "/home/hap/private/report.json"},
    ]
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("private evidence path forbidden" in item for item in record.failures)
    assert any("artifact_path: must be repo-relative" in item for item in record.failures)
    assert any(
        "artifact_path: must point to a public RKE aggregate artifact" in item
        for item in record.failures
    )


def _copy_registry_for_manual_progress(tmp_path: Path) -> Path:
    registry = tmp_path / "registry"
    shutil.copytree(Path("registry"), registry, dirs_exist_ok=True)
    return registry


def test_manual_review_progress_privacy_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_registry_for_manual_progress(tmp_path)

    record = _manual_review_progress_privacy_record(tmp_path)

    assert record.accepted
    assert record.item_count == 4
    assert record.failures == ()


def test_manual_review_progress_privacy_allows_missing_field_count_names(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["gates"][0]["current_batch_status"]["missing_required_fields"][
        "manual_claim_text"
    ] = 500
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_privacy_record(tmp_path)

    assert record.accepted


def test_manual_review_progress_privacy_rejects_private_text_fields(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["gates"][0]["claim_text"] = "private licensed report prose"
    progress["gates"][0]["current_batch_status"]["manual_claim_text"] = (
        "private reviewer text"
    )
    progress["gates"][0]["source_span_ids"] = ["span-private-1"]
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_privacy_record(tmp_path)

    assert not record.accepted
    assert any("claim_text: private/source text field forbidden" in item for item in record.failures)
    assert any("manual_claim_text: private/source text field forbidden" in item for item in record.failures)
    assert any("source_span_ids: private/source text field forbidden" in item for item in record.failures)


def test_manual_review_progress_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress = json.loads(
        (registry / "review_batches/manual_review_progress_report.json").read_text(
            encoding="utf-8"
        )
    )
    gold_evidence = progress["gates"][0]["current_batch_status"]["evidence_status"]
    footprint_evidence = progress["gates"][1]["current_batch_status"][
        "evidence_status"
    ]

    record = _manual_review_progress_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == 4
    assert record.failures == ()
    assert gold_evidence["aligned"] is True
    assert gold_evidence["covered_review_rows"] == gold_evidence["review_input_rows"]
    assert footprint_evidence["aligned"] is True
    assert (
        footprint_evidence["covered_review_rows"]
        == footprint_evidence["review_input_rows"]
    )


def test_manual_review_progress_contract_accepts_completed_gate_state(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["ready_for_promotion_dry_run"] = True
    progress["blockers"] = []
    for gate in progress["gates"]:
        gate["complete_rows"] = gate["target_rows"]
        gate["pending_rows"] = 0
        gate["ready_for_promotion"] = True
        gate["simulation_accepted"] = True
        gate["blockers"] = []
        gate["current_batch_status"] = {}
        gate["batch_plan"] = []
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == 4
    assert record.failures == ()


def test_manual_review_progress_contract_rejects_tampered_ready_state(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["ready_for_promotion_dry_run"] = True
    progress["blockers"] = []
    progress["gates"][0]["ready_for_promotion"] = True
    progress["gates"][0]["simulation_accepted"] = True
    progress["gates"][0]["blockers"] = ["still blocked"]
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "ready_for_promotion_dry_run: expected False" in item
        for item in record.failures
    )
    assert any("blockers: must be non-empty" in item for item in record.failures)
    assert any(
        "gates[gold_set].pending_rows: ready gate must be zero" in item
        for item in record.failures
    )
    assert any("ready gate must not block" in item for item in record.failures)


def test_manual_review_progress_contract_rejects_count_or_command_drift(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["gates"][1]["pending_rows"] = 0
    progress["gates"][1]["complete_rows"] = 1
    progress["gates"][1]["target_rows"] = 1001
    progress["gates"][1]["prepare_command"] = "mosaic-rke prepare-footprint-review --root ."
    progress["gates"][1]["dry_run_command"] = (
        "MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke "
        "mosaic-rke apply-footprint-review --root ."
    )
    progress["gates"][1]["apply_command"] = (
        "MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke "
        "mosaic-rke apply-footprint-review --root . "
        "--input registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    progress["gates"][1]["current_batch_status"]["pending_rows"] = 49
    progress["gates"][1]["batch_plan"][0]["offset"] = 50
    progress["gates"][1]["batch_plan"][0]["apply_effect"] = "replace_promotion_input"
    progress["gates"][1]["batch_plan"][0]["promotion_input_path"] = (
        "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    progress["gates"][1]["batch_plan"][0]["commands"]["apply"] = (
        "MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke TMPDIR=/home/hap/tmp/mosaic-rke "
        "mosaic-rke apply-footprint-review --root . "
        "--input registry/report_intelligence/analytical_footprint_reviewed.jsonl"
    )
    progress["gates"][1]["batch_plan"][0]["commands"]["dry_run"] = (
        progress["gates"][1]["batch_plan"][0]["commands"]["dry_run"].replace(
            "--dry-run",
            "",
        )
    )
    progress["gates"][1]["batch_plan"][0]["commands"]["evidence"] = (
        progress["gates"][1]["batch_plan"][0]["commands"]["evidence"].replace(
            "--offset 0",
            "--offset 50",
        )
    )
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_contract_record(tmp_path)

    assert not record.accepted
    assert any("complete_rows + pending_rows must equal target_rows" in item for item in record.failures)
    assert any("prepare_command: missing MOSAIC_RKE_TMPDIR prefix" in item for item in record.failures)
    assert any("prepare_command: missing TMPDIR prefix" in item for item in record.failures)
    assert any("dry_run_command: must include --dry-run" in item for item in record.failures)
    assert any("dry_run_command: expected promotion input" in item for item in record.failures)
    assert any("apply_command: expected promotion input" in item for item in record.failures)
    assert any(
        "current_batch_status: complete + pending + malformed must equal rows" in item
        for item in record.failures
    )
    assert any("batch_plan[1].offset: expected 0" in item for item in record.failures)
    assert any("batch_plan[1].apply_effect" in item for item in record.failures)
    assert any("batch_plan[1].promotion_input_path" in item for item in record.failures)
    assert any("batch_plan[1].commands.dry_run: must include --dry-run" in item for item in record.failures)
    assert any("batch_plan[1].commands.apply: expected batch input" in item for item in record.failures)
    assert any("batch_plan[1].commands.apply: must not use promotion input" in item for item in record.failures)


def test_manual_review_progress_contract_rejects_bad_evidence_alignment(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    evidence = progress["gates"][0]["current_batch_status"]["evidence_status"]
    evidence["aligned"] = True
    evidence["covered_review_rows"] = 49
    evidence["missing_review_rows"] = 1
    evidence["same_order"] = False
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "evidence_status.same_order: aligned evidence must be in review input order"
        in item
        for item in record.failures
    )
    assert any(
        "evidence_status.covered_review_rows: aligned evidence must cover every review row"
        in item
        for item in record.failures
    )
    assert any(
        "evidence_status.missing_review_rows: aligned evidence must have zero gaps"
        in item
        for item in record.failures
    )


def test_operator_readiness_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_registry_for_manual_progress(tmp_path)

    record = _operator_readiness_record(tmp_path)

    assert record.accepted
    assert record.item_count == 18
    assert record.failures == ()


def test_operator_readiness_contract_rejects_missing_gate_check(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    readiness_path = registry / "handoffs/rke_operator_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["checks"] = [
        check
        for check in readiness["checks"]
        if check["check_id"] != "blank_bundle_dry_run_does_not_promote"
    ]
    readiness["check_count"] = len(readiness["checks"])
    readiness["passed_count"] = len(readiness["checks"])
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_readiness_record(tmp_path)

    assert not record.accepted
    assert any(
        "missing check_ids: blank_bundle_dry_run_does_not_promote" in item
        for item in record.failures
    )


def test_operator_readiness_contract_rejects_false_acceptance(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    readiness_path = registry / "handoffs/rke_operator_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    expected_passed_count = int(readiness["check_count"]) - 1
    readiness["checks"][0]["passed"] = False
    readiness["checks"][0]["blocker"] = "fixture blocker"
    readiness["accepted"] = True
    readiness["passed_count"] = readiness["check_count"]
    readiness["failure_count"] = 0
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_readiness_record(tmp_path)

    assert not record.accepted
    assert any("failed checks: required_registry_valid" in item for item in record.failures)
    assert any(
        f"passed_count: expected {expected_passed_count}" in item
        for item in record.failures
    )
    assert any("failure_count: expected 1" in item for item in record.failures)
    assert any("failure_count must be zero" in item for item in record.failures)


def test_operator_handoff_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_registry_for_manual_progress(tmp_path)

    record = _operator_handoff_record(tmp_path)

    assert record.accepted
    assert record.item_count == 19
    assert record.failures == ()


def test_operator_handoff_contract_rejects_manual_gate_contract_drift(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    handoff_path = registry / "handoffs/rke_operator_handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    gold_gate = next(
        gate for gate in handoff["gates"] if gate["review_kind"] == "gold_set"
    )
    gold_gate["review_aids"]["fill_import_path"] = "registry/review_batches/stale.jsonl"
    gold_gate["field_contract"]["required_fields"] = ["reviewer"]
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_handoff_record(tmp_path)

    assert not record.accepted
    assert any("review_aids: must match shared manual review aid paths" in item for item in record.failures)
    assert any("field_contract: must match shared manual review field contract" in item for item in record.failures)


def test_operator_handoff_contract_rejects_template_or_license_promotion_inputs(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    handoff_path = registry / "handoffs/rke_operator_handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    promotion_step = next(
        step for step in handoff["command_sequence"] if step["step_id"] == "promotion-dry-run"
    )
    promotion_step["command"] = (
        promotion_step["command"].replace(
            "registry/review_batches/gold_set_full_reviewed.jsonl",
            "registry/review_batches/gold_set_full_import_template.jsonl",
        )
        + " --license-input registry/review_batches/source_license_policy_reviewed.json"
    )
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_handoff_record(tmp_path)

    assert not record.accepted
    assert any(
        "expected registry/review_batches/gold_set_full_reviewed.jsonl" in item
        for item in record.failures
    )
    assert any(
        "must not use gold_set_full_import_template.jsonl" in item
        for item in record.failures
    )
    assert any(
        "must not pass source-license input" in item for item in record.failures
    )


def test_operator_handoff_contract_rejects_step_order_or_tmp_prefix_drift(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    handoff_path = registry / "handoffs/rke_operator_handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["command_sequence"][0], handoff["command_sequence"][1] = (
        handoff["command_sequence"][1],
        handoff["command_sequence"][0],
    )
    handoff["command_sequence"][0]["command"] = "mosaic-rke prepare-gold-review --root ."
    handoff["run_order"] = [
        step["step_id"] for step in handoff["command_sequence"]
    ]
    handoff["production_allowed"] = True
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_handoff_record(tmp_path)

    assert not record.accepted
    assert any("step_id order mismatch" in item for item in record.failures)
    assert any("missing MOSAIC_RKE_TMPDIR prefix" in item for item in record.failures)
    assert any("missing TMPDIR prefix" in item for item in record.failures)
    assert any("production_allowed: must be false" in item for item in record.failures)


def test_operator_handoff_contract_requires_actions_only_preflight(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    handoff_path = registry / "handoffs/rke_operator_handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    preflight = next(
        step
        for step in handoff["command_sequence"]
        if step["step_id"] == "review-progress-preflight"
    )
    preflight["command"] = (
        "MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke "
        "TMPDIR=/home/hap/tmp/mosaic-rke mosaic-rke review-progress --root ."
    )
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_handoff_record(tmp_path)

    assert not record.accepted
    assert any("must use actions-only no-write preflight" in item for item in record.failures)


def test_manual_review_bundle_manifest_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_registry_for_manual_progress(tmp_path)

    record = _manual_review_bundle_manifest_record(tmp_path)

    assert record.accepted
    assert record.item_count == 11
    assert record.failures == ()


def test_manual_review_bundle_manifest_contract_accepts_completed_promotion_summary(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    report_path = registry / "promotion/rke_promotion_dry_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "accepted": True,
            "after_blockers": [],
            "after_next_state": "production",
            "production_allowed_after_simulation": True,
            "staged_production_allowed_after_simulation": True,
        }
    )
    for step in report["steps"]:
        step["accepted"] = True
        step["blockers"] = []
        if step["review_kind"] == "source_license":
            step["applied"] = False
            step["changed_rows"] = 0
            step["provided"] = False
            step["result"] = "already_applied"
            step["input_path"] = ""
        else:
            step["applied"] = True
            step["changed_rows"] = 1
            step["provided"] = True
            step["result"] = "accepted"
            step["input_path"] = f"registry/review_batches/{step['review_kind']}.jsonl"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = registry / "review_batches/manual_review_bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["promotion_dry_run"] = {
        "accepted": True,
        "accepted_steps": [
            "gold_set",
            "footprint_review",
            "source_license",
            "lockbox",
        ],
        "after_next_state": "production",
        "already_applied_steps": ["source_license"],
        "missing_steps": [],
        "production_allowed_after_simulation": True,
        "provided_steps": ["gold_set", "footprint_review", "lockbox"],
        "rejected_steps": [],
        "staged_production_allowed_after_simulation": True,
    }
    report_bytes = report_path.stat().st_size
    report_sha = "sha256:" + sha256(report_path.read_bytes()).hexdigest()
    for artifact in manifest["artifacts"]:
        if artifact["role"] == "promotion_dry_run_report":
            artifact["bytes"] = report_bytes
            artifact["sha256"] = report_sha
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_bundle_manifest_record(tmp_path)

    assert record.accepted
    assert record.item_count == 11
    assert record.failures == ()


def test_manual_review_bundle_manifest_contract_rejects_missing_artifact_role(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    manifest_path = registry / "review_batches/manual_review_bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact["role"] != "promotion_dry_run_report"
    ]
    manifest["artifact_count"] = len(manifest["artifacts"])
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_bundle_manifest_record(tmp_path)

    assert not record.accepted
    assert any(
        "missing roles: promotion_dry_run_report" in item
        for item in record.failures
    )
    assert any("artifact_count: expected 11" in item for item in record.failures)


def test_manual_review_bundle_manifest_contract_rejects_bad_hash_or_promotion(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    manifest_path = registry / "review_batches/manual_review_bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["sha256"] = "sha256:not-a-real-digest"
    manifest["artifacts"][0]["bytes"] = 0
    manifest["promotion_dry_run"]["production_allowed_after_simulation"] = True
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_bundle_manifest_record(tmp_path)

    assert not record.accepted
    assert any(".bytes: must be positive" in item for item in record.failures)
    assert any(".sha256: must be sha256:<64 hex>" in item for item in record.failures)
    assert any(
        "production_allowed_after_simulation: expected False" in item
        for item in record.failures
    )
    assert any(
        "must match current promotion dry-run report" in item
        for item in record.failures
    )


def test_manual_review_bundle_manifest_contract_rejects_stale_file_digest(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    handoff_markdown_path = registry / "handoffs/rke_operator_handoff.md"
    handoff_markdown_path.write_text(
        handoff_markdown_path.read_text(encoding="utf-8")
        + "\nStale manifest fixture line.\n",
        encoding="utf-8",
    )

    record = _manual_review_bundle_manifest_record(tmp_path)

    assert not record.accepted
    assert any(
        "artifacts[operator_handoff_markdown].bytes: expected current file size"
        in item
        for item in record.failures
    )
    assert any(
        "artifacts[operator_handoff_markdown].sha256: expected current file digest"
        in item
        for item in record.failures
    )


def test_promotion_dry_run_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_registry_for_manual_progress(tmp_path)

    record = _promotion_dry_run_record(tmp_path)

    assert record.accepted
    assert record.item_count == 4
    assert record.failures == ()


def test_promotion_dry_run_contract_accepts_completed_simulation(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    report_path = registry / "promotion/rke_promotion_dry_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "accepted": True,
            "after_blockers": [],
            "after_next_state": "production",
            "production_allowed_after_simulation": True,
            "staged_production_allowed_after_simulation": True,
        }
    )
    for step in report["steps"]:
        step["accepted"] = True
        step["blockers"] = []
        if step["review_kind"] == "source_license":
            step["applied"] = False
            step["changed_rows"] = 0
            step["provided"] = False
            step["result"] = "already_applied"
            step["input_path"] = ""
        else:
            step["applied"] = True
            step["changed_rows"] = 1
            step["provided"] = True
            step["result"] = "accepted"
            step["input_path"] = f"registry/review_batches/{step['review_kind']}.jsonl"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _promotion_dry_run_record(tmp_path)

    assert record.accepted
    assert record.item_count == 4
    assert record.failures == ()


def test_promotion_dry_run_contract_rejects_production_bypass(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    report_path = registry / "promotion/rke_promotion_dry_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["accepted"] = True
    report["production_allowed_after_simulation"] = True
    report["staged_production_allowed_after_simulation"] = True
    report["mutated_original_registry"] = True
    report["before_next_state"] = "staged_production"
    report["after_next_state"] = "paper_trading"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _promotion_dry_run_record(tmp_path)

    assert not record.accepted
    assert any("accepted mismatch with steps" in item for item in record.failures)
    assert any(
        "production_allowed_after_simulation: expected False"
        in item
        for item in record.failures
    )
    assert any(
        "staged_production_allowed_after_simulation: expected False"
        in item
        for item in record.failures
    )
    assert any(
        "mutated_original_registry: must be false" in item
        for item in record.failures
    )


def test_promotion_dry_run_contract_rejects_step_inconsistency(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    report_path = registry / "promotion/rke_promotion_dry_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["steps"][0]["accepted"] = True
    report["steps"][0]["blockers"] = ["gold_set input not provided"]
    report["steps"][0]["provided"] = False
    report["steps"][0]["input_path"] = "registry/review_batches/gold.jsonl"
    report["steps"][1]["accepted"] = False
    report["steps"][1]["blockers"] = []
    report["steps"][2]["result"] = "already_applied"
    report["steps"][2]["applied"] = True
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _promotion_dry_run_record(tmp_path)

    assert not record.accepted
    assert any("accepted step must not block" in item for item in record.failures)
    assert any("input_path: must be empty when not provided" in item for item in record.failures)
    assert any("rejected step requires blocker" in item for item in record.failures)
    assert any("already_applied must be false" in item for item in record.failures)


def test_production_promotion_gate_contract_accepts_current_public_artifact(
    tmp_path: Path,
):
    _copy_registry_for_manual_progress(tmp_path)

    record = _production_promotion_gate_record(tmp_path)

    assert record.accepted
    assert record.item_count == 10
    assert record.failures == ()


def test_production_promotion_gate_contract_accepts_completed_state(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    gate_path = registry / "promotion/rke_production_promotion_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    for criterion in gate["criteria"]:
        criterion["passed"] = True
        criterion["blocker"] = ""
    gate.update(
        {
            "blockers": [],
            "direct_production_forbidden": False,
            "next_state": "production",
            "paper_trading_allowed": True,
            "production_allowed": True,
            "staged_production_allowed": True,
        }
    )
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _production_promotion_gate_record(tmp_path)

    assert record.accepted
    assert record.item_count == 10
    assert record.failures == ()


def test_production_promotion_gate_contract_rejects_missing_criterion(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    gate_path = registry / "promotion/rke_production_promotion_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["criteria"] = [
        criterion
        for criterion in gate["criteria"]
        if criterion["criterion_id"] != "PG10"
    ]
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _production_promotion_gate_record(tmp_path)

    assert not record.accepted
    assert any("missing criterion_ids: PG10" in item for item in record.failures)


def test_production_promotion_gate_contract_rejects_blocker_mismatch(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    gate_path = registry / "promotion/rke_production_promotion_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["criteria"][1]["passed"] = True
    gate["criteria"][1]["blocker"] = "manual gold-set review still required"
    gate["blockers"] = []
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _production_promotion_gate_record(tmp_path)

    assert not record.accepted
    assert any("passed criterion must not block" in item for item in record.failures)
    assert any("blockers mismatch with criteria" in item for item in record.failures)


def test_production_promotion_gate_contract_rejects_production_bypass(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    gate_path = registry / "promotion/rke_production_promotion_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["staged_production_allowed"] = True
    gate["production_allowed"] = True
    gate["direct_production_forbidden"] = False
    gate["next_state"] = "production"
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _production_promotion_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "production_allowed: requires all criteria passed" in item
        for item in record.failures
    )
    assert any(
        "blockers: production state must be empty" in item
        for item in record.failures
    )
    assert any(
        "staged_production_allowed: requires PG01-PG08" in item
        for item in record.failures
    )


def test_schema_validation_accepts_public_registry_without_private_report_inputs(
    tmp_path: Path,
):
    shutil.copytree("schemas", tmp_path / "schemas")
    shutil.copytree(
        "registry",
        tmp_path / "registry",
        ignore=shutil.ignore_patterns(
            "tushare_research_reports*",
            "tushare_license_review*",
            "source_registry_validation_report.json",
            "report_metadata.jsonl",
            "forecast_claims.jsonl",
            "analytical_footprints.jsonl",
            "report_outcome_labels.jsonl",
            "weighted_research_contexts.jsonl",
            "processing_status.jsonl",
            "analytical_footprint_review_template.jsonl",
            "analytical_footprint_reviewed.jsonl",
            "pdfs",
            "markdown",
            "mineru",
        ),
    )

    report = build_schema_validation_report(tmp_path)

    assert not report.accepted
    _assert_only_phase_b_patch_coverage_failures(report)
    private_artifacts = {
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
    }
    private_records = {
        record.artifact_path: record for record in report.records
        if record.artifact_path in private_artifacts
    }
    assert set(private_records) == private_artifacts
    assert all(record.item_count == 0 for record in private_records.values())


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
                "industry_proxy_label_ready_count": 0,
                "stock_proxy_label_ready_count": 0,
                "proxy_label_only_ready_count": 0,
                "blocked_count": 0,
                "test_status_counts": {},
                "mapping_gap_counts": {},
                "unlabelable_mapping_gap_counts": {},
                "ready_forecast_claim_ids": [],
                "standard_blocked_forecast_claim_ids": [],
                "proxy_label_ready_forecast_claim_ids": [],
                "industry_proxy_label_ready_forecast_claim_ids": [],
                "stock_proxy_label_ready_forecast_claim_ids": [],
                "proxy_label_only_ready_forecast_claim_ids": [],
                "blocked_forecast_claim_ids": [],
                "blocked_reason": "",
                "minimum_required_mapping": [
                    "target",
                    "benchmark",
                    "direction",
                    "horizon",
                ],
                "policy": "test readiness fixture",
                "industry_etf_proxy_readiness": {},
                "stock_price_proxy_readiness": {},
                "next_actions": [],
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


def test_report_intelligence_monitoring_rejects_confidence_impact_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitoring_path = registry / "monitoring_report.json"
    monitoring = json.loads(monitoring_path.read_text(encoding="utf-8"))
    confidence = monitoring["confidence_impact_monitoring"]
    confidence["observation_count"] = 0
    confidence["recommended_action_counts"] = {"keep_shadow": 1}
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
    assert any(
        "confidence_impact_monitoring observation_count mismatch" in item
        for item in monitoring_record.failures
    )
    assert any(
        "confidence_impact_monitoring recommended_action_counts mismatch" in item
        for item in monitoring_record.failures
    )


def test_report_intelligence_monitoring_rejects_corpus_or_tooling_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitoring_path = registry / "monitoring_report.json"
    monitoring = json.loads(monitoring_path.read_text(encoding="utf-8"))
    monitoring["report_corpus"]["outcome_label_rows"] = 0
    tooling = monitoring["tooling_loop_monitoring"]
    tooling["tool_gap_open_count"] = 0
    tooling["tool_gap_priority_counts"] = {"medium": 1}
    tooling["evidence_coverage"]["metric_candidate_count"] = 0
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
    assert any("report_corpus outcome_label_rows mismatch" in item for item in monitoring_record.failures)
    assert any("tool_gap_open_count" in item for item in monitoring_record.failures)
    assert any("tool_gap_priority_counts mismatch" in item for item in monitoring_record.failures)
    assert any("metric_candidate_count mismatch" in item for item in monitoring_record.failures)


def test_report_intelligence_monitoring_rejects_weighting_summary_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitoring_path = registry / "monitoring_report.json"
    monitoring = json.loads(monitoring_path.read_text(encoding="utf-8"))
    weighting = monitoring["report_weighting_monitoring"]
    weighting["effective_n_by_source"]["profile_count"] = 0
    weighting["effective_n_by_viewpoint"]["max_effective_n"] = 999.0
    weighting["source_weight_drift"]["non_neutral_profile_count"] = 0
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
    assert any("effective_n_by_source.profile_count" in item for item in monitoring_record.failures)
    assert any("effective_n_by_viewpoint.max_effective_n" in item for item in monitoring_record.failures)
    assert any("non_neutral_profile_count mismatch" in item for item in monitoring_record.failures)


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

    assert code == 2
    assert output["accepted"] is False
    assert output["failure_count"] == (
        len(EXPECTED_ANALYTICAL_FOOTPRINT_REVIEW_FAILURES)
        + len(EXPECTED_PHASE_B_PATCH_COVERAGE_FAILURES)
    )
    assert Path("registry/schemas/rke_schema_validation_report.json").exists()


def test_schema_status_cli_filters_failures_without_writing(tmp_path: Path, capsys):
    schema_dir = tmp_path / "schemas"
    registry_dir = tmp_path / "registry"
    schema_dir.mkdir()
    for path in Path("schemas").iterdir():
        if path.is_file():
            (schema_dir / path.name).write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
    shutil.copytree(
        Path("registry"),
        registry_dir,
        ignore=shutil.ignore_patterns("schemas"),
        dirs_exist_ok=True,
    )

    code = main(
        (
            "schema-status",
            "--root",
            str(tmp_path),
            "--failures-only",
            "--no-write",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert output["failure_count"] == (
        len(EXPECTED_ANALYTICAL_FOOTPRINT_REVIEW_FAILURES)
        + len(EXPECTED_PHASE_B_PATCH_COVERAGE_FAILURES)
    )
    assert output["record_count"] > output["reported_record_count"]
    assert {
        record["schema_path"] for record in output["records"]
    } == {
        "schemas/report_intelligence_analytical_footprint_review_rules",
        "schemas/report_intelligence_patch_v1_5_coverage_rules",
    }
    next_actions = {action["action_id"]: action for action in output["next_actions"]}
    assert {
        "complete_manual_analytical_footprint_review",
        "clear_patch_v1_5_manual_review_coverage",
    } == set(next_actions)
    assert (
        "MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke"
        in next_actions["complete_manual_analytical_footprint_review"]["commands"][
            "inspect"
        ]
    )
    assert (
        "schema-status --root . --failures-only --no-write"
        in next_actions["complete_manual_analytical_footprint_review"]["commands"][
            "schema_after_review"
        ]
    )
    assert next_actions["complete_manual_analytical_footprint_review"][
        "review_aids"
    ]["evidence_markdown"] == (
        "registry/report_intelligence/analytical_footprint_review_evidence.md"
    )
    assert "review_notes" in next_actions[
        "complete_manual_analytical_footprint_review"
    ]["field_contract"]["required_fields"]
    assert (
        "review-progress --root . --actions-only --no-write --review-kind gold_set"
        in next_actions["clear_patch_v1_5_manual_review_coverage"]["commands"][
            "inspect_gold"
        ]
    )
    assert next_actions["clear_patch_v1_5_manual_review_coverage"]["review_aids"][
        "gold_set"
    ]["fill_import_path"] == "registry/review_batches/gold_set_reviewed.jsonl"
    assert next_actions["clear_patch_v1_5_manual_review_coverage"]["review_aids"][
        "footprint_review"
    ]["fill_import_path"] == (
        "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    assert next_actions["clear_patch_v1_5_manual_review_coverage"][
        "field_contract"
    ]["gold_set"]["optional_fields"] == ["review_notes"]
    assert "metric_mapping_correct" in next_actions[
        "clear_patch_v1_5_manual_review_coverage"
    ]["field_contract"]["footprint_review"]["boolean_fields"]
    assert all(record["accepted"] is False for record in output["records"])
    assert not (registry_dir / "schemas/rke_schema_validation_report.json").exists()


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
