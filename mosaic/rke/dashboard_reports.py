"""Dashboard-ready report generation for RKE monitoring and audits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def _path_label(root_path: Path, path: Path) -> str:
    try:
        return path.relative_to(root_path).as_posix()
    except ValueError:
        return path.as_posix()


def _read_mapping_json(
    path: Path,
    root_path: Path,
    *,
    required: bool = False,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not path.exists():
        return {}, (f"{_path_label(root_path, path)} missing",) if required else ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, (
            f"{_path_label(root_path, path)} must contain valid JSON: {exc.msg}",
        )
    if not isinstance(payload, Mapping):
        return {}, (f"{_path_label(root_path, path)} must be object",)
    return dict(payload), ()


def _mapping_field(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    label: str,
    artifact_errors: list[str],
) -> Mapping[str, Any]:
    value = payload.get(field_name)
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    artifact_errors.append(f"{label}.{field_name} must be object")
    return {}


def _sequence_field(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    label: str,
    artifact_errors: list[str],
) -> tuple[Any, ...]:
    value = payload.get(field_name)
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    artifact_errors.append(f"{label}.{field_name} must be array")
    return ()


def _mapping_sequence_field(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    label: str,
    artifact_errors: list[str],
) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for index, item in enumerate(
        _sequence_field(
            payload, field_name, label=label, artifact_errors=artifact_errors
        ),
        1,
    ):
        if isinstance(item, Mapping):
            rows.append(item)
        else:
            artifact_errors.append(f"{label}.{field_name}[{index}] must be object")
    return tuple(rows)


def _blocked_section_ids(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(record.get("section_id"))
        for record in records
        if record.get("status") == "blocked"
    )


def _first_mapping_item_field(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    label: str,
    artifact_errors: list[str],
) -> Mapping[str, Any]:
    values = _sequence_field(
        payload, field_name, label=label, artifact_errors=artifact_errors
    )
    if not values:
        return {}
    first = values[0]
    if isinstance(first, Mapping):
        return first
    artifact_errors.append(f"{label}.{field_name}[1] must be object")
    return {}


def build_dashboard_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    artifact_errors: list[str] = []

    def load_mapping(relative_path: str, *, required: bool = False) -> dict[str, Any]:
        payload, errors = _read_mapping_json(
            root_path / relative_path, root_path, required=required
        )
        artifact_errors.extend(errors)
        return payload

    completion = load_mapping(
        "registry/audits/rke_completion_audit.json", required=True
    )
    coverage_path = root_path / "registry/audits/rke_master_plan_coverage_report.json"
    coverage = (
        load_mapping("registry/audits/rke_master_plan_coverage_report.json")
        if coverage_path.exists()
        else {}
    )
    paper = load_mapping(
        "registry/monitoring/central_bank_paper_trading_report.json",
        required=True,
    )
    audit_trace = load_mapping(
        "registry/audits/central_bank_mvp_audit_trace.json", required=True
    )
    audit_view_path = root_path / "registry/audits/central_bank_mvp_audit_view.json"
    audit_view = (
        load_mapping("registry/audits/central_bank_mvp_audit_view.json")
        if audit_view_path.exists()
        else {}
    )
    runtime = load_mapping(
        "registry/runtime_outputs/macro.central_bank.20260605.json",
        required=True,
    )
    lockbox_path = root_path / "registry/lockbox/central_bank_lockbox_review.json"
    lockbox = (
        load_mapping("registry/lockbox/central_bank_lockbox_review.json")
        if lockbox_path.exists()
        else {}
    )
    promotion_gate_path = (
        root_path / "registry/promotion/rke_production_promotion_gate.json"
    )
    promotion_gate = (
        load_mapping("registry/promotion/rke_production_promotion_gate.json")
        if promotion_gate_path.exists()
        else {}
    )
    hardening_path = (
        root_path / "registry/validation_hardening/central_bank_hardening_report.json"
    )
    hardening = (
        load_mapping("registry/validation_hardening/central_bank_hardening_report.json")
        if hardening_path.exists()
        else {}
    )
    monitor_diagnostics_path = (
        root_path / "registry/monitoring/central_bank_monitoring_diagnostics.json"
    )
    monitor_diagnostics = (
        load_mapping("registry/monitoring/central_bank_monitoring_diagnostics.json")
        if monitor_diagnostics_path.exists()
        else {}
    )
    rollback_readiness_path = (
        root_path / "registry/monitoring/central_bank_rollback_readiness_report.json"
    )
    rollback_readiness = (
        load_mapping("registry/monitoring/central_bank_rollback_readiness_report.json")
        if rollback_readiness_path.exists()
        else {}
    )
    source_validation_path = (
        root_path / "registry/source_checks/source_registry_validation_report.json"
    )
    source_validation = (
        load_mapping("registry/source_checks/source_registry_validation_report.json")
        if source_validation_path.exists()
        else {}
    )
    source_text_redaction_path = (
        root_path / "registry/compliance/source_text_redaction_report.json"
    )
    source_text_redaction = (
        load_mapping("registry/compliance/source_text_redaction_report.json")
        if source_text_redaction_path.exists()
        else {}
    )
    statistical_path = (
        root_path
        / "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    )
    statistical = (
        load_mapping(
            "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
        )
        if statistical_path.exists()
        else {}
    )
    experiment_validation_path = (
        root_path / "registry/experiment_checks/experiment_validation_report.json"
    )
    experiment_validation = (
        load_mapping("registry/experiment_checks/experiment_validation_report.json")
        if experiment_validation_path.exists()
        else {}
    )
    sector_rule_path = (
        root_path
        / "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json"
    )
    sector_disagreement_path = (
        root_path / "registry/disagreement/semiconductor_policy_substitution.json"
    )
    sector_runtime_path = (
        root_path / "registry/runtime_outputs/sector.semiconductor.demo.20260605.json"
    )
    sector_rule = (
        load_mapping(
            "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json"
        )
        if sector_rule_path.exists()
        else {}
    )
    sector_disagreement = (
        load_mapping("registry/disagreement/semiconductor_policy_substitution.json")
        if sector_disagreement_path.exists()
        else {}
    )
    sector_runtime = (
        load_mapping("registry/runtime_outputs/sector.semiconductor.demo.20260605.json")
        if sector_runtime_path.exists()
        else {}
    )
    macro_expansion_path = root_path / "registry/expansion/macro_phase6_expansion.json"
    macro_expansion = (
        load_mapping("registry/expansion/macro_phase6_expansion.json")
        if macro_expansion_path.exists()
        else {}
    )
    integration_path = (
        root_path / "registry/integration/phase7_layer_integration_contracts.json"
    )
    integration = (
        load_mapping("registry/integration/phase7_layer_integration_contracts.json")
        if integration_path.exists()
        else {}
    )
    gold_review_path = (
        root_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    )
    gold_packet_path = (
        root_path / "registry/gold_sets/tushare_research_reports.review_packet.json"
    )
    gold_candidate_claims_path = (
        root_path
        / "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
    )
    license_review_path = (
        root_path / "registry/compliance/tushare_license_review_summary.json"
    )
    license_packet_path = (
        root_path / "registry/compliance/tushare_license_review_packet.json"
    )
    review_batch_status_path = (
        root_path / "registry/review_batches/manual_review_batch_status.json"
    )
    review_progress_path = (
        root_path / "registry/review_batches/manual_review_progress_report.json"
    )
    review_runbook_path = "registry/review_batches/manual_review_runbook.md"
    operator_handoff_path = root_path / "registry/handoffs/rke_operator_handoff.json"
    operator_readiness_path = (
        root_path / "registry/handoffs/rke_operator_readiness_report.json"
    )
    gold_review = (
        load_mapping("registry/gold_sets/tushare_research_reports.review_summary.json")
        if gold_review_path.exists()
        else {}
    )
    gold_packet = (
        load_mapping("registry/gold_sets/tushare_research_reports.review_packet.json")
        if gold_packet_path.exists()
        else {}
    )
    gold_candidate_claims = (
        load_mapping(
            "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
        )
        if gold_candidate_claims_path.exists()
        else {}
    )
    license_review = (
        load_mapping("registry/compliance/tushare_license_review_summary.json")
        if license_review_path.exists()
        else {}
    )
    license_packet = (
        load_mapping("registry/compliance/tushare_license_review_packet.json")
        if license_packet_path.exists()
        else {}
    )
    review_batch_status = (
        load_mapping("registry/review_batches/manual_review_batch_status.json")
        if review_batch_status_path.exists()
        else {}
    )
    review_progress = (
        load_mapping("registry/review_batches/manual_review_progress_report.json")
        if review_progress_path.exists()
        else {}
    )
    operator_handoff = (
        load_mapping("registry/handoffs/rke_operator_handoff.json")
        if operator_handoff_path.exists()
        else {}
    )
    operator_readiness = (
        load_mapping("registry/handoffs/rke_operator_readiness_report.json")
        if operator_readiness_path.exists()
        else {}
    )
    family_path = (
        root_path
        / "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json"
    )
    cost_model_path = root_path / "registry/evaluation/cost_model/cost_model_v1.json"
    overlap_path = (
        root_path
        / "registry/evaluation/overlap_correction/effective_n_overlap_policy.json"
    )
    lockbox_policy_path = root_path / "registry/evaluation/lockbox/lockbox_policy.json"
    schema_validation_path = (
        root_path / "registry/schemas/rke_schema_validation_report.json"
    )
    claim_variable_validation_path = (
        root_path / "registry/claim_checks/claim_variable_validation_report.json"
    )
    claim_grounding_validation_path = (
        root_path / "registry/claim_checks/claim_grounding_validation_report.json"
    )
    rule_pack_validation_path = (
        root_path / "registry/rule_checks/rule_pack_validation_report.json"
    )
    prompt_validation_path = (
        root_path / "registry/prompt_checks/prompt_asset_validation_report.json"
    )
    policy_doc_validation_path = (
        root_path / "registry/docs/rke_policy_doc_validation_report.json"
    )
    rendered_prompt_path = (
        root_path / "registry/rendered_prompts/macro.central_bank.rke.json"
    )
    mutation_patch_path = (
        root_path / "registry/mutation_patches/central_bank_parameter_update.json"
    )
    family = (
        load_mapping(
            "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json"
        )
        if family_path.exists()
        else {}
    )
    cost_model = (
        load_mapping("registry/evaluation/cost_model/cost_model_v1.json")
        if cost_model_path.exists()
        else {}
    )
    overlap_policy = (
        load_mapping(
            "registry/evaluation/overlap_correction/effective_n_overlap_policy.json"
        )
        if overlap_path.exists()
        else {}
    )
    lockbox_policy = (
        load_mapping("registry/evaluation/lockbox/lockbox_policy.json")
        if lockbox_policy_path.exists()
        else {}
    )
    schema_validation = (
        load_mapping("registry/schemas/rke_schema_validation_report.json")
        if schema_validation_path.exists()
        else {}
    )
    claim_variable_validation = (
        load_mapping("registry/claim_checks/claim_variable_validation_report.json")
        if claim_variable_validation_path.exists()
        else {}
    )
    claim_grounding_validation = (
        load_mapping("registry/claim_checks/claim_grounding_validation_report.json")
        if claim_grounding_validation_path.exists()
        else {}
    )
    rule_pack_validation = (
        load_mapping("registry/rule_checks/rule_pack_validation_report.json")
        if rule_pack_validation_path.exists()
        else {}
    )
    prompt_validation = (
        load_mapping("registry/prompt_checks/prompt_asset_validation_report.json")
        if prompt_validation_path.exists()
        else {}
    )
    policy_doc_validation = (
        load_mapping("registry/docs/rke_policy_doc_validation_report.json")
        if policy_doc_validation_path.exists()
        else {}
    )
    rendered_prompt = (
        load_mapping("registry/rendered_prompts/macro.central_bank.rke.json")
        if rendered_prompt_path.exists()
        else {}
    )
    mutation_patch = (
        load_mapping("registry/mutation_patches/central_bank_parameter_update.json")
        if mutation_patch_path.exists()
        else {}
    )
    criteria = _mapping_sequence_field(
        completion,
        "criteria",
        label="registry/audits/rke_completion_audit.json",
        artifact_errors=artifact_errors,
    )
    paper_summary = _mapping_field(
        paper,
        "paper_trading_summary",
        label="registry/monitoring/central_bank_paper_trading_report.json",
        artifact_errors=artifact_errors,
    )
    production_monitor = _mapping_field(
        paper,
        "production_monitor",
        label="registry/monitoring/central_bank_paper_trading_report.json",
        artifact_errors=artifact_errors,
    )
    promotion_blockers = _sequence_field(
        promotion_gate,
        "blockers",
        label="registry/promotion/rke_production_promotion_gate.json",
        artifact_errors=artifact_errors,
    )
    ablation_checks = _mapping_field(
        hardening,
        "ablation_checks",
        label="registry/validation_hardening/central_bank_hardening_report.json",
        artifact_errors=artifact_errors,
    )
    regime_partial_pooling = _mapping_field(
        hardening,
        "regime_partial_pooling",
        label="registry/validation_hardening/central_bank_hardening_report.json",
        artifact_errors=artifact_errors,
    )
    confidence_interval = _mapping_field(
        statistical,
        "confidence_interval",
        label="registry/evaluation/statistical_significance/central_bank_after_cost_significance.json",
        artifact_errors=artifact_errors,
    )
    sector_cluster = _mapping_field(
        sector_disagreement,
        "cluster",
        label="registry/disagreement/semiconductor_policy_substitution.json",
        artifact_errors=artifact_errors,
    )
    sector_recommendation = _first_mapping_item_field(
        sector_runtime,
        "recommendations",
        label="registry/runtime_outputs/sector.semiconductor.demo.20260605.json",
        artifact_errors=artifact_errors,
    )
    macro_candidates = _sequence_field(
        macro_expansion,
        "candidates",
        label="registry/expansion/macro_phase6_expansion.json",
        artifact_errors=artifact_errors,
    )
    integration_sector = _mapping_field(
        integration,
        "sector",
        label="registry/integration/phase7_layer_integration_contracts.json",
        artifact_errors=artifact_errors,
    )
    integration_superinvestor = _mapping_field(
        integration,
        "superinvestor",
        label="registry/integration/phase7_layer_integration_contracts.json",
        artifact_errors=artifact_errors,
    )
    integration_decision = _mapping_field(
        integration,
        "decision",
        label="registry/integration/phase7_layer_integration_contracts.json",
        artifact_errors=artifact_errors,
    )
    review_batch_gold = _mapping_field(
        review_batch_status,
        "gold_set",
        label="registry/review_batches/manual_review_batch_status.json",
        artifact_errors=artifact_errors,
    )
    review_batch_license = _mapping_field(
        review_batch_status,
        "source_license",
        label="registry/review_batches/manual_review_batch_status.json",
        artifact_errors=artifact_errors,
    )
    operator_remaining_blockers = _sequence_field(
        operator_handoff,
        "remaining_blockers",
        label="registry/handoffs/rke_operator_handoff.json",
        artifact_errors=artifact_errors,
    )
    operator_gates = _sequence_field(
        operator_handoff,
        "gates",
        label="registry/handoffs/rke_operator_handoff.json",
        artifact_errors=artifact_errors,
    )
    review_progress_gates = _sequence_field(
        review_progress,
        "gates",
        label="registry/review_batches/manual_review_progress_report.json",
        artifact_errors=artifact_errors,
    )
    review_progress_blockers = _sequence_field(
        review_progress,
        "blockers",
        label="registry/review_batches/manual_review_progress_report.json",
        artifact_errors=artifact_errors,
    )
    schema_records = _sequence_field(
        schema_validation,
        "records",
        label="registry/schemas/rke_schema_validation_report.json",
        artifact_errors=artifact_errors,
    )
    claim_variable_records = _sequence_field(
        claim_variable_validation,
        "records",
        label="registry/claim_checks/claim_variable_validation_report.json",
        artifact_errors=artifact_errors,
    )
    claim_grounding_records = _sequence_field(
        claim_grounding_validation,
        "records",
        label="registry/claim_checks/claim_grounding_validation_report.json",
        artifact_errors=artifact_errors,
    )
    rule_pack_validation_records = _sequence_field(
        rule_pack_validation,
        "records",
        label="registry/rule_checks/rule_pack_validation_report.json",
        artifact_errors=artifact_errors,
    )
    experiment_validation_records = _mapping_sequence_field(
        experiment_validation,
        "records",
        label="registry/experiment_checks/experiment_validation_report.json",
        artifact_errors=artifact_errors,
    )
    experiment_regime_record = next(
        (
            record
            for record in experiment_validation_records
            if record.get("check_id") == "EXPERIMENT-REGIME-BUCKET-RULES"
        ),
        {},
    )
    experiment_regime_details = _mapping_field(
        experiment_regime_record,
        "details",
        label="registry/experiment_checks/experiment_validation_report.json.records.EXPERIMENT-REGIME-BUCKET-RULES",
        artifact_errors=artifact_errors,
    )
    prompt_records = _sequence_field(
        prompt_validation,
        "records",
        label="registry/prompt_checks/prompt_asset_validation_report.json",
        artifact_errors=artifact_errors,
    )
    mutation = _mapping_field(
        mutation_patch,
        "mutation",
        label="registry/mutation_patches/central_bank_parameter_update.json",
        artifact_errors=artifact_errors,
    )
    mutation_validation = _mapping_field(
        mutation_patch,
        "validation",
        label="registry/mutation_patches/central_bank_parameter_update.json",
        artifact_errors=artifact_errors,
    )
    audit_source_ids = _sequence_field(
        audit_trace,
        "source_ids",
        label="registry/audits/central_bank_mvp_audit_trace.json",
        artifact_errors=artifact_errors,
    )
    audit_claim_ids = _sequence_field(
        audit_trace,
        "claim_ids",
        label="registry/audits/central_bank_mvp_audit_trace.json",
        artifact_errors=artifact_errors,
    )
    audit_rule_ids = _sequence_field(
        audit_trace,
        "rule_ids",
        label="registry/audits/central_bank_mvp_audit_trace.json",
        artifact_errors=artifact_errors,
    )
    audit_experiment_ids = _sequence_field(
        audit_trace,
        "experiment_ids",
        label="registry/audits/central_bank_mvp_audit_trace.json",
        artifact_errors=artifact_errors,
    )
    audit_patch_ids = _sequence_field(
        audit_trace,
        "patch_ids",
        label="registry/audits/central_bank_mvp_audit_trace.json",
        artifact_errors=artifact_errors,
    )
    audit_agent_output_ids = _sequence_field(
        audit_trace,
        "agent_output_ids",
        label="registry/audits/central_bank_mvp_audit_trace.json",
        artifact_errors=artifact_errors,
    )
    audit_missing_references = _sequence_field(
        audit_view,
        "missing_references",
        label="registry/audits/central_bank_mvp_audit_view.json",
        artifact_errors=artifact_errors,
    )
    audit_broken_edges = _sequence_field(
        audit_view,
        "broken_edges",
        label="registry/audits/central_bank_mvp_audit_view.json",
        artifact_errors=artifact_errors,
    )
    runtime_progress = _mapping_field(
        runtime,
        "progress_event",
        label="registry/runtime_outputs/macro.central_bank.20260605.json",
        artifact_errors=artifact_errors,
    )
    runtime_recommendations = _sequence_field(
        runtime,
        "recommendations",
        label="registry/runtime_outputs/macro.central_bank.20260605.json",
        artifact_errors=artifact_errors,
    )
    coverage_records = _mapping_sequence_field(
        coverage,
        "records",
        label="registry/audits/rke_master_plan_coverage_report.json",
        artifact_errors=artifact_errors,
    )
    coverage_mvp_deliverable_records = _mapping_sequence_field(
        coverage,
        "mvp_deliverable_records",
        label="registry/audits/rke_master_plan_coverage_report.json",
        artifact_errors=artifact_errors,
    )
    coverage_mvp_exit_records = _mapping_sequence_field(
        coverage,
        "mvp_exit_records",
        label="registry/audits/rke_master_plan_coverage_report.json",
        artifact_errors=artifact_errors,
    )
    coverage_final_acceptance_records = _mapping_sequence_field(
        coverage,
        "final_acceptance_records",
        label="registry/audits/rke_master_plan_coverage_report.json",
        artifact_errors=artifact_errors,
    )
    return {
        "dashboard_id": "RKE-DASHBOARD-20260605",
        "artifact_errors": tuple(artifact_errors),
        "ready_for_broad_rollout": bool(criteria)
        and not artifact_errors
        and all(item.get("passed") is True for item in criteria),
        "completion": {
            "passed": sum(item.get("passed") is True for item in criteria),
            "total": len(criteria),
            "blockers": [
                item.get("blocker") for item in criteria if item.get("blocker")
            ],
        },
        "master_plan_coverage": {
            "coverage_complete": coverage.get("coverage_complete"),
            "ready_for_broad_rollout": coverage.get("ready_for_broad_rollout"),
            "passed_count": coverage.get("passed_count"),
            "blocked_count": coverage.get("blocked_count"),
            "missing_count": coverage.get("missing_count"),
            "blocked_sections": _blocked_section_ids(coverage_records),
            "mvp_deliverables": {
                "section": coverage.get("mvp_deliverables_section"),
                "ready": coverage.get("mvp_deliverables_ready"),
                "passed_count": coverage.get("mvp_deliverables_passed_count"),
                "blocked_count": coverage.get("mvp_deliverables_blocked_count"),
                "missing_count": coverage.get("mvp_deliverables_missing_count"),
                "blocked_sections": _blocked_section_ids(
                    coverage_mvp_deliverable_records
                ),
            },
            "mvp_exit_criteria": {
                "section": coverage.get("mvp_exit_criteria_section"),
                "ready": coverage.get("mvp_exit_ready"),
                "passed_count": coverage.get("mvp_exit_passed_count"),
                "blocked_count": coverage.get("mvp_exit_blocked_count"),
                "missing_count": coverage.get("mvp_exit_missing_count"),
                "blocked_sections": _blocked_section_ids(coverage_mvp_exit_records),
            },
            "final_acceptance": {
                "section": coverage.get("final_acceptance_section"),
                "ready": coverage.get("final_acceptance_ready"),
                "passed_count": coverage.get("final_acceptance_passed_count"),
                "blocked_count": coverage.get("final_acceptance_blocked_count"),
                "missing_count": coverage.get("final_acceptance_missing_count"),
                "blocked_sections": _blocked_section_ids(
                    coverage_final_acceptance_records
                ),
            },
        },
        "paper_trading": paper_summary,
        "production_monitor": production_monitor,
        "production_monitor_diagnostics": {
            "accepted": monitor_diagnostics.get("accepted"),
            "scenario_count": monitor_diagnostics.get("scenario_count"),
            "failure_count": monitor_diagnostics.get("failure_count"),
        },
        "rollback_readiness": {
            "accepted": rollback_readiness.get("accepted"),
            "check_count": rollback_readiness.get("check_count"),
            "failure_count": rollback_readiness.get("failure_count"),
        },
        "lockbox": {
            "result": lockbox.get("result"),
            "open_count": lockbox.get("open_count"),
            "production_allowed": lockbox.get("result") == "passed"
            and int(lockbox.get("open_count") or 0) <= 1,
        },
        "promotion_gate": {
            "paper_trading_allowed": promotion_gate.get("paper_trading_allowed"),
            "staged_production_allowed": promotion_gate.get(
                "staged_production_allowed"
            ),
            "production_allowed": promotion_gate.get("production_allowed"),
            "next_state": promotion_gate.get("next_state"),
            "direct_production_forbidden": promotion_gate.get(
                "direct_production_forbidden"
            ),
            "blocker_count": len(promotion_blockers),
        },
        "validation_hardening": {
            "ablation_accepted": ablation_checks.get("accepted"),
            "horizon_metric_failures": hardening.get("horizon_metric_failures", ()),
            "precision_failures": hardening.get("precision_failures", ()),
            "regime_failures": regime_partial_pooling.get("failures", ()),
            "statistical_significance_accepted": statistical.get("accepted"),
            "after_cost_ci_low": confidence_interval.get("low"),
            "deflated_sharpe_ratio": statistical.get("deflated_sharpe_ratio"),
        },
        "experiment_validation": {
            "accepted": experiment_validation.get("accepted"),
            "failure_count": experiment_validation.get("failure_count"),
            "record_count": len(experiment_validation_records),
            "diagnostic_failure_count": experiment_regime_details.get(
                "diagnostic_failure_count"
            ),
            "insufficient_bucket_count": experiment_regime_details.get(
                "insufficient_bucket_count"
            ),
        },
        "source_validation": {
            "accepted_for_sandbox": source_validation.get("accepted_for_sandbox"),
            "accepted_for_production": source_validation.get("accepted_for_production"),
            "failure_count": source_validation.get("failure_count"),
            "production_blocker_count": source_validation.get(
                "production_blocker_count"
            ),
            "unique_source_count": source_validation.get("unique_source_count"),
            "duplicate_reference_count": source_validation.get(
                "duplicate_reference_count"
            ),
        },
        "source_text_redaction": {
            "accepted": source_text_redaction.get("accepted"),
            "failure_count": source_text_redaction.get("failure_count"),
            "source_text_count": source_text_redaction.get("source_text_count"),
            "checked_path_count": source_text_redaction.get("checked_path_count"),
            "skipped_allowed_path_count": source_text_redaction.get(
                "skipped_allowed_path_count"
            ),
            "min_match_chars": source_text_redaction.get("min_match_chars"),
        },
        "sector_demo": {
            "rule_pack_id": sector_rule.get("rule_pack_id"),
            "demo_status": sector_rule.get("demo_status"),
            "production_allowed": sector_rule.get("production_allowed"),
            "empirical_confidence_bin": sector_rule.get("empirical_confidence_bin"),
            "disagreement_cluster_id": sector_cluster.get("cluster_id"),
            "recommendation_actionability": sector_recommendation.get("actionability"),
        },
        "macro_expansion": {
            "phase": macro_expansion.get("phase"),
            "central_bank_phase4_ready": macro_expansion.get(
                "central_bank_phase4_ready"
            ),
            "candidate_count": len(macro_candidates),
            "production_allowed": macro_expansion.get("production_allowed"),
        },
        "layer_integration": {
            "sector_agent": integration_sector.get("agent_id"),
            "sector_actionability": integration_sector.get("actionability"),
            "superinvestor_agent": integration_superinvestor.get("agent_id"),
            "decision_agent": integration_decision.get("agent_id"),
            "decision_cash_floor": integration_decision.get("cash_floor"),
        },
        "manual_review_gates": {
            "gold_set": {
                "reviewed_claims": gold_review.get("reviewed_claims"),
                "total_claims": gold_review.get("total_claims"),
                "pending_claims": gold_review.get("pending_claims"),
                "passed": gold_review.get("passed"),
            },
            "gold_review_packet": {
                "status": gold_packet.get("status"),
                "document_count": gold_packet.get("document_count"),
                "pending_review_rows": gold_packet.get("pending_review_rows"),
                "candidate_span_ref_count": gold_packet.get("candidate_span_ref_count"),
                "risk_flag_counts": gold_packet.get("risk_flag_counts"),
            },
            "gold_candidate_claims": {
                "candidate_claim_count": gold_candidate_claims.get(
                    "candidate_claim_count"
                ),
                "candidate_available_count": gold_candidate_claims.get(
                    "candidate_available_count"
                ),
                "missing_variable_mapping_count": gold_candidate_claims.get(
                    "missing_variable_mapping_count"
                ),
                "review_rows_with_candidate_fields": gold_candidate_claims.get(
                    "review_rows_with_candidate_fields"
                ),
                "manual_fields_preserved": gold_candidate_claims.get(
                    "manual_fields_preserved"
                ),
            },
            "source_license": {
                "reviewed_sources": license_review.get("reviewed_sources"),
                "total_sources": license_review.get("total_sources"),
                "pending_sources": license_review.get("pending_sources"),
                "approved_for_production_runtime": license_review.get(
                    "approved_for_production_runtime"
                ),
                "passed": license_review.get("passed"),
            },
            "license_review_packet": {
                "status": license_packet.get("status"),
                "source_count": license_packet.get("source_count"),
                "pending_sources": license_packet.get("pending_sources"),
                "approved_for_derived_claim_storage": license_packet.get(
                    "approved_for_derived_claim_storage"
                ),
                "approved_for_production_runtime": license_packet.get(
                    "approved_for_production_runtime"
                ),
                "policy_reason_counts": license_packet.get("policy_reason_counts"),
            },
            "review_batches": {
                "ready_for_manual_review": review_batch_status.get(
                    "ready_for_manual_review"
                ),
                "gold_set_pending_rows": review_batch_gold.get("pending_rows"),
                "gold_set_exported_rows": review_batch_gold.get("exported_rows"),
                "gold_set_full_import_template": review_batch_gold.get(
                    "full_import_template_path"
                ),
                "gold_set_review_workbook": "registry/review_batches/gold_set_review_workbook.md",
                "gold_set_dry_run_command": review_batch_gold.get("dry_run_command"),
                "source_license_pending_rows": review_batch_license.get("pending_rows"),
                "source_license_exported_rows": review_batch_license.get(
                    "exported_rows"
                ),
                "source_license_review_workbook": "registry/review_batches/source_license_review_workbook.md",
                "source_license_dry_run_command": review_batch_license.get(
                    "dry_run_command"
                ),
            },
            "review_progress": {
                "ready_for_promotion_dry_run": review_progress.get(
                    "ready_for_promotion_dry_run"
                ),
                "gate_count": len(review_progress_gates),
                "blocker_count": len(review_progress_blockers),
                "runbook_path": review_runbook_path,
            },
        },
        "operator_handoff": {
            "ready_for_operator_review": operator_handoff.get(
                "ready_for_operator_review"
            ),
            "next_state": operator_handoff.get("next_state"),
            "remaining_blocker_count": len(operator_remaining_blockers),
            "gate_count": len(operator_gates),
            "run_order": operator_handoff.get("run_order"),
        },
        "operator_readiness": {
            "accepted": operator_readiness.get("accepted"),
            "check_count": operator_readiness.get("check_count"),
            "failure_count": operator_readiness.get("failure_count"),
        },
        "experiment_governance": {
            "family_id": family.get("family_id"),
            "selected_experiment_id": family.get("selected_experiment_id"),
            "adjusted_q_value": family.get("adjusted_q_value"),
            "max_fdr": family.get("max_fdr"),
            "primary_metric": cost_model.get("primary_metric"),
            "net_alpha_after_cost": cost_model.get("net_alpha_after_cost"),
            "effective_n": overlap_policy.get("effective_n"),
            "minimum_effective_n": overlap_policy.get("minimum_effective_n"),
            "overlap_policy": overlap_policy.get("overlap_policy"),
            "lockbox_policy_status": lockbox_policy.get("policy_status"),
        },
        "schema_validation": {
            "accepted": schema_validation.get("accepted"),
            "failure_count": schema_validation.get("failure_count"),
            "record_count": len(schema_records),
        },
        "claim_variable_validation": {
            "accepted": claim_variable_validation.get("accepted"),
            "failure_count": claim_variable_validation.get("failure_count"),
            "record_count": len(claim_variable_records),
        },
        "claim_grounding_validation": {
            "accepted": claim_grounding_validation.get("accepted"),
            "failure_count": claim_grounding_validation.get("failure_count"),
            "record_count": len(claim_grounding_records),
        },
        "rule_pack_validation": {
            "accepted": rule_pack_validation.get("accepted"),
            "failure_count": rule_pack_validation.get("failure_count"),
            "record_count": len(rule_pack_validation_records),
        },
        "prompt_evolution": {
            "rendered_prompt_path": rendered_prompt.get("rendered_prompt_path"),
            "prompt_version": rendered_prompt.get("prompt_version"),
            "asset_validation_accepted": prompt_validation.get("accepted"),
            "asset_validation_failure_count": prompt_validation.get("failure_count"),
            "asset_validation_record_count": len(prompt_records),
            "policy_doc_validation_accepted": policy_doc_validation.get("accepted"),
            "policy_doc_validation_failure_count": policy_doc_validation.get(
                "failure_count"
            ),
            "mutation_id": mutation.get("mutation_id"),
            "mutation_target_path": mutation.get("target_path"),
            "mutation_validation_accepted": mutation_validation.get("accepted"),
            "production_allowed": mutation_patch.get("production_allowed"),
        },
        "audit_trace": {
            "complete": audit_view.get("complete"),
            "node_count": audit_view.get("node_count"),
            "edge_count": audit_view.get("edge_count"),
            "missing_reference_count": len(audit_missing_references),
            "broken_edge_count": len(audit_broken_edges),
            "source_count": len(audit_source_ids),
            "claim_count": len(audit_claim_ids),
            "rule_count": len(audit_rule_ids),
            "experiment_count": len(audit_experiment_ids),
            "patch_count": len(audit_patch_ids),
            "agent_output_count": len(audit_agent_output_ids),
        },
        "runtime_progress": runtime_progress,
        "runtime_recommendations": runtime_recommendations,
    }


def render_dashboard_markdown(report: Mapping[str, Any]) -> str:
    completion = dict(report.get("completion") or {})
    coverage = dict(report.get("master_plan_coverage") or {})
    mvp_deliverables = dict(coverage.get("mvp_deliverables") or {})
    mvp_exit = dict(coverage.get("mvp_exit_criteria") or {})
    final_acceptance = dict(coverage.get("final_acceptance") or {})
    paper = dict(report.get("paper_trading") or {})
    monitor = dict(report.get("production_monitor") or {})
    blockers = completion.get("blockers") or []
    lines = [
        "# RKE Dashboard",
        "",
        f"- Broad rollout ready: {str(report.get('ready_for_broad_rollout')).lower()}",
        f"- Dashboard artifact errors: {len(report.get('artifact_errors') or ())}",
        f"- Completion: {completion.get('passed', 0)} / {completion.get('total', 0)}",
        f"- Master-plan coverage missing: {coverage.get('missing_count')}",
        f"- Master-plan coverage blocked: {coverage.get('blocked_count')}",
        f"- Master-plan blocked sections: {', '.join(coverage.get('blocked_sections') or ()) or 'none'}",
        f"- MVP deliverables blocked: {mvp_deliverables.get('blocked_count')}",
        f"- MVP deliverable blocked sections: {', '.join(mvp_deliverables.get('blocked_sections') or ()) or 'none'}",
        f"- MVP exit criteria blocked: {mvp_exit.get('blocked_count')}",
        f"- MVP exit blocked sections: {', '.join(mvp_exit.get('blocked_sections') or ()) or 'none'}",
        f"- Final acceptance blocked: {final_acceptance.get('blocked_count')}",
        f"- Final acceptance blocked sections: {', '.join(final_acceptance.get('blocked_sections') or ()) or 'none'}",
        f"- Paper trading ready: {str(paper.get('ready')).lower()}",
        f"- Mean live vs baseline delta: {paper.get('mean_live_vs_baseline_delta')}",
        f"- Production monitor state: {monitor.get('state')}",
        f"- Production monitor action: {monitor.get('action')}",
        f"- Production monitor diagnostics accepted: {dict(report.get('production_monitor_diagnostics') or {}).get('accepted')}",
        f"- Production monitor diagnostic failures: {dict(report.get('production_monitor_diagnostics') or {}).get('failure_count')}",
        f"- Rollback readiness accepted: {dict(report.get('rollback_readiness') or {}).get('accepted')}",
        f"- Rollback readiness failures: {dict(report.get('rollback_readiness') or {}).get('failure_count')}",
        f"- Lockbox result: {dict(report.get('lockbox') or {}).get('result')}",
        f"- Promotion next state: {dict(report.get('promotion_gate') or {}).get('next_state')}",
        f"- Promotion production allowed: {dict(report.get('promotion_gate') or {}).get('production_allowed')}",
        f"- Validation ablations accepted: {dict(report.get('validation_hardening') or {}).get('ablation_accepted')}",
        f"- Validation statistical significance accepted: {dict(report.get('validation_hardening') or {}).get('statistical_significance_accepted')}",
        f"- Experiment validation failures: {dict(report.get('experiment_validation') or {}).get('failure_count')}",
        f"- Source validation sandbox accepted: {dict(report.get('source_validation') or {}).get('accepted_for_sandbox')}",
        f"- Source validation production blockers: {dict(report.get('source_validation') or {}).get('production_blocker_count')}",
        f"- Source text redaction accepted: {dict(report.get('source_text_redaction') or {}).get('accepted')}",
        f"- Source text redaction failures: {dict(report.get('source_text_redaction') or {}).get('failure_count')}",
        f"- Sector demo: {dict(report.get('sector_demo') or {}).get('demo_status')}",
        f"- Macro expansion candidates: {dict(report.get('macro_expansion') or {}).get('candidate_count')}",
        f"- Phase 7 sector actionability: {dict(report.get('layer_integration') or {}).get('sector_actionability')}",
        f"- Gold-set review pending claims: {dict(dict(report.get('manual_review_gates') or {}).get('gold_set') or {}).get('pending_claims')}",
        f"- Gold review packet spans: {dict(dict(report.get('manual_review_gates') or {}).get('gold_review_packet') or {}).get('candidate_span_ref_count')}",
        f"- Gold candidate claims: {dict(dict(report.get('manual_review_gates') or {}).get('gold_candidate_claims') or {}).get('candidate_claim_count')}",
        f"- License review pending sources: {dict(dict(report.get('manual_review_gates') or {}).get('source_license') or {}).get('pending_sources')}",
        f"- License review packet pending sources: {dict(dict(report.get('manual_review_gates') or {}).get('license_review_packet') or {}).get('pending_sources')}",
        f"- Next gold review batch rows: {dict(dict(report.get('manual_review_gates') or {}).get('review_batches') or {}).get('gold_set_exported_rows')}",
        f"- Full gold review import template: {dict(dict(report.get('manual_review_gates') or {}).get('review_batches') or {}).get('gold_set_full_import_template')}",
        f"- Gold review workbook: {dict(dict(report.get('manual_review_gates') or {}).get('review_batches') or {}).get('gold_set_review_workbook')}",
        f"- Next license review batch rows: {dict(dict(report.get('manual_review_gates') or {}).get('review_batches') or {}).get('source_license_exported_rows')}",
        f"- Source license review workbook: {dict(dict(report.get('manual_review_gates') or {}).get('review_batches') or {}).get('source_license_review_workbook')}",
        f"- Manual review promotion dry-run ready: {dict(dict(report.get('manual_review_gates') or {}).get('review_progress') or {}).get('ready_for_promotion_dry_run')}",
        f"- Manual review progress blockers: {dict(dict(report.get('manual_review_gates') or {}).get('review_progress') or {}).get('blocker_count')}",
        f"- Manual review runbook: {dict(dict(report.get('manual_review_gates') or {}).get('review_progress') or {}).get('runbook_path')}",
        f"- Operator handoff ready: {dict(report.get('operator_handoff') or {}).get('ready_for_operator_review')}",
        f"- Operator handoff blockers: {dict(report.get('operator_handoff') or {}).get('remaining_blocker_count')}",
        f"- Operator readiness accepted: {dict(report.get('operator_readiness') or {}).get('accepted')}",
        f"- Operator readiness failures: {dict(report.get('operator_readiness') or {}).get('failure_count')}",
        f"- Experiment governance family: {dict(report.get('experiment_governance') or {}).get('family_id')}",
        f"- Schema validation failures: {dict(report.get('schema_validation') or {}).get('failure_count')}",
        f"- Claim variable validation failures: {dict(report.get('claim_variable_validation') or {}).get('failure_count')}",
        f"- Claim grounding validation failures: {dict(report.get('claim_grounding_validation') or {}).get('failure_count')}",
        f"- Rule pack validation failures: {dict(report.get('rule_pack_validation') or {}).get('failure_count')}",
        f"- Prompt asset validation failures: {dict(report.get('prompt_evolution') or {}).get('asset_validation_failure_count')}",
        f"- Policy doc validation failures: {dict(report.get('prompt_evolution') or {}).get('policy_doc_validation_failure_count')}",
        f"- Prompt mutation validation accepted: {dict(report.get('prompt_evolution') or {}).get('mutation_validation_accepted')}",
        f"- Audit trace complete: {dict(report.get('audit_trace') or {}).get('complete')}",
        f"- Audit trace edges: {dict(report.get('audit_trace') or {}).get('edge_count')}",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Runtime",
            "",
            f"- Agent: {dict(report.get('runtime_progress') or {}).get('agent_id')}",
            f"- Status: {dict(report.get('runtime_progress') or {}).get('status')}",
            f"- Confidence: {dict(report.get('runtime_progress') or {}).get('confidence')}",
            "",
        ]
    )
    return "\n".join(lines)


def write_dashboard_reports(root: str | Path = ".") -> dict[str, str]:
    root_path = Path(root)
    report = build_dashboard_report(root_path)
    output_dir = root_path / "registry/dashboards"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "rke_dashboard.json"
    md_path = output_dir / "rke_dashboard.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_dashboard_markdown(report) + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> None:
    print(json.dumps(write_dashboard_reports(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
