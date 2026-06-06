from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_dashboard_report,
    render_dashboard_markdown,
    write_dashboard_reports,
)


def _source_row_count() -> int:
    return sum(
        1
        for line in Path("registry/sources/tushare_research_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )


def _source_text_count() -> int:
    payload = json.loads(
        Path("registry/compliance/source_text_redaction_report.json").read_text(
            encoding="utf-8"
        )
    )
    return int(payload["source_text_count"])


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def test_dashboard_report_summarizes_completion_and_monitoring():
    report = build_dashboard_report(".")
    source_row_count = _source_row_count()
    source_text_count = _source_text_count()

    assert report["dashboard_id"] == "RKE-DASHBOARD-20260605"
    assert report["artifact_errors"] == ()
    assert report["ready_for_broad_rollout"] is False
    assert report["completion"]["passed"] == 10
    assert report["completion"]["total"] == 12
    assert report["master_plan_coverage"]["coverage_complete"] is True
    assert report["master_plan_coverage"]["ready_for_broad_rollout"] is False
    assert report["master_plan_coverage"]["missing_count"] == 0
    assert report["master_plan_coverage"]["blocked_count"] == 2
    assert report["master_plan_coverage"]["blocked_sections"] == (
        "Phase-1B",
        "Compliance",
    )
    assert report["master_plan_coverage"]["mvp_deliverables"]["section"] == "16.3"
    assert report["master_plan_coverage"]["mvp_deliverables"]["blocked_count"] == 1
    assert report["master_plan_coverage"]["mvp_deliverables"]["blocked_sections"] == (
        "MVP-D2",
    )
    assert report["master_plan_coverage"]["mvp_exit_criteria"]["section"] == "16.4"
    assert report["master_plan_coverage"]["mvp_exit_criteria"]["blocked_count"] == 1
    assert report["master_plan_coverage"]["mvp_exit_criteria"]["blocked_sections"] == (
        "MVP-E01",
    )
    assert report["master_plan_coverage"]["final_acceptance"]["section"] == "22"
    assert report["master_plan_coverage"]["final_acceptance"]["blocked_count"] == 2
    assert report["master_plan_coverage"]["final_acceptance"]["blocked_sections"] == (
        "FinalAcceptance-C02",
        "FinalAcceptance-C11",
    )
    assert report["paper_trading"]["ready"] is True
    assert report["production_monitor_diagnostics"]["accepted"] is True
    assert report["production_monitor_diagnostics"]["scenario_count"] == 6
    assert report["production_monitor_diagnostics"]["failure_count"] == 0
    assert report["rollback_readiness"]["accepted"] is True
    assert report["rollback_readiness"]["check_count"] == 5
    assert report["rollback_readiness"]["failure_count"] == 0
    assert report["lockbox"]["result"] == "not_opened"
    assert report["lockbox"]["production_allowed"] is False
    assert report["promotion_gate"]["paper_trading_allowed"] is True
    assert report["promotion_gate"]["staged_production_allowed"] is False
    assert report["promotion_gate"]["production_allowed"] is False
    assert report["promotion_gate"]["next_state"] == "paper_trading"
    assert report["promotion_gate"]["blocker_count"] >= 3
    assert report["validation_hardening"]["ablation_accepted"] is True
    assert report["validation_hardening"]["horizon_metric_failures"] == []
    assert report["validation_hardening"]["statistical_significance_accepted"] is True
    assert report["validation_hardening"]["after_cost_ci_low"] > 0
    assert report["source_validation"]["accepted_for_sandbox"] is True
    assert report["source_validation"]["accepted_for_production"] is False
    assert report["source_validation"]["production_blocker_count"] == source_row_count
    assert report["source_text_redaction"]["accepted"] is True
    assert report["source_text_redaction"]["failure_count"] == 0
    assert report["source_text_redaction"]["source_text_count"] == source_text_count
    assert report["sector_demo"]["demo_status"] == "sandbox"
    assert report["sector_demo"]["production_allowed"] is False
    assert report["sector_demo"]["recommendation_actionability"] == "monitor_only"
    assert report["macro_expansion"]["candidate_count"] == 3
    assert report["macro_expansion"]["production_allowed"] is False
    assert report["layer_integration"]["sector_actionability"] == "monitor_only"
    assert report["layer_integration"]["decision_cash_floor"] == 0.05
    assert report["claim_variable_validation"]["accepted"] is True
    assert report["claim_variable_validation"]["failure_count"] == 0
    assert report["prompt_evolution"]["asset_validation_accepted"] is True
    assert report["prompt_evolution"]["asset_validation_failure_count"] == 0
    assert report["prompt_evolution"]["policy_doc_validation_accepted"] is True
    assert report["prompt_evolution"]["policy_doc_validation_failure_count"] == 0
    assert report["prompt_evolution"]["mutation_validation_accepted"] is True
    assert report["prompt_evolution"]["production_allowed"] is False
    assert (
        report["manual_review_gates"]["gold_review_packet"]["status"]
        == "manual_review_pending"
    )
    assert report["manual_review_gates"]["gold_review_packet"]["document_count"] == 50
    assert (
        report["manual_review_gates"]["gold_review_packet"]["candidate_span_ref_count"]
        > 0
    )
    assert (
        report["manual_review_gates"]["gold_candidate_claims"]["candidate_claim_count"]
        == 500
    )
    assert (
        report["manual_review_gates"]["gold_candidate_claims"][
            "review_rows_with_candidate_fields"
        ]
        == 500
    )
    assert (
        report["manual_review_gates"]["gold_candidate_claims"][
            "manual_fields_preserved"
        ]
        is True
    )
    assert (
        report["manual_review_gates"]["license_review_packet"]["status"]
        == "manual_review_pending"
    )
    assert (
        report["manual_review_gates"]["license_review_packet"]["source_count"]
        == source_row_count
    )
    assert (
        report["manual_review_gates"]["license_review_packet"][
            "approved_for_production_runtime"
        ]
        == 0
    )
    assert (
        report["manual_review_gates"]["review_batches"]["ready_for_manual_review"]
        is True
    )
    assert (
        report["manual_review_gates"]["review_batches"]["gold_set_pending_rows"] == 500
    )
    assert (
        report["manual_review_gates"]["review_batches"]["gold_set_exported_rows"] == 50
    )
    assert (
        report["manual_review_gates"]["review_batches"]["gold_set_full_import_template"]
        == "registry/review_batches/gold_set_full_import_template.jsonl"
    )
    assert (
        report["manual_review_gates"]["review_batches"]["gold_set_review_workbook"]
        == "registry/review_batches/gold_set_review_workbook.md"
    )
    assert (
        report["manual_review_gates"]["review_batches"]["source_license_pending_rows"]
        == source_row_count
    )
    assert (
        report["manual_review_gates"]["review_batches"]["source_license_exported_rows"]
        == 50
    )
    assert (
        report["manual_review_gates"]["review_batches"][
            "source_license_review_workbook"
        ]
        == "registry/review_batches/source_license_review_workbook.md"
    )
    assert (
        report["manual_review_gates"]["review_progress"]["ready_for_promotion_dry_run"]
        is False
    )
    assert report["manual_review_gates"]["review_progress"]["gate_count"] == 3
    assert report["manual_review_gates"]["review_progress"]["blocker_count"] >= 3
    assert (
        report["manual_review_gates"]["review_progress"]["runbook_path"]
        == "registry/review_batches/manual_review_runbook.md"
    )
    assert report["operator_handoff"]["ready_for_operator_review"] is True
    assert report["operator_handoff"]["next_state"] == "paper_trading"
    assert report["operator_handoff"]["remaining_blocker_count"] >= 3
    assert report["operator_handoff"]["gate_count"] == 3
    assert report["operator_readiness"]["accepted"] is True
    assert report["operator_readiness"]["check_count"] == 15
    assert report["operator_readiness"]["failure_count"] == 0
    assert report["audit_trace"]["complete"] is True
    assert report["audit_trace"]["node_count"] == 8
    assert report["audit_trace"]["edge_count"] >= 12
    assert report["audit_trace"]["missing_reference_count"] == 0
    assert report["audit_trace"]["broken_edge_count"] == 0
    assert report["audit_trace"]["agent_output_count"] == 1
    assert "manual" in " ".join(report["completion"]["blockers"])


def test_dashboard_report_surfaces_malformed_artifacts_without_crashing(tmp_path: Path):
    _copy_registry(tmp_path)
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    sector_runtime_path = (
        tmp_path / "registry/runtime_outputs/sector.semiconductor.demo.20260605.json"
    )
    runtime_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    sector_runtime = json.loads(sector_runtime_path.read_text(encoding="utf-8"))
    sector_runtime["recommendations"] = ["not an object"]
    sector_runtime_path.write_text(
        json.dumps(sector_runtime, ensure_ascii=False), encoding="utf-8"
    )

    report = build_dashboard_report(tmp_path)
    markdown = render_dashboard_markdown(report)

    assert not report["ready_for_broad_rollout"]
    assert report["runtime_progress"] == {}
    assert report["sector_demo"]["recommendation_actionability"] is None
    assert (
        "registry/runtime_outputs/macro.central_bank.20260605.json must be object"
        in report["artifact_errors"]
    )
    assert (
        "registry/runtime_outputs/sector.semiconductor.demo.20260605.json.recommendations[1] must be object"
        in report["artifact_errors"]
    )
    assert "Dashboard artifact errors: 2" in markdown


def test_dashboard_markdown_renders_blockers():
    markdown = render_dashboard_markdown(build_dashboard_report("."))
    source_row_count = _source_row_count()

    assert "# RKE Dashboard" in markdown
    assert "Broad rollout ready: false" in markdown
    assert "Dashboard artifact errors: 0" in markdown
    assert "Master-plan coverage missing: 0" in markdown
    assert "Master-plan coverage blocked: 2" in markdown
    assert "Master-plan blocked sections: Phase-1B, Compliance" in markdown
    assert "MVP deliverables blocked: 1" in markdown
    assert "MVP deliverable blocked sections: MVP-D2" in markdown
    assert "MVP exit criteria blocked: 1" in markdown
    assert "MVP exit blocked sections: MVP-E01" in markdown
    assert "Final acceptance blocked: 2" in markdown
    assert (
        "Final acceptance blocked sections: FinalAcceptance-C02, FinalAcceptance-C11"
        in markdown
    )
    assert "Promotion next state: paper_trading" in markdown
    assert "Promotion production allowed: False" in markdown
    assert "Validation ablations accepted: True" in markdown
    assert "Validation statistical significance accepted: True" in markdown
    assert "Source validation sandbox accepted: True" in markdown
    assert f"Source validation production blockers: {source_row_count}" in markdown
    assert "Production monitor diagnostics accepted: True" in markdown
    assert "Production monitor diagnostic failures: 0" in markdown
    assert "Rollback readiness accepted: True" in markdown
    assert "Rollback readiness failures: 0" in markdown
    assert "Source text redaction accepted: True" in markdown
    assert "Source text redaction failures: 0" in markdown
    assert "Sector demo: sandbox" in markdown
    assert "Macro expansion candidates: 3" in markdown
    assert "Phase 7 sector actionability: monitor_only" in markdown
    assert "Gold review packet spans:" in markdown
    assert "Gold candidate claims: 500" in markdown
    assert "License review packet pending sources:" in markdown
    assert "Next gold review batch rows: 50" in markdown
    assert (
        "Full gold review import template: registry/review_batches/gold_set_full_import_template.jsonl"
        in markdown
    )
    assert (
        "Gold review workbook: registry/review_batches/gold_set_review_workbook.md"
        in markdown
    )
    assert "Next license review batch rows: 50" in markdown
    assert (
        "Source license review workbook: registry/review_batches/source_license_review_workbook.md"
        in markdown
    )
    assert "Manual review promotion dry-run ready: False" in markdown
    assert "Manual review progress blockers:" in markdown
    assert (
        "Manual review runbook: registry/review_batches/manual_review_runbook.md"
        in markdown
    )
    assert "Operator handoff ready: True" in markdown
    assert "Operator handoff blockers:" in markdown
    assert "Operator readiness accepted: True" in markdown
    assert "Operator readiness failures: 0" in markdown
    assert "Claim variable validation failures: 0" in markdown
    assert "Prompt asset validation failures: 0" in markdown
    assert "Policy doc validation failures: 0" in markdown
    assert "Prompt mutation validation accepted: True" in markdown
    assert "Audit trace complete: True" in markdown
    assert "Audit trace edges:" in markdown
    assert "manual" in markdown
    assert "license" in markdown


def test_dashboard_report_writer_outputs_json_and_markdown():
    # Reuse current repo registry by validating writer on the repository root.
    paths = write_dashboard_reports(".")
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["completion"]["total"] == 12
    assert markdown.startswith("# RKE Dashboard")
