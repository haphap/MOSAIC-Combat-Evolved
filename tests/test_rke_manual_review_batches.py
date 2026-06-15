from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
    build_gold_review_assist,
    build_gold_review_evidence,
    build_manual_review_bundle_manifest,
    build_manual_review_batch_status,
    build_gold_review_workbook,
    render_gold_review_assist_markdown,
    render_gold_review_evidence_markdown,
    build_source_license_review_workbook,
    write_gold_review_assist,
    write_gold_review_evidence,
    write_gold_review_starter,
    write_gold_review_workbook,
    write_manual_review_bundle_manifest,
    write_manual_review_batches,
    write_source_license_review_workbook,
)
from mosaic.rke.manual_review_batches import GOLD_REVIEWED_IMPORT_PATH, GOLD_REVIEW_TEMPLATE_PATH
from mosaic.rke.manual_review_import import TARGET_ROW_HASH_FIELD, review_row_fingerprint


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
        row["target_correct"] = None
        row["horizon_correct"] = None
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
            "target_correct": True,
            "horizon_correct": True,
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
    expected_gold_rows = status["gold_set"]["pending_rows"]
    assert expected_gold_rows == len(gold_full_rows)
    assert status["gold_set"]["exported_rows"] == 12
    assert status["gold_set"]["full_import_template_path"] == "registry/review_batches/gold_set_full_import_template.jsonl"
    assert "registry/review_batches/gold_set_review_workbook.md" in status["generated_paths"]
    assert "registry/review_batches/gold_set_review_assist.jsonl" in status["generated_paths"]
    assert "registry/review_batches/gold_set_review_assist.md" in status["generated_paths"]
    assert "registry/review_batches/source_license_review_workbook.md" in status["generated_paths"]
    assert status["source_license"]["pending_rows"] == source_count
    assert status["source_license"]["exported_rows"] == 7
    assert len(gold_rows) == 12
    assert len(gold_full_rows) == expected_gold_rows
    assert len(license_rows) == 7
    assert paths["gold_set_review_workbook_rows"] == expected_gold_rows
    assert paths["gold_set_review_assist_rows"] == expected_gold_rows
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
    expected_gold_rows = build_manual_review_batch_status(tmp_path)[0].gold_set.pending_rows

    assert result["rows"] == expected_gold_rows
    assert summary.row_count == expected_gold_rows
    assert summary.pending_rows == expected_gold_rows
    assert summary.blockers == ()
    assert len(rows) == expected_gold_rows
    assert len(written_rows) == expected_gold_rows
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
    assert import_report.rejected_rows == expected_gold_rows
    assert any(
        "assist_kind unexpected in manual review import" in reason
        for reason in import_report.invalid_rows[0].reasons
    )


def test_gold_review_assist_reports_quality_gap_targets_for_completed_gold_set(
    tmp_path: Path,
):
    review_path = tmp_path / GOLD_REVIEW_TEMPLATE_PATH
    review_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        review_path,
        [
            {
                "source_id": "SRC-A",
                "source_span_id": "SRC-A:abstract",
                "claim_id": "GOLD-SRC-A-001",
                "document_id": "SRC-A",
                "claim_correct": True,
                "source_span_supports_claim": True,
                "direction_correct": False,
                "target_correct": True,
                "horizon_correct": True,
                "variable_mapping_correct": False,
                "unsupported_field_false_grounded": True,
                "manual_claim_text": "manual claim",
                "reviewer": "reviewer-a",
                "review_date": "2026-06-06",
                "review_notes": "fixture low quality",
            }
        ],
    )

    result = write_gold_review_assist(tmp_path)
    summary, rows = build_gold_review_assist(tmp_path)
    markdown = render_gold_review_assist_markdown(summary, rows)

    assert result["rows"] == 0
    assert result["quality_gap_targets"]["sample_size_claims"][
        "minimum_additional_count"
    ] == 99
    assert summary.quality_gap_targets is not None
    assert summary.quality_gap_targets["metrics"]["direction_accuracy"][
        "minimum_additional_pass_count_if_denominator_unchanged"
    ] == 1
    assert "## Quality Gate Gap Targets" in markdown


def test_gold_review_assist_can_follow_review_input_order(tmp_path: Path):
    _copy_registry(tmp_path)
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = _load_jsonl(review_path)
    selected = rows[1:3]
    review_input_rows = []
    for row in reversed(selected):
        review_input_rows.append(
            {
                "claim_id": row["claim_id"],
                TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
                "review_context_ref": "registry/gold_sets/tushare_research_reports.review_packet.json",
                "target_review_path": "registry/gold_sets/tushare_research_reports.review_template.jsonl",
                "manual_claim_text": "",
                "claim_correct": None,
                "source_span_supports_claim": None,
                "direction_correct": None,
                "target_correct": None,
                "horizon_correct": None,
                "variable_mapping_correct": None,
                "unsupported_field_false_grounded": None,
                "reviewer": "hap",
                "review_date": "2026-06-15",
                "review_notes": "",
            }
        )
    _write_jsonl(tmp_path / GOLD_REVIEWED_IMPORT_PATH, review_input_rows)

    result = write_gold_review_assist(
        tmp_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
    )
    summary, assist_rows = build_gold_review_assist(
        tmp_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
    )
    workbook_summary, workbook_rows = build_gold_review_workbook(
        tmp_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
    )

    expected_claim_ids = [row["claim_id"] for row in review_input_rows]
    assert result["blockers"] == 0
    assert result["rows"] == 2
    assert result["selection_source"] == "review_input"
    assert result["review_input_path"] == GOLD_REVIEWED_IMPORT_PATH
    assert result["quality_gap_targets"]["metrics"]["direction_accuracy"][
        "current_rate"
    ] is not None
    assert summary.selection_source == "review_input"
    assert summary.quality_gap_targets["metrics"]["variable_mapping_accuracy"][
        "current_rate"
    ] is not None
    assert workbook_summary.selection_source == "review_input"
    assert [row["claim_id"] for row in assist_rows] == expected_claim_ids
    assert [row["claim_id"] for row in workbook_rows] == expected_claim_ids


def test_gold_review_evidence_is_private_non_import_review_aid(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_gold_review_evidence(tmp_path, limit=2)
    summary, rows = build_gold_review_evidence(tmp_path, limit=2)
    markdown = render_gold_review_evidence_markdown(summary, rows)
    written_rows = _load_jsonl(
        tmp_path / "registry/review_batches/gold_set_review_evidence.jsonl"
    )

    assert result["rows"] == 2
    assert result["evidence_rows"] == 2
    assert result["quality_gap_targets"]["metrics"]["direction_accuracy"][
        "current_rate"
    ] is not None
    assert summary.row_count == 2
    assert summary.evidence_rows == 2
    assert summary.quality_gap_targets["metrics"]["variable_mapping_accuracy"][
        "current_rate"
    ] is not None
    assert summary.blockers == ()
    assert len(rows) == 2
    assert len(written_rows) == 2
    assert rows[0]["evidence_kind"] == "gold_review_evidence_not_import"
    assert rows[0]["not_apply_gold_review_input"] is True
    assert rows[0]["human_review_required"] is True
    assert rows[0]["evidence_snippets"]
    assert rows[0]["suggested_review_decision"]["unsupported_field_false_grounded"] is False
    assert rows[0]["suggested_review_rationales"]
    assert "manual_claim_text" not in rows[0]
    assert markdown.startswith("# RKE Gold Review Evidence Draft")
    assert "## Batch Triage Summary" in markdown
    assert "Suggested tag counts" in markdown
    assert "Proposed risk flag counts" in markdown
    assert "Suggested decision counts" in markdown
    assert "## Quality Gate Gap Targets" in markdown
    assert "Suggested decision rationales" in markdown
    assert "not an import file" in markdown
    assert (tmp_path / "registry/review_batches/gold_set_review_evidence.md").exists()

    import_report = apply_gold_set_review_import(
        tmp_path,
        tmp_path / "registry/review_batches/gold_set_review_evidence.jsonl",
        dry_run=True,
    )

    assert not import_report.accepted
    assert import_report.rejected_rows == 2
    assert any(
        "evidence_kind unexpected in manual review import" in reason
        for reason in import_report.invalid_rows[0].reasons
    )


def test_gold_review_evidence_flags_non_research_claim_text(tmp_path: Path):
    _copy_registry(tmp_path)
    template_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = _load_jsonl(template_path)
    rows[0]["proposed_claim_text"] = (
        "风险提示：宏观经济、货币政策超预期变化、数据误差等风险。"
    )
    rows[0]["proposed_direction"] = "positive"
    rows[0]["proposed_review_risk_flags"] = [
        "manual_review_required",
        "original_markdown_forecast_claim",
    ]
    _write_jsonl(template_path, rows)
    review_input = tmp_path / "gold_non_research_input.jsonl"
    _write_jsonl(review_input, [{"claim_id": rows[0]["claim_id"]}])

    summary, evidence_rows = build_gold_review_evidence(
        tmp_path,
        review_input_path=review_input.relative_to(tmp_path),
    )
    markdown = render_gold_review_evidence_markdown(summary, evidence_rows)
    row = evidence_rows[0]

    assert "non_research_claim_text" in row["suggested_manual_error_tags"]
    assert row["suggested_review_decision"]["claim_correct"] is False
    assert row["suggested_review_decision"]["direction_correct"] is None
    assert row["suggested_review_decision"]["unsupported_field_false_grounded"] is True
    assert row["unsupported_grounding_diagnostics"]["non_research_claim_text"] is True
    assert "unsupported_field_false_grounded" in row["quality_gap_focus_fields"]
    assert "Quality-gap focus field counts" in markdown
    assert "Review diagnostics" in markdown


def test_gold_review_evidence_flags_direction_text_mismatch(tmp_path: Path):
    _copy_registry(tmp_path)
    template_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = _load_jsonl(template_path)
    rows[0]["proposed_claim_text"] = (
        "需求下滑导致公司利润承压，后续股价表现可能弱于行业。"
    )
    rows[0]["proposed_direction"] = "positive"
    rows[0]["proposed_cause_variables"] = []
    rows[0]["proposed_target_variables"] = []
    rows[0]["proposed_review_risk_flags"] = ["manual_review_required"]
    _write_jsonl(template_path, rows)
    review_input = tmp_path / "gold_direction_mismatch_input.jsonl"
    _write_jsonl(review_input, [{"claim_id": rows[0]["claim_id"]}])

    _summary, evidence_rows = build_gold_review_evidence(
        tmp_path,
        review_input_path=review_input.relative_to(tmp_path),
    )
    row = evidence_rows[0]

    assert "direction_text_needs_review" in row["suggested_manual_error_tags"]
    assert "variable_mapping_missing_cause" in row["suggested_manual_error_tags"]
    assert "variable_mapping_missing_target" in row["suggested_manual_error_tags"]
    assert row["suggested_review_decision"]["direction_correct"] is None
    assert row["direction_text_diagnostics"]["status"] == (
        "positive_label_negative_text"
    )
    assert row["variable_mapping_diagnostics"]["blockers"] == (
        "missing_cause_variables",
        "missing_target_variables",
    )
    assert "direction_correct" in row["quality_gap_focus_fields"]
    assert "variable_mapping_correct" in row["quality_gap_focus_fields"]


def test_gold_review_evidence_supports_offset_batches(tmp_path: Path):
    _copy_registry(tmp_path)

    first_summary, first_rows = build_gold_review_evidence(tmp_path, limit=1, offset=0)
    second_summary, second_rows = build_gold_review_evidence(tmp_path, limit=1, offset=1)
    result = write_gold_review_evidence(tmp_path, limit=1, offset=1)

    assert first_summary.requested_offset == 0
    assert second_summary.requested_offset == 1
    assert result["offset"] == 1
    assert len(first_rows) == 1
    assert len(second_rows) == 1
    assert first_rows[0]["claim_id"] != second_rows[0]["claim_id"]


def test_gold_review_evidence_can_follow_review_input_batch(tmp_path: Path):
    _copy_registry(tmp_path)
    result = write_gold_review_starter(
        tmp_path,
        force=True,
        gold_batch_size=3,
        offset=0,
    )
    result_path = Path(result.path)
    if not result_path.is_absolute():
        result_path = tmp_path / result_path
    review_input = result_path.relative_to(tmp_path)
    review_rows = _load_jsonl(tmp_path / review_input)

    summary, evidence_rows = build_gold_review_evidence(
        tmp_path,
        limit=1,
        offset=99,
        review_input_path=review_input,
    )
    write_result = write_gold_review_evidence(
        tmp_path,
        limit=1,
        offset=99,
        review_input_path=review_input,
    )

    assert summary.selection_source == "review_input"
    assert summary.review_input_path == str(review_input)
    assert write_result["selection_source"] == "review_input"
    assert write_result["review_input_path"] == str(review_input)
    assert [row["claim_id"] for row in evidence_rows] == [
        row["claim_id"] for row in review_rows
    ]
    assert [row["target_row_hash"] for row in evidence_rows] == [
        row["target_row_hash"] for row in review_rows
    ]


def test_gold_review_evidence_uses_local_markdown_cache_without_metadata(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    first_row = _load_jsonl(
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )[0]
    source_id = first_row["source_id"]
    metadata_path = tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    metadata_rows = [
        row
        for row in _load_jsonl(metadata_path)
        if row.get("source_id") != source_id
    ]
    _write_jsonl(metadata_path, metadata_rows)
    cache_path = (
        tmp_path
        / ".mosaic/rke/report_intelligence/markdown"
        / f"{source_id}.md"
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        f"# Local markdown fallback\n\n{first_row['proposed_claim_text']}\n",
        encoding="utf-8",
    )

    _summary, rows = build_gold_review_evidence(tmp_path, limit=1)

    assert rows[0]["source_id"] == source_id
    assert rows[0]["markdown_exists"] is True
    assert rows[0]["markdown_path"] == f".mosaic/rke/report_intelligence/markdown/{source_id}.md"
    assert "markdown_missing" not in rows[0]["suggested_manual_error_tags"]


def test_gold_review_evidence_does_not_auto_accept_unavailable_candidate(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    template_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = _load_jsonl(template_path)
    rows[0]["proposed_claim_text"] = (
        "Candidate extraction did not find a source-grounded mechanism sentence; "
        "manual claim required."
    )
    rows[0]["proposed_review_risk_flags"] = [
        "manual_review_required",
        "candidate_unavailable",
    ]
    rows[0]["proposed_source_start_char"] = 0
    rows[0]["proposed_source_end_char"] = 0
    _write_jsonl(template_path, rows)

    review_input = tmp_path / "candidate_unavailable_input.jsonl"
    _write_jsonl(review_input, [{"claim_id": rows[0]["claim_id"]}])

    _summary, evidence_rows = build_gold_review_evidence(
        tmp_path,
        limit=1,
        review_input_path=review_input,
    )
    decision = evidence_rows[0]["suggested_review_decision"]

    assert evidence_rows[0]["suggested_manual_claim_text"] == ""
    assert "candidate_unavailable_requires_manual_rewrite" in evidence_rows[0][
        "suggested_manual_error_tags"
    ]
    assert any(
        item["field"] == "manual_claim_text"
        and item["reason"].startswith("candidate unavailable")
        for item in evidence_rows[0]["suggested_review_rationales"]
    )
    assert decision["claim_correct"] is None
    assert decision["source_span_supports_claim"] is None
    assert decision["direction_correct"] is None
    assert decision["unsupported_field_false_grounded"] is None


def test_gold_review_workbook_is_read_only_claim_checklist(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_gold_review_workbook(tmp_path)
    summary, rows = build_gold_review_workbook(tmp_path)
    workbook = Path(result["path"]).read_text(encoding="utf-8")
    expected_gold_rows = build_manual_review_batch_status(tmp_path)[0].gold_set.pending_rows

    assert result["rows"] == expected_gold_rows
    assert summary.pending_rows == expected_gold_rows
    assert len(rows) == expected_gold_rows
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


def test_write_gold_review_starter_supports_offset_batches(tmp_path: Path):
    _copy_registry(tmp_path)
    first_path = tmp_path / "registry/review_batches/gold_set_reviewed_batch_1.jsonl"
    second_path = tmp_path / "registry/review_batches/gold_set_reviewed_batch_2.jsonl"

    first = write_gold_review_starter(
        tmp_path,
        output_path=first_path,
        gold_batch_size=1,
        offset=0,
    )
    second = write_gold_review_starter(
        tmp_path,
        output_path=second_path,
        gold_batch_size=1,
        offset=1,
    )
    first_rows = _load_jsonl(first_path)
    second_rows = _load_jsonl(second_path)

    assert first.written
    assert second.written
    assert first.offset == 0
    assert second.offset == 1
    assert first.rows == 1
    assert second.rows == 1
    assert first_rows[0]["claim_id"] != second_rows[0]["claim_id"]


def test_write_gold_review_starter_exports_reviewed_failures_for_targeted_rereview(tmp_path: Path):
    _copy_registry(tmp_path)
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = _load_jsonl(review_path)
    distinct_rows = []
    seen_sources = set()
    for row in rows:
        source_id = row["source_id"]
        if source_id in seen_sources:
            continue
        distinct_rows.append(row)
        seen_sources.add(source_id)
        if len(distinct_rows) == 4:
            break
    for index, row in enumerate(distinct_rows):
        row.update(
            {
                "proposed_claim_text": f"若政策催化持续，行业景气有望改善 {index}",
                "proposed_cause_variables": ["industry_policy_catalyst"],
                "proposed_target_variables": ["industry_etf_forward_return"],
                "proposed_review_risk_flags": ["manual_review_required"],
                "manual_claim_text": "reviewed claim",
                "claim_correct": True,
                "source_span_supports_claim": True,
                "direction_correct": True,
                "target_correct": True,
                "horizon_correct": True,
                "variable_mapping_correct": True,
                "unsupported_field_false_grounded": False,
                "reviewer": "hap",
                "review_date": "2026-06-14",
            }
        )
    distinct_rows[1]["variable_mapping_correct"] = False
    distinct_rows[2]["unsupported_field_false_grounded"] = True
    distinct_rows[3]["manual_claim_text"] = ""
    _write_jsonl(review_path, rows)

    result = write_gold_review_starter(
        tmp_path,
        reviewed_failures=True,
        gold_batch_size=10,
        force=True,
        reviewer="hap",
        review_date="2026-06-14",
    )
    reviewed_path = tmp_path / "registry/review_batches/gold_set_reviewed.jsonl"
    exported = _load_jsonl(reviewed_path)

    assert result.written
    assert result.reviewed_failures is True
    assert result.full is False
    assert result.rows == 2
    assert {row["claim_id"] for row in exported} == {
        distinct_rows[1]["claim_id"],
        distinct_rows[2]["claim_id"],
    }
    assert all(row["manual_claim_text"] == "" for row in exported)
    assert all(row["reviewer"] == "hap" for row in exported)


def test_write_gold_review_starter_full_force_overwrites(tmp_path: Path):
    _copy_registry(tmp_path)
    reviewed_path = tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl"
    _write_jsonl(reviewed_path, [{"reviewer": "stale", "review_notes": "preserve me"}])

    result = write_gold_review_starter(
        tmp_path,
        full=True,
        force=True,
        reviewer="hap",
        review_date="2026-06-12",
    )
    rows = _load_jsonl(reviewed_path)

    assert result.written
    assert result.overwritten
    assert result.backed_up_existing_output is True
    assert result.backup_path
    backup_path = Path(result.backup_path)
    assert backup_path.is_file()
    assert backup_path.is_relative_to(tmp_path / ".mosaic/tmp/review-backups")
    assert "preserve me" in backup_path.read_text(encoding="utf-8")
    assert result.full
    expected_gold_rows = build_manual_review_batch_status(tmp_path)[0].gold_set.pending_rows
    assert result.rows == expected_gold_rows
    assert result.template_path == "registry/review_batches/gold_set_full_import_template.jsonl"
    assert len(rows) == expected_gold_rows
    assert rows[0]["reviewer"] == "hap"
    assert rows[0]["review_date"] == "2026-06-12"
    assert rows[0]["claim_correct"] is None
    assert rows[0]["source_span_supports_claim"] is None
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
    assert 0 < status.gold_set.pending_rows <= gold_count
    assert len(gold_batch) == 3
    assert status.source_license.total_rows == source_count + 1
    assert status.source_license.pending_rows == source_count
    assert len(gold_batch) == 3
    assert len(license_batch) == 4
    assert payload["ready_for_manual_review"] is False
    assert paths["gold_set_rows"] == 3
    assert paths["gold_set_full_rows"] == status.gold_set.pending_rows
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
    assert 0 < status.gold_set.pending_rows <= gold_count
    assert len(gold_batch) == 3
    assert status.source_license.pending_rows == source_count
    assert len(gold_batch) == 3
    assert len(license_batch) == 4
    assert payload["ready_for_manual_review"] is False
    assert paths["gold_set_rows"] == 3
    assert paths["gold_set_full_rows"] == status.gold_set.pending_rows
    assert paths["source_license_rows"] == 4


def test_manual_review_bundle_manifest_hashes_review_artifacts(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_manual_review_bundle_manifest(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    artifacts = {artifact["path"]: artifact for artifact in payload["artifacts"]}

    assert result["accepted"] is True
    assert payload["accepted"] is True
    assert payload["artifact_count"] >= 10
    assert payload["blockers"] == []
    assert "registry/review_batches/manual_review_bundle_manifest.json" not in artifacts
    assert payload["promotion_dry_run"]["accepted"] is False
    assert payload["promotion_dry_run"]["production_allowed_after_simulation"] is False
    assert payload["promotion_dry_run"]["provided_steps"] == []
    assert payload["promotion_dry_run"]["accepted_steps"] == ["source_license"]
    assert set(payload["promotion_dry_run"]["rejected_steps"]) == {
        "gold_set",
        "footprint_review",
        "lockbox",
    }
    assert payload["promotion_dry_run"]["already_applied_steps"] == ["source_license"]
    assert set(payload["promotion_dry_run"]["missing_steps"]) == {
        "gold_set",
        "footprint_review",
        "lockbox",
    }
    assert artifacts["registry/review_batches/manual_review_progress_report.json"]["format"] == "json"
    assert artifacts["registry/review_batches/manual_review_runbook.md"]["format"] == "markdown"
    assert "registry/review_batches/gold_set_full_import_template.jsonl" not in artifacts
    assert "registry/review_batches/gold_set_review_workbook.md" not in artifacts
    assert "registry/review_batches/gold_set_review_assist.jsonl" not in artifacts
    assert "registry/review_batches/gold_set_review_assist.md" not in artifacts
    assert "registry/review_batches/gold_set_review_evidence.jsonl" not in artifacts
    assert "registry/review_batches/gold_set_review_evidence.md" not in artifacts
    assert "registry/review_batches/source_license_review_workbook.md" not in artifacts
    assert "registry/review_batches/source_license_next_import_template.jsonl" not in artifacts
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


def test_manual_review_bundle_manifest_ignores_private_malformed_jsonl_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "registry/review_batches/source_license_next_import_template.jsonl"
    _append_jsonl_value(import_path, "not an object")

    manifest = build_manual_review_bundle_manifest(tmp_path)

    assert manifest.accepted
    assert not any(
        item.path.endswith("source_license_next_import_template.jsonl")
        for item in manifest.artifacts
    )
    assert manifest.blockers == ()


def test_manual_review_bundle_manifest_excludes_private_jsonl_parse_errors(tmp_path: Path):
    _copy_registry(tmp_path)
    import_path = tmp_path / "registry/review_batches/source_license_next_import_template.jsonl"
    import_path.write_text(
        import_path.read_text(encoding="utf-8") + "{\n" + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    manifest = build_manual_review_bundle_manifest(tmp_path)

    assert manifest.accepted
    assert not any(
        item.path.endswith("source_license_next_import_template.jsonl")
        for item in manifest.artifacts
    )
    assert not any("source_license_next_import_template" in item for item in manifest.blockers)


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
    assert status.gold_set.pending_rows >= len(gold_batch)
    assert status.source_license.pending_rows == source_count - 1
    assert all(row["claim_id"] != first_gold_id for row in gold_batch)
    assert all(row["source_id"] != first_license_id for row in license_batch)
