from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
    build_gold_review_assist,
    build_manual_review_bundle_manifest,
    build_manual_review_batch_status,
    build_gold_review_workbook,
    render_gold_review_assist_markdown,
    build_source_license_review_workbook,
    write_gold_review_assist,
    write_gold_review_starter,
    write_gold_review_workbook,
    write_manual_review_bundle_manifest,
    write_manual_review_batches,
    write_source_license_review_workbook,
)


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    gold_review = dst_root / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    _reset_gold_review_rows(gold_review)
    license_review = dst_root / "registry/compliance/tushare_license_review_template.jsonl"
    _reset_source_license_review_rows(license_review)
    write_manual_review_batches(dst_root)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _reset_gold_review_rows(path: Path) -> None:
    rows = _load_jsonl(path)
    for row in rows:
        row["manual_claim_text"] = ""
        row["claim_correct"] = None
        row["source_span_supports_claim"] = None
        row["direction_correct"] = None
        row["variable_mapping_correct"] = None
        row["unsupported_field_false_grounded"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["review_notes"] = ""
    _write_jsonl(path, rows)


def _reset_source_license_review_rows(path: Path) -> None:
    rows = _load_jsonl(path)
    for row in rows:
        row["approved_for_derived_claim_storage"] = None
        row["approved_for_production_runtime"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["notes"] = ""
    _write_jsonl(path, rows)


def _append_jsonl_value(path: Path, value) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def _accepted_gold_row(row: dict) -> dict:
    out = dict(row)
    out.update(
        {
            "manual_claim_text": row.get("proposed_claim_text") or "manual claim",
            "claim_correct": True,
            "source_span_supports_claim": True,
            "direction_correct": True,
            "variable_mapping_correct": True,
            "unsupported_field_false_grounded": False,
            "reviewer": "reviewer-a",
            "review_date": "2026-06-06",
            "review_notes": "batch fixture",
        }
    )
    return out


def _accepted_license_row(row: dict) -> dict:
    out = dict(row)
    out.update(
        {
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
            "notes": "batch fixture",
        }
    )
    return out


def _license_review_source_count(root: Path) -> int:
    return len(_load_jsonl(root / "registry/compliance/tushare_license_review_template.jsonl"))


def test_manual_review_batches_export_sparse_import_templates(tmp_path: Path):
    _copy_registry(tmp_path)
    source_count = _license_review_source_count(tmp_path)

    paths = write_manual_review_batches(tmp_path, gold_batch_size=12, license_batch_size=7)
    status = json.loads(Path(paths["status"]).read_text(encoding="utf-8"))
    gold_rows = _load_jsonl(Path(paths["gold_set_import_template"]))
    gold_full_rows = _load_jsonl(Path(paths["gold_set_full_import_template"]))
    license_rows = _load_jsonl(Path(paths["source_license_import_template"]))
    workbook = Path(paths["gold_set_review_workbook"]).read_text(encoding="utf-8")
    license_workbook = Path(paths["source_license_review_workbook"]).read_text(encoding="utf-8")

    assert status["ready_for_manual_review"] is True
    assert status["gold_set"]["pending_rows"] == 500
    assert status["gold_set"]["exported_rows"] == 12
    assert status["gold_set"]["full_import_template_path"] == "registry/review_batches/gold_set_full_import_template.jsonl"
    assert "registry/review_batches/gold_set_review_workbook.md" in status["generated_paths"]
    assert "registry/review_batches/gold_set_review_assist.jsonl" in status["generated_paths"]
    assert "registry/review_batches/gold_set_review_assist.md" in status["generated_paths"]
    assert "registry/review_batches/source_license_review_workbook.md" in status["generated_paths"]
    assert status["source_license"]["pending_rows"] == source_count
    assert status["source_license"]["exported_rows"] == 7
    assert len(gold_rows) == 12
    assert len(gold_full_rows) == 500
    assert len(license_rows) == 7
    assert paths["gold_set_review_workbook_rows"] == 500
    assert paths["gold_set_review_assist_rows"] == 500
    assert paths["source_license_review_workbook_rows"] == 50
    assert workbook.startswith("# RKE Gold Review Workbook")
    assert license_workbook.startswith("# RKE Source-License Review Workbook")
    assert "source_license_policy_reviewed.json" in license_workbook
    assert "abstract" not in license_workbook
    assert "GOLD-SRC-" in workbook
    assert "manual_claim_text" not in workbook
    assert "span_preview" not in gold_rows[0]
    assert "abstract" not in gold_rows[0]
    assert "abstract" not in license_rows[0]
    assert gold_rows[0]["proposed_claim_text"]
    assert len(gold_rows[0]["proposed_claim_text"]) <= 72
    assert isinstance(gold_rows[0]["proposed_claim_text_truncated"], bool)
    assert gold_rows[0]["target_row_hash"].startswith("sha256:")
    assert gold_rows[0]["proposed_source_text_hash"].startswith("sha256:")
    assert gold_rows[0]["gold_set_domain"]
    assert gold_rows[0]["gold_set_domain_matches"]
    assert gold_rows[0]["proposed_review_risk_flags"]
    assert gold_rows[0]["manual_claim_text"] == ""
    assert gold_rows[0]["claim_correct"] is None
    assert license_rows[0]["target_row_hash"].startswith("sha256:")
    assert license_rows[0]["approved_for_production_runtime"] is None
    assert "apply-gold-review" in status["gold_set"]["dry_run_command"]
    assert "apply-license-review" in status["source_license"]["dry_run_command"]


def test_gold_review_assist_is_non_import_review_aid(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_gold_review_assist(tmp_path)
    summary, rows = build_gold_review_assist(tmp_path)
    markdown = render_gold_review_assist_markdown(summary, rows)
    written_rows = _load_jsonl(
        tmp_path / "registry/review_batches/gold_set_review_assist.jsonl"
    )

    assert result["rows"] == 500
    assert summary.row_count == 500
    assert summary.pending_rows == 500
    assert summary.blockers == ()
    assert len(rows) == 500
    assert len(written_rows) == 500
    assert rows[0]["assist_kind"] == "gold_review_assist_not_import"
    assert rows[0]["not_apply_gold_review_input"] is True
    assert rows[0]["human_review_required"] is True
    assert "manual_claim_text" in rows[0]["human_required_fields"]
    assert rows[0]["suggested_manual_claim_text_hash"].startswith("sha256:")
    assert len(rows[0]["suggested_manual_claim_text_preview"]) <= 72
    assert markdown.startswith("# RKE Gold Review Assist")
    assert "not an import file" in markdown
    assert (tmp_path / "registry/review_batches/gold_set_review_assist.md").exists()

    import_report = apply_gold_set_review_import(
        tmp_path,
        tmp_path / "registry/review_batches/gold_set_review_assist.jsonl",
        dry_run=True,
    )

    assert not import_report.accepted
    assert import_report.rejected_rows == 500
    assert any(
        "assist_kind unexpected in manual review import" in reason
        for reason in import_report.invalid_rows[0].reasons
    )


def test_gold_review_workbook_is_read_only_claim_checklist(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_gold_review_workbook(tmp_path)
    summary, rows = build_gold_review_workbook(tmp_path)
    workbook = Path(result["path"]).read_text(encoding="utf-8")

    assert result["rows"] == 500
    assert summary.pending_rows == 500
    assert len(rows) == 500
    assert summary.blockers == ()
    assert workbook.startswith("# RKE Gold Review Workbook")
    assert "mosaic-rke prepare-gold-review --root . --full" in workbook
    assert "target_hash" in workbook
    assert rows[0]["target_row_hash"].startswith("sha256:")
    assert len(rows[0]["claim_preview"]) <= 72
    assert "span_preview" not in workbook
    assert "claim_correct" not in workbook


def test_source_license_review_workbook_is_read_only_policy_checklist(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_source_license_review_workbook(tmp_path)
    summary, rows = build_source_license_review_workbook(tmp_path)
    workbook = Path(result["path"]).read_text(encoding="utf-8")

    assert result["rows"] == 50
    assert summary.pending_rows == _license_review_source_count(tmp_path)
    assert summary.matched_row_count == _license_review_source_count(tmp_path)
    assert summary.sample_rows == 50
    assert summary.matched_rows_fingerprint.startswith("sha256:")
    assert summary.blockers == ()
    assert len(rows) == 50
    assert rows[0]["source_id"].startswith("SRC-TSRR-")
    assert rows[0]["target_row_hash"].startswith("sha256:")
    assert len(rows[0]["title_preview"]) <= 96
    assert workbook.startswith("# RKE Source-License Review Workbook")
    assert "approved_for_production_runtime" not in workbook
    assert "abstract" not in workbook


def test_write_gold_review_starter_defaults_to_next_batch_and_preserves_existing(tmp_path: Path):
    _copy_registry(tmp_path)

    first = write_gold_review_starter(tmp_path, gold_batch_size=11)
    reviewed_path = tmp_path / "registry/review_batches/gold_set_reviewed.jsonl"
    rows = _load_jsonl(reviewed_path)
    rows[0]["reviewer"] = "manual reviewer"
    _write_jsonl(reviewed_path, rows)
    second = write_gold_review_starter(tmp_path, gold_batch_size=11)
    preserved = _load_jsonl(reviewed_path)

    assert first.written
    assert first.rows == 11
    assert first.template_path == "registry/review_batches/gold_set_next_import_template.jsonl"
    assert len(rows) == 11
    assert not second.written
    assert not second.overwritten
    assert "already exists" in second.blockers[0]
    assert preserved[0]["reviewer"] == "manual reviewer"


def test_write_gold_review_starter_full_force_overwrites(tmp_path: Path):
    _copy_registry(tmp_path)
    reviewed_path = tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl"
    _write_jsonl(reviewed_path, [{"reviewer": "stale"}])

    result = write_gold_review_starter(tmp_path, full=True, force=True)
    rows = _load_jsonl(reviewed_path)

    assert result.written
    assert result.overwritten
    assert result.full
    assert result.rows == 500
    assert result.template_path == "registry/review_batches/gold_set_full_import_template.jsonl"
    assert len(rows) == 500
    assert rows[0]["reviewer"] == ""
    assert rows[0]["target_row_hash"].startswith("sha256:")


def test_manual_review_batches_reject_malformed_review_rows_without_crashing(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_review = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    license_review = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    gold_count = len(_load_jsonl(gold_review))
    source_count = _license_review_source_count(tmp_path)
    _append_jsonl_value(gold_review, "not an object")
    _append_jsonl_value(license_review, ["not", "an", "object"])

    status, gold_batch, license_batch = build_manual_review_batch_status(
        tmp_path,
        gold_batch_size=3,
        license_batch_size=4,
    )
    paths = write_manual_review_batches(tmp_path, gold_batch_size=3, license_batch_size=4)
    payload = json.loads(Path(paths["status"]).read_text(encoding="utf-8"))

    assert status.ready_for_manual_review is False
    assert f"gold-set review row must be object at row(s): {gold_count + 1}" in status.blockers
    assert f"source license review row must be object at row(s): {source_count + 1}" in status.blockers
    assert status.gold_set.total_rows == gold_count + 1
    assert status.gold_set.pending_rows == gold_count
    assert status.source_license.total_rows == source_count + 1
    assert status.source_license.pending_rows == source_count
    assert len(gold_batch) == 3
    assert len(license_batch) == 4
    assert payload["ready_for_manual_review"] is False
    assert paths["gold_set_rows"] == 3
    assert paths["gold_set_full_rows"] == gold_count
    assert paths["source_license_rows"] == 4


def test_manual_review_batches_report_malformed_json_review_rows_without_crashing(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_review = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    license_review = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    gold_count = len(_load_jsonl(gold_review))
    source_count = _license_review_source_count(tmp_path)
    gold_review.write_text(gold_review.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    license_review.write_text(license_review.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    status, gold_batch, license_batch = build_manual_review_batch_status(
        tmp_path,
        gold_batch_size=3,
        license_batch_size=4,
    )
    paths = write_manual_review_batches(tmp_path, gold_batch_size=3, license_batch_size=4)
    payload = json.loads(Path(paths["status"]).read_text(encoding="utf-8"))

    assert status.ready_for_manual_review is False
    assert f"gold-set review row {gold_count + 1} must contain valid JSON" in status.blockers[0]
    assert any(
        f"source license review row {source_count + 1} must contain valid JSON" in blocker
        for blocker in status.blockers
    )
    assert status.gold_set.total_rows == gold_count + 1
    assert status.source_license.total_rows == source_count + 1
    assert status.gold_set.pending_rows == gold_count
    assert status.source_license.pending_rows == source_count
    assert len(gold_batch) == 3
    assert len(license_batch) == 4
    assert payload["ready_for_manual_review"] is False
    assert paths["gold_set_rows"] == 3
    assert paths["gold_set_full_rows"] == gold_count
    assert paths["source_license_rows"] == 4


def test_manual_review_bundle_manifest_hashes_review_artifacts(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_manual_review_bundle_manifest(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    artifacts = {artifact["path"]: artifact for artifact in payload["artifacts"]}

    assert result["accepted"] is True
    assert payload["accepted"] is True
    assert payload["artifact_count"] >= 20
    assert payload["blockers"] == []
    assert "registry/review_batches/manual_review_bundle_manifest.json" not in artifacts
    assert payload["promotion_dry_run"]["accepted"] is False
    assert payload["promotion_dry_run"]["production_allowed_after_simulation"] is False
    assert payload["promotion_dry_run"]["provided_steps"] == []
    assert set(payload["promotion_dry_run"]["accepted_steps"]) == {"gold_set", "source_license"}
    assert payload["promotion_dry_run"]["rejected_steps"] == ["lockbox"]
    assert set(payload["promotion_dry_run"]["already_applied_steps"]) == {"gold_set", "source_license"}
    assert payload["promotion_dry_run"]["missing_steps"] == ["lockbox"]
    assert artifacts["registry/review_batches/gold_set_full_import_template.jsonl"]["row_count"] == 500
    assert artifacts["registry/review_batches/manual_review_progress_report.json"]["format"] == "json"
    assert artifacts["registry/review_batches/manual_review_runbook.md"]["format"] == "markdown"
    assert artifacts["registry/review_batches/gold_set_review_workbook.md"]["format"] == "markdown"
    assert artifacts["registry/review_batches/gold_set_review_assist.jsonl"]["row_count"] == 500
    assert artifacts["registry/review_batches/gold_set_review_assist.md"]["format"] == "markdown"
    assert artifacts["registry/review_batches/source_license_review_workbook.md"]["format"] == "markdown"
    assert artifacts["registry/review_batches/source_license_next_import_template.jsonl"]["row_count"] == 50
    assert artifacts["registry/promotion/rke_promotion_dry_run_report.json"]["format"] == "json"
    assert all(artifact["sha256"].startswith("sha256:") for artifact in payload["artifacts"])


def test_manual_review_bundle_manifest_detects_missing_artifact(tmp_path: Path):
    _copy_registry(tmp_path)
    (tmp_path / "registry/review_batches/lockbox_review_next_import_template.json").unlink()

    manifest = build_manual_review_bundle_manifest(tmp_path)

    assert not manifest.accepted
    assert any("lockbox_review_next_import_template.json missing" in blocker for blocker in manifest.blockers)


def test_manual_review_bundle_manifest_reports_malformed_json_artifacts(tmp_path: Path):
    _copy_registry(tmp_path)
    artifact_path = tmp_path / "registry/review_batches/lockbox_review_next_import_template.json"
    artifact_path.write_text("{\n", encoding="utf-8")

    manifest = build_manual_review_bundle_manifest(tmp_path)

    assert not manifest.accepted
    assert any(
        "registry/review_batches/lockbox_review_next_import_template.json must contain valid JSON"
        in blocker
        for blocker in manifest.blockers
    )


def test_manual_review_bundle_manifest_reports_non_object_json_artifacts(tmp_path: Path):
    _copy_registry(tmp_path)
    artifact_path = tmp_path / "registry/review_batches/lockbox_review_next_import_template.json"
    artifact_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    manifest = build_manual_review_bundle_manifest(tmp_path)

    assert not manifest.accepted
    assert (
        "registry/review_batches/lockbox_review_next_import_template.json must be object"
        in manifest.blockers
    )


def test_manual_review_bundle_manifest_detects_malformed_jsonl_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "registry/review_batches/source_license_next_import_template.jsonl"
    expected_row = len(import_path.read_text(encoding="utf-8").splitlines()) + 1
    _append_jsonl_value(import_path, "not an object")

    manifest = build_manual_review_bundle_manifest(tmp_path)
    artifact = next(item for item in manifest.artifacts if item.path.endswith("source_license_next_import_template.jsonl"))

    assert not manifest.accepted
    assert artifact.row_count == expected_row
    assert (
        f"registry/review_batches/source_license_next_import_template.jsonl row must be object at row(s): {expected_row}"
        in manifest.blockers
    )


def test_manual_review_bundle_manifest_reports_malformed_jsonl_line_numbers(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "registry/review_batches/source_license_next_import_template.jsonl"
    existing_lines = len(import_path.read_text(encoding="utf-8").splitlines())
    import_path.write_text(
        import_path.read_text(encoding="utf-8") + "{\n" + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    manifest = build_manual_review_bundle_manifest(tmp_path)
    artifact = next(item for item in manifest.artifacts if item.path.endswith("source_license_next_import_template.jsonl"))

    assert not manifest.accepted
    assert artifact.row_count == existing_lines + 2
    assert (
        f"registry/review_batches/source_license_next_import_template.jsonl row {existing_lines + 1} "
        "must contain valid JSON"
        in manifest.blockers[0]
    )
    assert (
        "registry/review_batches/source_license_next_import_template.jsonl "
        f"row must be object at row(s): {existing_lines + 2}"
        in manifest.blockers
    )


def test_manual_review_batch_status_moves_after_partial_import(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_template = _load_jsonl(tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl")
    license_template = _load_jsonl(tmp_path / "registry/review_batches/source_license_next_import_template.jsonl")
    source_count = _license_review_source_count(tmp_path)
    first_gold_id = gold_template[0]["claim_id"]
    first_license_id = license_template[0]["source_id"]
    gold_import = tmp_path / "gold_batch_import.jsonl"
    license_import = tmp_path / "license_batch_import.jsonl"
    _write_jsonl(gold_import, [_accepted_gold_row(gold_template[0])])
    _write_jsonl(license_import, [_accepted_license_row(license_template[0])])

    gold_report = apply_gold_set_review_import(tmp_path, gold_import)
    license_report = apply_source_license_review_import(tmp_path, license_import)
    status, gold_batch, license_batch = build_manual_review_batch_status(
        tmp_path,
        gold_batch_size=5,
        license_batch_size=5,
    )

    assert gold_report.accepted
    assert license_report.accepted
    assert status.gold_set.pending_rows == 499
    assert status.source_license.pending_rows == source_count - 1
    assert all(row["claim_id"] != first_gold_id for row in gold_batch)
    assert all(row["source_id"] != first_license_id for row in license_batch)
