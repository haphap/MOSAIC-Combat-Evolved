from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_claim_grounding_validation_report,
    write_claim_grounding_validation_report,
)


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def test_claim_grounding_validation_accepts_repo_artifacts():
    report = build_claim_grounding_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert {record.check_id for record in report.records} == {
        "CLAIM-GROUNDING-CONTRACT",
        "CLAIM-HYPOTHESIS-SEPARATION",
        "CLAIM-RULE-COMPILER-ELIGIBILITY",
    }
    grounding = next(
        record
        for record in report.records
        if record.check_id == "CLAIM-GROUNDING-CONTRACT"
    )
    assert grounding.details["claim_count"] == 4
    assert grounding.details["verifier_passed_count"] == 4


def test_claim_grounding_validation_rejects_unregistered_source_span(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    claim_path = tmp_path / "registry/claims/semiconductor_claims.jsonl"
    rows = [
        json.loads(line) for line in claim_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["source_span_id"] = "missing-span"
    claim_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )

    report = build_claim_grounding_validation_report(tmp_path)
    grounding = next(
        record
        for record in report.records
        if record.check_id == "CLAIM-GROUNDING-CONTRACT"
    )

    assert not report.accepted
    assert not grounding.accepted
    assert any(
        "source_span_id not registered" in failure for failure in grounding.failures
    )


def test_claim_grounding_validation_rejects_hypothesis_source_grounded_fields(
    tmp_path: Path,
):
    _copy_registry(Path("."), tmp_path)
    hypothesis_path = tmp_path / "registry/hypotheses/central_bank_hypotheses.jsonl"
    row = json.loads(hypothesis_path.read_text(encoding="utf-8").splitlines()[0])
    row["not_source_grounded"] = False
    row["source_span_id"] = "PAGE-1-PARA-1"
    hypothesis_path.write_text(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_claim_grounding_validation_report(tmp_path)
    separation = next(
        record
        for record in report.records
        if record.check_id == "CLAIM-HYPOTHESIS-SEPARATION"
    )

    assert not report.accepted
    assert not separation.accepted
    assert any(
        "not_source_grounded must be true" in failure for failure in separation.failures
    )
    assert any(
        "must not carry source-grounded fields" in failure
        for failure in separation.failures
    )


def test_claim_grounding_validation_rejects_unverified_rule_claim(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    claim_path = tmp_path / "registry/claims/central_bank_claims.jsonl"
    claim = json.loads(claim_path.read_text(encoding="utf-8").splitlines()[0])
    claim["verifier_status"] = "requires_review"
    claim_path.write_text(
        json.dumps(claim, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_claim_grounding_validation_report(tmp_path)
    compiler = next(
        record
        for record in report.records
        if record.check_id == "CLAIM-RULE-COMPILER-ELIGIBILITY"
    )

    assert not report.accepted
    assert not compiler.accepted
    assert any(
        "verifier_status must be passed" in failure for failure in compiler.failures
    )


def test_claim_grounding_validation_writer_outputs_report(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)

    result = write_claim_grounding_validation_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert len(payload["records"]) == 3
