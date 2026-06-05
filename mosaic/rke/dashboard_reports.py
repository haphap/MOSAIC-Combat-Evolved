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
        f"- Sector demo: {dict(report.get('sector_demo') or {}).get('demo_status')}",
        f"- Macro expansion candidates: {dict(report.get('macro_expansion') or {}).get('candidate_count')}",
        f"- Phase 7 sector actionability: {dict(report.get('layer_integration') or {}).get('sector_actionability')}",
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
