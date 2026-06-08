from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from mosaic.rke import (
    audit_master_plan_completion,
    load_jsonl,
    write_central_bank_mvp_registry,
    write_completion_audit,
    write_gold_set_review_template,
    write_source_license_review_template,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _completed_gold_review_rows(path: Path) -> list[dict]:
    rows = _read_jsonl(path)
    for row in rows:
        row.update(
            {
                "manual_claim_text": row.get("proposed_claim_text") or "manual claim",
                "claim_correct": True,
                "source_span_supports_claim": True,
                "direction_correct": True,
                "variable_mapping_correct": True,
                "unsupported_field_false_grounded": False,
                "reviewer": "reviewer-a",
                "review_date": "2026-06-06",
                "review_notes": "fixture approval",
            }
        )
    return rows


def _completed_license_review_rows(path: Path) -> list[dict]:
    rows = _read_jsonl(path)
    for row in rows:
        row.update(
            {
                "approved_for_derived_claim_storage": True,
                "approved_for_production_runtime": True,
                "reviewer": "compliance",
                "review_date": "2026-06-06",
                "notes": "fixture approval",
            }
        )
    return rows


def test_completion_auditor_recomputes_current_registry_gates():
    audit = audit_master_plan_completion(".")
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert len(audit.criteria) == 12
    assert audit.ready_for_broad_rollout
    assert by_id["C01"].passed
    assert "paper trading ready" in by_id["C01"].evidence
    assert by_id["C04"].passed
    assert "hardening/statistical" in by_id["C04"].evidence
    assert by_id["C05"].passed
    assert "runtime checker accepted aggregation summary" in by_id["C05"].evidence
    assert by_id["C09"].passed
    assert "paper summary recomputed" in by_id["C09"].evidence
    assert by_id["C10"].passed
    assert (
        "6 diagnostic scenarios + 5 rollback readiness checks" in by_id["C10"].evidence
    )
    assert by_id["C12"].passed
    assert by_id["C02"].passed
    assert by_id["C11"].passed
    assert "manual gold-set review passed" in by_id["C02"].evidence
    assert "sources approved for production runtime" in by_id["C11"].evidence


def test_completion_auditor_requires_statistical_significance_gate(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    statistical_path = (
        tmp_path
        / "registry/evaluation/statistical_significance/central_bank_after_cost_significance.json"
    )
    statistical = json.loads(statistical_path.read_text(encoding="utf-8"))
    statistical["confidence_interval"]["low"] = -0.001
    statistical["accepted"] = False
    statistical_path.write_text(
        json.dumps(statistical, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C04"].passed
    assert "confidence interval includes zero" in by_id["C04"].blocker


def test_completion_auditor_requires_rule_pack_data_proxy_coverage(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    data_path = (
        tmp_path / "registry/data_availability/central_bank_data_availability.json"
    )
    data_matrix = json.loads(data_path.read_text(encoding="utf-8"))
    data_matrix["proxies"].pop("risk_appetite_proxy")
    data_path.write_text(
        json.dumps(data_matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C03"].passed
    assert (
        "data availability proxy missing or malformed: risk_appetite_proxy"
        in by_id["C03"].blocker
    )


def test_completion_auditor_requires_production_eligible_data_proxy(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    data_path = (
        tmp_path / "registry/data_availability/central_bank_data_availability.json"
    )
    data_matrix = json.loads(data_path.read_text(encoding="utf-8"))
    data_matrix["proxies"]["pboc_net_injection_7d"]["allowed_for_production"] = False
    data_matrix["proxies"]["pboc_net_injection_7d"]["point_in_time_available"] = False
    data_path.write_text(
        json.dumps(data_matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C03"].passed
    assert (
        "pboc_net_injection_7d.allowed_for_production must be true"
        in by_id["C03"].blocker
    )
    assert (
        "pboc_net_injection_7d.point_in_time_available must be true"
        in by_id["C03"].blocker
    )


def test_completion_auditor_requires_data_proxy_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    data_path = (
        tmp_path / "registry/data_availability/central_bank_data_availability.json"
    )
    data_matrix = json.loads(data_path.read_text(encoding="utf-8"))
    data_matrix["proxies"]["risk_appetite_proxy"].pop("history_start")
    data_matrix["proxies"]["risk_appetite_proxy"]["known_biases"] = "low"
    data_path.write_text(
        json.dumps(data_matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C03"].passed
    assert "risk_appetite_proxy.history_start missing" in by_id["C03"].blocker
    assert "risk_appetite_proxy.history_start must be non-empty" in by_id["C03"].blocker
    assert (
        "risk_appetite_proxy.known_biases must be list when present"
        in by_id["C03"].blocker
    )


def test_completion_auditor_rejects_non_object_gold_review_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    review_path.write_text(
        review_path.read_text(encoding="utf-8")
        + json.dumps(["not", "an", "object"])
        + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert len(audit.criteria) == 12
    assert not by_id["C02"].passed
    assert "gold-set review row must be object" in by_id["C02"].blocker


def test_completion_auditor_rejects_invalid_json_gold_review_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    expected_row = len(review_path.read_text(encoding="utf-8").splitlines()) + 1
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert len(audit.criteria) == 12
    assert not by_id["C02"].passed
    assert (
        f"gold-set review row {expected_row} must contain valid JSON"
        in by_id["C02"].blocker
    )


def test_completion_auditor_rejects_non_boolean_gold_review_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = _completed_gold_review_rows(review_path)
    rows[0]["claim_correct"] = "yes"
    _write_jsonl(review_path, rows)

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C02"].passed
    assert "gold-set review row 1 claim_correct must be boolean" in by_id["C02"].blocker


def test_completion_auditor_requires_gold_review_provenance(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = _completed_gold_review_rows(review_path)
    rows[0]["reviewer"] = ""
    rows[1]["review_date"] = "20260606"
    rows[2]["manual_claim_text"] = ""
    _write_jsonl(review_path, rows)

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C02"].passed
    assert "gold-set review row 1 reviewer required" in by_id["C02"].blocker
    assert (
        "gold-set review row 2 review_date must be YYYY-MM-DD" in by_id["C02"].blocker
    )
    assert "gold-set review row 3 manual_claim_text required" in by_id["C02"].blocker


def test_completion_auditor_rejects_duplicate_gold_claim_ids(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = _read_jsonl(review_path)
    rows[1]["claim_id"] = rows[0]["claim_id"]
    _write_jsonl(review_path, rows)

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C02"].passed
    assert "gold-set review claim_id duplicated" in by_id["C02"].blocker


def test_completion_auditor_rejects_non_object_license_review_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert len(audit.criteria) == 12
    assert not by_id["C11"].passed
    assert "source license review row must be object" in by_id["C11"].blocker


def test_completion_auditor_rejects_invalid_json_source_registry_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    expected_row = len(source_path.read_text(encoding="utf-8").splitlines()) + 1
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert len(audit.criteria) == 12
    assert not by_id["C11"].passed
    assert (
        f"source registry row {expected_row} must contain valid JSON"
        in by_id["C11"].blocker
    )


def test_completion_auditor_requires_license_review_provenance(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    rows = _completed_license_review_rows(review_path)
    rows[0]["reviewer"] = ""
    rows[1]["review_date"] = "20260606"
    _write_jsonl(review_path, rows)

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C11"].passed
    assert "source license review row 1 reviewer required" in by_id["C11"].blocker
    assert (
        "source license review row 2 review_date must be YYYY-MM-DD"
        in by_id["C11"].blocker
    )


def test_completion_auditor_rejects_license_review_identity_mismatch(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    rows = _read_jsonl(review_path)
    rows.append(dict(rows[0]))
    rows.append(dict(rows[0], source_id="SRC-UNKNOWN"))
    _write_jsonl(review_path, rows)

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C11"].passed
    assert "source license review source_id duplicated" in by_id["C11"].blocker
    assert (
        "source license review rows reference unknown source_id" in by_id["C11"].blocker
    )


def test_completion_auditor_rejects_inconsistent_license_approval(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    rows = _completed_license_review_rows(review_path)
    rows[0]["approved_for_derived_claim_storage"] = False
    rows[1]["approved_for_production_runtime"] = "true"
    rows[2]["approved_for_derived_claim_storage"] = None
    _write_jsonl(review_path, rows)

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C11"].passed
    assert (
        "source license review row 1 production approval requires derived-claim approval"
        in by_id["C11"].blocker
    )
    assert (
        "source license review row 2 approved_for_production_runtime must be boolean"
        in by_id["C11"].blocker
    )
    assert (
        "source license review row 3 approved_for_derived_claim_storage required"
        in by_id["C11"].blocker
    )


def test_completion_auditor_rejects_malformed_paper_report(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert not by_id["C09"].passed
    assert by_id["C10"].passed
    assert "paper trading report must be object" in by_id["C01"].blocker
    assert "paper trading report must be object" in by_id["C09"].blocker


def test_completion_auditor_rejects_invalid_json_paper_report(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper_path.write_text("{", encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert not by_id["C09"].passed
    assert by_id["C10"].passed
    assert "paper trading report must contain valid JSON" in by_id["C01"].blocker
    assert "paper trading report must contain valid JSON" in by_id["C09"].blocker


def test_completion_auditor_recomputes_paper_summary_from_snapshots(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    paper["paper_trading_summary"]["mean_live_vs_baseline_delta"] = 0.99
    paper_path.write_text(
        json.dumps(paper, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert not by_id["C09"].passed
    assert "must equal recomputed snapshot mean" in by_id["C09"].blocker


def test_completion_auditor_requires_positive_paper_after_cost_alpha(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    for snapshot in paper["paper_trading_report"]["snapshots"]:
        snapshot["live_net_alpha_after_cost"] = -0.004
    paper["paper_trading_summary"]["mean_live_net_alpha_after_cost"] = -0.004
    paper_path.write_text(
        json.dumps(paper, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert by_id["C09"].passed
    assert "mean_live_net_alpha_after_cost must be positive" in by_id["C01"].blocker


def test_completion_auditor_requires_clean_paper_production_monitor(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    paper["production_monitor"]["state"] = "rollback_required"
    paper["production_monitor"]["action"] = "rollback"
    paper_path.write_text(
        json.dumps(paper, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert "production_monitor.state must be production" in by_id["C01"].blocker
    assert "production_monitor.action must be none" in by_id["C01"].blocker


def test_completion_auditor_rejects_false_paper_ready_flag(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    paper["paper_trading_summary"]["ready"] = False
    paper_path.write_text(
        json.dumps(paper, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert by_id["C09"].passed
    assert "paper_trading_summary.ready must be true" in by_id["C01"].blocker


def test_completion_auditor_requires_monitor_diagnostic_scenarios(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    diagnostics_path = (
        tmp_path / "registry/monitoring/central_bank_monitoring_diagnostics.json"
    )
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    for scenario in diagnostics["scenarios"]:
        if scenario["scenario_id"] == "calibration_drift":
            scenario["result"]["state"] = "production"
            scenario["result"]["action"] = "none"
            scenario["result"]["reasons"] = []
            break
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C10"].passed
    assert (
        "calibration_drift.result.state must be monitored_decay" in by_id["C10"].blocker
    )
    assert "calibration_drift.result.reasons missing" in by_id["C10"].blocker


def test_completion_auditor_requires_all_monitor_diagnostic_scenarios(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    diagnostics_path = (
        tmp_path / "registry/monitoring/central_bank_monitoring_diagnostics.json"
    )
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    diagnostics["scenarios"] = [
        scenario
        for scenario in diagnostics["scenarios"]
        if scenario["scenario_id"] != "alpha_decay"
    ]
    diagnostics["scenario_count"] = len(diagnostics["scenarios"])
    diagnostics["passed_count"] = len(diagnostics["scenarios"])
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C10"].passed
    assert (
        "production monitor diagnostics scenario_count mismatch" in by_id["C10"].blocker
    )
    assert "alpha_decay" in by_id["C10"].blocker


def test_completion_auditor_requires_rollback_readiness_checks(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    rollback_path = (
        tmp_path / "registry/monitoring/central_bank_rollback_readiness_report.json"
    )
    rollback = json.loads(rollback_path.read_text(encoding="utf-8"))
    for check in rollback["checks"]:
        if check["check_id"] == "hard_rollback_negative_alpha":
            check["passed"] = False
            check["action"] = "none"
            check["blocker"] = "unit-test blocker"
            break
    rollback["accepted"] = False
    rollback["failure_count"] = 1
    rollback_path.write_text(
        json.dumps(rollback, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C10"].passed
    assert "rollback readiness accepted must be true" in by_id["C10"].blocker
    assert "hard_rollback_negative_alpha.passed must be true" in by_id["C10"].blocker
    assert (
        "hard_rollback_negative_alpha.action must be rollback" in by_id["C10"].blocker
    )


def test_completion_auditor_rejects_malformed_runtime_output(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C05"].passed
    assert not by_id["C06"].passed
    assert "runtime output must be object" in by_id["C05"].blocker
    assert "runtime output must be object" in by_id["C06"].blocker


def test_completion_auditor_rejects_invalid_json_runtime_output(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime_path.write_text("{", encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C05"].passed
    assert not by_id["C06"].passed
    assert "runtime output must contain valid JSON" in by_id["C05"].blocker
    assert "runtime output must contain valid JSON" in by_id["C06"].blocker


def test_completion_auditor_requires_runtime_conflict_objects(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["rule_aggregation_summary"]["has_opposing_rules"] = True
    runtime["rule_aggregation_summary"].pop("conflict_objects", None)
    runtime_path.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C05"].passed
    assert "opposing rules require conflict_objects" in by_id["C05"].blocker


def test_completion_auditor_requires_runtime_dedup_groups(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["rule_aggregation_summary"]["correlated_rule_duplicate_count"] = 2
    runtime["rule_aggregation_summary"].pop("deduped_rule_groups", None)
    runtime_path.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C05"].passed
    assert (
        "correlated rule duplicates require deduped_rule_groups" in by_id["C05"].blocker
    )


def test_completion_auditor_rejects_aggregation_cap_violation(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["rule_aggregation_summary"]["group_deltas"][
        "macro.central_bank.liquidity"
    ] = 0.11
    runtime["rule_aggregation_summary"]["final_research_delta"] = 0.11
    runtime_path.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C05"].passed
    assert "exceeds rule_group_max_adjustment" in by_id["C05"].blocker


def test_completion_auditor_requires_confidence_policy_trace(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime.pop("confidence_policy_trace", None)
    runtime_path.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C06"].passed
    assert "confidence_policy_trace missing" in by_id["C06"].blocker


def test_completion_auditor_rejects_non_conservative_confidence_trace(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["confidence_policy_trace"]["final_confidence"] = 0.66
    runtime["recommendations"][0]["confidence"] = 0.66
    runtime["progress_event"]["confidence"] = 0.66
    runtime_path.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C06"].passed
    assert (
        "final_confidence must equal min(pre_cap, confidence_cap)"
        in by_id["C06"].blocker
    )


def test_completion_auditor_rejects_research_only_actionability(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    sector_path = (
        tmp_path / "registry/runtime_outputs/sector.semiconductor.demo.20260605.json"
    )
    sector = json.loads(sector_path.read_text(encoding="utf-8"))
    sector["recommendations"][0]["actionability"] = "modest_tilt"
    sector["recommendations"][0]["confidence"] = 0.62
    sector_path.write_text(
        json.dumps(sector, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C07"].passed
    assert "actionability must be no_trade or monitor_only" in by_id["C07"].blocker
    assert "confidence must be <= 0.50" in by_id["C07"].blocker


def test_completion_auditor_replays_patch_validator(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    patch_path = tmp_path / "registry/patches/central_bank_paper_trading_patch.json"
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    patch["old_value"] = 999
    patch_path.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C08"].passed
    assert "old_value does not match current registry" in by_id["C08"].blocker


def test_completion_auditor_rejects_forbidden_patch_target_path(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    patch_path = tmp_path / "registry/patches/central_bank_paper_trading_patch.json"
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    patch["target_path"] = "/output_schema_ref"
    patch_path.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C08"].passed
    assert "target_path" in by_id["C08"].blocker


def test_completion_auditor_rejects_patch_experiment_mismatch(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    patch_path = tmp_path / "registry/patches/central_bank_paper_trading_patch.json"
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    patch["source_experiment_id"] = "EXP-UNKNOWN"
    patch_path.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C08"].passed
    assert (
        "source_experiment_id must match validation experiment" in by_id["C08"].blocker
    )


def test_completion_auditor_rejects_malformed_validation_experiment(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    experiment_path = (
        tmp_path / "registry/experiments/central_bank_validation_experiment_v2.json"
    )
    experiment_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C04"].passed
    assert by_id["C04"].evidence == "validation experiment malformed"
    assert "validation experiment must be object" in by_id["C04"].blocker


def test_completion_auditor_rejects_invalid_json_validation_experiment(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    experiment_path = (
        tmp_path / "registry/experiments/central_bank_validation_experiment_v2.json"
    )
    experiment_path.write_text("{", encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C04"].passed
    assert by_id["C04"].evidence == "validation experiment malformed"
    assert "validation experiment must contain valid JSON" in by_id["C04"].blocker


def test_completion_auditor_requires_audit_trace_parameter_chain(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    trace_path = tmp_path / "registry/audits/central_bank_mvp_audit_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["parameter_paths"] = []
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C12"].passed
    assert "audit trace missing node types" in by_id["C12"].blocker
    assert "parameter_path" in by_id["C12"].blocker
    assert "rule -> parameter" in by_id["C12"].blocker


def test_completion_auditor_requires_audit_trace_agent_output_rule_edge(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    runtime_path = (
        tmp_path / "registry/runtime_outputs/macro.central_bank.20260605.json"
    )
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["research_rule_ids_used"] = []
    runtime_path.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C12"].passed
    assert "agent_output" in by_id["C12"].blocker
    assert "rule output" in by_id["C12"].blocker
    assert "rule -> agent output" in by_id["C12"].blocker


def test_completion_auditor_writes_registry_file(tmp_path: Path):
    write_central_bank_mvp_registry(tmp_path)
    gold_candidates = load_jsonl(
        "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    )
    source_rows = load_jsonl("registry/sources/tushare_research_reports.jsonl")
    write_gold_set_review_template(
        gold_candidates,
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl",
        claims_per_document=10,
    )
    write_source_license_review_template(
        source_rows,
        tmp_path / "registry/compliance/tushare_license_review_template.jsonl",
    )

    result = write_completion_audit(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["ready_for_broad_rollout"] is False
    assert payload["report_id"] == "RKE-COMPLETION-AUDIT-20260606"
    assert payload["master_plan_path"] == "docs/master_plan_v1_1.md"
    assert payload["acceptance_section"] == "22"
    assert payload["acceptance_criteria_count"] == 12
    assert [item["criterion_id"] for item in payload["acceptance_requirements"]] == [
        f"C{index:02d}" for index in range(1, 13)
    ]
    passed_count = sum(1 for item in payload["criteria"] if item["passed"])
    assert payload["passed_count"] == passed_count
    assert payload["blocked_count"] == len(payload["criteria"]) - passed_count
    assert len(payload["criteria"]) == 12
    assert {item["criterion_id"] for item in payload["criteria"]} >= {"C02", "C11"}


def test_completion_auditor_serializes_as_current_registry_format():
    audit = audit_master_plan_completion(".")
    payload = asdict(audit)

    assert "criteria" in payload
    assert payload["criteria"][0]["criterion_id"] == "C01"
