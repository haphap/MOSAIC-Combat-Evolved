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
    GOLD_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_ASSIST_JSONL_PATH,
    GOLD_REVIEW_ASSIST_MD_PATH,
    GOLD_REVIEW_EVIDENCE_JSONL_PATH,
    GOLD_REVIEW_EVIDENCE_MD_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    build_manual_review_batch_status,
    write_manual_review_batches,
)
from .promotion_gate import (
    build_production_promotion_gate_report,
    write_production_promotion_gate_report,
)
from .report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
)
from .temp_paths import operator_command


OPERATOR_HANDOFF_JSON_PATH = "registry/handoffs/rke_operator_handoff.json"
OPERATOR_HANDOFF_MD_PATH = "registry/handoffs/rke_operator_handoff.md"
LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH = (
    "registry/review_batches/lockbox_review_next_import_template.json"
)
LOCKBOX_REVIEWED_IMPORT_PATH = "registry/review_batches/lockbox_reviewed.json"
MANUAL_REVIEW_PROGRESS_REPORT_PATH = "registry/review_batches/manual_review_progress_report.json"
MANUAL_REVIEW_RUNBOOK_MD_PATH = "registry/review_batches/manual_review_runbook.md"


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
class OperatorCommandStep:
    step_id: str
    phase: str
    action: str
    command: str
    manual_input_path: str
    expected_result: str


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
    command_sequence: Sequence[OperatorCommandStep]
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


def _footprint_review_gate(root_path: Path) -> OperatorGateHandoff:
    summary_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH
    summary: Mapping[str, Any] = {}
    if summary_path.exists():
        try:
            payload = _read_json(summary_path)
            if isinstance(payload, Mapping):
                summary = payload
        except json.JSONDecodeError:
            summary = {}
    passed = (
        summary.get("accepted") is True
        and summary.get("review_complete") is True
        and summary.get("quality_gate_passed") is True
    )
    blockers = [
        str(item)
        for item in (
            *(summary.get("blockers") or ()),
            *(summary.get("quality_gate_blockers") or ()),
        )
        if str(item).strip()
    ]
    return OperatorGateHandoff(
        gate_id="RI-FOOTPRINT-REVIEW",
        review_kind="footprint_review",
        passed=passed,
        blocker="; ".join(dict.fromkeys(blockers))
        or "analytical-footprint review still required",
        evidence_path=ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
        evidence=(
            f"{int(summary.get('complete_rows') or 0)} / "
            f"{int(summary.get('total_rows') or 0)} analytical footprints reviewed"
        ),
        review_packet_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        workbook_path=ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
        import_template_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        full_import_template_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        policy_template_path="",
        reviewed_policy_path=ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
        prepare_command=operator_command(
            "mosaic-rke prepare-footprint-review --root . "
            f"--output {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} --overwrite"
        ),
        pending_rows=int(summary.get("pending_rows") or 0),
        exported_rows=int(summary.get("total_rows") or 0),
        required_manual_fields=(
            "reviewer",
            "review_date",
            "review_notes",
            "footprint_correct",
            "source_span_supports_footprint",
            "metric_mapping_correct",
            "inferred_steps_tagged_correctly",
            "unknowns_used_when_uncertain",
            "no_proprietary_text_leakage",
        ),
        dry_run_command=operator_command(
            "mosaic-rke apply-footprint-review --root . "
            f"--input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} --dry-run"
        ),
        apply_command=operator_command(
            "mosaic-rke apply-footprint-review --root . "
            f"--input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH}"
        ),
        operator_note=(
            "Generate the private footprint review assist/workbook and evidence draft, "
            "fill the reviewed scratch JSONL, keep hashes intact, and dry-run before applying. "
            f"For batch work, prepare {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} "
            "with --limit/--offset, dry-run it, and apply accepted batches to accumulate progress."
        ),
    )


def _operator_command_sequence(
    gates: Sequence[OperatorGateHandoff],
    *,
    promotion_dry_run_command: str,
) -> tuple[OperatorCommandStep, ...]:
    gate_by_kind = {gate.review_kind: gate for gate in gates}
    gold = gate_by_kind["gold_set"]
    footprint = gate_by_kind["footprint_review"]
    source_license = gate_by_kind["source_license"]
    lockbox = gate_by_kind["lockbox"]
    steps: list[OperatorCommandStep] = [
        OperatorCommandStep(
            step_id="review-progress-preflight",
            phase="preflight",
            action="Inspect current manual-gate status.",
            command=operator_command("mosaic-rke review-progress --root ."),
            manual_input_path="",
            expected_result="Shows current blockers without applying reviewer decisions.",
        ),
        OperatorCommandStep(
            step_id="prepare-gold-review",
            phase="gold_set",
            action="Write the full gold-set import starter and workbook.",
            command=gold.prepare_command,
            manual_input_path="",
            expected_result=f"Reviewer scratch target is {GOLD_FULL_REVIEWED_IMPORT_PATH}.",
        ),
        OperatorCommandStep(
            step_id="write-gold-review-evidence",
            phase="gold_set",
            action="Write private gold-set evidence draft files.",
            command=operator_command(
                "mosaic-rke write-gold-review-evidence --root . --limit 50 --offset 0"
            ),
            manual_input_path="",
            expected_result=(
                f"Private evidence Markdown is {GOLD_REVIEW_EVIDENCE_MD_PATH} "
                f"and evidence JSONL is {GOLD_REVIEW_EVIDENCE_JSONL_PATH}."
            ),
        ),
        OperatorCommandStep(
            step_id="fill-gold-review",
            phase="gold_set",
            action="Fill the gold-set reviewed scratch file.",
            command="",
            manual_input_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            expected_result="All 500 claim rows have required manual fields and preserved provenance hashes.",
        ),
        OperatorCommandStep(
            step_id="dry-run-gold-review",
            phase="gold_set",
            action="Validate the reviewed gold-set scratch file.",
            command=gold.dry_run_command,
            manual_input_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            expected_result="Import is accepted and gold-set quality thresholds pass.",
        ),
        OperatorCommandStep(
            step_id="apply-gold-review",
            phase="gold_set",
            action="Apply accepted gold-set review decisions.",
            command=gold.apply_command,
            manual_input_path=GOLD_FULL_REVIEWED_IMPORT_PATH,
            expected_result="Gold-set summaries and downstream gates are recomputed.",
        ),
        OperatorCommandStep(
            step_id="prepare-footprint-review",
            phase="footprint_review",
            action="Write the analytical-footprint review starter.",
            command=footprint.prepare_command,
            manual_input_path="",
            expected_result=(
                f"Reviewer scratch target is {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH}."
            ),
        ),
        OperatorCommandStep(
            step_id="write-footprint-review-assist",
            phase="footprint_review",
            action="Write private analytical-footprint review assist files.",
            command=operator_command("mosaic-rke write-footprint-review-assist --root ."),
            manual_input_path="",
            expected_result=(
                f"Private workbook is {ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH} "
                f"and JSONL assist is {ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH}."
            ),
        ),
        OperatorCommandStep(
            step_id="write-footprint-review-evidence",
            phase="footprint_review",
            action="Write private analytical-footprint evidence draft files.",
            command=operator_command(
                "mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0"
            ),
            manual_input_path="",
            expected_result=(
                f"Private evidence Markdown is {ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH} "
                f"and evidence JSONL is {ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH}."
            ),
        ),
        OperatorCommandStep(
            step_id="fill-footprint-review",
            phase="footprint_review",
            action="Fill the analytical-footprint reviewed scratch file.",
            command="",
            manual_input_path=ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
            expected_result="All footprint rows have required manual fields and preserved provenance hashes.",
        ),
        OperatorCommandStep(
            step_id="dry-run-footprint-review",
            phase="footprint_review",
            action="Validate the reviewed analytical-footprint scratch file.",
            command=footprint.dry_run_command,
            manual_input_path=ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
            expected_result="Import is accepted and footprint quality thresholds pass.",
        ),
        OperatorCommandStep(
            step_id="apply-footprint-review",
            phase="footprint_review",
            action="Apply accepted analytical-footprint review decisions.",
            command=footprint.apply_command,
            manual_input_path=ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
            expected_result="Footprint summaries and downstream gates are recomputed.",
        ),
    ]
    if not source_license.passed:
        steps.extend(
            [
                OperatorCommandStep(
                    step_id="prepare-source-license-review",
                    phase="source_license",
                    action="Write the reviewed source-license policy starter and workbook.",
                    command=source_license.prepare_command,
                    manual_input_path="",
                    expected_result=f"Reviewed policy target is {SOURCE_LICENSE_REVIEWED_POLICY_PATH}.",
                ),
                OperatorCommandStep(
                    step_id="fill-source-license-policy",
                    phase="source_license",
                    action="Fill and sign the reviewed source-license policy.",
                    command="",
                    manual_input_path=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
                    expected_result="Policy fields, matched-row fingerprint, and production approval scope are complete.",
                ),
                OperatorCommandStep(
                    step_id="dry-run-source-license-review",
                    phase="source_license",
                    action="Build and validate the source-license import rows.",
                    command=source_license.dry_run_command,
                    manual_input_path=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
                    expected_result="Policy expands to all current source rows and dry-run import is accepted.",
                ),
                OperatorCommandStep(
                    step_id="apply-source-license-review",
                    phase="source_license",
                    action="Build and apply accepted source-license decisions.",
                    command=source_license.apply_command,
                    manual_input_path=SOURCE_LICENSE_REVIEWED_POLICY_PATH,
                    expected_result="Source-license summaries and production blockers are recomputed.",
                ),
            ]
        )
    steps.extend(
        [
            OperatorCommandStep(
            step_id="promotion-status-before-lockbox",
            phase="promotion",
            action="Confirm only the final lockbox gate remains before opening it.",
            command=operator_command("mosaic-rke promotion-status --root ."),
            manual_input_path="",
            expected_result="Gold-set, footprint, and source-license criteria pass; lockbox remains not opened.",
        ),
            OperatorCommandStep(
            step_id="prepare-lockbox-review",
            phase="lockbox",
            action="Write the one-time lockbox review starter.",
            command=lockbox.prepare_command,
            manual_input_path="",
            expected_result=f"Reviewer scratch target is {LOCKBOX_REVIEWED_IMPORT_PATH}.",
        ),
            OperatorCommandStep(
            step_id="fill-lockbox-review",
            phase="lockbox",
            action="Fill the one-time lockbox review scratch file.",
            command="",
            manual_input_path=LOCKBOX_REVIEWED_IMPORT_PATH,
            expected_result="Lockbox result, open count, post-open flags, and hashes are complete.",
        ),
            OperatorCommandStep(
            step_id="dry-run-lockbox-review",
            phase="lockbox",
            action="Validate the signed lockbox review.",
            command=lockbox.dry_run_command,
            manual_input_path=LOCKBOX_REVIEWED_IMPORT_PATH,
            expected_result="Lockbox import is accepted and production decision is eligible.",
        ),
            OperatorCommandStep(
            step_id="promotion-dry-run",
            phase="promotion",
            action="Simulate the complete reviewed bundle before final apply.",
            command=promotion_dry_run_command,
            manual_input_path="",
            expected_result="Simulation accepts all required reviewed inputs without mutating the original registry.",
        ),
            OperatorCommandStep(
            step_id="apply-lockbox-review",
            phase="lockbox",
            action="Apply the accepted one-time lockbox review.",
            command=lockbox.apply_command,
            manual_input_path=LOCKBOX_REVIEWED_IMPORT_PATH,
            expected_result="Lockbox review is recorded and downstream promotion gates are recomputed.",
        ),
            OperatorCommandStep(
            step_id="promotion-status-final",
            phase="promotion",
            action="Inspect final staged-promotion state.",
            command=operator_command("mosaic-rke promotion-status --root ."),
            manual_input_path="",
            expected_result="Promotion status reflects the applied manual reviews and lockbox decision.",
        ),
        ]
    )
    return tuple(steps)


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
            prepare_command=operator_command("mosaic-rke prepare-gold-review --root . --full"),
            pending_rows=gold.pending_rows,
            exported_rows=gold.pending_rows,
            required_manual_fields=tuple(gold.required_manual_fields),
            dry_run_command=operator_command(
                "mosaic-rke apply-gold-review --root . "
                f"--input {GOLD_FULL_REVIEWED_IMPORT_PATH} --dry-run"
            ),
            apply_command=operator_command(
                "mosaic-rke apply-gold-review --root . "
                f"--input {GOLD_FULL_REVIEWED_IMPORT_PATH}"
            ),
            operator_note=(
                "Run prepare-gold-review --full, fill the reviewed scratch JSONL, "
                f"use {GOLD_REVIEW_WORKBOOK_MD_PATH} as the read-only claim checklist, "
                f"and use {GOLD_REVIEW_ASSIST_MD_PATH} as non-import machine assistance, "
                f"use {GOLD_REVIEW_EVIDENCE_MD_PATH} as private source evidence draft, "
                "then dry-run before applying the 500-claim gold set. For batch work, "
                f"prepare {GOLD_REVIEWED_IMPORT_PATH} with --gold-batch-size/--offset, "
                "dry-run it, and apply accepted batches to accumulate progress."
            ),
        ),
        _footprint_review_gate(root_path),
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
            dry_run_command=operator_command(
                "mosaic-rke build-license-review-import --root . "
                f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
                f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
                "mosaic-rke apply-license-review --root . "
                f"--input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
            ),
            apply_command=operator_command(
                "mosaic-rke build-license-review-import --root . "
                f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
                f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
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
            prepare_command=operator_command(
                "mosaic-rke prepare-license-policy-review --root ."
            ),
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
            prepare_command=operator_command("mosaic-rke prepare-lockbox-review --root ."),
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
            dry_run_command=operator_command(
                "mosaic-rke apply-lockbox-review --root . "
                f"--input {LOCKBOX_REVIEWED_IMPORT_PATH} --dry-run"
            ),
            apply_command=operator_command(
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
        GOLD_REVIEW_ASSIST_JSONL_PATH,
        GOLD_REVIEW_ASSIST_MD_PATH,
        GOLD_REVIEW_EVIDENCE_JSONL_PATH,
        GOLD_REVIEW_EVIDENCE_MD_PATH,
        source_license.import_template_path,
        SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
        MANUAL_REVIEW_PROGRESS_REPORT_PATH,
        MANUAL_REVIEW_RUNBOOK_MD_PATH,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        OPERATOR_HANDOFF_JSON_PATH,
        OPERATOR_HANDOFF_MD_PATH,
    )
    source_license_gate = next(gate for gate in gates if gate.review_kind == "source_license")
    footprint_arg = f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH}"
    if source_license_gate.passed:
        promotion_dry_run_command = operator_command(
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"{footprint_arg} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        )
    else:
        promotion_dry_run_command = operator_command(
            "mosaic-rke build-license-review-import --root . "
            f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
            f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"{footprint_arg} "
            f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        )
    command_sequence = _operator_command_sequence(
        gates,
        promotion_dry_run_command=promotion_dry_run_command,
    )
    remaining_blockers = tuple(
        dict.fromkeys(
            blocker
            for blocker in (
                *promotion.blockers,
                *(gate.blocker for gate in gates if not gate.passed),
            )
            if str(blocker).strip()
        )
    )
    return OperatorHandoff(
        handoff_id="RKE-OPERATOR-HANDOFF-20260606",
        production_allowed=promotion.production_allowed,
        staged_production_allowed=promotion.staged_production_allowed,
        paper_trading_allowed=promotion.paper_trading_allowed,
        next_state=promotion.next_state,
        direct_production_forbidden=promotion.direct_production_forbidden,
        ready_for_operator_review=bool(batch_status.ready_for_manual_review),
        remaining_blockers=remaining_blockers,
        gates=gates,
        generated_paths=generated_paths,
        command_sequence=command_sequence,
        run_order=tuple(step.step_id for step in command_sequence),
        promotion_dry_run_command=promotion_dry_run_command,
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
        f"- Manual review runbook: {MANUAL_REVIEW_RUNBOOK_MD_PATH}",
        "",
        "## Run Order",
        "",
    ]
    lines.extend(f"- {item}" for item in handoff.run_order)
    lines.extend(["", f"Dry-run command: `{handoff.promotion_dry_run_command}`", ""])
    lines.extend(["## Command Sequence", ""])
    for step in handoff.command_sequence:
        command = f"`{step.command}`" if step.command else "manual"
        lines.extend(
            [
                f"### {step.step_id}",
                "",
                f"- Phase: {step.phase}",
                f"- Action: {step.action}",
                f"- Command: {command}",
                f"- Manual input: {step.manual_input_path or 'none'}",
                f"- Expected result: {step.expected_result}",
                "",
            ]
        )
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
    from .review_progress import write_manual_review_progress_report, write_manual_review_runbook

    root_path = Path(root)
    review_batches = write_manual_review_batches(root_path)
    policy_template = write_source_license_policy_template(root_path)
    license_workbook = write_source_license_review_workbook(root_path)
    progress = write_manual_review_progress_report(root_path)
    runbook = write_manual_review_runbook(root_path)
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
        "gold_set_review_assist_jsonl": review_batches[
            "gold_set_review_assist_jsonl"
        ],
        "gold_set_review_assist_markdown": review_batches[
            "gold_set_review_assist_markdown"
        ],
        "source_license_import_template": review_batches[
            "source_license_import_template"
        ],
        "source_license_review_workbook": str(license_workbook["path"]),
        "source_license_policy_template": str(policy_template["path"]),
        "manual_review_progress_report": str(progress["path"]),
        "manual_review_runbook": str(runbook["path"]),
    }
