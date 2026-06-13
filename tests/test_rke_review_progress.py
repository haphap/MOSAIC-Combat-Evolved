from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke.cli import main
from mosaic.rke.manual_review_batches import write_manual_review_batches
from mosaic.rke.license_policy_import import build_source_license_policy_template
from mosaic.rke.operator_handoff import build_lockbox_review_import_template
from mosaic.rke.review_progress import (
    build_manual_review_progress,
    render_manual_review_runbook_markdown,
    write_manual_review_progress_report,
    write_manual_review_runbook,
)
from mosaic.rke.temp_paths import (
    RKE_OPERATOR_TMP_ENV_PREFIX,
    operator_command,
    rke_temporary_directory,
)


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    footprint_reviewed = (
        dst_root / "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
    )
    if footprint_reviewed.exists():
        footprint_reviewed.unlink()
    footprint_batch = (
        dst_root / "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    if footprint_batch.exists():
        footprint_batch.unlink()
    gold_batch = dst_root / "registry/review_batches/gold_set_reviewed.jsonl"
    if gold_batch.exists():
        gold_batch.unlink()
    lockbox_reviewed = dst_root / "registry/review_batches/lockbox_reviewed.json"
    if lockbox_reviewed.exists():
        lockbox_reviewed.unlink()
    gold_path = dst_root / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    gold_rows = _load_jsonl(gold_path)
    for row in gold_rows:
        row["manual_claim_text"] = ""
        row["claim_correct"] = None
        row["source_span_supports_claim"] = None
        row["direction_correct"] = None
        row["target_correct"] = None
        row["horizon_correct"] = None
        row["variable_mapping_correct"] = None
        row["unsupported_field_false_grounded"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["review_notes"] = ""
    _write_jsonl(gold_path, gold_rows)
    review_path = dst_root / "registry/compliance/tushare_license_review_template.jsonl"
    rows = _load_jsonl(review_path)
    for row in rows:
        row["approved_for_derived_claim_storage"] = None
        row["approved_for_production_runtime"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["notes"] = ""
    _write_jsonl(review_path, rows)
    write_manual_review_batches(dst_root)


def _copy_registry_without_license_reset(dst_root: Path) -> None:
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


def test_rke_temporary_directory_honors_rke_tmpdir(tmp_path: Path, monkeypatch):
    tmp_parent = tmp_path / "rke-tmp"
    monkeypatch.setenv("MOSAIC_RKE_TMPDIR", str(tmp_parent))

    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        tmp_path_obj = Path(tmp_dir)
        assert tmp_path_obj.parent == tmp_parent
        assert tmp_path_obj.exists()

    assert tmp_parent.exists()


def test_rke_temporary_directory_defaults_to_operator_tmpdir(
    tmp_path: Path,
    monkeypatch,
):
    from mosaic.rke import temp_paths

    tmp_parent = tmp_path / "operator-tmp"
    monkeypatch.delenv("MOSAIC_RKE_TMPDIR", raising=False)
    monkeypatch.setattr(temp_paths, "RKE_OPERATOR_TMPDIR", str(tmp_parent))

    with temp_paths.rke_temporary_directory(
        prefix="mosaic-rke-review-progress-"
    ) as tmp_dir:
        tmp_path_obj = Path(tmp_dir)
        assert tmp_path_obj.parent == tmp_parent
        assert tmp_path_obj.exists()

    assert tmp_parent.exists()


def test_operator_command_prefixes_each_shell_segment():
    command = operator_command("mosaic-rke first --root . && mosaic-rke second --root .")

    assert command == (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke first --root . && "
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} mosaic-rke second --root ."
    )


def _license_review_source_count(root: Path) -> int:
    return len(_load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl"))


def _accepted_gold_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(root / "registry/review_batches/gold_set_full_import_template.jsonl")
    for row in rows:
        row.update(
            {
                "manual_claim_text": row.get("proposed_claim_text") or "manual claim",
                "claim_correct": True,
                "source_span_supports_claim": True,
                "direction_correct": True,
                "target_correct": True,
                "horizon_correct": True,
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


def _accepted_footprint_rows(root: Path) -> list[dict]:
    rows = _load_jsonl(
        root / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    for row in rows:
        row.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": [],
                "reviewer": "reviewer-a",
                "review_date": "2026-06-06",
                "review_notes": "fixture approval",
            }
        )
    return rows


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
        "footprint_review",
        "source_license",
        "lockbox",
    }
    gold_gate = next(gate for gate in output["gates"] if gate["review_kind"] == "gold_set")
    footprint_gate = next(
        gate for gate in output["gates"] if gate["review_kind"] == "footprint_review"
    )
    assert gold_gate["next_batch_commands"]["prepare"].startswith(
        RKE_OPERATOR_TMP_ENV_PREFIX
    )
    assert (
        "mosaic-rke prepare-gold-review --root . --gold-batch-size 50 --offset 0"
        in gold_gate["next_batch_commands"]["prepare"]
    )
    expected_footprint_dry_run = (
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} "
        "mosaic-rke apply-footprint-review --root . "
        "--input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run"
    )
    assert (
        footprint_gate["next_batch_commands"]["dry_run"]
        == expected_footprint_dry_run
    )
    assert len(gold_gate["batch_plan"]) == 10
    assert gold_gate["batch_plan"][0]["offset"] == 0
    assert (
        gold_gate["batch_plan"][0]["apply_effect"]
        == "merge_batch_into_target_review_template"
    )
    assert (
        gold_gate["batch_plan"][0]["batch_input_path"]
        == "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert (
        gold_gate["batch_plan"][0]["promotion_input_path"]
        == "registry/review_batches/gold_set_full_reviewed.jsonl"
    )
    assert gold_gate["batch_plan"][-1]["offset"] == 450
    assert len(footprint_gate["batch_plan"]) == 21
    assert footprint_gate["batch_plan"][-1]["offset"] == 1000
    assert footprint_gate["batch_plan"][-1]["limit"] == 1
    assert "source_id" not in json.dumps(gold_gate["batch_plan"])
    assert "footprint_id" not in json.dumps(footprint_gate["batch_plan"])
    assert gold_gate["current_batch_status"]["exists"] is False
    assert (
        gold_gate["current_batch_status"]["path"]
        == "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert footprint_gate["current_batch_status"]["exists"] is False
    assert (
        footprint_gate["current_batch_status"]["path"]
        == "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    lockbox_gate = next(gate for gate in output["gates"] if gate["review_kind"] == "lockbox")
    assert lockbox_gate["current_batch_status"]["exists"] is False
    assert (
        lockbox_gate["current_batch_status"]["path"]
        == "registry/review_batches/lockbox_reviewed.json"
    )
    assert all(gate["input_exists"] is False for gate in output["gates"])
    assert any("prepare-gold-review" in blocker for blocker in output["blockers"])
    assert any("prepare-footprint-review" in blocker for blocker in output["blockers"])
    assert any("prepare-license-policy-review" in blocker for blocker in output["blockers"])
    assert any("prepare-lockbox-review" in blocker for blocker in output["blockers"])
    assert (tmp_path / "registry/review_batches/manual_review_progress_report.json").exists()


def test_review_progress_reports_current_batch_scratch_status(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_rows = _accepted_gold_rows(tmp_path)[:2]
    gold_rows[1]["manual_claim_text"] = ""
    gold_rows[1]["claim_correct"] = None
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_reviewed.jsonl",
        gold_rows,
    )
    footprint_rows = _accepted_footprint_rows(tmp_path)[:2]
    footprint_rows[0]["review_notes"] = ""
    footprint_rows[1]["metric_mapping_correct"] = None
    _write_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprint_review_batch.jsonl",
        footprint_rows,
    )
    lockbox_row = dict(build_lockbox_review_import_template(tmp_path))
    lockbox_row.update(
        {
            "opened_at": "",
            "opened_by": "",
            "open_count": None,
            "result": "",
            "parameter_search_after_open": False,
            "rule_design_after_open": False,
            "notes": "operator-only scratch text must not be rendered",
        }
    )
    _write_json(
        tmp_path / "registry/review_batches/lockbox_reviewed.json",
        lockbox_row,
    )

    report = build_manual_review_progress(tmp_path)
    gates = {gate.review_kind: gate for gate in report.gates}
    gold_batch = gates["gold_set"].current_batch_status
    footprint_batch = gates["footprint_review"].current_batch_status
    lockbox_status = gates["lockbox"].current_batch_status
    markdown = render_manual_review_runbook_markdown(report)

    assert gold_batch["exists"] is True
    assert gold_batch["rows"] == 2
    assert gold_batch["complete_rows"] == 1
    assert gold_batch["pending_rows"] == 1
    assert gold_batch["missing_required_fields"] == {
        "claim_correct": 1,
        "manual_claim_text": 1,
    }
    assert footprint_batch["exists"] is True
    assert footprint_batch["rows"] == 2
    assert footprint_batch["complete_rows"] == 0
    assert footprint_batch["pending_rows"] == 2
    assert footprint_batch["missing_required_fields"] == {
        "metric_mapping_correct": 1,
        "review_notes": 1,
    }
    assert lockbox_status["exists"] is True
    assert lockbox_status["rows"] == 1
    assert lockbox_status["complete_rows"] == 0
    assert lockbox_status["pending_rows"] == 1
    assert lockbox_status["missing_required_fields"] == {
        "open_count": 1,
        "opened_at": 1,
        "opened_by": 1,
        "result": 1,
    }
    assert "## Current Batch Scratch" in markdown
    assert "Gold-set batch" in markdown
    assert "Analytical-footprint batch" in markdown
    assert "Lockbox decision" in markdown
    assert "`manual_claim_text`=1" in markdown
    assert "`review_notes`=1" in markdown
    assert "`open_count`=1" in markdown
    assert "fixture approval" not in markdown
    assert "operator-only scratch text" not in markdown


def test_write_manual_review_progress_report_outputs_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_manual_review_progress_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["ready_for_promotion_dry_run"] is False
    assert result["blocker_count"] >= 3
    assert payload["ready_for_promotion_dry_run"] is False
    assert len(payload["gates"]) == 4
    assert payload["gates"][0]["review_kind"] == "gold_set"
    assert payload["gates"][1]["review_kind"] == "footprint_review"


def test_manual_review_runbook_renders_operator_checklist_without_source_text(tmp_path: Path):
    _copy_registry(tmp_path)

    report = build_manual_review_progress(tmp_path)
    markdown = render_manual_review_runbook_markdown(report)
    result = write_manual_review_runbook(tmp_path)
    written = Path(result["path"]).read_text(encoding="utf-8")

    assert markdown.startswith("# RKE Manual Review Runbook")
    assert written == markdown + "\n"
    assert result["path"].endswith("registry/review_batches/manual_review_runbook.md")
    assert result["ready_for_promotion_dry_run"] is False
    assert "mosaic-rke prepare-gold-review --root . --full" in markdown
    assert "## Next Batch Commands" in markdown
    assert "## Full Pending Batch Plan" in markdown
    assert (
        "Batch 10: pending rows 451-500; limit=50; offset=450; "
        "batch input=`registry/review_batches/gold_set_reviewed.jsonl`"
        in markdown
    )
    assert (
        "Batch 21: pending rows 1001-1001; limit=1; offset=1000; "
        "batch input=`registry/report_intelligence/analytical_footprint_review_batch.jsonl`"
        in markdown
    )
    assert "### gold_set" in markdown
    assert "### footprint_review" in markdown
    assert "After applying an accepted batch, rerun review-progress" in markdown
    assert (
        "mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 "
        "--review-input registry/review_batches/gold_set_reviewed.jsonl"
        in markdown
    )
    assert "mosaic-rke apply-gold-review --root . --input registry/review_batches/gold_set_reviewed.jsonl --dry-run" in markdown
    assert "rerun with `--offset 0` because completed rows leave the pending set" in markdown
    assert "batch-aligned private source-evidence draft" in markdown
    assert "mosaic-rke prepare-footprint-review --root ." in markdown
    assert "mosaic-rke write-footprint-review-assist --root ." in markdown
    assert (
        "mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 "
        "--review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl"
        in markdown
    )
    assert "mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run" in markdown
    assert "mosaic-rke prepare-license-policy-review --root ." in markdown
    assert "mosaic-rke prepare-lockbox-review --root ." in markdown
    assert "Lockbox decision" in markdown
    assert "registry/review_batches/gold_set_full_reviewed.jsonl" in markdown
    assert "registry/report_intelligence/analytical_footprint_reviewed.jsonl" in markdown
    assert "registry/review_batches/gold_set_review_evidence.jsonl" in markdown
    assert "registry/review_batches/gold_set_review_evidence.md" in markdown
    assert "registry/report_intelligence/analytical_footprint_review_assist.jsonl" in markdown
    assert "registry/report_intelligence/analytical_footprint_review_workbook.md" in markdown
    assert "registry/report_intelligence/analytical_footprint_review_evidence.jsonl" in markdown
    assert "registry/report_intelligence/analytical_footprint_review_evidence.md" in markdown
    assert "registry/review_batches/source_license_policy_reviewed.json" in markdown
    assert "registry/review_batches/lockbox_reviewed.json" in markdown
    assert "registry/review_batches/gold_set_review_workbook.md" in markdown
    assert "registry/review_batches/source_license_review_workbook.md" in markdown
    assert "## Gate Acceptance Criteria" in markdown
    assert "manual_claim_text" in markdown
    assert "claim precision >= 0.85" in markdown
    assert "span-support precision >= 0.90" in markdown
    assert "direction accuracy >= 0.85" in markdown
    assert "variable mapping accuracy >= 0.80" in markdown
    assert "unsupported-field false grounding <= 0.05" in markdown
    assert "footprint_correct" in markdown
    assert "no_proprietary_text_leakage" in markdown
    assert "approved_for_production_runtime=true" in markdown
    assert "matched_rows_fingerprint" in markdown
    assert "result=passed" in markdown
    assert "open_count<=1" in markdown
    assert "matching target/context hashes" in markdown
    assert "promotion-dry-run" in markdown
    assert "Do not commit" in markdown
    assert "abstract" not in markdown.lower()
    assert "source_span_text" not in markdown


def test_review_progress_accepts_complete_reviewed_scratch_files(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        _accepted_gold_rows(tmp_path),
    )
    footprint_rows = _accepted_footprint_rows(tmp_path)
    _write_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        footprint_rows,
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
    assert gates["footprint_review"]["complete_rows"] == len(footprint_rows)
    assert gates["footprint_review"]["ready_for_promotion"] is True
    assert gates["source_license"]["complete_rows"] == _license_review_source_count(tmp_path)
    assert gates["source_license"]["ready_for_promotion"] is True
    assert gates["lockbox"]["complete_rows"] == 1
    assert gates["lockbox"]["ready_for_promotion"] is True
    assert (tmp_path / "registry/review_batches/manual_review_progress_report.json").exists()


def test_review_progress_accepts_already_applied_source_license_with_stale_scratch(
    tmp_path: Path,
):
    _copy_registry_without_license_reset(tmp_path)
    stale_policy = _accepted_license_policy(tmp_path)
    stale_policy["matched_rows_fingerprint"] = "sha256:stale"
    _write_json(
        tmp_path / "registry/review_batches/source_license_policy_reviewed.json",
        stale_policy,
    )

    report = build_manual_review_progress(tmp_path)
    source_license = next(
        gate for gate in report.gates if gate.review_kind == "source_license"
    )

    assert source_license.ready_for_promotion is True
    assert source_license.simulation_accepted is True
    assert source_license.complete_rows == source_license.target_rows
    assert source_license.pending_rows == 0
    assert source_license.blockers == ()


def test_review_progress_accepts_already_applied_gold_with_stale_scratch(
    tmp_path: Path,
):
    _copy_registry_without_license_reset(tmp_path)
    target_row = _load_jsonl(
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )[0]
    stale_row = dict(target_row)
    stale_row["target_row_hash"] = "sha256:stale"
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        [stale_row],
    )

    report = build_manual_review_progress(tmp_path)
    gold = next(gate for gate in report.gates if gate.review_kind == "gold_set")

    assert gold.ready_for_promotion is True
    assert gold.simulation_accepted is True
    assert gold.complete_rows == gold.target_rows
    assert gold.pending_rows == 0
    assert gold.blockers == ()


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


def test_review_progress_reports_stale_gold_scratch_hashes(tmp_path: Path):
    _copy_registry(tmp_path)
    rows = _load_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl"
    )
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        rows,
    )
    target_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    target_rows = _load_jsonl(target_path)
    target_rows[0]["proposed_claim_text"] = "changed after reviewed scratch export"
    _write_jsonl(target_path, target_rows)

    report = build_manual_review_progress(tmp_path)
    gold = next(gate for gate in report.gates if gate.review_kind == "gold_set")

    assert not gold.ready_for_promotion
    assert any("stale target_row_hash" in blocker for blocker in gold.blockers)
    assert any(
        "prepare-gold-review --root . --full --force" in blocker
        for blocker in gold.blockers
    )
