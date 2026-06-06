"""Operator handoff package for the remaining manual RKE gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    write_source_license_review_workbook,
    write_source_license_policy_template,
)
from .lockbox_review_import import (
    LOCKBOX_POLICY_PATH,
    LOCKBOX_REVIEW_CONTEXT_HASH_FIELD,
    LOCKBOX_REVIEW_PATH,
)
from .manual_review_import import TARGET_ROW_HASH_FIELD, review_row_fingerprint
from .manual_review_batches import (
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    build_manual_review_batch_status,
    write_manual_review_batches,
)
from .promotion_gate import (
    build_production_promotion_gate_report,
    write_production_promotion_gate_report,
)


OPERATOR_HANDOFF_JSON_PATH = "registry/handoffs/rke_operator_handoff.json"
OPERATOR_HANDOFF_MD_PATH = "registry/handoffs/rke_operator_handoff.md"
LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH = (
    "registry/review_batches/lockbox_review_next_import_template.json"
)
LOCKBOX_REVIEWED_IMPORT_PATH = "registry/review_batches/lockbox_reviewed.json"
MANUAL_REVIEW_PROGRESS_REPORT_PATH = "registry/review_batches/manual_review_progress_report.json"


@dataclass(frozen=True)
class OperatorGateHandoff:
    gate_id: str
    review_kind: str
    passed: bool
    blocker: str
    evidence_path: str
    evidence: str
    review_packet_path: str
    workbook_path: str
    import_template_path: str
    full_import_template_path: str
    policy_template_path: str
    reviewed_policy_path: str
    prepare_command: str
    pending_rows: int | None
    exported_rows: int | None
    required_manual_fields: Sequence[str]
    dry_run_command: str
    apply_command: str
    operator_note: str


@dataclass(frozen=True)
class OperatorHandoff:
    handoff_id: str
    production_allowed: bool
    staged_production_allowed: bool
    paper_trading_allowed: bool
    next_state: str
    direct_production_forbidden: bool
    ready_for_operator_review: bool
    remaining_blockers: Sequence[str]
    gates: Sequence[OperatorGateHandoff]
    generated_paths: Sequence[str]
    run_order: Sequence[str]
    promotion_dry_run_command: str


@dataclass(frozen=True)
class LockboxReviewStarterResult:
    path: str
    template_path: str
    force: bool
    written: bool
    overwritten: bool
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
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_mapping_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must contain valid JSON: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be object")
    return payload


def _criterion_by_id(criteria: Sequence[Any], criterion_id: str) -> Mapping[str, Any]:
    for criterion in criteria:
        row = (
            asdict(criterion)
            if hasattr(criterion, "__dataclass_fields__")
            else dict(criterion)
        )
        if row.get("criterion_id") == criterion_id:
            return row
    return {}


def build_lockbox_review_import_template(root: str | Path = ".") -> Mapping[str, Any]:
    root_path = Path(root)
    target = _read_mapping_json(root_path / LOCKBOX_REVIEW_PATH, "lockbox target")
    policy = _read_mapping_json(root_path / LOCKBOX_POLICY_PATH, "lockbox policy")
    return {
        "experiment_family_id": str(target.get("experiment_family_id") or ""),
        "experiment_id": str(target.get("experiment_id") or ""),
        "opened_at": "",
        "opened_by": "",
        "open_count": None,
        "result": "",
        "parameter_search_after_open": False,
        "rule_design_after_open": False,
        "notes": "",
        "review_context_ref": LOCKBOX_POLICY_PATH,
        LOCKBOX_REVIEW_CONTEXT_HASH_FIELD: review_row_fingerprint(policy),
        TARGET_ROW_HASH_FIELD: review_row_fingerprint(target),
        "target_review_path": LOCKBOX_REVIEW_PATH,
    }


def write_lockbox_review_import_template(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    return _write_json(
        root_path / LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        build_lockbox_review_import_template(root_path),
    )


def write_lockbox_review_starter(
    root: str | Path = ".",
    *,
    output_path: str | Path = LOCKBOX_REVIEWED_IMPORT_PATH,
    force: bool = False,
) -> LockboxReviewStarterResult:
    """Write a reviewer-editable lockbox JSON starter without clobbering reviews."""
    root_path = Path(root)
    resolved_output_path = Path(output_path)
    if not resolved_output_path.is_absolute():
        resolved_output_path = root_path / resolved_output_path
    template = build_lockbox_review_import_template(root_path)
    exists = resolved_output_path.exists()
    blockers: list[str] = []
    if exists and not force:
        blockers.append(f"{resolved_output_path} already exists; pass --force to overwrite")
    if not blockers:
        _write_json(resolved_output_path, template)
    return LockboxReviewStarterResult(
        path=str(resolved_output_path),
        template_path=LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        force=force,
        written=not blockers,
        overwritten=exists and force and not blockers,
        blockers=tuple(blockers),
    )


def _invalid_lockbox_review_import_template(reason: str) -> Mapping[str, Any]:
    return {
        "template_status": "invalid",
        "template_blocker": reason,
        "experiment_family_id": "",
        "experiment_id": "",
        "opened_at": "",
        "opened_by": "",
        "open_count": None,
        "result": "",
        "parameter_search_after_open": False,
        "rule_design_after_open": False,
        "notes": "",
        "review_context_ref": LOCKBOX_POLICY_PATH,
        LOCKBOX_REVIEW_CONTEXT_HASH_FIELD: "",
        TARGET_ROW_HASH_FIELD: "",
        "target_review_path": LOCKBOX_REVIEW_PATH,
    }


def _write_lockbox_review_import_template_or_error(root_path: Path) -> dict[str, Any]:
    try:
        return write_lockbox_review_import_template(root_path)
    except ValueError as exc:
        return _write_json(
            root_path / LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
            _invalid_lockbox_review_import_template(str(exc)),
        )


def build_operator_handoff(root: str | Path = ".") -> OperatorHandoff:
    root_path = Path(root)
    batch_status, _, _ = build_manual_review_batch_status(root_path)
    promotion = build_production_promotion_gate_report(root_path)
    criteria = tuple(promotion.criteria)
    pg02 = _criterion_by_id(criteria, "PG02")
    pg03 = _criterion_by_id(criteria, "PG03")
    pg09 = _criterion_by_id(criteria, "PG09")

    gold = batch_status.gold_set
    source_license = batch_status.source_license
    gates = (
        OperatorGateHandoff(
            gate_id="PG02",
            review_kind="gold_set",
            passed=bool(pg02.get("passed")),
            blocker=str(pg02.get("blocker") or ""),
            evidence_path=str(pg02.get("evidence_path") or ""),
            evidence=str(pg02.get("evidence") or ""),
            review_packet_path=gold.review_packet_path,
            workbook_path=GOLD_REVIEW_WORKBOOK_MD_PATH,
            import_template_path=gold.import_template_path,
            full_import_template_path=gold.full_import_template_path,
            policy_template_path="",
            reviewed_policy_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            prepare_command="mosaic-rke prepare-gold-review --root . --full",
            pending_rows=gold.pending_rows,
            exported_rows=gold.pending_rows,
            required_manual_fields=tuple(gold.required_manual_fields),
            dry_run_command=(
                "mosaic-rke apply-gold-review --root . "
                f"--input {GOLD_FULL_REVIEWED_IMPORT_PATH} --dry-run"
            ),
            apply_command=(
                "mosaic-rke apply-gold-review --root . "
                f"--input {GOLD_FULL_REVIEWED_IMPORT_PATH}"
            ),
            operator_note=(
                "Run prepare-gold-review --full, fill the reviewed scratch JSONL, "
                f"use {GOLD_REVIEW_WORKBOOK_MD_PATH} as the read-only claim checklist, "
                "then dry-run before applying the 500-claim gold set."
            ),
        ),
        OperatorGateHandoff(
            gate_id="PG03",
            review_kind="source_license",
            passed=bool(pg03.get("passed")),
            blocker=str(pg03.get("blocker") or ""),
            evidence_path=str(pg03.get("evidence_path") or ""),
            evidence=str(pg03.get("evidence") or ""),
            review_packet_path=source_license.review_packet_path,
            workbook_path=SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
            import_template_path=source_license.import_template_path,
            full_import_template_path=DEFAULT_LICENSE_POLICY_IMPORT_PATH,
            policy_template_path=SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
            pending_rows=source_license.pending_rows,
            exported_rows=source_license.exported_rows,
            required_manual_fields=tuple(source_license.required_manual_fields),
            dry_run_command=(
                "mosaic-rke build-license-review-import --root . "
                f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
                f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
                "mosaic-rke apply-license-review --root . "
                f"--input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
            ),
            apply_command=(
                "mosaic-rke apply-license-review --root . "
                f"--input {DEFAULT_LICENSE_POLICY_IMPORT_PATH}"
            ),
            operator_note=(
                "Compliance approval is required before production runtime retrieval. "
                f"Use {SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH} as the read-only "
                "source-class checklist. "
                f"Copy {SOURCE_LICENSE_POLICY_TEMPLATE_PATH} to "
                f"{SOURCE_LICENSE_REVIEWED_POLICY_PATH}, fill and sign the reviewed "
                "policy, then expand it instead of editing every source row manually."
            ),
            reviewed_policy_path=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
            prepare_command="mosaic-rke prepare-license-policy-review --root .",
        ),
        OperatorGateHandoff(
            gate_id="PG09",
            review_kind="lockbox",
            passed=bool(pg09.get("passed")),
            blocker=str(pg09.get("blocker") or ""),
            evidence_path=str(pg09.get("evidence_path") or ""),
            evidence=str(pg09.get("evidence") or ""),
            review_packet_path="registry/evaluation/lockbox/lockbox_policy.json",
            workbook_path="",
            import_template_path=LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
            full_import_template_path="",
            policy_template_path="",
            reviewed_policy_path=LOCKBOX_REVIEWED_IMPORT_PATH,
            prepare_command="mosaic-rke prepare-lockbox-review --root .",
            pending_rows=None,
            exported_rows=1,
            required_manual_fields=(
                "opened_at",
                "opened_by",
                "open_count",
                "result",
                "parameter_search_after_open",
                "rule_design_after_open",
                "notes",
            ),
            dry_run_command=(
                "mosaic-rke apply-lockbox-review --root . "
                f"--input {LOCKBOX_REVIEWED_IMPORT_PATH} --dry-run"
            ),
            apply_command=(
                "mosaic-rke apply-lockbox-review --root . "
                f"--input {LOCKBOX_REVIEWED_IMPORT_PATH}"
            ),
            operator_note=(
                "Run prepare-lockbox-review only after manual gold and license gates pass, "
                "fill the reviewed scratch JSON, then dry-run before applying the one-time lockbox review."
            ),
        ),
    )
    generated_paths = (
        gold.import_template_path,
        gold.full_import_template_path,
        GOLD_REVIEW_WORKBOOK_MD_PATH,
        source_license.import_template_path,
        SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        MANUAL_REVIEW_PROGRESS_REPORT_PATH,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        OPERATOR_HANDOFF_JSON_PATH,
        OPERATOR_HANDOFF_MD_PATH,
    )
    return OperatorHandoff(
        handoff_id="RKE-OPERATOR-HANDOFF-20260606",
        production_allowed=promotion.production_allowed,
        staged_production_allowed=promotion.staged_production_allowed,
        paper_trading_allowed=promotion.paper_trading_allowed,
        next_state=promotion.next_state,
        direct_production_forbidden=promotion.direct_production_forbidden,
        ready_for_operator_review=bool(batch_status.ready_for_manual_review),
        remaining_blockers=tuple(promotion.blockers),
        gates=gates,
        generated_paths=generated_paths,
        run_order=(
            "promotion-dry-run",
            "gold_set",
            "source_license",
            "promotion-status",
            "lockbox",
        ),
        promotion_dry_run_command=(
            "mosaic-rke build-license-review-import --root . "
            f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
            f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        ),
    )


def render_operator_handoff_markdown(handoff: OperatorHandoff) -> str:
    lines = [
        "# RKE Operator Handoff",
        "",
        f"- Next state: {handoff.next_state}",
        f"- Paper trading allowed: {str(handoff.paper_trading_allowed).lower()}",
        f"- Staged production allowed: {str(handoff.staged_production_allowed).lower()}",
        f"- Production allowed: {str(handoff.production_allowed).lower()}",
        f"- Direct production forbidden: {str(handoff.direct_production_forbidden).lower()}",
        "",
        "## Run Order",
        "",
    ]
    lines.extend(f"- {item}" for item in handoff.run_order)
    lines.extend(["", f"Dry-run command: `{handoff.promotion_dry_run_command}`", ""])
    lines.extend(["## Gates", ""])
    for gate in handoff.gates:
        lines.extend(
            [
                f"### {gate.gate_id} {gate.review_kind}",
                "",
                f"- Passed: {str(gate.passed).lower()}",
                f"- Blocker: {gate.blocker or 'none'}",
                f"- Evidence: {gate.evidence}",
                f"- Review packet: {gate.review_packet_path}",
                f"- Review workbook: {gate.workbook_path or 'none'}",
                f"- Import template: {gate.import_template_path}",
                f"- Full import template: {gate.full_import_template_path or 'none'}",
                f"- Policy template: {gate.policy_template_path or 'none'}",
                f"- Reviewed policy/input: {gate.reviewed_policy_path or 'none'}",
                f"- Prepare: `{gate.prepare_command}`" if gate.prepare_command else "- Prepare: none",
                f"- Pending rows: {gate.pending_rows}",
                f"- Exported rows: {gate.exported_rows}",
                f"- Dry run: `{gate.dry_run_command}`",
                f"- Apply: `{gate.apply_command}`",
                f"- Note: {gate.operator_note}",
                "",
            ]
        )
    if handoff.remaining_blockers:
        lines.extend(["## Remaining Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in handoff.remaining_blockers)
    return "\n".join(lines).rstrip()


def write_operator_handoff(root: str | Path = ".") -> dict[str, Any]:
    from .review_progress import write_manual_review_progress_report

    root_path = Path(root)
    review_batches = write_manual_review_batches(root_path)
    policy_template = write_source_license_policy_template(root_path)
    license_workbook = write_source_license_review_workbook(root_path)
    progress = write_manual_review_progress_report(root_path)
    lockbox_template = _write_lockbox_review_import_template_or_error(root_path)
    write_production_promotion_gate_report(root_path)
    handoff = build_operator_handoff(root_path)
    json_result = _write_json(root_path / OPERATOR_HANDOFF_JSON_PATH, asdict(handoff))
    md_path = root_path / OPERATOR_HANDOFF_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        render_operator_handoff_markdown(handoff) + "\n", encoding="utf-8"
    )
    return {
        "json": str(json_result["path"]),
        "markdown": str(md_path),
        "lockbox_import_template": str(lockbox_template["path"]),
        "gold_set_import_template": review_batches["gold_set_import_template"],
        "gold_set_full_import_template": review_batches[
            "gold_set_full_import_template"
        ],
        "gold_set_review_workbook": review_batches["gold_set_review_workbook"],
        "source_license_import_template": review_batches[
            "source_license_import_template"
        ],
        "source_license_review_workbook": str(license_workbook["path"]),
        "source_license_policy_template": str(policy_template["path"]),
        "manual_review_progress_report": str(progress["path"]),
    }
