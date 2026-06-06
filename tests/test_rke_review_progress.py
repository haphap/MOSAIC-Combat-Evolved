from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke.cli import main
from mosaic.rke.license_policy_import import build_source_license_policy_template
from mosaic.rke.operator_handoff import build_lockbox_review_import_template
from mosaic.rke.review_progress import build_manual_review_progress, write_manual_review_progress_report


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _accepted_gold_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(root / "registry/review_batches/gold_set_full_import_template.jsonl")
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


def _accepted_license_policy(root: Path) -> dict:
    policy = dict(build_source_license_policy_template(root))
    policy.update(
        {
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
            "notes": "fixture approval",
        }
    )
    return policy


def _accepted_lockbox(root: Path) -> dict:
    row = dict(build_lockbox_review_import_template(root))
    row.update(
        {
            "opened_at": "2026-06-06T10:00:00+08:00",
            "opened_by": "quant_research",
            "open_count": 1,
            "result": "passed",
            "parameter_search_after_open": False,
            "rule_design_after_open": False,
            "notes": "fixture lockbox pass",
        }
    )
    return row


def test_review_progress_reports_missing_scratch_files(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    report = build_manual_review_progress(tmp_path)
    code = main(("review-progress", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert not report.ready_for_promotion_dry_run
    assert code == 2
    assert output["path"].endswith("registry/review_batches/manual_review_progress_report.json")
    assert output["ready_for_promotion_dry_run"] is False
    assert {gate["review_kind"] for gate in output["gates"]} == {
        "gold_set",
        "source_license",
        "lockbox",
    }
    assert all(gate["input_exists"] is False for gate in output["gates"])
    assert any("prepare-gold-review" in blocker for blocker in output["blockers"])
    assert any("prepare-license-policy-review" in blocker for blocker in output["blockers"])
    assert any("prepare-lockbox-review" in blocker for blocker in output["blockers"])
    assert (tmp_path / "registry/review_batches/manual_review_progress_report.json").exists()


def test_write_manual_review_progress_report_outputs_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_manual_review_progress_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["ready_for_promotion_dry_run"] is False
    assert result["blocker_count"] >= 3
    assert payload["ready_for_promotion_dry_run"] is False
    assert len(payload["gates"]) == 3
    assert payload["gates"][0]["review_kind"] == "gold_set"


def test_review_progress_accepts_complete_reviewed_scratch_files(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        _accepted_gold_rows(tmp_path),
    )
    _write_json(
        tmp_path / "registry/review_batches/source_license_policy_reviewed.json",
        _accepted_license_policy(tmp_path),
    )
    _write_json(
        tmp_path / "registry/review_batches/lockbox_reviewed.json",
        _accepted_lockbox(tmp_path),
    )

    code = main(("review-progress", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)
    gates = {gate["review_kind"]: gate for gate in output["gates"]}

    assert code == 0
    assert output["path"].endswith("registry/review_batches/manual_review_progress_report.json")
    assert output["ready_for_promotion_dry_run"] is True
    assert output["blockers"] == []
    assert gates["gold_set"]["complete_rows"] == 500
    assert gates["gold_set"]["ready_for_promotion"] is True
    assert gates["source_license"]["complete_rows"] == 9812
    assert gates["source_license"]["ready_for_promotion"] is True
    assert gates["lockbox"]["complete_rows"] == 1
    assert gates["lockbox"]["ready_for_promotion"] is True
    assert (tmp_path / "registry/review_batches/manual_review_progress_report.json").exists()


def test_review_progress_reports_partial_gold_scratch(tmp_path: Path):
    _copy_registry(tmp_path)
    partial_rows = _accepted_gold_rows(tmp_path)[:50]
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        partial_rows,
    )

    report = build_manual_review_progress(tmp_path)
    gold = next(gate for gate in report.gates if gate.review_kind == "gold_set")

    assert not report.ready_for_promotion_dry_run
    assert gold.input_exists
    assert gold.simulation_accepted
    assert gold.complete_rows == 50
    assert gold.pending_rows == 450
    assert not gold.ready_for_promotion
    assert any("450 gold-set claim review rows still pending" in blocker for blocker in gold.blockers)
