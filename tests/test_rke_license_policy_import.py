from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    apply_source_license_review_import,
    build_source_license_policy_import,
)
from mosaic.rke.cli import main


def _copy_registry(dst_root: Path) -> None:
    dst = dst_root / "registry/compliance/tushare_license_review_template.jsonl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    rows = _load_jsonl(Path("registry/compliance/tushare_license_review_template.jsonl"))[:3]
    dst.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _policy(**overrides) -> dict:
    payload = {
        "approved_for_derived_claim_storage": True,
        "approved_for_production_runtime": False,
        "filters": {
            "current_license_status": ["pending_review"],
            "source_type": ["tushare_research_report"],
        },
        "notes": "compliance policy fixture",
        "review_date": "2026-06-06",
        "reviewer": "compliance",
    }
    payload.update(overrides)
    return payload


def test_build_source_license_policy_import_expands_signed_policy(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy())

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)
    rows = _load_jsonl(output_path)
    dry_run = apply_source_license_review_import(tmp_path, output_path, dry_run=True)

    assert report.accepted
    assert report.matched_rows == len(rows)
    assert report.output_rows == len(rows)
    assert rows
    assert rows[0]["reviewer"] == "compliance"
    assert rows[0]["approved_for_derived_claim_storage"] is True
    assert rows[0]["approved_for_production_runtime"] is False
    assert dry_run.accepted
    assert dry_run.applied_rows == 0


def test_build_source_license_policy_import_dry_run_does_not_write_output(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy())

    report = build_source_license_policy_import(
        tmp_path,
        policy_path,
        output_path=output_path,
        dry_run=True,
    )

    assert report.accepted
    assert report.output_rows == 0
    assert not output_path.exists()
    assert (tmp_path / "registry/review_batches/source_license_policy_import_report.json").exists()


def test_build_source_license_policy_import_rejects_unscoped_policy(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy(filters={}))

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "at least one policy filter is required" in report.blockers
    assert not output_path.exists()


def test_cli_build_license_review_import(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy())

    code = main(
        (
            "build-license-review-import",
            "--root",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--output",
            str(output_path),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["matched_rows"] == len(_load_jsonl(output_path))
