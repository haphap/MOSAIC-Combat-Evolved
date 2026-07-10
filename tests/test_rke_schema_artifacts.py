from __future__ import annotations

import json
import os
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from mosaic.rke import (
    build_schema_validation_report,
    validate_json_schema_artifact,
)
import mosaic.rke.cli as cli_module
from mosaic.rke.cli import _schema_status_next_actions, main
from mosaic.rke.schema_validation import (
    REPORT_INTELLIGENCE_JSON_SCHEMA_TARGETS,
    SchemaValidationRecord,
    SchemaValidationReport,
    SUPPORTED_JSON_SCHEMA_KEYWORDS,
    iter_json_schema_keywords,
    validate_report_intelligence_semantics,
    validate_rule_pack_schema_artifact,
)
from mosaic.rke.report_intelligence import (
    REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS,
    REPORT_INTELLIGENCE_PUBLIC_DERIVED_OUTPUT_PATHS,
    _evolution_gate_cli_summary,
    build_default_industry_etf_proxy_map_rows,
)
from mosaic.rke.registry_manifest import PRIVATE_LOCAL_REGISTRY_FILES
from mosaic.rke.temp_paths import RKE_OPERATOR_TMP_ENV_PREFIX


REQUIRED_SCHEMA_FILES = {
    "source_metadata.schema.json",
    "source_grounded_claim.schema.json",
    "hypothesis.schema.json",
    "data_availability_matrix.schema.json",
    "rule_pack.schema.yaml",
    "parameter_prior.schema.json",
    "validation_experiment_v2.schema.json",
    "production_patch.schema.json",
    "research_knobs_v1.schema.json",
    "prompt_ir_runtime_contract_v1.schema.json",
    "domain_knob_catalog_v1.schema.json",
    "runtime_agent_manifest_v1.schema.json",
    "domain_knob_evaluation_contract_v1.schema.json",
    "evidence_claim_graph_v1.schema.json",
    "prompt_mutation_transaction_v1.schema.json",
    "prompt_mutation_recovery_v1.schema.json",
    "active_prompt_release_manifest_v1.schema.json",
    "domain_evaluation_preregistration_v1.schema.json",
    "domain_evaluation_sample_manifest_v1.schema.json",
    "domain_evaluation_result_v1.schema.json",
    "domain_promotion_decision_v1.schema.json",
    "l4_run_snapshot_bundle_v1.schema.json",
    "domain_knob_values_v1.schema.json",
    "prompt_governance_values_v1.schema.json",
    "prompt_release_canary_event_v1.schema.json",
    "prompt_release_canary_slo_v1.schema.json",
    "prompt_token_budget_manifest_v1.schema.json",
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
    "report_intelligence_macro_regime_snapshot.schema.json",
    "report_intelligence_macro_agent_research_prior.schema.json",
    "report_intelligence_macro_market_series_catalog.schema.json",
    "report_intelligence_stock_context_snapshot.schema.json",
    "report_intelligence_industry_context_snapshot.schema.json",
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

CURRENT_MANUAL_REPORT_INTELLIGENCE_SCHEMA_BLOCKERS = {
    "registry/report_intelligence/analytical_footprint_review_summary.json",
    "registry/report_intelligence/patch_v1_5_coverage_report.json",
}


def _assert_only_current_manual_report_intelligence_schema_blockers(report) -> None:
    failing_records = [record for record in report.records if not record.accepted]
    assert {
        record.artifact_path for record in failing_records
    } == CURRENT_MANUAL_REPORT_INTELLIGENCE_SCHEMA_BLOCKERS
    failures = [failure for record in failing_records for failure in record.failures]
    assert any(
        "analytical_footprint_review_summary pending_rows must be zero" in failure
        for failure in failures
    )
    assert any(
        "patch_v1_5_coverage_report Phase B: accepted must be true" in failure
        for failure in failures
    )
    assert not any("extraction_provenance_audit" in failure for failure in failures)
    assert not any("statistical_robustness_audit" in failure for failure in failures)


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
        "metric_mapping_accuracy 0.558824 below threshold 0.80"
    ),
}

PRIVATE_GENERATED_REPORT_INTELLIGENCE_FIXTURE_FILES = (
    REPORT_INTELLIGENCE_PUBLIC_DERIVED_OUTPUT_PATHS
    | {
        "registry/report_intelligence/source_performance_profiles.jsonl",
        "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
        "registry/report_intelligence/method_performance_profiles.jsonl",
        "registry/report_intelligence/confidence_impact_observations.jsonl",
        "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
        "registry/report_intelligence/prompt_mutation_candidates.jsonl",
        "registry/report_intelligence/audit_refresh_history.jsonl",
        "registry/report_intelligence/data_acquisition_proposals.jsonl",
        "registry/report_intelligence/gap_distribution_history.jsonl",
        "registry/report_intelligence/macro_agent_research_priors.jsonl",
        "registry/report_intelligence/method_patterns.jsonl",
        "registry/report_intelligence/metric_candidates.jsonl",
        "registry/report_intelligence/monitor_refresh_history.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/tool_gaps.jsonl",
    }
)
PRIVATE_GENERATED_REPORT_INTELLIGENCE_FIXTURE_COUNT_FIELDS = {
    "registry/report_intelligence/audit_refresh_history.jsonl": None,
    "registry/report_intelligence/confidence_impact_observations.jsonl": None,
    "registry/report_intelligence/gap_distribution_history.jsonl": None,
    "registry/report_intelligence/method_performance_profiles.jsonl": (
        "method_performance_profile_rows"
    ),
    "registry/report_intelligence/prompt_mutation_candidates.jsonl": (
        "prompt_mutation_candidate_rows"
    ),
    "registry/report_intelligence/recipe_paper_trading_runs.jsonl": None,
    "registry/report_intelligence/source_performance_profiles.jsonl": (
        "source_performance_profile_rows"
    ),
    "registry/report_intelligence/viewpoint_performance_profiles.jsonl": (
        "viewpoint_performance_profile_rows"
    ),
}
PRIVATE_GENERATED_REPORT_INTELLIGENCE_TEST_NAMES = {
    "test_stock_report_outcome_status_doc_matches_public_artifacts",
    "test_profile_outcome_layer_contract_accepts_current_public_artifacts",
    "test_profile_outcome_layer_contract_rejects_layer_drift",
    "test_extraction_report_contract_accepts_current_public_artifact",
    "test_confidence_impact_observation_rejects_unknown_drift_status",
    "test_confidence_impact_observation_schema_requires_plan_fields",
    "test_confidence_impact_observation_schema_requires_regime_monitor_fields",
    "test_recipe_paper_trading_contract_accepts_current_public_artifacts",
    "test_recipe_paper_trading_contract_rejects_confidence_bypass",
    "test_recipe_paper_trading_contract_rejects_missing_confidence_monitor_field",
    "test_recipe_paper_trading_contract_rejects_regime_monitor_mismatch",
    "test_recipe_paper_trading_contract_rejects_confidence_observation_id_drift",
    "test_recipe_paper_trading_contract_rejects_monitor_action_mismatch",
    "test_recipe_paper_trading_contract_rejects_monitor_derived_field_mismatch",
    "test_recipe_paper_trading_contract_rejects_run_summary_mismatch",
    "test_recipe_paper_trading_contract_rejects_validated_count_alias_mismatch",
    "test_recipe_paper_trading_contract_rejects_summary_protocol_mismatch",
    "test_recipe_paper_trading_contract_rejects_preregistration_payload_mismatch",
    "test_recipe_paper_trading_contract_rejects_experiment_id_drift",
    "test_recipe_paper_trading_contract_rejects_raw_required_data_persistence",
    "test_recipe_paper_trading_run_schema_requires_plan_metrics",
    "test_recipe_paper_trading_contract_rejects_missing_plan_metric",
    "test_recipe_paper_trading_contract_rejects_passed_run_without_oos_alpha",
    "test_recipe_paper_trading_contract_rejects_instability_without_gap",
    "test_patch_coverage_rules_reject_stale_public_corpus_counts",
    "test_evolution_refresh_history_rejects_accepted_aggregate_calibration_drift",
    "test_evolution_refresh_history_rejects_stale_gap_distribution_state",
    "test_evolution_refresh_history_requires_data_vintage_hash",
    "test_prompt_mutation_candidate_contract_accepts_current_public_artifact",
    "test_prompt_mutation_candidate_contract_rejects_production_prompt_bypass",
    "test_prompt_mutation_candidate_contract_rejects_private_source_text",
    "test_prompt_mutation_candidate_contract_requires_manual_blocked_shadow_review",
    "test_prompt_mutation_candidate_contract_requires_full_validation_matrix",
    "test_prompt_mutation_candidate_contract_requires_existing_public_evidence",
    "test_prompt_mutation_candidate_contract_rejects_private_evidence_paths",
    "test_prompt_mutation_candidate_contract_rejects_gold_quality_evidence_drift",
    "test_prompt_mutation_candidate_contract_rejects_footprint_quality_evidence_drift",
    "test_prompt_mutation_candidate_contract_rejects_refresh_stability_evidence_drift",
    "test_prompt_mutation_candidate_contract_rejects_industry_mapping_evidence_drift",
    "test_prompt_mutation_candidate_contract_rejects_calibration_evidence_drift",
    "test_prompt_mutation_candidate_contract_rejects_mapping_markdown_confidence_drift",
    "test_prompt_mutation_candidate_contract_rejects_remaining_public_evidence_drift",
    "test_report_intelligence_monitoring_rejects_corpus_or_tooling_drift",
    "test_report_intelligence_monitoring_rejects_weighting_summary_drift",
}


def _missing_private_generated_report_intelligence_fixtures() -> list[str]:
    return [
        path
        for path in sorted(PRIVATE_GENERATED_REPORT_INTELLIGENCE_FIXTURE_FILES)
        if not Path(path).exists()
    ]


def _stale_private_generated_report_intelligence_fixtures() -> list[str]:
    report_path = Path("registry/report_intelligence/extraction_report.json")
    extraction_report = json.loads(report_path.read_text(encoding="utf-8"))
    stale = []
    for path, field_name in sorted(
        PRIVATE_GENERATED_REPORT_INTELLIGENCE_FIXTURE_COUNT_FIELDS.items()
    ):
        if field_name is None:
            continue
        row_count = sum(
            1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
        )
        expected_count = extraction_report[field_name]
        if row_count != expected_count:
            stale.append(f"{path}: {row_count} != {expected_count}")
    return stale


@pytest.fixture(autouse=True)
def _skip_private_generated_report_intelligence_contracts(request) -> None:
    if request.node.name not in PRIVATE_GENERATED_REPORT_INTELLIGENCE_TEST_NAMES:
        return
    if os.getenv("MOSAIC_TEST_PRIVATE_REPORT_INTELLIGENCE_FIXTURES") != "1":
        pytest.skip(
            "private/generated report-intelligence fixtures are opt-in; set "
            "MOSAIC_TEST_PRIVATE_REPORT_INTELLIGENCE_FIXTURES=1"
        )
    missing = _missing_private_generated_report_intelligence_fixtures()
    if missing:
        pytest.skip(
            "full private/generated report-intelligence fixture is absent in this "
            f"checkout; first missing artifact: {missing[0]}"
        )
    stale = _stale_private_generated_report_intelligence_fixtures()
    if stale:
        pytest.skip(
            "full private/generated report-intelligence fixture is not aligned "
            f"with public extraction_report.json; first stale artifact: {stale[0]}"
        )


def _expected_schema_failure_count() -> int:
    return (
        len(EXPECTED_ANALYTICAL_FOOTPRINT_REVIEW_FAILURES)
        + len(EXPECTED_PHASE_B_PATCH_COVERAGE_FAILURES)
    )


def _require_local_report_intelligence_artifacts(*names: str) -> Path:
    if os.getenv("MOSAIC_TEST_PRIVATE_REPORT_INTELLIGENCE_FIXTURES") != "1":
        pytest.skip(
            "local report-intelligence artifacts are opt-in; set "
            "MOSAIC_TEST_PRIVATE_REPORT_INTELLIGENCE_FIXTURES=1"
        )
    registry = Path("registry/report_intelligence")
    if not registry.exists():
        pytest.skip("local report-intelligence artifacts are absent")
    missing = [
        str(registry / name)
        for name in names
        if not (registry / name).exists()
    ]
    if missing:
        pytest.skip(
            "local report-intelligence artifacts are absent; first missing "
            f"artifact: {missing[0]}"
        )
    return registry


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
    assert report.failure_count == _expected_schema_failure_count()


def _copy_report_intelligence_registry(tmp_path: Path) -> Path:
    source = _require_local_report_intelligence_artifacts(
        *(
            Path(path).name
            for path in sorted(PRIVATE_GENERATED_REPORT_INTELLIGENCE_FIXTURE_FILES)
        )
    )
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    for fixture_path in sorted(PRIVATE_GENERATED_REPORT_INTELLIGENCE_FIXTURE_FILES):
        name = Path(fixture_path).name
        shutil.copy2(source / name, registry / name)
    return registry


def _remove_private_report_intelligence_inputs(registry: Path) -> None:
    for name in (
        "report_metadata.jsonl",
        "forecast_claims.jsonl",
        "analytical_footprints.jsonl",
        "report_outcome_labels.jsonl",
        "weighted_research_contexts.jsonl",
        "processing_status.jsonl",
    ):
        path = registry / name
        if path.exists():
            path.unlink()


def _ignore_private_registry_inputs(dirname: str, names: list[str]) -> set[str]:
    ignored = set(
        shutil.ignore_patterns(
            "report_intelligence",
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
            "schemas",
        )(dirname, names)
    )
    try:
        relative_dir = Path(dirname).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        relative_dir = Path(dirname).as_posix()
    private_files = PRIVATE_LOCAL_REGISTRY_FILES | REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS
    ignored.update(
        name
        for name in names
        if f"{relative_dir}/{name}" in private_files
    )
    return ignored


def test_macro_public_research_rules_reject_raw_market_series_catalog(
    tmp_path: Path,
):
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    (registry / "macro_market_series_catalog.jsonl").write_text(
        json.dumps(
            {
                "catalog_id": "MMSC-RAW",
                "schema_version": "macro_market_series_catalog_v1",
                "series_id": "US10Y",
                "series_family": "yield",
                "source": "scorecard_macro_series",
                "source_endpoint": "scorecard.macro_series",
                "instrument": "US_10Y_YIELD",
                "quote_convention": "yield_level_percent",
                "unit": "percent",
                "calendar": "observation_date",
                "frequency": "daily_or_source_frequency",
                "latest_observation_date": "2026-01-05",
                "earliest_observation_date": "2026-01-01",
                "point_in_time_policy": "metadata only",
                "license_boundary": "public_metadata_no_raw_licensed_observations",
                "target_agent_candidates": ["macro.yield_curve"],
                "implementation_status": "implemented_scorecard_read_only",
                "readiness_status": "ready",
                "gap_reason": "",
                "raw_observations_included": True,
                "private_text_included": False,
                "value": 4.25,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path == "schemas/report_intelligence_macro_public_research_rules"
    )

    assert not record.accepted
    assert record.item_count == 1
    assert any(
        "raw_observations_included: must be false" in item
        for item in record.failures
    )
    assert any(
        ".value: raw observations are not public" in item
        for item in record.failures
    )


def test_phase1_schema_artifacts_exist():
    schema_dir = Path("schemas")

    assert {path.name for path in schema_dir.iterdir()} >= REQUIRED_SCHEMA_FILES


def test_master_plan_policy_docs_exist():
    docs_dir = Path("docs")
    plans_dir = docs_dir / "plans"

    assert {path.name for path in docs_dir.iterdir()} >= REQUIRED_POLICY_DOCS
    assert {path.name for path in plans_dir.iterdir()} >= REQUIRED_PLAN_DOCS


def test_stock_report_outcome_status_doc_matches_public_artifacts():
    pytest.skip("report-intelligence derived status is local-only")
    local_report_intelligence = _require_local_report_intelligence_artifacts(
        "extraction_report.json",
        "evolution_readiness_gate.json",
        "outcome_labeling_readiness.json",
        "analytical_footprint_review_summary.json",
        "prompt_mutation_candidates.jsonl",
    )
    status_text = Path(
        "docs/plans/rke_stock_report_outcome_and_evolution_status.md"
    ).read_text(encoding="utf-8")
    extraction_report = json.loads(
        (local_report_intelligence / "extraction_report.json").read_text(
            encoding="utf-8"
        ),
    )
    progress_report = json.loads(
        Path("registry/review_batches/manual_review_progress_report.json").read_text(
            encoding="utf-8"
        )
    )
    evolution_gate = json.loads(
        (local_report_intelligence / "evolution_readiness_gate.json").read_text(
            encoding="utf-8"
        ),
    )
    outcome_readiness = json.loads(
        (local_report_intelligence / "outcome_labeling_readiness.json").read_text(
            encoding="utf-8"
        ),
    )
    footprint_summary = json.loads(
        (
            local_report_intelligence / "analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    prompt_mutation_candidates = [
        json.loads(line)
        for line in (
            local_report_intelligence / "prompt_mutation_candidates.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    operator_readiness = json.loads(
        Path("registry/handoffs/rke_operator_readiness_report.json").read_text(
            encoding="utf-8"
        )
    )
    gold_gate = next(
        gate for gate in progress_report["gates"] if gate["review_kind"] == "gold_set"
    )
    footprint_gate = next(
        gate
        for gate in progress_report["gates"]
        if gate["review_kind"] == "footprint_review"
    )
    evolution_checks = {
        check["check_id"]: check for check in evolution_gate["checks"]
    }
    audit_check = evolution_checks["RI-EVOL-04"]
    audit_evidence = audit_check["evidence"]
    normalized_status_text = " ".join(status_text.split())

    outcome_count = extraction_report["outcome_label_rows"]
    industry_count = extraction_report["industry_etf_proxy_outcome_label_rows"]
    stock_count = extraction_report["stock_price_proxy_outcome_label_rows"]
    macro_count = extraction_report["macro_asset_proxy_outcome_label_rows"]
    macro_series_count = extraction_report[
        "macro_series_directional_outcome_label_rows"
    ]
    macro_curve_count = extraction_report["macro_curve_directional_outcome_label_rows"]
    assert outcome_readiness["stock_price_proxy_readiness"]["eligible_claim_count"] > 0
    assert (
        f"{extraction_report['metadata_rows']} selected reports, "
        f"{extraction_report['markdown_ready_count']} Markdown-ready reports"
    ) in normalized_status_text
    assert (
        f"{extraction_report['forecast_claim_rows']} forecast claims, and "
        f"{outcome_count} outcome labels"
    ) in status_text
    assert (
        f"{industry_count} industry ETF proxy labels, {stock_count} stock price proxy"
    ) in status_text
    assert f"{macro_count} macro asset proxy labels" in status_text
    assert f"{macro_series_count} macro direct-series labels" in status_text
    assert f"{macro_curve_count} macro curve labels" in normalized_status_text
    assert (
        f"{outcome_readiness['ready_for_outcome_labeling_count']} standard ready claims"
        in status_text
    )
    assert (
        f"{outcome_readiness['proxy_label_ready_count']} proxy-label ready claims"
        in normalized_status_text
    )
    assert f"{outcome_readiness['blocked_count']} still blocked claims" in status_text
    assert f"{gold_gate['complete_rows']} reviewed claims" in status_text
    assert (
        f"{footprint_summary['complete_rows']} reviewed footprints"
        in normalized_status_text
    )
    assert f"{footprint_summary['pending_rows']} pending rows" in status_text
    assert (
        "schema-status --root . --failures-only --no-write` currently reports 0 "
        "failures"
    ) in normalized_status_text
    assert "operator-readiness --root .` is accepted with 18/18 checks" in status_text
    assert (
        "evolution-readiness --root . --no-write` is accepted with RI-EVOL-01 "
        "through RI-EVOL-07 passing"
    ) in normalized_status_text
    assert evolution_gate["gate_status"] == "passed"
    assert evolution_gate["blockers"] == []
    assert audit_check["blockers"] == []
    assert audit_evidence["schema_accepted"] is True
    assert audit_evidence["pit_accepted"] is True
    assert audit_evidence["provenance_accepted"] is True
    assert audit_evidence["statistical_accepted"] is True
    assert audit_evidence["current_failure_counts"]["schema"] == 0
    assert audit_evidence["trailing_audit_pass_count"] >= 3
    assert audit_evidence["trailing_audit_distinct_vintage_count"] >= 3
    assert (
        "RI-EVOL-04 has "
        f"{audit_evidence['trailing_audit_pass_count']} trailing clean audit "
        f"passes and {audit_evidence['trailing_audit_distinct_vintage_count']} "
        "distinct clean audit vintages"
    ) in normalized_status_text
    assert "Patch v1.5 coverage is accepted" in status_text
    assert f"{len(prompt_mutation_candidates)} shadow-only candidates" in status_text
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
    assert operator_readiness["accepted"] is True
    assert operator_readiness["passed_count"] == operator_readiness["check_count"] == 18
    assert "report prose" in status_text
    assert "report-derived signals remain shadow-only" in normalized_status_text
    return

    gate_kinds = {gate["review_kind"] for gate in progress_report["gates"]}
    gold_gate = next(
        gate for gate in progress_report["gates"] if gate["review_kind"] == "gold_set"
    )
    footprint_gate = next(
        gate
        for gate in progress_report["gates"]
        if gate["review_kind"] == "footprint_review"
    )
    gold_batch = gold_gate["current_batch_status"]
    gold_batch_overview = gold_gate["batch_overview"]
    gold_workload_summary = gold_batch_overview[
        "current_batch_review_field_workload_summary"
    ]
    gold_field_workload = gold_batch_overview["current_batch_review_field_workload"]
    footprint_batch_overview = footprint_gate["batch_overview"]
    footprint_workload_summary = footprint_batch_overview[
        "current_batch_review_field_workload_summary"
    ]
    operator_check_ids = {check["check_id"] for check in operator_readiness["checks"]}

    outcome_count = extraction_report["outcome_label_rows"]
    industry_count = extraction_report["industry_etf_proxy_outcome_label_rows"]
    stock_count = extraction_report["stock_price_proxy_outcome_label_rows"]
    macro_count = extraction_report["macro_asset_proxy_outcome_label_rows"]
    stock_readiness = outcome_readiness["stock_price_proxy_readiness"]
    assert (
        f"{outcome_count} outcome labels: {industry_count} industry ETF proxy, "
        f"{stock_count} stock price proxy, {macro_count} macro asset proxy"
    ) in status_text
    assert {"gold_set", "footprint_review", "source_license", "lockbox"} <= gate_kinds
    assert "public baseline: gold-set" in status_text
    assert "reviewed but quality-blocked" in status_text
    assert "analytical-footprint review" in status_text
    assert "reviewed with" in status_text
    assert "source license 17529/17529" in status_text
    assert "source license 17529/17529 already applied" in status_text
    assert "action_state=already_applied" in status_text
    assert "can_run_now=false" in status_text
    assert (
        "private footprint review assist/workbook snapshot follows the active "
        "50-row scratch batch via `--review-input`"
        in status_text
    )
    assert (
        f"expanded gold review target is now {gold_gate['target_rows']} rows "
        f"with {gold_gate['complete_rows']} complete and {gold_gate['pending_rows']} pending"
        in status_text
    )
    assert (
        f"Current gold batch status is {gold_batch['rows']} rows, "
        f"{gold_batch['complete_rows']} complete, {gold_batch['pending_rows']} pending"
        in status_text
    )
    assert (
        f"write-gold-review-evidence --root . --limit {gold_batch['rows']} --offset 0 "
        "--review-input registry/review_batches/gold_set_reviewed.jsonl"
    ) in status_text
    assert (
        f"{gold_workload_summary['missing_required_cells']} missing required review cells, "
        f"{gold_workload_summary['draft_decision_available_cells']} evidence-draft cells "
        "available for"
    ) in status_text
    assert (
        f"{gold_workload_summary['draft_text_available_cells']} evidence text-draft cells "
        "available for\n  `manual_claim_text`"
    ) in status_text
    assert (
        f"{footprint_workload_summary['draft_text_available_cells']} evidence text-draft\n"
        "  cells available for `review_notes`"
    ) in status_text
    assert "fields with evidence text drafts available" in status_text
    assert "draft-decision / draft-text verification fields" in status_text
    assert (
        f"{gold_workload_summary['manual_review_required_cells']} cells that still "
        "require manual input"
    ) in status_text
    assert (
        f"active scratch evidence has draft decisions for "
        f"{gold_workload_summary['draft_decision_available_cells']} required cells "
        f"and {gold_workload_summary['manual_review_required_cells']}"
    ) in status_text
    assert (
        "`target_correct` "
        f"true={gold_field_workload['target_correct']['suggested_true_rows']}/"
        f"false={gold_field_workload['target_correct']['suggested_false_rows']}/"
        f"null={gold_field_workload['target_correct']['suggested_null_rows']}"
    ) in status_text
    assert (
        "`horizon_correct`\n"
        f"true={gold_field_workload['horizon_correct']['suggested_true_rows']}/"
        f"false={gold_field_workload['horizon_correct']['suggested_false_rows']}/"
        f"null={gold_field_workload['horizon_correct']['suggested_null_rows']}"
    ) in status_text
    assert (
        "`variable_mapping_correct` "
        f"true={gold_field_workload['variable_mapping_correct']['suggested_true_rows']}/"
        f"false={gold_field_workload['variable_mapping_correct']['suggested_false_rows']}"
    ) in status_text
    assert "needs_human_review_fields" in status_text
    assert (
        "private evidence draft is aligned with the same "
        f"{gold_batch['rows']} scratch rows"
        in status_text
    )
    assert "write-gold-review-assist --root . --review-input" in status_text
    assert "current active analytical-footprint batch has 50 rows" in status_text
    assert "Synthetic pytest fixtures" in status_text
    assert "current target hashes" in status_text
    assert "promotion gold-set import" in status_text
    assert "remains not ready because the expanded current batch" in status_text
    assert "lockbox is 0/1" in status_text
    assert "labelability_summary" in status_text
    assert "outcome_labeling_readiness.industry_etf_proxy_readiness" in status_text
    assert (
        f"{stock_readiness['labelable_forecast_claim_count']} labelable stock claims"
        in status_text
    )
    assert (
        f"{stock_readiness['pending_future_window_count']} pending future windows"
        in status_text
    )
    assert "qlib://..." in status_text
    assert "entry_lag_trading_days" in status_text
    assert "STOCK_PRICE_PROXY_ENTRY_LAG_TRADING_DAYS" in status_text
    assert f"{len(prompt_mutation_candidates)} shadow-only mutation candidates" in status_text
    assert "production_prompt_change_allowed=false" in status_text
    assert len(prompt_mutation_candidates) >= 10
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
    assert (
        "paper_trading_validated_recipe_count_below_threshold"
        not in evolution_gate["blockers"]
    )
    assert "RI-EVOL-02 now passes" in status_text
    for blocker in (
        "industry_proxy_claim_count_below_threshold",
        "evaluability_bucket_coverage_below_p9_target",
    ):
        assert blocker not in evolution_gate["blockers"]
    assert "current gate thresholds are cleared" in status_text
    assert "20-recipe threshold" in status_text
    assert "coverage_gate_status=passed" in status_text
    assert "macro_asset_proxy_candidate" in status_text
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


def test_schema_validation_report_tracks_current_clean_registry(
    tmp_path: Path,
):
    shutil.copytree("schemas", tmp_path / "schemas")
    shutil.copytree(
        "registry",
        tmp_path / "registry",
        ignore=_ignore_private_registry_inputs,
    )

    report = build_schema_validation_report(tmp_path)

    assert report.accepted
    assert report.failure_count == 0
    assert all(record.accepted for record in report.records)
    assert len(report.records) >= 15
    assert {
        "schemas/source_metadata.schema.json",
        "schemas/source_grounded_claim.schema.json",
        "schemas/validation_experiment_v2.schema.json",
        "schemas/rule_pack.schema.yaml",
        "schemas/confidence_policy.schema.yaml",
        "schemas/report_intelligence_forecast_claim.schema.json",
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


def test_schema_validation_allows_missing_local_report_intelligence_artifact(
    tmp_path: Path,
):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir(parents=True)
    schema_name = "report_intelligence_feature_flags.schema.json"
    (schema_dir / schema_name).write_text(
        Path("schemas", schema_name).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path=f"schemas/{schema_name}",
        artifact_path="registry/report_intelligence/feature_flags.json",
        artifact_kind="json",
    )

    assert record.accepted
    assert record.item_count == 0
    assert record.failures == ()
    assert validate_report_intelligence_semantics(tmp_path) == ()


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
    registry = _copy_report_intelligence_registry(tmp_path)
    _remove_private_report_intelligence_inputs(registry)
    readiness = json.loads(
        (registry / "outcome_labeling_readiness.json").read_text(encoding="utf-8")
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert record.accepted
    assert record.item_count == readiness["stock_price_proxy_readiness"][
        "eligible_claim_count"
    ]
    assert record.item_count >= 100
    assert record.failures == ()


def test_stock_price_proxy_readiness_contract_accepts_audited_survivorship_state(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    _remove_private_report_intelligence_inputs(registry)
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
    assert record.item_count == readiness["stock_price_proxy_readiness"][
        "eligible_claim_count"
    ]
    assert record.item_count >= 100
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


def test_stock_price_proxy_readiness_contract_accepts_blocking_gap_counts(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    readiness_path = registry / "outcome_labeling_readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    stock_readiness = readiness["stock_price_proxy_readiness"]
    stock_readiness["data_gap_counts"].update(
        {
            "entry_limit_locked": 1,
            "entry_liquidity_unverified": 2,
            "exit_limit_locked": 3,
            "exit_liquidity_unverified": 4,
            "stock_delisted_before_exit": 5,
            "stock_entry_suspended": 6,
            "stock_long_suspension_window": 7,
        }
    )
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert record.accepted
    assert record.failures == ()


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
    stock_readiness["pending_future_forecast_claim_count"] = (
        stock_readiness["eligible_claim_count"] + 1
    )
    readiness["stock_proxy_label_ready_count"] = 0
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _stock_price_proxy_readiness_record(tmp_path)

    assert not record.accepted
    assert any("labelable_window_count" in failure for failure in record.failures)
    assert any("eligible_claim_count" in failure for failure in record.failures)
    assert any("stock_proxy_label_ready_count" in failure for failure in record.failures)


def test_profile_outcome_layer_contract_accepts_current_public_artifacts(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    expected_count = sum(
        1
        for filename in (
            "source_performance_profiles.jsonl",
            "viewpoint_performance_profiles.jsonl",
            "method_performance_profiles.jsonl",
        )
        for line in (registry / filename).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

    record = _profile_outcome_layer_record(tmp_path)

    assert record.accepted
    assert record.item_count == expected_count
    assert record.item_count >= 3000
    assert record.failures == ()


def _seed_profile_outcome_layer(profile):
    profile["n_effective"] = 1.0
    support = profile["outcome_layer_support"]
    support["layer_count"] = 1
    support["mixed_layer_profile"] = False
    support["layering_policy"] = (
        "compare by label_type, target_family, benchmark_family, cost_model_id, "
        "agent_layer, and regime_bucket"
    )
    summary = {
        "label_type": "stock_price_proxy",
        "target_family": "stock",
        "benchmark_family": "CSI300_ETF_PROXY",
        "cost_model_id": "single_stock_round_trip_20bps_v1",
        "agent_layer": "superinvestor",
        "regime_bucket": "company_quality",
        "n_nominal": 1,
        "n_effective": 1.0,
        "mean_after_cost_alpha": 0.01,
        "hit_rate": 1.0,
        "shrunk_after_cost_alpha": 0.001,
        "shrunk_hit_rate": 0.55,
        "statistical_reliability_bucket": "insufficient_data",
    }
    key = {
        "label_type": "stock_price_proxy",
        "target_family": "stock",
        "benchmark_family": "CSI300_ETF_PROXY",
        "cost_model_id": "single_stock_round_trip_20bps_v1",
        "agent_layer": "superinvestor",
        "regime_bucket": "company_quality",
    }
    domain_support = {
        "rating_row_count": 1,
        "rating_bucket_counts": {"supportive_evidence": 1},
        "failure_mode_counts": {},
        "tradeability_blocker_count": 0,
        "target_price_hit_count": 0,
        "fundamental_metric_family_counts": {"inventory_to_sales": 1},
        "target_family_counts": {"stock": 1},
        "agent_layer_counts": {"superinvestor": 1},
        "regime_bucket_counts": {"company_quality": 1},
        "mapping_confidence_counts": {},
        "proxy_limitation_tags": [],
        "privacy_policy": "redacted_internal_rating_aggregate_only",
    }
    summary["domain_rating_support"] = dict(domain_support)
    support["layer_summaries"] = [summary]
    support["layer_keys"] = [key]
    support["domain_rating_support"] = dict(domain_support)
    return support, summary, key


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
    support, summary, _key = _seed_profile_outcome_layer(profiles[0])
    support["layer_count"] = 0
    support["mixed_layer_profile"] = False
    support["layer_keys"] = []
    summary["n_effective"] = 0.0
    summary.pop("benchmark_family", None)
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


def test_profile_outcome_layer_contract_rejects_incomplete_extended_keys(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    profiles_path = registry / "source_performance_profiles.jsonl"
    profiles = [
        json.loads(line)
        for line in profiles_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _support, summary, key = _seed_profile_outcome_layer(profiles[0])
    summary.pop("target_family")
    key.pop("agent_layer")
    profiles_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in profiles
        )
        + "\n",
        encoding="utf-8",
    )

    record = _profile_outcome_layer_record(tmp_path)

    assert not record.accepted
    assert any("target_family" in failure for failure in record.failures)
    assert any("agent_layer" in failure for failure in record.failures)


def test_profile_outcome_layer_contract_rejects_bad_domain_rating_support(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    profiles_path = registry / "source_performance_profiles.jsonl"
    profiles = [
        json.loads(line)
        for line in profiles_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    support, summary, _key = _seed_profile_outcome_layer(profiles[0])
    support["domain_rating_support"]["rating_bucket_counts"] = {"generic_good": 1}
    summary["domain_rating_support"].pop("target_family_counts")
    profiles_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in profiles
        )
        + "\n",
        encoding="utf-8",
    )

    record = _profile_outcome_layer_record(tmp_path)

    assert not record.accepted
    assert any("unsupported rating bucket" in failure for failure in record.failures)
    assert any("target_family_counts: expected object" in failure for failure in record.failures)


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


def _write_evolution_readiness_gate(tmp_path: Path, gate: dict[str, object]) -> Path:
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True, exist_ok=True)
    gate_path = registry / "evolution_readiness_gate.json"
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gate_path


def _copy_gold_review_summary(tmp_path: Path) -> Path:
    report_intelligence_dir = tmp_path / "registry/report_intelligence"
    report_intelligence_dir.mkdir(parents=True, exist_ok=True)
    (report_intelligence_dir / "feature_flags.json").write_text(
        json.dumps(
            {
                "flags": {},
                "rollout_mode": "extraction_only",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    gold_dir = tmp_path / "registry/gold_sets"
    gold_dir.mkdir(parents=True, exist_ok=True)
    summary_path = gold_dir / "tushare_research_reports.review_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "blockers": ["100 gold-set claim review rows still pending"],
                "metrics": None,
                "passed": False,
                "pending_claims": 100,
                "review_complete": False,
                "review_path": "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                "reviewed_claims": 0,
                "summary_id": "RKE-GOLD-SET-REVIEW-SUMMARY-20260606",
                "total_claims": 100,
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
    elif label_type == "macro_asset_proxy":
        row.update(
            {
                "horizon_days": 90,
                "effective_n_weight": 0.333333,
                "proxy_symbol": "SH510300",
                "benchmark_symbol": "CASH_0",
                "benchmark_source": "cash_zero_return",
                "benchmark_family": "ABSOLUTE_RETURN_PROXY",
                "benchmark_return": 0.0,
                "cost_model_id": "macro_asset_etf_round_trip_10bps_v1",
                "outcome_label_source": "pit_macro_asset_etf_price_window",
                "decision_basis": "directional_macro_asset_proxy_return",
                "source_horizon_days": 180,
                "source_horizon_bucket": "medium",
                "evaluation_policy": "macro_asset_t_plus_1_multi_window_proxy_retains_long_horizon_evidence",
                "relative_alpha": 0.02,
                "after_cost_alpha": 0.019,
                "macro_asset_target_id": "CN_A_SHARE_BROAD",
                "mapping_id": "MACRO-PROXY-TEST",
                "mapping_version": 1,
                "mapping_confidence": "operator_seeded_macro_asset_alias",
                "proxy_return": 0.02,
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
            _base_outcome_label("macro_asset_proxy"),
        ],
    )

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == 3
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


def test_report_outcome_label_semantics_reject_bad_macro_window_role(
    tmp_path: Path,
):
    macro_label = _base_outcome_label("macro_asset_proxy")
    macro_label["horizon_days"] = 180
    macro_label["window_role"] = "short"
    _write_proxy_outcome_labels(tmp_path, [macro_label])

    record = _proxy_outcome_contract_record(tmp_path)

    assert record.accepted is False
    assert any("window_role: must be medium" in failure for failure in record.failures)


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
    assert len(mapping_rows) == availability["mapping_count"]
    action_summary = availability["labelability_action_summary"]
    assert action_summary["sector_etf_mapping_missing_count"] == (
        availability["labelability_summary"]["sector_etf_mapping_missing_count"]
    )
    assert action_summary["pit_unavailable_mapping_count"] == (
        availability["mapping_count"] - availability["pit_available_mapping_count"]
    )
    assert (
        "add_primary_etf_mapping_for_unmapped_industry_sectors"
        in action_summary["next_actions"]
    )
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


def test_industry_etf_mapping_contract_rejects_action_summary_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    availability_path = registry / "industry_etf_proxy_pit_availability.json"
    availability = json.loads(availability_path.read_text(encoding="utf-8"))
    availability["labelability_action_summary"]["remaining_action_count"] = 0
    availability["labelability_action_summary"]["next_actions"] = []
    availability_path.write_text(
        json.dumps(availability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any("labelability_action_summary.remaining_action_count" in item for item in record.failures)
    assert any("labelability_action_summary.next_actions: required" in item for item in record.failures)


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


def test_industry_etf_mapping_contract_rejects_proxy_sector_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
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
    available_mapping_ids = {
        record["mapping_id"]
        for record in availability["mapping_records"]
        if record.get("pit_available") is True
    }
    mapping = next(
        row for row in mapping_rows if row["mapping_id"] in available_mapping_ids
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
            "proxy_sector": "stale-sector-name",
            "proxy_symbol": mapping["etf_symbol"],
        }
    )
    _write_proxy_outcome_labels(tmp_path, [label])

    record = _industry_etf_mapping_contract_record(tmp_path)

    assert not record.accepted
    assert any("proxy_sector: mapping mismatch" in item for item in record.failures)


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


def test_markdown_coverage_privacy_rules_reject_stale_blocked_status(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["coverage_gate_status"] = "blocked"
    coverage["coverage_gate_blockers"] = []
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
        "markdown_coverage_summary.coverage_gate_status: expected passed" in failure
        for failure in record.failures
    )


def test_markdown_coverage_privacy_rules_reject_stale_count_blocker(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["coverage_gate_status"] = "blocked"
    coverage["coverage_gate_blockers"] = ["selected_report_count_below_p9_target"]
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
        "stale selected_report_count_below_p9_target" in failure
        for failure in record.failures
    )


def test_markdown_coverage_privacy_rules_reject_shortfall_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["coverage_shortfalls"]["selected_report_count"]["remaining"] = 999
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
        "coverage_shortfalls.selected_report_count.remaining: expected 0" in failure
        for failure in record.failures
    )


def test_markdown_coverage_privacy_rules_reject_shortfall_next_action_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    coverage_path = registry / "markdown_coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["coverage_shortfalls"]["selected_report_count"][
        "next_action"
    ] = "stale_action"
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
        "coverage_shortfalls.selected_report_count.next_action: expected "
        "add_stratified_real_reports_to_private_source_pool" in failure
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


def test_recipe_paper_trading_contract_rejects_confidence_observation_id_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    observations_path = registry / "confidence_impact_observations.jsonl"
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations[1]["confidence_observation_id"] = observations[0][
        "confidence_observation_id"
    ]
    observations[2]["confidence_observation_id"] = "CIMOBS-posthoc-override"
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
        "confidence_observation_id: duplicate" in item for item in record.failures
    )
    assert any(
        "confidence_observation_id: must bind run_id and recipe_id" in item
        for item in record.failures
    )


def test_recipe_paper_trading_contract_rejects_monitor_action_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitor_path = registry / "confidence_impact_monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
    monitor["recommended_action_counts"] = {"keep_shadow": 4}
    monitor_path.write_text(
        json.dumps(monitor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("recommended_action_counts mismatch" in item for item in record.failures)


def test_public_summary_privacy_rejects_id_queues(tmp_path: Path):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitor_path = registry / "confidence_impact_monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
    monitor["tracked_recipe_ids"] = ["RECIPE-PRIVATE"]
    monitor["requested_tools"] = ["tool.requested.private_source_phrase"]
    monitor["tool_gap_ids"] = ["TOOL-GAP-PRIVATE"]
    monitor_path.write_text(
        json.dumps(monitor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = next(
        item
        for item in validate_report_intelligence_semantics(tmp_path)
        if item.schema_path
        == "schemas/report_intelligence_public_id_queue_privacy_rules"
    )

    assert not record.accepted
    assert any("private id queue field forbidden" in item for item in record.failures)
    assert any("private queue field forbidden" in item for item in record.failures)


def test_recipe_paper_trading_contract_rejects_monitor_derived_field_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    monitor_path = registry / "confidence_impact_monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
    monitor["unvalidated_confidence_impact_count"] = 99
    monitor["alpha_decay_fail_count"] = 0
    monitor["aggregate_calibration_drift_count"] = 1
    monitor["confidence_alpha_correlation"] = -1.0
    monitor["confidence_alpha_correlation_status"] = "negative"
    monitor["confidence_delta_bucket_outcomes"] = {}
    monitor["calibration_drift_rule_counts"] = {"manual_override": 1}
    monitor_path.write_text(
        json.dumps(monitor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    expected_fragments = [
        "unvalidated_confidence_impact_count",
        "alpha_decay_fail_count",
        "aggregate_calibration_drift_count",
        "confidence_alpha_correlation mismatch",
        "confidence_alpha_correlation_status mismatch",
        "confidence_delta_bucket_outcomes mismatch",
        "calibration_drift_rule_counts mismatch",
    ]
    for fragment in expected_fragments:
        assert any(fragment in item for item in record.failures)


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


def test_recipe_paper_trading_contract_rejects_validated_count_alias_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    summary_path = registry / "recipe_paper_trading_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["paper_trading_validated_recipe_count"] = (
        int(summary["validation_pass_count"]) + 1
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "recipe_paper_trading_summary.paper_trading_validated_recipe_count"
        in item
        for item in record.failures
    )


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


def test_recipe_paper_trading_contract_rejects_experiment_id_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    runs_path = registry / "recipe_paper_trading_runs.jsonl"
    runs = [
        json.loads(line)
        for line in runs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    runs[1]["experiment_id"] = runs[0]["experiment_id"]
    runs[2]["paper_trading_run_id"] = runs[0]["paper_trading_run_id"]
    runs[3]["experiment_id"] = "RIEXP-posthoc-override"
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in runs)
        + "\n",
        encoding="utf-8",
    )

    record = _recipe_paper_trading_contract_record(tmp_path)

    assert not record.accepted
    assert any("experiment_id: duplicate" in item for item in record.failures)
    assert any("paper_trading_run_id: duplicate" in item for item in record.failures)
    assert any(
        "experiment_id: must bind analysis_recipe_id and protocol_version" in item
        for item in record.failures
    )


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


def test_evolution_readiness_gate_contract_tracks_current_public_artifact(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)

    record = _evolution_readiness_gate_record(tmp_path)
    gate = json.loads((registry / "evolution_readiness_gate.json").read_text(encoding="utf-8"))
    monitor_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-03"
    )
    monitor_summary = monitor_check["evidence"]["recipe_level_monitor"]

    assert record.accepted
    assert record.item_count == len(gate["checks"])
    assert record.failures == ()
    assert isinstance(monitor_summary["recipe_level_risk_counts"], dict)
    assert isinstance(monitor_summary["recommended_action_counts"], dict)
    assert isinstance(monitor_summary["actionable_recipe_level_action_counts"], dict)
    assert "global_blocker_policy" in monitor_summary


def test_evolution_readiness_gate_cli_reports_monitor_recipe_actions(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate = json.loads((registry / "evolution_readiness_gate.json").read_text(encoding="utf-8"))
    monitor_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-03"
    )
    monitor_check["evidence"]["recipe_level_monitor"] = {
        "actionable_recipe_level_action_count": 2,
        "actionable_recipe_level_action_counts": {"freeze_recipe": 2},
        "global_blocker_policy": (
            "per-recipe risks stay shadow-only unless aggregate blockers exist"
        ),
        "recipe_level_risk_count": 2,
        "recipe_level_risk_counts": {"alpha_decay_fail_count": 2},
        "recommended_action_counts": {"freeze_recipe": 2, "keep_shadow": 1},
    }
    cli_summary = _evolution_gate_cli_summary(gate)
    next_actions = {action["action_id"]: action for action in cli_summary["next_actions"]}
    monitor_action = next_actions["review_confidence_monitor_recipe_actions"]
    assert monitor_action["quality_gap_targets"]["recommended_action_counts"][
        "freeze_recipe"
    ] > 0
    assert (
        "mosaic-rke evolution-readiness --root . --refresh-prompt-mutations"
        in monitor_action["commands"]["refresh_prompt_mutations"]
    )


def test_evolution_readiness_gate_contract_rejects_missing_monitor_recipe_summary(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    monitor_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-03"
    )
    monitor_check["evidence"].pop("recipe_level_monitor", None)
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "RI-EVOL-03].evidence.recipe_level_monitor: expected object" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_monitor_recipe_count_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    monitor_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-03"
    )
    summary = monitor_check["evidence"]["recipe_level_monitor"]
    summary["actionable_recipe_level_action_count"] = 0
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "actionable_recipe_level_action_count: mismatch" in item
        for item in record.failures
    )


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


def test_evolution_readiness_gate_contract_allows_complete_macro_check_group(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["checks"] = [
        check
        for check in gate["checks"]
        if not str(check.get("check_id") or "").startswith("RI-MACRO-")
    ]
    gate["checks"].extend(
        {
            "check_id": f"RI-MACRO-{index:02d}",
            "requirement": "macro gate fixture",
            "passed": True,
            "evidence": {},
            "blockers": [],
        }
        for index in range(1, 8)
    )
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert record.accepted


def test_evolution_readiness_gate_contract_rejects_partial_macro_check_group(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["checks"] = [
        check
        for check in gate["checks"]
        if not str(check.get("check_id") or "").startswith("RI-MACRO-")
    ]
    gate["checks"].append(
        {
            "check_id": "RI-MACRO-01",
            "requirement": "macro gate fixture",
            "passed": True,
            "evidence": {},
            "blockers": [],
        }
    )
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "incomplete optional check group: RI-MACRO-02" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_allows_complete_stock_industry_check_groups(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["checks"].extend(
        {
            "check_id": check_id,
            "requirement": "domain gate fixture",
            "passed": True,
            "evidence": {},
            "blockers": [],
        }
        for check_id in (
            "RI-STOCK-01",
            "RI-STOCK-02",
            "RI-STOCK-03",
            "RI-STOCK-04",
            "RI-INDUSTRY-01",
            "RI-INDUSTRY-02",
            "RI-INDUSTRY-03",
            "RI-INDUSTRY-04",
        )
    )
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert record.accepted


def test_evolution_readiness_gate_contract_rejects_partial_stock_check_group(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["checks"].append(
        {
            "check_id": "RI-STOCK-01",
            "requirement": "stock gate fixture",
            "passed": True,
            "evidence": {},
            "blockers": [],
        }
    )
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "incomplete optional check group: RI-STOCK-02" in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_blocker_count_mismatch(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    for check in gate["checks"]:
        if check["check_id"] == "RI-EVOL-04":
            check["blockers"] = ["audit_refresh_history_below_threshold"]
    gate["blockers"] = ["audit_refresh_history_below_threshold"]
    gate["blocker_count"] = 0
    gate["gate_status"] = "passed"
    gate["promotion_state"] = "ready_for_shadow_evolution_candidate"
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "evolution_readiness_gate.blocker_count: expected 1" in item
        for item in record.failures
    )
    assert any(
        "evolution_readiness_gate.gate_status: expected blocked" in item
        for item in record.failures
    )
    assert any(
        "evolution_readiness_gate.promotion_state: expected blocked_before_prompt_evolution"
        in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_synthetic_prior_refusal_only_pass(
    tmp_path: Path,
):
    gate = {
        "blocker_count": 0,
        "blockers": [],
        "checks": [
            {
                "blockers": [],
                "check_id": "RI-EVOL-08",
                "evidence": {
                    "prior_compiler_actionable_candidate_count": 0,
                    "prior_compiler_candidate_count": 4,
                },
                "passed": True,
                "requirement": "prior compiler fixture",
            }
        ],
        "gate_status": "passed",
        "private_text_included": False,
        "production_prompt_change_allowed": False,
        "promotion_state": "ready_for_shadow_evolution_candidate",
        "thresholds": {},
    }
    _write_evolution_readiness_gate(tmp_path, gate)

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "prior_compiler_refusal_only required" in item for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_prior_compiler_refusal_only_pass(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    check = next(row for row in gate["checks"] if row["check_id"] == "RI-EVOL-08")
    check["blockers"] = []
    check["passed"] = True
    check["evidence"]["prior_compiler_actionable_candidate_count"] = 0
    gate["blockers"] = [
        blocker
        for blocker in gate["blockers"]
        if blocker != "prior_compiler_refusal_only"
    ]
    gate["blocker_count"] = len(gate["blockers"])
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "prior_compiler_refusal_only required" in item for item in record.failures
    )


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


def test_evolution_readiness_gate_contract_rejects_stale_audit_failure_summary(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    dependency = audit_check["evidence"]["audit_history_dependency"]
    dependency["current_failure_counts"]["schema"] = 0
    dependency["current_failure_refs"]["pit"] = ["check:RI-PIT-STale"]
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted


def test_evolution_readiness_gate_contract_rejects_self_schema_audit_ref(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    evidence = audit_check["evidence"]
    dependency = evidence["audit_history_dependency"]
    self_ref = "schemas/report_intelligence_evolution_readiness_gate_rules"
    evidence["current_failure_counts"]["schema"] += 5
    dependency["current_failure_counts"]["schema"] += 5
    evidence["current_failure_refs"]["schema"].append(self_ref)
    dependency["current_failure_refs"]["schema"].append(self_ref)
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "current_failure_refs.schema: must exclude evolution-readiness self schema rule"
        in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_audit_ref_summary_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    audit_check["evidence"]["current_failure_counts"]["schema"] = 1
    audit_check["evidence"]["current_failure_refs"]["schema"] = [
        "schemas/report_intelligence_gold_review_gate_rules"
    ]
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _evolution_readiness_gate_record(tmp_path)

    assert not record.accepted
    assert any(
        "evidence.current_failure_counts: must match "
        "audit_history_dependency.current_failure_counts"
        in item
        for item in record.failures
    )
    assert any(
        "evidence.current_failure_refs.schema: must match "
        "audit_history_dependency.current_failure_refs"
        in item
        for item in record.failures
    )


def test_evolution_readiness_gate_contract_rejects_stale_audit_history_blocker(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    gate_path = registry / "evolution_readiness_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["blockers"] = ["audit_refresh_history_below_threshold"]
    gate["blocker_count"] = 1
    gate["gate_status"] = "blocked"
    gate["promotion_state"] = "blocked"
    audit_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-04"
    )
    audit_check["passed"] = False
    audit_check["blockers"] = ["audit_refresh_history_below_threshold"]
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
    gold_check["evidence"]["reviewed_claims"] = 100
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
    gold_check["evidence"]["reviewed_claims"] = 100
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
            "reviewed_claims": 99,
            "total_claims": 100,
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
    assert any("reviewed_claims: expected >= 100" in item for item in record.failures)
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
    registry = _copy_report_intelligence_registry(tmp_path)
    expected_count = sum(
        1
        for line in (registry / "prompt_mutation_candidates.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == expected_count
    assert record.item_count > 0
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


def test_prompt_mutation_candidate_contract_rejects_prior_refusal_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    refusal = next(
        row for row in candidates if str(row["candidate_type"]).endswith("_refusal")
    )
    refusal["blocked_by"] = []
    evidence = refusal["evidence_refs"][0]
    assert isinstance(evidence, dict)
    evidence["candidate_kind"] = "macro_rule_parameter_candidate"
    evidence["refusal_reasons"] = ["unsupported_refusal"]
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any("unsupported unsupported_refusal" in item for item in record.failures)
    assert any("blocked_by: must include refusal reasons" in item for item in record.failures)
    assert any("candidate_kind: must be refusal" in item for item in record.failures)


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


def test_prompt_mutation_candidate_contract_rejects_gold_quality_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    repair = next(
        (
            row
            for row in candidates
            if row["candidate_type"] == "gold_quality_prompt_repair_rule"
        ),
        None,
    )
    if repair is None:
        return
    evidence = repair["evidence_refs"][0]
    assert isinstance(evidence, dict)
    metric_failures = evidence["metric_failures"]
    assert isinstance(metric_failures, dict)
    direction_failure = metric_failures["direction_accuracy"]
    assert isinstance(direction_failure, dict)
    direction_failure["current_rate"] = 0.99
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "gold_quality_prompt_repair_rule.evidence_refs.metric_failures" in item
        for item in record.failures
    )


def test_prompt_mutation_candidate_contract_rejects_footprint_quality_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    repair = next(
        (
            row
            for row in candidates
            if row["candidate_type"] == "footprint_quality_prompt_repair_rule"
        ),
        None,
    )
    if repair is None:
        return
    evidence = repair["evidence_refs"][0]
    assert isinstance(evidence, dict)
    evidence["pending_rows"] = 0
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    assert any(
        "footprint_quality_prompt_repair_rule.evidence_refs.pending_rows" in item
        for item in record.failures
    )


def test_prompt_mutation_candidate_contract_rejects_refresh_stability_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    stability = next(
        (
            row
            for row in candidates
            if row["candidate_type"] == "evolution_refresh_stability_rule"
        ),
        None,
    )
    if stability is None:
        return
    evidence_refs = stability["evidence_refs"]
    assert isinstance(evidence_refs, list)
    evidence = evidence_refs[0]
    assert isinstance(evidence, dict)
    payload = evidence["evidence"]
    assert isinstance(payload, dict)
    payload["data_vintage_hash"] = "sha256:" + ("0" * 64)
    payload["current_failure_counts"] = {
        "pit": 0,
        "provenance": 0,
        "schema": 999,
        "statistical": 0,
    }
    evidence["blockers"] = ["audit_refresh_history_below_threshold"]
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted


def test_prompt_mutation_candidate_contract_rejects_industry_mapping_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    mapping = next(
        row for row in candidates if row["candidate_type"] == "industry_proxy_mapping_rule"
    )
    evidence_refs = mapping["evidence_refs"]
    assert isinstance(evidence_refs, list)
    action = next(
        row
        for row in evidence_refs
        if isinstance(row, dict) and row.get("field") == "labelability_action_summary"
    )
    pit = next(
        row
        for row in evidence_refs
        if isinstance(row, dict) and row.get("field") == "pit_gap_counts"
    )
    readiness = next(
        row
        for row in evidence_refs
        if isinstance(row, dict)
        and row.get("field") == "industry_etf_proxy_readiness.data_gap_counts"
    )
    action["remaining_action_count"] = 0
    action["next_actions"] = []
    pit["gap_counts"] = {}
    readiness["sector_etf_mapping_missing_count"] = 0
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    expected_fragments = [
        "industry_proxy_mapping_rule.evidence_refs.labelability_action_summary.remaining_action_count",
        "industry_proxy_mapping_rule.evidence_refs.labelability_action_summary.next_actions",
        "industry_proxy_mapping_rule.evidence_refs.pit_gap_counts.gap_counts",
        "industry_proxy_mapping_rule.evidence_refs.industry_etf_proxy_readiness.data_gap_counts.sector_etf_mapping_missing_count",
    ]
    for fragment in expected_fragments:
        assert any(fragment in item for item in record.failures)


def test_prompt_mutation_candidate_contract_rejects_calibration_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    calibration = next(
        row for row in candidates if row["candidate_type"] == "calibration_fix_required"
    )
    evidence_refs = calibration["evidence_refs"]
    assert isinstance(evidence_refs, list)
    evidence = next(
        row
        for row in evidence_refs
        if isinstance(row, dict) and row.get("field") == "drift_status_counts"
    )
    evidence["drift_status_counts"] = {"stable_shadow": 1}
    evidence["confidence_alpha_correlation_status"] = "negative"
    recipe_level = evidence["recipe_level_monitor"]
    assert isinstance(recipe_level, dict)
    recipe_level["actionable_recipe_level_action_count"] = 0
    recipe_level["actionable_recipe_level_action_counts"] = {}
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    expected_fragments = [
        "calibration_fix_required.evidence_refs.drift_status_counts.drift_status_counts",
        "calibration_fix_required.evidence_refs.drift_status_counts.confidence_alpha_correlation_status",
        "calibration_fix_required.evidence_refs.drift_status_counts.recipe_level_monitor",
    ]
    for fragment in expected_fragments:
        assert any(fragment in item for item in record.failures)


def test_prompt_mutation_candidate_contract_rejects_mapping_markdown_confidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    confidence = next(
        row for row in candidates if row["candidate_type"] == "confidence_gate_rule"
    )
    target = next(row for row in candidates if row["candidate_type"] == "target_mapping_rule")
    horizon = next(
        row for row in candidates if row["candidate_type"] == "horizon_direction_rule"
    )
    markdown = next(
        (
            row
            for row in candidates
            if row["candidate_type"] == "markdown_quality_rule"
        ),
        None,
    )

    confidence_evidence = confidence["evidence_refs"][0]
    target_evidence = target["evidence_refs"][0]
    horizon_evidence = horizon["evidence_refs"][0]
    assert isinstance(confidence_evidence, dict)
    assert isinstance(target_evidence, dict)
    assert isinstance(horizon_evidence, dict)
    confidence_evidence["blocked_observation_count"] = 0
    target_evidence["gap_counts"] = {}
    target_evidence["total_gap_count"] = 0
    horizon_evidence["gap_counts"] = {"horizon": 1}
    horizon_evidence["total_gap_count"] = 1
    if markdown is not None:
        markdown_evidence = markdown["evidence_refs"][0]
        assert isinstance(markdown_evidence, dict)
        markdown_evidence["gap_counts"] = {}
        markdown_evidence["retry_queue_count"] = 0
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    expected_fragments = [
        "confidence_gate_rule.evidence_refs.paper_trading_status.blocked_observation_count",
        "target_mapping_rule.evidence_refs.stock_price_proxy_readiness.data_gap_counts.gap_counts",
        "target_mapping_rule.evidence_refs.stock_price_proxy_readiness.data_gap_counts.total_gap_count",
        "horizon_direction_rule.evidence_refs.mapping_gap_counts.gap_counts",
        "horizon_direction_rule.evidence_refs.mapping_gap_counts.total_gap_count",
    ]
    if markdown is not None:
        expected_fragments.extend(
            [
                "markdown_quality_rule.evidence_refs.markdown_quality_gap_counts.gap_counts",
                "markdown_quality_rule.evidence_refs.markdown_quality_gap_counts.retry_queue_count",
            ]
        )
    for fragment in expected_fragments:
        assert any(fragment in item for item in record.failures)


def test_prompt_mutation_candidate_contract_rejects_remaining_public_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    gold = next(
        (
            row
            for row in candidates
            if row["candidate_type"] == "forecast_gold_set_review_rule"
        ),
        None,
    )
    regime = next(
        row
        for row in candidates
        if row["candidate_type"] == "regime_mechanism_extraction_rule"
    )
    tool_gap = next(
        row
        for row in candidates
        if row["candidate_type"] == "tool_gap_prioritization_rule"
    )
    paper = next(
        row for row in candidates if row["candidate_type"] == "recipe_paper_trading_rule"
    )

    regime_evidence = regime["evidence_refs"][0]
    tool_gap_evidence = tool_gap["evidence_refs"][0]
    paper_blockers = next(
        row
        for row in paper["evidence_refs"]
        if isinstance(row, dict) and row.get("field") == "blocked_reasons"
    )
    paper_diagnostics = next(
        row
        for row in paper["evidence_refs"]
        if isinstance(row, dict)
        and row.get("field") == "direct_pit_binding_diagnostics"
    )
    assert isinstance(regime_evidence, dict)
    assert isinstance(tool_gap_evidence, dict)
    if gold is not None:
        gold_evidence = gold["evidence_refs"][0]
        assert isinstance(gold_evidence, dict)
        gold_evidence["reviewed_claims"] = 0
        gold_evidence["blockers"] = []
    regime_evidence["hard_gap_count"] = 0
    regime_evidence["mechanism_gap_counts"] = {}
    tool_gap_evidence["priority_counts"] = {}
    tool_gap_evidence["top_tool_gap_ids"] = []
    paper_blockers["blocker_counts"] = {}
    paper_diagnostics["no_direct_recipe_outcome_binding_count"] = 0
    paper_diagnostics["next_actions"] = []
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    expected_fragments = [
        "regime_mechanism_extraction_rule.evidence_refs.regime_gap_counts.mechanism_gap_counts.hard_gap_count",
        "regime_mechanism_extraction_rule.evidence_refs.regime_gap_counts.mechanism_gap_counts.mechanism_gap_counts",
        "tool_gap_prioritization_rule.evidence_refs.priority_bucket.priority_counts",
        "tool_gap_prioritization_rule.evidence_refs.priority_bucket.top_tool_gap_ids",
        "recipe_paper_trading_rule.evidence_refs.blocked_reasons.blocker_counts",
        "recipe_paper_trading_rule.evidence_refs.direct_pit_binding_diagnostics.no_direct_recipe_outcome_binding_count",
        "recipe_paper_trading_rule.evidence_refs.direct_pit_binding_diagnostics.next_actions",
    ]
    if gold is not None:
        expected_fragments.extend(
            [
                "forecast_gold_set_review_rule.evidence_refs.checks.RI-EVOL-05.evidence.reviewed_claims",
                "forecast_gold_set_review_rule.evidence_refs.checks.RI-EVOL-05.evidence.blockers",
            ]
        )
    for fragment in expected_fragments:
        assert any(fragment in item for item in record.failures)


def test_prompt_mutation_candidate_contract_rejects_data_acquisition_evidence_drift(
    tmp_path: Path,
):
    registry = _copy_report_intelligence_registry(tmp_path)
    proposals_path = registry / "data_acquisition_proposals.jsonl"
    proposals_path.write_text(
        json.dumps(
            {
                "data_proposal_id": "DAP-MARKET-CAP",
                "tool_gap_id": "stock_context_market_cap_metadata_missing",
                "business_priority": "medium",
                "pit_feasibility_status": "requires_pit_backfill_review",
                "license_status": "pending_review",
                "decision_status": "pending_review",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    candidates_path = registry / "prompt_mutation_candidates.jsonl"
    candidates = _read_prompt_mutation_candidates(candidates_path)
    candidate = dict(candidates[0])
    candidate.update(
        {
            "mutation_candidate_id": "PMUT-DATA-ACQUISITION-TEST",
            "candidate_type": "data_acquisition_prioritization_rule",
            "target_scope": "report_intelligence.data_acquisition",
            "target_component": "data_acquisition_review_queue",
            "proposed_change": "Keep data acquisition gaps blocked until review.",
            "trigger_sources": ["data_acquisition_proposals"],
            "evidence_refs": [
                {
                    "artifact_path": (
                        "registry/report_intelligence/"
                        "data_acquisition_proposals.jsonl"
                    ),
                    "field": "decision_status",
                    "proposal_count": 0,
                    "business_priority_counts": {},
                    "pit_feasibility_status_counts": {},
                    "license_status_counts": {},
                    "market_cap_metadata_gap_count": 0,
                    "top_tool_gap_ids": [],
                }
            ],
            "severity": "medium",
            "blocked_by": ["data_engineering_review_required"],
            "promotion_state": "shadow_candidate_only",
            "manual_review_required": True,
            "production_prompt_change_allowed": False,
            "private_text_included": False,
        }
    )
    candidates.append(candidate)
    _write_prompt_mutation_candidates(candidates_path, candidates)

    record = _prompt_mutation_candidate_contract_record(tmp_path)

    assert not record.accepted
    expected_fragments = [
        "data_acquisition_prioritization_rule.evidence_refs.decision_status.proposal_count",
        "data_acquisition_prioritization_rule.evidence_refs.decision_status.business_priority_counts",
        "data_acquisition_prioritization_rule.evidence_refs.decision_status.pit_feasibility_status_counts",
        "data_acquisition_prioritization_rule.evidence_refs.decision_status.license_status_counts",
        "data_acquisition_prioritization_rule.evidence_refs.decision_status.market_cap_metadata_gap_count",
        "data_acquisition_prioritization_rule.evidence_refs.decision_status.top_tool_gap_ids",
    ]
    for fragment in expected_fragments:
        assert any(fragment in item for item in record.failures)


def _copy_registry_for_manual_progress(tmp_path: Path) -> Path:
    registry = tmp_path / "registry"
    shutil.copytree(
        Path("registry"),
        registry,
        dirs_exist_ok=True,
        ignore=_ignore_private_registry_inputs,
    )
    report_intelligence = registry / "report_intelligence"
    report_intelligence.mkdir()
    (report_intelligence / "feature_flags.json").write_text(
        json.dumps(
            {
                "allowed_rollout_modes": [
                    "off",
                    "extraction_only",
                    "shadow_retrieval",
                    "shadow_tooling",
                    "paper_trading",
                    "limited_production",
                    "production",
                ],
                "flags": {
                    "analytical_footprint_enabled": True,
                    "method_pattern_registry_enabled": True,
                    "production_use_of_weighted_reports": False,
                    "report_weighting_enabled": True,
                    "shadow_tool_runtime_enabled": True,
                    "tool_design_loop_enabled": True,
                    "weighted_research_retriever_enabled": True,
                },
                "rollout_mode": "shadow_tooling",
                "runtime_behavior": (
                    "shadow retrieval and shadow tooling only; no agent decision impact; "
                    "no trade without current data confirmation, validated recipes, "
                    "paper trading gates, and production promotion approval"
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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


def test_manual_review_progress_privacy_allows_workload_field_count_names(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    evidence_status = progress["gates"][0]["current_batch_status"]["evidence_status"]
    evidence_status["review_field_workload"]["manual_claim_text"] = {
        "draft_decision_available_rows": 0,
        "manual_decision_required_rows": 500,
        "missing_required_rows": 500,
        "suggested_false_rows": 0,
        "suggested_null_rows": 0,
        "suggested_other_rows": 0,
        "suggested_true_rows": 0,
    }
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_privacy_record(tmp_path)

    assert record.accepted


def test_manual_review_progress_privacy_allows_batch_overview_workload_counts(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    batch_overview = progress["gates"][0]["batch_overview"]
    workload = batch_overview.setdefault("current_batch_review_field_workload", {})
    workload["manual_claim_text"] = {
        "draft_decision_available_rows": 0,
        "manual_decision_required_rows": 500,
        "missing_required_rows": 500,
        "suggested_false_rows": 0,
        "suggested_null_rows": 0,
        "suggested_other_rows": 0,
        "suggested_true_rows": 0,
    }
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
    gold_current = progress["gates"][0]["current_batch_status"]
    footprint_evidence = progress["gates"][1]["current_batch_status"][
        "evidence_status"
    ]
    footprint_current = progress["gates"][1]["current_batch_status"]
    footprint_target = footprint_current.get("target_status") or {}

    record = _manual_review_progress_contract_record(tmp_path)

    assert record.accepted
    assert record.item_count == 4
    assert record.failures == ()
    if (
        gold_evidence["review_input_rows"]
        and not gold_current.get("already_applied")
        and not progress["gates"][0]["ready_for_promotion"]
    ):
        assert gold_evidence["aligned"] is True
        assert gold_evidence["covered_review_rows"] == gold_evidence["review_input_rows"]
    if (
        footprint_evidence["review_input_rows"]
        and not footprint_current.get("already_applied")
        and not progress["gates"][1]["ready_for_promotion"]
        and footprint_target.get("aligned") is True
    ):
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
        gate["batch_overview"] = (
            {
                "batch_count": 0,
                "pending_rows": 0,
                "promotion_input_path": gate["input_path"],
                "current_batch_stale_after_promotion_ready": False,
                "stale_current_batch_path": "",
                "stale_current_batch_pending_rows": 0,
                "rerun_review_progress_after_batch_apply": False,
            }
            if gate["review_kind"] in {"gold_set", "footprint_review"}
            else {}
        )
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
    footprint_gate = next(
        gate for gate in progress["gates"] if gate["review_kind"] == "footprint_review"
    )
    footprint_gate["ready_for_promotion"] = True
    footprint_gate["simulation_accepted"] = True
    footprint_gate["blockers"] = ["still blocked"]
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_contract_record(tmp_path)

    assert not record.accepted
    assert record.failures


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
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke apply-footprint-review --root ."
    )
    progress["gates"][1]["apply_command"] = (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke apply-footprint-review --root . "
        "--input registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    progress["gates"][1]["current_batch_status"]["pending_rows"] = 49
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


def test_manual_review_progress_contract_rejects_batch_overview_drift(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    progress_path = registry / "review_batches/manual_review_progress_report.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    gold_gate = next(gate for gate in progress["gates"] if gate["review_kind"] == "gold_set")
    overview = gold_gate["batch_overview"]
    overview["promotion_input_path"] = "registry/review_batches/stale.jsonl"
    progress_path.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_progress_contract_record(tmp_path)

    assert not record.accepted
    assert record.failures


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


def test_operator_handoff_contract_rejects_batch_overview_drift(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    handoff_path = registry / "handoffs/rke_operator_handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    gold_gate = next(
        gate for gate in handoff["gates"] if gate["review_kind"] == "gold_set"
    )
    gold_gate["batch_overview"]["promotion_input_path"] = (
        "registry/review_batches/stale.jsonl"
    )
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_handoff_record(tmp_path)

    assert not record.accepted
    assert any(
        "batch_overview: must match manual_review_progress_report gate batch_overview"
        in item
        for item in record.failures
    )


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
    handoff["next_state"] = "paper_trading"
    handoff_path.write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _operator_handoff_record(tmp_path)

    assert not record.accepted
    assert any("step_id order mismatch" in item for item in record.failures)
    assert any("missing MOSAIC_RKE_TMPDIR prefix" in item for item in record.failures)
    assert any("missing TMPDIR prefix" in item for item in record.failures)
    assert any(
        "next_state: expected production when production is allowed" in item
        for item in record.failures
    )


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
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke review-progress --root ."
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


def test_manual_review_bundle_manifest_contract_accepts_staged_lockbox_gap(
    tmp_path: Path,
):
    registry = _copy_registry_for_manual_progress(tmp_path)
    report_path = registry / "promotion/rke_promotion_dry_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "accepted": False,
            "after_blockers": ["lockbox has not been opened"],
            "after_next_state": "staged_production",
            "production_allowed_after_simulation": False,
            "staged_production_allowed_after_simulation": True,
        }
    )
    for step in report["steps"]:
        if step["review_kind"] == "lockbox":
            step.update(
                {
                    "accepted": False,
                    "applied": False,
                    "blockers": ["lockbox input not provided"],
                    "changed_rows": None,
                    "input_path": "",
                    "provided": False,
                    "result": "not_provided",
                }
            )
        else:
            step.update(
                {
                    "accepted": True,
                    "applied": False,
                    "blockers": [],
                    "changed_rows": 0,
                    "input_path": "",
                    "provided": False,
                    "result": "already_applied",
                }
            )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = registry / "review_batches/manual_review_bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["promotion_dry_run"] = {
        "accepted": False,
        "accepted_steps": ["gold_set", "footprint_review", "source_license"],
        "after_next_state": "staged_production",
        "already_applied_steps": [
            "gold_set",
            "footprint_review",
            "source_license",
        ],
        "missing_steps": ["lockbox"],
        "production_allowed_after_simulation": False,
        "provided_steps": [],
        "rejected_steps": ["lockbox"],
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
    expected_production = (
        manifest["promotion_dry_run"]["after_next_state"] == "production"
    )
    manifest["promotion_dry_run"]["production_allowed_after_simulation"] = (
        not expected_production
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _manual_review_bundle_manifest_record(tmp_path)

    assert not record.accepted
    assert any(".bytes: must be positive" in item for item in record.failures)
    assert any(".sha256: must be sha256:<64 hex>" in item for item in record.failures)
    assert any(
        f"production_allowed_after_simulation: expected {expected_production}" in item
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
    expected_production_after = report["after_next_state"] == "production"
    expected_staged_after = report["after_next_state"] in {
        "staged_production",
        "production",
    }
    report["production_allowed_after_simulation"] = not expected_production_after
    report["staged_production_allowed_after_simulation"] = not expected_staged_after
    report["mutated_original_registry"] = True
    report["steps"][0]["accepted"] = False
    report["steps"][0]["blockers"] = ["fixture rejection"]
    report["steps"][0]["result"] = "rejected"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record = _promotion_dry_run_record(tmp_path)

    assert not record.accepted
    assert any("accepted mismatch with steps" in item for item in record.failures)
    assert any(
        f"production_allowed_after_simulation: expected {expected_production_after}"
        in item
        for item in record.failures
    )
    assert any(
        f"staged_production_allowed_after_simulation: expected {expected_staged_after}"
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
    gate["criteria"][0]["passed"] = False
    gate["criteria"][0]["blocker"] = "fixture_failed"
    gate["blockers"] = ["fixture_failed"]
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


def test_schema_validation_tracks_current_public_registry_without_private_report_inputs(
    tmp_path: Path,
):
    shutil.copytree("schemas", tmp_path / "schemas")
    shutil.copytree(
        "registry",
        tmp_path / "registry",
        ignore=_ignore_private_registry_inputs,
    )

    report = build_schema_validation_report(tmp_path)

    assert report.accepted
    assert report.failure_count == 0
    assert all(record.accepted for record in report.records)
    local_report_intelligence_artifacts = {
        artifact_path
        for _, artifact_path, _, _ in REPORT_INTELLIGENCE_JSON_SCHEMA_TARGETS
    }
    local_records = {
        record.artifact_path: record for record in report.records
        if record.artifact_path in local_report_intelligence_artifacts
    }
    assert set(local_records) == local_report_intelligence_artifacts
    assert all(record.item_count == 0 for record in local_records.values())
    assert all(record.accepted for record in local_records.values())


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


def test_schema_validation_enforces_local_refs_min_properties_and_one_of(
    tmp_path: Path,
):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/report_intelligence"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "composed.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "Composed fixture",
                "type": "object",
                "required": ["digest", "registry", "variant"],
                "properties": {
                    "digest": {"$ref": "#/$defs/sha256"},
                    "registry": {
                        "type": "object",
                        "minProperties": 1,
                    },
                    "variant": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "integer"},
                        ]
                    },
                },
                "$defs": {
                    "sha256": {
                        "type": "string",
                        "pattern": "^sha256:[0-9a-f]{64}$",
                    }
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "composed.json").write_text(
        json.dumps(
            {"digest": "not-a-sha256", "registry": {}, "variant": []},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/composed.schema.json",
        artifact_path="registry/report_intelligence/composed.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any(".digest: pattern mismatch" in failure for failure in record.failures)
    assert any(".registry: below minProperties" in failure for failure in record.failures)
    assert any(".variant: expected exactly one oneOf" in failure for failure in record.failures)


def test_prompt_ir_runtime_contract_schema_accepts_runtime_contract(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_ir"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/prompt_ir_runtime_contract_v1.schema.json",
        schema_dir / "prompt_ir_runtime_contract_v1.schema.json",
    )
    (artifact_dir / "macro.central_bank.json").write_text(
        json.dumps(
            {
                "schema_version": "prompt_ir_runtime_contract_v1",
                "agent_id": "macro.central_bank",
                "layer": "macro",
                "cohort_scope": "*",
                "prompt_version": "0.4.0-research-knobs",
                "role_contract": {
                    "responsibility": "Generate central-bank research output.",
                    "may_decide": ["stance"],
                    "must_not_decide": ["final_portfolio_sizing"],
                },
                "required_tools": [
                    {
                        "name": "get_pboc_ops",
                        "freshness_max_days": 1,
                        "required": True,
                        "metric_ids": ["pboc_ops_current"],
                        "metric_candidate_ids": [],
                        "analysis_recipe_ids": [],
                        "pit_required_for_backtest": True,
                        "fallback_confidence_cap": 0.6,
                        "lineage": {},
                    }
                ],
                "fallback_tools": [
                    {
                        "name": "get_pboc_ops:fallback",
                        "confidence_cap": 0.6,
                    }
                ],
                "research_rule_pack_refs": ["macro.central_bank.runtime.v1"],
                "confidence_policy_ref": "confidence_policy.v1",
                "rule_aggregation_policy_ref": "rule_aggregation_policy.v1",
                "output_schema_ref": "agent_output_schema.macro.central_bank.v1",
                "output_schema_fields": ["stance", "confidence"],
                "progress_event_schema_ref": "progress_event.v1",
                "handoff_schema_ref": "downstream_handoff.v1",
                "evolution_targets": {
                    "allowed_paths": ["/rule_packs/*/rules/*/learnable_parameters/*/value"],
                    "forbidden_paths": ["/output_schema_ref"],
                },
                "guardrails": ["research_reports_are_prior_not_signal"],
                "shared_contract_refs": ["research_knobs_v1"],
                "status": {
                    "promotion_state": "paper_trading",
                    "production_allowed": False,
                    "manual_gold_set_required": True,
                    "source_license_review_required": True,
                    "lockbox_required": True,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_ir_runtime_contract_v1.schema.json",
        artifact_path="registry/prompt_ir/macro.central_bank.json",
        artifact_kind="json",
    )

    assert record.accepted
    assert record.item_count == 1


def test_prompt_ir_runtime_contract_schema_requires_output_fields(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_ir"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/prompt_ir_runtime_contract_v1.schema.json",
        schema_dir / "prompt_ir_runtime_contract_v1.schema.json",
    )
    (artifact_dir / "macro.central_bank.json").write_text(
        json.dumps(
            {
                "schema_version": "prompt_ir_runtime_contract_v1",
                "agent_id": "macro.central_bank",
                "layer": "macro",
                "cohort_scope": "*",
                "prompt_version": "0.4.0-research-knobs",
                "role_contract": {
                    "responsibility": "Generate central-bank research output.",
                    "may_decide": ["stance"],
                    "must_not_decide": ["final_portfolio_sizing"],
                },
                "required_tools": [],
                "fallback_tools": [],
                "research_rule_pack_refs": ["macro.central_bank.runtime.v1"],
                "confidence_policy_ref": "confidence_policy.v1",
                "rule_aggregation_policy_ref": "rule_aggregation_policy.v1",
                "output_schema_ref": "agent_output_schema.macro.central_bank.v1",
                "progress_event_schema_ref": "progress_event.v1",
                "handoff_schema_ref": "downstream_handoff.v1",
                "evolution_targets": {
                    "allowed_paths": ["/rule_packs/*/rules/*/learnable_parameters/*/value"],
                    "forbidden_paths": ["/output_schema_ref"],
                },
                "guardrails": ["research_reports_are_prior_not_signal"],
                "shared_contract_refs": ["research_knobs_v1"],
                "status": {
                    "promotion_state": "paper_trading",
                    "production_allowed": False,
                    "manual_gold_set_required": True,
                    "source_license_review_required": True,
                    "lockbox_required": True,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_ir_runtime_contract_v1.schema.json",
        artifact_path="registry/prompt_ir/macro.central_bank.json",
        artifact_kind="json",
    )

    assert not record.accepted
    assert any(".output_schema_fields: required" in failure for failure in record.failures)


def test_prompt_governance_values_schema_accepts_physical_write_back_registry(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_governance/cohort_default"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/prompt_governance_values_v1.schema.json",
        schema_dir / "prompt_governance_values_v1.schema.json",
    )
    weight_path = (
        "/rule_packs/macro.central_bank.runtime.v1/rules/"
        "macro.central_bank.soft.001/learnable_parameters/pboc_ops_weight/value"
    )
    (artifact_dir / "central_bank.json").write_text(
        json.dumps(
            {
                "schema_version": "prompt_governance_values_v1",
                "agent": "macro.central_bank",
                "cohort": "cohort_default",
                "prompt_ir_scope": "*",
                "prompt_ir_hash": f"sha256:{'1' * 64}",
                "generator_version": "prompt_governance_projection_v1",
                "values_by_path": {weight_path: 1.0},
                "weight_groups": {
                    "evidence_weights": {
                        "normalization": "sum_to_one",
                        "members": [weight_path],
                    }
                },
                "last_mutation_id": None,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_governance_values_v1.schema.json",
        artifact_path="registry/prompt_governance/cohort_default/central_bank.json",
        artifact_kind="json",
    )

    assert record.accepted
    assert record.item_count == 1


def _runtime_agent_manifest_fixture() -> dict:
    return {
        "schema_version": "runtime_agent_manifest_v1",
        "runtime_agent_count": 1,
        "runtime_stage_count": 2,
        "default_cohort": "cohort_default",
        "research_knobs_cohort_enablement": [
            {
                "cohort": "cohort_default",
                "enabled_agent_stages": ["cio:cio_proposal"],
                "legacy_agent_stages": ["cio:cio_final"],
            }
        ],
        "canonical_l4_sequence": [
            "alpha_discovery",
            "cio_proposal",
            "cro_review",
            "execution_feasibility",
            "cio_final",
        ],
        "agents": [
            {
                "agent": "cio",
                "layer": "decision",
                "prompt_ir_agent_id": "decision.cio",
                "required_tools": ["get_rke_research_context"],
                "output_schema_fields": ["portfolio_actions", "confidence"],
                "stages": [
                    {
                        "stage": "cio_proposal",
                        "enablement": "declared",
                        "output_schema_ref": "decision.cio.proposal.v1",
                        "fallback_factory_id": "decision.cio.cio_proposal.fallback",
                        "fallback_factory_version": "1",
                        "required_source_ids": ["current_position_snapshot"],
                        "produced_source_ids": [
                            "candidate_target_state",
                            "position_review_state",
                        ],
                    },
                    {
                        "stage": "cio_final",
                        "enablement": "legacy",
                        "output_schema_ref": "decision.cio.final.v1",
                        "fallback_factory_id": "decision.cio.cio_final.fallback",
                        "fallback_factory_version": "1",
                        "required_source_ids": [
                            "candidate_target_state",
                            "cro_review_state",
                            "execution_feasibility_state",
                        ],
                        "produced_source_ids": [],
                    },
                ],
            }
        ],
    }


def _write_runtime_agent_manifest_fixture(tmp_path: Path, manifest: dict) -> SchemaValidationRecord:
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/runtime_agent_manifest_v1.schema.json",
        schema_dir / "runtime_agent_manifest_v1.schema.json",
    )
    (artifact_dir / "runtime_agent_manifest_v1.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/runtime_agent_manifest_v1.schema.json",
        artifact_path="registry/prompt_checks/runtime_agent_manifest_v1.json",
        artifact_kind="json",
    )


def test_runtime_agent_manifest_schema_accepts_stage_contract(tmp_path: Path):
    record = _write_runtime_agent_manifest_fixture(tmp_path, _runtime_agent_manifest_fixture())

    assert record.accepted
    assert record.item_count == 1


def test_runtime_agent_manifest_schema_requires_fallback_factory(tmp_path: Path):
    manifest = _runtime_agent_manifest_fixture()
    del manifest["agents"][0]["stages"][0]["fallback_factory_id"]

    record = _write_runtime_agent_manifest_fixture(tmp_path, manifest)

    assert not record.accepted
    assert any("fallback_factory_id: required" in failure for failure in record.failures)


def test_evidence_claim_graph_schema_accepts_contract_shape(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/evidence_claim_graph_v1.schema.json",
        schema_dir / "evidence_claim_graph_v1.schema.json",
    )
    snapshot_hash = f"sha256:{'1' * 64}"
    source_hash = f"sha256:{'2' * 64}"
    (artifact_dir / "evidence_claim_graph_v1.json").write_text(
        json.dumps(
            {
                "schema_version": "evidence_claim_graph_v1",
                "run_id": "run-1",
                "snapshot_hash": snapshot_hash,
                "evidence_ledger": [
                    {
                        "evidence_id": "ev-1",
                        "run_id": "run-1",
                        "snapshot_hash": snapshot_hash,
                        "source_kind": "tool",
                        "tool_or_source": "get_stock_data",
                        "metric": "close_return_20d",
                        "value": 0.08,
                        "unit": "ratio",
                        "as_of": "2026-07-10",
                        "lookback": "20d",
                        "freshness": "current",
                        "fallback": False,
                        "source_fingerprint": source_hash,
                        "direction": "positive",
                        "privacy_class": "public_structured",
                    }
                ],
                "claims": [
                    {
                        "claim_id": "claim-1",
                        "claim_type": "inference",
                        "statement": "Current price evidence supports a positive signal.",
                        "structured_conclusion": {"signal": "positive"},
                        "evidence_refs": ["ev-1"],
                        "research_rule_refs": ["sector.semiconductor.soft.001"],
                        "snapshot_hash": snapshot_hash,
                    }
                ],
                "recommendation_claim_refs": [
                    {
                        "output_id": "action-1",
                        "output_type": "portfolio_action",
                        "claim_refs": ["claim-1"],
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/evidence_claim_graph_v1.schema.json",
        artifact_path="registry/prompt_checks/evidence_claim_graph_v1.json",
        artifact_kind="json",
    )

    assert record.accepted
    assert record.item_count == 1


def test_prompt_transaction_and_release_schemas_accept_staged_contracts(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    for schema_name in (
        "prompt_mutation_transaction_v1.schema.json",
        "prompt_mutation_recovery_v1.schema.json",
        "active_prompt_release_manifest_v1.schema.json",
    ):
        shutil.copyfile(f"schemas/{schema_name}", schema_dir / schema_name)
    digest = f"sha256:{'1' * 64}"
    transaction = {
        "schema_version": "prompt_mutation_transaction_v1",
        "mutation_id": "mutation-1",
        "transaction_id": "transaction-1",
        "experiment_id": "experiment-1",
        "state": "created",
        "recovery_state": "not_needed",
        "base_release_id": "release-0",
        "catalog_hash": digest,
        "schema_hash": digest,
        "evaluation_contract_hash": digest,
        "recovery_descriptor_hash": digest,
        "target_paths": ["/rule_packs/test/value"],
        "components": [
            {
                "repo_id": "MOSAIC-Prompts",
                "base_commit": "1234567",
                "new_commit": None,
                "candidate_ref": "refs/mosaic-candidates/mutation-1",
                "prepare_status": "pending",
                "files": [
                    {
                        "path": "registry/domain_knobs/cohort_default/cio.json",
                        "old_hash": digest,
                        "new_hash": digest,
                        "staging_path_hash": digest,
                    }
                ],
            }
        ],
        "metadata_log": {
            "path": "mutation_patches/knob_mutations.jsonl",
            "entry_hash": digest,
            "appended": False,
        },
        "created_at": "2026-07-10T00:00:00Z",
        "prepared_at": None,
        "committed_at": None,
        "aborted_at": None,
        "recovery_decision": None,
    }
    recovery = {
        "schema_version": "prompt_mutation_recovery_v1",
        "transaction_id": "transaction-1",
        "mutation_id": "mutation-1",
        "version_id": 1,
        "agent": "central_bank",
        "cohort": "cohort_default",
        "components": [
            {
                "repo_id": "MOSAIC-Prompts",
                "target": "private_git",
                "branch": "cohort/cohort_default/auto/central_bank/2026-07-10",
            },
            {
                "repo_id": "MOSAIC-RKE",
                "target": "project_git",
                "branch": "cohort/cohort_default/auto/central_bank/2026-07-10",
            },
        ],
        "summary": "test mutation",
        "prompt_sha256": "1" * 64,
        "code_commit_hash": "c" * 40,
        "metadata_log_path": "mutation_patches/knob_mutations.jsonl",
        "mutation_metadata": {
            "schema_version": "knob_mutation_metadata_v1",
            "mutation_id": "mutation-1",
            "transaction_id": "transaction-1",
            "experiment_id": "experiment-1",
        },
    }
    release = {
        "schema_version": "active_prompt_release_manifest_v1",
        "release_id": "release-1",
        "base_release_id": "release-0",
        "lifecycle_state": "staged",
        "prompt_commit": "1234567",
        "code_commit": "7654321",
        "prompt_hash": digest,
        "prompt_pairs": [
            {
                "agent": "central_bank",
                "layer": "macro",
                "cohort": "cohort_default",
                "stages": ["agent_run"],
                "zh": {
                    "path": "prompts/mosaic/cohort_default/macro/central_bank.zh.md",
                    "sha256": digest,
                },
                "en": {
                    "path": "prompts/mosaic/cohort_default/macro/central_bank.en.md",
                    "sha256": digest,
                },
                "pair_hash": digest,
            }
        ],
        "stage_snapshot_hashes": {"central_bank:agent_run": digest},
        "catalog_hash": digest,
        "schema_hash": digest,
        "evaluation_contract_hash": digest,
        "keep_decision_hash": digest,
        "keep_decision_state": "kept",
        "release_evidence": {
            "version_id": 1,
            "mutation_id": "mutation-1",
            "experiment_id": "experiment-1",
            "mutated_agent": "central_bank",
            "evaluation_result_hash": digest,
            "transaction_manifest_hash": digest,
            "prompt_pair_sha256": "1" * 64,
        },
        "activation_scope": {
            "cohort": "cohort_default",
            "account_mode": "paper",
            "traffic_percent": 0,
        },
        "approval_policy_id": "decision_release_manual_v1",
        "approved_by": None,
        "canary_started_at": None,
        "canary_ended_at": None,
        "runtime_slo_summary": None,
        "runtime_slo_evidence": None,
        "rollback_triggers": ["schema_failure_rate_gt_0"],
        "previous_approved_release_id": "release-0",
        "bundled_fallback": None,
        "created_at": "2026-07-10T00:00:00Z",
        "activated_at": None,
        "rolled_back_at": None,
    }
    artifacts = {
        "prompt_mutation_transaction_v1.json": transaction,
        "prompt_mutation_recovery_v1.json": recovery,
        "active_prompt_release_manifest_v1.json": release,
    }
    for filename, payload in artifacts.items():
        (artifact_dir / filename).write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )

    transaction_record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_mutation_transaction_v1.schema.json",
        artifact_path="registry/prompt_checks/prompt_mutation_transaction_v1.json",
        artifact_kind="json",
    )
    recovery_record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_mutation_recovery_v1.schema.json",
        artifact_path="registry/prompt_checks/prompt_mutation_recovery_v1.json",
        artifact_kind="json",
    )
    release_record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/active_prompt_release_manifest_v1.schema.json",
        artifact_path="registry/prompt_checks/active_prompt_release_manifest_v1.json",
        artifact_kind="json",
    )

    assert transaction_record.accepted
    assert recovery_record.accepted
    assert release_record.accepted


def test_prompt_token_budget_manifest_schema_accepts_machine_budget(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/prompt_token_budget_manifest_v1.schema.json",
        schema_dir / "prompt_token_budget_manifest_v1.schema.json",
    )
    digest = f"sha256:{'1' * 64}"
    artifact = {
        "schema_version": "prompt_token_budget_manifest_v1",
        "generator_id": "prompt_token_budget",
        "generator_version": "1",
        "generated_at": "2026-07-10T00:00:00Z",
        "cohort": "cohort_default",
        "tokenizer": {
            "id": "cl100k_base",
            "package": "js-tiktoken",
            "version": "1.0.21",
        },
        "context_window_tokens": 131072,
        "visible_contract_cap_tokens": 8192,
        "system_prompt_cap_tokens": 32768,
        "min_reserved_context_ratio": 0.5,
        "max_baseline_growth_ratio": 1.25,
        "runtime_manifest_hash": digest,
        "source_commits": {"private": "a" * 40, "bundled": "b" * 40},
        "baseline_manifest_hash": None,
        "rows": [
            {
                "source": "private",
                "agent": "central_bank",
                "stage": "agent_run",
                "language": "zh",
                "source_path": "cohort_default/macro/central_bank.zh.md",
                "source_sha256": digest,
                "source_bytes": 1000,
                "parsed_projection_bytes": 500,
                "visible_contract_tokens": 100,
                "final_system_prompt_tokens": 200,
                "reserved_context_tokens": 130872,
                "baseline_final_system_prompt_tokens": None,
                "baseline_growth_ratio": None,
                "checks": {
                    "visible_contract_within_cap": True,
                    "system_prompt_within_cap": True,
                    "reserved_context_within_floor": True,
                    "baseline_growth_within_limit": True,
                },
                "passed": True,
            }
        ],
        "summary": {
            "expected_row_count": 104,
            "row_count": 1,
            "passed_row_count": 1,
            "failed_row_count": 0,
            "semantic_parity_passed": True,
            "ready": False,
        },
        "manifest_hash": digest,
    }
    (artifact_dir / "prompt_token_budget_manifest_v1.json").write_text(
        json.dumps(artifact, sort_keys=True) + "\n", encoding="utf-8"
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_token_budget_manifest_v1.schema.json",
        artifact_path="registry/prompt_checks/prompt_token_budget_manifest_v1.json",
        artifact_kind="json",
    )

    assert record.accepted


def _domain_knob_catalog_fixture() -> dict:
    dependency_id = "sector.semiconductor.inventory_cycle_quarters.primary"
    return {
        "schema_version": "domain_knob_catalog_v1",
        "catalog_version": "domain_knob_catalog_v1",
        "runtime_agent_count": 1,
        "runtime_sources": {},
        "evaluation_metrics": {
            "sector_rank_correlation_20d": {
                "id": "sector_rank_correlation_20d",
                "unit": "ratio",
                "value_convention": "signed_return",
                "direction": "higher_is_better",
                "aggregation": "mean",
                "window": "20d",
                "baseline": "previous_knob_snapshot",
                "calculator_id": "pit.rank_correlation",
                "calculator_version": "1",
                "valid_range": {"minimum": -1, "maximum": 1},
                "null_policy": "exclude_sample",
                "non_finite_policy": "reject_evaluation",
                "normalization_version": "1",
                "uncertainty_method": "fisher_z",
                "overlapping_sample_policy": "inverse_overlap_weight",
                "min_sample_size": 30,
                "pit_required": True,
                "exclusion_rules": ["missing_required_evidence_dependency"],
            }
        },
        "evaluation_calculators": {
            "pit.rank_correlation": {
                "id": "pit.rank_correlation",
                "version": "1",
                "implementation_language": "python",
                "implementation_ref": (
                    "mosaic.autoresearch.domain_metrics:calculate_rank_correlation"
                ),
                "input_schema_ref": "autoresearch.domain_metric_sample.v1",
                "output_schema_ref": "autoresearch.domain_metric_result.v1",
                "deterministic": True,
                "pit_enforced": True,
                "supported_value_conventions": ["score"],
            }
        },
        "agents": [
            {
                "layer": "sector",
                "agent": "semiconductor",
                "prompt_ir_agent": "sector.semiconductor",
                "min_mutable_domain_knobs": 1,
                "card_count": 1,
                "cards": [
                    {
                        "id": "inventory_cycle_quarters",
                        "owner_agent": "sector.semiconductor",
                        "consumer_agents": ["sector.semiconductor"],
                        "owner_stage": "agent_run",
                        "consumer_stages": ["agent_run"],
                        "projection_bucket": "lookbacks",
                        "path": (
                            "/rule_packs/sector.semiconductor.runtime.v1/rules/"
                            "sector.semiconductor.soft.001/learnable_parameters/"
                            "inventory_cycle_quarters/value"
                        ),
                        "type": "integer",
                        "default": 4,
                        "min": 2,
                        "max": 8,
                        "step": 1,
                        "coverage_level": "direct_tool",
                        "activation_state": "active",
                        "runtime_input_sources": [],
                        "runtime_input_source_policies": {},
                        "evidence_dependencies": [
                            {
                                "dependency_id": dependency_id,
                                "evidence_key": "balance_sheet",
                                "tool": "get_balance_sheet",
                                "metric_ids": ["inventory_to_revenue"],
                                "freshness": "latest_reported_quarter_pit",
                                "required_for_prediction": True,
                                "dependency_type": "direct_tool",
                                "scope_resolution": "pre_run",
                                "scope_schema": {"ticker": "required"},
                                "min_scope_coverage": 0.8,
                            }
                        ],
                        "evidence_dependency_policies": {
                            dependency_id: {
                                "missing": "exclude_sample_and_cap_if_required",
                                "stale": "exclude_sample_and_cap_if_required",
                                "fallback": "exclude_sample_and_cap_if_required",
                                "tool_failed": "exclude_sample_and_cap_if_required",
                                "partial_loaded": "exclude_sample_only",
                                "loaded": "allow",
                            }
                        },
                        "learning_objective": "calibrate inventory cycle lookback",
                        "prediction_target": "sector.semiconductor.inventory_cycle_quarters.20d",
                        "evaluation_metric": "sector_rank_correlation_20d",
                        "secondary_metrics": [],
                        "horizon": "20d",
                        "rollback_condition": {
                            "metric": "sector_rank_correlation_20d",
                            "worse_by": 0.02,
                            "unit": "ratio",
                        },
                        "enforcement": "advisory",
                        "category": "domain",
                        "cross_field_group": None,
                        "weight_group": None,
                        "atomic_mutation_group": None,
                        "normalization": "none",
                    }
                ],
            }
        ],
    }


def _write_domain_knob_catalog_fixture(tmp_path: Path, catalog: dict) -> SchemaValidationRecord:
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/domain_knob_catalog_v1.schema.json",
        schema_dir / "domain_knob_catalog_v1.schema.json",
    )
    (artifact_dir / "domain_knob_catalog_v1.json").write_text(
        json.dumps(catalog, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/domain_knob_catalog_v1.schema.json",
        artifact_path="registry/prompt_checks/domain_knob_catalog_v1.json",
        artifact_kind="json",
    )


def test_domain_knob_catalog_schema_accepts_valid_catalog(tmp_path: Path):
    record = _write_domain_knob_catalog_fixture(tmp_path, _domain_knob_catalog_fixture())

    assert record.accepted
    assert record.item_count == 1


def test_domain_knob_catalog_schema_requires_in_run_scope_fields(tmp_path: Path):
    catalog = _domain_knob_catalog_fixture()
    dependency = catalog["agents"][0]["cards"][0]["evidence_dependencies"][0]
    dependency["scope_resolution"] = "in_run_tool_derived"

    record = _write_domain_knob_catalog_fixture(tmp_path, catalog)

    assert not record.accepted
    assert any("scope_source_tool: required" in failure for failure in record.failures)
    assert any("empty_scope_behavior: required" in failure for failure in record.failures)


def test_domain_knob_catalog_schema_requires_code_enforcement_fields(tmp_path: Path):
    catalog = _domain_knob_catalog_fixture()
    card = catalog["agents"][0]["cards"][0]
    card["enforcement"] = "code"

    record = _write_domain_knob_catalog_fixture(tmp_path, catalog)

    assert not record.accepted
    assert any("runtime_validator: required" in failure for failure in record.failures)
    assert any("audit_field: required" in failure for failure in record.failures)


def test_domain_knob_catalog_schema_requires_numeric_bounds(tmp_path: Path):
    catalog = _domain_knob_catalog_fixture()
    del catalog["agents"][0]["cards"][0]["step"]

    record = _write_domain_knob_catalog_fixture(tmp_path, catalog)

    assert not record.accepted
    assert any(".step: required" in failure for failure in record.failures)


def test_domain_knob_catalog_schema_requires_secondary_metrics(tmp_path: Path):
    catalog = _domain_knob_catalog_fixture()
    del catalog["agents"][0]["cards"][0]["secondary_metrics"]

    record = _write_domain_knob_catalog_fixture(tmp_path, catalog)

    assert not record.accepted
    assert any(".secondary_metrics: required" in failure for failure in record.failures)


def _write_domain_knob_evaluation_contract_fixture(
    tmp_path: Path, contract: dict
) -> SchemaValidationRecord:
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        "schemas/domain_knob_evaluation_contract_v1.schema.json",
        schema_dir / "domain_knob_evaluation_contract_v1.schema.json",
    )
    (artifact_dir / "domain_knob_evaluation_contract_v1.json").write_text(
        json.dumps(contract, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/domain_knob_evaluation_contract_v1.schema.json",
        artifact_path="registry/prompt_checks/domain_knob_evaluation_contract_v1.json",
        artifact_kind="json",
    )


def test_domain_knob_evaluation_contract_schema_accepts_generated_contract(tmp_path: Path):
    contract = json.loads(
        Path("registry/prompt_checks/domain_knob_evaluation_contract_v1.json").read_text(
            encoding="utf-8"
        )
    )
    expected_schema_hash = "sha256:" + sha256(
        Path("schemas/domain_knob_evaluation_contract_v1.schema.json").read_bytes()
    ).hexdigest()

    record = _write_domain_knob_evaluation_contract_fixture(tmp_path, contract)

    assert record.accepted
    assert record.item_count == 1
    assert contract["schema_hash"] == expected_schema_hash


def test_domain_knob_evaluation_contract_schema_requires_contract_hash(tmp_path: Path):
    contract = json.loads(
        Path("registry/prompt_checks/domain_knob_evaluation_contract_v1.json").read_text(
            encoding="utf-8"
        )
    )
    del contract["contract_hash"]

    record = _write_domain_knob_evaluation_contract_fixture(tmp_path, contract)

    assert not record.accepted
    assert any(".contract_hash: required" in failure for failure in record.failures)


def test_domain_knob_evaluation_contract_schema_enforces_refs_and_min_properties(
    tmp_path: Path,
):
    contract = json.loads(
        Path("registry/prompt_checks/domain_knob_evaluation_contract_v1.json").read_text(
            encoding="utf-8"
        )
    )
    contract["catalog_hash"] = "not-a-sha256"
    contract["evaluation_metrics"] = {}

    record = _write_domain_knob_evaluation_contract_fixture(tmp_path, contract)

    assert not record.accepted
    assert any(".catalog_hash: pattern mismatch" in failure for failure in record.failures)
    assert any(".evaluation_metrics: below minProperties" in failure for failure in record.failures)


def test_domain_knob_evaluation_contract_schema_requires_binding_activation_state(
    tmp_path: Path,
):
    contract = json.loads(
        Path("registry/prompt_checks/domain_knob_evaluation_contract_v1.json").read_text(
            encoding="utf-8"
        )
    )
    del contract["card_bindings"][0]["activation_state"]

    record = _write_domain_knob_evaluation_contract_fixture(tmp_path, contract)

    assert not record.accepted
    assert any(".activation_state: required" in failure for failure in record.failures)


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


def test_schema_status_cli_writes_report(tmp_path: Path, capsys):
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
        ignore=_ignore_private_registry_inputs,
        dirs_exist_ok=True,
    )

    code = main(("schema-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert all(record["accepted"] is True for record in output["records"])
    assert (registry_dir / "schemas/rke_schema_validation_report.json").exists()


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
        ignore=_ignore_private_registry_inputs,
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

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert output["record_count"] > output["reported_record_count"]
    assert output["records"] == []
    assert output["next_actions"] == []
    assert not (registry_dir / "schemas/rke_schema_validation_report.json").exists()


def test_schema_status_next_actions_reports_gold_quality_gaps(
    tmp_path: Path,
    monkeypatch,
):
    summary_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "passed": False,
                "review_complete": True,
                "reviewed_claims": 100,
                "pending_claims": 0,
                "total_documents": 40,
                "metrics": {
                    "claim_precision": 0.90,
                    "source_span_support_precision": 0.95,
                    "direction_accuracy": 0.70,
                    "target_accuracy": 0.90,
                    "horizon_accuracy": 0.90,
                    "variable_mapping_accuracy": 0.60,
                    "unsupported_field_false_grounding_rate": 0.10,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    records = [
        SchemaValidationRecord(
            schema_path="schemas/report_intelligence_gold_review_gate_rules",
            artifact_path="registry/gold_sets/tushare_research_reports.review_summary.json",
            item_count=1,
            accepted=False,
            failures=("direction_accuracy below threshold",),
        )
    ]
    monkeypatch.setattr(cli_module, "build_manual_review_progress", lambda root: object())
    monkeypatch.setattr(
        cli_module,
        "build_manual_review_action_queue",
        lambda report, *, review_kinds: {
            "actions": [
                {
                    "commands": {
                        "assist": (
                            f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke "
                            "write-gold-review-assist --root . --review-input "
                            "registry/review_batches/gold_set_reviewed.jsonl"
                        ),
                        "evidence": (
                            f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke "
                            "write-gold-review-evidence --root . --limit 12 "
                            "--offset 0 --review-input "
                            "registry/review_batches/gold_set_reviewed.jsonl"
                        ),
                        "dry_run": (
                            f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke "
                            "apply-gold-review --root . --input "
                            "registry/review_batches/gold_set_reviewed.jsonl --dry-run"
                        ),
                    },
                    "batch_overview": {
                        "current_batch_path": (
                            "registry/review_batches/gold_set_reviewed.jsonl"
                        ),
                        "current_batch_rows": 12,
                        "current_batch_evidence_aligned": True,
                        "remaining_rows_after_current_batch": 3,
                    },
                    "after_dry_run_accepts": {
                        "apply_current_batch": (
                            "apply-gold-review --root . --input "
                            "registry/review_batches/gold_set_reviewed.jsonl"
                        ),
                        "rerun_review_progress": (
                            "review-progress --root . --actions-only --no-write "
                            "--review-kind gold_set"
                        ),
                    },
                    "next_manual_action": (
                        "fill_current_batch_review_fields_then_dry_run"
                    ),
                    "action_state": "needs_human_review_fields",
                    "can_run_now": True,
                    "blocks_promotion": True,
                    "post_current_batch_action": (
                        "apply_current_batch_then_rerun_review_progress"
                    ),
                    "manual_input_path": (
                        "registry/review_batches/gold_set_reviewed.jsonl"
                    ),
                    "promotion_input_path": (
                        "registry/review_batches/gold_set_full_reviewed.jsonl"
                    ),
                    "current_batch_pending_rows": 12,
                    "evidence_aligned": True,
                }
            ]
        },
    )

    actions = {
        action["action_id"]: action
        for action in _schema_status_next_actions(records, root=tmp_path)
    }
    gold_action = actions["complete_manual_forecast_gold_review"]

    assert gold_action["commands"]["inspect"].startswith(RKE_OPERATOR_TMP_ENV_PREFIX)
    assert "--limit 12 --offset 0" in gold_action["commands"]["write_evidence"]
    assert gold_action["batch_overview"]["current_batch_rows"] == 12
    assert gold_action["batch_overview"]["remaining_rows_after_current_batch"] == 3
    assert gold_action["action_state"] == "needs_human_review_fields"
    assert gold_action["can_run_now"] is True
    assert gold_action["post_current_batch_action"] == (
        "apply_current_batch_then_rerun_review_progress"
    )
    assert gold_action["manual_input_path"] == (
        "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert "apply-gold-review" in gold_action["after_dry_run_accepts"][
        "apply_current_batch"
    ]
    assert gold_action["review_aids"]["fill_import_path"] == (
        "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert gold_action["quality_gap_targets"]["sample_size_documents"][
        "minimum_additional_count"
    ] == 10
    assert gold_action["quality_gap_targets"]["metrics"]["direction_accuracy"][
        "minimum_additional_pass_count_if_denominator_unchanged"
    ] == 15


def test_schema_status_cli_reports_malformed_artifact(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
):
    record = SchemaValidationRecord(
        schema_path="schemas/source_metadata.schema.json",
        artifact_path="registry/sources/central_bank_sources.jsonl",
        item_count=0,
        accepted=False,
        failures=("line 1: invalid JSON",),
    )
    monkeypatch.setattr(
        cli_module,
        "build_schema_validation_report",
        lambda root: SchemaValidationReport(
            report_id="schema-validation-test",
            records=(record,),
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "_schema_status_next_actions",
        lambda records, *, root: [],
    )

    code = main(("schema-status", "--root", str(tmp_path), "--no-write"))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert output["failure_count"] == 1
    assert output["records"][0]["failures"] == ["line 1: invalid JSON"]
