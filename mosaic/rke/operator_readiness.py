"""Integrity checks for the manual-review operator handoff bundle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .manual_review_batches import (
    GOLD_BATCH_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_IMPORT_TEMPLATE_PATH,
    LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    build_manual_review_batch_status,
)
from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    LICENSE_POLICY_IMPORT_REPORT_PATH,
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    build_source_license_policy_import,
    build_source_license_policy_template,
)
from .operator_handoff import (
    LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    OPERATOR_HANDOFF_JSON_PATH,
    OPERATOR_HANDOFF_MD_PATH,
    build_lockbox_review_import_template,
    build_operator_handoff,
    write_operator_handoff,
)
from .phase_minus1 import load_jsonl
from .promotion_dry_run import build_promotion_dry_run_report
from .promotion_gate import build_production_promotion_gate_report
from .registry_manifest import validate_required_registry


OPERATOR_READINESS_REPORT_PATH = "registry/handoffs/rke_operator_readiness_report.json"
_FORBIDDEN_IMPORT_FIELDS = frozenset(
    {
        "abstract",
        "source_text",
        "source_span_text",
        "span_text",
        "span_preview",
        "full_text",
    }
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _template_row_count(root_path: Path, relative_path: str) -> int:
    path = root_path / relative_path
    return len(load_jsonl(path)) if path.exists() else 0


def _import_templates_are_sparse(root_path: Path) -> tuple[bool, str, str]:
    for relative_path in (
        GOLD_BATCH_IMPORT_TEMPLATE_PATH,
        GOLD_FULL_IMPORT_TEMPLATE_PATH,
        LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    ):
        path = root_path / relative_path
        if not path.exists():
            return False, f"{relative_path} missing", f"{relative_path} missing"
        for index, row in enumerate(load_jsonl(path), 1):
            leaked = sorted(_FORBIDDEN_IMPORT_FIELDS & set(row))
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
    return True, "gold/license import templates omit long source text", ""


def build_operator_readiness_report(root: str | Path = ".") -> OperatorReadinessReport:
    root_path = Path(root)
    checks: list[OperatorReadinessCheck] = []

    missing, empty = validate_required_registry(root_path)
    self_generated_paths = {OPERATOR_READINESS_REPORT_PATH, LICENSE_POLICY_IMPORT_REPORT_PATH}
    missing = tuple(path for path in missing if path not in self_generated_paths)
    empty = tuple(path for path in empty if path not in self_generated_paths)
    checks.append(
        _check(
            "required_registry_valid",
            not missing and not empty,
            f"missing={len(missing)}, empty={len(empty)}",
            "required registry artifacts are missing or empty",
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
    gold_rows = _template_row_count(root_path, GOLD_BATCH_IMPORT_TEMPLATE_PATH)
    gold_full_rows = _template_row_count(root_path, GOLD_FULL_IMPORT_TEMPLATE_PATH)
    license_rows = _template_row_count(root_path, LICENSE_BATCH_IMPORT_TEMPLATE_PATH)
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
                f"license_exported={batch_status.source_license.exported_rows}/{license_rows}"
            ),
            "manual batch templates do not match batch status",
        )
    )

    sparse_ok, sparse_evidence, sparse_blocker = _import_templates_are_sparse(root_path)
    checks.append(_check("manual_import_templates_are_sparse", sparse_ok, sparse_evidence, sparse_blocker))

    lockbox_path = root_path / LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH
    lockbox_template = _read_json(lockbox_path) if lockbox_path.exists() else {}
    expected_lockbox = build_lockbox_review_import_template(root_path)
    checks.append(
        _check(
            "lockbox_template_requires_human_decision",
            bool(lockbox_template)
            and lockbox_template == expected_lockbox
            and lockbox_template.get("result") == ""
            and lockbox_template.get("open_count") is None,
            f"lockbox_template_path={LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH}",
            "lockbox import template is missing or already filled",
        )
    )

    policy_path = root_path / SOURCE_LICENSE_POLICY_TEMPLATE_PATH
    policy_template = _read_json(policy_path) if policy_path.exists() else {}
    expected_policy = build_source_license_policy_template(root_path)
    checks.append(
        _check(
            "source_license_policy_template_requires_human_decision",
            bool(policy_template)
            and policy_template == expected_policy
            and policy_template.get("approved_for_derived_claim_storage") is None
            and policy_template.get("approved_for_production_runtime") is None
            and not str(policy_template.get("reviewer") or "").strip()
            and int(policy_template.get("matched_row_count") or 0)
            == batch_status.source_license.pending_rows,
            f"policy_template_path={SOURCE_LICENSE_POLICY_TEMPLATE_PATH}",
            "source-license policy template is missing, scoped incorrectly, or already filled",
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

    blank_dry_run = build_promotion_dry_run_report(
        root_path,
        gold_input=GOLD_BATCH_IMPORT_TEMPLATE_PATH,
        license_input=LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        lockbox_input=LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
    )
    checks.append(
        _check(
            "blank_bundle_dry_run_does_not_promote",
            blank_dry_run.mutated_original_registry is False
            and not blank_dry_run.accepted
            and not blank_dry_run.production_allowed_after_simulation,
            (
                f"accepted={blank_dry_run.accepted}, "
                f"after_next_state={blank_dry_run.after_next_state}"
            ),
            "blank manual templates unexpectedly pass promotion dry-run",
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

    redaction_path = root_path / "registry/compliance/source_text_redaction_report.json"
    redaction = _read_json(redaction_path) if redaction_path.exists() else {}
    checks.append(
        _check(
            "source_text_redaction_clean",
            redaction.get("accepted") is True and int(redaction.get("failure_count") or 0) == 0,
            f"failure_count={redaction.get('failure_count')}",
            "source-text redaction audit is not clean",
        )
    )

    passed_count = sum(check.passed for check in checks)
    generated_paths = (
        OPERATOR_HANDOFF_JSON_PATH,
        OPERATOR_HANDOFF_MD_PATH,
        OPERATOR_READINESS_REPORT_PATH,
        GOLD_BATCH_IMPORT_TEMPLATE_PATH,
        GOLD_FULL_IMPORT_TEMPLATE_PATH,
        LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
        SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
        LICENSE_POLICY_IMPORT_REPORT_PATH,
        LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
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
