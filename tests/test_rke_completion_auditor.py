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


def test_completion_auditor_writes_registry_file(tmp_path: Path):
    write_central_bank_mvp_registry(tmp_path)
    gold_candidates = load_jsonl("registry/sources/tushare_research_reports.gold_candidates.jsonl")
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
    assert len(payload["criteria"]) == 12
    assert {item["criterion_id"] for item in payload["criteria"]} >= {"C02", "C11"}


def test_completion_auditor_serializes_as_current_registry_format():
    audit = audit_master_plan_completion(".")
    payload = asdict(audit)

    assert "criteria" in payload
    assert payload["criteria"][0]["criterion_id"] == "C01"
