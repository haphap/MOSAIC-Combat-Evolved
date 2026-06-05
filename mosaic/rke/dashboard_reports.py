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
    paper = _read_json(root_path / "registry/monitoring/central_bank_paper_trading_report.json")
    audit_trace = _read_json(root_path / "registry/audits/central_bank_mvp_audit_trace.json")
    runtime = _read_json(root_path / "registry/runtime_outputs/macro.central_bank.20260605.json")
    lockbox_path = root_path / "registry/lockbox/central_bank_lockbox_review.json"
    lockbox = _read_json(lockbox_path) if lockbox_path.exists() else {}
    hardening_path = root_path / "registry/validation_hardening/central_bank_hardening_report.json"
    hardening = _read_json(hardening_path) if hardening_path.exists() else {}
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
    license_review_path = root_path / "registry/compliance/tushare_license_review_summary.json"
    gold_review = _read_json(gold_review_path) if gold_review_path.exists() else {}
    license_review = _read_json(license_review_path) if license_review_path.exists() else {}
    family_path = root_path / "registry/evaluation/experiment_family_registry/central_bank_liquidity_family.json"
    cost_model_path = root_path / "registry/evaluation/cost_model/cost_model_v1.json"
    overlap_path = root_path / "registry/evaluation/overlap_correction/effective_n_overlap_policy.json"
    lockbox_policy_path = root_path / "registry/evaluation/lockbox/lockbox_policy.json"
    schema_validation_path = root_path / "registry/schemas/rke_schema_validation_report.json"
    claim_variable_validation_path = root_path / "registry/claim_checks/claim_variable_validation_report.json"
    prompt_validation_path = root_path / "registry/prompt_checks/prompt_asset_validation_report.json"
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
        "paper_trading": paper.get("paper_trading_summary", {}),
        "production_monitor": paper.get("production_monitor", {}),
        "lockbox": {
            "result": lockbox.get("result"),
            "open_count": lockbox.get("open_count"),
            "production_allowed": lockbox.get("result") == "passed"
            and int(lockbox.get("open_count") or 0) <= 1,
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
            "source_license": {
                "reviewed_sources": license_review.get("reviewed_sources"),
                "total_sources": license_review.get("total_sources"),
                "pending_sources": license_review.get("pending_sources"),
                "approved_for_production_runtime": license_review.get(
                    "approved_for_production_runtime"
                ),
                "passed": license_review.get("passed"),
            },
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
            "mutation_id": (mutation_patch.get("mutation") or {}).get("mutation_id"),
            "mutation_target_path": (mutation_patch.get("mutation") or {}).get("target_path"),
            "mutation_validation_accepted": (mutation_patch.get("validation") or {}).get("accepted"),
            "production_allowed": mutation_patch.get("production_allowed"),
        },
        "audit_trace": {
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
        f"- Paper trading ready: {str(paper.get('ready')).lower()}",
        f"- Mean live vs baseline delta: {paper.get('mean_live_vs_baseline_delta')}",
        f"- Production monitor state: {monitor.get('state')}",
        f"- Production monitor action: {monitor.get('action')}",
        f"- Lockbox result: {dict(report.get('lockbox') or {}).get('result')}",
        f"- Validation ablations accepted: {dict(report.get('validation_hardening') or {}).get('ablation_accepted')}",
        f"- Validation statistical significance accepted: {dict(report.get('validation_hardening') or {}).get('statistical_significance_accepted')}",
        f"- Sector demo: {dict(report.get('sector_demo') or {}).get('demo_status')}",
        f"- Macro expansion candidates: {dict(report.get('macro_expansion') or {}).get('candidate_count')}",
        f"- Phase 7 sector actionability: {dict(report.get('layer_integration') or {}).get('sector_actionability')}",
        f"- Gold-set review pending claims: {dict(dict(report.get('manual_review_gates') or {}).get('gold_set') or {}).get('pending_claims')}",
        f"- License review pending sources: {dict(dict(report.get('manual_review_gates') or {}).get('source_license') or {}).get('pending_sources')}",
        f"- Experiment governance family: {dict(report.get('experiment_governance') or {}).get('family_id')}",
        f"- Schema validation failures: {dict(report.get('schema_validation') or {}).get('failure_count')}",
        f"- Claim variable validation failures: {dict(report.get('claim_variable_validation') or {}).get('failure_count')}",
        f"- Prompt asset validation failures: {dict(report.get('prompt_evolution') or {}).get('asset_validation_failure_count')}",
        f"- Prompt mutation validation accepted: {dict(report.get('prompt_evolution') or {}).get('mutation_validation_accepted')}",
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
