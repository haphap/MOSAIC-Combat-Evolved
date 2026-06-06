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
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    build_source_license_policy_import,
)
from .lockbox_review_import import apply_lockbox_review_import
from .manual_review_batches import (
    GOLD_BATCH_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    build_manual_review_batch_status,
)
from .manual_review_import import (
    apply_gold_set_review_import,
)
from .operator_handoff import LOCKBOX_REVIEWED_IMPORT_PATH
from .review_gates import summarize_gold_set_review


MANUAL_REVIEW_PROGRESS_REPORT_ID = "RKE-MANUAL-REVIEW-PROGRESS-20260606"
MANUAL_REVIEW_PROGRESS_REPORT_PATH = "registry/review_batches/manual_review_progress_report.json"
MANUAL_REVIEW_RUNBOOK_MD_PATH = "registry/review_batches/manual_review_runbook.md"

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
    source_license = gate_lookup["source_license"]
    lockbox = gate_lookup["lockbox"]
    lines = [
        "# RKE Manual Review Runbook",
        "",
        "This artifact is a read-only operator checklist for the remaining manual RKE gates.",
        "It records paths, commands, row counts, and current blockers only.",
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
        "## Prepare Commands",
        "",
        f"- Gold-set: `{gold.prepare_command}`",
        f"- Source-license: `{source_license.prepare_command}`",
        f"- Lockbox: `{lockbox.prepare_command}`",
        "",
        "## Reviewer Inputs",
        "",
        f"- Gold-set reviewed scratch: `{GOLD_FULL_REVIEWED_IMPORT_PATH}`",
        f"- Source-license reviewed policy: `{SOURCE_LICENSE_REVIEWED_POLICY_PATH}`",
        f"- Lockbox reviewed scratch: `{LOCKBOX_REVIEWED_IMPORT_PATH}`",
        "",
        "Reviewed scratch files are operator-local decision files. Do not commit them unless the operator explicitly chooses to publish signed review decisions.",
        "",
        "## Read-Only Checklists",
        "",
        f"- Gold-set workbook: `{GOLD_REVIEW_WORKBOOK_MD_PATH}`",
        "- Gold-set packet JSON: `registry/gold_sets/tushare_research_reports.review_packet.json`",
        "- Gold-set packet Markdown: `registry/gold_sets/tushare_research_reports.review_packet.md`",
        f"- Source-license workbook: `{SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH}`",
        "- Source-license packet JSON: `registry/compliance/tushare_license_review_packet.json`",
        "- Source-license packet Markdown: `registry/compliance/tushare_license_review_packet.md`",
        f"- Source-license policy template: `{SOURCE_LICENSE_POLICY_TEMPLATE_PATH}`",
        "- Lockbox policy packet: `registry/evaluation/lockbox/lockbox_policy.json`",
        "",
        "These checklist files are not import files. Use them to inspect IDs, hashes, counts, and short previews only.",
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
        f"- Source-license: `{source_license.dry_run_command}`",
        f"- Lockbox: `{lockbox.dry_run_command}`",
        "",
        "## Apply Commands",
        "",
        f"- Gold-set: `{gold.apply_command}`",
        f"- Source-license: `{source_license.apply_command}`",
        f"- Lockbox: `{lockbox.apply_command}`",
        "",
        "## Promotion Dry Run",
        "",
        (
            "`mosaic-rke build-license-review-import --root . "
            f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
            f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}`"
        ),
        "",
        "## Current Blockers",
        "",
    ]
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
