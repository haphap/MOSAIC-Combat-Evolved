"""Validation gate for RKE policy documentation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


POLICY_DOC_VALIDATION_REPORT_PATH = "registry/docs/rke_policy_doc_validation_report.json"

REQUIRED_POLICY_DOC_MARKERS: Mapping[str, Sequence[str]] = {
    "docs/master_plan_v1_1.md": (
        "MOSAIC Prompt Evolution",
        "最终验收标准",
        "Compliance / License Gate",
        "Checker 规则清单",
    ),
    "docs/rke_phase_minus_1_plan.md": (
        "PIT Data Availability",
        "Claim Extraction Reliability",
        "mosaic-rke gold-candidate-claims",
        "mosaic-rke review-batches",
        "mosaic-rke apply-gold-review",
        "mosaic-rke apply-license-review",
    ),
    "docs/claim_extraction_guidelines.md": (
        "Source-Grounded Claim",
        "Hypothesis",
        "Gold Set Gate",
        "Candidate Claims",
        "mosaic-rke apply-gold-review",
    ),
    "docs/validation_policy.md": (
        "experiment family",
        "Effective sample size",
        "Statistical Controls",
        "Cost-Aware Acceptance",
        "Promotion Boundary",
        "mosaic-rke promotion-status",
        "mosaic-rke apply-lockbox-review",
    ),
    "docs/confidence_policy.md": (
        "Conservative Function",
        "Research-Only Rule",
        "Required Runtime Components",
        "Calibration",
    ),
    "docs/compliance_policy.md": (
        "License Status",
        "Production Runtime Gate",
        "Manual License Review",
        "mosaic-rke apply-license-review",
        "mosaic-rke source-text-status",
        "Original Text Handling",
    ),
}


@dataclass(frozen=True)
class PolicyDocValidationRecord:
    path: str
    accepted: bool
    missing_markers: Sequence[str]
    bytes: int


@dataclass(frozen=True)
class PolicyDocValidationReport:
    report_id: str
    accepted: bool
    failure_count: int
    records: Sequence[PolicyDocValidationRecord]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def build_policy_doc_validation_report(root: str | Path = ".") -> PolicyDocValidationReport:
    root_path = Path(root)
    records: list[PolicyDocValidationRecord] = []
    for relative, markers in REQUIRED_POLICY_DOC_MARKERS.items():
        path = root_path / relative
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = tuple(marker for marker in markers if marker not in text)
        records.append(
            PolicyDocValidationRecord(
                path=relative,
                accepted=path.exists() and bool(text.strip()) and not missing,
                missing_markers=missing,
                bytes=path.stat().st_size if path.exists() else 0,
            )
        )
    failure_count = sum(len(record.missing_markers) + (0 if record.bytes > 0 else 1) for record in records)
    return PolicyDocValidationReport(
        report_id="RKE-POLICY-DOC-VALIDATION-REPORT-20260606",
        accepted=all(record.accepted for record in records),
        failure_count=failure_count,
        records=tuple(records),
    )


def write_policy_doc_validation_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_policy_doc_validation_report(root_path)
    return _write_json(root_path / POLICY_DOC_VALIDATION_REPORT_PATH, asdict(report))
