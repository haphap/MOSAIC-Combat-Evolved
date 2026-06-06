"""Production-promotion gate for RKE rollout decisions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lockbox import LockboxReview, evaluate_lockbox_review


PROMOTION_GATE_REPORT_PATH = "registry/promotion/rke_production_promotion_gate.json"


@dataclass(frozen=True)
class PromotionGateCriterion:
    criterion_id: str
    description: str
    passed: bool
    evidence_path: str
    evidence: str
    blocker: str


@dataclass(frozen=True)
class ProductionPromotionGateReport:
    report_id: str
    paper_trading_allowed: bool
    staged_production_allowed: bool
    production_allowed: bool
    next_state: str
    direct_production_forbidden: bool
    criteria: Sequence[PromotionGateCriterion]
    blockers: Sequence[str]


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


def _optional_json(path: Path, label: str) -> tuple[Any, tuple[str, ...]]:
    if not path.exists():
        return {}, ()
    try:
        return _read_json(path), ()
    except json.JSONDecodeError as exc:
        return {}, (f"{label} must contain valid JSON: {exc.msg}",)


def _optional_mapping(
    path: Path, label: str
) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    if not path.exists():
        return {}, ()
    try:
        payload = _read_json(path)
    except json.JSONDecodeError as exc:
        return {}, (f"{label} must contain valid JSON: {exc.msg}",)
    if isinstance(payload, Mapping):
        return payload, ()
    return {}, (f"{label} must be object",)


def _child_mapping(
    payload: Mapping[str, Any],
    field: str,
    label: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    value = payload.get(field)
    if value is None:
        return {}, ()
    if isinstance(value, Mapping):
        return dict(value), ()
    return {}, (f"{label} must be object",)


def _payload_blocker(errors: Sequence[str], fallback: str) -> str:
    return "; ".join(errors) if errors else fallback


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return {"path": str(path), "rows": 1}


def _criterion(
    criterion_id: str,
    description: str,
    passed: bool,
    evidence_path: str,
    evidence: str,
    blocker: str,
) -> PromotionGateCriterion:
    return PromotionGateCriterion(
        criterion_id=criterion_id,
        description=description,
        passed=passed,
        evidence_path=evidence_path,
        evidence=evidence,
        blocker="" if passed else blocker,
    )


def _completion_criterion(
    payload: Mapping[str, Any], criterion_id: str
) -> Mapping[str, Any]:
    for row in payload.get("criteria") or ():
        if isinstance(row, Mapping) and row.get("criterion_id") == criterion_id:
            return row
    return {}


def _lockbox_decision_from_payload(payload: Any) -> tuple[Any, tuple[str, ...]]:
    if payload is None or payload == {}:
        return evaluate_lockbox_review(None), ()
    if not isinstance(payload, Mapping):
        return evaluate_lockbox_review(None), ("lockbox review must be object",)
    try:
        return evaluate_lockbox_review(LockboxReview(**payload)), ()
    except TypeError as exc:
        return evaluate_lockbox_review(None), (f"lockbox review schema invalid: {exc}",)


def build_production_promotion_gate_report(
    root: str | Path = ".",
) -> ProductionPromotionGateReport:
    root_path = Path(root)
    completion_path = "registry/audits/rke_completion_audit.json"
    gold_path = "registry/gold_sets/tushare_research_reports.review_summary.json"
    license_path = "registry/compliance/tushare_license_review_summary.json"
    source_validation_path = (
        "registry/source_checks/source_registry_validation_report.json"
    )
    redaction_path = "registry/compliance/source_text_redaction_report.json"
    paper_path = "registry/monitoring/central_bank_paper_trading_report.json"
    lockbox_path = "registry/lockbox/central_bank_lockbox_review.json"
    patch_path = "registry/patches/central_bank_paper_trading_patch.json"

    completion, completion_errors = _optional_mapping(
        root_path / completion_path, "completion audit"
    )
    gold, gold_errors = _optional_mapping(root_path / gold_path, "gold review summary")
    license_review, license_errors = _optional_mapping(
        root_path / license_path,
        "source license review summary",
    )
    source_validation, source_validation_errors = _optional_mapping(
        root_path / source_validation_path,
        "source registry validation report",
    )
    redaction, redaction_errors = _optional_mapping(
        root_path / redaction_path,
        "source text redaction report",
    )
    paper, paper_errors = _optional_mapping(
        root_path / paper_path, "paper-trading report"
    )
    lockbox_payload, lockbox_json_errors = _optional_json(
        root_path / lockbox_path,
        "lockbox review",
    )
    patch, patch_errors = _optional_mapping(root_path / patch_path, "promotion patch")

    lockbox_decision, lockbox_payload_reasons = _lockbox_decision_from_payload(
        lockbox_payload
    )
    lockbox_payload_reasons = (*lockbox_json_errors, *lockbox_payload_reasons)
    paper_summary, paper_summary_errors = _child_mapping(
        paper,
        "paper_trading_summary",
        "paper_trading_summary",
    )
    production_monitor, production_monitor_errors = _child_mapping(
        paper,
        "production_monitor",
        "production_monitor",
    )
    patch_validation, patch_validation_errors = _child_mapping(
        patch,
        "validation_summary",
        "patch validation_summary",
    )
    rollback_rule, rollback_rule_errors = _child_mapping(
        patch,
        "rollback_rule",
        "patch rollback_rule",
    )
    c02 = _completion_criterion(completion, "C02")
    c11 = _completion_criterion(completion, "C11")
    completion_payload_errors = (*completion_errors,)
    gold_payload_errors = (*gold_errors, *completion_errors)
    license_payload_errors = (*license_errors, *completion_errors)
    source_validation_payload_errors = (*source_validation_errors,)
    redaction_payload_errors = (*redaction_errors,)
    paper_summary_payload_errors = (*paper_errors, *paper_summary_errors)
    production_monitor_payload_errors = (*paper_errors, *production_monitor_errors)
    patch_validation_payload_errors = (
        *patch_errors,
        *patch_validation_errors,
        *rollback_rule_errors,
    )
    patch_direct_payload_errors = (*patch_errors, *patch_validation_errors)

    criteria = (
        _criterion(
            "PG01",
            "Broad-rollout completion audit is green.",
            (
                not completion_payload_errors
                and bool(
                    completion
                    and all(
                        isinstance(row, Mapping) and row.get("passed") is True
                        for row in completion.get("criteria") or ()
                    )
                )
            ),
            completion_path,
            f"{sum(isinstance(row, Mapping) and row.get('passed') is True for row in completion.get('criteria') or ())} / {len(completion.get('criteria') or ())} completion criteria passed",
            _payload_blocker(
                completion_payload_errors,
                "broad-rollout completion audit still has blockers",
            ),
        ),
        _criterion(
            "PG02",
            "Manual gold-set review passed before staged production.",
            not gold_payload_errors
            and gold.get("passed") is True
            and c02.get("passed") is True,
            gold_path,
            f"{gold.get('reviewed_claims')} / {gold.get('total_claims')} gold-set claims reviewed",
            _payload_blocker(
                gold_payload_errors,
                str(c02.get("blocker") or "manual gold-set review still required"),
            ),
        ),
        _criterion(
            "PG03",
            "Source-license review approves production runtime retrieval.",
            (
                not license_payload_errors
                and license_review.get("passed") is True
                and c11.get("passed") is True
            ),
            license_path,
            f"{license_review.get('approved_for_production_runtime')} / {license_review.get('total_sources')} sources approved for production runtime",
            _payload_blocker(
                license_payload_errors,
                str(
                    c11.get("blocker")
                    or "source license review still pending or restricted"
                ),
            ),
        ),
        _criterion(
            "PG04",
            "Source registry accepts production runtime use.",
            (
                not source_validation_payload_errors
                and source_validation.get("accepted_for_production") is True
            ),
            source_validation_path,
            f"{source_validation.get('production_blocker_count')} source production blockers",
            _payload_blocker(
                source_validation_payload_errors,
                "source registry has production blockers",
            ),
        ),
        _criterion(
            "PG05",
            "Long sell-side source text is absent from runtime and public artifacts.",
            not redaction_payload_errors and redaction.get("accepted") is True,
            redaction_path,
            f"{redaction.get('failure_count')} source-text redaction failures",
            _payload_blocker(
                redaction_payload_errors, "source text redaction audit failed"
            ),
        ),
        _criterion(
            "PG06",
            "Paper-trading report is ready.",
            not paper_summary_payload_errors and paper_summary.get("ready") is True,
            paper_path,
            f"paper_trading_ready={paper_summary.get('ready')}, n={paper_summary.get('n')}",
            _payload_blocker(
                paper_summary_payload_errors, "paper-trading report is not ready"
            ),
        ),
        _criterion(
            "PG07",
            "Production monitor has not requested rollback.",
            (
                not production_monitor_payload_errors
                and bool(production_monitor)
                and production_monitor.get("state") != "rollback_required"
            ),
            paper_path,
            f"monitor_state={production_monitor.get('state')}, action={production_monitor.get('action')}",
            _payload_blocker(
                production_monitor_payload_errors,
                "production monitor requires rollback",
            ),
        ),
        _criterion(
            "PG08",
            "Promotion patch is still paper-trading and has rollback rule.",
            (
                not patch_validation_payload_errors
                and patch_validation.get("promotion_state") == "paper_trading"
                and bool(rollback_rule)
            ),
            patch_path,
            f"promotion_state={patch_validation.get('promotion_state')}, rollback_rule={bool(rollback_rule)}",
            _payload_blocker(
                patch_validation_payload_errors,
                "patch promotion state or rollback rule is invalid",
            ),
        ),
        _criterion(
            "PG09",
            "Lockbox is passed before final production.",
            lockbox_decision.production_allowed,
            lockbox_path,
            (
                f"lockbox_state={lockbox_decision.state}, "
                f"next_state={lockbox_decision.next_state}, "
                f"payload_errors={len(lockbox_payload_reasons)}"
            ),
            "; ".join((*lockbox_payload_reasons, *lockbox_decision.reasons))
            or "lockbox has not passed",
        ),
        _criterion(
            "PG10",
            "Direct production remains forbidden until all staged gates and lockbox pass.",
            not patch_direct_payload_errors
            and patch_validation.get("promotion_state") != "production",
            patch_path,
            f"promotion_state={patch_validation.get('promotion_state')}",
            _payload_blocker(
                patch_direct_payload_errors, "direct production is not blocked"
            ),
        ),
    )

    staged_required = {f"PG{idx:02d}" for idx in range(1, 9)}
    staged_allowed = all(
        criterion.passed
        for criterion in criteria
        if criterion.criterion_id in staged_required
    )
    production_allowed = staged_allowed and lockbox_decision.production_allowed
    paper_trading_allowed = paper_summary.get("ready") is True and bool(rollback_rule)
    blockers = tuple(criterion.blocker for criterion in criteria if criterion.blocker)
    if production_allowed:
        next_state = "production"
    elif staged_allowed:
        next_state = "staged_production"
    elif paper_trading_allowed:
        next_state = "paper_trading"
    else:
        next_state = "candidate"

    return ProductionPromotionGateReport(
        report_id="RKE-PRODUCTION-PROMOTION-GATE-20260606",
        paper_trading_allowed=paper_trading_allowed,
        staged_production_allowed=staged_allowed,
        production_allowed=production_allowed,
        next_state=next_state,
        direct_production_forbidden=not production_allowed,
        criteria=criteria,
        blockers=blockers,
    )


def write_production_promotion_gate_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_production_promotion_gate_report(root_path)
    return _write_json(root_path / PROMOTION_GATE_REPORT_PATH, asdict(report))
