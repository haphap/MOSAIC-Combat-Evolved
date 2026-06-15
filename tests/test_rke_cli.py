from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    TushareResearchReportRefreshResult,
    write_completion_audit,
    write_gold_set_review_summary,
    write_manual_review_batches,
)
from mosaic.rke.cli import main
from mosaic.rke.registry_manifest import PRIVATE_LOCAL_REGISTRY_FILES
from mosaic.rke.temp_paths import RKE_OPERATOR_TMP_ENV_PREFIX
from mosaic.rke.tushare_reports import P9_REPORT_INTELLIGENCE_CORPUS_PROFILE


GOLD_MANUAL_FIELDS = (
    "manual_claim_text",
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "target_correct",
    "horizon_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
    "reviewer",
    "review_notes",
)


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")
    _reset_gold_review_rows(
        dst_root / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    write_gold_set_review_summary(dst_root)
    write_manual_review_batches(dst_root)
    write_completion_audit(dst_root)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
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


def _redaction_source_text_count(root: Path) -> int:
    payload = json.loads(
        (root / "registry/compliance/source_text_redaction_report.json").read_text(
            encoding="utf-8"
        )
    )
    return int(payload["source_text_count"])


def test_rke_cli_validate_required_success(capsys):
    code = main(("validate-required", "--root", "."))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["valid"] is True
    assert output["missing_required"] == []
    assert output["empty_required"] == []
    assert output["invalid_required"] == []


def test_rke_cli_validate_required_failure(tmp_path: Path, capsys):
    code = main(("validate-required", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["valid"] is False
    assert "registry/audits/rke_completion_audit.json" in output["missing_required"]
    assert output["invalid_required"] == []


def test_rke_cli_validate_required_rejects_invalid_json(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    target = tmp_path / "registry/audits/rke_completion_audit.json"
    target.write_text("{", encoding="utf-8")

    code = main(("validate-required", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["valid"] is False
    assert output["missing_required"] == []
    assert len(output["invalid_required"]) == 1
    assert (
        "registry/audits/rke_completion_audit.json must contain valid JSON"
        in output["invalid_required"][0]
    )


def test_rke_cli_manifest_writes_file(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("manifest", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)
    manifest = json.loads(Path(output["path"]).read_text(encoding="utf-8"))
    artifact_paths = {str(artifact["path"]) for artifact in manifest["artifacts"]}

    assert code == 0
    assert output["valid"] is True
    assert Path(output["path"]).exists()
    assert artifact_paths.isdisjoint(PRIVATE_LOCAL_REGISTRY_FILES)


def test_rke_cli_master_plan_status_writes_coverage(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    shutil.copytree(Path("docs"), tmp_path / "docs")
    shutil.copytree(Path("schemas"), tmp_path / "schemas")

    code = main(("master-plan-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["coverage_complete"] is False
    assert output["ready_for_broad_rollout"] is False
    assert output["blocked_count"] == 0
    assert output["missing_count"] == 1
    next_actions = {action["action_id"]: action for action in output["next_actions"]}
    assert {
        "inspect_master_plan_schema_blockers",
        "complete_manual_analytical_footprint_review",
        "clear_patch_v1_5_manual_review_coverage",
    } <= set(next_actions)
    assert (
        "schema-status --root . --failures-only --no-write"
        in next_actions["inspect_master_plan_schema_blockers"]["commands"][
            "schema_failures"
        ]
    )
    assert next_actions["inspect_master_plan_schema_blockers"]["review_aids"][
        "gold_set"
    ]["fill_import_path"] == "registry/review_batches/gold_set_reviewed.jsonl"
    assert "review_notes" in next_actions[
        "complete_manual_analytical_footprint_review"
    ]["field_contract"]["required_fields"]
    assert (tmp_path / "registry/audits/rke_master_plan_coverage_report.json").exists()


def test_rke_cli_master_plan_status_no_write_preserves_artifacts(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    shutil.copytree(Path("docs"), tmp_path / "docs")
    shutil.copytree(Path("schemas"), tmp_path / "schemas")

    main(("master-plan-status", "--root", str(tmp_path)))
    capsys.readouterr()

    sentinel_by_path = {
        tmp_path / "registry/audits/central_bank_mvp_audit_trace.json": '{"sentinel":"trace"}\n',
        tmp_path / "registry/audits/central_bank_mvp_audit_view.json": '{"sentinel":"view"}\n',
        tmp_path / "registry/audits/central_bank_mvp_audit_view.md": "sentinel view\n",
        tmp_path / "registry/audits/rke_completion_audit.json": '{"sentinel":"completion"}\n',
        tmp_path / "registry/audits/rke_master_plan_coverage_report.json": '{"sentinel":"coverage"}\n',
    }
    for path, sentinel in sentinel_by_path.items():
        path.write_text(sentinel, encoding="utf-8")

    code = main(("master-plan-status", "--root", str(tmp_path), "--no-write"))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["coverage_complete"] is False
    next_actions = {action["action_id"]: action for action in output["next_actions"]}
    assert "inspect_master_plan_schema_blockers" in next_actions
    assert (
        "review-progress --root . --actions-only --no-write"
        in next_actions["inspect_master_plan_schema_blockers"]["commands"][
            "manual_queue"
        ]
    )
    for path, sentinel in sentinel_by_path.items():
        assert path.read_text(encoding="utf-8") == sentinel


def test_rke_cli_audit_view_writes_trace_view(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("audit-view", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["complete"] is True
    assert output["node_count"] == 8
    assert output["edge_count"] >= 12
    assert output["missing_references"] == []
    assert output["broken_edges"] == []
    assert (tmp_path / "registry/audits/central_bank_mvp_audit_view.json").exists()
    assert (tmp_path / "registry/audits/central_bank_mvp_audit_view.md").exists()


def test_rke_cli_audit_view_reports_malformed_jsonl_rows(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    claim_path = tmp_path / "registry/claims/central_bank_claims.jsonl"
    claim_path.write_text(
        claim_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    code = main(("audit-view", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["complete"] is False
    assert (
        "registry/claims/central_bank_claims.jsonl row 2 must be object"
        in output["broken_edges"]
    )


def test_rke_cli_refresh_preserves_reviews(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    gold_review = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    rows = [json.loads(line) for line in gold_review.read_text(encoding="utf-8").splitlines()]
    rows[0]["manual_claim_text"] = "manual label"
    rows[0]["claim_correct"] = True
    rows[0]["source_span_supports_claim"] = True
    rows[0]["direction_correct"] = True
    rows[0]["target_correct"] = True
    rows[0]["horizon_correct"] = True
    rows[0]["variable_mapping_correct"] = True
    rows[0]["unsupported_field_false_grounded"] = True
    rows[0]["reviewer"] = "tester"
    rows[0]["review_notes"] = "preserve manual review fields"
    edited_claim_id = str(rows[0].get("claim_id") or "")
    gold_review.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    original_manual = {
        str(row.get("claim_id") or ""): {field: row.get(field) for field in GOLD_MANUAL_FIELDS}
        for row in rows
    }

    code = main(("refresh", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)
    refreshed_rows = [json.loads(line) for line in gold_review.read_text(encoding="utf-8").splitlines()]
    refreshed_manual = {
        str(row.get("claim_id") or ""): {field: row.get(field) for field in GOLD_MANUAL_FIELDS}
        for row in refreshed_rows
    }

    assert code == 0
    assert output["manifest_valid"] is True
    assert refreshed_manual[edited_claim_id] == original_manual[edited_claim_id]
    assert all(
        manual_fields == original_manual[claim_id]
        for claim_id, manual_fields in refreshed_manual.items()
    )


def test_rke_cli_review_status_commands_write_summaries(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    expected_review_row_count = len(
        _load_jsonl(
            tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
        )
    )

    gold_code = main(("gold-set-status", "--root", str(tmp_path)))
    gold_output = json.loads(capsys.readouterr().out)
    candidate_code = main(("gold-candidate-claims", "--root", str(tmp_path)))
    candidate_output = json.loads(capsys.readouterr().out)
    packet_code = main(("gold-review-packet", "--root", str(tmp_path)))
    packet_output = json.loads(capsys.readouterr().out)
    license_code = main(("license-status", "--root", str(tmp_path)))
    license_output = json.loads(capsys.readouterr().out)
    license_packet_code = main(("license-review-packet", "--root", str(tmp_path)))
    license_packet_output = json.loads(capsys.readouterr().out)
    candidate_claim_rows = _load_jsonl(
        tmp_path / "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"
    )
    candidate_summary = json.loads(
        (
            tmp_path
            / "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
        ).read_text(encoding="utf-8")
    )
    packet_review_row_count = len(
        _load_jsonl(
            tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
        )
    )

    assert gold_code == 0
    assert gold_output["pending_claims"] == expected_review_row_count
    assert (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_summary.json"
    ).exists()
    assert candidate_code == 0
    assert candidate_output["candidate_claim_count"] == len(candidate_claim_rows)
    assert (
        candidate_output["review_rows_with_candidate_fields"]
        == candidate_summary["review_rows_with_candidate_fields"]
    )
    assert candidate_output["manual_fields_preserved"] is True
    assert (
        tmp_path / "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"
    ).exists()
    assert (
        tmp_path
        / "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
    ).exists()
    assert packet_code == 0
    assert packet_output["pending_review_rows"] == packet_review_row_count
    assert packet_output["candidate_claim_count"] == candidate_output["candidate_claim_count"]
    assert (
        packet_output["review_rows_with_candidate_fields"]
        == candidate_output["review_rows_with_candidate_fields"]
    )
    assert packet_output["candidate_span_ref_count"] > 0
    assert (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_packet.json"
    ).exists()
    assert (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_packet.md"
    ).exists()
    assert license_code == 0
    assert license_output["pending_sources"] == 0
    assert (
        license_output["approved_for_production_runtime"]
        == license_output["total_sources"]
    )
    assert license_output["missing_review_source_ids"] == {
        "count": 0,
        "sample": [],
        "truncated": False,
    }
    assert license_output["extra_review_source_ids"] == {
        "count": 0,
        "sample": [],
        "truncated": False,
    }
    assert license_output["full_summary_path"] == (
        "registry/compliance/tushare_license_review_summary.json"
    )
    full_license_summary = json.loads(
        (
            tmp_path / "registry/compliance/tushare_license_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert full_license_summary["missing_review_source_ids"] == []
    assert (
        tmp_path / "registry/compliance/tushare_license_review_summary.json"
    ).exists()
    assert license_packet_code == 0
    assert license_packet_output["pending_sources"] == 0
    assert (
        license_packet_output["approved_for_production_runtime"]
        == license_output["total_sources"]
    )
    assert (
        tmp_path / "registry/compliance/tushare_license_review_packet.json"
    ).exists()
    assert (tmp_path / "registry/compliance/tushare_license_review_packet.md").exists()


def test_rke_cli_prepare_license_policy_review_protects_existing_file(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    reviewed_path = (
        tmp_path / "registry/review_batches/source_license_policy_reviewed.json"
    )

    code = main(("prepare-license-policy-review", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)
    second_code = main(("prepare-license-policy-review", "--root", str(tmp_path)))
    second_output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["written"] is True
    assert output["path"] == str(reviewed_path)
    assert output["workbook_path"].endswith(
        "registry/review_batches/source_license_review_workbook.md"
    )
    assert output["workbook_rows"] == 0
    assert reviewed_path.exists()
    assert (
        tmp_path / "registry/review_batches/source_license_review_workbook.md"
    ).exists()
    assert second_code == 2
    assert second_output["written"] is False
    assert "already exists" in second_output["blockers"][0]


def test_rke_cli_prepare_gold_review_supports_full_and_protects_existing_file(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    reviewed_path = tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl"

    code = main(
        (
            "prepare-gold-review",
            "--root",
            str(tmp_path),
            "--full",
            "--reviewer",
            "hap",
            "--review-date",
            "2026-06-12",
        )
    )
    output = json.loads(capsys.readouterr().out)
    second_code = main(("prepare-gold-review", "--root", str(tmp_path), "--full"))
    second_output = json.loads(capsys.readouterr().out)
    rows = _load_jsonl(reviewed_path)

    assert code == 0
    assert output["written"] is True
    assert output["full"] is True
    assert output["rows"] == len(rows)
    assert output["rows"] > 0
    assert output["path"] == str(reviewed_path)
    assert reviewed_path.exists()
    assert rows[0]["reviewer"] == "hap"
    assert rows[0]["review_date"] == "2026-06-12"
    assert rows[0]["claim_correct"] is None
    assert second_code == 2
    assert second_output["written"] is False
    assert "already exists" in second_output["blockers"][0]


def test_rke_cli_prepare_lockbox_review_protects_existing_file(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    reviewed_path = tmp_path / "registry/review_batches/lockbox_reviewed.json"
    if reviewed_path.exists():
        reviewed_path.unlink()

    blocked_code = main(("prepare-lockbox-review", "--root", str(tmp_path)))
    blocked_output = json.loads(capsys.readouterr().out)
    assert blocked_code == 2
    assert blocked_output["written"] is False
    assert blocked_output["allow_pending_upstream"] is False
    assert "gold_set gate must be ready before opening lockbox review" in (
        blocked_output["upstream_blockers"]
    )
    assert "footprint_review gate must be ready before opening lockbox review" in (
        blocked_output["upstream_blockers"]
    )
    assert not reviewed_path.exists()

    code = main(
        (
            "prepare-lockbox-review",
            "--root",
            str(tmp_path),
            "--allow-pending-upstream",
        )
    )
    output = json.loads(capsys.readouterr().out)
    second_code = main(
        (
            "prepare-lockbox-review",
            "--root",
            str(tmp_path),
            "--allow-pending-upstream",
        )
    )
    second_output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["written"] is True
    assert output["allow_pending_upstream"] is True
    assert output["upstream_blockers"] == []
    assert output["path"] == str(reviewed_path)
    assert (
        output["template_path"]
        == "registry/review_batches/lockbox_review_next_import_template.json"
    )
    assert (
        output["checklist_path"]
        == "registry/review_batches/lockbox_review_checklist.md"
    )
    assert reviewed_path.exists()
    checklist = tmp_path / "registry/review_batches/lockbox_review_checklist.md"
    assert checklist.exists()
    assert "RKE Lockbox Review Checklist" in checklist.read_text(encoding="utf-8")
    starter = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert starter["result"] == ""
    assert starter["target_row_hash"].startswith("sha256:")
    assert second_code == 2
    assert second_output["written"] is False
    assert "already exists" in second_output["blockers"][0]


def test_rke_cli_review_status_commands_report_malformed_jsonl_rows(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    gold_path = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    )
    license_path = (
        tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    )
    license_bad_row = len(license_path.read_text(encoding="utf-8").splitlines()) + 1
    gold_path.write_text(
        gold_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )
    license_path.write_text(
        license_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )

    gold_code = main(("gold-set-status", "--root", str(tmp_path)))
    gold_output = json.loads(capsys.readouterr().out)
    license_code = main(("license-status", "--root", str(tmp_path)))
    license_output = json.loads(capsys.readouterr().out)

    assert gold_code == 0
    assert any(
        "gold-set review row 501 must contain valid JSON" in blocker
        for blocker in gold_output["blockers"]
    )
    assert gold_output["total_claims"] == 501
    assert license_code == 0
    assert any(
        f"source license review row {license_bad_row} must contain valid JSON"
        in blocker
        for blocker in license_output["blockers"]
    )
    assert license_output["total_review_rows"] == license_bad_row


def test_rke_cli_gold_candidate_claims_reports_malformed_jsonl_rows(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    candidates_path = (
        tmp_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    )
    expected_candidate_count = len(_load_jsonl(candidates_path))
    candidates_path.write_text(
        candidates_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )

    code = main(("gold-candidate-claims", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)
    candidate_claim_rows = _load_jsonl(
        tmp_path / "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"
    )

    assert code == 0
    assert output["candidate_claim_count"] == len(candidate_claim_rows)
    assert any(
        f"gold candidate row {expected_candidate_count + 1} must contain valid JSON"
        in blocker
        for blocker in output["blockers"]
    )


def test_rke_cli_prompt_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("prompt-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (
        tmp_path / "registry/prompt_checks/prompt_asset_validation_report.json"
    ).exists()


def test_rke_cli_rule_pack_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("rule-pack-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/rule_checks/rule_pack_validation_report.json").exists()


def test_rke_cli_claim_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("claim-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (
        tmp_path / "registry/claim_checks/claim_variable_validation_report.json"
    ).exists()
    assert (
        tmp_path / "registry/claim_checks/claim_grounding_validation_report.json"
    ).exists()
    assert (tmp_path / "registry/vocabularies/claim_variable_vocabulary.json").exists()


def test_rke_cli_experiment_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("experiment-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert len(output["records"]) == 4
    assert (
        tmp_path / "registry/experiment_checks/experiment_validation_report.json"
    ).exists()


def test_rke_cli_claim_status_reports_malformed_vocabulary_without_overwrite(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)
    vocabulary_path = tmp_path / "registry/vocabularies/claim_variable_vocabulary.json"
    vocabulary_path.write_text("{\n", encoding="utf-8")

    code = main(("claim-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)
    schema = next(
        record
        for record in output["records"]
        if record["check_id"] == "CLAIM-VOCABULARY-SCHEMA"
    )

    assert code == 2
    assert output["accepted"] is False
    assert any(
        "claim_variable_vocabulary.json must contain valid JSON" in failure
        for failure in schema["failures"]
    )
    assert vocabulary_path.read_text(encoding="utf-8") == "{\n"


def test_rke_cli_source_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("source-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted_for_sandbox"] is True
    persisted = json.loads(
        (
            tmp_path / "registry/source_checks/source_registry_validation_report.json"
        ).read_text(encoding="utf-8")
    )
    assert output["accepted_for_production"] == persisted["accepted_for_production"]
    assert (
        tmp_path / "registry/source_checks/source_registry_validation_report.json"
    ).exists()


def test_rke_cli_source_status_reports_malformed_jsonl_rows(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    source_path = tmp_path / "registry/sources/central_bank_sources.jsonl"
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )

    code = main(("source-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted_for_sandbox"] is False
    assert output["failure_count"] >= 1
    assert any(
        any(
            "central_bank_sources.jsonl row" in failure
            and "must contain valid JSON" in failure
            for failure in record["failures"]
        )
        for record in output["records"]
    )


def test_rke_cli_source_text_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("source-text-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/compliance/source_text_redaction_report.json").exists()
    assert output["source_text_count"] == _redaction_source_text_count(tmp_path)


def test_rke_cli_source_text_status_reports_malformed_jsonl_rows(
    tmp_path: Path, capsys
):
    _copy_registry(tmp_path)
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8"
    )

    code = main(("source-text-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert output["malformed_source_row_count"] == 1
    assert any(
        "tushare_research_reports.jsonl row" in blocker
        for blocker in output["blockers"]
    )
    assert any("must contain valid JSON" in blocker for blocker in output["blockers"])


def test_rke_cli_promotion_status_writes_report(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("promotion-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["paper_trading_allowed"] is True
    assert output["staged_production_allowed"] is False
    assert output["production_allowed"] is False
    assert output["next_state"] == "paper_trading"
    next_actions = {action["action_id"]: action for action in output["next_actions"]}
    assert {
        "complete_manual_forecast_gold_review",
        "prepare_lockbox_after_upstream_manual_gates",
    } == set(next_actions)
    assert next_actions["complete_manual_forecast_gold_review"]["commands"][
        "inspect"
    ].startswith(RKE_OPERATOR_TMP_ENV_PREFIX)
    assert (
        "promotion-status --root . --no-write"
        in next_actions["complete_manual_forecast_gold_review"]["commands"][
            "check_promotion_after_review"
        ]
    )
    assert next_actions["complete_manual_forecast_gold_review"]["review_aids"][
        "fill_import_path"
    ] == "registry/review_batches/gold_set_reviewed.jsonl"
    assert next_actions["complete_manual_forecast_gold_review"][
        "field_contract"
    ]["optional_fields"] == ["review_notes"]
    assert (
        "review-progress --root . --actions-only --no-write --review-kind lockbox"
        in next_actions["prepare_lockbox_after_upstream_manual_gates"]["commands"][
            "inspect_lockbox_dependencies"
        ]
    )
    assert next_actions["prepare_lockbox_after_upstream_manual_gates"]["review_aids"][
        "footprint_review"
    ]["promotion_import_path"] == (
        "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
    )
    assert next_actions["prepare_lockbox_after_upstream_manual_gates"]["review_aids"][
        "lockbox"
    ]["fill_import_path"] == "registry/review_batches/lockbox_reviewed.json"
    assert "passed" in next_actions[
        "prepare_lockbox_after_upstream_manual_gates"
    ]["field_contract"]["lockbox"]["allowed_results"]
    assert "review_notes" in next_actions[
        "prepare_lockbox_after_upstream_manual_gates"
    ]["field_contract"]["footprint_review"]["required_fields"]
    assert (
        "promotion-dry-run --root ."
        in next_actions["prepare_lockbox_after_upstream_manual_gates"]["commands"][
            "promotion_dry_run_after_all_reviews"
        ]
    )
    assert (
        "--license-input"
        not in next_actions["prepare_lockbox_after_upstream_manual_gates"][
            "commands"
        ]["promotion_dry_run_after_all_reviews"]
    )
    assert (
        "build-license-review-import"
        not in next_actions["prepare_lockbox_after_upstream_manual_gates"][
            "commands"
        ]["promotion_dry_run_after_all_reviews"]
    )
    assert (tmp_path / "registry/promotion/rke_production_promotion_gate.json").exists()


def test_rke_cli_promotion_status_no_write_preserves_report(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    main(("promotion-status", "--root", str(tmp_path)))
    capsys.readouterr()
    report_path = tmp_path / "registry/promotion/rke_production_promotion_gate.json"
    before = report_path.read_text(encoding="utf-8")
    before_mtime = report_path.stat().st_mtime_ns

    code = main(("promotion-status", "--root", str(tmp_path), "--no-write"))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["paper_trading_allowed"] is True
    assert output["next_actions"]
    assert report_path.read_text(encoding="utf-8") == before
    assert report_path.stat().st_mtime_ns == before_mtime


def test_rke_cli_review_batches_writes_next_import_templates(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(
        (
            "review-batches",
            "--root",
            str(tmp_path),
            "--gold-batch-size",
            "11",
            "--license-batch-size",
            "9",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["status"]["ready_for_manual_review"] is True
    assert output["status"]["gold_set"]["exported_rows"] == 11
    assert (
        output["status"]["gold_set"]["full_import_template_path"]
        == "registry/review_batches/gold_set_full_import_template.jsonl"
    )
    assert (
        "registry/review_batches/gold_set_review_workbook.md"
        in output["status"]["generated_paths"]
    )
    assert output["status"]["source_license"]["exported_rows"] == 0
    assert (
        "registry/review_batches/source_license_review_workbook.md"
        in output["status"]["generated_paths"]
    )
    assert (
        tmp_path / "registry/review_batches/manual_review_batch_status.json"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/gold_set_next_import_template.jsonl"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/gold_set_full_import_template.jsonl"
    ).exists()
    assert (tmp_path / "registry/review_batches/gold_set_review_workbook.md").exists()
    assert (
        tmp_path / "registry/review_batches/source_license_next_import_template.jsonl"
    ).exists()
    assert (
        tmp_path / "registry/review_batches/source_license_review_workbook.md"
    ).exists()


def test_rke_cli_fetch_tushare_reports_passes_query_args(
    monkeypatch, tmp_path: Path, capsys
):
    captured = {}

    def fake_refresh(root, **kwargs):
        captured["root"] = str(root)
        captured.update(kwargs)
        return TushareResearchReportRefreshResult(
            root=str(root),
            source_rows=3,
            rows_with_abstract=3,
            skipped_empty_abstract_rows=0,
            gold_candidate_rows=3,
            gold_review_template_updated=True,
            license_review_template_updated=True,
            publish_date_min="2026-06-01",
            publish_date_max="2026-06-05",
            report_type_counts={"个股研报": 2, "行业研报": 1},
            query_key_counts={"600519.SH": 1, "300750.SZ": 1, "银行": 1},
            completion_ready_for_broad_rollout=False,
            manifest_valid=True,
            outputs={"source": "registry/sources/tushare_research_reports.jsonl"},
        )

    monkeypatch.setattr(
        "mosaic.rke.cli.refresh_tushare_research_report_registry", fake_refresh
    )

    code = main(
        (
            "fetch-tushare-reports",
            "--root",
            str(tmp_path),
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-05",
            "--stock-code",
            "600519.SH,300750.SZ",
            "--industry-keyword",
            "银行",
            "--report-type",
            "个股研报,行业研报",
            "--max-reports-per-query",
            "42",
            "--stock-query-batch-size",
            "2",
            "--date-chunk-days",
            "7",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["source_rows"] == 3
    assert captured["root"] == str(tmp_path)
    assert captured["stock_codes"] == ("600519.SH", "300750.SZ")
    assert captured["industry_keywords"] == ("银行",)
    assert captured["report_types"] == ("个股研报", "行业研报")
    assert captured["start_date"] == "2026-06-01"
    assert captured["end_date"] == "2026-06-05"
    assert captured["input_path"] is None
    assert captured["max_reports_per_query"] == 42
    assert captured["stock_query_batch_size"] == 2
    assert captured["date_chunk_days"] == 7
    assert captured["corpus_profile"] is None
    assert captured["preserve_review_templates"] is True


def test_rke_cli_fetch_tushare_reports_p9_profile_defaults_date_chunk(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    captured = {}

    def fake_refresh(root, **kwargs):
        captured["root"] = str(root)
        captured.update(kwargs)
        return TushareResearchReportRefreshResult(
            root=str(root),
            source_rows=6,
            rows_with_abstract=6,
            skipped_empty_abstract_rows=0,
            gold_candidate_rows=6,
            gold_review_template_updated=True,
            license_review_template_updated=True,
            publish_date_min="2026-06-01",
            publish_date_max="2026-06-01",
            report_type_counts={"个股研报": 1, "行业研报": 1},
            query_key_counts={"000001.SZ": 1, "半导体": 1},
            completion_ready_for_broad_rollout=False,
            manifest_valid=True,
            outputs={"source": "registry/sources/tushare_research_reports.jsonl"},
            corpus_profile=P9_REPORT_INTELLIGENCE_CORPUS_PROFILE,
        )

    monkeypatch.setattr(
        "mosaic.rke.cli.refresh_tushare_research_report_registry", fake_refresh
    )

    code = main(
        (
            "fetch-tushare-reports",
            "--root",
            str(tmp_path),
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-01",
            "--p9-profile",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["corpus_profile"] == P9_REPORT_INTELLIGENCE_CORPUS_PROFILE
    assert captured["corpus_profile"] == P9_REPORT_INTELLIGENCE_CORPUS_PROFILE
    assert captured["date_chunk_days"] == 7
    assert captured["report_types"] == ()


def test_rke_cli_fetch_tushare_reports_accepts_local_input_path(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    captured = {}

    def fake_refresh(root, **kwargs):
        captured["root"] = str(root)
        captured.update(kwargs)
        return TushareResearchReportRefreshResult(
            root=str(root),
            source_rows=2,
            rows_with_abstract=2,
            skipped_empty_abstract_rows=0,
            gold_candidate_rows=2,
            gold_review_template_updated=True,
            license_review_template_updated=True,
            publish_date_min="2026-06-02",
            publish_date_max="2026-06-03",
            report_type_counts={"个股研报": 1, "行业研报": 1},
            query_key_counts={"000001.SZ": 1, "半导体": 1},
            completion_ready_for_broad_rollout=False,
            manifest_valid=True,
            outputs={"source": "registry/sources/tushare_research_reports.jsonl"},
        )

    monkeypatch.setattr(
        "mosaic.rke.cli.refresh_tushare_research_report_registry", fake_refresh
    )
    local_input = tmp_path / "reports.csv"
    local_input.write_text("trade_date,title,abstr\n20260603,a,b\n", encoding="utf-8")

    code = main(
        (
            "fetch-tushare-reports",
            "--root",
            str(tmp_path),
            "--input-path",
            str(local_input),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["source_rows"] == 2
    assert captured["root"] == str(tmp_path)
    assert captured["input_path"] == str(local_input)
    assert captured["start_date"] is None
    assert captured["end_date"] is None
    assert captured["stock_codes"] == ()
    assert captured["industry_keywords"] == ()
    assert captured["report_types"] == ()
    assert captured["date_chunk_days"] == 31
    assert captured["corpus_profile"] is None


def test_rke_cli_evolution_readiness_alias_rebuilds_gate(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    captured = {}

    def fake_write_gate(registry_dir, *, run_id):
        captured["gate_registry_dir"] = str(registry_dir)
        captured["gate_run_id"] = run_id
        return {
            "evolution_readiness_gate": "registry/report_intelligence/evolution_readiness_gate.json",
            "gate_status": "blocked",
            "blocker_count": 1,
            "blockers": ["manual_review_pending"],
            "blocked_check_ids": ["RI-EVOL-05"],
            "passed_check_ids": ["RI-EVOL-01"],
            "blocked_checks": [
                {"check_id": "RI-EVOL-05", "blockers": ["manual_review_pending"]}
            ],
            "input_load_blockers": [],
        }

    def fake_write_mutations(registry_dir, *, run_id):
        captured["mutations_registry_dir"] = str(registry_dir)
        captured["mutations_run_id"] = run_id
        return {
            "prompt_mutation_candidates": "registry/report_intelligence/prompt_mutation_candidates.jsonl",
            "prompt_mutation_candidate_count": 2,
        }

    monkeypatch.setattr(
        "mosaic.rke.cli.write_report_intelligence_evolution_readiness_gate",
        fake_write_gate,
    )
    monkeypatch.setattr(
        "mosaic.rke.cli.write_report_intelligence_prompt_mutation_candidates",
        fake_write_mutations,
    )

    code = main(
        (
            "evolution-readiness",
            "--root",
            str(tmp_path),
            "--run-id",
            "RIR-ALIAS-TEST",
            "--refresh-prompt-mutations",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert captured == {
        "gate_registry_dir": str(tmp_path / "registry/report_intelligence"),
        "gate_run_id": "RIR-ALIAS-TEST",
        "mutations_registry_dir": str(tmp_path / "registry/report_intelligence"),
        "mutations_run_id": "RIR-ALIAS-TEST",
    }
    assert output["gate_status"] == "blocked"
    assert output["blocker_count"] == 1
    assert output["blocked_check_ids"] == ["RI-EVOL-05"]
    assert output["blocked_checks"] == [
        {"check_id": "RI-EVOL-05", "blockers": ["manual_review_pending"]}
    ]
    assert output["prompt_mutation_candidate_count"] == 2


def test_rke_cli_evolution_readiness_no_write_uses_read_only_gate(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    captured = {}

    def fake_write_gate(registry_dir, *, run_id, write=True):
        captured["registry_dir"] = str(registry_dir)
        captured["run_id"] = run_id
        captured["write"] = write
        return {
            "evolution_readiness_gate": "registry/report_intelligence/evolution_readiness_gate.json",
            "gate_status": "blocked",
            "blocker_count": 1,
            "blockers": ["manual_review_pending"],
            "blocked_check_ids": ["RI-EVOL-05"],
            "passed_check_ids": ["RI-EVOL-01"],
            "blocked_checks": [
                {"check_id": "RI-EVOL-05", "blockers": ["manual_review_pending"]}
            ],
            "input_load_blockers": [],
            "written": write,
        }

    monkeypatch.setattr(
        "mosaic.rke.cli.write_report_intelligence_evolution_readiness_gate",
        fake_write_gate,
    )

    code = main(
        (
            "evolution-readiness",
            "--root",
            str(tmp_path),
            "--run-id",
            "RIR-READ-ONLY",
            "--no-write",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert captured == {
        "registry_dir": str(tmp_path / "registry/report_intelligence"),
        "run_id": "RIR-READ-ONLY",
        "write": False,
    }
    assert output["written"] is False
    assert output["blocked_check_ids"] == ["RI-EVOL-05"]


def test_rke_cli_evolution_readiness_no_write_rejects_prompt_mutation_refresh(
    tmp_path: Path,
    capsys,
):
    code = main(
        (
            "evolution-readiness",
            "--root",
            str(tmp_path),
            "--no-write",
            "--refresh-prompt-mutations",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert "--no-write cannot be combined" in output["blockers"][0]


def test_pyproject_exposes_mosaic_rke_console_script():
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'mosaic-rke = "mosaic.rke.cli:main"' in text
