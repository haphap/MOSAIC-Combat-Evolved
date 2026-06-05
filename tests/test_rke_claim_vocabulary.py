from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_claim_variable_validation_report,
    build_default_claim_variable_vocabulary,
    write_claim_variable_validation_report,
    write_claim_variable_vocabulary,
)


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def test_default_claim_variable_vocabulary_contains_current_claim_variables():
    vocabulary = build_default_claim_variable_vocabulary()
    variable_ids = {item.variable_id for item in vocabulary.variables}

    assert {
        "pboc_net_injection",
        "short_term_liquidity_pressure",
        "ai_compute_demand",
        "semiconductor_storage_cycle",
        "valuation_percentile",
        "forward_alpha_after_policy_catalyst",
        "trade_friction_intensity",
        "semiconductor_policy_substitution_alpha",
    } <= variable_ids


def test_claim_variable_validation_accepts_repo_artifacts():
    report = build_claim_variable_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert {record.check_id for record in report.records} == {
        "CLAIM-VOCABULARY-SCHEMA",
        "CLAIM-VARIABLE-MAPPING",
    }


def test_claim_variable_validation_rejects_unknown_variable(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    claim_path = tmp_path / "registry/claims/central_bank_claims.jsonl"
    row = json.loads(claim_path.read_text(encoding="utf-8").splitlines()[0])
    row["cause_variables"] = ["ad_hoc_variable"]
    claim_path.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    report = build_claim_variable_validation_report(tmp_path)
    mapping = next(record for record in report.records if record.check_id == "CLAIM-VARIABLE-MAPPING")

    assert not report.accepted
    assert not mapping.accepted
    assert any("unknown variable" in failure for failure in mapping.failures)


def test_claim_variable_validation_rejects_character_leakage(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    claim_path = tmp_path / "registry/claims/semiconductor_claims.jsonl"
    rows = [json.loads(line) for line in claim_path.read_text(encoding="utf-8").splitlines()]
    rows[-1]["target_variables"] = list("alpha")
    claim_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    report = build_claim_variable_validation_report(tmp_path)
    mapping = next(record for record in report.records if record.check_id == "CLAIM-VARIABLE-MAPPING")

    assert not report.accepted
    assert any("character leakage" in failure for failure in mapping.failures)


def test_claim_variable_validation_writer_outputs_report(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    write_claim_variable_vocabulary(tmp_path)

    result = write_claim_variable_validation_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert len(payload["records"]) == 2
