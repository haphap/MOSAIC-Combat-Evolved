"""Hash manifest for the manual RKE review handoff bundle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

MANUAL_REVIEW_BUNDLE_MANIFEST_PATH = "registry/review_batches/manual_review_bundle_manifest.json"

BundleArtifactFormat = Literal["json", "jsonl", "markdown"]

MANUAL_REVIEW_BUNDLE_ARTIFACTS: tuple[tuple[str, str, BundleArtifactFormat], ...] = (
    ("operator_handoff_json", "registry/handoffs/rke_operator_handoff.json", "json"),
    ("operator_handoff_markdown", "registry/handoffs/rke_operator_handoff.md", "markdown"),
    ("manual_review_batch_status", "registry/review_batches/manual_review_batch_status.json", "json"),
    ("gold_review_packet_json", "registry/gold_sets/tushare_research_reports.review_packet.json", "json"),
    ("gold_review_packet_markdown", "registry/gold_sets/tushare_research_reports.review_packet.md", "markdown"),
    ("gold_next_import_template", "registry/review_batches/gold_set_next_import_template.jsonl", "jsonl"),
    ("gold_full_import_template", "registry/review_batches/gold_set_full_import_template.jsonl", "jsonl"),
    ("gold_blank_import_report", "registry/gold_sets/tushare_research_reports.review_import_report.json", "json"),
    ("license_review_packet_json", "registry/compliance/tushare_license_review_packet.json", "json"),
    ("license_review_packet_markdown", "registry/compliance/tushare_license_review_packet.md", "markdown"),
    ("license_next_import_template", "registry/review_batches/source_license_next_import_template.jsonl", "jsonl"),
    ("license_policy_template", "registry/review_batches/source_license_policy_template.json", "json"),
    ("license_policy_blank_import_report", "registry/review_batches/source_license_policy_import_report.json", "json"),
    ("lockbox_import_template", "registry/review_batches/lockbox_review_next_import_template.json", "json"),
    ("lockbox_blank_import_report", "registry/lockbox/central_bank_lockbox_review_import_report.json", "json"),
    ("promotion_blank_dry_run_report", "registry/promotion/rke_promotion_dry_run_report.json", "json"),
)


@dataclass(frozen=True)
class ManualReviewBundleArtifact:
    role: str
    path: str
    format: BundleArtifactFormat
    exists: bool
    bytes: int
    sha256: str
    row_count: int | None


@dataclass(frozen=True)
class ManualReviewBundleManifest:
    manifest_id: str
    accepted: bool
    artifact_count: int
    artifacts: Sequence[ManualReviewBundleArtifact]
    promotion_dry_run: Mapping[str, Any] | None
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


def _file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _load_jsonl_artifact(path: Path, *, label: str) -> tuple[list[tuple[int, Any]], tuple[str, ...]]:
    rows: list[tuple[int, Any]] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((line_number, json.loads(line)))
            except json.JSONDecodeError as exc:
                errors.append(f"{label} row {line_number} must contain valid JSON: {exc.msg}")
    return rows, tuple(errors)


def _inspect_artifact(
    root_path: Path,
    *,
    role: str,
    relative_path: str,
    artifact_format: BundleArtifactFormat,
) -> tuple[ManualReviewBundleArtifact, tuple[str, ...]]:
    path = root_path / relative_path
    blockers: list[str] = []
    if not path.exists():
        return (
            ManualReviewBundleArtifact(
                role=role,
                path=relative_path,
                format=artifact_format,
                exists=False,
                bytes=0,
                sha256="",
                row_count=None,
            ),
            (f"{relative_path} missing",),
        )

    byte_count = path.stat().st_size
    if byte_count <= 0:
        blockers.append(f"{relative_path} empty")

    row_count: int | None = None
    if artifact_format == "json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            blockers.append(f"{relative_path} must contain valid JSON: {exc.msg}")
        else:
            if not isinstance(payload, Mapping):
                blockers.append(f"{relative_path} must be object")
    elif artifact_format == "jsonl":
        rows, parse_blockers = _load_jsonl_artifact(path, label=relative_path)
        row_count = len(rows) + len(parse_blockers)
        blockers.extend(parse_blockers)
        invalid_rows = [
            str(line_number)
            for line_number, row in rows
            if not isinstance(row, Mapping)
        ]
        if invalid_rows:
            blockers.append(
                f"{relative_path} row must be object at row(s): "
                + ", ".join(invalid_rows)
            )

    return (
        ManualReviewBundleArtifact(
            role=role,
            path=relative_path,
            format=artifact_format,
            exists=True,
            bytes=byte_count,
            sha256=_file_sha256(path) if byte_count > 0 else "",
            row_count=row_count,
        ),
        tuple(blockers),
    )


def _promotion_dry_run_summary(root_path: Path) -> Mapping[str, Any] | None:
    path = root_path / "registry/promotion/rke_promotion_dry_run_report.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None

    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    step_rows = [step for step in steps if isinstance(step, Mapping)]
    return {
        "accepted": payload.get("accepted") if isinstance(payload.get("accepted"), bool) else None,
        "after_next_state": str(payload.get("after_next_state") or ""),
        "production_allowed_after_simulation": (
            payload.get("production_allowed_after_simulation")
            if isinstance(payload.get("production_allowed_after_simulation"), bool)
            else None
        ),
        "staged_production_allowed_after_simulation": (
            payload.get("staged_production_allowed_after_simulation")
            if isinstance(payload.get("staged_production_allowed_after_simulation"), bool)
            else None
        ),
        "provided_steps": [
            str(step.get("review_kind") or "") for step in step_rows if step.get("provided") is True
        ],
        "accepted_steps": [
            str(step.get("review_kind") or "") for step in step_rows if step.get("accepted") is True
        ],
        "rejected_steps": [
            str(step.get("review_kind") or "") for step in step_rows if step.get("accepted") is False
        ],
        "missing_steps": [
            str(step.get("review_kind") or "") for step in step_rows if step.get("provided") is False
        ],
    }


def build_manual_review_bundle_manifest(root: str | Path = ".") -> ManualReviewBundleManifest:
    root_path = Path(root)
    artifacts: list[ManualReviewBundleArtifact] = []
    blockers: list[str] = []
    for role, relative_path, artifact_format in MANUAL_REVIEW_BUNDLE_ARTIFACTS:
        artifact, artifact_blockers = _inspect_artifact(
            root_path,
            role=role,
            relative_path=relative_path,
            artifact_format=artifact_format,
        )
        artifacts.append(artifact)
        blockers.extend(artifact_blockers)

    return ManualReviewBundleManifest(
        manifest_id="RKE-MANUAL-REVIEW-BUNDLE-MANIFEST-20260606",
        accepted=not blockers,
        artifact_count=len(artifacts),
        artifacts=tuple(artifacts),
        promotion_dry_run=_promotion_dry_run_summary(root_path),
        blockers=tuple(blockers),
    )


def write_manual_review_bundle_manifest(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    manifest = build_manual_review_bundle_manifest(root_path)
    result = _write_json(root_path / MANUAL_REVIEW_BUNDLE_MANIFEST_PATH, asdict(manifest))
    return {
        "path": str(result["path"]),
        "accepted": manifest.accepted,
        "artifact_count": manifest.artifact_count,
    }
