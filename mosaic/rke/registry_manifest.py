"""Registry manifest and required-artifact checks for RKE."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Sequence


PRIVATE_LOCAL_REGISTRY_FILES = frozenset(
    {
        "registry/compliance/tushare_license_review_import_report.json",
        "registry/compliance/tushare_license_review_packet.json",
        "registry/compliance/tushare_license_review_packet.md",
        "registry/compliance/tushare_license_review_summary.json",
        "registry/compliance/tushare_license_review_template.jsonl",
        "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl",
        "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json",
        "registry/gold_sets/tushare_research_reports.review_import_report.json",
        "registry/gold_sets/tushare_research_reports.review_packet.json",
        "registry/gold_sets/tushare_research_reports.review_packet.md",
        "registry/gold_sets/tushare_research_reports.review_summary.json",
        "registry/gold_sets/tushare_research_reports.review_template.jsonl",
        "registry/review_batches/gold_set_full_import_template.jsonl",
        "registry/review_batches/gold_set_next_import_template.jsonl",
        "registry/review_batches/gold_set_review_assist.jsonl",
        "registry/review_batches/gold_set_review_assist.md",
        "registry/review_batches/gold_set_review_workbook.md",
        "registry/review_batches/source_license_next_import_template.jsonl",
        "registry/review_batches/source_license_review_workbook.md",
        "registry/report_intelligence/analytical_footprint_review_template.jsonl",
        "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/processing_status.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
        "registry/source_checks/source_registry_validation_report.json",
        "registry/sources/tushare_research_reports.gold_candidates.jsonl",
        "registry/sources/tushare_research_reports.jsonl",
        "registry/sources/tushare_research_reports.manifest.json",
    }
)
PRIVATE_LOCAL_REGISTRY_PREFIXES = (
    "registry/report_intelligence/markdown/",
    "registry/report_intelligence/mineru/",
    "registry/report_intelligence/pdfs/",
)


REQUIRED_REGISTRY_FILES = (
    "registry/audits/central_bank_mvp_audit_trace.json",
    "registry/audits/central_bank_mvp_audit_view.json",
    "registry/audits/central_bank_mvp_audit_view.md",
    "registry/audits/rke_completion_audit.json",
    "registry/audits/rke_master_plan_coverage_report.json",
    "registry/claim_checks/claim_grounding_validation_report.json",
    "registry/claim_checks/claim_variable_validation_report.json",
    "registry/claims/central_bank_claims.jsonl",
    "registry/claims/semiconductor_claims.jsonl",
    "registry/compliance/source_text_redaction_report.json",
    "registry/dashboards/rke_dashboard.json",
    "registry/dashboards/rke_dashboard.md",
    "registry/docs/rke_policy_doc_validation_report.json",
    "registry/data_availability/central_bank_data_availability.json",
    "registry/data_availability/macro_expansion_data_availability.json",
    "registry/data_availability/semiconductor_sandbox_data_availability.json",
    "registry/disagreement/semiconductor_policy_substitution.json",
    "registry/expansion/macro_phase6_expansion.json",
    "registry/evaluation/baselines/central_bank_baseline_versions.json",
    "registry/evaluation/cost_model/cost_model_v1.json",
    "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json",
    "registry/evaluation/lockbox/lockbox_policy.json",
    "registry/evaluation/overlap_correction/effective_n_overlap_policy.json",
    "registry/evaluation/pre_registration/central_bank_liquidity_preregistration.json",
    "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json",
    "registry/experiments/central_bank_validation_experiment_v2.json",
    "registry/experiment_checks/experiment_validation_report.json",
    "registry/handoffs/rke_operator_handoff.json",
    "registry/handoffs/rke_operator_handoff.md",
    "registry/handoffs/rke_operator_readiness_report.json",
    "registry/hypotheses/central_bank_hypotheses.jsonl",
    "registry/hypotheses/semiconductor_hypotheses.jsonl",
    "registry/integration/phase7_layer_integration_contracts.json",
    "registry/lockbox/central_bank_lockbox_review.json",
    "registry/lockbox/central_bank_lockbox_review_import_report.json",
    "registry/monitoring/central_bank_monitoring_diagnostics.json",
    "registry/monitoring/central_bank_paper_trading_report.json",
    "registry/monitoring/central_bank_rollback_readiness_report.json",
    "registry/mutation_patches/central_bank_parameter_update.json",
    "registry/parameter_priors/central_bank_parameter_priors.jsonl",
    "registry/patches/central_bank_paper_trading_patch.json",
    "registry/prompt_checks/prompt_asset_validation_report.json",
    "registry/prompt_ir/macro.central_bank.json",
    "registry/promotion/rke_promotion_dry_run_report.json",
    "registry/promotion/rke_production_promotion_gate.json",
    "registry/rendered_prompts/macro.central_bank.rke.json",
    "registry/rendered_prompts/macro.central_bank.rke.md",
    "registry/report_intelligence/analysis_recipes.jsonl",
    "registry/report_intelligence/analytical_footprint_error_taxonomy.json",
    "registry/report_intelligence/analytical_footprint_review_summary.json",
    "registry/report_intelligence/data_acquisition_proposals.jsonl",
    "registry/report_intelligence/extraction_provenance_audit.json",
    "registry/report_intelligence/extraction_report.json",
    "registry/report_intelligence/feature_flags.json",
    "registry/report_intelligence/industry_etf_proxy_map.jsonl",
    "registry/report_intelligence/industry_etf_proxy_pit_availability.json",
    "registry/report_intelligence/markdown_coverage_summary.json",
    "registry/report_intelligence/method_patterns.jsonl",
    "registry/report_intelligence/method_performance_profiles.jsonl",
    "registry/report_intelligence/metric_candidates.jsonl",
    "registry/report_intelligence/monitoring_report.json",
    "registry/report_intelligence/pit_leakage_audit.json",
    "registry/report_intelligence/patch_v1_5_coverage_report.json",
    "registry/report_intelligence/outcome_labeling_readiness.json",
    "registry/report_intelligence/recipe_paper_trading_runs.jsonl",
    "registry/report_intelligence/recipe_paper_trading_summary.json",
    "registry/report_intelligence/confidence_impact_observations.jsonl",
    "registry/report_intelligence/confidence_impact_monitor.json",
    "registry/report_intelligence/monitor_refresh_history.jsonl",
    "registry/report_intelligence/audit_refresh_history.jsonl",
    "registry/report_intelligence/gap_distribution_history.jsonl",
    "registry/report_intelligence/prompt_mutation_candidates.jsonl",
    "registry/report_intelligence/report_forecast_ledger.jsonl",
    "registry/report_intelligence/source_performance_profiles.jsonl",
    "registry/report_intelligence/runtime_safety_audit.json",
    "registry/report_intelligence/runtime_tool_gap_observations.jsonl",
    "registry/report_intelligence/statistical_robustness_audit.json",
    "registry/report_intelligence/tool_feasibility_audit.json",
    "registry/report_intelligence/recipe_validation_audit.json",
    "registry/report_intelligence/tool_coverage_matches.jsonl",
    "registry/report_intelligence/tool_design_proposals.jsonl",
    "registry/report_intelligence/tool_gaps.jsonl",
    "registry/report_intelligence/viewpoint_performance_profiles.jsonl",
    "registry/rule_checks/rule_pack_validation_report.json",
    "registry/rule_packs/macro.central_bank.liquidity.v1.json",
    "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json",
    "registry/runtime_inputs/macro.central_bank.20260605.json",
    "registry/runtime_outputs/macro.central_bank.20260605.json",
    "registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
    "registry/review_batches/manual_review_batch_status.json",
    "registry/review_batches/manual_review_bundle_manifest.json",
    "registry/review_batches/manual_review_progress_report.json",
    "registry/review_batches/manual_review_runbook.md",
    "registry/review_batches/lockbox_review_next_import_template.json",
    "registry/review_batches/source_license_policy_import_report.json",
    "registry/review_batches/source_license_policy_template.json",
    "registry/schemas/rke_schema_validation_report.json",
    "registry/sources/central_bank_sources.jsonl",
    "registry/sources/semiconductor_demo_sources.jsonl",
    "registry/validation_hardening/central_bank_hardening_report.json",
    "registry/vocabularies/claim_variable_vocabulary.json",
)
EMPTY_REQUIRED_REGISTRY_FILES = frozenset()


@dataclass(frozen=True)
class RegistryArtifact:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class RegistryManifest:
    manifest_id: str
    artifact_count: int
    artifacts: Sequence[RegistryArtifact]
    missing_required: Sequence[str]
    empty_required: Sequence[str]
    invalid_required: Sequence[str]

    @property
    def valid(self) -> bool:
        return (
            not self.missing_required
            and not self.empty_required
            and not self.invalid_required
        )


def file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def is_public_registry_artifact(relative: str) -> bool:
    if relative in PRIVATE_LOCAL_REGISTRY_FILES:
        return False
    return not any(relative.startswith(prefix) for prefix in PRIVATE_LOCAL_REGISTRY_PREFIXES)


def validate_required_registry(
    root: str | Path = ".",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    root_path = Path(root)
    missing: list[str] = []
    empty: list[str] = []
    for relative in REQUIRED_REGISTRY_FILES:
        path = root_path / relative
        if not path.exists():
            missing.append(relative)
        elif (
            path.stat().st_size <= 0
            and relative not in EMPTY_REQUIRED_REGISTRY_FILES
        ):
            empty.append(relative)
    return tuple(missing), tuple(empty)


def validate_required_registry_content(root: str | Path = ".") -> tuple[str, ...]:
    root_path = Path(root)
    invalid: list[str] = []
    for relative in REQUIRED_REGISTRY_FILES:
        path = root_path / relative
        if not path.exists() or path.stat().st_size <= 0:
            continue
        if relative.endswith(".json"):
            _validate_json_object(path, relative, invalid)
        elif relative.endswith(".jsonl"):
            _validate_jsonl_objects(path, relative, invalid)
    return tuple(invalid)


def _validate_json_object(path: Path, relative: str, invalid: list[str]) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        invalid.append(f"{relative} must contain valid JSON: {exc.msg}")
        return
    if not isinstance(payload, dict):
        invalid.append(f"{relative} must be object")


def _validate_jsonl_objects(path: Path, relative: str, invalid: list[str]) -> None:
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                invalid.append(
                    f"{relative} row {index} must contain valid JSON: {exc.msg}"
                )
                return
            if not isinstance(payload, dict):
                invalid.append(f"{relative} row {index} must be object")
                return


def build_registry_manifest(root: str | Path = ".") -> RegistryManifest:
    root_path = Path(root)
    artifacts: list[RegistryArtifact] = []
    for path in sorted((root_path / "registry").rglob("*")):
        if not path.is_file():
            continue
        if path.name == "rke_registry_manifest.json":
            continue
        relative = path.relative_to(root_path).as_posix()
        if not is_public_registry_artifact(relative):
            continue
        artifacts.append(
            RegistryArtifact(
                path=relative,
                bytes=path.stat().st_size,
                sha256=file_sha256(path),
            )
        )
    missing, empty = validate_required_registry(root_path)
    invalid = validate_required_registry_content(root_path)
    return RegistryManifest(
        manifest_id="RKE-REGISTRY-MANIFEST-20260606",
        artifact_count=len(artifacts),
        artifacts=tuple(artifacts),
        missing_required=missing,
        empty_required=empty,
        invalid_required=invalid,
    )


def write_registry_manifest(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    manifest = build_registry_manifest(root_path)
    output_path = root_path / "registry/manifests/rke_registry_manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "artifact_count": manifest.artifact_count,
        "valid": manifest.valid,
    }
