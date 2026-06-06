"""Read-only progress checks for reviewer-edited RKE scratch files."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    build_source_license_policy_import,
)
from .lockbox_review_import import apply_lockbox_review_import
from .manual_review_batches import (
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    build_manual_review_batch_status,
)
from .manual_review_import import (
    apply_gold_set_review_import,
    apply_source_license_review_import,
)
from .operator_handoff import LOCKBOX_REVIEWED_IMPORT_PATH
from .review_gates import summarize_gold_set_review, summarize_source_license_review


MANUAL_REVIEW_PROGRESS_REPORT_ID = "RKE-MANUAL-REVIEW-PROGRESS-20260606"

ReviewProgressKind = Literal["gold_set", "source_license", "lockbox"]


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


def _missing_gate(
    *,
    review_kind: ReviewProgressKind,
    input_path: str,
    target_rows: int,
    prepare_command: str,
    dry_run_command: str,
    apply_command: str,
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
    )


def _gold_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = GOLD_FULL_REVIEWED_IMPORT_PATH
    target_rows = build_manual_review_batch_status(root_path)[0].gold_set.pending_rows
    resolved_input = _resolve(root_path, input_path)
    prepare_command = "mosaic-rke prepare-gold-review --root . --full"
    dry_run_command = f"mosaic-rke apply-gold-review --root . --input {input_path} --dry-run"
    apply_command = f"mosaic-rke apply-gold-review --root . --input {input_path}"
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="gold_set",
            input_path=input_path,
            target_rows=target_rows,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
        )

    input_rows = _jsonl_row_count(resolved_input)
    with tempfile.TemporaryDirectory(prefix="mosaic-rke-review-progress-") as tmp_dir:
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
    )


def _source_license_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = SOURCE_LICENSE_REVIEWED_POLICY_PATH
    target_rows = build_manual_review_batch_status(root_path)[0].source_license.pending_rows
    resolved_input = _resolve(root_path, input_path)
    prepare_command = "mosaic-rke prepare-license-policy-review --root ."
    dry_run_command = (
        "mosaic-rke build-license-review-import --root . "
        f"--policy {input_path} --output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        f"mosaic-rke apply-license-review --root . --input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
    )
    apply_command = (
        "mosaic-rke build-license-review-import --root . "
        f"--policy {input_path} --output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        f"mosaic-rke apply-license-review --root . --input {DEFAULT_LICENSE_POLICY_IMPORT_PATH}"
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
    with tempfile.TemporaryDirectory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        temp_output = temp_root / DEFAULT_LICENSE_POLICY_IMPORT_PATH
        policy_report = build_source_license_policy_import(
            temp_root,
            resolved_input,
            output_path=temp_output,
            dry_run=False,
        )
        apply_report = None
        if policy_report.accepted:
            apply_report = apply_source_license_review_import(temp_root, temp_output)
        summary = summarize_source_license_review(temp_root)
    apply_blockers = apply_report.blockers if apply_report is not None else ()
    blockers = _dedupe((*policy_report.blockers, *apply_blockers, *summary.blockers))
    return ManualReviewGateProgress(
        review_kind="source_license",
        input_path=input_path,
        input_exists=True,
        target_rows=target_rows,
        input_rows=input_rows,
        complete_rows=summary.reviewed_sources,
        pending_rows=summary.pending_sources,
        simulation_accepted=policy_report.accepted and (apply_report is not None and apply_report.accepted),
        ready_for_promotion=policy_report.accepted and (apply_report is not None and apply_report.accepted) and summary.passed,
        blockers=blockers,
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
    )


def _lockbox_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = LOCKBOX_REVIEWED_IMPORT_PATH
    resolved_input = _resolve(root_path, input_path)
    prepare_command = "mosaic-rke prepare-lockbox-review --root ."
    dry_run_command = f"mosaic-rke apply-lockbox-review --root . --input {input_path} --dry-run"
    apply_command = f"mosaic-rke apply-lockbox-review --root . --input {input_path}"
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="lockbox",
            input_path=input_path,
            target_rows=1,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
        )

    input_rows = _json_object_exists(resolved_input)
    with tempfile.TemporaryDirectory(prefix="mosaic-rke-review-progress-") as tmp_dir:
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
    )


def build_manual_review_progress(root: str | Path = ".") -> ManualReviewProgressReport:
    root_path = Path(root)
    gates = (
        _gold_progress(root_path),
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
