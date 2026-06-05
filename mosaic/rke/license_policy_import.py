"""Expand a signed source-license policy into sparse review import rows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manual_review_import import LICENSE_REVIEW_TEMPLATE_PATH, TARGET_ROW_HASH_FIELD, review_row_fingerprint
from .phase_minus1 import load_jsonl


DEFAULT_LICENSE_POLICY_IMPORT_PATH = "registry/review_batches/source_license_policy_import.jsonl"
LICENSE_POLICY_IMPORT_REPORT_PATH = "registry/review_batches/source_license_policy_import_report.json"
SOURCE_LICENSE_POLICY_TEMPLATE_PATH = "registry/review_batches/source_license_policy_template.json"
MATCHED_ROWS_FINGERPRINT_FIELD = "matched_rows_fingerprint"


@dataclass(frozen=True)
class SourceLicensePolicyFilters:
    source_type: Sequence[str] = ()
    current_license_status: Sequence[str] = ()
    publish_date_min: str | None = None
    publish_date_max: str | None = None
    source_id_prefix: Sequence[str] = ()


@dataclass(frozen=True)
class SourceLicensePolicyImportReport:
    report_id: str
    policy_path: str
    target_review_path: str
    output_path: str
    dry_run: bool
    accepted: bool
    total_review_rows: int
    matched_rows: int
    output_rows: int
    reviewer: str
    review_date: str
    approved_for_derived_claim_storage: bool | None
    approved_for_production_runtime: bool | None
    filters: SourceLicensePolicyFilters
    blockers: Sequence[str]


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


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"path": str(path), "rows": len(rows)}


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, list | tuple) else [value]
    return tuple(str(item).strip() for item in values if str(item).strip())


def _load_policy(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("source-license policy must be a JSON object")
    return payload


def _policy_filters(policy: Mapping[str, Any]) -> SourceLicensePolicyFilters:
    raw_filters = policy.get("filters") or {}
    if not isinstance(raw_filters, Mapping):
        raise ValueError("source-license policy filters must be an object")
    return SourceLicensePolicyFilters(
        source_type=_as_str_tuple(raw_filters.get("source_type")),
        current_license_status=_as_str_tuple(raw_filters.get("current_license_status")),
        publish_date_min=(
            str(raw_filters.get("publish_date_min")).strip()
            if raw_filters.get("publish_date_min") is not None
            else None
        ),
        publish_date_max=(
            str(raw_filters.get("publish_date_max")).strip()
            if raw_filters.get("publish_date_max") is not None
            else None
        ),
        source_id_prefix=_as_str_tuple(raw_filters.get("source_id_prefix")),
    )


def _matches(row: Mapping[str, Any], filters: SourceLicensePolicyFilters) -> bool:
    source_type = str(row.get("source_type") or "")
    current_status = str(row.get("current_license_status") or "")
    publish_date = str(row.get("publish_date") or "")
    source_id = str(row.get("source_id") or "")
    if filters.source_type and source_type not in set(filters.source_type):
        return False
    if filters.current_license_status and current_status not in set(filters.current_license_status):
        return False
    if filters.publish_date_min and publish_date < filters.publish_date_min:
        return False
    if filters.publish_date_max and publish_date > filters.publish_date_max:
        return False
    return not filters.source_id_prefix or any(
        source_id.startswith(prefix) for prefix in filters.source_id_prefix
    )


def _matched_rows_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "source_id": str(row.get("source_id") or ""),
            TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        }
        for row in rows
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def _review_row(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "approved_for_derived_claim_storage": policy.get("approved_for_derived_claim_storage"),
        "approved_for_production_runtime": policy.get("approved_for_production_runtime"),
        "current_license_status": str(row.get("current_license_status") or ""),
        "notes": str(policy.get("notes") or ""),
        "publish_date": str(row.get("publish_date") or ""),
        "review_date": str(policy.get("review_date") or ""),
        "review_context_ref": str(policy.get("review_context_ref") or "registry/compliance/tushare_license_review_packet.json"),
        "reviewer": str(policy.get("reviewer") or ""),
        "source_id": str(row.get("source_id") or ""),
        "source_type": str(row.get("source_type") or ""),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(row),
        "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
        "title": str(row.get("title") or ""),
    }


def build_source_license_policy_template(root: str | Path = ".") -> Mapping[str, Any]:
    """Build a reviewer-fillable policy template for same-source license batches.

    The template is intentionally not accepted by ``build-license-review-import``
    until a reviewer supplies the booleans, reviewer, and review_date.
    """
    root_path = Path(root)
    review_rows = load_jsonl(root_path / LICENSE_REVIEW_TEMPLATE_PATH)
    source_types = sorted({str(row.get("source_type") or "") for row in review_rows if row.get("source_type")})
    statuses = sorted(
        {
            str(row.get("current_license_status") or "")
            for row in review_rows
            if row.get("current_license_status")
        }
    )
    publish_dates = sorted(str(row.get("publish_date") or "") for row in review_rows if row.get("publish_date"))
    filters = SourceLicensePolicyFilters(
        current_license_status=tuple(statuses),
        source_type=tuple(source_types),
    )
    matched_rows = [row for row in review_rows if _matches(row, filters)]
    return {
        "approved_for_derived_claim_storage": None,
        "approved_for_production_runtime": None,
        "build_command": (
            "mosaic-rke build-license-review-import --root . "
            f"--policy {SOURCE_LICENSE_POLICY_TEMPLATE_PATH} "
            f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH}"
        ),
        "dry_run_command": (
            "mosaic-rke apply-license-review --root . "
            f"--input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
        ),
        "filters": {
            "current_license_status": statuses,
            "source_type": source_types,
        },
        "matched_row_count": len(matched_rows),
        MATCHED_ROWS_FINGERPRINT_FIELD: _matched_rows_fingerprint(matched_rows),
        "notes": "",
        "publish_date_max": publish_dates[-1] if publish_dates else None,
        "publish_date_min": publish_dates[0] if publish_dates else None,
        "review_date": "",
        "review_context_ref": "registry/compliance/tushare_license_review_packet.json",
        "reviewer": "",
        "target_review_path": LICENSE_REVIEW_TEMPLATE_PATH,
        "template_note": (
            "Reviewer must fill reviewer, review_date, notes, and both approval "
            "booleans before expanding this policy into per-source import rows."
        ),
    }


def write_source_license_policy_template(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    return _write_json(
        root_path / SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        build_source_license_policy_template(root_path),
    )


def build_source_license_policy_import(
    root: str | Path,
    policy_path: str | Path,
    *,
    output_path: str | Path = DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    dry_run: bool = False,
) -> SourceLicensePolicyImportReport:
    """Build a sparse ``apply-license-review`` input from a signed policy file.

    This does not apply the decision. Reviewers must inspect the generated JSONL
    and pass it to ``apply-license-review`` to update the registry.
    """
    root_path = Path(root)
    resolved_policy_path = Path(policy_path)
    if not resolved_policy_path.is_absolute():
        resolved_policy_path = root_path / resolved_policy_path
    resolved_output_path = Path(output_path)
    if not resolved_output_path.is_absolute():
        resolved_output_path = root_path / resolved_output_path

    policy = _load_policy(resolved_policy_path)
    filters = _policy_filters(policy)
    reviewer = str(policy.get("reviewer") or "").strip()
    review_date = str(policy.get("review_date") or "").strip()
    derived = policy.get("approved_for_derived_claim_storage")
    production = policy.get("approved_for_production_runtime")
    review_rows = load_jsonl(root_path / LICENSE_REVIEW_TEMPLATE_PATH)
    matched = [row for row in review_rows if _matches(row, filters)]
    output_rows = [_review_row(row, policy) for row in matched]
    matched_rows_fingerprint = _matched_rows_fingerprint(matched)

    blockers: list[str] = []
    if str(policy.get("target_review_path") or "").strip() != LICENSE_REVIEW_TEMPLATE_PATH:
        blockers.append(f"target_review_path must match {LICENSE_REVIEW_TEMPLATE_PATH}")
    if str(policy.get(MATCHED_ROWS_FINGERPRINT_FIELD) or "").strip() != matched_rows_fingerprint:
        blockers.append(f"{MATCHED_ROWS_FINGERPRINT_FIELD} does not match current matched rows")
    if policy.get("matched_row_count") != len(matched):
        blockers.append("matched_row_count does not match current matched rows")
    if not reviewer:
        blockers.append("reviewer required")
    if not review_date:
        blockers.append("review_date required")
    if not isinstance(derived, bool):
        blockers.append("approved_for_derived_claim_storage must be boolean")
    if not isinstance(production, bool):
        blockers.append("approved_for_production_runtime must be boolean")
    if not matched:
        blockers.append("policy filters matched zero source-license rows")
    if not any(
        (
            filters.source_type,
            filters.current_license_status,
            filters.publish_date_min,
            filters.publish_date_max,
            filters.source_id_prefix,
        )
    ):
        blockers.append("at least one policy filter is required")

    accepted = not blockers
    if accepted and not dry_run:
        _write_jsonl(resolved_output_path, output_rows)

    report = SourceLicensePolicyImportReport(
        report_id="RKE-SOURCE-LICENSE-POLICY-IMPORT-REPORT-20260606",
        policy_path=str(resolved_policy_path),
        target_review_path=LICENSE_REVIEW_TEMPLATE_PATH,
        output_path=str(resolved_output_path),
        dry_run=dry_run,
        accepted=accepted,
        total_review_rows=len(review_rows),
        matched_rows=len(matched),
        output_rows=0 if dry_run else len(output_rows) if accepted else 0,
        reviewer=reviewer,
        review_date=review_date,
        approved_for_derived_claim_storage=derived if isinstance(derived, bool) else None,
        approved_for_production_runtime=production if isinstance(production, bool) else None,
        filters=filters,
        blockers=tuple(blockers),
    )
    _write_json(root_path / LICENSE_POLICY_IMPORT_REPORT_PATH, asdict(report))
    return report
