from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_dashboard_report,
    render_dashboard_markdown,
    write_dashboard_reports,
)


def test_dashboard_report_summarizes_completion_and_monitoring():
    report = build_dashboard_report(".")

    assert report["dashboard_id"] == "RKE-DASHBOARD-20260605"
    assert report["ready_for_broad_rollout"] is False
    assert report["completion"]["passed"] == 10
    assert report["completion"]["total"] == 12
    assert report["master_plan_coverage"]["coverage_complete"] is True
    assert report["master_plan_coverage"]["ready_for_broad_rollout"] is False
    assert report["master_plan_coverage"]["missing_count"] == 0
    assert report["master_plan_coverage"]["blocked_count"] == 2
    assert report["paper_trading"]["ready"] is True
    assert report["lockbox"]["result"] == "not_opened"
    assert report["lockbox"]["production_allowed"] is False
    assert report["validation_hardening"]["ablation_accepted"] is True
    assert report["validation_hardening"]["horizon_metric_failures"] == []
    assert report["validation_hardening"]["statistical_significance_accepted"] is True
    assert report["validation_hardening"]["after_cost_ci_low"] > 0
    assert report["source_validation"]["accepted_for_sandbox"] is True
    assert report["source_validation"]["accepted_for_production"] is False
    assert report["source_validation"]["production_blocker_count"] == 207
    assert report["source_text_redaction"]["accepted"] is True
    assert report["source_text_redaction"]["failure_count"] == 0
    assert report["source_text_redaction"]["source_text_count"] == 207
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
    assert report["manual_review_gates"]["gold_review_packet"]["status"] == "manual_review_pending"
    assert report["manual_review_gates"]["gold_review_packet"]["document_count"] == 50
    assert report["manual_review_gates"]["gold_review_packet"]["candidate_span_ref_count"] > 0
    assert report["manual_review_gates"]["gold_candidate_claims"]["candidate_claim_count"] == 500
    assert report["manual_review_gates"]["gold_candidate_claims"]["review_rows_with_candidate_fields"] == 500
    assert report["manual_review_gates"]["gold_candidate_claims"]["manual_fields_preserved"] is True
    assert report["manual_review_gates"]["license_review_packet"]["status"] == "manual_review_pending"
    assert report["manual_review_gates"]["license_review_packet"]["source_count"] == 207
    assert report["manual_review_gates"]["license_review_packet"]["approved_for_production_runtime"] == 0
    assert report["manual_review_gates"]["review_batches"]["ready_for_manual_review"] is True
    assert report["manual_review_gates"]["review_batches"]["gold_set_pending_rows"] == 500
    assert report["manual_review_gates"]["review_batches"]["gold_set_exported_rows"] == 50
    assert report["manual_review_gates"]["review_batches"]["source_license_pending_rows"] == 207
    assert report["manual_review_gates"]["review_batches"]["source_license_exported_rows"] == 50
    assert report["audit_trace"]["agent_output_count"] == 1
    assert "manual" in " ".join(report["completion"]["blockers"])


def test_dashboard_markdown_renders_blockers():
    markdown = render_dashboard_markdown(build_dashboard_report("."))

    assert "# RKE Dashboard" in markdown
    assert "Broad rollout ready: false" in markdown
    assert "Master-plan coverage missing: 0" in markdown
    assert "Master-plan coverage blocked: 2" in markdown
    assert "Validation ablations accepted: True" in markdown
    assert "Validation statistical significance accepted: True" in markdown
    assert "Source validation sandbox accepted: True" in markdown
    assert "Source validation production blockers: 207" in markdown
    assert "Source text redaction accepted: True" in markdown
    assert "Source text redaction failures: 0" in markdown
    assert "Sector demo: sandbox" in markdown
    assert "Macro expansion candidates: 3" in markdown
    assert "Phase 7 sector actionability: monitor_only" in markdown
    assert "Gold review packet spans:" in markdown
    assert "Gold candidate claims: 500" in markdown
    assert "License review packet pending sources:" in markdown
    assert "Next gold review batch rows: 50" in markdown
    assert "Next license review batch rows: 50" in markdown
    assert "Claim variable validation failures: 0" in markdown
    assert "Prompt asset validation failures: 0" in markdown
    assert "Policy doc validation failures: 0" in markdown
    assert "Prompt mutation validation accepted: True" in markdown
    assert "manual" in markdown
    assert "license" in markdown


def test_dashboard_report_writer_outputs_json_and_markdown():
    # Reuse current repo registry by validating writer on the repository root.
    paths = write_dashboard_reports(".")
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")

    assert payload["completion"]["total"] == 12
    assert markdown.startswith("# RKE Dashboard")
