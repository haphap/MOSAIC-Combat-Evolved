"""Dashboard-ready report generation for RKE monitoring and audits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_dashboard_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    completion = _read_json(root_path / "registry/audits/rke_completion_audit.json")
    coverage_path = root_path / "registry/audits/rke_master_plan_coverage_report.json"
    coverage = _read_json(coverage_path) if coverage_path.exists() else {}
    paper = _read_json(root_path / "registry/monitoring/central_bank_paper_trading_report.json")
    audit_trace = _read_json(root_path / "registry/audits/central_bank_mvp_audit_trace.json")
    audit_view_path = root_path / "registry/audits/central_bank_mvp_audit_view.json"
    audit_view = _read_json(audit_view_path) if audit_view_path.exists() else {}
    runtime = _read_json(root_path / "registry/runtime_outputs/macro.central_bank.20260605.json")
    lockbox_path = root_path / "registry/lockbox/central_bank_lockbox_review.json"
    lockbox = _read_json(lockbox_path) if lockbox_path.exists() else {}
    promotion_gate_path = root_path / "registry/promotion/rke_production_promotion_gate.json"
    promotion_gate = _read_json(promotion_gate_path) if promotion_gate_path.exists() else {}
    hardening_path = root_path / "registry/validation_hardening/central_bank_hardening_report.json"
    hardening = _read_json(hardening_path) if hardening_path.exists() else {}
    monitor_diagnostics_path = root_path / "registry/monitoring/central_bank_monitoring_diagnostics.json"
    monitor_diagnostics = (
        _read_json(monitor_diagnostics_path) if monitor_diagnostics_path.exists() else {}
    )
    rollback_readiness_path = root_path / "registry/monitoring/central_bank_rollback_readiness_report.json"
    rollback_readiness = (
        _read_json(rollback_readiness_path) if rollback_readiness_path.exists() else {}
    )
    source_validation_path = root_path / "registry/source_checks/source_registry_validation_report.json"
    source_validation = _read_json(source_validation_path) if source_validation_path.exists() else {}
    source_text_redaction_path = root_path / "registry/compliance/source_text_redaction_report.json"
    source_text_redaction = (
        _read_json(source_text_redaction_path) if source_text_redaction_path.exists() else {}
    )
    statistical_path = (
        root_path
        / "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    )
    statistical = _read_json(statistical_path) if statistical_path.exists() else {}
    sector_rule_path = root_path / "registry/rule_packs/sector.semiconductor.policy_substitution.v1.json"
    sector_disagreement_path = root_path / "registry/disagreement/semiconductor_policy_substitution.json"
    sector_runtime_path = root_path / "registry/runtime_outputs/sector.semiconductor.demo.20260605.json"
    sector_rule = _read_json(sector_rule_path) if sector_rule_path.exists() else {}
    sector_disagreement = (
        _read_json(sector_disagreement_path) if sector_disagreement_path.exists() else {}
    )
    sector_runtime = _read_json(sector_runtime_path) if sector_runtime_path.exists() else {}
    macro_expansion_path = root_path / "registry/expansion/macro_phase6_expansion.json"
    macro_expansion = _read_json(macro_expansion_path) if macro_expansion_path.exists() else {}
    integration_path = root_path / "registry/integration/phase7_layer_integration_contracts.json"
    integration = _read_json(integration_path) if integration_path.exists() else {}
    gold_review_path = root_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    gold_packet_path = root_path / "registry/gold_sets/tushare_research_reports.review_packet.json"
    gold_candidate_claims_path = (
        root_path / "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
    )
    license_review_path = root_path / "registry/compliance/tushare_license_review_summary.json"
    license_packet_path = root_path / "registry/compliance/tushare_license_review_packet.json"
    review_batch_status_path = root_path / "registry/review_batches/manual_review_batch_status.json"
    operator_handoff_path = root_path / "registry/handoffs/rke_operator_handoff.json"
    operator_readiness_path = root_path / "registry/handoffs/rke_operator_readiness_report.json"
    gold_review = _read_json(gold_review_path) if gold_review_path.exists() else {}
    gold_packet = _read_json(gold_packet_path) if gold_packet_path.exists() else {}
    gold_candidate_claims = (
        _read_json(gold_candidate_claims_path) if gold_candidate_claims_path.exists() else {}
    )
    license_review = _read_json(license_review_path) if license_review_path.exists() else {}
    license_packet = _read_json(license_packet_path) if license_packet_path.exists() else {}
    review_batch_status = (
        _read_json(review_batch_status_path) if review_batch_status_path.exists() else {}
    )
    operator_handoff = _read_json(operator_handoff_path) if operator_handoff_path.exists() else {}
    operator_readiness = (
        _read_json(operator_readiness_path) if operator_readiness_path.exists() else {}
    )
    family_path = root_path / "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json"
    cost_model_path = root_path / "registry/evaluation/cost_model/cost_model_v1.json"
    overlap_path = root_path / "registry/evaluation/overlap_correction/effective_n_overlap_policy.json"
    lockbox_policy_path = root_path / "registry/evaluation/lockbox/lockbox_policy.json"
    schema_validation_path = root_path / "registry/schemas/rke_schema_validation_report.json"
    claim_variable_validation_path = root_path / "registry/claim_checks/claim_variable_validation_report.json"
    prompt_validation_path = root_path / "registry/prompt_checks/prompt_asset_validation_report.json"
    policy_doc_validation_path = root_path / "registry/docs/rke_policy_doc_validation_report.json"
    rendered_prompt_path = root_path / "registry/rendered_prompts/macro.central_bank.rke.json"
    mutation_patch_path = root_path / "registry/mutation_patches/central_bank_parameter_update.json"
    family = _read_json(family_path) if family_path.exists() else {}
    cost_model = _read_json(cost_model_path) if cost_model_path.exists() else {}
    overlap_policy = _read_json(overlap_path) if overlap_path.exists() else {}
    lockbox_policy = _read_json(lockbox_policy_path) if lockbox_policy_path.exists() else {}
    schema_validation = (
        _read_json(schema_validation_path) if schema_validation_path.exists() else {}
    )
    claim_variable_validation = (
        _read_json(claim_variable_validation_path) if claim_variable_validation_path.exists() else {}
    )
    prompt_validation = (
        _read_json(prompt_validation_path) if prompt_validation_path.exists() else {}
    )
    policy_doc_validation = (
        _read_json(policy_doc_validation_path) if policy_doc_validation_path.exists() else {}
    )
    rendered_prompt = _read_json(rendered_prompt_path) if rendered_prompt_path.exists() else {}
    mutation_patch = _read_json(mutation_patch_path) if mutation_patch_path.exists() else {}
    criteria = completion.get("criteria", ())
    return {
        "dashboard_id": "RKE-DASHBOARD-20260605",
        "ready_for_broad_rollout": all(item.get("passed") is True for item in criteria),
        "completion": {
            "passed": sum(item.get("passed") is True for item in criteria),
            "total": len(criteria),
            "blockers": [item.get("blocker") for item in criteria if item.get("blocker")],
        },
        "master_plan_coverage": {
            "coverage_complete": coverage.get("coverage_complete"),
            "ready_for_broad_rollout": coverage.get("ready_for_broad_rollout"),
            "passed_count": coverage.get("passed_count"),
            "blocked_count": coverage.get("blocked_count"),
            "missing_count": coverage.get("missing_count"),
        },
        "paper_trading": paper.get("paper_trading_summary", {}),
        "production_monitor": paper.get("production_monitor", {}),
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
            "staged_production_allowed": promotion_gate.get("staged_production_allowed"),
            "production_allowed": promotion_gate.get("production_allowed"),
            "next_state": promotion_gate.get("next_state"),
            "direct_production_forbidden": promotion_gate.get("direct_production_forbidden"),
            "blocker_count": len(promotion_gate.get("blockers") or ()),
        },
        "validation_hardening": {
            "ablation_accepted": hardening.get("ablation_checks", {}).get("accepted"),
            "horizon_metric_failures": hardening.get("horizon_metric_failures", ()),
            "precision_failures": hardening.get("precision_failures", ()),
            "regime_failures": hardening.get("regime_partial_pooling", {}).get("failures", ()),
            "statistical_significance_accepted": statistical.get("accepted"),
            "after_cost_ci_low": (statistical.get("confidence_interval") or {}).get("low"),
            "deflated_sharpe_ratio": statistical.get("deflated_sharpe_ratio"),
        },
        "source_validation": {
            "accepted_for_sandbox": source_validation.get("accepted_for_sandbox"),
            "accepted_for_production": source_validation.get("accepted_for_production"),
            "failure_count": source_validation.get("failure_count"),
            "production_blocker_count": source_validation.get("production_blocker_count"),
            "unique_source_count": source_validation.get("unique_source_count"),
            "duplicate_reference_count": source_validation.get("duplicate_reference_count"),
        },
        "source_text_redaction": {
            "accepted": source_text_redaction.get("accepted"),
            "failure_count": source_text_redaction.get("failure_count"),
            "source_text_count": source_text_redaction.get("source_text_count"),
            "checked_path_count": source_text_redaction.get("checked_path_count"),
            "skipped_allowed_path_count": source_text_redaction.get("skipped_allowed_path_count"),
            "min_match_chars": source_text_redaction.get("min_match_chars"),
        },
        "sector_demo": {
            "rule_pack_id": sector_rule.get("rule_pack_id"),
            "demo_status": sector_rule.get("demo_status"),
            "production_allowed": sector_rule.get("production_allowed"),
            "empirical_confidence_bin": sector_rule.get("empirical_confidence_bin"),
            "disagreement_cluster_id": sector_disagreement.get("cluster", {}).get("cluster_id"),
            "recommendation_actionability": (
                (sector_runtime.get("recommendations") or [{}])[0].get("actionability")
                if sector_runtime
                else None
            ),
        },
        "macro_expansion": {
            "phase": macro_expansion.get("phase"),
            "central_bank_phase4_ready": macro_expansion.get("central_bank_phase4_ready"),
            "candidate_count": len(macro_expansion.get("candidates") or ()),
            "production_allowed": macro_expansion.get("production_allowed"),
        },
        "layer_integration": {
            "sector_agent": integration.get("sector", {}).get("agent_id"),
            "sector_actionability": integration.get("sector", {}).get("actionability"),
            "superinvestor_agent": integration.get("superinvestor", {}).get("agent_id"),
            "decision_agent": integration.get("decision", {}).get("agent_id"),
            "decision_cash_floor": integration.get("decision", {}).get("cash_floor"),
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
                "candidate_claim_count": gold_candidate_claims.get("candidate_claim_count"),
                "candidate_available_count": gold_candidate_claims.get("candidate_available_count"),
                "missing_variable_mapping_count": gold_candidate_claims.get(
                    "missing_variable_mapping_count"
                ),
                "review_rows_with_candidate_fields": gold_candidate_claims.get(
                    "review_rows_with_candidate_fields"
                ),
                "manual_fields_preserved": gold_candidate_claims.get("manual_fields_preserved"),
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
                "ready_for_manual_review": review_batch_status.get("ready_for_manual_review"),
                "gold_set_pending_rows": (review_batch_status.get("gold_set") or {}).get(
                    "pending_rows"
                ),
                "gold_set_exported_rows": (review_batch_status.get("gold_set") or {}).get(
                    "exported_rows"
                ),
                "gold_set_full_import_template": (review_batch_status.get("gold_set") or {}).get(
                    "full_import_template_path"
                ),
                "gold_set_dry_run_command": (review_batch_status.get("gold_set") or {}).get(
                    "dry_run_command"
                ),
                "source_license_pending_rows": (
                    review_batch_status.get("source_license") or {}
                ).get("pending_rows"),
                "source_license_exported_rows": (
                    review_batch_status.get("source_license") or {}
                ).get("exported_rows"),
                "source_license_dry_run_command": (
                    review_batch_status.get("source_license") or {}
                ).get("dry_run_command"),
            },
        },
        "operator_handoff": {
            "ready_for_operator_review": operator_handoff.get("ready_for_operator_review"),
            "next_state": operator_handoff.get("next_state"),
            "remaining_blocker_count": len(operator_handoff.get("remaining_blockers") or ()),
            "gate_count": len(operator_handoff.get("gates") or ()),
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
            "record_count": len(schema_validation.get("records") or ()),
        },
        "claim_variable_validation": {
            "accepted": claim_variable_validation.get("accepted"),
            "failure_count": claim_variable_validation.get("failure_count"),
            "record_count": len(claim_variable_validation.get("records") or ()),
        },
        "prompt_evolution": {
            "rendered_prompt_path": rendered_prompt.get("rendered_prompt_path"),
            "prompt_version": rendered_prompt.get("prompt_version"),
            "asset_validation_accepted": prompt_validation.get("accepted"),
            "asset_validation_failure_count": prompt_validation.get("failure_count"),
            "asset_validation_record_count": len(prompt_validation.get("records") or ()),
            "policy_doc_validation_accepted": policy_doc_validation.get("accepted"),
            "policy_doc_validation_failure_count": policy_doc_validation.get("failure_count"),
            "mutation_id": (mutation_patch.get("mutation") or {}).get("mutation_id"),
            "mutation_target_path": (mutation_patch.get("mutation") or {}).get("target_path"),
            "mutation_validation_accepted": (mutation_patch.get("validation") or {}).get("accepted"),
            "production_allowed": mutation_patch.get("production_allowed"),
        },
        "audit_trace": {
            "complete": audit_view.get("complete"),
            "node_count": audit_view.get("node_count"),
            "edge_count": audit_view.get("edge_count"),
            "missing_reference_count": len(audit_view.get("missing_references") or ()),
            "broken_edge_count": len(audit_view.get("broken_edges") or ()),
            "source_count": len(audit_trace.get("source_ids", ())),
            "claim_count": len(audit_trace.get("claim_ids", ())),
            "rule_count": len(audit_trace.get("rule_ids", ())),
            "experiment_count": len(audit_trace.get("experiment_ids", ())),
            "patch_count": len(audit_trace.get("patch_ids", ())),
            "agent_output_count": len(audit_trace.get("agent_output_ids", ())),
        },
        "runtime_progress": runtime.get("progress_event", {}),
        "runtime_recommendations": runtime.get("recommendations", ()),
    }


def render_dashboard_markdown(report: Mapping[str, Any]) -> str:
    completion = dict(report.get("completion") or {})
    paper = dict(report.get("paper_trading") or {})
    monitor = dict(report.get("production_monitor") or {})
    blockers = completion.get("blockers") or []
    lines = [
        "# RKE Dashboard",
        "",
        f"- Broad rollout ready: {str(report.get('ready_for_broad_rollout')).lower()}",
        f"- Completion: {completion.get('passed', 0)} / {completion.get('total', 0)}",
        f"- Master-plan coverage missing: {dict(report.get('master_plan_coverage') or {}).get('missing_count')}",
        f"- Master-plan coverage blocked: {dict(report.get('master_plan_coverage') or {}).get('blocked_count')}",
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
        f"- Next license review batch rows: {dict(dict(report.get('manual_review_gates') or {}).get('review_batches') or {}).get('source_license_exported_rows')}",
        f"- Operator handoff ready: {dict(report.get('operator_handoff') or {}).get('ready_for_operator_review')}",
        f"- Operator handoff blockers: {dict(report.get('operator_handoff') or {}).get('remaining_blocker_count')}",
        f"- Operator readiness accepted: {dict(report.get('operator_readiness') or {}).get('accepted')}",
        f"- Operator readiness failures: {dict(report.get('operator_readiness') or {}).get('failure_count')}",
        f"- Experiment governance family: {dict(report.get('experiment_governance') or {}).get('family_id')}",
        f"- Schema validation failures: {dict(report.get('schema_validation') or {}).get('failure_count')}",
        f"- Claim variable validation failures: {dict(report.get('claim_variable_validation') or {}).get('failure_count')}",
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
