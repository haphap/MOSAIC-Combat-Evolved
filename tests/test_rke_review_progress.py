from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import review_progress as review_progress_module
from mosaic.rke.cli import main
from mosaic.rke.lockbox_review_import import (
    LOCKBOX_BOOL_FIELDS,
    LOCKBOX_REQUIRED_FIELDS,
    LOCKBOX_RESULTS,
)
from mosaic.rke.license_policy_import import (
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    build_source_license_policy_template,
)
from mosaic.rke.manual_review_aids import (
    manual_review_aid_paths,
    manual_review_field_contract,
)
from mosaic.rke.manual_review_batches import (
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_PACKET_PATH,
    GOLD_REVIEW_TEMPLATE_PATH,
    GOLD_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_ASSIST_JSONL_PATH,
    GOLD_REVIEW_ASSIST_MD_PATH,
    GOLD_REVIEW_EVIDENCE_JSONL_PATH,
    GOLD_REVIEW_EVIDENCE_MD_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    write_gold_review_evidence,
    write_manual_review_batches,
)
from mosaic.rke.manual_review_import import (
    GOLD_BOOL_FIELDS,
    LICENSE_IMPORTED_FIELDS,
    TARGET_ROW_HASH_FIELD,
    review_row_fingerprint,
)
from mosaic.rke.operator_handoff import (
    LOCKBOX_REVIEWED_IMPORT_PATH,
    build_lockbox_review_import_template,
)
from mosaic.rke.report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
    ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
)
from mosaic.rke.review_progress import (
    build_manual_review_action_queue,
    build_manual_review_progress,
    build_manual_review_progress_summary,
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
    for private_evidence in (
        dst_root / "registry/review_batches/gold_set_review_evidence.jsonl",
        dst_root
        / "registry/report_intelligence/analytical_footprint_review_evidence.jsonl",
    ):
        if private_evidence.exists():
            private_evidence.unlink()
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


def test_manual_review_field_contracts_match_import_validators():
    gold = manual_review_field_contract("gold_set")
    assert gold["boolean_fields"] == list(GOLD_BOOL_FIELDS)
    assert gold["required_fields"] == [
        "manual_claim_text",
        *GOLD_BOOL_FIELDS,
        "reviewer",
        "review_date",
    ]
    assert gold["optional_fields"] == ["review_notes"]

    footprint = manual_review_field_contract("footprint_review")
    assert footprint["boolean_fields"] == list(
        ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS
    )
    assert footprint["required_fields"] == list(
        ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS
    )
    assert footprint["optional_fields"] == []

    source_license = manual_review_field_contract("source_license")
    assert source_license["required_fields"] == list(LICENSE_IMPORTED_FIELDS[:-1])
    assert source_license["optional_fields"] == ["notes"]
    assert source_license["boolean_fields"] == list(LICENSE_IMPORTED_FIELDS[:2])

    lockbox = manual_review_field_contract("lockbox")
    assert lockbox["required_fields"] == [
        *LOCKBOX_REQUIRED_FIELDS,
        *LOCKBOX_BOOL_FIELDS,
    ]
    assert lockbox["boolean_fields"] == list(LOCKBOX_BOOL_FIELDS)
    assert lockbox["allowed_results"] == sorted(LOCKBOX_RESULTS - {"not_opened"})


def test_manual_review_aid_paths_match_artifact_constants():
    gold = manual_review_aid_paths("gold_set")
    assert gold["fill_import_path"] == GOLD_REVIEWED_IMPORT_PATH
    assert gold["promotion_import_path"] == GOLD_FULL_REVIEWED_IMPORT_PATH
    assert gold["assist_jsonl"] == GOLD_REVIEW_ASSIST_JSONL_PATH
    assert gold["assist_markdown"] == GOLD_REVIEW_ASSIST_MD_PATH
    assert gold["evidence_jsonl"] == GOLD_REVIEW_EVIDENCE_JSONL_PATH
    assert gold["evidence_markdown"] == GOLD_REVIEW_EVIDENCE_MD_PATH
    assert gold["batch_workbook_markdown"] == GOLD_REVIEW_WORKBOOK_MD_PATH

    footprint = manual_review_aid_paths("footprint_review")
    assert (
        footprint["fill_import_path"]
        == ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
    )
    assert (
        footprint["promotion_import_path"]
        == ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
    )
    assert (
        footprint["assist_jsonl"]
        == ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH
    )
    assert (
        footprint["assist_workbook_markdown"]
        == ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH
    )
    assert (
        footprint["evidence_jsonl"]
        == ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH
    )
    assert (
        footprint["evidence_markdown"]
        == ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH
    )

    source_license = manual_review_aid_paths("source_license")
    assert source_license["fill_policy_path"] == SOURCE_LICENSE_REVIEWED_POLICY_PATH
    assert source_license["policy_template_path"] == SOURCE_LICENSE_POLICY_TEMPLATE_PATH
    assert source_license["workbook_markdown"] == SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH

    lockbox = manual_review_aid_paths("lockbox")
    assert lockbox["fill_import_path"] == LOCKBOX_REVIEWED_IMPORT_PATH


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
    target_rows = _load_jsonl(root / GOLD_REVIEW_TEMPLATE_PATH)
    rows = []
    for target_row in target_rows:
        row = {
            "claim_id": str(target_row.get("claim_id") or ""),
            TARGET_ROW_HASH_FIELD: review_row_fingerprint(target_row),
            "source_id": str(target_row.get("source_id") or ""),
            "source_span_id": str(target_row.get("source_span_id") or ""),
            "document_id": str(
                target_row.get("document_id") or target_row.get("source_id") or ""
            ),
            "gold_set_domain": str(target_row.get("gold_set_domain") or "other"),
            "target_review_path": GOLD_REVIEW_TEMPLATE_PATH,
            "review_context_ref": GOLD_REVIEW_PACKET_PATH,
        }
        rows.append(row)
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
    source_license_gate = next(
        gate for gate in output["gates"] if gate["review_kind"] == "source_license"
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
    assert "--priority" in footprint_gate["next_batch_commands"]["prepare"]
    assert source_license_gate["next_batch_commands"] == {}
    assert len(gold_gate["batch_plan"]) >= 1
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
    gold_offsets = [batch["offset"] for batch in gold_gate["batch_plan"]]
    assert gold_offsets == sorted(gold_offsets)
    assert len(footprint_gate["batch_plan"]) == 22
    assert footprint_gate["batch_plan"][-1]["offset"] == 1050
    assert footprint_gate["batch_plan"][-1]["limit"] == 1
    assert (
        footprint_gate["batch_plan"][0]["mode"]
        == "priority_sorted_pending_batch_before_applying_any_batch"
    )
    assert "--priority" in footprint_gate["batch_plan"][0]["commands"]["prepare"]
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


def test_review_progress_reports_gold_quality_blockers_without_reapplying_stale_full_import(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    gold_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    row = _load_jsonl(gold_path)[0]
    row.update(
        {
            "manual_claim_text": "reviewed but low quality label",
            "claim_correct": True,
            "source_span_supports_claim": True,
            "direction_correct": False,
            "target_correct": True,
            "horizon_correct": True,
            "variable_mapping_correct": False,
            "unsupported_field_false_grounded": True,
            "reviewer": "reviewer-a",
            "review_date": "2026-06-06",
            "review_notes": "complete row with failing quality metrics",
        }
    )
    _write_jsonl(gold_path, [row])
    stale_import = dict(row)
    stale_import["claim_id"] = "GOLD-STALE-IMPORT-ROW"
    _write_jsonl(tmp_path / GOLD_FULL_REVIEWED_IMPORT_PATH, [stale_import])
    stale_batch_row = dict(row)
    stale_batch_row[TARGET_ROW_HASH_FIELD] = "sha256:stale-current-batch"
    _write_jsonl(tmp_path / GOLD_REVIEWED_IMPORT_PATH, [stale_batch_row])

    report = build_manual_review_progress(tmp_path)
    summary = build_manual_review_progress_summary(report)
    gold_gate = next(gate for gate in report.gates if gate.review_kind == "gold_set")
    gold_summary = next(
        gate for gate in summary["gates"] if gate["review_kind"] == "gold_set"
    )

    assert gold_gate.pending_rows == 0
    assert gold_gate.complete_rows == 1
    assert gold_gate.simulation_accepted is False
    assert any("gold set requires >= 50 documents" in blocker for blocker in gold_gate.blockers)
    assert not any("claim_id missing from target review template" in blocker for blocker in gold_gate.blockers)
    assert (
        gold_gate.current_batch_status["target_status"][
            "target_row_hash_mismatch_count"
        ]
        == 1
    )
    assert gold_summary["next_manual_action"] == "address_quality_gate_blockers"
    assert gold_summary["quality_gap_targets"]["sample_size_documents"][
        "minimum_additional_count"
    ] == 49
    assert gold_summary["quality_gap_targets"]["metrics"]["direction_accuracy"][
        "minimum_additional_pass_count_if_denominator_unchanged"
    ] == 1
    assert set(gold_summary["next_batch_commands"]) == {
        "assist",
        "backfill_dry_run",
        "backfill_write",
        "dry_run",
        "evidence",
        "expand_candidate_review_rows",
        "prepare_expanded_batch",
        "prepare_reviewed_failures",
        "refresh_source_candidates",
    }
    assert "--reviewed-failures" in gold_summary["next_batch_commands"][
        "prepare_reviewed_failures"
    ]

    action_queue = build_manual_review_action_queue(report)
    gold_action = next(
        action
        for action in action_queue["actions"]
        if action["review_kind"] == "gold_set"
    )
    assert gold_action["action_state"] == "needs_quality_gate_work"
    assert gold_action["can_run_now"] is True
    assert gold_action["quality_gap_targets"]["sample_size_claims"][
        "minimum_additional_count"
    ] == 99
    assert set(gold_action["commands"]) == {
        "assist",
        "backfill_dry_run",
        "backfill_write",
        "dry_run",
        "evidence",
        "expand_candidate_review_rows",
        "prepare_expanded_batch",
        "prepare_reviewed_failures",
        "refresh_source_candidates",
    }
    assert "--ensure-candidate-review-rows" in gold_action["commands"][
        "expand_candidate_review_rows"
    ]
    assert "--refresh-candidates-from-source" in gold_action["commands"][
        "expand_candidate_review_rows"
    ]


def test_review_progress_prioritizes_pending_gold_quality_batch_fields(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    gold_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    row = _load_jsonl(gold_path)[0]
    row.update(
        {
            "manual_claim_text": "reviewed but low quality label",
            "claim_correct": True,
            "source_span_supports_claim": True,
            "direction_correct": False,
            "target_correct": True,
            "horizon_correct": True,
            "variable_mapping_correct": False,
            "unsupported_field_false_grounded": True,
            "reviewer": "reviewer-a",
            "review_date": "2026-06-06",
            "review_notes": "complete row with failing quality metrics",
        }
    )
    _write_jsonl(gold_path, [row])
    pending_import = {
        "claim_id": row["claim_id"],
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "source_id": row.get("source_id", ""),
        "source_span_id": row.get("source_span_id", ""),
        "document_id": row.get("document_id") or row.get("source_id", ""),
        "review_context_ref": GOLD_REVIEW_PACKET_PATH,
        "target_review_path": GOLD_REVIEW_TEMPLATE_PATH,
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
    _write_jsonl(tmp_path / GOLD_REVIEWED_IMPORT_PATH, [pending_import])
    evidence = write_gold_review_evidence(
        tmp_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
    )

    report = build_manual_review_progress(tmp_path)
    action_queue = build_manual_review_action_queue(report)
    gold_action = next(
        action
        for action in action_queue["actions"]
        if action["review_kind"] == "gold_set"
    )

    assert evidence["blockers"] == 0
    assert gold_action["next_manual_action"] == (
        "fill_current_batch_review_fields_then_dry_run"
    )
    assert gold_action["action_state"] == "needs_human_review_fields"
    assert gold_action["current_batch_pending_rows"] == 1
    assert set(gold_action["commands"]) == {
        "assist",
        "backfill_dry_run",
        "backfill_write",
        "dry_run",
        "evidence",
    }
    assert (
        "mosaic-rke write-gold-review-evidence --root . --limit 1 --offset 0 "
        "--review-input registry/review_batches/gold_set_reviewed.jsonl"
        in gold_action["commands"]["evidence"]
    )
    assert "prepare_reviewed_failures" not in gold_action["commands"]


def test_review_progress_summary_omits_full_batch_plan(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("review-progress", "--root", str(tmp_path), "--summary"))
    output = json.loads(capsys.readouterr().out)
    encoded = json.dumps(output, ensure_ascii=False)
    gold_gate = next(gate for gate in output["gates"] if gate["review_kind"] == "gold_set")
    lockbox_gate = next(
        gate for gate in output["gates"] if gate["review_kind"] == "lockbox"
    )

    assert code == 2
    assert output["ready_for_promotion_dry_run"] is False
    assert output["gate_count"] == 4
    assert output["blocker_count"] > 0
    assert "blockers" not in output
    assert "batch_plan" not in encoded
    assert gold_gate["blocker_count"] > 0
    assert gold_gate["batch_overview"]["batch_count"] >= 1
    assert gold_gate["batch_overview"]["next_batch_offset"] == 0
    assert gold_gate["batch_overview"]["next_batch_limit"] == 50
    assert (
        gold_gate["batch_overview"]["current_batch_path"]
        == "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert gold_gate["batch_overview"]["rerun_review_progress_after_batch_apply"] is True
    assert gold_gate["next_manual_action"] in {
        "fill_current_batch_review_fields_then_dry_run",
        "prepare_next_review_batch",
    }
    assert gold_gate["next_batch_commands"]["prepare"].startswith(
        RKE_OPERATOR_TMP_ENV_PREFIX
    )
    assert gold_gate["promotion_commands"]["dry_run"].startswith(
        RKE_OPERATOR_TMP_ENV_PREFIX
    )
    footprint_gate = next(
        gate for gate in output["gates"] if gate["review_kind"] == "footprint_review"
    )
    assert footprint_gate["batch_overview"]["batch_count"] == 22
    assert footprint_gate["batch_overview"]["final_batch_offset"] == 1050
    assert footprint_gate["batch_overview"]["final_batch_limit"] == 1
    assert lockbox_gate["next_manual_action"] == "wait_for_prior_manual_gates"
    assert lockbox_gate["batch_overview"] == {}
    assert lockbox_gate["blocked_by_review_kinds"] == [
        "gold_set",
        "footprint_review",
        "source_license",
    ]


def test_review_progress_no_write_does_not_rewrite_artifacts(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)
    progress_path = tmp_path / "registry/review_batches/manual_review_progress_report.json"
    runbook_path = tmp_path / "registry/review_batches/manual_review_runbook.md"
    if progress_path.exists():
        progress_path.unlink()
    if runbook_path.exists():
        runbook_path.unlink()

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--summary",
            "--no-write",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["path"].endswith(
        "registry/review_batches/manual_review_progress_report.json"
    )
    assert output["runbook_path"].endswith(
        "registry/review_batches/manual_review_runbook.md"
    )
    assert not progress_path.exists()
    assert not runbook_path.exists()


def test_review_progress_summary_filters_review_kind(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--summary",
            "--no-write",
            "--review-kind",
            "footprint_review",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["ready_for_promotion_dry_run"] is False
    assert output["total_ready_for_promotion_dry_run"] is False
    assert output["gate_count"] == 1
    assert output["total_gate_count"] == 4
    assert output["reported_review_kinds"] == ["footprint_review"]
    assert [gate["review_kind"] for gate in output["gates"]] == ["footprint_review"]
    assert "batch_plan" not in json.dumps(output, ensure_ascii=False)
    assert output["gates"][0]["next_manual_action"] in {
        "fill_current_batch_review_fields_then_dry_run",
        "prepare_next_review_batch",
    }


def test_review_progress_summary_filter_exit_uses_selected_gate(
    tmp_path: Path,
    capsys,
):
    _copy_registry_without_license_reset(tmp_path)
    for incomplete_gate_path in (
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        tmp_path
        / "registry/report_intelligence/analytical_footprint_reviewed.jsonl",
        tmp_path / "registry/review_batches/lockbox_reviewed.json",
    ):
        if incomplete_gate_path.exists():
            incomplete_gate_path.unlink()

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--summary",
            "--no-write",
            "--review-kind",
            "source_license",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ready_for_promotion_dry_run"] is True
    assert output["total_ready_for_promotion_dry_run"] is False
    assert output["blocker_count"] == 0
    assert output["gate_count"] == 1
    assert output["reported_review_kinds"] == ["source_license"]
    assert output["gates"][0]["ready_for_promotion"] is True
    assert output["gates"][0]["next_batch_commands"] == {}


def test_review_progress_summary_reports_lockbox_dependencies(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--summary",
            "--no-write",
            "--review-kind",
            "lockbox",
        )
    )
    output = json.loads(capsys.readouterr().out)
    lockbox_gate = output["gates"][0]

    assert code == 2
    assert lockbox_gate["review_kind"] == "lockbox"
    assert lockbox_gate["next_manual_action"] == "wait_for_prior_manual_gates"
    assert lockbox_gate["blocked_by_review_kinds"] == [
        "gold_set",
        "footprint_review",
        "source_license",
    ]


def test_review_progress_actions_only_reports_next_manual_work(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)

    code = main(("review-progress", "--root", str(tmp_path), "--actions-only", "--no-write"))
    output = json.loads(capsys.readouterr().out)
    encoded = json.dumps(output, ensure_ascii=False)
    actions = {action["review_kind"]: action for action in output["actions"]}

    assert code == 2
    assert output["ready_for_promotion_dry_run"] is False
    assert output["action_count"] == 4
    assert output["total_gate_count"] == 4
    assert "gates" not in output
    assert "batch_plan" not in encoded
    assert actions["gold_set"]["action_rank"] == 1
    assert actions["gold_set"]["next_manual_action"] in {
        "fill_current_batch_review_fields_then_dry_run",
        "prepare_next_review_batch",
    }
    assert actions["gold_set"]["action_state"] in {
        "needs_human_review_fields",
        "needs_prepare",
    }
    assert (
        actions["gold_set"]["current_batch_path"]
        == "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert actions["gold_set"]["batch_overview"]["batch_count"] >= 1
    assert actions["gold_set"]["batch_overview"]["next_batch_limit"] == 50
    assert (
        actions["gold_set"]["batch_overview"]["current_batch_path"]
        == "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert (
        actions["gold_set"]["manual_input_path"]
        == "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert (
        actions["gold_set"]["promotion_input_path"]
        == "registry/review_batches/gold_set_full_reviewed.jsonl"
    )
    assert actions["gold_set"]["can_run_now"] is True
    assert actions["gold_set"]["blocks_promotion"] is True
    assert actions["gold_set"]["review_aids"]["policy"] == (
        "private_review_aids_only_not_import_files"
    )
    assert actions["gold_set"]["review_aids"]["assist_markdown"] == (
        "registry/review_batches/gold_set_review_assist.md"
    )
    assert actions["gold_set"]["review_aids"]["evidence_markdown"] == (
        "registry/review_batches/gold_set_review_evidence.md"
    )
    assert actions["gold_set"]["review_aids"]["fill_import_path"] == (
        "registry/review_batches/gold_set_reviewed.jsonl"
    )
    assert "manual_claim_text" in actions["gold_set"]["field_contract"][
        "required_fields"
    ]
    assert actions["gold_set"]["field_contract"]["optional_fields"] == [
        "review_notes"
    ]
    assert actions["gold_set"]["field_contract"]["boolean_allowed_values"] == [
        True,
        False,
    ]
    if actions["gold_set"]["action_state"] == "needs_human_review_fields":
        assert actions["gold_set"]["commands"]["dry_run"].startswith(
            RKE_OPERATOR_TMP_ENV_PREFIX
        )
        assert "evidence" in actions["gold_set"]["commands"]
        assert "prepare" not in actions["gold_set"]["commands"]
    else:
        assert actions["gold_set"]["commands"]["prepare"].startswith(
            RKE_OPERATOR_TMP_ENV_PREFIX
        )
        assert "dry_run" not in actions["gold_set"]["commands"]
    assert "apply" not in actions["gold_set"]["commands"]
    assert actions["footprint_review"]["next_manual_action"] in {
        "fill_current_batch_review_fields_then_dry_run",
        "prepare_next_review_batch",
    }
    assert actions["footprint_review"]["batch_overview"]["batch_count"] == 22
    assert actions["footprint_review"]["batch_overview"]["final_batch_limit"] == 1
    assert actions["footprint_review"]["review_aids"]["policy"] == (
        "private_review_aids_only_not_import_files"
    )
    assert actions["footprint_review"]["review_aids"]["evidence_markdown"] == (
        "registry/report_intelligence/analytical_footprint_review_evidence.md"
    )
    assert actions["footprint_review"]["review_aids"]["assist_workbook_markdown"] == (
        "registry/report_intelligence/analytical_footprint_review_workbook.md"
    )
    assert "review_notes" in actions["footprint_review"]["field_contract"][
        "required_fields"
    ]
    assert actions["footprint_review"]["field_contract"]["optional_fields"] == []
    assert "metric_mapping_correct" in actions["footprint_review"][
        "field_contract"
    ]["boolean_fields"]
    assert "apply" not in actions["footprint_review"]["commands"]
    assert (
        actions["source_license"]["next_manual_action"]
        == "review_or_apply_source_license_policy"
    )
    assert actions["source_license"]["action_state"] == "needs_policy_review"
    assert actions["source_license"]["can_run_now"] is True
    assert (
        actions["source_license"]["manual_input_path"]
        == "registry/review_batches/source_license_policy_reviewed.json"
    )
    assert set(actions["source_license"]["commands"]) == {"prepare", "dry_run"}
    assert actions["lockbox"]["next_manual_action"] == "wait_for_prior_manual_gates"
    assert actions["lockbox"]["action_state"] == "waiting_on_dependencies"
    assert actions["lockbox"]["can_run_now"] is False
    assert actions["lockbox"]["blocks_promotion"] is True
    assert actions["lockbox"]["batch_overview"] == {}
    assert actions["lockbox"]["blocked_by_review_kinds"] == [
        "gold_set",
        "footprint_review",
        "source_license",
    ]
    assert actions["lockbox"]["review_aids"] == {
        "fill_import_path": "registry/review_batches/lockbox_reviewed.json",
        "policy": "wait_for_prior_manual_gates_before_opening",
    }
    assert actions["lockbox"]["field_contract"]["policy"] == (
        "only_fill_after_upstream_manual_gates_are_ready"
    )
    assert "opened_by" in actions["lockbox"]["field_contract"]["required_fields"]
    assert "passed" in actions["lockbox"]["field_contract"]["allowed_results"]
    assert actions["lockbox"]["commands"] == {}


def test_review_progress_backfills_footprint_quality_gaps_from_template(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    template_path = tmp_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    summary_path = tmp_path / ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH
    _write_jsonl(
        template_path,
        [
            {
                "footprint_id": "FP-1",
                "target_row_hash": "sha256:" + "0" * 64,
                "review_context_ref": "registry/report_intelligence/analytical_footprints.jsonl",
                "target_review_path": ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": False,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "reviewer": "reviewer-a",
                "review_date": "2026-06-15",
                "review_notes": "fixture complete but metric mapping failed",
            }
        ],
    )
    summary_path.write_text(
        json.dumps(
            {
                "accepted": False,
                "review_complete": True,
                "quality_gate_passed": False,
                "total_rows": 1,
                "complete_rows": 1,
                "pending_rows": 0,
                "blockers": ["metric_mapping_accuracy below threshold"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_manual_review_progress(tmp_path)
    queue = build_manual_review_action_queue(report, review_kinds=("footprint_review",))
    action = queue["actions"][0]
    metric_gap = action["quality_gap_targets"]["metrics"]["metric_mapping_accuracy"]

    assert action["review_kind"] == "footprint_review"
    assert metric_gap["current_pass_count"] == 0
    assert (
        metric_gap["minimum_additional_pass_count_if_denominator_unchanged"]
        == metric_gap["required_pass_count"]
    )


def test_review_progress_actions_only_filters_review_kind(
    tmp_path: Path,
    capsys,
):
    _copy_registry_without_license_reset(tmp_path)

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--actions-only",
            "--no-write",
            "--review-kind",
            "source_license",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ready_for_promotion_dry_run"] is True
    assert output["total_ready_for_promotion_dry_run"] is False
    assert output["reported_review_kinds"] == ["source_license"]
    assert [action["review_kind"] for action in output["actions"]] == ["source_license"]
    assert output["actions"][0]["next_manual_action"] == "already_applied"
    assert output["actions"][0]["action_state"] == "already_applied"
    assert output["actions"][0]["can_run_now"] is False
    assert output["actions"][0]["commands"] == {}


def test_review_progress_actions_only_filters_action_state(
    tmp_path: Path,
    capsys,
):
    _copy_registry(tmp_path)
    _write_json(
        tmp_path / "registry/review_batches/source_license_policy_reviewed.json",
        _accepted_license_policy(tmp_path),
    )

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--actions-only",
            "--no-write",
            "--action-state",
            "ready_to_apply",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ready_for_promotion_dry_run"] is True
    assert output["total_ready_for_promotion_dry_run"] is False
    assert output["reported_action_states"] == ["ready_to_apply"]
    assert output["action_count"] >= 1
    assert {action["action_state"] for action in output["actions"]} == {"ready_to_apply"}
    assert all(action["can_run_now"] is True for action in output["actions"])
    assert {action["review_kind"] for action in output["actions"]} == {"source_license"}
    assert set(output["actions"][0]["commands"]) == {"dry_run", "apply"}


def test_review_progress_action_state_requires_actions_only(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--summary",
            "--action-state",
            "needs_human_review_fields",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output == {
        "accepted": False,
        "blockers": ["--action-state requires --actions-only"],
    }


def test_manual_review_action_queue_is_public_safe_compact(tmp_path: Path):
    _copy_registry(tmp_path)
    report = build_manual_review_progress(tmp_path)

    action_queue = build_manual_review_action_queue(report)
    encoded = json.dumps(action_queue, ensure_ascii=False)

    assert action_queue["action_count"] == 4
    assert "gates" not in action_queue
    assert "batch_plan" not in encoded
    assert "source_span_ids" not in encoded
    assert "source_text" not in encoded
    assert "abstract" not in encoded
    assert "pdf_url" not in encoded
    assert "markdown_path" not in encoded


def test_review_progress_review_kind_requires_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(
        (
            "review-progress",
            "--root",
            str(tmp_path),
            "--review-kind",
            "gold_set",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output == {
        "accepted": False,
        "blockers": ["--review-kind requires --summary or --actions-only"],
    }


def test_review_progress_temp_copy_skips_private_raw_sources(tmp_path: Path):
    _copy_registry(tmp_path)
    private_cache_dir = tmp_path / "registry/report_intelligence/markdown"
    private_cache_dir.mkdir(parents=True, exist_ok=True)
    (private_cache_dir / "sample.md").write_text("private markdown", encoding="utf-8")
    temp_root = tmp_path / "temp-copy"

    review_progress_module._copy_registry(tmp_path, temp_root)

    assert not (
        temp_root / "registry/sources/tushare_research_reports.jsonl"
    ).exists()
    assert not (
        temp_root / "registry/sources/tushare_research_reports.manifest.json"
    ).exists()
    assert not (
        temp_root / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    ).exists()
    for relative_path in (
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/markdown",
        "registry/report_intelligence/processing_status.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
    ):
        assert not (temp_root / relative_path).exists()
    assert (
        temp_root
        / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    ).exists()
    assert (
        temp_root
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    ).exists()


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
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_review_evidence.jsonl",
        [
            {
                "claim_id": row["claim_id"],
                "target_row_hash": row["target_row_hash"],
            }
            for row in gold_rows[:2]
        ],
    )
    _write_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_evidence.jsonl",
        [
            {
                "footprint_id": row["footprint_id"],
                "target_row_hash": row["target_row_hash"],
            }
            for row in footprint_rows
        ],
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
    summary = build_manual_review_progress_summary(report)

    assert gold_batch["exists"] is True
    assert gold_batch["rows"] == 2
    assert gold_batch["complete_rows"] == 1
    assert gold_batch["pending_rows"] == 1
    assert gold_batch["missing_required_fields"] == {
        "claim_correct": 1,
        "manual_claim_text": 1,
    }
    assert gold_batch["evidence_status"]["aligned"] is True
    assert gold_batch["evidence_status"]["covered_review_rows"] == 2
    assert gold_batch["evidence_status"]["review_input_rows"] == 2
    assert gold_batch["evidence_status"]["same_order"] is True
    assert gold_batch["target_status"]["aligned"] is True
    assert footprint_batch["exists"] is True
    assert footprint_batch["rows"] == 2
    assert footprint_batch["complete_rows"] == 0
    assert footprint_batch["pending_rows"] == 2
    assert footprint_batch["missing_required_fields"] == {
        "metric_mapping_correct": 1,
        "review_notes": 1,
    }
    assert footprint_batch["evidence_status"]["aligned"] is True
    assert footprint_batch["evidence_status"]["covered_review_rows"] == 2
    assert footprint_batch["evidence_status"]["review_input_rows"] == 2
    assert footprint_batch["evidence_status"]["same_order"] is True
    assert footprint_batch["target_status"]["aligned"] is True
    summary_gold = next(
        gate for gate in summary["gates"] if gate["review_kind"] == "gold_set"
    )
    summary_footprint = next(
        gate for gate in summary["gates"] if gate["review_kind"] == "footprint_review"
    )
    assert "batch_plan" not in json.dumps(summary, ensure_ascii=False)
    assert summary_gold["current_batch_status"]["evidence_status"]["aligned"] is True
    assert (
        summary_footprint["current_batch_status"]["evidence_status"][
            "covered_review_rows"
        ]
        == 2
    )
    assert (
        summary_footprint["current_batch_status"]["target_status"]["aligned"]
        is True
    )
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
    assert "Evidence alignment:" in markdown
    assert "covered: 2/2" in markdown
    assert "aligned: true" in markdown
    assert "`open_count`=1" in markdown
    assert "fixture approval" not in markdown
    assert "operator-only scratch text" not in markdown


def test_review_progress_evidence_alignment_counts_missing_ids(tmp_path: Path):
    _copy_registry(tmp_path)
    gold_rows = _accepted_gold_rows(tmp_path)[:2]
    gold_rows[1]["claim_id"] = ""
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_reviewed.jsonl",
        gold_rows,
    )
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_review_evidence.jsonl",
        [
            {
                "claim_id": gold_rows[0]["claim_id"],
                "target_row_hash": gold_rows[0]["target_row_hash"],
            }
        ],
    )

    report = build_manual_review_progress(tmp_path)
    gold_gate = next(gate for gate in report.gates if gate.review_kind == "gold_set")
    evidence_status = gold_gate.current_batch_status["evidence_status"]

    assert evidence_status["aligned"] is False
    assert evidence_status["covered_review_rows"] == 1
    assert evidence_status["missing_review_rows"] == 1
    assert evidence_status["same_order"] is True


def test_review_progress_reports_stale_footprint_batch_hashes(tmp_path: Path):
    _copy_registry(tmp_path)
    footprint_rows = _accepted_footprint_rows(tmp_path)[:2]
    _write_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprint_review_batch.jsonl",
        footprint_rows,
    )
    _write_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_evidence.jsonl",
        [
            {
                "footprint_id": row["footprint_id"],
                "target_row_hash": row["target_row_hash"],
            }
            for row in footprint_rows
        ],
    )
    template_path = (
        tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    target_rows = _load_jsonl(template_path)
    target_rows[0]["target_row_hash"] = "sha256:changed"
    _write_jsonl(template_path, target_rows)

    report = build_manual_review_progress(tmp_path)
    footprint_gate = next(
        gate for gate in report.gates if gate.review_kind == "footprint_review"
    )
    action_queue = build_manual_review_action_queue(
        report,
        review_kinds=("footprint_review",),
    )
    action = action_queue["actions"][0]
    target_status = footprint_gate.current_batch_status["target_status"]

    assert target_status["aligned"] is False
    assert target_status["target_row_hash_mismatch_count"] == 1
    assert footprint_gate.current_batch_status["evidence_status"]["aligned"] is True
    assert action["next_manual_action"] == "prepare_next_review_batch"
    assert action["action_state"] == "needs_prepare"
    assert action["batch_overview"]["current_batch_target_aligned"] is False
    assert action["batch_overview"]["current_batch_target_hash_mismatch_count"] == 1


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
        "Batch 1: pending rows 1-50; limit=50; offset=0; "
        "batch input=`registry/review_batches/gold_set_reviewed.jsonl`"
        in markdown
    )
    assert (
            "Batch 22: pending rows 1051-1051; limit=1; offset=1050; "
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
    assert "Evidence alignment:" in markdown
    assert "mosaic-rke prepare-footprint-review --root ." in markdown
    assert "prepare-footprint-review --root . --limit 50 --offset 0 --priority" in markdown
    assert (
        "mosaic-rke write-footprint-review-assist --root . --review-input "
        "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
        in markdown
    )
    assert (
        "mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 "
        "--review-input registry/report_intelligence/analytical_footprint_review_batch.jsonl"
        in markdown
    )
    assert "mosaic-rke apply-footprint-review --root . --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run" in markdown
    assert "mosaic-rke prepare-license-policy-review --root ." in markdown
    assert "mosaic-rke prepare-lockbox-review --root ." in markdown
    assert "Lockbox dependency status: waiting_on gold_set, footprint_review, source_license" in markdown
    assert "Lockbox: wait for upstream gates before running" in markdown
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
    assert "## Manual Field Contracts" in markdown
    assert "### Gold-set review" in markdown
    assert "- Optional fields: `review_notes`" in markdown
    assert "### Analytical-footprint review" in markdown
    assert (
        "- Required fields: `footprint_correct`, `source_span_supports_footprint`, "
        "`metric_mapping_correct`"
        in markdown
    )
    assert "### Lockbox review" in markdown
    assert "- Allowed results: `failed`, `passed`" in markdown
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


def test_review_runbook_omits_license_input_when_source_license_already_applied(
    tmp_path: Path,
):
    _copy_registry_without_license_reset(tmp_path)

    report = build_manual_review_progress(tmp_path)
    markdown = render_manual_review_runbook_markdown(report)
    promotion_section = markdown.split("## Promotion Dry Run", 1)[1].split(
        "## Full Pending Batch Plan",
        1,
    )[0]

    assert "mosaic-rke promotion-dry-run --root ." in promotion_section
    assert "--license-input" not in promotion_section
    assert "build-license-review-import" not in promotion_section


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
    stale_batch_row = dict(target_row)
    stale_batch_row["manual_claim_text"] = ""
    stale_batch_row["claim_correct"] = None
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_reviewed.jsonl",
        [stale_batch_row],
    )

    report = build_manual_review_progress(tmp_path)
    gold = next(gate for gate in report.gates if gate.review_kind == "gold_set")
    action_queue = build_manual_review_action_queue(report, review_kinds=("gold_set",))
    action = action_queue["actions"][0]

    assert gold.ready_for_promotion is True
    assert gold.simulation_accepted is True
    assert gold.complete_rows == gold.target_rows
    assert gold.pending_rows == 0
    assert gold.blockers == ()
    assert action["action_state"] == "ready_to_apply"
    assert action["manual_input_path"] == "registry/review_batches/gold_set_full_reviewed.jsonl"
    assert action["current_batch_path"] == "registry/review_batches/gold_set_reviewed.jsonl"
    assert action["current_batch_pending_rows"] == 0
    assert action["current_batch_stale_after_promotion_ready"] is True
    assert action["missing_required_fields"] == {}
    assert action["evidence_aligned"] is None
    assert action["batch_overview"] == {
        "batch_count": 0,
        "current_batch_stale_after_promotion_ready": True,
        "pending_rows": 0,
        "promotion_input_path": "registry/review_batches/gold_set_full_reviewed.jsonl",
        "rerun_review_progress_after_batch_apply": False,
        "stale_current_batch_path": "registry/review_batches/gold_set_reviewed.jsonl",
        "stale_current_batch_pending_rows": 1,
    }


def test_review_progress_reports_partial_gold_scratch(tmp_path: Path):
    _copy_registry(tmp_path)
    accepted_rows = _accepted_gold_rows(tmp_path)
    partial_rows = accepted_rows[:50]
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_full_reviewed.jsonl",
        partial_rows,
    )
    current_batch_rows = []
    for row in accepted_rows[50:70]:
        pending = dict(row)
        pending.update(
            {
                "manual_claim_text": "",
                "claim_correct": None,
                "source_span_supports_claim": None,
                "direction_correct": None,
                "target_correct": None,
                "horizon_correct": None,
                "variable_mapping_correct": None,
                "unsupported_field_false_grounded": None,
                "reviewer": "",
                "review_date": "",
                "review_notes": "",
            }
        )
        current_batch_rows.append(pending)
    _write_jsonl(tmp_path / GOLD_REVIEWED_IMPORT_PATH, current_batch_rows)
    write_gold_review_evidence(tmp_path, review_input_path=GOLD_REVIEWED_IMPORT_PATH)

    report = build_manual_review_progress(tmp_path)
    gold = next(gate for gate in report.gates if gate.review_kind == "gold_set")
    action_queue = build_manual_review_action_queue(report, review_kinds=("gold_set",))
    action = action_queue["actions"][0]
    markdown = render_manual_review_runbook_markdown(report)

    assert not report.ready_for_promotion_dry_run
    assert gold.input_exists
    assert gold.simulation_accepted
    assert gold.complete_rows == 50
    assert gold.pending_rows == 450
    assert not gold.ready_for_promotion
    assert any("450 gold-set claim review rows still pending" in blocker for blocker in gold.blockers)
    assert action["action_state"] == "needs_human_review_fields"
    assert (
        action["post_current_batch_action"]
        == "apply_current_batch_then_rerun_review_progress"
    )
    assert "Current scratch covers 20 of 450 pending target rows" in action[
        "operator_hint"
    ]
    assert "prepare the remaining 430 rows" in action["operator_hint"]
    assert action["quality_gap_targets"]["sample_size_documents"][
        "minimum_additional_count"
    ] >= 0
    assert action["quality_gap_targets"]["sample_size_claims"][
        "minimum_additional_count"
    ] >= 0
    assert action["quality_gap_targets"]["metrics"]["direction_accuracy"][
        "current_rate"
    ] is not None
    assert action["quality_gap_targets"]["metrics"]["variable_mapping_accuracy"][
        "current_rate"
    ] is not None
    assert (
        "mosaic-rke write-gold-review-evidence --root . --limit 20 --offset 0 "
        "--review-input registry/review_batches/gold_set_reviewed.jsonl"
        in action["commands"]["evidence"]
    )
    assert action["batch_overview"]["current_batch_rows"] == 20
    assert action["batch_overview"]["current_batch_target_covered_rows"] == 20
    assert action["batch_overview"]["remaining_rows_after_current_batch"] == 430
    assert action["batch_overview"]["remaining_rows_after_next_batch"] == 400
    assert action["batch_overview"]["current_batch_covers_next_batch"] is False
    assert (
        "Gold-set batch coverage: current scratch covers 20/450 pending target rows; "
        "remaining after current apply: 430; covers planned next batch: false"
        in markdown
    )


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
