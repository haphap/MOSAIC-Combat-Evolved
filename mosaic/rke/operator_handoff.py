"""Operator handoff package for the remaining manual RKE gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .lockbox_review_import import LOCKBOX_REVIEW_PATH
from .manual_review_batches import build_manual_review_batch_status, write_manual_review_batches
from .promotion_gate import build_production_promotion_gate_report, write_production_promotion_gate_report


OPERATOR_HANDOFF_JSON_PATH = "registry/handoffs/rke_operator_handoff.json"
OPERATOR_HANDOFF_MD_PATH = "registry/handoffs/rke_operator_handoff.md"
LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH = "registry/review_batches/lockbox_review_next_import_template.json"


@dataclass(frozen=True)
class OperatorGateHandoff:
    gate_id: str
    review_kind: str
    passed: bool
    blocker: str
    evidence_path: str
    evidence: str
    review_packet_path: str
    import_template_path: str
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _criterion_by_id(criteria: Sequence[Any], criterion_id: str) -> Mapping[str, Any]:
    for criterion in criteria:
        row = asdict(criterion) if hasattr(criterion, "__dataclass_fields__") else dict(criterion)
        if row.get("criterion_id") == criterion_id:
            return row
    return {}


def build_lockbox_review_import_template(root: str | Path = ".") -> Mapping[str, Any]:
    root_path = Path(root)
    target = _read_json(root_path / LOCKBOX_REVIEW_PATH)
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
    }


def write_lockbox_review_import_template(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    return _write_json(
        root_path / LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
        build_lockbox_review_import_template(root_path),
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
            import_template_path=gold.import_template_path,
            pending_rows=gold.pending_rows,
            exported_rows=gold.exported_rows,
            required_manual_fields=tuple(gold.required_manual_fields),
            dry_run_command=gold.dry_run_command,
            apply_command=gold.apply_command,
            operator_note="Review source-grounded claim labels before applying this batch.",
        ),
        OperatorGateHandoff(
            gate_id="PG03",
            review_kind="source_license",
            passed=bool(pg03.get("passed")),
            blocker=str(pg03.get("blocker") or ""),
            evidence_path=str(pg03.get("evidence_path") or ""),
            evidence=str(pg03.get("evidence") or ""),
            review_packet_path=source_license.review_packet_path,
            import_template_path=source_license.import_template_path,
            pending_rows=source_license.pending_rows,
            exported_rows=source_license.exported_rows,
            required_manual_fields=tuple(source_license.required_manual_fields),
            dry_run_command=source_license.dry_run_command,
            apply_command=source_license.apply_command,
            operator_note="Compliance approval is required before production runtime retrieval.",
        ),
        OperatorGateHandoff(
            gate_id="PG09",
            review_kind="lockbox",
            passed=bool(pg09.get("passed")),
            blocker=str(pg09.get("blocker") or ""),
            evidence_path=str(pg09.get("evidence_path") or ""),
            evidence=str(pg09.get("evidence") or ""),
            review_packet_path="registry/evaluation/lockbox/lockbox_policy.json",
            import_template_path=LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH,
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
                f"--input {LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH} --dry-run"
            ),
            apply_command=(
                "mosaic-rke apply-lockbox-review --root . "
                f"--input {LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH}"
            ),
            operator_note="Open lockbox only after manual gold and license gates pass.",
        ),
    )
    generated_paths = (
        gold.import_template_path,
        source_license.import_template_path,
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
        run_order=("promotion-dry-run", "gold_set", "source_license", "promotion-status", "lockbox"),
        promotion_dry_run_command=(
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {gold.import_template_path} "
            f"--license-input {source_license.import_template_path} "
            f"--lockbox-input {LOCKBOX_REVIEW_IMPORT_TEMPLATE_PATH}"
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
                f"- Import template: {gate.import_template_path}",
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
    root_path = Path(root)
    review_batches = write_manual_review_batches(root_path)
    lockbox_template = write_lockbox_review_import_template(root_path)
    write_production_promotion_gate_report(root_path)
    handoff = build_operator_handoff(root_path)
    json_result = _write_json(root_path / OPERATOR_HANDOFF_JSON_PATH, asdict(handoff))
    md_path = root_path / OPERATOR_HANDOFF_MD_PATH
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_operator_handoff_markdown(handoff) + "\n", encoding="utf-8")
    return {
        "json": str(json_result["path"]),
        "markdown": str(md_path),
        "lockbox_import_template": str(lockbox_template["path"]),
        "gold_set_import_template": review_batches["gold_set_import_template"],
        "source_license_import_template": review_batches["source_license_import_template"],
    }
