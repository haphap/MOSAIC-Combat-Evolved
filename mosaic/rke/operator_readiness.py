"""Integrity checks for the manual-review operator handoff bundle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manual_review_batches import (
    GOLD_BATCH_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_IMPORT_TEMPLATE_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    build_manual_review_batch_status,
)
from .manual_review_bundle_manifest import (
    MANUAL_REVIEW_BUNDLE_ARTIFACTS,
    MANUAL_REVIEW_BUNDLE_MANIFEST_PATH,
    write_manual_review_bundle_manifest,
)
from .manual_review_import import (
    GOLD_REVIEW_IMPORT_REPORT_PATH,
    TARGET_ROW_HASH_FIELD,
    apply_gold_set_review_import,
    manual_review_forbidden_field_paths,
)
from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    LICENSE_POLICY_IMPORT_REPORT_PATH,
    MATCHED_ROWS_FINGERPRINT_FIELD,
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    build_source_license_policy_import,
    build_source_license_policy_template,
)
from .lockbox_review_import import (
    LOCKBOX_REVIEW_CONTEXT_HASH_FIELD,
    LOCKBOX_REVIEW_IMPORT_REPORT_PATH,
    apply_lockbox_review_import,
)
from .operator_handoff import (
    LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    OPERATOR_HANDOFF_JSON_PATH,
    OPERATOR_HANDOFF_MD_PATH,
    build_lockbox_review_import_template,
    build_operator_handoff,
    write_operator_handoff,
)
from .promotion_dry_run import PROMOTION_DRY_RUN_REPORT_PATH, write_promotion_dry_run_report
from .promotion_gate import build_production_promotion_gate_report
from .registry_manifest import validate_required_registry, validate_required_registry_content


OPERATOR_READINESS_REPORT_PATH = "registry/handoffs/rke_operator_readiness_report.json"


@dataclass(frozen=True)
class OperatorReadinessCheck:
    check_id: str
    passed: bool
    evidence: str
    blocker: str


@dataclass(frozen=True)
class OperatorReadinessReport:
    report_id: str
    accepted: bool
    check_count: int
    passed_count: int
    failure_count: int
    checks: Sequence[OperatorReadinessCheck]
    generated_paths: Sequence[str]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_mapping_json(root_path: Path, relative_path: str) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    path = root_path / relative_path
    if not path.exists():
        return {}, (f"{relative_path} missing",)
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return {}, (f"{relative_path} must contain valid JSON: {exc.msg}",)
    if not isinstance(payload, Mapping):
        return {}, (f"{relative_path} must be object",)
    return payload, ()


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _check(check_id: str, passed: bool, evidence: str, blocker: str = "") -> OperatorReadinessCheck:
    return OperatorReadinessCheck(
        check_id=check_id,
        passed=passed,
        evidence=evidence,
        blocker="" if passed else blocker,
    )


def _load_jsonl_template_rows(root_path: Path, relative_path: str) -> tuple[list[tuple[int, Any]], tuple[str, ...]]:
    path = root_path / relative_path
    if not path.exists():
        return [], ()
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
                errors.append(f"{relative_path} row {line_number} must contain valid JSON: {exc.msg}")
    return rows, tuple(errors)


def _template_row_count(root_path: Path, relative_path: str) -> tuple[int, tuple[str, ...]]:
    rows, errors = _load_jsonl_template_rows(root_path, relative_path)
    return len(rows) + len(errors), errors


def _jsonl_row_object_failure(relative_path: str, index: int) -> tuple[str, str]:
    return (
        f"{relative_path} row {index} must be object",
        "manual import template row must be object",
    )


def _import_templates_are_sparse(root_path: Path) -> tuple[bool, str, str]:
    jsonl_templates = (
        GOLD_BATCH_IMPORT_TEMPLATE_PATH,
        GOLD_FULL_IMPORT_TEMPLATE_PATH,
        LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    )
    for relative_path in jsonl_templates:
        path = root_path / relative_path
        if not path.exists():
            return False, f"{relative_path} missing", f"{relative_path} missing"
        rows, row_errors = _load_jsonl_template_rows(root_path, relative_path)
        if row_errors:
            return False, row_errors[0], row_errors[0]
        for index, row in rows:
            if not isinstance(row, Mapping):
                return (False, *_jsonl_row_object_failure(relative_path, index))
            leaked = manual_review_forbidden_field_paths(row)
            if leaked:
                return (
                    False,
                    f"{relative_path} row {index} has forbidden fields {leaked}",
                    "manual import template includes long source-text field",
                )
            if relative_path in {GOLD_BATCH_IMPORT_TEMPLATE_PATH, GOLD_FULL_IMPORT_TEMPLATE_PATH}:
                preview = str(row.get("proposed_claim_text") or "")
                if len(preview) > 72:
                    return (
                        False,
                        f"{relative_path} row {index} proposed_claim_text length={len(preview)}",
                        "gold-set import preview is not truncated",
                    )

    json_templates = (
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    )
    for relative_path in json_templates:
        row, errors = _read_mapping_json(root_path, relative_path)
        if errors:
            return False, errors[0], errors[0]
        leaked = manual_review_forbidden_field_paths(row)
        if leaked:
            return (
                False,
                f"{relative_path} has forbidden fields {leaked}",
                "manual import template includes long source-text field",
            )

    return True, "manual import templates omit long source text", ""


def _manual_review_templates_have_provenance(root_path: Path) -> tuple[bool, str, str]:
    jsonl_requirements = {
        GOLD_BATCH_IMPORT_TEMPLATE_PATH: ("target_review_path", "review_context_ref", TARGET_ROW_HASH_FIELD),
        GOLD_FULL_IMPORT_TEMPLATE_PATH: ("target_review_path", "review_context_ref", TARGET_ROW_HASH_FIELD),
        LICENSE_BATCH_IMPORT_TEMPLATE_PATH: (
            "target_review_path",
            "review_context_ref",
            TARGET_ROW_HASH_FIELD,
        ),
    }
    for relative_path, required_fields in jsonl_requirements.items():
        path = root_path / relative_path
        if not path.exists():
            return False, f"{relative_path} missing", f"{relative_path} missing"
        rows, row_errors = _load_jsonl_template_rows(root_path, relative_path)
        if row_errors:
            return False, row_errors[0], row_errors[0]
        if not rows:
            return False, f"{relative_path} has 0 rows", "manual import template has no provenance rows"
        for line_number, row in rows:
            if not isinstance(row, Mapping):
                return (False, *_jsonl_row_object_failure(relative_path, line_number))
            missing = [field for field in required_fields if not str(row.get(field) or "").strip()]
            if missing:
                return (
                    False,
                    f"{relative_path} row {line_number} missing provenance fields {missing}",
                    "manual import template is missing provenance or row fingerprint fields",
                )

    json_requirements = {
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH: (
            "target_review_path",
            "review_context_ref",
            MATCHED_ROWS_FINGERPRINT_FIELD,
        ),
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH: (
            "target_review_path",
            "review_context_ref",
            TARGET_ROW_HASH_FIELD,
            LOCKBOX_REVIEW_CONTEXT_HASH_FIELD,
        ),
    }
    for relative_path, required_fields in json_requirements.items():
        row, errors = _read_mapping_json(root_path, relative_path)
        if errors:
            return False, errors[0], errors[0]
        missing = [field for field in required_fields if not str(row.get(field) or "").strip()]
        if missing:
            return (
                False,
                f"{relative_path} missing provenance fields {missing}",
                "manual review policy or lockbox template is missing provenance fingerprints",
            )

    return True, "manual import templates include target paths and fingerprints", ""


def build_operator_readiness_report(root: str | Path = ".") -> OperatorReadinessReport:
    root_path = Path(root)
    checks: list[OperatorReadinessCheck] = []

    missing, empty = validate_required_registry(root_path)
    invalid = validate_required_registry_content(root_path)
    self_generated_paths = {
        OPERATOR_READINESS_REPORT_PATH,
        GOLD_REVIEW_IMPORT_REPORT_PATH,
        LOCKBOX_REVIEW_IMPORT_REPORT_PATH,
        LICENSE_POLICY_IMPORT_REPORT_PATH,
        MANUAL_REVIEW_BUNDLE_MANIFEST_PATH,
        PROMOTION_DRY_RUN_REPORT_PATH,
    }
    missing = tuple(path for path in missing if path not in self_generated_paths)
    empty = tuple(path for path in empty if path not in self_generated_paths)
    checks.append(
        _check(
            "required_registry_valid",
            not missing and not empty and not invalid,
            f"missing={len(missing)}, empty={len(empty)}, invalid={len(invalid)}",
            "; ".join((*missing, *empty, *invalid)) or "required registry artifacts are missing, empty, or malformed",
        )
    )

    handoff = build_operator_handoff(root_path)
    gate_kinds = {gate.review_kind for gate in handoff.gates}
    checks.append(
        _check(
            "handoff_ready_for_operator",
            handoff.ready_for_operator_review
            and gate_kinds == {"gold_set", "source_license", "lockbox"}
            and handoff.direct_production_forbidden
            and not handoff.production_allowed,
            f"gates={sorted(gate_kinds)}, next_state={handoff.next_state}",
            "operator handoff does not expose all manual gates safely",
        )
    )

    batch_status, _, _ = build_manual_review_batch_status(root_path)
    gold_rows, gold_row_errors = _template_row_count(root_path, GOLD_BATCH_IMPORT_TEMPLATE_PATH)
    gold_full_rows, gold_full_row_errors = _template_row_count(root_path, GOLD_FULL_IMPORT_TEMPLATE_PATH)
    license_rows, license_row_errors = _template_row_count(root_path, LICENSE_BATCH_IMPORT_TEMPLATE_PATH)
    batch_shape_blockers = (
        *(blocker for blocker in batch_status.blockers if "still pending" not in blocker),
        *gold_row_errors,
        *gold_full_row_errors,
        *license_row_errors,
    )
    batch_blocker = "; ".join(batch_shape_blockers)
    checks.append(
        _check(
            "manual_batch_templates_match_status",
            batch_status.ready_for_manual_review
            and gold_rows == batch_status.gold_set.exported_rows
            and gold_full_rows == batch_status.gold_set.pending_rows
            and license_rows == batch_status.source_license.exported_rows
            and batch_status.gold_set.exported_rows > 0
            and batch_status.source_license.exported_rows > 0,
            (
                f"gold_exported={batch_status.gold_set.exported_rows}/{gold_rows}, "
                f"gold_full={batch_status.gold_set.pending_rows}/{gold_full_rows}, "
                f"license_exported={batch_status.source_license.exported_rows}/{license_rows}, "
                f"batch_blockers={len(batch_shape_blockers)}"
            ),
            batch_blocker or "manual batch templates do not match batch status",
        )
    )

    sparse_ok, sparse_evidence, sparse_blocker = _import_templates_are_sparse(root_path)
    checks.append(_check("manual_import_templates_are_sparse", sparse_ok, sparse_evidence, sparse_blocker))

    provenance_ok, provenance_evidence, provenance_blocker = _manual_review_templates_have_provenance(root_path)
    checks.append(
        _check(
            "manual_import_templates_have_provenance",
            provenance_ok,
            provenance_evidence,
            provenance_blocker,
        )
    )

    blank_gold_full = apply_gold_set_review_import(
        root_path,
        GOLD_FULL_IMPORT_TEMPLATE_PATH,
        dry_run=True,
    )
    checks.append(
        _check(
            "blank_full_gold_set_import_is_rejected",
            not blank_gold_full.accepted
            and blank_gold_full.dry_run
            and blank_gold_full.input_rows == batch_status.gold_set.pending_rows
            and blank_gold_full.applied_rows == 0
            and blank_gold_full.rejected_rows == batch_status.gold_set.pending_rows
            and f"{batch_status.gold_set.pending_rows} review rows failed validation"
            in set(blank_gold_full.blockers),
            (
                f"accepted={blank_gold_full.accepted}, "
                f"input_rows={blank_gold_full.input_rows}, "
                f"applied_rows={blank_gold_full.applied_rows}, "
                f"rejected_rows={blank_gold_full.rejected_rows}"
            ),
            "blank full gold-set import unexpectedly passes",
        )
    )

    lockbox_template, lockbox_template_errors = _read_mapping_json(
        root_path,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    )
    expected_lockbox: Mapping[str, Any] = {}
    expected_lockbox_error = ""
    try:
        expected_lockbox = build_lockbox_review_import_template(root_path)
    except ValueError as exc:
        expected_lockbox_error = str(exc)
    checks.append(
        _check(
            "lockbox_template_requires_human_decision",
            bool(lockbox_template)
            and not lockbox_template_errors
            and not expected_lockbox_error
            and lockbox_template == expected_lockbox
            and lockbox_template.get("result") == ""
            and lockbox_template.get("open_count") is None,
            (
                f"lockbox_template_path={LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH}"
                + (
                    f", template_error={'; '.join(lockbox_template_errors)}"
                    if lockbox_template_errors
                    else ""
                )
                + (f", expected_error={expected_lockbox_error}" if expected_lockbox_error else "")
            ),
            "; ".join(lockbox_template_errors)
            or expected_lockbox_error
            or "lockbox import template is missing or already filled",
        )
    )

    blank_lockbox = apply_lockbox_review_import(
        root_path,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        dry_run=True,
    )
    expected_lockbox_rejections = {
        "opened_at required",
        "opened_by required",
        "open_count required",
        "result required",
        "result must be one of not_opened, passed, failed",
        "open_count must be integer",
    }
    checks.append(
        _check(
            "blank_lockbox_import_is_rejected",
            not blank_lockbox.accepted
            and blank_lockbox.dry_run
            and not blank_lockbox.applied
            and not blank_lockbox.production_allowed
            and blank_lockbox.next_state == "paper_trading"
            and expected_lockbox_rejections <= set(blank_lockbox.rejected_reasons),
            (
                f"accepted={blank_lockbox.accepted}, "
                f"applied={blank_lockbox.applied}, "
                f"next_state={blank_lockbox.next_state}, "
                f"rejections={len(blank_lockbox.rejected_reasons)}"
            ),
            "blank lockbox import unexpectedly passes",
        )
    )

    policy_template, policy_template_errors = _read_mapping_json(
        root_path,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    )
    expected_policy = build_source_license_policy_template(root_path)
    checks.append(
        _check(
            "source_license_policy_template_requires_human_decision",
            bool(policy_template)
            and not policy_template_errors
            and policy_template == expected_policy
            and policy_template.get("approved_for_derived_claim_storage") is None
            and policy_template.get("approved_for_production_runtime") is None
            and not str(policy_template.get("reviewer") or "").strip()
            and int(policy_template.get("matched_row_count") or 0)
            == batch_status.source_license.pending_rows,
            (
                f"policy_template_path={SOURCE_LICENSE_POLICY_TEMPLATE_PATH}"
                + (
                    f", template_error={'; '.join(policy_template_errors)}"
                    if policy_template_errors
                    else ""
                )
            ),
            "; ".join(policy_template_errors)
            or "source-license policy template is missing, scoped incorrectly, or already filled",
        )
    )

    policy_dry_run = build_source_license_policy_import(
        root_path,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        output_path=DEFAULT_LICENSE_POLICY_IMPORT_PATH,
        dry_run=True,
    )
    policy_blockers = set(policy_dry_run.blockers)
    expected_policy_blockers = {
        "reviewer required",
        "review_date required",
        "approved_for_derived_claim_storage must be boolean",
        "approved_for_production_runtime must be boolean",
    }
    checks.append(
        _check(
            "blank_source_license_policy_import_is_rejected",
            not policy_dry_run.accepted
            and policy_dry_run.output_rows == 0
            and expected_policy_blockers <= policy_blockers,
            (
                f"accepted={policy_dry_run.accepted}, "
                f"matched_rows={policy_dry_run.matched_rows}, "
                f"output_rows={policy_dry_run.output_rows}, "
                f"blockers={len(policy_dry_run.blockers)}"
            ),
            "blank source-license policy unexpectedly expands into import rows",
        )
    )

    write_promotion_dry_run_report(
        root_path,
        gold_input=GOLD_FULL_IMPORT_TEMPLATE_PATH,
        license_input=LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        lockbox_input=LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    )
    blank_dry_run = _read_json(root_path / PROMOTION_DRY_RUN_REPORT_PATH)
    checks.append(
        _check(
            "blank_bundle_dry_run_does_not_promote",
            blank_dry_run.get("mutated_original_registry") is False
            and blank_dry_run.get("accepted") is False
            and blank_dry_run.get("production_allowed_after_simulation") is False,
            (
                f"accepted={blank_dry_run.get('accepted')}, "
                f"after_next_state={blank_dry_run.get('after_next_state')}, "
                f"path={PROMOTION_DRY_RUN_REPORT_PATH}"
            ),
            "blank manual templates unexpectedly pass promotion dry-run",
        )
    )

    bundle_result = write_manual_review_bundle_manifest(root_path)
    bundle_manifest = _read_json(root_path / MANUAL_REVIEW_BUNDLE_MANIFEST_PATH)
    bundle_paths = {
        str(artifact.get("path") or "")
        for artifact in bundle_manifest.get("artifacts", ())
        if artifact.get("exists") is True
    }
    expected_bundle_paths = {path for _, path, _ in MANUAL_REVIEW_BUNDLE_ARTIFACTS}
    bundle_dry_run = (
        bundle_manifest.get("promotion_dry_run")
        if isinstance(bundle_manifest.get("promotion_dry_run"), Mapping)
        else {}
    )
    checks.append(
        _check(
            "manual_review_bundle_manifest_current",
            bundle_result["accepted"] is True
            and int(bundle_manifest.get("artifact_count") or 0) == len(MANUAL_REVIEW_BUNDLE_ARTIFACTS)
            and expected_bundle_paths <= bundle_paths
            and bundle_dry_run.get("accepted") is False
            and bundle_dry_run.get("production_allowed_after_simulation") is False
            and all(str(artifact.get("sha256") or "").startswith("sha256:") for artifact in bundle_manifest["artifacts"]),
            (
                f"artifact_count={bundle_manifest.get('artifact_count')}, "
                f"blockers={len(bundle_manifest.get('blockers') or [])}, "
                f"dry_run_accepted={bundle_dry_run.get('accepted')}"
            ),
            "manual review bundle manifest is missing, stale, or incomplete",
        )
    )

    promotion = build_production_promotion_gate_report(root_path)
    checks.append(
        _check(
            "promotion_gate_still_blocks_production",
            promotion.paper_trading_allowed
            and not promotion.production_allowed
            and promotion.direct_production_forbidden,
            f"next_state={promotion.next_state}, blockers={len(promotion.blockers)}",
            "promotion gate no longer blocks direct production",
        )
    )

    redaction, redaction_errors = _read_mapping_json(
        root_path,
        "registry/compliance/source_text_redaction_report.json",
    )
    checks.append(
        _check(
            "source_text_redaction_clean",
            not redaction_errors
            and redaction.get("accepted") is True
            and int(redaction.get("failure_count") or 0) == 0,
            (
                f"failure_count={redaction.get('failure_count')}"
                + (f", artifact_error={'; '.join(redaction_errors)}" if redaction_errors else "")
            ),
            "; ".join(redaction_errors) or "source-text redaction audit is not clean",
        )
    )

    passed_count = sum(check.passed for check in checks)
    generated_paths = (
        OPERATOR_HANDOFF_JSON_PATH,
        OPERATOR_HANDOFF_MD_PATH,
        OPERATOR_READINESS_REPORT_PATH,
        GOLD_BATCH_IMPORT_TEMPLATE_PATH,
        GOLD_FULL_IMPORT_TEMPLATE_PATH,
        GOLD_REVIEW_WORKBOOK_MD_PATH,
        GOLD_REVIEW_IMPORT_REPORT_PATH,
        LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        LICENSE_POLICY_IMPORT_REPORT_PATH,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        LOCKBOX_REVIEW_IMPORT_REPORT_PATH,
        PROMOTION_DRY_RUN_REPORT_PATH,
        MANUAL_REVIEW_BUNDLE_MANIFEST_PATH,
    )
    return OperatorReadinessReport(
        report_id="RKE-OPERATOR-READINESS-REPORT-20260606",
        accepted=passed_count == len(checks),
        check_count=len(checks),
        passed_count=passed_count,
        failure_count=len(checks) - passed_count,
        checks=tuple(checks),
        generated_paths=generated_paths,
    )


def write_operator_readiness_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    write_operator_handoff(root_path)
    report = build_operator_readiness_report(root_path)
    result = _write_json(root_path / OPERATOR_READINESS_REPORT_PATH, asdict(report))
    return {"path": str(result["path"]), "accepted": report.accepted}
