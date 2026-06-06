"""Controlled import path for final lockbox review records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lockbox import LockboxReview, evaluate_lockbox_review
from .manual_review_import import (
    TARGET_ROW_HASH_FIELD,
    manual_review_forbidden_field_paths,
    review_row_fingerprint,
)


LOCKBOX_POLICY_PATH = "registry/evaluation/lockbox/lockbox_policy.json"
LOCKBOX_REVIEW_PATH = "registry/lockbox/central_bank_lockbox_review.json"
LOCKBOX_REVIEW_IMPORT_REPORT_PATH = "registry/lockbox/central_bank_lockbox_review_import_report.json"
LOCKBOX_REVIEW_CONTEXT_HASH_FIELD = "review_context_hash"

LOCKBOX_REQUIRED_FIELDS = (
    "experiment_family_id",
    "experiment_id",
    "opened_at",
    "opened_by",
    "open_count",
    "result",
)
LOCKBOX_BOOL_FIELDS = (
    "parameter_search_after_open",
    "rule_design_after_open",
)
LOCKBOX_RESULTS = {"not_opened", "passed", "failed"}


@dataclass(frozen=True)
class LockboxReviewImportReport:
    report_id: str
    input_path: str
    target_path: str
    dry_run: bool
    accepted: bool
    applied: bool
    result: str
    production_allowed: bool
    decision_state: str
    next_state: str
    rejected_reasons: Sequence[str]
    policy_reasons: Sequence[str]
    downstream_outputs: Mapping[str, str]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(root_path: Path, input_path: str | Path) -> Path:
    path = Path(input_path)
    return path if path.is_absolute() else root_path / path


def _normalize_lockbox_row(row: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "experiment_family_id": str(row.get("experiment_family_id") or ""),
        "experiment_id": str(row.get("experiment_id") or ""),
        "opened_at": str(row.get("opened_at") or ""),
        "opened_by": str(row.get("opened_by") or ""),
        "open_count": row.get("open_count"),
        "result": str(row.get("result") or ""),
        "parameter_search_after_open": row.get("parameter_search_after_open", False),
        "rule_design_after_open": row.get("rule_design_after_open", False),
        "notes": str(row.get("notes") or ""),
    }


def _provenance_failures(
    row: Mapping[str, Any],
    target: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[str]:
    failures: list[str] = []
    if str(row.get("target_review_path") or "").strip() != LOCKBOX_REVIEW_PATH:
        failures.append(f"target_review_path must match {LOCKBOX_REVIEW_PATH}")
    if str(row.get("review_context_ref") or "").strip() != LOCKBOX_POLICY_PATH:
        failures.append(f"review_context_ref must match {LOCKBOX_POLICY_PATH}")
    if str(row.get(TARGET_ROW_HASH_FIELD) or "").strip() != review_row_fingerprint(target):
        failures.append(f"{TARGET_ROW_HASH_FIELD} does not match current lockbox review target")
    if str(row.get(LOCKBOX_REVIEW_CONTEXT_HASH_FIELD) or "").strip() != review_row_fingerprint(policy):
        failures.append(
            f"{LOCKBOX_REVIEW_CONTEXT_HASH_FIELD} does not match current lockbox review context"
        )
    return failures


def _forbidden_field_failures(row: Mapping[str, Any]) -> list[str]:
    return [
        f"{field} forbidden in lockbox review import"
        for field in manual_review_forbidden_field_paths(row)
    ]


def _row_failures(row: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for field in LOCKBOX_REQUIRED_FIELDS:
        if field == "open_count":
            if row.get(field) is None:
                failures.append(f"{field} required")
            continue
        if not str(row.get(field) or "").strip():
            failures.append(f"{field} required")
    if row.get("experiment_family_id") != target.get("experiment_family_id"):
        failures.append("experiment_family_id must match current lockbox target")
    if row.get("experiment_id") != target.get("experiment_id"):
        failures.append("experiment_id must match current lockbox target")
    if row.get("result") not in LOCKBOX_RESULTS:
        failures.append("result must be one of not_opened, passed, failed")
    if type(row.get("open_count")) is not int:
        failures.append("open_count must be integer")
    elif int(row.get("open_count") or 0) < 0:
        failures.append("open_count must be non-negative")
    for field in LOCKBOX_BOOL_FIELDS:
        if not isinstance(row.get(field), bool):
            failures.append(f"{field} must be boolean")
    if row.get("result") in {"passed", "failed"}:
        if not str(row.get("opened_at") or "").strip():
            failures.append("opened_at required when lockbox is opened")
        if not str(row.get("opened_by") or "").strip():
            failures.append("opened_by required when lockbox is opened")
        if type(row.get("open_count")) is int and row.get("open_count", 0) < 1:
            failures.append("open_count must be >= 1 when lockbox is opened")
    if row.get("result") == "not_opened":
        if row.get("open_count") not in (0, None):
            failures.append("not_opened lockbox must have open_count=0")
    return failures


def _write_lockbox_downstream(root_path: Path) -> dict[str, str]:
    from .dashboard_reports import write_dashboard_reports
    from .master_plan_coverage import write_master_plan_coverage_report
    from .operator_handoff import write_operator_handoff
    from .promotion_gate import write_production_promotion_gate_report
    from .registry_manifest import write_registry_manifest

    outputs: dict[str, str] = {}
    outputs["production_promotion_gate"] = str(write_production_promotion_gate_report(root_path)["path"])
    operator_handoff = write_operator_handoff(root_path)
    outputs["operator_handoff.json"] = operator_handoff["json"]
    outputs["operator_handoff.markdown"] = operator_handoff["markdown"]
    outputs["lockbox_review_import_template"] = operator_handoff["lockbox_import_template"]
    outputs.update({f"dashboard.{key}": value for key, value in write_dashboard_reports(root_path).items()})
    outputs["master_plan_coverage"] = str(write_master_plan_coverage_report(root_path)["path"])
    outputs["registry_manifest"] = str(write_registry_manifest(root_path)["path"])
    return outputs


def apply_lockbox_review_import(
    root: str | Path,
    input_path: str | Path,
    *,
    dry_run: bool = False,
) -> LockboxReviewImportReport:
    root_path = Path(root)
    resolved_input = _resolve_path(root_path, input_path)
    target_path = root_path / LOCKBOX_REVIEW_PATH
    target = _read_json(target_path)
    policy = _read_json(root_path / LOCKBOX_POLICY_PATH)
    input_row = _read_json(resolved_input)
    normalized = _normalize_lockbox_row(input_row, target)
    rejected_reasons = _row_failures(normalized, target)
    rejected_reasons.extend(_forbidden_field_failures(input_row))
    rejected_reasons.extend(_provenance_failures(input_row, target, policy))
    decision = (
        evaluate_lockbox_review(LockboxReview(**normalized))
        if not rejected_reasons
        else evaluate_lockbox_review(None)
    )
    accepted = not rejected_reasons
    downstream_outputs: dict[str, str] = {}
    applied = False
    if accepted and not dry_run:
        _write_json(target_path, normalized)
        downstream_outputs = _write_lockbox_downstream(root_path)
        applied = True

    report = LockboxReviewImportReport(
        report_id="RKE-LOCKBOX-REVIEW-IMPORT-REPORT-20260606",
        input_path=str(resolved_input),
        target_path=LOCKBOX_REVIEW_PATH,
        dry_run=dry_run,
        accepted=accepted,
        applied=applied,
        result=str(normalized.get("result") or ""),
        production_allowed=decision.production_allowed,
        decision_state=decision.state,
        next_state=decision.next_state,
        rejected_reasons=tuple(rejected_reasons),
        policy_reasons=tuple(decision.reasons),
        downstream_outputs=downstream_outputs,
    )
    _write_json(root_path / LOCKBOX_REVIEW_IMPORT_REPORT_PATH, asdict(report))
    return report
