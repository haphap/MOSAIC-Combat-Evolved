"""Non-mutating promotion dry-run across the manual RKE gates."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .lockbox_review_import import apply_lockbox_review_import
from .manual_review_import import apply_gold_set_review_import, apply_source_license_review_import
from .promotion_gate import build_production_promotion_gate_report


PROMOTION_DRY_RUN_REPORT_PATH = "registry/promotion/rke_promotion_dry_run_report.json"

PromotionDryRunKind = Literal["gold_set", "source_license", "lockbox"]


@dataclass(frozen=True)
class PromotionDryRunStep:
    review_kind: PromotionDryRunKind
    input_path: str
    provided: bool
    accepted: bool
    applied: bool
    changed_rows: int | None
    result: str
    blockers: Sequence[str]


@dataclass(frozen=True)
class PromotionDryRunReport:
    report_id: str
    simulated: bool
    mutated_original_registry: bool
    root: str
    accepted: bool
    before_blockers: Sequence[str]
    after_blockers: Sequence[str]
    before_next_state: str
    after_next_state: str
    staged_production_allowed_after_simulation: bool
    production_allowed_after_simulation: bool
    steps: Sequence[PromotionDryRunStep]


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


def _resolve_input_path(root_path: Path, input_path: str | Path | None) -> Path | None:
    if input_path is None:
        return None
    path = Path(input_path)
    return path if path.is_absolute() else root_path / path


def _copy_registry(root_path: Path, temp_root: Path) -> None:
    shutil.copytree(root_path / "registry", temp_root / "registry")
    schemas_path = root_path / "schemas"
    if schemas_path.exists():
        shutil.copytree(schemas_path, temp_root / "schemas")


def _missing_step(review_kind: PromotionDryRunKind) -> PromotionDryRunStep:
    return PromotionDryRunStep(
        review_kind=review_kind,
        input_path="",
        provided=False,
        accepted=False,
        applied=False,
        changed_rows=None,
        result="not_provided",
        blockers=(f"{review_kind} input not provided",),
    )


def build_promotion_dry_run_report(
    root: str | Path = ".",
    *,
    gold_input: str | Path | None = None,
    license_input: str | Path | None = None,
    lockbox_input: str | Path | None = None,
) -> PromotionDryRunReport:
    root_path = Path(root)
    before = build_production_promotion_gate_report(root_path)
    resolved_gold = _resolve_input_path(root_path, gold_input)
    resolved_license = _resolve_input_path(root_path, license_input)
    resolved_lockbox = _resolve_input_path(root_path, lockbox_input)

    with tempfile.TemporaryDirectory(prefix="mosaic-rke-promotion-dry-run-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        steps: list[PromotionDryRunStep] = []
        if resolved_gold is None:
            steps.append(_missing_step("gold_set"))
        else:
            report = apply_gold_set_review_import(temp_root, resolved_gold)
            steps.append(
                PromotionDryRunStep(
                    review_kind="gold_set",
                    input_path=str(resolved_gold),
                    provided=True,
                    accepted=report.accepted,
                    applied=report.accepted,
                    changed_rows=report.applied_rows,
                    result="accepted" if report.accepted else "rejected",
                    blockers=tuple(report.blockers),
                )
            )
        if resolved_license is None:
            steps.append(_missing_step("source_license"))
        else:
            report = apply_source_license_review_import(temp_root, resolved_license)
            steps.append(
                PromotionDryRunStep(
                    review_kind="source_license",
                    input_path=str(resolved_license),
                    provided=True,
                    accepted=report.accepted,
                    applied=report.accepted,
                    changed_rows=report.applied_rows,
                    result="accepted" if report.accepted else "rejected",
                    blockers=tuple(report.blockers),
                )
            )
        if resolved_lockbox is None:
            steps.append(_missing_step("lockbox"))
        else:
            report = apply_lockbox_review_import(temp_root, resolved_lockbox)
            steps.append(
                PromotionDryRunStep(
                    review_kind="lockbox",
                    input_path=str(resolved_lockbox),
                    provided=True,
                    accepted=report.accepted,
                    applied=report.applied,
                    changed_rows=1 if report.applied else 0,
                    result=report.result if report.accepted else "rejected",
                    blockers=tuple(report.rejected_reasons or report.policy_reasons),
                )
            )
        after = build_production_promotion_gate_report(temp_root)

    accepted = all(step.provided and step.accepted for step in steps)
    return PromotionDryRunReport(
        report_id="RKE-PROMOTION-DRY-RUN-REPORT-20260606",
        simulated=True,
        mutated_original_registry=False,
        root=str(root_path),
        accepted=accepted,
        before_blockers=tuple(before.blockers),
        after_blockers=tuple(after.blockers),
        before_next_state=before.next_state,
        after_next_state=after.next_state,
        staged_production_allowed_after_simulation=after.staged_production_allowed,
        production_allowed_after_simulation=after.production_allowed,
        steps=tuple(steps),
    )


def write_promotion_dry_run_report(
    root: str | Path = ".",
    *,
    gold_input: str | Path | None = None,
    license_input: str | Path | None = None,
    lockbox_input: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    report = build_promotion_dry_run_report(
        root_path,
        gold_input=gold_input,
        license_input=license_input,
        lockbox_input=lockbox_input,
    )
    result = _write_json(root_path / PROMOTION_DRY_RUN_REPORT_PATH, asdict(report))
    return {"path": str(result["path"]), "accepted": report.accepted}
