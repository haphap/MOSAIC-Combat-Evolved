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
from .manual_review_aids import manual_review_aid_paths, manual_review_field_contract
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
    review_row_fingerprint,
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
    _gold_review_quality_gap_targets_from_summary,
    apply_analytical_footprint_review_import,
    build_analytical_footprint_review_summary,
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
GOLD_REVIEW_SUMMARY_PATH = (
    "registry/gold_sets/tushare_research_reports.review_summary.json"
)
TEMP_COPY_IGNORED_PRIVATE_REGISTRY_PATHS = frozenset(
    {
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/markdown",
        "registry/report_intelligence/mineru",
        "registry/report_intelligence/pdfs",
        "registry/report_intelligence/processing_status.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
        "registry/sources/tushare_research_reports.gold_candidates.jsonl",
        "registry/sources/tushare_research_reports.jsonl",
        "registry/sources/tushare_research_reports.manifest.json",
    }
)

ReviewProgressKind = Literal["gold_set", "source_license", "lockbox", "footprint_review"]
ACTION_QUEUE_STATES = (
    "ready_to_apply",
    "already_applied",
    "needs_human_review_fields",
    "needs_evidence_repair",
    "needs_prepare",
    "needs_quality_gate_work",
    "needs_policy_review",
    "waiting_on_dependencies",
    "needs_lockbox_decision",
    "needs_operator_inspection",
)


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
    quality_gap_targets: Mapping[str, Any] | None = None


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
    root_resolved = root_path.resolve()

    def _ignore_private_source_files(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        directory_path = Path(directory)
        for name in names:
            try:
                relative_path = (
                    directory_path / name
                ).resolve().relative_to(root_resolved).as_posix()
            except ValueError:
                continue
            if relative_path in TEMP_COPY_IGNORED_PRIVATE_REGISTRY_PATHS:
                ignored.add(name)
        return ignored

    shutil.copytree(
        root_path / "registry",
        temp_root / "registry",
        ignore=_ignore_private_source_files,
    )
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


def _read_mapping_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


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


def _review_target_alignment_status(
    root_path: Path,
    *,
    review_input_path: str,
    target_path: str,
    id_field: str,
) -> Mapping[str, Any]:
    review_path = _resolve(root_path, review_input_path)
    target_resolved = _resolve(root_path, target_path)
    status: dict[str, Any] = {
        "target_path": target_path,
        "exists": target_resolved.exists(),
        "review_input_path": review_input_path,
        "review_input_exists": review_path.exists(),
        "id_field": id_field,
        "review_input_rows": 0,
        "target_rows": 0,
        "missing_target_rows": 0,
        "target_row_hash_mismatch_count": 0,
        "malformed_rows": 0,
        "target_malformed_rows": 0,
        "aligned": False,
    }
    if not review_path.exists() or not target_resolved.exists():
        return status

    review_raw_rows, review_errors = load_jsonl_with_errors(
        review_path,
        label=review_input_path,
    )
    target_raw_rows, target_errors = load_jsonl_with_errors(
        target_resolved,
        label=target_path,
    )
    review_rows = [row for row in review_raw_rows if isinstance(row, Mapping)]
    target_rows = [row for row in target_raw_rows if isinstance(row, Mapping)]
    review_malformed = len(review_errors) + len(review_raw_rows) - len(review_rows)
    target_malformed = len(target_errors) + len(target_raw_rows) - len(target_rows)
    target_by_id = {
        str(row.get(id_field) or "").strip(): row
        for row in target_rows
        if str(row.get(id_field) or "").strip()
    }
    missing_target_rows = 0
    hash_mismatch_count = 0
    for row in review_rows:
        row_id = str(row.get(id_field) or "").strip()
        if not row_id:
            missing_target_rows += 1
            continue
        target_row = target_by_id.get(row_id)
        if target_row is None:
            missing_target_rows += 1
            continue
        review_hash = str(row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        target_hash = str(target_row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        if not target_hash:
            target_hash = review_row_fingerprint(target_row)
        if review_hash != target_hash:
            hash_mismatch_count += 1
    aligned = (
        bool(review_rows)
        and review_malformed == 0
        and target_malformed == 0
        and missing_target_rows == 0
        and hash_mismatch_count == 0
    )
    status.update(
        {
            "review_input_rows": len(review_rows) + review_malformed,
            "target_rows": len(target_rows) + target_malformed,
            "missing_target_rows": missing_target_rows,
            "target_row_hash_mismatch_count": hash_mismatch_count,
            "malformed_rows": review_malformed,
            "target_malformed_rows": target_malformed,
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
    status["target_status"] = _review_target_alignment_status(
        root_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
        target_path=GOLD_REVIEW_TEMPLATE_PATH,
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
    status["target_status"] = _review_target_alignment_status(
        root_path,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        target_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
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
        "assist": operator_command(
            "mosaic-rke write-gold-review-assist --root . "
            f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
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
        "backfill_dry_run": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "backfill_write": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --write"
        ),
        "dry_run": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
        ),
        "apply": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
    }


def _gold_quality_gate_commands() -> dict[str, str]:
    return {
        "assist": operator_command(
            "mosaic-rke write-gold-review-assist --root . "
            f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "refresh_source_candidates": operator_command(
            "mosaic-rke fetch-tushare-reports --root . --p9-profile "
            "--start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> "
            "--merge-existing-source"
        ),
        "expand_candidate_review_rows": operator_command(
            "mosaic-rke gold-candidate-claims --root . "
            "--refresh-candidates-from-source --ensure-candidate-review-rows"
        ),
        "prepare_reviewed_failures": operator_command(
            "mosaic-rke prepare-gold-review --root . --reviewed-failures "
            "--gold-batch-size 50 --offset 0 --force "
            "--reviewer <name> --review-date <YYYY-MM-DD>"
        ),
        "prepare_expanded_batch": operator_command(
            "mosaic-rke prepare-gold-review --root . "
            "--gold-batch-size 50 --offset 0 --force "
            "--reviewer <name> --review-date <YYYY-MM-DD>"
        ),
        "evidence": operator_command(
            "mosaic-rke write-gold-review-evidence --root . "
            f"--limit 50 --offset 0 --review-input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "backfill_dry_run": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "backfill_write": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --write"
        ),
        "dry_run": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
        ),
    }


def _footprint_next_batch_commands(pending_rows: int) -> dict[str, str]:
    if pending_rows <= 0:
        return {}
    batch_size = min(50, int(pending_rows))
    return {
        "assist": operator_command(
            "mosaic-rke write-footprint-review-assist --root . "
            f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
        "evidence": operator_command(
            "mosaic-rke write-footprint-review-evidence --root . "
            f"--limit {batch_size} --offset 0 --review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
        "prepare": (
            operator_command(
                "mosaic-rke prepare-footprint-review --root . "
                f"--limit {batch_size} --offset 0 --priority "
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
                "backfill_dry_run": operator_command(
                    f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "backfill_write": operator_command(
                    f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --write"
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
                "assist": operator_command(
                    "mosaic-rke write-footprint-review-assist --root . "
                    f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "evidence": operator_command(
                    "mosaic-rke write-footprint-review-evidence --root . "
                    f"--limit {limit} --offset {offset} "
                    f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "prepare": operator_command(
                    "mosaic-rke prepare-footprint-review --root . "
                    f"--limit {limit} --offset {offset} --priority "
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
                "mode": (
                    "pending_offset_batch_before_applying_any_batch"
                    if review_kind == "gold_set"
                    else "priority_sorted_pending_batch_before_applying_any_batch"
                ),
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
    quality_gap_targets: Mapping[str, Any] | None = None,
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
        quality_gap_targets=quality_gap_targets,
    )


def _gold_quality_gap_targets_from_review_summary(
    summary: Any,
    public_quality_gap_targets: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    if getattr(summary, "quality_gap_targets", None):
        return summary.quality_gap_targets
    if public_quality_gap_targets:
        return public_quality_gap_targets
    return _gold_review_quality_gap_targets_from_summary(asdict(summary))


def _gold_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = GOLD_FULL_REVIEWED_IMPORT_PATH
    current_batch_status = _gold_batch_status(root_path)
    current_summary = summarize_gold_set_review(root_path)
    public_quality_gap_targets = _gold_review_quality_gap_targets_from_summary(
        _read_mapping_json(root_path / GOLD_REVIEW_SUMMARY_PATH)
    )
    current_quality_gap_targets = _gold_quality_gap_targets_from_review_summary(
        current_summary,
        public_quality_gap_targets,
    )
    if current_summary.review_complete:
        resolved_input = _resolve(root_path, input_path)
        return ManualReviewGateProgress(
            review_kind="gold_set",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=current_summary.total_claims,
            input_rows=_jsonl_row_count(resolved_input) if resolved_input.exists() else 0,
            complete_rows=current_summary.reviewed_claims,
            pending_rows=current_summary.pending_claims,
            simulation_accepted=current_summary.passed,
            ready_for_promotion=current_summary.passed,
            blockers=tuple(current_summary.blockers),
            prepare_command=operator_command("mosaic-rke prepare-gold-review --root . --full"),
            dry_run_command=operator_command(
                f"mosaic-rke apply-gold-review --root . --input {input_path} --dry-run"
            ),
            apply_command=operator_command(
                f"mosaic-rke apply-gold-review --root . --input {input_path}"
            ),
            next_batch_commands=(
                _gold_quality_gate_commands()
                if not current_summary.passed
                else {}
            ),
            batch_plan=(),
            current_batch_status=current_batch_status,
            quality_gap_targets=current_quality_gap_targets,
        )
    target_rows = current_summary.total_claims
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
            quality_gap_targets=current_quality_gap_targets,
        )

    input_rows = _jsonl_row_count(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        report = apply_gold_set_review_import(temp_root, resolved_input, dry_run=False)
        summary = summarize_gold_set_review(temp_root)
    quality_gap_targets = (
        _gold_quality_gap_targets_from_review_summary(
            summary,
            public_quality_gap_targets,
        )
        or current_quality_gap_targets
    )
    blockers = _dedupe((*report.blockers, *summary.blockers))
    return ManualReviewGateProgress(
        review_kind="gold_set",
        input_path=input_path,
        input_exists=True,
        target_rows=summary.total_claims,
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
        quality_gap_targets=quality_gap_targets,
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
            next_batch_commands={},
            current_batch_status={"already_applied": True},
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
        next_batch_commands={},
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
    payload: Mapping[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        payload = loaded if isinstance(loaded, Mapping) else {}
    if payload.get("quality_gap_targets") is not None:
        return payload

    template_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    if not template_path.exists():
        return payload
    raw_rows, _ = load_jsonl_with_errors(
        template_path,
        label=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
    )
    template_rows = tuple(row for row in raw_rows if isinstance(row, Mapping))
    if not template_rows:
        return payload
    computed = build_analytical_footprint_review_summary(template_rows)
    return {**computed, **payload, "quality_gap_targets": computed.get("quality_gap_targets")}


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
            quality_gap_targets=summary.get("quality_gap_targets"),
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
            quality_gap_targets=summary.get("quality_gap_targets"),
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
        quality_gap_targets=simulated_summary.get("quality_gap_targets"),
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


def _render_current_batch_coverage_lines(
    label: str,
    gate: ManualReviewGateProgress,
) -> list[str]:
    overview = _compact_batch_overview(gate)
    if not overview or gate.ready_for_promotion:
        return []
    covered_rows = int(overview.get("current_batch_target_covered_rows") or 0)
    pending_rows = int(overview.get("pending_rows") or 0)
    if covered_rows <= 0 or pending_rows <= 0:
        return []
    remaining_rows = int(overview.get("remaining_rows_after_current_batch") or 0)
    covers_next_batch = bool(overview.get("current_batch_covers_next_batch"))
    return [
        (
            f"- {label} coverage: current scratch covers {covered_rows}/"
            f"{pending_rows} pending target rows; remaining after current apply: "
            f"{remaining_rows}; covers planned next batch: "
            f"{str(covers_next_batch).lower()}"
        )
    ]


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
        for command_name in (
            "assist",
            "evidence",
            "prepare",
            "backfill_dry_run",
            "backfill_write",
            "dry_run",
            "apply",
        ):
            command = command_map.get(command_name)
            if str(command or "").strip():
                lines.append(f"  - {command_name}: `{command}`")
    return lines


def _render_contract_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_contract_list(values: Any) -> str:
    if not isinstance(values, Sequence) or isinstance(values, str):
        return "none"
    items = [_render_contract_value(item) for item in values]
    if not items:
        return "none"
    return ", ".join(f"`{item}`" for item in items)


def _render_contract_mapping(values: Any) -> str:
    if not isinstance(values, Mapping) or not values:
        return "none"
    return ", ".join(
        f"`{key}`=`{_render_contract_value(value)}`"
        for key, value in sorted(values.items())
    )


def _render_field_contract_lines(
    title: str,
    contract: Mapping[str, Any],
) -> list[str]:
    if not contract:
        return []
    lines = [f"### {title}", ""]
    policy = str(contract.get("policy") or "").strip()
    if policy:
        lines.append(f"- Policy: `{policy}`")
    lines.extend(
        [
            f"- Required fields: {_render_contract_list(contract.get('required_fields'))}",
            f"- Optional fields: {_render_contract_list(contract.get('optional_fields'))}",
            f"- Boolean fields: {_render_contract_list(contract.get('boolean_fields'))}",
            f"- Boolean allowed values: {_render_contract_list(contract.get('boolean_allowed_values'))}",
            f"- Date fields: {_render_contract_mapping(contract.get('date_fields'))}",
            f"- Text fields: {_render_contract_list(contract.get('text_fields'))}",
            f"- Numeric fields: {_render_contract_list(contract.get('numeric_fields'))}",
            f"- Allowed results: {_render_contract_list(contract.get('allowed_results'))}",
            f"- Preserve fields: {_render_contract_list(contract.get('preserve_fields'))}",
            "",
        ]
    )
    return lines


def _promotion_dry_run_command(source_license: ManualReviewGateProgress) -> str:
    if source_license.ready_for_promotion:
        return operator_command(
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        )
    return operator_command(
        "mosaic-rke build-license-review-import --root . "
        f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
        f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        "mosaic-rke promotion-dry-run --root . "
        f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
        f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
        f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
        f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
    )


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


def _compact_current_batch_status(status: Mapping[str, Any]) -> Mapping[str, Any]:
    if not status:
        return {}
    compact: dict[str, Any] = {
        "path": status.get("path"),
        "exists": bool(status.get("exists")),
        "rows": int(status.get("rows") or 0),
        "complete_rows": int(status.get("complete_rows") or 0),
        "pending_rows": int(status.get("pending_rows") or 0),
        "malformed_rows": int(status.get("malformed_rows") or 0),
    }
    for field_name in ("missing_required_fields", "invalid_required_fields"):
        value = status.get(field_name)
        if isinstance(value, Mapping) and value:
            compact[field_name] = {
                str(key): int(count) for key, count in sorted(value.items())
            }
    evidence_status = status.get("evidence_status")
    if isinstance(evidence_status, Mapping) and evidence_status:
        compact["evidence_status"] = {
            "path": evidence_status.get("path"),
            "exists": bool(evidence_status.get("exists")),
            "rows": int(evidence_status.get("rows") or 0),
            "covered_review_rows": int(
                evidence_status.get("covered_review_rows") or 0
            ),
            "review_input_rows": int(evidence_status.get("review_input_rows") or 0),
            "same_order": bool(evidence_status.get("same_order")),
            "aligned": bool(evidence_status.get("aligned")),
            "missing_review_rows": int(
                evidence_status.get("missing_review_rows") or 0
            ),
            "extra_evidence_rows": int(
                evidence_status.get("extra_evidence_rows") or 0
            ),
            "target_row_hash_mismatch_count": int(
                evidence_status.get("target_row_hash_mismatch_count") or 0
            ),
        }
    target_status = status.get("target_status")
    if isinstance(target_status, Mapping) and target_status:
        compact["target_status"] = {
            "target_path": target_status.get("target_path"),
            "exists": bool(target_status.get("exists")),
            "review_input_rows": int(target_status.get("review_input_rows") or 0),
            "target_rows": int(target_status.get("target_rows") or 0),
            "missing_target_rows": int(target_status.get("missing_target_rows") or 0),
            "target_row_hash_mismatch_count": int(
                target_status.get("target_row_hash_mismatch_count") or 0
            ),
            "malformed_rows": int(target_status.get("malformed_rows") or 0),
            "target_malformed_rows": int(
                target_status.get("target_malformed_rows") or 0
            ),
            "aligned": bool(target_status.get("aligned")),
        }
    return compact


def _current_batch_stale_after_promotion_ready(
    gate: ManualReviewGateProgress,
) -> bool:
    current = (
        gate.current_batch_status
        if isinstance(gate.current_batch_status, Mapping)
        else {}
    )
    return (
        gate.ready_for_promotion
        and bool(current.get("exists"))
        and int(current.get("pending_rows") or 0) > 0
    )


def _compact_batch_overview(gate: ManualReviewGateProgress) -> Mapping[str, Any]:
    if gate.review_kind not in {"gold_set", "footprint_review"}:
        return {}
    current = _compact_current_batch_status(gate.current_batch_status)
    stale_current_batch = _current_batch_stale_after_promotion_ready(gate)
    if gate.ready_for_promotion:
        return {
            "batch_count": 0,
            "pending_rows": 0,
            "promotion_input_path": gate.input_path,
            "current_batch_stale_after_promotion_ready": stale_current_batch,
            "stale_current_batch_path": (
                str(current.get("path") or "") if stale_current_batch else ""
            ),
            "stale_current_batch_pending_rows": (
                int(current.get("pending_rows") or 0) if stale_current_batch else 0
            ),
            "rerun_review_progress_after_batch_apply": False,
        }
    batches = tuple(
        batch for batch in gate.batch_plan if isinstance(batch, Mapping)
    )
    evidence = (
        current.get("evidence_status")
        if isinstance(current.get("evidence_status"), Mapping)
        else {}
    )
    target = (
        current.get("target_status")
        if isinstance(current.get("target_status"), Mapping)
        else {}
    )
    current_batch_target_covered_rows = 0
    if (
        bool(current.get("exists"))
        and int(current.get("malformed_rows") or 0) == 0
        and target
        and bool(target.get("aligned"))
    ):
        current_batch_target_covered_rows = int(current.get("rows") or 0)
    overview: dict[str, Any] = {
        "batch_count": len(batches),
        "pending_rows": gate.pending_rows,
        "current_batch_path": current.get("path"),
        "current_batch_rows": int(current.get("rows") or 0),
        "current_batch_pending_rows": int(current.get("pending_rows") or 0),
        "current_batch_target_covered_rows": current_batch_target_covered_rows,
        "remaining_rows_after_current_batch": max(
            int(gate.pending_rows) - current_batch_target_covered_rows,
            0,
        ),
        "current_batch_evidence_aligned": (
            bool(evidence.get("aligned")) if evidence else None
        ),
        "current_batch_target_aligned": (
            bool(target.get("aligned")) if target else None
        ),
        "current_batch_target_hash_mismatch_count": (
            int(target.get("target_row_hash_mismatch_count") or 0) if target else 0
        ),
        "current_batch_evidence_path": (
            str(evidence.get("path") or "") if evidence else ""
        ),
        "rerun_review_progress_after_batch_apply": True,
    }
    if batches:
        first = batches[0]
        last = batches[-1]
        first_limit = int(first.get("limit") or 0)
        overview.update(
            {
                "next_batch_offset": int(first.get("offset") or 0),
                "next_batch_limit": first_limit,
                "next_batch_pending_row_start": int(
                    first.get("pending_row_start") or 0
                ),
                "next_batch_pending_row_end": int(first.get("pending_row_end") or 0),
                "final_batch_offset": int(last.get("offset") or 0),
                "final_batch_limit": int(last.get("limit") or 0),
                "remaining_rows_after_next_batch": max(
                    int(gate.pending_rows) - first_limit,
                    0,
                ),
                "current_batch_covers_next_batch": (
                    current_batch_target_covered_rows >= first_limit
                    if first_limit
                    else False
                ),
            }
        )
    return overview


def _review_aid_paths(gate: ManualReviewGateProgress) -> Mapping[str, Any]:
    return manual_review_aid_paths(gate.review_kind)


def _review_field_contract(gate: ManualReviewGateProgress) -> Mapping[str, Any]:
    return manual_review_field_contract(gate.review_kind)


def _compact_quality_gap_targets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact_quality_gap_targets(item)
            for key, item in value.items()
            if str(key) != "policy"
        }
    if isinstance(value, tuple):
        return tuple(_compact_quality_gap_targets(item) for item in value)
    if isinstance(value, list):
        return [_compact_quality_gap_targets(item) for item in value]
    return value


def _lockbox_dependency_blockers(
    gate: ManualReviewGateProgress,
    gates: Sequence[ManualReviewGateProgress],
) -> tuple[ReviewProgressKind, ...]:
    if gate.review_kind != "lockbox":
        return ()
    dependency_order: tuple[ReviewProgressKind, ...] = (
        "gold_set",
        "footprint_review",
        "source_license",
    )
    gate_by_kind = {item.review_kind: item for item in gates}
    return tuple(
        review_kind
        for review_kind in dependency_order
        if not gate_by_kind.get(review_kind, gate).ready_for_promotion
    )


def _next_manual_action(
    gate: ManualReviewGateProgress,
    *,
    dependency_blockers: Sequence[ReviewProgressKind] = (),
) -> str:
    current = (
        gate.current_batch_status
        if isinstance(gate.current_batch_status, Mapping)
        else {}
    )
    if gate.ready_for_promotion:
        if current.get("already_applied") is True:
            return "already_applied"
        return "ready_for_promotion_apply"
    if gate.review_kind == "source_license":
        return "review_or_apply_source_license_policy"
    if gate.review_kind == "lockbox":
        if dependency_blockers:
            return "wait_for_prior_manual_gates"
        if current.get("exists"):
            return "complete_lockbox_decision_then_dry_run"
        return "prepare_lockbox_review"
    if (
        gate.pending_rows == 0
        and gate.blockers
        and int(current.get("pending_rows") or 0) == 0
    ):
        return "address_quality_gate_blockers"
    target = current.get("target_status")
    if (
        current.get("exists")
        and isinstance(target, Mapping)
        and target.get("exists")
        and int(target.get("review_input_rows") or 0) > 0
        and not bool(target.get("aligned"))
    ):
        return "prepare_next_review_batch"
    if current.get("exists") and int(current.get("pending_rows") or 0) > 0:
        evidence = current.get("evidence_status")
        if isinstance(evidence, Mapping) and not bool(evidence.get("aligned")):
            return "repair_current_batch_evidence_alignment"
        return "fill_current_batch_review_fields_then_dry_run"
    if gate.next_batch_commands:
        return "prepare_next_review_batch"
    return "run_prepare_command"


def build_manual_review_progress_summary(
    report: ManualReviewProgressReport,
    *,
    path: str = MANUAL_REVIEW_PROGRESS_REPORT_PATH,
    runbook_path: str = MANUAL_REVIEW_RUNBOOK_MD_PATH,
    review_kinds: Sequence[ReviewProgressKind] | None = None,
) -> Mapping[str, Any]:
    """Return a public-safe compact progress view for operator CLI use."""
    requested_kinds = tuple(review_kinds or ())
    requested_kind_set = set(requested_kinds)
    selected_gates = tuple(
        gate
        for gate in report.gates
        if not requested_kind_set or gate.review_kind in requested_kind_set
    )
    selected_ready_for_promotion = bool(selected_gates) and all(
        gate.ready_for_promotion for gate in selected_gates
    )
    selected_blockers: list[str] = []
    gate_summaries: list[Mapping[str, Any]] = []
    for gate in selected_gates:
        dependency_blockers = _lockbox_dependency_blockers(gate, report.gates)
        if not gate.ready_for_promotion:
            selected_blockers.append(
                f"{gate.review_kind}: {gate.complete_rows}/{gate.target_rows} ready"
            )
            selected_blockers.extend(
                f"{gate.review_kind}: {blocker}" for blocker in gate.blockers
            )
        gate_summaries.append(
            {
                "review_kind": gate.review_kind,
                "input_path": gate.input_path,
                "input_exists": gate.input_exists,
                "target_rows": gate.target_rows,
                "input_rows": gate.input_rows,
                "complete_rows": gate.complete_rows,
                "pending_rows": gate.pending_rows,
                "simulation_accepted": gate.simulation_accepted,
                "ready_for_promotion": gate.ready_for_promotion,
                "blocker_count": len(gate.blockers),
                "next_manual_action": _next_manual_action(
                    gate,
                    dependency_blockers=dependency_blockers,
                ),
                "blocked_by_review_kinds": list(dependency_blockers),
                "current_batch_status": _compact_current_batch_status(
                    gate.current_batch_status
                ),
                "batch_overview": _compact_batch_overview(gate),
                "review_aids": _review_aid_paths(gate),
                "field_contract": _review_field_contract(gate),
                "quality_gap_targets": _compact_quality_gap_targets(
                    gate.quality_gap_targets
                ),
                "next_batch_commands": dict(gate.next_batch_commands),
                "promotion_commands": {
                    "prepare": gate.prepare_command,
                    "dry_run": gate.dry_run_command,
                    "apply": gate.apply_command,
                },
            }
        )
    return {
        "path": path,
        "runbook_path": runbook_path,
        "ready_for_promotion_dry_run": selected_ready_for_promotion,
        "total_ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "blocker_count": len(_dedupe(selected_blockers)),
        "gate_count": len(selected_gates),
        "total_gate_count": len(report.gates),
        "reported_review_kinds": [gate.review_kind for gate in selected_gates],
        "gates": gate_summaries,
    }


def _current_batch_evidence_command(
    gate: ManualReviewGateProgress,
    batch_overview: Mapping[str, Any],
) -> str:
    current_batch_rows = int(
        batch_overview.get("current_batch_target_covered_rows") or 0
    )
    if current_batch_rows <= 0:
        return ""
    if gate.review_kind == "gold_set":
        return operator_command(
            "mosaic-rke write-gold-review-evidence --root . "
            f"--limit {current_batch_rows} --offset 0 "
            f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
        )
    if gate.review_kind == "footprint_review":
        return operator_command(
            "mosaic-rke write-footprint-review-evidence --root . "
            f"--limit {current_batch_rows} --offset 0 "
            f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        )
    return ""


def _action_queue_commands(
    gate: ManualReviewGateProgress,
    action: str,
    *,
    batch_overview: Mapping[str, Any] | None = None,
) -> Mapping[str, str]:
    next_batch = dict(gate.next_batch_commands)
    if action == "ready_for_promotion_apply":
        return {
            "dry_run": gate.dry_run_command,
            "apply": gate.apply_command,
        }
    if action == "fill_current_batch_review_fields_then_dry_run":
        commands = {
            key: command
            for key, command in next_batch.items()
            if key in {"assist", "evidence", "backfill_dry_run", "backfill_write", "dry_run"}
        }
        evidence_command = _current_batch_evidence_command(
            gate,
            batch_overview or {},
        )
        if evidence_command:
            commands["evidence"] = evidence_command
        return commands
    if action == "repair_current_batch_evidence_alignment":
        commands = {
            key: command
            for key, command in next_batch.items()
            if key in {"assist", "evidence"}
        }
        evidence_command = _current_batch_evidence_command(
            gate,
            batch_overview or {},
        )
        if evidence_command:
            commands["evidence"] = evidence_command
        return commands
    if action == "prepare_next_review_batch":
        return {
            key: command
            for key, command in next_batch.items()
            if key in {"assist", "prepare", "evidence"}
        }
    if action == "address_quality_gate_blockers":
        return {
            key: command
            for key, command in next_batch.items()
            if key
            in {
                "assist",
                "refresh_source_candidates",
                "expand_candidate_review_rows",
                "prepare_reviewed_failures",
                "prepare_expanded_batch",
                "evidence",
                "backfill_dry_run",
                "backfill_write",
                "dry_run",
            }
        }
    if action == "run_prepare_command":
        return {"prepare": gate.prepare_command}
    if action == "review_or_apply_source_license_policy":
        return {
            "prepare": gate.prepare_command,
            "dry_run": gate.dry_run_command,
        }
    if action == "complete_lockbox_decision_then_dry_run":
        return {
            "prepare": gate.prepare_command,
            "dry_run": gate.dry_run_command,
        }
    if action == "prepare_lockbox_review":
        return {"prepare": gate.prepare_command}
    return {}


def _post_current_batch_action(
    action: str,
    batch_overview: Mapping[str, Any],
) -> str:
    if action != "fill_current_batch_review_fields_then_dry_run":
        return ""
    covered_rows = int(batch_overview.get("current_batch_target_covered_rows") or 0)
    if covered_rows <= 0:
        return ""
    remaining_rows = int(batch_overview.get("remaining_rows_after_current_batch") or 0)
    if remaining_rows > 0:
        return "apply_current_batch_then_rerun_review_progress"
    return "apply_current_batch_then_prepare_promotion_import"


def _action_queue_hint(
    action: str,
    *,
    batch_overview: Mapping[str, Any] | None = None,
) -> str:
    hints = {
        "ready_for_promotion_apply": "Gate is ready; run dry-run, then apply if accepted.",
        "already_applied": "Gate is already applied; no operator action is required.",
        "fill_current_batch_review_fields_then_dry_run": (
            "Fill the current reviewed scratch fields, regenerate/check evidence, "
            "then run the dry-run."
        ),
        "repair_current_batch_evidence_alignment": (
            "Regenerate evidence for the current scratch batch before review."
        ),
        "prepare_next_review_batch": "Prepare the next review batch before filling fields.",
        "address_quality_gate_blockers": (
            "No pending rows remain; re-review failed gold labels or refresh the gold "
            "candidate set to expand document coverage."
        ),
        "run_prepare_command": "Run the prepare command to create the review input.",
        "review_or_apply_source_license_policy": (
            "Review the source-license policy, build the import, then dry-run/apply."
        ),
        "wait_for_prior_manual_gates": (
            "Wait until listed upstream manual gates are ready."
        ),
        "complete_lockbox_decision_then_dry_run": (
            "Fill the lockbox decision only after upstream gates are ready."
        ),
        "prepare_lockbox_review": "Prepare the lockbox review after upstream gates pass.",
    }
    hint = hints.get(action, "Inspect gate blockers before proceeding.")
    if action != "fill_current_batch_review_fields_then_dry_run":
        return hint
    overview = batch_overview if isinstance(batch_overview, Mapping) else {}
    covered_rows = int(overview.get("current_batch_target_covered_rows") or 0)
    pending_rows = int(overview.get("pending_rows") or 0)
    remaining_rows = int(overview.get("remaining_rows_after_current_batch") or 0)
    if covered_rows <= 0 or pending_rows <= 0:
        return hint
    if remaining_rows > 0:
        return (
            f"{hint} Current scratch covers {covered_rows} of {pending_rows} "
            f"pending target rows; after applying it, rerun review-progress and "
            f"prepare the remaining {remaining_rows} rows."
        )
    return (
        f"{hint} Current scratch covers all {pending_rows} pending target rows; "
        "after applying it, rerun review-progress and prepare the promotion import."
    )


def _action_queue_state(action: str) -> str:
    states = {
        "ready_for_promotion_apply": "ready_to_apply",
        "already_applied": "already_applied",
        "fill_current_batch_review_fields_then_dry_run": "needs_human_review_fields",
        "repair_current_batch_evidence_alignment": "needs_evidence_repair",
        "prepare_next_review_batch": "needs_prepare",
        "address_quality_gate_blockers": "needs_quality_gate_work",
        "run_prepare_command": "needs_prepare",
        "review_or_apply_source_license_policy": "needs_policy_review",
        "wait_for_prior_manual_gates": "waiting_on_dependencies",
        "complete_lockbox_decision_then_dry_run": "needs_lockbox_decision",
        "prepare_lockbox_review": "needs_prepare",
    }
    return states.get(action, "needs_operator_inspection")


def _action_queue_can_run_now(
    action_state: str,
    *,
    dependency_blockers: Sequence[ReviewProgressKind],
) -> bool:
    if dependency_blockers:
        return False
    return action_state in {
        "ready_to_apply",
        "needs_human_review_fields",
        "needs_evidence_repair",
        "needs_prepare",
        "needs_policy_review",
        "needs_quality_gate_work",
        "needs_lockbox_decision",
    }


def build_manual_review_action_queue(
    report: ManualReviewProgressReport,
    *,
    path: str = MANUAL_REVIEW_PROGRESS_REPORT_PATH,
    runbook_path: str = MANUAL_REVIEW_RUNBOOK_MD_PATH,
    review_kinds: Sequence[ReviewProgressKind] | None = None,
    action_states: Sequence[str] | None = None,
) -> Mapping[str, Any]:
    """Return the next public-safe operator actions without full gate payloads."""
    requested_kinds = tuple(review_kinds or ())
    requested_kind_set = set(requested_kinds)
    requested_states = tuple(str(state) for state in (action_states or ()) if str(state))
    requested_state_set = set(requested_states)
    selected_gates = tuple(
        gate
        for gate in report.gates
        if not requested_kind_set or gate.review_kind in requested_kind_set
    )
    actions: list[Mapping[str, Any]] = []
    for action_rank, gate in enumerate(selected_gates, 1):
        current = (
            gate.current_batch_status
            if isinstance(gate.current_batch_status, Mapping)
            else {}
        )
        evidence = current.get("evidence_status")
        evidence_aligned = (
            bool(evidence.get("aligned")) if isinstance(evidence, Mapping) else None
        )
        dependency_blockers = _lockbox_dependency_blockers(gate, report.gates)
        action = _next_manual_action(
            gate,
            dependency_blockers=dependency_blockers,
        )
        action_state = _action_queue_state(action)
        if requested_state_set and action_state not in requested_state_set:
            continue
        can_run_now = _action_queue_can_run_now(
            action_state,
            dependency_blockers=dependency_blockers,
        )
        current_batch_path = str(current.get("path") or "")
        stale_current_batch = _current_batch_stale_after_promotion_ready(gate)
        active_manual_input_path = (
            gate.input_path
            if gate.ready_for_promotion
            else current_batch_path or gate.input_path
        )
        batch_overview = _compact_batch_overview(gate)
        actions.append(
            {
                "action_rank": action_rank,
                "review_kind": gate.review_kind,
                "next_manual_action": action,
                "action_state": action_state,
                "can_run_now": can_run_now,
                "blocks_promotion": not gate.ready_for_promotion,
                "operator_hint": _action_queue_hint(
                    action,
                    batch_overview=batch_overview,
                ),
                "post_current_batch_action": _post_current_batch_action(
                    action,
                    batch_overview,
                ),
                "ready_for_promotion": gate.ready_for_promotion,
                "blocked_by_review_kinds": list(dependency_blockers),
                "complete_rows": gate.complete_rows,
                "pending_rows": gate.pending_rows,
                "target_rows": gate.target_rows,
                "manual_input_path": active_manual_input_path,
                "promotion_input_path": gate.input_path,
                "current_batch_path": current_batch_path,
                "current_batch_pending_rows": (
                    0
                    if stale_current_batch
                    else int(current.get("pending_rows") or 0)
                ),
                "current_batch_malformed_rows": int(
                    current.get("malformed_rows") or 0
                ),
                "current_batch_stale_after_promotion_ready": stale_current_batch,
                "batch_overview": batch_overview,
                "review_aids": _review_aid_paths(gate),
                "field_contract": _review_field_contract(gate),
                "quality_gap_targets": _compact_quality_gap_targets(
                    gate.quality_gap_targets
                ),
                "missing_required_fields": dict(
                    {} if stale_current_batch else current.get("missing_required_fields") or {}
                ),
                "evidence_aligned": None if stale_current_batch else evidence_aligned,
                "commands": dict(
                    _action_queue_commands(
                        gate,
                        action,
                        batch_overview=batch_overview,
                    )
                ),
            }
        )
    selected_ready_for_promotion = bool(actions) and all(
        bool(action.get("ready_for_promotion")) for action in actions
    )
    return {
        "path": path,
        "runbook_path": runbook_path,
        "ready_for_promotion_dry_run": selected_ready_for_promotion,
        "total_ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "action_count": len(actions),
        "total_gate_count": len(report.gates),
        "reported_review_kinds": [str(action["review_kind"]) for action in actions],
        "reported_action_states": list(requested_states),
        "actions": actions,
    }


def render_manual_review_runbook_markdown(report: ManualReviewProgressReport) -> str:
    gate_lookup = {gate.review_kind: gate for gate in report.gates}
    gold = gate_lookup["gold_set"]
    footprint = gate_lookup["footprint_review"]
    source_license = gate_lookup["source_license"]
    lockbox = gate_lookup["lockbox"]
    lockbox_dependency_blockers = _lockbox_dependency_blockers(lockbox, report.gates)
    lockbox_dependency_summary = (
        "ready"
        if not lockbox_dependency_blockers
        else "waiting_on " + ", ".join(lockbox_dependency_blockers)
    )
    lockbox_prepare_line = (
        f"- Lockbox: `{lockbox.prepare_command}`"
        if not lockbox_dependency_blockers
        else (
            f"- Lockbox: wait for upstream gates before running "
            f"`{lockbox.prepare_command}`"
        )
    )
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
        "--priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
    )
    footprint_batch_dry_run = operator_command(
        "mosaic-rke apply-footprint-review --root . "
        f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
    )
    footprint_batch_apply = operator_command(
        "mosaic-rke apply-footprint-review --root . "
        f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
    footprint_assist = operator_command(
        "mosaic-rke write-footprint-review-assist --root . "
        f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
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
        f"- Lockbox dependency status: {lockbox_dependency_summary}",
        "",
        "## Current Batch Scratch",
        "",
        "This section reports aggregate completion counts for the current local batch or decision files only; it does not include source text, claim text, or reviewer notes.",
        *_render_batch_status_lines("Gold-set batch", gold.current_batch_status),
        *_render_current_batch_coverage_lines("Gold-set batch", gold),
        *_render_batch_status_lines(
            "Analytical-footprint batch",
            footprint.current_batch_status,
        ),
        *_render_current_batch_coverage_lines(
            "Analytical-footprint batch",
            footprint,
        ),
        *_render_batch_status_lines("Lockbox decision", lockbox.current_batch_status),
        "",
        "## Prepare Commands",
        "",
        f"- Temp workspace: `{RKE_OPERATOR_TMP_ENV_PREFIX}` keeps review-progress and promotion dry-run registry copies out of system `/tmp`; generated commands below include this prefix.",
        f"- Gold-set: `{gold.prepare_command}`",
        f"- Analytical-footprint: `{footprint.prepare_command}`",
        f"- Source-license: `{source_license.prepare_command}`",
        lockbox_prepare_line,
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
        "## Manual Field Contracts",
        "",
        "These contracts are public-safe field rules for reviewer-edited input files. They do not include source text, claim text, evidence snippets, or reviewer notes.",
        "",
        *_render_field_contract_lines(
            "Gold-set review",
            manual_review_field_contract("gold_set"),
        ),
        *_render_field_contract_lines(
            "Analytical-footprint review",
            manual_review_field_contract("footprint_review"),
        ),
        *_render_field_contract_lines(
            "Source-license review",
            manual_review_field_contract("source_license"),
        ),
        *_render_field_contract_lines(
            "Lockbox review",
            manual_review_field_contract("lockbox"),
        ),
        "## Gate Acceptance Criteria",
        "",
        "Gold-set review is accepted only when all current claim rows are completed and the dry run accepts the import.",
        "Each gold-set row must keep the template IDs and hashes intact and must fill `manual_claim_text`, `reviewer`, `review_date`, `claim_correct`, `source_span_supports_claim`, `direction_correct`, `target_correct`, `horizon_correct`, `variable_mapping_correct`, and `unsupported_field_false_grounded`.",
        f"Use `{gold_full_prepare}` to prefill reviewer identity and date only; claim text and boolean review decisions remain human judgments.",
        f"For batch work, use `{gold_batch_prepare}`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.",
        f"Batch gold-set imports use `{gold_batch_dry_run}`, then `{gold_batch_apply}` after the batch is accepted.",
        f"Use `{gold_evidence}` after preparing the current gold scratch batch to regenerate a batch-aligned private source-evidence draft.",
        "The resulting gold-set summary must satisfy the code-defined gate: at least 50 documents, at least 100 claims, claim precision >= 0.85, span-support precision >= 0.90, direction accuracy >= 0.85, target accuracy >= 0.85, horizon accuracy >= 0.85, variable mapping accuracy >= 0.80, and unsupported-field false grounding <= 0.05.",
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
        f"`{_promotion_dry_run_command(source_license)}`",
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
