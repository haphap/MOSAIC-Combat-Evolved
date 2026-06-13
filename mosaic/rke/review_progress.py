"""Read-only progress checks for reviewer-edited RKE scratch files."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    build_source_license_policy_import,
)
from .lockbox_review_import import (
    LOCKBOX_BOOL_FIELDS,
    LOCKBOX_REQUIRED_FIELDS,
    LOCKBOX_RESULTS,
    apply_lockbox_review_import,
)
from .manual_review_batches import (
    GOLD_BATCH_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_TEMPLATE_PATH,
    GOLD_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_EVIDENCE_JSONL_PATH,
    GOLD_REVIEW_EVIDENCE_MD_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    build_manual_review_batch_status,
)
from .manual_review_import import (
    GOLD_BOOL_FIELDS,
    TARGET_ROW_HASH_FIELD,
    apply_gold_set_review_import,
)
from .operator_handoff import LOCKBOX_REVIEWED_IMPORT_PATH
from .phase_minus1 import load_jsonl_with_errors
from .report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
    ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    apply_analytical_footprint_review_import,
)
from .review_gates import summarize_gold_set_review
from .review_gates import summarize_source_license_review
from .temp_paths import (
    RKE_OPERATOR_TMP_ENV_PREFIX,
    operator_command,
    rke_temporary_directory,
)


MANUAL_REVIEW_PROGRESS_REPORT_ID = "RKE-MANUAL-REVIEW-PROGRESS-20260606"
MANUAL_REVIEW_PROGRESS_REPORT_PATH = "registry/review_batches/manual_review_progress_report.json"
MANUAL_REVIEW_RUNBOOK_MD_PATH = "registry/review_batches/manual_review_runbook.md"

ReviewProgressKind = Literal["gold_set", "source_license", "lockbox", "footprint_review"]


@dataclass(frozen=True)
class ManualReviewGateProgress:
    review_kind: ReviewProgressKind
    input_path: str
    input_exists: bool
    target_rows: int
    input_rows: int
    complete_rows: int
    pending_rows: int
    simulation_accepted: bool
    ready_for_promotion: bool
    blockers: Sequence[str]
    prepare_command: str
    dry_run_command: str
    apply_command: str
    next_batch_commands: Mapping[str, str] = field(default_factory=dict)
    batch_plan: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    current_batch_status: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManualReviewProgressReport:
    report_id: str
    ready_for_promotion_dry_run: bool
    gates: Sequence[ManualReviewGateProgress]
    blockers: Sequence[str]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _copy_registry(root_path: Path, temp_root: Path) -> None:
    shutil.copytree(root_path / "registry", temp_root / "registry")
    schemas_path = root_path / "schemas"
    if schemas_path.exists():
        shutil.copytree(schemas_path, temp_root / "schemas")


def _resolve(root_path: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    return path if path.is_absolute() else root_path / path


def _jsonl_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _json_object_exists(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 1
    return 1 if isinstance(payload, Mapping) else 0


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in items if str(item).strip()))


GOLD_BATCH_REQUIRED_FIELDS = (
    "manual_claim_text",
    *GOLD_BOOL_FIELDS,
    "reviewer",
    "review_date",
)


def _is_missing_review_field(
    row: Mapping[str, Any],
    field: str,
    *,
    boolean_fields: Sequence[str],
) -> bool:
    if field in boolean_fields:
        return not isinstance(row.get(field), bool)
    return not str(row.get(field) or "").strip()


def _review_batch_status(
    root_path: Path,
    relative_path: str,
    *,
    required_fields: Sequence[str],
    boolean_fields: Sequence[str],
) -> Mapping[str, Any]:
    path = _resolve(root_path, relative_path)
    status: dict[str, Any] = {
        "path": relative_path,
        "exists": path.exists(),
        "rows": 0,
        "complete_rows": 0,
        "pending_rows": 0,
        "malformed_rows": 0,
        "missing_required_fields": {},
    }
    if not path.exists():
        return status

    rows, errors = load_jsonl_with_errors(path, label=relative_path)
    malformed_rows = len(errors)
    valid_rows: list[Mapping[str, Any]] = []
    for row in rows:
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            malformed_rows += 1

    missing_required_fields: dict[str, int] = {}
    complete_rows = 0
    for row in valid_rows:
        missing_fields = [
            field
            for field in required_fields
            if _is_missing_review_field(row, field, boolean_fields=boolean_fields)
        ]
        if not missing_fields:
            complete_rows += 1
            continue
        for missing_field in missing_fields:
            missing_required_fields[missing_field] = (
                missing_required_fields.get(missing_field, 0) + 1
            )

    total_rows = len(valid_rows) + malformed_rows
    status.update(
        {
            "rows": total_rows,
            "complete_rows": complete_rows,
            "pending_rows": max(total_rows - complete_rows, 0),
            "malformed_rows": malformed_rows,
            "missing_required_fields": dict(sorted(missing_required_fields.items())),
        }
    )
    return status


def _review_evidence_alignment_status(
    root_path: Path,
    *,
    review_input_path: str,
    evidence_path: str,
    id_field: str,
) -> Mapping[str, Any]:
    review_path = _resolve(root_path, review_input_path)
    evidence_resolved = _resolve(root_path, evidence_path)
    status: dict[str, Any] = {
        "path": evidence_path,
        "exists": evidence_resolved.exists(),
        "review_input_path": review_input_path,
        "review_input_exists": review_path.exists(),
        "id_field": id_field,
        "rows": 0,
        "review_input_rows": 0,
        "covered_review_rows": 0,
        "missing_review_rows": 0,
        "extra_evidence_rows": 0,
        "malformed_rows": 0,
        "review_input_malformed_rows": 0,
        "duplicate_review_id_count": 0,
        "duplicate_evidence_id_count": 0,
        "target_row_hash_mismatch_count": 0,
        "same_order": False,
        "aligned": False,
    }
    if not review_path.exists() or not evidence_resolved.exists():
        return status

    review_raw_rows, review_errors = load_jsonl_with_errors(
        review_path,
        label=review_input_path,
    )
    evidence_raw_rows, evidence_errors = load_jsonl_with_errors(
        evidence_resolved,
        label=evidence_path,
    )
    review_rows = [row for row in review_raw_rows if isinstance(row, Mapping)]
    evidence_rows = [row for row in evidence_raw_rows if isinstance(row, Mapping)]
    review_malformed = len(review_errors) + len(review_raw_rows) - len(review_rows)
    evidence_malformed = (
        len(evidence_errors) + len(evidence_raw_rows) - len(evidence_rows)
    )
    review_ids = [str(row.get(id_field) or "").strip() for row in review_rows]
    evidence_ids = [str(row.get(id_field) or "").strip() for row in evidence_rows]
    review_nonempty_ids = [item for item in review_ids if item]
    evidence_nonempty_ids = [item for item in evidence_ids if item]
    missing_review_id_count = len(review_ids) - len(review_nonempty_ids)
    missing_evidence_id_count = len(evidence_ids) - len(evidence_nonempty_ids)
    review_id_set = set(review_nonempty_ids)
    evidence_id_set = set(evidence_nonempty_ids)
    duplicate_review_id_count = len(review_nonempty_ids) - len(review_id_set)
    duplicate_evidence_id_count = len(evidence_nonempty_ids) - len(evidence_id_set)
    missing_review_rows = missing_review_id_count + sum(
        1 for item in review_nonempty_ids if item not in evidence_id_set
    )
    extra_evidence_rows = missing_evidence_id_count + sum(
        1 for item in evidence_nonempty_ids if item not in review_id_set
    )
    evidence_by_id = {
        str(row.get(id_field) or "").strip(): row
        for row in evidence_rows
        if str(row.get(id_field) or "").strip()
    }
    hash_mismatch_count = 0
    for row in review_rows:
        row_id = str(row.get(id_field) or "").strip()
        if not row_id:
            continue
        evidence_row = evidence_by_id.get(row_id)
        if evidence_row is None:
            continue
        review_hash = str(row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        evidence_hash = str(evidence_row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        if review_hash and evidence_hash and review_hash != evidence_hash:
            hash_mismatch_count += 1
    same_order = (
        bool(review_nonempty_ids)
        and len(review_nonempty_ids) == len(evidence_nonempty_ids)
        and review_nonempty_ids == evidence_nonempty_ids
    )
    aligned = (
        bool(review_nonempty_ids)
        and same_order
        and review_malformed == 0
        and evidence_malformed == 0
        and missing_review_id_count == 0
        and missing_evidence_id_count == 0
        and duplicate_review_id_count == 0
        and duplicate_evidence_id_count == 0
        and missing_review_rows == 0
        and extra_evidence_rows == 0
        and hash_mismatch_count == 0
    )
    status.update(
        {
            "rows": len(evidence_rows) + evidence_malformed,
            "review_input_rows": len(review_rows) + review_malformed,
            "covered_review_rows": sum(
                1 for item in review_nonempty_ids if item in evidence_id_set
            ),
            "missing_review_rows": missing_review_rows,
            "extra_evidence_rows": extra_evidence_rows,
            "malformed_rows": evidence_malformed,
            "review_input_malformed_rows": review_malformed,
            "duplicate_review_id_count": duplicate_review_id_count,
            "duplicate_evidence_id_count": duplicate_evidence_id_count,
            "target_row_hash_mismatch_count": hash_mismatch_count,
            "same_order": same_order,
            "aligned": aligned,
        }
    )
    return status


def _gold_batch_status(root_path: Path) -> Mapping[str, Any]:
    status = dict(
        _review_batch_status(
            root_path,
            GOLD_REVIEWED_IMPORT_PATH,
            required_fields=GOLD_BATCH_REQUIRED_FIELDS,
            boolean_fields=GOLD_BOOL_FIELDS,
        )
    )
    status["evidence_status"] = _review_evidence_alignment_status(
        root_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
        evidence_path=GOLD_REVIEW_EVIDENCE_JSONL_PATH,
        id_field="claim_id",
    )
    return status


def _footprint_batch_status(root_path: Path) -> Mapping[str, Any]:
    status = dict(
        _review_batch_status(
            root_path,
            ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
            required_fields=ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
            boolean_fields=ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
        )
    )
    status["evidence_status"] = _review_evidence_alignment_status(
        root_path,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        evidence_path=ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
        id_field="footprint_id",
    )
    return status


def _lockbox_missing_field(row: Mapping[str, Any], field: str) -> bool:
    if field in LOCKBOX_BOOL_FIELDS:
        return not isinstance(row.get(field), bool)
    if field == "open_count":
        return type(row.get(field)) is not int
    return not str(row.get(field) or "").strip()


def _lockbox_decision_status(root_path: Path) -> Mapping[str, Any]:
    path = _resolve(root_path, LOCKBOX_REVIEWED_IMPORT_PATH)
    status: dict[str, Any] = {
        "path": LOCKBOX_REVIEWED_IMPORT_PATH,
        "exists": path.exists(),
        "rows": 0,
        "complete_rows": 0,
        "pending_rows": 0,
        "malformed_rows": 0,
        "missing_required_fields": {},
        "invalid_required_fields": {},
    }
    if not path.exists():
        return status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        status.update({"rows": 1, "pending_rows": 1, "malformed_rows": 1})
        return status
    if not isinstance(payload, Mapping):
        status.update({"rows": 1, "pending_rows": 1, "malformed_rows": 1})
        return status

    required_fields = (*LOCKBOX_REQUIRED_FIELDS, *LOCKBOX_BOOL_FIELDS)
    missing_required_fields = {
        field: 1 for field in required_fields if _lockbox_missing_field(payload, field)
    }
    invalid_required_fields: dict[str, int] = {}
    if not missing_required_fields:
        if str(payload.get("result") or "") not in LOCKBOX_RESULTS - {"not_opened"}:
            invalid_required_fields["result"] = 1
        if type(payload.get("open_count")) is int and int(payload.get("open_count") or 0) < 1:
            invalid_required_fields["open_count"] = 1

    complete_rows = 0 if missing_required_fields or invalid_required_fields else 1
    status.update(
        {
            "rows": 1,
            "complete_rows": complete_rows,
            "pending_rows": 1 - complete_rows,
            "malformed_rows": 0,
            "missing_required_fields": dict(sorted(missing_required_fields.items())),
            "invalid_required_fields": dict(sorted(invalid_required_fields.items())),
        }
    )
    return status


def _gold_next_batch_commands(pending_rows: int) -> dict[str, str]:
    if pending_rows <= 0:
        return {}
    batch_size = min(50, int(pending_rows))
    return {
        "evidence": operator_command(
            "mosaic-rke write-gold-review-evidence --root . "
            f"--limit {batch_size} --offset 0 --review-input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "prepare": (
            operator_command(
                "mosaic-rke prepare-gold-review --root . "
                f"--gold-batch-size {batch_size} --offset 0 --force "
                "--reviewer <name> --review-date <YYYY-MM-DD>"
            )
        ),
        "dry_run": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
        ),
        "apply": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
    }


def _footprint_next_batch_commands(pending_rows: int) -> dict[str, str]:
    if pending_rows <= 0:
        return {}
    batch_size = min(50, int(pending_rows))
    return {
        "assist": operator_command("mosaic-rke write-footprint-review-assist --root ."),
        "evidence": operator_command(
            "mosaic-rke write-footprint-review-evidence --root . "
            f"--limit {batch_size} --offset 0 --review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
        "prepare": (
            operator_command(
                "mosaic-rke prepare-footprint-review --root . "
                f"--limit {batch_size} --offset 0 "
                "--reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
            )
        ),
        "dry_run": operator_command(
            "mosaic-rke apply-footprint-review --root . "
            f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
        ),
        "apply": operator_command(
            "mosaic-rke apply-footprint-review --root . "
            f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
    }


def _manual_review_batch_plan(
    review_kind: ReviewProgressKind,
    pending_rows: int,
    *,
    batch_size: int = 50,
) -> tuple[Mapping[str, Any], ...]:
    if review_kind not in {"gold_set", "footprint_review"} or pending_rows <= 0:
        return ()
    rows_remaining = int(pending_rows)
    size = max(1, int(batch_size))
    batches: list[Mapping[str, Any]] = []
    for batch_index, offset in enumerate(range(0, rows_remaining, size), 1):
        limit = min(size, rows_remaining - offset)
        if review_kind == "gold_set":
            commands = {
                "evidence": operator_command(
                    "mosaic-rke write-gold-review-evidence --root . "
                    f"--limit {limit} --offset {offset} "
                    f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "prepare": operator_command(
                    "mosaic-rke prepare-gold-review --root . "
                    f"--gold-batch-size {limit} --offset {offset} --force "
                    "--reviewer <name> --review-date <YYYY-MM-DD>"
                ),
                "dry_run": operator_command(
                    f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
                ),
                "apply": operator_command(
                    f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
            }
        else:
            commands = {
                "assist": operator_command("mosaic-rke write-footprint-review-assist --root ."),
                "evidence": operator_command(
                    "mosaic-rke write-footprint-review-evidence --root . "
                    f"--limit {limit} --offset {offset} "
                    f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "prepare": operator_command(
                    "mosaic-rke prepare-footprint-review --root . "
                    f"--limit {limit} --offset {offset} "
                    "--reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
                ),
                "dry_run": operator_command(
                    "mosaic-rke apply-footprint-review --root . "
                    f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
                ),
                "apply": operator_command(
                    "mosaic-rke apply-footprint-review --root . "
                    f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
            }
        batches.append(
            {
                "batch_index": batch_index,
                "offset": offset,
                "limit": limit,
                "pending_row_start": offset + 1,
                "pending_row_end": offset + limit,
                "mode": "pending_offset_batch_before_applying_any_batch",
                "apply_effect": "merge_batch_into_target_review_template",
                "target_review_template_path": (
                    GOLD_REVIEW_TEMPLATE_PATH
                    if review_kind == "gold_set"
                    else ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
                ),
                "batch_input_path": (
                    GOLD_REVIEWED_IMPORT_PATH
                    if review_kind == "gold_set"
                    else ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
                ),
                "promotion_input_path": (
                    GOLD_FULL_REVIEWED_IMPORT_PATH
                    if review_kind == "gold_set"
                    else ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
                ),
                "commands": commands,
            }
        )
    return tuple(batches)


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _missing_gate(
    *,
    review_kind: ReviewProgressKind,
    input_path: str,
    target_rows: int,
    prepare_command: str,
    dry_run_command: str,
    apply_command: str,
    next_batch_commands: Mapping[str, str] | None = None,
    batch_plan: Sequence[Mapping[str, Any]] | None = None,
    current_batch_status: Mapping[str, Any] | None = None,
) -> ManualReviewGateProgress:
    return ManualReviewGateProgress(
        review_kind=review_kind,
        input_path=input_path,
        input_exists=False,
        target_rows=target_rows,
        input_rows=0,
        complete_rows=0,
        pending_rows=target_rows,
        simulation_accepted=False,
        ready_for_promotion=False,
        blockers=(f"{input_path} missing; run {prepare_command}",),
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        next_batch_commands=dict(next_batch_commands or {}),
        batch_plan=tuple(batch_plan or ()),
        current_batch_status=dict(current_batch_status or {}),
    )


def _gold_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = GOLD_FULL_REVIEWED_IMPORT_PATH
    current_batch_status = _gold_batch_status(root_path)
    current_summary = summarize_gold_set_review(root_path)
    if current_summary.passed and current_summary.review_complete:
        resolved_input = _resolve(root_path, input_path)
        return ManualReviewGateProgress(
            review_kind="gold_set",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=current_summary.total_claims,
            input_rows=_jsonl_row_count(resolved_input) if resolved_input.exists() else 0,
            complete_rows=current_summary.reviewed_claims,
            pending_rows=0,
            simulation_accepted=True,
            ready_for_promotion=True,
            blockers=(),
            prepare_command=operator_command("mosaic-rke prepare-gold-review --root . --full"),
            dry_run_command=operator_command(
                f"mosaic-rke apply-gold-review --root . --input {input_path} --dry-run"
            ),
            apply_command=operator_command(
                f"mosaic-rke apply-gold-review --root . --input {input_path}"
            ),
            batch_plan=(),
            current_batch_status=current_batch_status,
        )
    target_rows = build_manual_review_batch_status(root_path)[0].gold_set.pending_rows
    resolved_input = _resolve(root_path, input_path)
    prepare_command = operator_command("mosaic-rke prepare-gold-review --root . --full")
    dry_run_command = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {input_path} --dry-run"
    )
    apply_command = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {input_path}"
    )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="gold_set",
            input_path=input_path,
            target_rows=target_rows,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            next_batch_commands=_gold_next_batch_commands(target_rows),
            batch_plan=_manual_review_batch_plan("gold_set", target_rows),
            current_batch_status=current_batch_status,
        )

    input_rows = _jsonl_row_count(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        report = apply_gold_set_review_import(temp_root, resolved_input, dry_run=False)
        summary = summarize_gold_set_review(temp_root)
    blockers = _dedupe((*report.blockers, *summary.blockers))
    return ManualReviewGateProgress(
        review_kind="gold_set",
        input_path=input_path,
        input_exists=True,
        target_rows=target_rows,
        input_rows=input_rows,
        complete_rows=summary.reviewed_claims,
        pending_rows=summary.pending_claims,
        simulation_accepted=report.accepted,
        ready_for_promotion=report.accepted and summary.passed,
        blockers=blockers,
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        next_batch_commands=_gold_next_batch_commands(summary.pending_claims),
        batch_plan=_manual_review_batch_plan("gold_set", summary.pending_claims),
        current_batch_status=current_batch_status,
    )


def _source_license_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = SOURCE_LICENSE_REVIEWED_POLICY_PATH
    target_rows = build_manual_review_batch_status(root_path)[0].source_license.pending_rows
    resolved_input = _resolve(root_path, input_path)
    prepare_command = operator_command("mosaic-rke prepare-license-policy-review --root .")
    dry_run_command = operator_command(
        "mosaic-rke build-license-review-import --root . "
        f"--policy {input_path} --output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        f"mosaic-rke apply-license-review --root . --input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
    )
    apply_command = operator_command(
        "mosaic-rke build-license-review-import --root . "
        f"--policy {input_path} --output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        f"mosaic-rke apply-license-review --root . --input {DEFAULT_LICENSE_POLICY_IMPORT_PATH}"
    )
    current_summary = summarize_source_license_review(root_path)
    if current_summary.passed and current_summary.review_complete:
        return ManualReviewGateProgress(
            review_kind="source_license",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=current_summary.total_sources,
            input_rows=_json_object_exists(resolved_input),
            complete_rows=current_summary.reviewed_sources,
            pending_rows=0,
            simulation_accepted=True,
            ready_for_promotion=True,
            blockers=(),
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            next_batch_commands=_footprint_next_batch_commands(target_rows),
        )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="source_license",
            input_path=input_path,
            target_rows=target_rows,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
        )

    input_rows = _json_object_exists(resolved_input)
    policy_report = build_source_license_policy_import(
        root_path,
        resolved_input,
        output_path=DEFAULT_LICENSE_POLICY_IMPORT_PATH,
        dry_run=True,
        write_report=False,
    )
    complete_rows = policy_report.matched_rows if policy_report.accepted else 0
    pending_rows = max(target_rows - complete_rows, 0)
    blockers = list(policy_report.blockers)
    if pending_rows:
        blockers.append(f"{pending_rows} source license review rows still pending")
    if policy_report.accepted and policy_report.approved_for_production_runtime is not True:
        blockers.append(f"0 / {target_rows} sources approved for production runtime")
    blockers = _dedupe(blockers)
    return ManualReviewGateProgress(
        review_kind="source_license",
        input_path=input_path,
        input_exists=True,
        target_rows=target_rows,
        input_rows=input_rows,
        complete_rows=complete_rows,
        pending_rows=pending_rows,
        simulation_accepted=policy_report.accepted,
        ready_for_promotion=policy_report.accepted
        and pending_rows == 0
        and policy_report.approved_for_production_runtime is True,
        blockers=blockers,
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        next_batch_commands=_footprint_next_batch_commands(pending_rows),
    )


def _lockbox_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = LOCKBOX_REVIEWED_IMPORT_PATH
    current_batch_status = _lockbox_decision_status(root_path)
    resolved_input = _resolve(root_path, input_path)
    prepare_command = operator_command("mosaic-rke prepare-lockbox-review --root .")
    dry_run_command = operator_command(
        f"mosaic-rke apply-lockbox-review --root . --input {input_path} --dry-run"
    )
    apply_command = operator_command(
        f"mosaic-rke apply-lockbox-review --root . --input {input_path}"
    )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="lockbox",
            input_path=input_path,
            target_rows=1,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            batch_plan=(),
            current_batch_status=current_batch_status,
        )

    input_rows = _json_object_exists(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        report = apply_lockbox_review_import(temp_root, resolved_input, dry_run=False)
    blockers = _dedupe((*report.rejected_reasons, *(() if report.production_allowed else report.policy_reasons)))
    complete_rows = 1 if report.accepted else 0
    return ManualReviewGateProgress(
        review_kind="lockbox",
        input_path=input_path,
        input_exists=True,
        target_rows=1,
        input_rows=input_rows,
        complete_rows=complete_rows,
        pending_rows=0 if report.accepted else 1,
        simulation_accepted=report.accepted,
        ready_for_promotion=report.accepted and report.production_allowed,
        blockers=blockers,
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        current_batch_status=current_batch_status,
    )


def _footprint_review_summary(root_path: Path) -> Mapping[str, Any]:
    path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _footprint_review_target_rows(root_path: Path, summary: Mapping[str, Any]) -> int:
    template_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    if template_path.exists():
        return _jsonl_row_count(template_path)
    return int(summary.get("total_rows") or 0)


def _footprint_review_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
    current_batch_status = _footprint_batch_status(root_path)
    resolved_input = _resolve(root_path, input_path)
    summary = _footprint_review_summary(root_path)
    target_rows = _footprint_review_target_rows(root_path, summary)
    prepare_command = (
        operator_command(
            "mosaic-rke prepare-footprint-review --root . "
            f"--output {input_path} --overwrite"
        )
    )
    dry_run_command = operator_command(
        f"mosaic-rke apply-footprint-review --root . --input {input_path} --dry-run"
    )
    apply_command = operator_command(
        f"mosaic-rke apply-footprint-review --root . --input {input_path}"
    )
    if summary.get("accepted") is True and summary.get("review_complete") is True:
        return ManualReviewGateProgress(
            review_kind="footprint_review",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=target_rows,
            input_rows=_jsonl_row_count(resolved_input) if resolved_input.exists() else 0,
            complete_rows=int(summary.get("reviewed_rows") or target_rows),
            pending_rows=0,
            simulation_accepted=True,
            ready_for_promotion=True,
            blockers=(),
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            current_batch_status=current_batch_status,
        )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="footprint_review",
            input_path=input_path,
            target_rows=target_rows,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            next_batch_commands=_footprint_next_batch_commands(target_rows),
            batch_plan=_manual_review_batch_plan("footprint_review", target_rows),
            current_batch_status=current_batch_status,
        )

    input_rows = _jsonl_row_count(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        report = apply_analytical_footprint_review_import(
            temp_root,
            resolved_input,
            dry_run=False,
        )
        simulated_summary = _footprint_review_summary(temp_root)
    blockers = list(report.blockers)
    blockers.extend(str(item) for item in simulated_summary.get("blockers", ()))
    blockers.extend(
        str(item) for item in simulated_summary.get("quality_gate_blockers", ())
    )
    pending_rows = int(simulated_summary.get("pending_rows") or 0)
    complete_rows = int(
        simulated_summary.get("reviewed_rows")
        or simulated_summary.get("complete_rows")
        or max(target_rows - pending_rows, 0)
    )
    return ManualReviewGateProgress(
        review_kind="footprint_review",
        input_path=input_path,
        input_exists=True,
        target_rows=target_rows,
        input_rows=input_rows,
        complete_rows=complete_rows,
        pending_rows=pending_rows,
        simulation_accepted=report.accepted,
        ready_for_promotion=(
            report.accepted
            and simulated_summary.get("accepted") is True
            and simulated_summary.get("quality_gate_passed") is True
        ),
        blockers=_dedupe(blockers),
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        next_batch_commands=_footprint_next_batch_commands(pending_rows),
        batch_plan=_manual_review_batch_plan("footprint_review", pending_rows),
        current_batch_status=current_batch_status,
    )


def _render_batch_status_lines(label: str, status: Mapping[str, Any]) -> list[str]:
    if not status:
        return [f"- {label}: no current batch scratch configured"]
    lines = [
        (
            f"- {label}: `{status.get('path')}`; "
            f"exists: {str(bool(status.get('exists'))).lower()}; "
            f"rows: {int(status.get('rows') or 0)}; "
            f"complete: {int(status.get('complete_rows') or 0)}; "
            f"pending: {int(status.get('pending_rows') or 0)}; "
            f"malformed: {int(status.get('malformed_rows') or 0)}"
        )
    ]
    missing_required_fields = status.get("missing_required_fields")
    if isinstance(missing_required_fields, Mapping) and missing_required_fields:
        missing = ", ".join(
            f"`{field}`={int(count)}"
            for field, count in sorted(missing_required_fields.items())
        )
        lines.append(f"  Missing required fields: {missing}")
    invalid_required_fields = status.get("invalid_required_fields")
    if isinstance(invalid_required_fields, Mapping) and invalid_required_fields:
        invalid = ", ".join(
            f"`{field}`={int(count)}"
            for field, count in sorted(invalid_required_fields.items())
        )
        lines.append(f"  Invalid required fields: {invalid}")
    evidence_status = status.get("evidence_status")
    if isinstance(evidence_status, Mapping) and evidence_status:
        lines.append(
            "  Evidence alignment: "
            f"path=`{evidence_status.get('path')}`; "
            f"exists: {str(bool(evidence_status.get('exists'))).lower()}; "
            f"rows: {int(evidence_status.get('rows') or 0)}; "
            f"covered: {int(evidence_status.get('covered_review_rows') or 0)}/"
            f"{int(evidence_status.get('review_input_rows') or 0)}; "
            f"same_order: {str(bool(evidence_status.get('same_order'))).lower()}; "
            f"aligned: {str(bool(evidence_status.get('aligned'))).lower()}"
        )
        evidence_gaps: list[str] = []
        for field in (
            "missing_review_rows",
            "extra_evidence_rows",
            "target_row_hash_mismatch_count",
            "malformed_rows",
            "review_input_malformed_rows",
            "duplicate_review_id_count",
            "duplicate_evidence_id_count",
        ):
            count = int(evidence_status.get(field) or 0)
            if count:
                evidence_gaps.append(f"`{field}`={count}")
        if evidence_gaps:
            lines.append("  Evidence alignment gaps: " + ", ".join(evidence_gaps))
    return lines


def _render_batch_plan_lines(label: str, batch_plan: Sequence[Mapping[str, Any]]) -> list[str]:
    if not batch_plan:
        return [f"- {label}: no pending review batches."]
    lines = [f"### {label}", ""]
    for batch in batch_plan:
        commands = batch.get("commands")
        command_map = commands if isinstance(commands, Mapping) else {}
        lines.extend(
            [
                (
                    f"- Batch {batch.get('batch_index')}: pending rows "
                    f"{batch.get('pending_row_start')}-{batch.get('pending_row_end')}; "
                    f"limit={batch.get('limit')}; offset={batch.get('offset')}; "
                    f"batch input=`{batch.get('batch_input_path')}`; "
                    f"promotion input=`{batch.get('promotion_input_path')}`"
                ),
            ]
        )
        for command_name in ("assist", "evidence", "prepare", "dry_run", "apply"):
            command = command_map.get(command_name)
            if str(command or "").strip():
                lines.append(f"  - {command_name}: `{command}`")
    return lines


def build_manual_review_progress(root: str | Path = ".") -> ManualReviewProgressReport:
    root_path = Path(root)
    gates = (
        _gold_progress(root_path),
        _footprint_review_progress(root_path),
        _source_license_progress(root_path),
        _lockbox_progress(root_path),
    )
    blockers: list[str] = []
    for gate in gates:
        if not gate.ready_for_promotion:
            blockers.append(
                f"{gate.review_kind}: {gate.complete_rows}/{gate.target_rows} ready"
            )
            blockers.extend(f"{gate.review_kind}: {blocker}" for blocker in gate.blockers)
    return ManualReviewProgressReport(
        report_id=MANUAL_REVIEW_PROGRESS_REPORT_ID,
        ready_for_promotion_dry_run=all(gate.ready_for_promotion for gate in gates),
        gates=gates,
        blockers=_dedupe(blockers),
    )


def write_manual_review_progress_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_manual_review_progress(root_path)
    result = _write_json(root_path / MANUAL_REVIEW_PROGRESS_REPORT_PATH, asdict(report))
    return {
        "path": str(result["path"]),
        "ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "blocker_count": len(report.blockers),
    }


def render_manual_review_runbook_markdown(report: ManualReviewProgressReport) -> str:
    gate_lookup = {gate.review_kind: gate for gate in report.gates}
    gold = gate_lookup["gold_set"]
    footprint = gate_lookup["footprint_review"]
    source_license = gate_lookup["source_license"]
    lockbox = gate_lookup["lockbox"]
    gold_full_prepare = operator_command(
        "mosaic-rke prepare-gold-review --root . --full --force "
        "--reviewer <name> --review-date <YYYY-MM-DD>"
    )
    gold_batch_prepare = operator_command(
        "mosaic-rke prepare-gold-review --root . --gold-batch-size 50 "
        "--offset 0 --force --reviewer <name> --review-date <YYYY-MM-DD>"
    )
    gold_batch_dry_run = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
    )
    gold_batch_apply = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
    )
    gold_evidence = operator_command(
        "mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0 "
        f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
    )
    footprint_batch_prepare = operator_command(
        "mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 "
        "--reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
    )
    footprint_batch_dry_run = operator_command(
        "mosaic-rke apply-footprint-review --root . "
        f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
    )
    footprint_batch_apply = operator_command(
        "mosaic-rke apply-footprint-review --root . "
        f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
    footprint_assist = operator_command("mosaic-rke write-footprint-review-assist --root .")
    footprint_evidence = operator_command(
        "mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 "
        f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
    lines = [
        "# RKE Manual Review Runbook",
        "",
        "This artifact is a read-only operator checklist for the remaining manual RKE gates.",
        "It records paths, commands, row counts, acceptance criteria, and current blockers only.",
        "",
        "## Current Progress",
        "",
        f"- Promotion dry-run ready: {str(report.ready_for_promotion_dry_run).lower()}",
        (
            "- Gold-set review: "
            f"{gold.complete_rows}/{gold.target_rows} complete; "
            f"scratch exists: {str(gold.input_exists).lower()}; "
            f"simulation accepted: {str(gold.simulation_accepted).lower()}"
        ),
        (
            "- Analytical-footprint review: "
            f"{footprint.complete_rows}/{footprint.target_rows} complete; "
            f"scratch exists: {str(footprint.input_exists).lower()}; "
            f"simulation accepted: {str(footprint.simulation_accepted).lower()}"
        ),
        (
            "- Source-license review: "
            f"{source_license.complete_rows}/{source_license.target_rows} complete; "
            f"scratch exists: {str(source_license.input_exists).lower()}; "
            f"simulation accepted: {str(source_license.simulation_accepted).lower()}"
        ),
        (
            "- Lockbox review: "
            f"{lockbox.complete_rows}/{lockbox.target_rows} complete; "
            f"scratch exists: {str(lockbox.input_exists).lower()}; "
            f"simulation accepted: {str(lockbox.simulation_accepted).lower()}"
        ),
        "",
        "## Current Batch Scratch",
        "",
        "This section reports aggregate completion counts for the current local batch or decision files only; it does not include source text, claim text, or reviewer notes.",
        *_render_batch_status_lines("Gold-set batch", gold.current_batch_status),
        *_render_batch_status_lines(
            "Analytical-footprint batch",
            footprint.current_batch_status,
        ),
        *_render_batch_status_lines("Lockbox decision", lockbox.current_batch_status),
        "",
        "## Prepare Commands",
        "",
        f"- Temp workspace: `{RKE_OPERATOR_TMP_ENV_PREFIX}` keeps review-progress and promotion dry-run registry copies out of system `/tmp`; generated commands below include this prefix.",
        f"- Gold-set: `{gold.prepare_command}`",
        f"- Analytical-footprint: `{footprint.prepare_command}`",
        f"- Source-license: `{source_license.prepare_command}`",
        f"- Lockbox: `{lockbox.prepare_command}`",
        "",
        "## Reviewer Inputs",
        "",
        f"- Gold-set reviewed scratch: `{GOLD_FULL_REVIEWED_IMPORT_PATH}`",
        f"- Analytical-footprint reviewed scratch: `{ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH}`",
        f"- Source-license reviewed policy: `{SOURCE_LICENSE_REVIEWED_POLICY_PATH}`",
        f"- Lockbox reviewed scratch: `{LOCKBOX_REVIEWED_IMPORT_PATH}`",
        "",
        "Reviewed scratch files are operator-local decision files. Do not commit them unless the operator explicitly chooses to publish signed review decisions.",
        "",
        "## Read-Only Checklists",
        "",
        f"- Gold-set workbook: `{GOLD_REVIEW_WORKBOOK_MD_PATH}`",
        f"- Gold-set evidence draft Markdown: `{GOLD_REVIEW_EVIDENCE_MD_PATH}`",
        f"- Gold-set evidence draft JSONL: `{GOLD_REVIEW_EVIDENCE_JSONL_PATH}`",
        "- Gold-set packet JSON: `registry/gold_sets/tushare_research_reports.review_packet.json`",
        "- Gold-set packet Markdown: `registry/gold_sets/tushare_research_reports.review_packet.md`",
        f"- Source-license workbook: `{SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH}`",
        "- Source-license packet JSON: `registry/compliance/tushare_license_review_packet.json`",
        "- Source-license packet Markdown: `registry/compliance/tushare_license_review_packet.md`",
        f"- Source-license policy template: `{SOURCE_LICENSE_POLICY_TEMPLATE_PATH}`",
        f"- Analytical-footprint review template: `{ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH}`",
        f"- Analytical-footprint review workbook: `{ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH}`",
        f"- Analytical-footprint review assist JSONL: `{ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH}`",
        f"- Analytical-footprint evidence draft Markdown: `{ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH}`",
        f"- Analytical-footprint evidence draft JSONL: `{ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH}`",
        "- Lockbox policy packet: `registry/evaluation/lockbox/lockbox_policy.json`",
        "",
        "These checklist files are not import files. Use them to inspect IDs, hashes, counts, and short previews only.",
        "",
        "## Gate Acceptance Criteria",
        "",
        "Gold-set review is accepted only when all current 500 claim rows are completed and the dry run accepts the import.",
        "Each gold-set row must keep the template IDs and hashes intact and must fill `manual_claim_text`, `reviewer`, `review_date`, `claim_correct`, `source_span_supports_claim`, `direction_correct`, `target_correct`, `horizon_correct`, `variable_mapping_correct`, and `unsupported_field_false_grounded`.",
        f"Use `{gold_full_prepare}` to prefill reviewer identity and date only; claim text and boolean review decisions remain human judgments.",
        f"For batch work, use `{gold_batch_prepare}`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.",
        f"Batch gold-set imports use `{gold_batch_dry_run}`, then `{gold_batch_apply}` after the batch is accepted.",
        f"Use `{gold_evidence}` after preparing the current gold scratch batch to regenerate a batch-aligned private source-evidence draft.",
        "The resulting gold-set summary must satisfy the code-defined gate: at least 50 documents, at least 500 claims, claim precision >= 0.85, span-support precision >= 0.90, direction accuracy >= 0.85, target accuracy >= 0.85, horizon accuracy >= 0.85, variable mapping accuracy >= 0.80, and unsupported-field false grounding <= 0.05.",
        "",
        "Analytical-footprint review is accepted only when every footprint row is completed, the import dry run accepts it, and the review summary quality gate passes.",
        "Each analytical-footprint row must keep target IDs and hashes intact and must fill `reviewer`, `review_date`, `review_notes`, `footprint_correct`, `source_span_supports_footprint`, `metric_mapping_correct`, `inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`, and `no_proprietary_text_leakage`.",
        f"For batch work, use `{footprint_batch_prepare}`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.",
        f"Batch analytical-footprint imports use `{footprint_batch_dry_run}`, then `{footprint_batch_apply}` after the batch is accepted.",
        f"Use `{footprint_assist}` and `{footprint_evidence}` after preparing the current footprint scratch batch to regenerate a batch-aligned private evidence draft.",
        "",
        "Source-license review is accepted only when the reviewed policy expands to all current source rows and both the build step and license import dry run accept it.",
        "The reviewed policy must fill `reviewer`, `review_date`, `approved_for_derived_claim_storage`, and `approved_for_production_runtime`; production promotion requires `approved_for_production_runtime=true` for every matched current source.",
        "The policy must keep `target_review_path`, `review_context_ref`, `matched_row_count`, `matched_rows_fingerprint`, publish-date bounds, and filter scope aligned with the current template; rerun prepare if the source scope changes.",
        "",
        "Lockbox review is accepted only after the final holdout is opened once, the import dry run accepts the signed row, and the lockbox decision allows production.",
        "The lockbox row must fill `opened_at`, `opened_by`, `open_count`, `result`, `parameter_search_after_open`, and `rule_design_after_open`; production requires `result=passed`, `open_count<=1`, no parameter search after open, no rule design after open, and matching target/context hashes.",
        "",
        "A promotion dry run is ready only when all manual gates above report ready for promotion. Missing scratch files, incomplete rows, failed dry runs, or failed quality thresholds keep the system in paper trading.",
        "",
        "## Import Templates",
        "",
        f"- Next gold-set batch template: `{GOLD_BATCH_IMPORT_TEMPLATE_PATH}`",
        f"- Full gold-set import template: `{GOLD_FULL_IMPORT_TEMPLATE_PATH}`",
        f"- Next source-license batch template: `{LICENSE_BATCH_IMPORT_TEMPLATE_PATH}`",
        f"- Expanded source-license import output: `{DEFAULT_LICENSE_POLICY_IMPORT_PATH}`",
        "- Lockbox import template: `registry/review_batches/lockbox_review_next_import_template.json`",
        "",
        "## Dry-Run Commands",
        "",
        f"- Gold-set: `{gold.dry_run_command}`",
        f"- Analytical-footprint: `{footprint.dry_run_command}`",
        f"- Source-license: `{source_license.dry_run_command}`",
        f"- Lockbox: `{lockbox.dry_run_command}`",
        "",
        "## Apply Commands",
        "",
        f"- Gold-set: `{gold.apply_command}`",
        f"- Analytical-footprint: `{footprint.apply_command}`",
        f"- Source-license: `{source_license.apply_command}`",
        f"- Lockbox: `{lockbox.apply_command}`",
        "",
        "## Promotion Dry Run",
        "",
        (
            "`"
            + operator_command(
                "mosaic-rke build-license-review-import --root . "
                f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
                f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
                "mosaic-rke promotion-dry-run --root . "
                f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
                f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
                f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
                f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
            )
            + "`"
        ),
        "",
    ]
    lines.extend(
        [
            "## Full Pending Batch Plan",
            "",
            "This plan slices the current pending set before any new batch is applied. If you apply one accepted batch, rerun `review-progress` and use the refreshed offsets.",
            "",
            *_render_batch_plan_lines("Gold-set review", gold.batch_plan),
            "",
            *_render_batch_plan_lines("Analytical-footprint review", footprint.batch_plan),
            "",
            "## Next Batch Commands",
            "",
            "These commands operate on the current pending set. After applying an accepted batch, rerun review-progress and use the refreshed commands.",
            "",
        ]
    )
    for gate in (gold, footprint):
        if not gate.next_batch_commands:
            continue
        lines.append(f"### {gate.review_kind}")
        lines.append("")
        for command_name, command in gate.next_batch_commands.items():
            lines.append(f"- {command_name}: `{command}`")
        lines.append("")
    lines.extend(["## Current Blockers", ""])
    if report.blockers:
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip()


def write_manual_review_runbook(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_manual_review_progress(root_path)
    path = root_path / MANUAL_REVIEW_RUNBOOK_MD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_manual_review_runbook_markdown(report)
    path.write_text(markdown + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "blocker_count": len(report.blockers),
    }
