"""Integrity checks for the manual-review operator handoff bundle."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manual_review_batches import (
    GOLD_BATCH_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_ASSIST_JSONL_PATH,
    GOLD_REVIEW_ASSIST_MD_PATH,
    GOLD_REVIEW_EVIDENCE_JSONL_PATH,
    GOLD_REVIEW_EVIDENCE_MD_PATH,
    GOLD_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    build_manual_review_batch_status,
    write_gold_review_assist,
)
from .manual_review_bundle_manifest import (
    MANUAL_REVIEW_BUNDLE_ARTIFACTS,
    MANUAL_REVIEW_BUNDLE_MANIFEST_PATH,
    build_manual_review_bundle_manifest,
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
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    build_source_license_policy_import,
    build_source_license_policy_template,
    write_source_license_review_workbook,
)
from .lockbox_review_import import (
    LOCKBOX_REVIEW_CONTEXT_HASH_FIELD,
    LOCKBOX_REVIEW_IMPORT_REPORT_PATH,
    apply_lockbox_review_import,
)
from .operator_handoff import (
    LOCKBOX_UPSTREAM_REVIEW_KINDS,
    LOCKBOX_REVIEW_CHECKLIST_MD_PATH,
    LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    LOCKBOX_REVIEWED_IMPORT_PATH,
    OPERATOR_HANDOFF_JSON_PATH,
    OPERATOR_HANDOFF_MD_PATH,
    build_lockbox_review_import_template,
    build_operator_handoff,
    lockbox_upstream_review_blockers,
    write_operator_handoff,
)
from .promotion_dry_run import (
    build_promotion_dry_run_report,
)
from .promotion_gate import build_production_promotion_gate_report
from .registry_manifest import validate_required_registry, validate_required_registry_content
from .report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
)
from .review_progress import (
    MANUAL_REVIEW_PROGRESS_REPORT_PATH,
    MANUAL_REVIEW_RUNBOOK_MD_PATH,
    build_manual_review_progress,
    write_manual_review_progress_report,
    write_manual_review_runbook,
)
from .temp_paths import rke_temporary_directory


OPERATOR_READINESS_REPORT_PATH = "registry/handoffs/rke_operator_readiness_report.json"
OPERATOR_READINESS_TEMP_COPY_IGNORED_PATHS = frozenset(
    {
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/processing_status.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
        "registry/sources/tushare_research_reports.gold_candidates.jsonl",
        "registry/sources/tushare_research_reports.jsonl",
        "registry/sources/tushare_research_reports.manifest.json",
    }
)
OPERATOR_READINESS_TEMP_COPY_IGNORED_PREFIXES = (
    "registry/report_intelligence/markdown/",
    "registry/report_intelligence/mineru/",
    "registry/report_intelligence/pdfs/",
)


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


def _operator_readiness_dry_run_root(
    root_path: Path,
    *,
    write_supporting_artifacts: bool,
) -> tuple[Path, Any | None]:
    if write_supporting_artifacts:
        return root_path, None
    temp_dir = rke_temporary_directory(prefix="mosaic-rke-operator-readiness-")
    temp_root = Path(temp_dir.name)
    shutil.copytree(
        root_path / "registry",
        temp_root / "registry",
        ignore=_operator_readiness_copy_ignore(root_path),
    )
    for directory_name in ("schemas", "docs"):
        source_path = root_path / directory_name
        if source_path.exists():
            shutil.copytree(source_path, temp_root / directory_name)
    return temp_root, temp_dir


def _operator_readiness_copy_ignore(root_path: Path):
    def ignore(directory: str, names: Sequence[str]) -> set[str]:
        ignored: set[str] = set()
        directory_path = Path(directory)
        for name in names:
            candidate = directory_path / name
            try:
                relative = candidate.relative_to(root_path).as_posix()
            except ValueError:
                continue
            if relative in OPERATOR_READINESS_TEMP_COPY_IGNORED_PATHS or any(
                relative == prefix.rstrip("/") or relative.startswith(prefix)
                for prefix in OPERATOR_READINESS_TEMP_COPY_IGNORED_PREFIXES
            ):
                ignored.add(name)
        return ignored

    return ignore


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


def _promotion_gate_state_consistency(
    promotion: Any,
) -> tuple[bool, str, str]:
    criteria = tuple(getattr(promotion, "criteria", ()) or ())
    passed_by_id = {
        str(getattr(criterion, "criterion_id", "") or ""): getattr(criterion, "passed", None) is True
        for criterion in criteria
    }
    missing = sorted({f"PG{index:02d}" for index in range(1, 11)} - set(passed_by_id))
    staged_expected = all(passed_by_id.get(f"PG{index:02d}") is True for index in range(1, 9))
    production_expected = staged_expected and all(
        passed_by_id.get(f"PG{index:02d}") is True for index in range(9, 11)
    )
    direct_forbidden_expected = not production_expected
    if production_expected:
        next_state_expected = "production"
    elif staged_expected:
        next_state_expected = "staged_production"
    elif getattr(promotion, "paper_trading_allowed", None) is True:
        next_state_expected = "paper_trading"
    else:
        next_state_expected = "candidate"

    blockers = tuple(getattr(promotion, "blockers", ()) or ())
    consistent = (
        not missing
        and getattr(promotion, "staged_production_allowed", None) is staged_expected
        and getattr(promotion, "production_allowed", None) is production_expected
        and getattr(promotion, "direct_production_forbidden", None) is direct_forbidden_expected
        and getattr(promotion, "next_state", None) == next_state_expected
        and (not production_expected or not blockers)
    )
    evidence = (
        f"next_state={getattr(promotion, 'next_state', None)}, "
        f"expected_next_state={next_state_expected}, "
        f"staged={getattr(promotion, 'staged_production_allowed', None)}/{staged_expected}, "
        f"production={getattr(promotion, 'production_allowed', None)}/{production_expected}, "
        f"direct_forbidden={getattr(promotion, 'direct_production_forbidden', None)}/{direct_forbidden_expected}, "
        f"blockers={len(blockers)}, missing={len(missing)}"
    )
    blocker = (
        "promotion gate state is inconsistent with PG01-PG10 criteria"
        if not missing
        else f"promotion gate missing criteria: {', '.join(missing)}"
    )
    return consistent, evidence, blocker


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


def _manual_review_templates_have_provenance(
    root_path: Path,
    *,
    allow_empty_jsonl: frozenset[str] = frozenset(),
) -> tuple[bool, str, str]:
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
        if not rows and relative_path in allow_empty_jsonl:
            continue
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


def _handoff_command_sequence_complete(handoff: Any) -> tuple[bool, str, str]:
    gates = tuple(getattr(handoff, "gates", ()) or ())
    source_license_gate = next(
        (
            gate
            for gate in gates
            if str(getattr(gate, "review_kind", "") or "") == "source_license"
        ),
        None,
    )
    source_license_already_passed = bool(
        getattr(source_license_gate, "passed", False)
    )
    source_license_steps = (
        ()
        if source_license_already_passed
        else (
            "prepare-source-license-review",
            "fill-source-license-policy",
            "dry-run-source-license-review",
            "apply-source-license-review",
        )
    )
    expected_steps = (
        "review-progress-preflight",
        "prepare-gold-review",
        "write-gold-review-evidence",
        "fill-gold-review",
        "dry-run-gold-review",
        "apply-gold-review",
        "prepare-footprint-review",
        "write-footprint-review-assist",
        "write-footprint-review-evidence",
        "fill-footprint-review",
        "dry-run-footprint-review",
        "apply-footprint-review",
        *source_license_steps,
        "promotion-status-before-lockbox",
        "prepare-lockbox-review",
        "fill-lockbox-review",
        "dry-run-lockbox-review",
        "promotion-dry-run",
        "apply-lockbox-review",
        "promotion-status-final",
    )
    sequence = tuple(getattr(handoff, "command_sequence", ()) or ())
    step_ids = tuple(str(getattr(step, "step_id", "") or "") for step in sequence)
    run_order = tuple(str(item) for item in getattr(handoff, "run_order", ()) or ())
    by_id = {str(getattr(step, "step_id", "") or ""): step for step in sequence}
    failures: list[str] = []
    if step_ids != expected_steps:
        failures.append("command_sequence step order is incomplete or out of order")
    if run_order != step_ids:
        failures.append("run_order must mirror command_sequence step_id order")

    preflight = by_id.get("review-progress-preflight")
    preflight_command = str(getattr(preflight, "command", "") or "")
    if (
        "review-progress --root . --actions-only --no-write"
        not in preflight_command
    ):
        failures.append("review-progress preflight must use the action queue")
    for step_id in ("promotion-status-before-lockbox", "promotion-status-final"):
        promotion_status_step = by_id.get(step_id)
        promotion_status_command = str(
            getattr(promotion_status_step, "command", "") or ""
        )
        if "promotion-status --root . --no-write" not in promotion_status_command:
            failures.append(f"{step_id} must use promotion-status --no-write")

    fill_expectations = {
        "fill-gold-review": "registry/review_batches/gold_set_full_reviewed.jsonl",
        "fill-footprint-review": (
            "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
        ),
        "fill-lockbox-review": "registry/review_batches/lockbox_reviewed.json",
    }
    if not source_license_already_passed:
        fill_expectations[
            "fill-source-license-policy"
        ] = "registry/review_batches/source_license_policy_reviewed.json"
    for step_id, expected_input in fill_expectations.items():
        step = by_id.get(step_id)
        if step is None:
            failures.append(f"{step_id} missing")
            continue
        if str(getattr(step, "command", "") or ""):
            failures.append(f"{step_id} must be a manual step without command")
        if str(getattr(step, "manual_input_path", "") or "") != expected_input:
            failures.append(f"{step_id} manual input path mismatch")

    if not source_license_already_passed:
        source_apply = by_id.get("apply-source-license-review")
        source_apply_command = str(getattr(source_apply, "command", "") or "")
        if (
            "build-license-review-import" not in source_apply_command
            or "source_license_policy_reviewed.json" not in source_apply_command
            or "apply-license-review" not in source_apply_command
        ):
            failures.append(
                "source-license apply step must build the import before applying it"
            )

    promotion_dry_run = by_id.get("promotion-dry-run")
    promotion_dry_run_command = str(getattr(promotion_dry_run, "command", "") or "")
    if (
        "promotion-dry-run" not in promotion_dry_run_command
        or "gold_set_full_reviewed.jsonl" not in promotion_dry_run_command
        or "analytical_footprint_reviewed.jsonl" not in promotion_dry_run_command
        or "lockbox_reviewed.json" not in promotion_dry_run_command
    ):
        failures.append("promotion dry-run must use all required reviewed inputs")
    if (
        not source_license_already_passed
        and "source_license_policy_import.jsonl" not in promotion_dry_run_command
    ):
        failures.append("promotion dry-run must include source-license input")
    if (
        source_license_already_passed
        and "--license-input" in promotion_dry_run_command
    ):
        failures.append(
            "promotion dry-run must not rebuild source-license input after the gate already passed"
        )

    expected_before_promotion = (
        "dry-run-gold-review",
        "dry-run-footprint-review",
        "dry-run-lockbox-review",
    )
    if not source_license_already_passed:
        expected_before_promotion = (
            "dry-run-gold-review",
            "dry-run-footprint-review",
            "dry-run-source-license-review",
            "dry-run-lockbox-review",
        )
    if step_ids == expected_steps:
        promotion_index = step_ids.index("promotion-dry-run")
        for step_id in expected_before_promotion:
            if step_ids.index(step_id) > promotion_index:
                failures.append(f"{step_id} must run before promotion-dry-run")

    evidence = (
        f"steps={len(step_ids)}, first={step_ids[0] if step_ids else 'none'}, "
        f"last={step_ids[-1] if step_ids else 'none'}"
    )
    return not failures, evidence, "; ".join(failures)


def _markdown_heading_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    next_heading = text.find("\n## ", start + len(marker))
    return text[start:] if next_heading < 0 else text[start:next_heading]


def _manual_review_runbook_promotion_policy_consistent(
    root_path: Path,
    *,
    source_license_already_passed: bool,
) -> tuple[bool, str, str]:
    path = root_path / MANUAL_REVIEW_RUNBOOK_MD_PATH
    if not path.exists():
        return False, f"{MANUAL_REVIEW_RUNBOOK_MD_PATH} missing", "manual review runbook is missing"
    section = _markdown_heading_section(path.read_text(encoding="utf-8"), "Promotion Dry Run")
    if not section:
        return (
            False,
            "promotion_section=missing",
            "manual review runbook is missing Promotion Dry Run section",
        )

    required_fragments = (
        "mosaic-rke promotion-dry-run --root .",
        f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH}",
        f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH}",
        f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}",
    )
    missing_fragments = [fragment for fragment in required_fragments if fragment not in section]
    has_license_input = "--license-input" in section
    has_license_import = DEFAULT_LICENSE_POLICY_IMPORT_PATH in section
    has_license_builder = "build-license-review-import" in section
    failures = list(missing_fragments)
    if source_license_already_passed:
        if has_license_input or has_license_import or has_license_builder:
            failures.append("source-license input must be omitted after the gate already passed")
    elif not has_license_input or not has_license_import or not has_license_builder:
        failures.append("source-license input must be built and passed before the gate has passed")

    evidence = (
        f"source_license_already_passed={source_license_already_passed}, "
        f"license_input={has_license_input}, license_import={has_license_import}, "
        f"license_builder={has_license_builder}, missing_fragments={len(missing_fragments)}"
    )
    return (
        not failures,
        evidence,
        "; ".join(failures) or "manual review runbook promotion dry-run source-license policy drifted",
    )


def _manual_batch_promotion_inputs_separated(
    root_path: Path,
) -> tuple[bool, str, str]:
    progress, progress_errors = _read_mapping_json(
        root_path,
        MANUAL_REVIEW_PROGRESS_REPORT_PATH,
    )
    if progress_errors:
        return False, "; ".join(progress_errors), "; ".join(progress_errors)

    expected_paths = {
        "gold_set": {
            "batch": GOLD_REVIEWED_IMPORT_PATH,
            "promotion": "registry/review_batches/gold_set_full_reviewed.jsonl",
        },
        "footprint_review": {
            "batch": ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
            "promotion": ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
        },
    }
    failures: list[str] = []
    checked_batches = 0
    checked_gates = 0
    gates = progress.get("gates")
    if not isinstance(gates, Sequence) or isinstance(gates, str):
        return False, "gates=invalid", "manual review progress gates must be an array"
    for gate in gates:
        if not isinstance(gate, Mapping):
            failures.append("manual review progress gate must be object")
            continue
        review_kind = str(gate.get("review_kind") or "")
        paths = expected_paths.get(review_kind)
        if paths is None:
            continue
        checked_gates += 1
        promotion_input = paths["promotion"]
        for command_field in ("dry_run_command", "apply_command"):
            command = str(gate.get(command_field) or "")
            if f"--input {promotion_input}" not in command:
                failures.append(f"{review_kind}.{command_field} must use {promotion_input}")
        batch_plan = gate.get("batch_plan")
        if not isinstance(batch_plan, Sequence) or isinstance(batch_plan, str):
            failures.append(f"{review_kind}.batch_plan must be array")
            continue
        for batch in batch_plan:
            if not isinstance(batch, Mapping):
                failures.append(f"{review_kind}.batch_plan row must be object")
                continue
            checked_batches += 1
            batch_input = paths["batch"]
            if batch.get("batch_input_path") != batch_input:
                failures.append(f"{review_kind}.batch_input_path must be {batch_input}")
            if batch.get("promotion_input_path") != promotion_input:
                failures.append(
                    f"{review_kind}.promotion_input_path must be {promotion_input}"
                )
            commands = batch.get("commands")
            if not isinstance(commands, Mapping):
                failures.append(f"{review_kind}.batch.commands must be object")
                continue
            for command_name in ("dry_run", "apply"):
                command = str(commands.get(command_name) or "")
                if f"--input {batch_input}" not in command:
                    failures.append(
                        f"{review_kind}.batch.commands.{command_name} must use {batch_input}"
                    )
                if f"--input {promotion_input}" in command:
                    failures.append(
                        f"{review_kind}.batch.commands.{command_name} must not use {promotion_input}"
                    )
    evidence = f"gates={checked_gates}, batches={checked_batches}, failures={len(failures)}"
    return not failures and checked_gates == 2, evidence, "; ".join(failures)


def _lockbox_upstream_guard_consistent(root_path: Path) -> tuple[bool, str, str]:
    report = build_manual_review_progress(root_path)
    gate_by_kind = {gate.review_kind: gate for gate in report.gates}
    expected_blockers = tuple(
        f"{review_kind} gate must be ready before opening lockbox review"
        for review_kind in LOCKBOX_UPSTREAM_REVIEW_KINDS
        if not gate_by_kind.get(review_kind, None)
        or not gate_by_kind[review_kind].ready_for_promotion
    )
    actual_blockers = lockbox_upstream_review_blockers(root_path)
    ready_kinds = tuple(
        review_kind
        for review_kind in LOCKBOX_UPSTREAM_REVIEW_KINDS
        if gate_by_kind.get(review_kind, None)
        and gate_by_kind[review_kind].ready_for_promotion
    )
    pending_kinds = tuple(
        review_kind
        for review_kind in LOCKBOX_UPSTREAM_REVIEW_KINDS
        if review_kind not in ready_kinds
    )
    evidence = (
        "pending="
        + (",".join(pending_kinds) if pending_kinds else "none")
        + "; ready="
        + (",".join(ready_kinds) if ready_kinds else "none")
        + f"; blockers={len(actual_blockers)}"
    )
    return (
        actual_blockers == expected_blockers,
        evidence,
        "lockbox upstream CLI guard does not match manual gate readiness",
    )


def build_operator_readiness_report(
    root: str | Path = ".",
    *,
    write_supporting_artifacts: bool = True,
) -> OperatorReadinessReport:
    root_path = Path(root)
    if write_supporting_artifacts:
        if not (root_path / GOLD_REVIEW_ASSIST_JSONL_PATH).exists() or not (
            root_path / GOLD_REVIEW_ASSIST_MD_PATH
        ).exists():
            write_gold_review_assist(root_path)
        write_source_license_review_workbook(root_path)
        write_manual_review_progress_report(root_path)
        write_manual_review_runbook(root_path)
    dry_run_root, dry_run_temp = _operator_readiness_dry_run_root(
        root_path,
        write_supporting_artifacts=write_supporting_artifacts,
    )
    checks: list[OperatorReadinessCheck] = []

    missing, empty = validate_required_registry(root_path)
    invalid = validate_required_registry_content(root_path)
    self_generated_paths = {
        OPERATOR_READINESS_REPORT_PATH,
        GOLD_REVIEW_IMPORT_REPORT_PATH,
        LOCKBOX_REVIEW_IMPORT_REPORT_PATH,
        LICENSE_POLICY_IMPORT_REPORT_PATH,
        MANUAL_REVIEW_BUNDLE_MANIFEST_PATH,
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
            and gate_kinds
            == {"gold_set", "footprint_review", "source_license", "lockbox"}
            and handoff.direct_production_forbidden
            and not handoff.production_allowed,
            f"gates={sorted(gate_kinds)}, next_state={handoff.next_state}",
            "operator handoff does not expose all manual gates safely",
        )
    )
    sequence_ok, sequence_evidence, sequence_blocker = _handoff_command_sequence_complete(handoff)
    checks.append(
        _check(
            "handoff_command_sequence_complete",
            sequence_ok,
            sequence_evidence,
            sequence_blocker or "operator handoff command sequence is incomplete or unsafe",
        )
    )
    manual_progress = build_manual_review_progress(root_path)
    source_license_progress = next(
        (
            gate
            for gate in tuple(getattr(manual_progress, "gates", ()) or ())
            if gate.review_kind == "source_license"
        ),
        None,
    )
    runbook_ok, runbook_evidence, runbook_blocker = (
        _manual_review_runbook_promotion_policy_consistent(
            root_path,
            source_license_already_passed=bool(
                source_license_progress and source_license_progress.ready_for_promotion
            ),
        )
    )
    checks.append(
        _check(
            "manual_review_runbook_promotion_policy_consistent",
            runbook_ok,
            runbook_evidence,
            runbook_blocker,
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
            and (
                batch_status.gold_set.pending_rows == 0
                or batch_status.gold_set.exported_rows > 0
            )
            and (
                batch_status.source_license.pending_rows == 0
                or batch_status.source_license.exported_rows > 0
            ),
            (
                f"gold_exported={batch_status.gold_set.exported_rows}/{gold_rows}, "
                f"gold_full={batch_status.gold_set.pending_rows}/{gold_full_rows}, "
                f"license_exported={batch_status.source_license.exported_rows}/{license_rows}, "
                f"batch_blockers={len(batch_shape_blockers)}"
            ),
            batch_blocker or "manual batch templates do not match batch status",
        )
    )
    (
        batch_input_ok,
        batch_input_evidence,
        batch_input_blocker,
    ) = _manual_batch_promotion_inputs_separated(root_path)
    checks.append(
        _check(
            "manual_batch_promotion_inputs_separated",
            batch_input_ok,
            batch_input_evidence,
            batch_input_blocker
            or "manual review batch inputs and promotion inputs are not separated",
        )
    )

    sparse_ok, sparse_evidence, sparse_blocker = _import_templates_are_sparse(root_path)
    checks.append(_check("manual_import_templates_are_sparse", sparse_ok, sparse_evidence, sparse_blocker))

    empty_provenance_allowed = set()
    if batch_status.gold_set.pending_rows == 0:
        empty_provenance_allowed.update(
            {
                GOLD_BATCH_IMPORT_TEMPLATE_PATH,
                GOLD_FULL_IMPORT_TEMPLATE_PATH,
            }
        )
    if batch_status.source_license.pending_rows == 0:
        empty_provenance_allowed.add(LICENSE_BATCH_IMPORT_TEMPLATE_PATH)
    provenance_ok, provenance_evidence, provenance_blocker = (
        _manual_review_templates_have_provenance(
            root_path,
            allow_empty_jsonl=frozenset(empty_provenance_allowed),
        )
    )
    checks.append(
        _check(
            "manual_import_templates_have_provenance",
            provenance_ok,
            provenance_evidence,
            provenance_blocker,
        )
    )

    blank_gold_full = apply_gold_set_review_import(
        dry_run_root,
        GOLD_FULL_IMPORT_TEMPLATE_PATH,
        dry_run=True,
    )
    expected_blank_gold_blocker = (
        "manual review import file is empty"
        if batch_status.gold_set.pending_rows == 0
        else f"{batch_status.gold_set.pending_rows} review rows failed validation"
    )
    checks.append(
        _check(
            "blank_full_gold_set_import_is_rejected",
            not blank_gold_full.accepted
            and blank_gold_full.dry_run
            and blank_gold_full.input_rows == batch_status.gold_set.pending_rows
            and blank_gold_full.applied_rows == 0
            and blank_gold_full.rejected_rows == batch_status.gold_set.pending_rows
            and expected_blank_gold_blocker in set(blank_gold_full.blockers),
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
        dry_run_root,
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
    (
        lockbox_guard_ok,
        lockbox_guard_evidence,
        lockbox_guard_blocker,
    ) = _lockbox_upstream_guard_consistent(root_path)
    checks.append(
        _check(
            "lockbox_upstream_cli_guard_enforced",
            lockbox_guard_ok,
            lockbox_guard_evidence,
            lockbox_guard_blocker,
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
        dry_run_root,
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

    blank_dry_run = build_promotion_dry_run_report(
        dry_run_root,
        gold_input=GOLD_FULL_IMPORT_TEMPLATE_PATH,
        license_input=LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        lockbox_input=LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    )
    checks.append(
        _check(
            "blank_bundle_dry_run_does_not_promote",
            blank_dry_run.mutated_original_registry is False
            and blank_dry_run.accepted is False
            and blank_dry_run.production_allowed_after_simulation is False,
            (
                f"accepted={blank_dry_run.accepted}, "
                f"after_next_state={blank_dry_run.after_next_state}"
            ),
            "blank manual templates unexpectedly pass promotion dry-run",
        )
    )

    if write_supporting_artifacts:
        bundle_result = write_manual_review_bundle_manifest(root_path)
        bundle_manifest = _read_json(root_path / MANUAL_REVIEW_BUNDLE_MANIFEST_PATH)
    else:
        built_bundle_manifest = build_manual_review_bundle_manifest(root_path)
        bundle_result = {
            "accepted": built_bundle_manifest.accepted,
            "artifact_count": built_bundle_manifest.artifact_count,
        }
        bundle_manifest = _jsonable(asdict(built_bundle_manifest))
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
    promotion_ok, promotion_evidence, promotion_blocker = _promotion_gate_state_consistency(
        promotion
    )
    checks.append(
        _check(
            "promotion_gate_state_consistent",
            promotion_ok,
            promotion_evidence,
            promotion_blocker,
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
        GOLD_REVIEW_ASSIST_JSONL_PATH,
        GOLD_REVIEW_ASSIST_MD_PATH,
        GOLD_REVIEW_EVIDENCE_JSONL_PATH,
        GOLD_REVIEW_EVIDENCE_MD_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
        ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
        GOLD_REVIEW_IMPORT_REPORT_PATH,
        LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        LICENSE_POLICY_IMPORT_REPORT_PATH,
        MANUAL_REVIEW_PROGRESS_REPORT_PATH,
        MANUAL_REVIEW_RUNBOOK_MD_PATH,
        LOCKBOX_REVIEW_CHECKLIST_MD_PATH,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        LOCKBOX_REVIEW_IMPORT_REPORT_PATH,
        MANUAL_REVIEW_BUNDLE_MANIFEST_PATH,
    )
    if dry_run_temp is not None:
        dry_run_temp.cleanup()
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
