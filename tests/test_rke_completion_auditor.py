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


def test_completion_auditor_recomputes_current_registry_gates():
    audit = audit_master_plan_completion(".")
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert len(audit.criteria) == 12
    assert not audit.ready_for_broad_rollout
    assert by_id["C01"].passed
    assert by_id["C04"].passed
    assert "hardening/statistical" in by_id["C04"].evidence
    assert by_id["C10"].passed
    assert "6 diagnostic scenarios" in by_id["C10"].evidence
    assert by_id["C12"].passed
    assert not by_id["C02"].passed
    assert not by_id["C11"].passed
    assert "gold-set" in by_id["C02"].evidence
    assert "license review" in by_id["C11"].blocker


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


def test_completion_auditor_rejects_malformed_paper_report(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert not by_id["C09"].passed
    assert not by_id["C10"].passed
    assert "paper trading report must be object" in by_id["C01"].blocker
    assert "paper trading report must be object" in by_id["C09"].blocker
    assert "paper trading report must be object" in by_id["C10"].blocker


def test_completion_auditor_rejects_invalid_json_paper_report(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    paper_path = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    paper_path.write_text("{", encoding="utf-8")

    audit = audit_master_plan_completion(tmp_path)
    by_id = {criterion.criterion_id: criterion for criterion in audit.criteria}

    assert not by_id["C01"].passed
    assert not by_id["C09"].passed
    assert not by_id["C10"].passed
    assert "paper trading report must contain valid JSON" in by_id["C01"].blocker
    assert "paper trading report must contain valid JSON" in by_id["C09"].blocker
    assert "paper trading report must contain valid JSON" in by_id["C10"].blocker


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
