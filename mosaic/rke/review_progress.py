"""Read-only progress checks for reviewer-edited RKE scratch files."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .license_policy_import import (
    DEFAULT_LICENSE_POLICY_IMPORT_PATH,
    SOURCE_LICENSE_POLICY_TEMPLATE_PATH,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH,
    build_source_license_policy_import,
)
from .lockbox_review_import import (
    LOCKBOX_BOOL_FIELDS,
    LOCKBOX_REQUIRED_FIELDS,
    LOCKBOX_RESULTS,
    apply_lockbox_review_import,
)
from .manual_review_aids import manual_review_aid_paths, manual_review_field_contract
from .manual_review_batches import (
    GOLD_BATCH_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_IMPORT_TEMPLATE_PATH,
    GOLD_FULL_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_TEMPLATE_PATH,
    GOLD_REVIEWED_IMPORT_PATH,
    GOLD_REVIEW_EVIDENCE_JSONL_PATH,
    GOLD_REVIEW_EVIDENCE_MD_PATH,
    GOLD_REVIEW_WORKBOOK_MD_PATH,
    LICENSE_BATCH_IMPORT_TEMPLATE_PATH,
    backfill_gold_review_from_prior,
    build_manual_review_batch_status,
)
from .manual_review_import import (
    GOLD_BOOL_FIELDS,
    TARGET_ROW_HASH_FIELD,
    apply_gold_set_review_import,
    review_row_fingerprint,
)
from .operator_handoff import LOCKBOX_REVIEWED_IMPORT_PATH
from .phase_minus1 import load_jsonl_with_errors
from .report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
    ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    _gold_review_quality_gap_targets_from_summary,
    apply_analytical_footprint_review_import,
    build_analytical_footprint_review_summary,
)
from .review_gates import summarize_gold_set_review
from .review_gates import summarize_source_license_review
from .temp_paths import (
    RKE_OPERATOR_TMP_ENV_PREFIX,
    operator_command,
    rke_temporary_directory,
)


MANUAL_REVIEW_PROGRESS_REPORT_ID = "RKE-MANUAL-REVIEW-PROGRESS-20260606"
MANUAL_REVIEW_PROGRESS_REPORT_PATH = "registry/review_batches/manual_review_progress_report.json"
MANUAL_REVIEW_RUNBOOK_MD_PATH = "registry/review_batches/manual_review_runbook.md"
GOLD_REVIEW_SUMMARY_PATH = (
    "registry/gold_sets/tushare_research_reports.review_summary.json"
)
TEMP_COPY_IGNORED_PRIVATE_REGISTRY_PATHS = frozenset(
    {
        "registry/report_intelligence/analytical_footprints.jsonl",
        "registry/report_intelligence/forecast_claims.jsonl",
        "registry/report_intelligence/markdown",
        "registry/report_intelligence/mineru",
        "registry/report_intelligence/pdfs",
        "registry/report_intelligence/processing_status.jsonl",
        "registry/report_intelligence/report_metadata.jsonl",
        "registry/report_intelligence/report_outcome_labels.jsonl",
        "registry/report_intelligence/weighted_research_contexts.jsonl",
        "registry/sources/tushare_research_reports.gold_candidates.jsonl",
        "registry/sources/tushare_research_reports.jsonl",
        "registry/sources/tushare_research_reports.manifest.json",
    }
)

ReviewProgressKind = Literal["gold_set", "source_license", "lockbox", "footprint_review"]
ACTION_QUEUE_STATES = (
    "ready_to_apply",
    "already_applied",
    "needs_human_review_fields",
    "needs_evidence_repair",
    "needs_prepare",
    "needs_quality_gate_work",
    "needs_policy_review",
    "waiting_on_dependencies",
    "needs_lockbox_decision",
    "needs_operator_inspection",
)

QUALITY_GAP_REVIEW_FIELD_MAP: Mapping[str, Mapping[str, str]] = {
    "gold_set": {
        "claim_precision": "claim_correct",
        "source_span_support_precision": "source_span_supports_claim",
        "direction_accuracy": "direction_correct",
        "target_accuracy": "target_correct",
        "horizon_accuracy": "horizon_correct",
        "variable_mapping_accuracy": "variable_mapping_correct",
        "unsupported_field_false_grounding_rate": "unsupported_field_false_grounded",
    },
    "footprint_review": {
        "footprint_precision": "footprint_correct",
        "span_support_precision": "source_span_supports_footprint",
        "metric_mapping_accuracy": "metric_mapping_correct",
        "inferred_step_tagging_accuracy": "inferred_steps_tagged_correctly",
        "unknown_on_ambiguity_rate": "unknowns_used_when_uncertain",
        "proprietary_leakage_free_rate": "no_proprietary_text_leakage",
    },
}

QUALITY_GAP_REVIEW_TAG_MAP: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "gold_set": {
        "claim_precision": ("context_synthesis_required",),
        "source_span_support_precision": ("context_synthesis_required",),
        "direction_accuracy": ("direction_text_needs_review",),
        "target_accuracy": ("forecast_mapping_insufficient",),
        "horizon_accuracy": ("context_synthesis_required",),
        "variable_mapping_accuracy": ("forecast_mapping_insufficient",),
        "unsupported_field_false_grounding_rate": (
            "unsupported_grounding_needs_review",
        ),
    },
    "footprint_review": {
        "footprint_precision": ("complex_multi_step_patterns",),
        "span_support_precision": ("missing_indicator_mentions",),
        "metric_mapping_accuracy": (
            "metric_mapping_missing",
            "metric_mapping_unknown",
            "metric_mapping_ungrounded",
            "metric_mapping_inference_available",
        ),
        "inferred_step_tagging_accuracy": ("complex_multi_step_patterns",),
        "unknown_on_ambiguity_rate": ("metric_mapping_unknown",),
        "proprietary_leakage_free_rate": (),
    },
}


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
    next_batch_commands: Mapping[str, str] = field(default_factory=dict)
    batch_plan: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    current_batch_status: Mapping[str, Any] = field(default_factory=dict)
    quality_gap_targets: Mapping[str, Any] | None = None


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
    root_resolved = root_path.resolve()

    def _ignore_private_source_files(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        directory_path = Path(directory)
        for name in names:
            try:
                relative_path = (
                    directory_path / name
                ).resolve().relative_to(root_resolved).as_posix()
            except ValueError:
                continue
            if relative_path in TEMP_COPY_IGNORED_PRIVATE_REGISTRY_PATHS:
                ignored.add(name)
        return ignored

    shutil.copytree(
        root_path / "registry",
        temp_root / "registry",
        ignore=_ignore_private_source_files,
    )
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


def _read_mapping_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in items if str(item).strip()))


GOLD_BATCH_REQUIRED_FIELDS = (
    "manual_claim_text",
    *GOLD_BOOL_FIELDS,
    "reviewer",
    "review_date",
)


def _is_missing_review_field(
    row: Mapping[str, Any],
    field: str,
    *,
    boolean_fields: Sequence[str],
) -> bool:
    if field in boolean_fields:
        return not isinstance(row.get(field), bool)
    return not str(row.get(field) or "").strip()


def _review_batch_status(
    root_path: Path,
    relative_path: str,
    *,
    required_fields: Sequence[str],
    boolean_fields: Sequence[str],
) -> Mapping[str, Any]:
    path = _resolve(root_path, relative_path)
    status: dict[str, Any] = {
        "path": relative_path,
        "exists": path.exists(),
        "rows": 0,
        "complete_rows": 0,
        "pending_rows": 0,
        "malformed_rows": 0,
        "missing_required_fields": {},
    }
    if not path.exists():
        return status

    rows, errors = load_jsonl_with_errors(path, label=relative_path)
    malformed_rows = len(errors)
    valid_rows: list[Mapping[str, Any]] = []
    for row in rows:
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            malformed_rows += 1

    missing_required_fields: dict[str, int] = {}
    complete_rows = 0
    for row in valid_rows:
        missing_fields = [
            field
            for field in required_fields
            if _is_missing_review_field(row, field, boolean_fields=boolean_fields)
        ]
        if not missing_fields:
            complete_rows += 1
            continue
        for missing_field in missing_fields:
            missing_required_fields[missing_field] = (
                missing_required_fields.get(missing_field, 0) + 1
            )

    total_rows = len(valid_rows) + malformed_rows
    status.update(
        {
            "rows": total_rows,
            "complete_rows": complete_rows,
            "pending_rows": max(total_rows - complete_rows, 0),
            "malformed_rows": malformed_rows,
            "missing_required_fields": dict(sorted(missing_required_fields.items())),
        }
    )
    return status


def _priority_score_is_positive(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value > 0
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return float(text) > 0
    except ValueError:
        return True


def _suggested_review_decision_bucket(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return "other"


def _review_field_workload(
    *,
    missing_required_fields: Mapping[str, Any],
    suggested_review_decision_counts: Mapping[str, Any],
) -> Mapping[str, Any]:
    fields = sorted(
        {
            str(field)
            for field in (
                *missing_required_fields.keys(),
                *suggested_review_decision_counts.keys(),
            )
            if str(field).strip()
        }
    )
    workload: dict[str, Any] = {}
    for field_name in fields:
        counts = suggested_review_decision_counts.get(field_name)
        count_map = counts if isinstance(counts, Mapping) else {}
        true_rows = int(count_map.get("true") or 0)
        false_rows = int(count_map.get("false") or 0)
        null_rows = int(count_map.get("null") or 0)
        other_rows = int(count_map.get("other") or 0)
        missing_rows = int(missing_required_fields.get(field_name) or 0)
        draft_decision_rows = true_rows + false_rows
        workload[field_name] = {
            "missing_required_rows": missing_rows,
            "suggested_true_rows": true_rows,
            "suggested_false_rows": false_rows,
            "suggested_null_rows": null_rows,
            "suggested_other_rows": other_rows,
            "draft_decision_available_rows": draft_decision_rows,
            "manual_decision_required_rows": max(
                missing_rows - draft_decision_rows,
                0,
            ),
        }
    return workload


def _empty_review_field_workload_item() -> dict[str, int]:
    return {
        "missing_required_rows": 0,
        "suggested_true_rows": 0,
        "suggested_false_rows": 0,
        "suggested_null_rows": 0,
        "suggested_other_rows": 0,
        "draft_decision_available_rows": 0,
        "manual_decision_required_rows": 0,
    }


def _review_field_workload_summary(workload: Mapping[str, Any]) -> Mapping[str, int]:
    summary = {
        "field_count": 0,
        "fields_with_draft_decisions": 0,
        "fields_with_manual_review_required": 0,
        "missing_required_cells": 0,
        "draft_decision_available_cells": 0,
        "manual_review_required_cells": 0,
        "suggested_true_cells": 0,
        "suggested_false_cells": 0,
        "suggested_null_cells": 0,
        "suggested_other_cells": 0,
    }
    for item in workload.values():
        if not isinstance(item, Mapping):
            continue
        summary["field_count"] += 1
        draft_rows = int(item.get("draft_decision_available_rows") or 0)
        manual_rows = int(item.get("manual_decision_required_rows") or 0)
        if draft_rows:
            summary["fields_with_draft_decisions"] += 1
        if manual_rows:
            summary["fields_with_manual_review_required"] += 1
        summary["missing_required_cells"] += int(
            item.get("missing_required_rows") or 0
        )
        summary["draft_decision_available_cells"] += draft_rows
        summary["manual_review_required_cells"] += manual_rows
        summary["suggested_true_cells"] += int(item.get("suggested_true_rows") or 0)
        summary["suggested_false_cells"] += int(item.get("suggested_false_rows") or 0)
        summary["suggested_null_cells"] += int(item.get("suggested_null_rows") or 0)
        summary["suggested_other_cells"] += int(item.get("suggested_other_rows") or 0)
    return summary


def _review_field_action_order(workload: Mapping[str, Any]) -> Mapping[str, Any]:
    manual_fields: list[dict[str, Any]] = []
    draft_fields: list[dict[str, Any]] = []
    for field_name, item in sorted(workload.items()):
        if not isinstance(item, Mapping):
            continue
        missing_rows = int(item.get("missing_required_rows") or 0)
        draft_rows = int(item.get("draft_decision_available_rows") or 0)
        manual_rows = int(item.get("manual_decision_required_rows") or 0)
        field_summary = {
            "field": str(field_name),
            "missing_required_rows": missing_rows,
            "draft_decision_available_rows": draft_rows,
            "manual_decision_required_rows": manual_rows,
        }
        if manual_rows:
            manual_fields.append(dict(field_summary))
        if draft_rows:
            draft_fields.append(dict(field_summary))
    manual_fields.sort(
        key=lambda item: (
            -int(item["manual_decision_required_rows"]),
            -int(item["missing_required_rows"]),
            str(item["field"]),
        )
    )
    draft_fields.sort(
        key=lambda item: (
            -int(item["draft_decision_available_rows"]),
            -int(item["missing_required_rows"]),
            str(item["field"]),
        )
    )
    return {
        "manual_review_required_fields": manual_fields,
        "draft_decision_review_fields": draft_fields,
    }


def _review_field_workflow_groups(
    workload: Mapping[str, Any],
    field_contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    boolean_fields = {str(field) for field in field_contract.get("boolean_fields") or ()}
    date_fields = {
        str(field)
        for field in (
            field_contract.get("date_fields").keys()
            if isinstance(field_contract.get("date_fields"), Mapping)
            else ()
        )
    }
    text_fields = {str(field) for field in field_contract.get("text_fields") or ()}
    metadata_fields = date_fields | {
        "opened_at",
        "opened_by",
        "open_count",
        "review_date",
        "reviewer",
    }
    groups: dict[str, list[dict[str, Any]]] = {
        "decision_fields_need_review": [],
        "metadata_fields_need_fill": [],
        "text_fields_need_fill": [],
        "other_fields_need_fill": [],
        "draft_decision_fields_to_verify": [],
    }
    for field_name, item in sorted(workload.items()):
        if not isinstance(item, Mapping):
            continue
        field = str(field_name)
        field_summary = {
            "field": field,
            "missing_required_rows": int(item.get("missing_required_rows") or 0),
            "draft_decision_available_rows": int(
                item.get("draft_decision_available_rows") or 0
            ),
            "manual_decision_required_rows": int(
                item.get("manual_decision_required_rows") or 0
            ),
        }
        if field_summary["draft_decision_available_rows"] and field in boolean_fields:
            groups["draft_decision_fields_to_verify"].append(dict(field_summary))
        if not field_summary["manual_decision_required_rows"]:
            continue
        if field in boolean_fields:
            groups["decision_fields_need_review"].append(dict(field_summary))
        elif field in metadata_fields:
            groups["metadata_fields_need_fill"].append(dict(field_summary))
        elif field in text_fields:
            groups["text_fields_need_fill"].append(dict(field_summary))
        else:
            groups["other_fields_need_fill"].append(dict(field_summary))
    for group_items in groups.values():
        group_items.sort(
            key=lambda item: (
                -int(item["manual_decision_required_rows"]),
                -int(item["draft_decision_available_rows"]),
                str(item["field"]),
            )
        )
    return groups


def _active_quality_gap_metrics(
    quality_gap_targets: Mapping[str, Any] | None,
) -> Mapping[str, Mapping[str, Any]]:
    if not isinstance(quality_gap_targets, Mapping):
        return {}
    metrics = quality_gap_targets.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    active: dict[str, Mapping[str, Any]] = {}
    for metric_name, metric in sorted(metrics.items()):
        if not isinstance(metric, Mapping):
            continue
        if metric.get("is_passing") is False:
            active[str(metric_name)] = metric
    return active


def _quality_gap_review_focus(
    *,
    review_kind: ReviewProgressKind,
    quality_gap_targets: Mapping[str, Any] | None,
    evidence_status: Mapping[str, Any],
    workload: Mapping[str, Any],
) -> Mapping[str, Any]:
    metric_to_field = QUALITY_GAP_REVIEW_FIELD_MAP.get(review_kind, {})
    if not metric_to_field:
        return {}
    active_metrics = _active_quality_gap_metrics(quality_gap_targets)
    if not active_metrics:
        return {}
    focus_field_counts = evidence_status.get("quality_gap_focus_field_counts")
    focus_counts = focus_field_counts if isinstance(focus_field_counts, Mapping) else {}
    suggested_tag_counts = evidence_status.get("suggested_tag_counts")
    tag_counts = suggested_tag_counts if isinstance(suggested_tag_counts, Mapping) else {}
    suggested_decision_counts = evidence_status.get("suggested_review_decision_counts")
    decision_counts = (
        suggested_decision_counts
        if isinstance(suggested_decision_counts, Mapping)
        else {}
    )
    tag_map = QUALITY_GAP_REVIEW_TAG_MAP.get(review_kind, {})
    items: list[dict[str, Any]] = []
    for metric_name, metric in active_metrics.items():
        field_name = metric_to_field.get(metric_name)
        if not field_name:
            continue
        workload_item = workload.get(field_name)
        field_workload = workload_item if isinstance(workload_item, Mapping) else {}
        decision_item = decision_counts.get(field_name)
        field_decisions = decision_item if isinstance(decision_item, Mapping) else {}
        related_tags = {
            str(tag): int(tag_counts.get(tag) or 0)
            for tag in tag_map.get(metric_name, ())
            if int(tag_counts.get(tag) or 0) > 0
        }
        item: dict[str, Any] = {
            "metric": metric_name,
            "field": field_name,
            "operator": str(metric.get("operator") or ""),
            "threshold": metric.get("threshold"),
            "current_rate": metric.get("current_rate"),
            "missing_required_rows": int(
                field_workload.get("missing_required_rows") or 0
            ),
            "draft_decision_available_rows": int(
                field_workload.get("draft_decision_available_rows") or 0
            ),
            "manual_decision_required_rows": int(
                field_workload.get("manual_decision_required_rows") or 0
            ),
            "evidence_focus_rows": int(focus_counts.get(field_name) or 0),
            "suggested_decision_counts": {
                str(bucket): int(count)
                for bucket, count in sorted(field_decisions.items())
            },
            "related_evidence_tag_counts": related_tags,
        }
        for count_key in (
            "current_pass_count",
            "current_true_count",
            "required_pass_count",
            "max_allowed_true_count",
            "minimum_additional_pass_count_if_denominator_unchanged",
            "minimum_excess_true_count_if_denominator_unchanged",
        ):
            if count_key in metric:
                item[count_key] = metric.get(count_key)
        items.append(item)
    if not items:
        return {}
    items.sort(
        key=lambda item: (
            -int(item.get("manual_decision_required_rows") or 0),
            -int(item.get("evidence_focus_rows") or 0),
            str(item.get("metric") or ""),
        )
    )
    return {
        "policy": "public_safe_quality_gap_to_current_batch_review_fields",
        "active_metric_count": len(active_metrics),
        "mapped_metric_count": len(items),
        "items": items,
    }


def _missing_review_field_workload(
    review_rows: Sequence[Mapping[str, Any]],
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    id_field: str,
    required_fields: Sequence[str],
    boolean_fields: Sequence[str],
) -> Mapping[str, Any]:
    workload: dict[str, dict[str, int]] = {}
    for row in review_rows:
        row_id = str(row.get(id_field) or "").strip()
        evidence_row = evidence_by_id.get(row_id) if row_id else None
        decision = (
            evidence_row.get("suggested_review_decision")
            if isinstance(evidence_row, Mapping)
            else None
        )
        decision_map = decision if isinstance(decision, Mapping) else {}
        for field_name in required_fields:
            if not _is_missing_review_field(
                row,
                field_name,
                boolean_fields=boolean_fields,
            ):
                continue
            item = workload.setdefault(
                str(field_name),
                _empty_review_field_workload_item(),
            )
            item["missing_required_rows"] += 1
            if field_name not in decision_map:
                continue
            bucket = _suggested_review_decision_bucket(decision_map.get(field_name))
            if bucket == "true":
                item["suggested_true_rows"] += 1
            elif bucket == "false":
                item["suggested_false_rows"] += 1
            elif bucket == "null":
                item["suggested_null_rows"] += 1
            else:
                item["suggested_other_rows"] += 1
    for item in workload.values():
        item["draft_decision_available_rows"] = (
            item["suggested_true_rows"] + item["suggested_false_rows"]
        )
        item["manual_decision_required_rows"] = max(
            item["missing_required_rows"] - item["draft_decision_available_rows"],
            0,
        )
    return {field: workload[field] for field in sorted(workload)}


def _review_evidence_alignment_status(
    root_path: Path,
    *,
    review_input_path: str,
    evidence_path: str,
    id_field: str,
    required_fields: Sequence[str] = (),
    boolean_fields: Sequence[str] = (),
) -> Mapping[str, Any]:
    review_path = _resolve(root_path, review_input_path)
    evidence_resolved = _resolve(root_path, evidence_path)
    status: dict[str, Any] = {
        "path": evidence_path,
        "exists": evidence_resolved.exists(),
        "review_input_path": review_input_path,
        "review_input_exists": review_path.exists(),
        "id_field": id_field,
        "rows": 0,
        "review_input_rows": 0,
        "covered_review_rows": 0,
        "missing_review_rows": 0,
        "extra_evidence_rows": 0,
        "malformed_rows": 0,
        "review_input_malformed_rows": 0,
        "duplicate_review_id_count": 0,
        "duplicate_evidence_id_count": 0,
        "target_row_hash_mismatch_count": 0,
        "missing_markdown_rows": 0,
        "snippet_ready_rows": 0,
        "quality_gap_focus_field_counts": {},
        "suggested_tag_counts": {},
        "priority_score_counts": {},
        "priority_reason_counts": {},
        "priority_reason_ready_rows": 0,
        "priority_reason_missing_rows": 0,
        "priority_metadata_refresh_recommended": False,
        "suggested_review_decision_counts": {},
        "review_field_workload": {},
        "same_order": False,
        "aligned": False,
    }
    if not review_path.exists() or not evidence_resolved.exists():
        return status

    review_raw_rows, review_errors = load_jsonl_with_errors(
        review_path,
        label=review_input_path,
    )
    evidence_raw_rows, evidence_errors = load_jsonl_with_errors(
        evidence_resolved,
        label=evidence_path,
    )
    review_rows = [row for row in review_raw_rows if isinstance(row, Mapping)]
    evidence_rows = [row for row in evidence_raw_rows if isinstance(row, Mapping)]
    review_malformed = len(review_errors) + len(review_raw_rows) - len(review_rows)
    evidence_malformed = (
        len(evidence_errors) + len(evidence_raw_rows) - len(evidence_rows)
    )
    review_ids = [str(row.get(id_field) or "").strip() for row in review_rows]
    evidence_ids = [str(row.get(id_field) or "").strip() for row in evidence_rows]
    review_nonempty_ids = [item for item in review_ids if item]
    evidence_nonempty_ids = [item for item in evidence_ids if item]
    missing_review_id_count = len(review_ids) - len(review_nonempty_ids)
    missing_evidence_id_count = len(evidence_ids) - len(evidence_nonempty_ids)
    review_id_set = set(review_nonempty_ids)
    evidence_id_set = set(evidence_nonempty_ids)
    duplicate_review_id_count = len(review_nonempty_ids) - len(review_id_set)
    duplicate_evidence_id_count = len(evidence_nonempty_ids) - len(evidence_id_set)
    missing_review_rows = missing_review_id_count + sum(
        1 for item in review_nonempty_ids if item not in evidence_id_set
    )
    extra_evidence_rows = missing_evidence_id_count + sum(
        1 for item in evidence_nonempty_ids if item not in review_id_set
    )
    evidence_by_id = {
        str(row.get(id_field) or "").strip(): row
        for row in evidence_rows
        if str(row.get(id_field) or "").strip()
    }
    missing_markdown_rows = sum(
        1 for row in evidence_rows if row.get("markdown_exists") is False
    )
    snippet_ready_rows = sum(1 for row in evidence_rows if row.get("evidence_snippets"))
    quality_focus_counts = Counter(
        str(field)
        for row in evidence_rows
        for field in row.get("quality_gap_focus_fields") or ()
        if str(field).strip()
    )
    suggested_tag_counts = Counter(
        str(tag)
        for row in evidence_rows
        for tag in row.get("suggested_manual_error_tags") or ()
        if str(tag).strip()
    )
    priority_score_counts = Counter(
        str(row.get("priority_score") if row.get("priority_score") is not None else 0)
        for row in evidence_rows
    )
    priority_reason_counts = Counter(
        str(reason)
        for row in evidence_rows
        for reason in row.get("priority_reasons") or ()
        if str(reason).strip()
    )
    priority_reason_ready_rows = sum(
        1 for row in evidence_rows if tuple(row.get("priority_reasons") or ())
    )
    priority_reason_missing_rows = sum(
        1
        for row in evidence_rows
        if _priority_score_is_positive(row.get("priority_score"))
        and not tuple(row.get("priority_reasons") or ())
    )
    suggested_decision_counts: dict[str, Counter[str]] = {}
    for row in evidence_rows:
        decision = row.get("suggested_review_decision")
        if not isinstance(decision, Mapping):
            continue
        for decision_field, value in decision.items():
            field_name = str(decision_field)
            if not field_name:
                continue
            suggested_decision_counts.setdefault(field_name, Counter())[
                _suggested_review_decision_bucket(value)
            ] += 1
    hash_mismatch_count = 0
    for row in review_rows:
        row_id = str(row.get(id_field) or "").strip()
        if not row_id:
            continue
        evidence_row = evidence_by_id.get(row_id)
        if evidence_row is None:
            continue
        review_hash = str(row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        evidence_hash = str(evidence_row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        if review_hash and evidence_hash and review_hash != evidence_hash:
            hash_mismatch_count += 1
    same_order = (
        bool(review_nonempty_ids)
        and len(review_nonempty_ids) == len(evidence_nonempty_ids)
        and review_nonempty_ids == evidence_nonempty_ids
    )
    aligned = (
        bool(review_nonempty_ids)
        and same_order
        and review_malformed == 0
        and evidence_malformed == 0
        and missing_review_id_count == 0
        and missing_evidence_id_count == 0
        and duplicate_review_id_count == 0
        and duplicate_evidence_id_count == 0
        and missing_review_rows == 0
        and extra_evidence_rows == 0
        and hash_mismatch_count == 0
    )
    status.update(
        {
            "rows": len(evidence_rows) + evidence_malformed,
            "review_input_rows": len(review_rows) + review_malformed,
            "covered_review_rows": sum(
                1 for item in review_nonempty_ids if item in evidence_id_set
            ),
            "missing_review_rows": missing_review_rows,
            "extra_evidence_rows": extra_evidence_rows,
            "malformed_rows": evidence_malformed,
            "review_input_malformed_rows": review_malformed,
            "duplicate_review_id_count": duplicate_review_id_count,
            "duplicate_evidence_id_count": duplicate_evidence_id_count,
            "target_row_hash_mismatch_count": hash_mismatch_count,
            "missing_markdown_rows": missing_markdown_rows,
            "snippet_ready_rows": snippet_ready_rows,
            "quality_gap_focus_field_counts": dict(
                sorted(quality_focus_counts.items())
            ),
            "suggested_tag_counts": dict(sorted(suggested_tag_counts.items())),
            "priority_score_counts": dict(sorted(priority_score_counts.items())),
            "priority_reason_counts": dict(sorted(priority_reason_counts.items())),
            "priority_reason_ready_rows": priority_reason_ready_rows,
            "priority_reason_missing_rows": priority_reason_missing_rows,
            "priority_metadata_refresh_recommended": priority_reason_missing_rows > 0,
            "suggested_review_decision_counts": {
                field: dict(sorted(counts.items()))
                for field, counts in sorted(suggested_decision_counts.items())
            },
            "review_field_workload": _missing_review_field_workload(
                review_rows,
                evidence_by_id=evidence_by_id,
                id_field=id_field,
                required_fields=required_fields,
                boolean_fields=boolean_fields,
            ),
            "same_order": same_order,
            "aligned": aligned,
        }
    )
    return status


def _review_target_alignment_status(
    root_path: Path,
    *,
    review_input_path: str,
    target_path: str,
    id_field: str,
) -> Mapping[str, Any]:
    review_path = _resolve(root_path, review_input_path)
    target_resolved = _resolve(root_path, target_path)
    status: dict[str, Any] = {
        "target_path": target_path,
        "exists": target_resolved.exists(),
        "review_input_path": review_input_path,
        "review_input_exists": review_path.exists(),
        "id_field": id_field,
        "review_input_rows": 0,
        "target_rows": 0,
        "missing_target_rows": 0,
        "target_row_hash_mismatch_count": 0,
        "malformed_rows": 0,
        "target_malformed_rows": 0,
        "aligned": False,
    }
    if not review_path.exists() or not target_resolved.exists():
        return status

    review_raw_rows, review_errors = load_jsonl_with_errors(
        review_path,
        label=review_input_path,
    )
    target_raw_rows, target_errors = load_jsonl_with_errors(
        target_resolved,
        label=target_path,
    )
    review_rows = [row for row in review_raw_rows if isinstance(row, Mapping)]
    target_rows = [row for row in target_raw_rows if isinstance(row, Mapping)]
    review_malformed = len(review_errors) + len(review_raw_rows) - len(review_rows)
    target_malformed = len(target_errors) + len(target_raw_rows) - len(target_rows)
    target_by_id = {
        str(row.get(id_field) or "").strip(): row
        for row in target_rows
        if str(row.get(id_field) or "").strip()
    }
    missing_target_rows = 0
    hash_mismatch_count = 0
    for row in review_rows:
        row_id = str(row.get(id_field) or "").strip()
        if not row_id:
            missing_target_rows += 1
            continue
        target_row = target_by_id.get(row_id)
        if target_row is None:
            missing_target_rows += 1
            continue
        review_hash = str(row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        target_hash = str(target_row.get(TARGET_ROW_HASH_FIELD) or "").strip()
        if not target_hash:
            target_hash = review_row_fingerprint(target_row)
        if review_hash != target_hash:
            hash_mismatch_count += 1
    aligned = (
        bool(review_rows)
        and review_malformed == 0
        and target_malformed == 0
        and missing_target_rows == 0
        and hash_mismatch_count == 0
    )
    status.update(
        {
            "review_input_rows": len(review_rows) + review_malformed,
            "target_rows": len(target_rows) + target_malformed,
            "missing_target_rows": missing_target_rows,
            "target_row_hash_mismatch_count": hash_mismatch_count,
            "malformed_rows": review_malformed,
            "target_malformed_rows": target_malformed,
            "aligned": aligned,
        }
    )
    return status


def _gold_backfill_blocker_reason(blocker: str) -> str:
    if "is missing required manual fields" in blocker:
        return "prior_review_missing_required_manual_fields"
    if "no prior reviewed row" in blocker:
        return "prior_review_missing"
    if "duplicate claim/document keys" in blocker:
        return "prior_review_duplicate_keys"
    if "must contain valid JSON" in blocker:
        return "malformed_json"
    if "row must be object" in blocker:
        return "non_object_row"
    if "claim_id: required" in blocker:
        return "claim_id_required"
    if "missing or empty" in blocker:
        return "input_or_prior_missing_or_empty"
    return "other"


def _gold_backfill_status(root_path: Path) -> Mapping[str, Any]:
    result = backfill_gold_review_from_prior(
        root_path,
        input_path=GOLD_REVIEWED_IMPORT_PATH,
        dry_run=True,
    )
    reason_counts = Counter(
        _gold_backfill_blocker_reason(blocker) for blocker in result.blockers
    )
    return {
        "available": result.updated_rows > 0 and not result.blockers,
        "write_command_available": result.updated_rows > 0 and not result.blockers,
        "row_count": result.row_count,
        "matched_prior_rows": result.matched_prior_rows,
        "updated_rows": result.updated_rows,
        "copied_field_count": result.copied_field_count,
        "preserved_existing_field_count": result.preserved_existing_field_count,
        "complete_after_backfill_rows": result.complete_after_backfill_rows,
        "blocker_count": len(result.blockers),
        "blocker_reason_counts": dict(sorted(reason_counts.items())),
    }


def _gold_batch_status(root_path: Path) -> Mapping[str, Any]:
    status = dict(
        _review_batch_status(
            root_path,
            GOLD_REVIEWED_IMPORT_PATH,
            required_fields=GOLD_BATCH_REQUIRED_FIELDS,
            boolean_fields=GOLD_BOOL_FIELDS,
        )
    )
    status["evidence_status"] = _review_evidence_alignment_status(
        root_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
        evidence_path=GOLD_REVIEW_EVIDENCE_JSONL_PATH,
        id_field="claim_id",
        required_fields=GOLD_BATCH_REQUIRED_FIELDS,
        boolean_fields=GOLD_BOOL_FIELDS,
    )
    status["target_status"] = _review_target_alignment_status(
        root_path,
        review_input_path=GOLD_REVIEWED_IMPORT_PATH,
        target_path=GOLD_REVIEW_TEMPLATE_PATH,
        id_field="claim_id",
    )
    status["backfill_status"] = _gold_backfill_status(root_path)
    return status


def _footprint_batch_status(root_path: Path) -> Mapping[str, Any]:
    status = dict(
        _review_batch_status(
            root_path,
            ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
            required_fields=ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
            boolean_fields=ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
        )
    )
    status["evidence_status"] = _review_evidence_alignment_status(
        root_path,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        evidence_path=ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
        id_field="footprint_id",
        required_fields=ANALYTICAL_FOOTPRINT_REVIEW_REQUIRED_FIELDS,
        boolean_fields=ANALYTICAL_FOOTPRINT_REVIEW_BOOLEAN_FIELDS,
    )
    status["target_status"] = _review_target_alignment_status(
        root_path,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
        target_path=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
        id_field="footprint_id",
    )
    return status


def _lockbox_missing_field(row: Mapping[str, Any], field: str) -> bool:
    if field in LOCKBOX_BOOL_FIELDS:
        return not isinstance(row.get(field), bool)
    if field == "open_count":
        return type(row.get(field)) is not int
    return not str(row.get(field) or "").strip()


def _lockbox_decision_status(root_path: Path) -> Mapping[str, Any]:
    path = _resolve(root_path, LOCKBOX_REVIEWED_IMPORT_PATH)
    status: dict[str, Any] = {
        "path": LOCKBOX_REVIEWED_IMPORT_PATH,
        "exists": path.exists(),
        "rows": 0,
        "complete_rows": 0,
        "pending_rows": 0,
        "malformed_rows": 0,
        "missing_required_fields": {},
        "invalid_required_fields": {},
    }
    if not path.exists():
        return status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        status.update({"rows": 1, "pending_rows": 1, "malformed_rows": 1})
        return status
    if not isinstance(payload, Mapping):
        status.update({"rows": 1, "pending_rows": 1, "malformed_rows": 1})
        return status

    required_fields = (*LOCKBOX_REQUIRED_FIELDS, *LOCKBOX_BOOL_FIELDS)
    missing_required_fields = {
        field: 1 for field in required_fields if _lockbox_missing_field(payload, field)
    }
    invalid_required_fields: dict[str, int] = {}
    if not missing_required_fields:
        if str(payload.get("result") or "") not in LOCKBOX_RESULTS - {"not_opened"}:
            invalid_required_fields["result"] = 1
        if type(payload.get("open_count")) is int and int(payload.get("open_count") or 0) < 1:
            invalid_required_fields["open_count"] = 1

    complete_rows = 0 if missing_required_fields or invalid_required_fields else 1
    status.update(
        {
            "rows": 1,
            "complete_rows": complete_rows,
            "pending_rows": 1 - complete_rows,
            "malformed_rows": 0,
            "missing_required_fields": dict(sorted(missing_required_fields.items())),
            "invalid_required_fields": dict(sorted(invalid_required_fields.items())),
        }
    )
    return status


def _gold_next_batch_commands(pending_rows: int) -> dict[str, str]:
    if pending_rows <= 0:
        return {}
    batch_size = min(50, int(pending_rows))
    return {
        "assist": operator_command(
            "mosaic-rke write-gold-review-assist --root . "
            f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "evidence": operator_command(
            _gold_review_evidence_command_text(batch_size)
        ),
        "prepare": (
            operator_command(
                "mosaic-rke prepare-gold-review --root . "
                f"--gold-batch-size {batch_size} --offset 0 --force "
                "--reviewer <name> --review-date <YYYY-MM-DD>"
            )
        ),
        "backfill_dry_run": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "backfill_write": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --write"
        ),
        "dry_run": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
        ),
        "apply": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
    }


def _gold_review_evidence_command_text(limit: int) -> str:
    return (
        "mosaic-rke write-gold-review-evidence --root . "
        f"--limit {limit} --offset 0 --review-input {GOLD_REVIEWED_IMPORT_PATH}"
    )


def _current_gold_batch_target_covered_rows(
    current_batch_status: Mapping[str, Any],
) -> int:
    target_status = current_batch_status.get("target_status")
    if (
        bool(current_batch_status.get("exists"))
        and int(current_batch_status.get("malformed_rows") or 0) == 0
        and isinstance(target_status, Mapping)
        and bool(target_status.get("aligned"))
    ):
        return int(current_batch_status.get("rows") or 0)
    return 0


def _gold_commands_for_current_batch(
    commands: Mapping[str, str],
    current_batch_status: Mapping[str, Any],
) -> dict[str, str]:
    out = dict(commands)
    covered_rows = _current_gold_batch_target_covered_rows(current_batch_status)
    if covered_rows > 0:
        out["evidence"] = operator_command(
            _gold_review_evidence_command_text(covered_rows)
        )
    backfill_status = current_batch_status.get("backfill_status")
    if (
        isinstance(backfill_status, Mapping)
        and not bool(backfill_status.get("write_command_available"))
    ):
        out.pop("backfill_write", None)
    return out


def _gold_quality_gate_commands() -> dict[str, str]:
    return {
        "assist": operator_command(
            "mosaic-rke write-gold-review-assist --root . "
            f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "refresh_source_candidates": operator_command(
            "mosaic-rke fetch-tushare-reports --root . --p9-profile "
            "--start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> "
            "--merge-existing-source"
        ),
        "expand_candidate_review_rows": operator_command(
            "mosaic-rke gold-candidate-claims --root . "
            "--refresh-candidates-from-source --ensure-candidate-review-rows"
        ),
        "prepare_reviewed_failures": operator_command(
            "mosaic-rke prepare-gold-review --root . --reviewed-failures "
            "--gold-batch-size 50 --offset 0 --force "
            "--reviewer <name> --review-date <YYYY-MM-DD>"
        ),
        "prepare_expanded_batch": operator_command(
            "mosaic-rke prepare-gold-review --root . "
            "--gold-batch-size 50 --offset 0 --force "
            "--reviewer <name> --review-date <YYYY-MM-DD>"
        ),
        "evidence": operator_command(
            _gold_review_evidence_command_text(50)
        ),
        "backfill_dry_run": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
        ),
        "backfill_write": operator_command(
            f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --write"
        ),
        "dry_run": operator_command(
            f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
        ),
    }


def _footprint_next_batch_commands(pending_rows: int) -> dict[str, str]:
    if pending_rows <= 0:
        return {}
    batch_size = min(50, int(pending_rows))
    return {
        "assist": operator_command(
            "mosaic-rke write-footprint-review-assist --root . "
            f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
        "evidence": operator_command(
            "mosaic-rke write-footprint-review-evidence --root . "
            f"--limit {batch_size} --offset 0 --review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
        "prepare": (
            operator_command(
                "mosaic-rke prepare-footprint-review --root . "
                f"--limit {batch_size} --offset 0 --priority "
                "--reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
            )
        ),
        "dry_run": operator_command(
            "mosaic-rke apply-footprint-review --root . "
            f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
        ),
        "apply": operator_command(
            "mosaic-rke apply-footprint-review --root . "
            f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        ),
    }


def _manual_review_batch_plan(
    review_kind: ReviewProgressKind,
    pending_rows: int,
    *,
    batch_size: int = 50,
) -> tuple[Mapping[str, Any], ...]:
    if review_kind not in {"gold_set", "footprint_review"} or pending_rows <= 0:
        return ()
    rows_remaining = int(pending_rows)
    size = max(1, int(batch_size))
    batches: list[Mapping[str, Any]] = []
    for batch_index, offset in enumerate(range(0, rows_remaining, size), 1):
        limit = min(size, rows_remaining - offset)
        if review_kind == "gold_set":
            commands = {
                "evidence": operator_command(
                    "mosaic-rke write-gold-review-evidence --root . "
                    f"--limit {limit} --offset {offset} "
                    f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "prepare": operator_command(
                    "mosaic-rke prepare-gold-review --root . "
                    f"--gold-batch-size {limit} --offset {offset} --force "
                    "--reviewer <name> --review-date <YYYY-MM-DD>"
                ),
                "backfill_dry_run": operator_command(
                    f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
                "backfill_write": operator_command(
                    f"mosaic-rke backfill-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --write"
                ),
                "dry_run": operator_command(
                    f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
                ),
                "apply": operator_command(
                    f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
                ),
            }
        else:
            commands = {
                "assist": operator_command(
                    "mosaic-rke write-footprint-review-assist --root . "
                    f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "evidence": operator_command(
                    "mosaic-rke write-footprint-review-evidence --root . "
                    f"--limit {limit} --offset {offset} "
                    f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
                "prepare": operator_command(
                    "mosaic-rke prepare-footprint-review --root . "
                    f"--limit {limit} --offset {offset} --priority "
                    "--reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
                ),
                "dry_run": operator_command(
                    "mosaic-rke apply-footprint-review --root . "
                    f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
                ),
                "apply": operator_command(
                    "mosaic-rke apply-footprint-review --root . "
                    f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
                ),
            }
        batches.append(
            {
                "batch_index": batch_index,
                "offset": offset,
                "limit": limit,
                "pending_row_start": offset + 1,
                "pending_row_end": offset + limit,
                "mode": (
                    "pending_offset_batch_before_applying_any_batch"
                    if review_kind == "gold_set"
                    else "priority_sorted_pending_batch_before_applying_any_batch"
                ),
                "apply_effect": "merge_batch_into_target_review_template",
                "target_review_template_path": (
                    GOLD_REVIEW_TEMPLATE_PATH
                    if review_kind == "gold_set"
                    else ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
                ),
                "batch_input_path": (
                    GOLD_REVIEWED_IMPORT_PATH
                    if review_kind == "gold_set"
                    else ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
                ),
                "promotion_input_path": (
                    GOLD_FULL_REVIEWED_IMPORT_PATH
                    if review_kind == "gold_set"
                    else ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
                ),
                "commands": commands,
            }
        )
    return tuple(batches)


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
    next_batch_commands: Mapping[str, str] | None = None,
    batch_plan: Sequence[Mapping[str, Any]] | None = None,
    current_batch_status: Mapping[str, Any] | None = None,
    quality_gap_targets: Mapping[str, Any] | None = None,
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
        next_batch_commands=dict(next_batch_commands or {}),
        batch_plan=tuple(batch_plan or ()),
        current_batch_status=dict(current_batch_status or {}),
        quality_gap_targets=quality_gap_targets,
    )


def _gold_quality_gap_targets_from_review_summary(
    summary: Any,
    public_quality_gap_targets: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    if getattr(summary, "quality_gap_targets", None):
        return summary.quality_gap_targets
    if public_quality_gap_targets:
        return public_quality_gap_targets
    return _gold_review_quality_gap_targets_from_summary(asdict(summary))


def _gold_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = GOLD_FULL_REVIEWED_IMPORT_PATH
    current_batch_status = _gold_batch_status(root_path)
    current_summary = summarize_gold_set_review(root_path)
    public_quality_gap_targets = _gold_review_quality_gap_targets_from_summary(
        _read_mapping_json(root_path / GOLD_REVIEW_SUMMARY_PATH)
    )
    current_quality_gap_targets = _gold_quality_gap_targets_from_review_summary(
        current_summary,
        public_quality_gap_targets,
    )
    if current_summary.review_complete:
        resolved_input = _resolve(root_path, input_path)
        return ManualReviewGateProgress(
            review_kind="gold_set",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=current_summary.total_claims,
            input_rows=_jsonl_row_count(resolved_input) if resolved_input.exists() else 0,
            complete_rows=current_summary.reviewed_claims,
            pending_rows=current_summary.pending_claims,
            simulation_accepted=current_summary.passed,
            ready_for_promotion=current_summary.passed,
            blockers=tuple(current_summary.blockers),
            prepare_command=operator_command("mosaic-rke prepare-gold-review --root . --full"),
            dry_run_command=operator_command(
                f"mosaic-rke apply-gold-review --root . --input {input_path} --dry-run"
            ),
            apply_command=operator_command(
                f"mosaic-rke apply-gold-review --root . --input {input_path}"
            ),
            next_batch_commands=(
                _gold_commands_for_current_batch(
                    _gold_quality_gate_commands(),
                    current_batch_status,
                )
                if not current_summary.passed
                else {}
            ),
            batch_plan=(),
            current_batch_status=current_batch_status,
            quality_gap_targets=current_quality_gap_targets,
        )
    target_rows = current_summary.total_claims
    resolved_input = _resolve(root_path, input_path)
    prepare_command = operator_command("mosaic-rke prepare-gold-review --root . --full")
    dry_run_command = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {input_path} --dry-run"
    )
    apply_command = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {input_path}"
    )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="gold_set",
            input_path=input_path,
            target_rows=target_rows,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            next_batch_commands=_gold_commands_for_current_batch(
                _gold_next_batch_commands(target_rows),
                current_batch_status,
            ),
            batch_plan=_manual_review_batch_plan("gold_set", target_rows),
            current_batch_status=current_batch_status,
            quality_gap_targets=current_quality_gap_targets,
        )

    input_rows = _jsonl_row_count(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        report = apply_gold_set_review_import(temp_root, resolved_input, dry_run=False)
        summary = summarize_gold_set_review(temp_root)
    quality_gap_targets = (
        _gold_quality_gap_targets_from_review_summary(
            summary,
            public_quality_gap_targets,
        )
        or current_quality_gap_targets
    )
    blockers = _dedupe((*report.blockers, *summary.blockers))
    return ManualReviewGateProgress(
        review_kind="gold_set",
        input_path=input_path,
        input_exists=True,
        target_rows=summary.total_claims,
        input_rows=input_rows,
        complete_rows=summary.reviewed_claims,
        pending_rows=summary.pending_claims,
        simulation_accepted=report.accepted,
        ready_for_promotion=report.accepted and summary.passed,
        blockers=blockers,
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        next_batch_commands=_gold_commands_for_current_batch(
            _gold_next_batch_commands(summary.pending_claims),
            current_batch_status,
        ),
        batch_plan=_manual_review_batch_plan("gold_set", summary.pending_claims),
        current_batch_status=current_batch_status,
        quality_gap_targets=quality_gap_targets,
    )


def _source_license_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = SOURCE_LICENSE_REVIEWED_POLICY_PATH
    target_rows = build_manual_review_batch_status(root_path)[0].source_license.pending_rows
    resolved_input = _resolve(root_path, input_path)
    prepare_command = operator_command("mosaic-rke prepare-license-policy-review --root .")
    dry_run_command = operator_command(
        "mosaic-rke build-license-review-import --root . "
        f"--policy {input_path} --output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        f"mosaic-rke apply-license-review --root . --input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} --dry-run"
    )
    apply_command = operator_command(
        "mosaic-rke build-license-review-import --root . "
        f"--policy {input_path} --output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        f"mosaic-rke apply-license-review --root . --input {DEFAULT_LICENSE_POLICY_IMPORT_PATH}"
    )
    current_summary = summarize_source_license_review(root_path)
    if current_summary.passed and current_summary.review_complete:
        return ManualReviewGateProgress(
            review_kind="source_license",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=current_summary.total_sources,
            input_rows=_json_object_exists(resolved_input),
            complete_rows=current_summary.reviewed_sources,
            pending_rows=0,
            simulation_accepted=True,
            ready_for_promotion=True,
            blockers=(),
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            next_batch_commands={},
            current_batch_status={"already_applied": True},
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
        next_batch_commands={},
    )


def _lockbox_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = LOCKBOX_REVIEWED_IMPORT_PATH
    current_batch_status = _lockbox_decision_status(root_path)
    resolved_input = _resolve(root_path, input_path)
    prepare_command = operator_command("mosaic-rke prepare-lockbox-review --root .")
    dry_run_command = operator_command(
        f"mosaic-rke apply-lockbox-review --root . --input {input_path} --dry-run"
    )
    apply_command = operator_command(
        f"mosaic-rke apply-lockbox-review --root . --input {input_path}"
    )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="lockbox",
            input_path=input_path,
            target_rows=1,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            batch_plan=(),
            current_batch_status=current_batch_status,
        )

    input_rows = _json_object_exists(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
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
        current_batch_status=current_batch_status,
    )


def _footprint_review_summary(root_path: Path) -> Mapping[str, Any]:
    path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_SUMMARY_PATH
    payload: Mapping[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        payload = loaded if isinstance(loaded, Mapping) else {}
    if payload.get("quality_gap_targets") is not None:
        return payload

    template_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    if not template_path.exists():
        return payload
    raw_rows, _ = load_jsonl_with_errors(
        template_path,
        label=ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH,
    )
    template_rows = tuple(row for row in raw_rows if isinstance(row, Mapping))
    if not template_rows:
        return payload
    computed = build_analytical_footprint_review_summary(template_rows)
    return {**computed, **payload, "quality_gap_targets": computed.get("quality_gap_targets")}


def _footprint_review_target_rows(root_path: Path, summary: Mapping[str, Any]) -> int:
    template_path = root_path / ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH
    if template_path.exists():
        return _jsonl_row_count(template_path)
    return int(summary.get("total_rows") or 0)


def _footprint_review_progress(root_path: Path) -> ManualReviewGateProgress:
    input_path = ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH
    current_batch_status = _footprint_batch_status(root_path)
    resolved_input = _resolve(root_path, input_path)
    summary = _footprint_review_summary(root_path)
    target_rows = _footprint_review_target_rows(root_path, summary)
    prepare_command = (
        operator_command(
            "mosaic-rke prepare-footprint-review --root . "
            f"--output {input_path} --overwrite"
        )
    )
    dry_run_command = operator_command(
        f"mosaic-rke apply-footprint-review --root . --input {input_path} --dry-run"
    )
    apply_command = operator_command(
        f"mosaic-rke apply-footprint-review --root . --input {input_path}"
    )
    if summary.get("accepted") is True and summary.get("review_complete") is True:
        return ManualReviewGateProgress(
            review_kind="footprint_review",
            input_path=input_path,
            input_exists=resolved_input.exists(),
            target_rows=target_rows,
            input_rows=_jsonl_row_count(resolved_input) if resolved_input.exists() else 0,
            complete_rows=int(summary.get("reviewed_rows") or target_rows),
            pending_rows=0,
            simulation_accepted=True,
            ready_for_promotion=True,
            blockers=(),
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            current_batch_status=current_batch_status,
            quality_gap_targets=summary.get("quality_gap_targets"),
        )
    if not resolved_input.exists():
        return _missing_gate(
            review_kind="footprint_review",
            input_path=input_path,
            target_rows=target_rows,
            prepare_command=prepare_command,
            dry_run_command=dry_run_command,
            apply_command=apply_command,
            next_batch_commands=_footprint_next_batch_commands(target_rows),
            batch_plan=_manual_review_batch_plan("footprint_review", target_rows),
            current_batch_status=current_batch_status,
            quality_gap_targets=summary.get("quality_gap_targets"),
        )

    input_rows = _jsonl_row_count(resolved_input)
    with rke_temporary_directory(prefix="mosaic-rke-review-progress-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _copy_registry(root_path, temp_root)
        report = apply_analytical_footprint_review_import(
            temp_root,
            resolved_input,
            dry_run=False,
        )
        simulated_summary = _footprint_review_summary(temp_root)
    blockers = list(report.blockers)
    blockers.extend(str(item) for item in simulated_summary.get("blockers", ()))
    blockers.extend(
        str(item) for item in simulated_summary.get("quality_gate_blockers", ())
    )
    pending_rows = int(simulated_summary.get("pending_rows") or 0)
    complete_rows = int(
        simulated_summary.get("reviewed_rows")
        or simulated_summary.get("complete_rows")
        or max(target_rows - pending_rows, 0)
    )
    return ManualReviewGateProgress(
        review_kind="footprint_review",
        input_path=input_path,
        input_exists=True,
        target_rows=target_rows,
        input_rows=input_rows,
        complete_rows=complete_rows,
        pending_rows=pending_rows,
        simulation_accepted=report.accepted,
        ready_for_promotion=(
            report.accepted
            and simulated_summary.get("accepted") is True
            and simulated_summary.get("quality_gate_passed") is True
        ),
        blockers=_dedupe(blockers),
        prepare_command=prepare_command,
        dry_run_command=dry_run_command,
        apply_command=apply_command,
        next_batch_commands=_footprint_next_batch_commands(pending_rows),
        batch_plan=_manual_review_batch_plan("footprint_review", pending_rows),
        current_batch_status=current_batch_status,
        quality_gap_targets=simulated_summary.get("quality_gap_targets"),
    )


def _render_batch_status_lines(
    label: str,
    status: Mapping[str, Any],
    *,
    review_kind: ReviewProgressKind | None = None,
) -> list[str]:
    if not status:
        return [f"- {label}: no current batch scratch configured"]
    lines = [
        (
            f"- {label}: `{status.get('path')}`; "
            f"exists: {str(bool(status.get('exists'))).lower()}; "
            f"rows: {int(status.get('rows') or 0)}; "
            f"complete: {int(status.get('complete_rows') or 0)}; "
            f"pending: {int(status.get('pending_rows') or 0)}; "
            f"malformed: {int(status.get('malformed_rows') or 0)}"
        )
    ]
    missing_required_fields = status.get("missing_required_fields")
    if isinstance(missing_required_fields, Mapping) and missing_required_fields:
        missing = ", ".join(
            f"`{field}`={int(count)}"
            for field, count in sorted(missing_required_fields.items())
        )
        lines.append(f"  Missing required fields: {missing}")
    invalid_required_fields = status.get("invalid_required_fields")
    if isinstance(invalid_required_fields, Mapping) and invalid_required_fields:
        invalid = ", ".join(
            f"`{field}`={int(count)}"
            for field, count in sorted(invalid_required_fields.items())
        )
        lines.append(f"  Invalid required fields: {invalid}")
    evidence_status = status.get("evidence_status")
    if isinstance(evidence_status, Mapping) and evidence_status:
        lines.append(
            "  Evidence alignment: "
            f"path=`{evidence_status.get('path')}`; "
            f"exists: {str(bool(evidence_status.get('exists'))).lower()}; "
            f"rows: {int(evidence_status.get('rows') or 0)}; "
            f"covered: {int(evidence_status.get('covered_review_rows') or 0)}/"
            f"{int(evidence_status.get('review_input_rows') or 0)}; "
            f"same_order: {str(bool(evidence_status.get('same_order'))).lower()}; "
            f"aligned: {str(bool(evidence_status.get('aligned'))).lower()}"
        )
        lines.append(
            "  Evidence quality: "
            f"snippet_ready: {int(evidence_status.get('snippet_ready_rows') or 0)}; "
            f"missing_markdown: {int(evidence_status.get('missing_markdown_rows') or 0)}"
        )
        priority_reason_missing_rows = int(
            evidence_status.get("priority_reason_missing_rows") or 0
        )
        priority_reason_ready_rows = int(
            evidence_status.get("priority_reason_ready_rows") or 0
        )
        if priority_reason_missing_rows or priority_reason_ready_rows:
            refresh_recommended = str(
                bool(evidence_status.get("priority_metadata_refresh_recommended"))
            ).lower()
            lines.append(
                "  Evidence priority metadata: "
                f"reason_ready: {priority_reason_ready_rows}; "
                f"missing_reason_rows: {priority_reason_missing_rows}; "
                f"refresh_recommended: {refresh_recommended}"
            )
        quality_focus = evidence_status.get("quality_gap_focus_field_counts")
        if isinstance(quality_focus, Mapping) and quality_focus:
            focus = ", ".join(
                f"`{field}`={int(count)}"
                for field, count in sorted(quality_focus.items())
            )
            lines.append(f"  Quality-gap focus fields: {focus}")
        suggested_tags = evidence_status.get("suggested_tag_counts")
        if isinstance(suggested_tags, Mapping) and suggested_tags:
            tags = ", ".join(
                f"`{tag}`={int(count)}"
                for tag, count in sorted(suggested_tags.items())
            )
            lines.append(f"  Suggested evidence tags: {tags}")
        priority_scores = evidence_status.get("priority_score_counts")
        if isinstance(priority_scores, Mapping) and priority_scores:
            scores = ", ".join(
                f"`{score}`={int(count)}"
                for score, count in sorted(priority_scores.items())
            )
            lines.append(f"  Evidence priority scores: {scores}")
        priority_reasons = evidence_status.get("priority_reason_counts")
        if isinstance(priority_reasons, Mapping) and priority_reasons:
            reasons = ", ".join(
                f"`{reason}`={int(count)}"
                for reason, count in sorted(priority_reasons.items())
            )
            lines.append(f"  Evidence priority reasons: {reasons}")
        decision_counts = evidence_status.get("suggested_review_decision_counts")
        if isinstance(decision_counts, Mapping) and decision_counts:
            rendered_fields: list[str] = []
            for field, counts in sorted(decision_counts.items()):
                if not isinstance(counts, Mapping):
                    continue
                rendered_counts = ",".join(
                    f"{bucket}:{int(count)}"
                    for bucket, count in sorted(counts.items())
                )
                rendered_fields.append(f"`{field}`={{{rendered_counts}}}")
            if rendered_fields:
                lines.append(
                    "  Suggested decision counts: " + "; ".join(rendered_fields)
                )
        workload = evidence_status.get("review_field_workload")
        if not isinstance(workload, Mapping) or not workload:
            missing_required = status.get("missing_required_fields")
            suggested_counts = evidence_status.get("suggested_review_decision_counts")
            workload = (
                _review_field_workload(
                    missing_required_fields=missing_required,
                    suggested_review_decision_counts=suggested_counts,
                )
                if isinstance(missing_required, Mapping)
                and isinstance(suggested_counts, Mapping)
                else {}
            )
        if isinstance(workload, Mapping):
            if workload:
                workload_summary = _review_field_workload_summary(workload)
                lines.append(
                    "  Review workload summary: "
                    "missing_required_cells="
                    f"{int(workload_summary.get('missing_required_cells') or 0)}; "
                    "draft_decision_available_cells="
                    f"{int(workload_summary.get('draft_decision_available_cells') or 0)}; "
                    "manual_review_required_cells="
                    f"{int(workload_summary.get('manual_review_required_cells') or 0)}; "
                    "fields_with_manual_review_required="
                    f"{int(workload_summary.get('fields_with_manual_review_required') or 0)}"
                )
                action_order = _review_field_action_order(workload)
                manual_fields = action_order.get("manual_review_required_fields")
                draft_fields = action_order.get("draft_decision_review_fields")
                rendered_manual_fields = (
                    ", ".join(
                        f"`{item.get('field')}`="
                        f"{int(item.get('manual_decision_required_rows') or 0)}"
                        for item in manual_fields
                        if isinstance(item, Mapping)
                    )
                    if isinstance(manual_fields, Sequence)
                    else ""
                )
                rendered_draft_fields = (
                    ", ".join(
                        f"`{item.get('field')}`="
                        f"{int(item.get('draft_decision_available_rows') or 0)}"
                        for item in draft_fields
                        if isinstance(item, Mapping)
                    )
                    if isinstance(draft_fields, Sequence)
                    else ""
                )
                if rendered_manual_fields or rendered_draft_fields:
                    lines.append(
                        "  Review next fields: "
                        f"manual_required: {rendered_manual_fields or 'none'}; "
                        f"draft_available: {rendered_draft_fields or 'none'}"
                    )
                if review_kind:
                    workflow_groups = _review_field_workflow_groups(
                        workload,
                        manual_review_field_contract(review_kind),
                    )

                    def _render_group(group_name: str, count_field: str) -> str:
                        group = workflow_groups.get(group_name)
                        if not isinstance(group, Sequence) or not group:
                            return "none"
                        return ", ".join(
                            f"`{item.get('field')}`="
                            f"{int(item.get(count_field) or 0)}"
                            for item in group
                            if isinstance(item, Mapping)
                        )

                    lines.append(
                        "  Review workflow groups: "
                        "decision: "
                        f"{_render_group('decision_fields_need_review', 'manual_decision_required_rows')}; "
                        "metadata: "
                        f"{_render_group('metadata_fields_need_fill', 'manual_decision_required_rows')}; "
                        f"text: {_render_group('text_fields_need_fill', 'manual_decision_required_rows')}; "
                        "draft_verify: "
                        f"{_render_group('draft_decision_fields_to_verify', 'draft_decision_available_rows')}"
                    )
                rendered_workload: list[str] = []
                for field, item in sorted(workload.items()):
                    if not isinstance(item, Mapping):
                        continue
                    rendered_workload.append(
                        f"`{field}`="
                        f"missing:{int(item.get('missing_required_rows') or 0)},"
                        f"draft:{int(item.get('draft_decision_available_rows') or 0)},"
                        f"manual:{int(item.get('manual_decision_required_rows') or 0)}"
                    )
                if rendered_workload:
                    lines.append(
                        "  Review field workload: " + "; ".join(rendered_workload)
                    )
        evidence_gaps: list[str] = []
        for field in (
            "missing_review_rows",
            "extra_evidence_rows",
            "target_row_hash_mismatch_count",
            "malformed_rows",
            "review_input_malformed_rows",
            "duplicate_review_id_count",
            "duplicate_evidence_id_count",
        ):
            count = int(evidence_status.get(field) or 0)
            if count:
                evidence_gaps.append(f"`{field}`={count}")
        if evidence_gaps:
            lines.append("  Evidence alignment gaps: " + ", ".join(evidence_gaps))
    return lines


def _render_current_batch_coverage_lines(
    label: str,
    gate: ManualReviewGateProgress,
) -> list[str]:
    overview = _compact_batch_overview(gate)
    if not overview or gate.ready_for_promotion:
        return []
    covered_rows = int(overview.get("current_batch_target_covered_rows") or 0)
    pending_rows = int(overview.get("pending_rows") or 0)
    if covered_rows <= 0 or pending_rows <= 0:
        return []
    remaining_rows = int(overview.get("remaining_rows_after_current_batch") or 0)
    covers_next_batch = bool(overview.get("current_batch_covers_next_batch"))
    lines = [
        (
            f"- {label} coverage: current scratch covers {covered_rows}/"
            f"{pending_rows} pending target rows; remaining after current apply: "
            f"{remaining_rows}; covers planned next batch: "
            f"{str(covers_next_batch).lower()}"
        )
    ]
    quality_focus = overview.get("current_batch_quality_gap_review_focus")
    rendered_quality_focus = _render_quality_gap_review_focus(quality_focus)
    if rendered_quality_focus:
        lines.append(f"- {label} quality-gap review focus: {rendered_quality_focus}")
    return lines


def _render_quality_gap_review_focus(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    items = value.get("items")
    if not isinstance(items, Sequence) or isinstance(items, str):
        return ""
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        metric = str(item.get("metric") or "").strip()
        field = str(item.get("field") or "").strip()
        if not metric or not field:
            continue
        rendered.append(
            f"`{metric}`->`{field}` "
            f"manual={int(item.get('manual_decision_required_rows') or 0)},"
            f"draft={int(item.get('draft_decision_available_rows') or 0)},"
            f"focus={int(item.get('evidence_focus_rows') or 0)}"
        )
    return "; ".join(rendered)


def _render_batch_plan_lines(label: str, batch_plan: Sequence[Mapping[str, Any]]) -> list[str]:
    if not batch_plan:
        return [f"- {label}: no pending review batches."]
    lines = [f"### {label}", ""]
    for batch in batch_plan:
        commands = batch.get("commands")
        command_map = commands if isinstance(commands, Mapping) else {}
        lines.extend(
            [
                (
                    f"- Batch {batch.get('batch_index')}: pending rows "
                    f"{batch.get('pending_row_start')}-{batch.get('pending_row_end')}; "
                    f"limit={batch.get('limit')}; offset={batch.get('offset')}; "
                    f"batch input=`{batch.get('batch_input_path')}`; "
                    f"promotion input=`{batch.get('promotion_input_path')}`"
                ),
            ]
        )
        for command_name in (
            "assist",
            "evidence",
            "prepare",
            "backfill_dry_run",
            "backfill_write",
            "dry_run",
            "apply",
        ):
            command = command_map.get(command_name)
            if str(command or "").strip():
                lines.append(f"  - {command_name}: `{command}`")
    return lines


def _render_contract_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_contract_list(values: Any) -> str:
    if not isinstance(values, Sequence) or isinstance(values, str):
        return "none"
    items = [_render_contract_value(item) for item in values]
    if not items:
        return "none"
    return ", ".join(f"`{item}`" for item in items)


def _render_contract_mapping(values: Any) -> str:
    if not isinstance(values, Mapping) or not values:
        return "none"
    return ", ".join(
        f"`{key}`=`{_render_contract_value(value)}`"
        for key, value in sorted(values.items())
    )


def _render_field_contract_lines(
    title: str,
    contract: Mapping[str, Any],
) -> list[str]:
    if not contract:
        return []
    lines = [f"### {title}", ""]
    policy = str(contract.get("policy") or "").strip()
    if policy:
        lines.append(f"- Policy: `{policy}`")
    lines.extend(
        [
            f"- Required fields: {_render_contract_list(contract.get('required_fields'))}",
            f"- Optional fields: {_render_contract_list(contract.get('optional_fields'))}",
            f"- Boolean fields: {_render_contract_list(contract.get('boolean_fields'))}",
            f"- Boolean allowed values: {_render_contract_list(contract.get('boolean_allowed_values'))}",
            f"- Date fields: {_render_contract_mapping(contract.get('date_fields'))}",
            f"- Text fields: {_render_contract_list(contract.get('text_fields'))}",
            f"- Numeric fields: {_render_contract_list(contract.get('numeric_fields'))}",
            f"- Allowed results: {_render_contract_list(contract.get('allowed_results'))}",
            f"- Preserve fields: {_render_contract_list(contract.get('preserve_fields'))}",
            "",
        ]
    )
    return lines


def _promotion_dry_run_command(source_license: ManualReviewGateProgress) -> str:
    if source_license.ready_for_promotion:
        return operator_command(
            "mosaic-rke promotion-dry-run --root . "
            f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
            f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
            f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
        )
    return operator_command(
        "mosaic-rke build-license-review-import --root . "
        f"--policy {SOURCE_LICENSE_REVIEWED_POLICY_PATH} "
        f"--output {DEFAULT_LICENSE_POLICY_IMPORT_PATH} && "
        "mosaic-rke promotion-dry-run --root . "
        f"--gold-input {GOLD_FULL_REVIEWED_IMPORT_PATH} "
        f"--footprint-input {ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH} "
        f"--license-input {DEFAULT_LICENSE_POLICY_IMPORT_PATH} "
        f"--lockbox-input {LOCKBOX_REVIEWED_IMPORT_PATH}"
    )


def build_manual_review_progress(root: str | Path = ".") -> ManualReviewProgressReport:
    root_path = Path(root)
    gates = (
        _gold_progress(root_path),
        _footprint_review_progress(root_path),
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


def _manual_review_progress_report_payload(
    report: ManualReviewProgressReport,
) -> Mapping[str, Any]:
    payload = _jsonable(report)
    gates = payload.get("gates") if isinstance(payload, Mapping) else None
    if isinstance(gates, list):
        for gate_payload, gate in zip(gates, report.gates, strict=False):
            if isinstance(gate_payload, dict):
                gate_payload["batch_overview"] = _compact_batch_overview(gate)
    return payload


def write_manual_review_progress_report(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    report = build_manual_review_progress(root_path)
    result = _write_json(
        root_path / MANUAL_REVIEW_PROGRESS_REPORT_PATH,
        _manual_review_progress_report_payload(report),
    )
    return {
        "path": str(result["path"]),
        "ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "blocker_count": len(report.blockers),
    }


def _compact_current_batch_status(status: Mapping[str, Any]) -> Mapping[str, Any]:
    if not status:
        return {}
    compact: dict[str, Any] = {
        "path": status.get("path"),
        "exists": bool(status.get("exists")),
        "rows": int(status.get("rows") or 0),
        "complete_rows": int(status.get("complete_rows") or 0),
        "pending_rows": int(status.get("pending_rows") or 0),
        "malformed_rows": int(status.get("malformed_rows") or 0),
    }
    for field_name in ("missing_required_fields", "invalid_required_fields"):
        value = status.get(field_name)
        if isinstance(value, Mapping) and value:
            compact[field_name] = {
                str(key): int(count) for key, count in sorted(value.items())
            }
    evidence_status = status.get("evidence_status")
    if isinstance(evidence_status, Mapping) and evidence_status:
        compact["evidence_status"] = {
            "path": evidence_status.get("path"),
            "exists": bool(evidence_status.get("exists")),
            "rows": int(evidence_status.get("rows") or 0),
            "covered_review_rows": int(
                evidence_status.get("covered_review_rows") or 0
            ),
            "review_input_rows": int(evidence_status.get("review_input_rows") or 0),
            "same_order": bool(evidence_status.get("same_order")),
            "aligned": bool(evidence_status.get("aligned")),
            "missing_review_rows": int(
                evidence_status.get("missing_review_rows") or 0
            ),
            "extra_evidence_rows": int(
                evidence_status.get("extra_evidence_rows") or 0
            ),
            "target_row_hash_mismatch_count": int(
                evidence_status.get("target_row_hash_mismatch_count") or 0
            ),
            "missing_markdown_rows": int(
                evidence_status.get("missing_markdown_rows") or 0
            ),
            "snippet_ready_rows": int(evidence_status.get("snippet_ready_rows") or 0),
            "priority_reason_ready_rows": int(
                evidence_status.get("priority_reason_ready_rows") or 0
            ),
            "priority_reason_missing_rows": int(
                evidence_status.get("priority_reason_missing_rows") or 0
            ),
            "priority_metadata_refresh_recommended": bool(
                evidence_status.get("priority_metadata_refresh_recommended")
            ),
        }
        for field_name in (
            "quality_gap_focus_field_counts",
            "suggested_tag_counts",
            "priority_score_counts",
            "priority_reason_counts",
            "suggested_review_decision_counts",
        ):
            value = evidence_status.get(field_name)
            if isinstance(value, Mapping) and value:
                if field_name == "suggested_review_decision_counts":
                    compact["evidence_status"][field_name] = {
                        str(field): {
                            str(bucket): int(count)
                            for bucket, count in sorted(counts.items())
                        }
                        for field, counts in sorted(value.items())
                        if isinstance(counts, Mapping)
                    }
                else:
                    compact["evidence_status"][field_name] = {
                        str(key): int(count) for key, count in sorted(value.items())
                    }
        workload = evidence_status.get("review_field_workload")
        if isinstance(workload, Mapping) and workload:
            compact["review_field_workload"] = {
                str(field): {
                    str(key): int(count)
                    for key, count in sorted(item.items())
                }
                for field, item in sorted(workload.items())
                if isinstance(item, Mapping)
            }
            compact["review_field_workload_summary"] = _review_field_workload_summary(
                compact["review_field_workload"]
            )
            compact["review_field_action_order"] = _review_field_action_order(
                compact["review_field_workload"]
            )
        else:
            missing_required = status.get("missing_required_fields")
            suggested_counts = compact["evidence_status"].get(
                "suggested_review_decision_counts"
            )
            if isinstance(missing_required, Mapping) and isinstance(
                suggested_counts,
                Mapping,
            ):
                fallback_workload = _review_field_workload(
                    missing_required_fields=missing_required,
                    suggested_review_decision_counts=suggested_counts,
                )
                if fallback_workload:
                    compact["review_field_workload"] = fallback_workload
                    compact["review_field_workload_summary"] = (
                        _review_field_workload_summary(fallback_workload)
                    )
                    compact["review_field_action_order"] = (
                        _review_field_action_order(fallback_workload)
                    )
    target_status = status.get("target_status")
    if isinstance(target_status, Mapping) and target_status:
        compact["target_status"] = {
            "target_path": target_status.get("target_path"),
            "exists": bool(target_status.get("exists")),
            "review_input_rows": int(target_status.get("review_input_rows") or 0),
            "target_rows": int(target_status.get("target_rows") or 0),
            "missing_target_rows": int(target_status.get("missing_target_rows") or 0),
            "target_row_hash_mismatch_count": int(
                target_status.get("target_row_hash_mismatch_count") or 0
            ),
            "malformed_rows": int(target_status.get("malformed_rows") or 0),
            "target_malformed_rows": int(
                target_status.get("target_malformed_rows") or 0
            ),
            "aligned": bool(target_status.get("aligned")),
        }
    backfill_status = status.get("backfill_status")
    if isinstance(backfill_status, Mapping) and backfill_status:
        blocker_reason_counts = backfill_status.get("blocker_reason_counts")
        compact["backfill_status"] = {
            "available": bool(backfill_status.get("available")),
            "write_command_available": bool(
                backfill_status.get("write_command_available")
            ),
            "row_count": int(backfill_status.get("row_count") or 0),
            "matched_prior_rows": int(
                backfill_status.get("matched_prior_rows") or 0
            ),
            "updated_rows": int(backfill_status.get("updated_rows") or 0),
            "copied_field_count": int(
                backfill_status.get("copied_field_count") or 0
            ),
            "preserved_existing_field_count": int(
                backfill_status.get("preserved_existing_field_count") or 0
            ),
            "complete_after_backfill_rows": int(
                backfill_status.get("complete_after_backfill_rows") or 0
            ),
            "blocker_count": int(backfill_status.get("blocker_count") or 0),
            "blocker_reason_counts": (
                {
                    str(key): int(count)
                    for key, count in sorted(blocker_reason_counts.items())
                }
                if isinstance(blocker_reason_counts, Mapping)
                else {}
            ),
        }
    return compact


def _current_batch_stale_after_promotion_ready(
    gate: ManualReviewGateProgress,
) -> bool:
    current = (
        gate.current_batch_status
        if isinstance(gate.current_batch_status, Mapping)
        else {}
    )
    return (
        gate.ready_for_promotion
        and bool(current.get("exists"))
        and int(current.get("pending_rows") or 0) > 0
    )


def _compact_batch_overview(gate: ManualReviewGateProgress) -> Mapping[str, Any]:
    if gate.review_kind not in {"gold_set", "footprint_review"}:
        return {}
    current = _compact_current_batch_status(gate.current_batch_status)
    stale_current_batch = _current_batch_stale_after_promotion_ready(gate)
    if gate.ready_for_promotion:
        return {
            "batch_count": 0,
            "pending_rows": 0,
            "promotion_input_path": gate.input_path,
            "current_batch_stale_after_promotion_ready": stale_current_batch,
            "stale_current_batch_path": (
                str(current.get("path") or "") if stale_current_batch else ""
            ),
            "stale_current_batch_pending_rows": (
                int(current.get("pending_rows") or 0) if stale_current_batch else 0
            ),
            "rerun_review_progress_after_batch_apply": False,
        }
    batches = tuple(
        batch for batch in gate.batch_plan if isinstance(batch, Mapping)
    )
    evidence = (
        current.get("evidence_status")
        if isinstance(current.get("evidence_status"), Mapping)
        else {}
    )
    target = (
        current.get("target_status")
        if isinstance(current.get("target_status"), Mapping)
        else {}
    )
    current_batch_target_covered_rows = 0
    if (
        bool(current.get("exists"))
        and int(current.get("malformed_rows") or 0) == 0
        and target
        and bool(target.get("aligned"))
    ):
        current_batch_target_covered_rows = int(current.get("rows") or 0)
    overview: dict[str, Any] = {
        "batch_count": len(batches),
        "pending_rows": gate.pending_rows,
        "current_batch_path": current.get("path"),
        "current_batch_rows": int(current.get("rows") or 0),
        "current_batch_pending_rows": int(current.get("pending_rows") or 0),
        "current_batch_target_covered_rows": current_batch_target_covered_rows,
        "remaining_rows_after_current_batch": max(
            int(gate.pending_rows) - current_batch_target_covered_rows,
            0,
        ),
        "current_batch_evidence_aligned": (
            bool(evidence.get("aligned")) if evidence else None
        ),
        "current_batch_target_aligned": (
            bool(target.get("aligned")) if target else None
        ),
        "current_batch_target_hash_mismatch_count": (
            int(target.get("target_row_hash_mismatch_count") or 0) if target else 0
        ),
        "current_batch_evidence_path": (
            str(evidence.get("path") or "") if evidence else ""
        ),
        "current_batch_evidence_missing_markdown_rows": (
            int(evidence.get("missing_markdown_rows") or 0) if evidence else 0
        ),
        "current_batch_evidence_snippet_ready_rows": (
            int(evidence.get("snippet_ready_rows") or 0) if evidence else 0
        ),
        "current_batch_evidence_priority_reason_ready_rows": (
            int(evidence.get("priority_reason_ready_rows") or 0) if evidence else 0
        ),
        "current_batch_evidence_priority_reason_missing_rows": (
            int(evidence.get("priority_reason_missing_rows") or 0) if evidence else 0
        ),
        "current_batch_evidence_priority_metadata_refresh_recommended": (
            bool(evidence.get("priority_metadata_refresh_recommended"))
            if evidence
            else False
        ),
        "rerun_review_progress_after_batch_apply": True,
    }
    review_field_workload = current.get("review_field_workload")
    if isinstance(review_field_workload, Mapping) and review_field_workload:
        overview["current_batch_review_field_workload"] = {
            str(field): {
                str(key): int(count)
                for key, count in sorted(item.items())
            }
            for field, item in sorted(review_field_workload.items())
            if isinstance(item, Mapping)
        }
        workload_summary = current.get("review_field_workload_summary")
        overview["current_batch_review_field_workload_summary"] = (
            {
                str(key): int(value)
                for key, value in sorted(workload_summary.items())
            }
            if isinstance(workload_summary, Mapping) and workload_summary
            else _review_field_workload_summary(
                overview["current_batch_review_field_workload"]
            )
        )
        action_order = current.get("review_field_action_order")
        overview["current_batch_review_field_action_order"] = (
            action_order
            if isinstance(action_order, Mapping) and action_order
            else _review_field_action_order(
                overview["current_batch_review_field_workload"]
            )
        )
        overview["current_batch_review_field_workflow_groups"] = (
            _review_field_workflow_groups(
                overview["current_batch_review_field_workload"],
                _review_field_contract(gate),
            )
        )
    for field_name in (
        "quality_gap_focus_field_counts",
        "suggested_tag_counts",
        "priority_score_counts",
        "priority_reason_counts",
        "suggested_review_decision_counts",
    ):
        value = evidence.get(field_name) if evidence else None
        if isinstance(value, Mapping) and value:
            if field_name == "suggested_review_decision_counts":
                overview[f"current_batch_evidence_{field_name}"] = {
                    str(field): {
                        str(bucket): int(count)
                        for bucket, count in sorted(counts.items())
                    }
                    for field, counts in sorted(value.items())
                    if isinstance(counts, Mapping)
                }
            else:
                overview[f"current_batch_evidence_{field_name}"] = {
                    str(key): int(count) for key, count in sorted(value.items())
                }
    quality_focus = _quality_gap_review_focus(
        review_kind=gate.review_kind,
        quality_gap_targets=gate.quality_gap_targets,
        evidence_status=evidence,
        workload=overview.get("current_batch_review_field_workload", {}),
    )
    if quality_focus:
        overview["current_batch_quality_gap_review_focus"] = quality_focus
    if batches:
        first = batches[0]
        last = batches[-1]
        first_limit = int(first.get("limit") or 0)
        overview.update(
            {
                "next_batch_offset": int(first.get("offset") or 0),
                "next_batch_limit": first_limit,
                "next_batch_pending_row_start": int(
                    first.get("pending_row_start") or 0
                ),
                "next_batch_pending_row_end": int(first.get("pending_row_end") or 0),
                "final_batch_offset": int(last.get("offset") or 0),
                "final_batch_limit": int(last.get("limit") or 0),
                "remaining_rows_after_next_batch": max(
                    int(gate.pending_rows) - first_limit,
                    0,
                ),
                "current_batch_covers_next_batch": (
                    current_batch_target_covered_rows >= first_limit
                    if first_limit
                    else False
                ),
            }
        )
    return overview


def _review_aid_paths(gate: ManualReviewGateProgress) -> Mapping[str, Any]:
    return manual_review_aid_paths(gate.review_kind)


def _review_field_contract(gate: ManualReviewGateProgress) -> Mapping[str, Any]:
    return manual_review_field_contract(gate.review_kind)


def _compact_quality_gap_targets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact_quality_gap_targets(item)
            for key, item in value.items()
            if str(key) != "policy"
        }
    if isinstance(value, tuple):
        return tuple(_compact_quality_gap_targets(item) for item in value)
    if isinstance(value, list):
        return [_compact_quality_gap_targets(item) for item in value]
    return value


def _lockbox_dependency_blockers(
    gate: ManualReviewGateProgress,
    gates: Sequence[ManualReviewGateProgress],
) -> tuple[ReviewProgressKind, ...]:
    if gate.review_kind != "lockbox":
        return ()
    dependency_order: tuple[ReviewProgressKind, ...] = (
        "gold_set",
        "footprint_review",
        "source_license",
    )
    gate_by_kind = {item.review_kind: item for item in gates}
    return tuple(
        review_kind
        for review_kind in dependency_order
        if not gate_by_kind.get(review_kind, gate).ready_for_promotion
    )


def _next_manual_action(
    gate: ManualReviewGateProgress,
    *,
    dependency_blockers: Sequence[ReviewProgressKind] = (),
) -> str:
    current = (
        gate.current_batch_status
        if isinstance(gate.current_batch_status, Mapping)
        else {}
    )
    if gate.ready_for_promotion:
        if current.get("already_applied") is True:
            return "already_applied"
        return "ready_for_promotion_apply"
    if gate.review_kind == "source_license":
        return "review_or_apply_source_license_policy"
    if gate.review_kind == "lockbox":
        if dependency_blockers:
            return "wait_for_prior_manual_gates"
        if current.get("exists"):
            return "complete_lockbox_decision_then_dry_run"
        return "prepare_lockbox_review"
    if (
        gate.pending_rows == 0
        and gate.blockers
        and int(current.get("pending_rows") or 0) == 0
    ):
        return "address_quality_gate_blockers"
    target = current.get("target_status")
    if (
        current.get("exists")
        and isinstance(target, Mapping)
        and target.get("exists")
        and int(target.get("review_input_rows") or 0) > 0
        and not bool(target.get("aligned"))
    ):
        return "prepare_next_review_batch"
    if current.get("exists") and int(current.get("pending_rows") or 0) > 0:
        evidence = current.get("evidence_status")
        if isinstance(evidence, Mapping) and not bool(evidence.get("aligned")):
            return "repair_current_batch_evidence_alignment"
        return "fill_current_batch_review_fields_then_dry_run"
    if gate.next_batch_commands:
        return "prepare_next_review_batch"
    return "run_prepare_command"


def build_manual_review_progress_summary(
    report: ManualReviewProgressReport,
    *,
    path: str = MANUAL_REVIEW_PROGRESS_REPORT_PATH,
    runbook_path: str = MANUAL_REVIEW_RUNBOOK_MD_PATH,
    review_kinds: Sequence[ReviewProgressKind] | None = None,
) -> Mapping[str, Any]:
    """Return a public-safe compact progress view for operator CLI use."""
    requested_kinds = tuple(review_kinds or ())
    requested_kind_set = set(requested_kinds)
    selected_gates = tuple(
        gate
        for gate in report.gates
        if not requested_kind_set or gate.review_kind in requested_kind_set
    )
    selected_ready_for_promotion = bool(selected_gates) and all(
        gate.ready_for_promotion for gate in selected_gates
    )
    selected_blockers: list[str] = []
    gate_summaries: list[Mapping[str, Any]] = []
    for gate in selected_gates:
        dependency_blockers = _lockbox_dependency_blockers(gate, report.gates)
        next_manual_action = _next_manual_action(
            gate,
            dependency_blockers=dependency_blockers,
        )
        batch_overview = _compact_batch_overview(gate)
        if not gate.ready_for_promotion:
            selected_blockers.append(
                f"{gate.review_kind}: {gate.complete_rows}/{gate.target_rows} ready"
            )
            selected_blockers.extend(
                f"{gate.review_kind}: {blocker}" for blocker in gate.blockers
            )
        gate_summaries.append(
            {
                "review_kind": gate.review_kind,
                "input_path": gate.input_path,
                "input_exists": gate.input_exists,
                "target_rows": gate.target_rows,
                "input_rows": gate.input_rows,
                "complete_rows": gate.complete_rows,
                "pending_rows": gate.pending_rows,
                "simulation_accepted": gate.simulation_accepted,
                "ready_for_promotion": gate.ready_for_promotion,
                "blocker_count": len(gate.blockers),
                "next_manual_action": next_manual_action,
                "blocked_by_review_kinds": list(dependency_blockers),
                "current_batch_status": _compact_current_batch_status(
                    gate.current_batch_status
                ),
                "batch_overview": batch_overview,
                "review_aids": _review_aid_paths(gate),
                "field_contract": _review_field_contract(gate),
                "quality_gap_targets": _compact_quality_gap_targets(
                    gate.quality_gap_targets
                ),
                "next_batch_commands": _summary_next_batch_commands(
                    gate,
                    next_manual_action=next_manual_action,
                    batch_overview=batch_overview,
                ),
                "promotion_commands": {
                    "prepare": gate.prepare_command,
                    "dry_run": gate.dry_run_command,
                    "apply": gate.apply_command,
                },
            }
        )
    return {
        "path": path,
        "runbook_path": runbook_path,
        "ready_for_promotion_dry_run": selected_ready_for_promotion,
        "total_ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "blocker_count": len(_dedupe(selected_blockers)),
        "gate_count": len(selected_gates),
        "total_gate_count": len(report.gates),
        "reported_review_kinds": [gate.review_kind for gate in selected_gates],
        "gates": gate_summaries,
    }


def _current_batch_evidence_command(
    gate: ManualReviewGateProgress,
    batch_overview: Mapping[str, Any],
) -> str:
    current_batch_rows = int(
        batch_overview.get("current_batch_target_covered_rows") or 0
    )
    if current_batch_rows <= 0:
        return ""
    if gate.review_kind == "gold_set":
        return operator_command(
            "mosaic-rke write-gold-review-evidence --root . "
            f"--limit {current_batch_rows} --offset 0 "
            f"--review-input {GOLD_REVIEWED_IMPORT_PATH}"
        )
    if gate.review_kind == "footprint_review":
        return operator_command(
            "mosaic-rke write-footprint-review-evidence --root . "
            f"--limit {current_batch_rows} --offset 0 "
            f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
        )
    return ""


def _summary_next_batch_commands(
    gate: ManualReviewGateProgress,
    *,
    next_manual_action: str,
    batch_overview: Mapping[str, Any],
) -> dict[str, str]:
    commands = _apply_backfill_command_policy(gate, gate.next_batch_commands)
    if next_manual_action in {
        "fill_current_batch_review_fields_then_dry_run",
        "repair_current_batch_evidence_alignment",
    }:
        evidence_command = _current_batch_evidence_command(gate, batch_overview)
        if evidence_command:
            commands["evidence"] = evidence_command
    return commands


def _backfill_write_command_available(gate: ManualReviewGateProgress) -> bool:
    if gate.review_kind != "gold_set":
        return True
    current = (
        gate.current_batch_status
        if isinstance(gate.current_batch_status, Mapping)
        else {}
    )
    backfill_status = current.get("backfill_status")
    if not isinstance(backfill_status, Mapping):
        return True
    return bool(backfill_status.get("write_command_available"))


def _apply_backfill_command_policy(
    gate: ManualReviewGateProgress,
    commands: Mapping[str, str],
) -> dict[str, str]:
    out = dict(commands)
    if gate.review_kind == "gold_set" and not _backfill_write_command_available(gate):
        out.pop("backfill_write", None)
    return out


def _action_queue_commands(
    gate: ManualReviewGateProgress,
    action: str,
    *,
    batch_overview: Mapping[str, Any] | None = None,
) -> Mapping[str, str]:
    next_batch = dict(gate.next_batch_commands)
    if action == "ready_for_promotion_apply":
        return {
            "dry_run": gate.dry_run_command,
            "apply": gate.apply_command,
        }
    if action == "fill_current_batch_review_fields_then_dry_run":
        commands = {
            key: command
            for key, command in next_batch.items()
            if key in {"assist", "evidence", "backfill_dry_run", "backfill_write", "dry_run"}
        }
        evidence_command = _current_batch_evidence_command(
            gate,
            batch_overview or {},
        )
        if evidence_command:
            commands["evidence"] = evidence_command
        return _apply_backfill_command_policy(gate, commands)
    if action == "repair_current_batch_evidence_alignment":
        commands = {
            key: command
            for key, command in next_batch.items()
            if key in {"assist", "evidence"}
        }
        evidence_command = _current_batch_evidence_command(
            gate,
            batch_overview or {},
        )
        if evidence_command:
            commands["evidence"] = evidence_command
        return commands
    if action == "prepare_next_review_batch":
        return {
            key: command
            for key, command in next_batch.items()
            if key in {"assist", "prepare", "evidence"}
        }
    if action == "address_quality_gate_blockers":
        commands = {
            key: command
            for key, command in next_batch.items()
            if key
            in {
                "assist",
                "refresh_source_candidates",
                "expand_candidate_review_rows",
                "prepare_reviewed_failures",
                "prepare_expanded_batch",
                "evidence",
                "backfill_dry_run",
                "backfill_write",
                "dry_run",
            }
        }
        return _apply_backfill_command_policy(gate, commands)
    if action == "run_prepare_command":
        return {"prepare": gate.prepare_command}
    if action == "review_or_apply_source_license_policy":
        return {
            "prepare": gate.prepare_command,
            "dry_run": gate.dry_run_command,
        }
    if action == "complete_lockbox_decision_then_dry_run":
        return {
            "prepare": gate.prepare_command,
            "dry_run": gate.dry_run_command,
        }
    if action == "prepare_lockbox_review":
        return {"prepare": gate.prepare_command}
    return {}


def _post_current_batch_action(
    action: str,
    batch_overview: Mapping[str, Any],
) -> str:
    if action != "fill_current_batch_review_fields_then_dry_run":
        return ""
    covered_rows = int(batch_overview.get("current_batch_target_covered_rows") or 0)
    if covered_rows <= 0:
        return ""
    remaining_rows = int(batch_overview.get("remaining_rows_after_current_batch") or 0)
    if remaining_rows > 0:
        return "apply_current_batch_then_rerun_review_progress"
    return "apply_current_batch_then_prepare_promotion_import"


def _after_dry_run_accepts_commands(
    gate: ManualReviewGateProgress,
    action: str,
    batch_overview: Mapping[str, Any],
) -> Mapping[str, str]:
    if action != "fill_current_batch_review_fields_then_dry_run":
        return {}
    apply_command = str(gate.next_batch_commands.get("apply") or "").strip()
    if not apply_command:
        return {}
    commands: dict[str, str] = {
        "apply_current_batch": apply_command,
        "rerun_review_progress": operator_command(
            "mosaic-rke review-progress --root . --actions-only --no-write "
            f"--review-kind {gate.review_kind}"
        ),
        "schema_after_review": operator_command(
            "mosaic-rke schema-status --root . --failures-only --no-write"
        ),
    }
    remaining_rows = int(batch_overview.get("remaining_rows_after_current_batch") or 0)
    if remaining_rows > 0:
        prepare_command = str(gate.next_batch_commands.get("prepare") or "").strip()
        if prepare_command:
            commands["prepare_next_batch_after_rerun"] = prepare_command
    else:
        commands["prepare_promotion_import_after_rerun"] = gate.prepare_command
    return commands


def _action_queue_hint(
    action: str,
    *,
    batch_overview: Mapping[str, Any] | None = None,
) -> str:
    hints = {
        "ready_for_promotion_apply": "Gate is ready; run dry-run, then apply if accepted.",
        "already_applied": "Gate is already applied; no operator action is required.",
        "fill_current_batch_review_fields_then_dry_run": (
            "Fill the current reviewed scratch fields, regenerate/check evidence, "
            "then run the dry-run."
        ),
        "repair_current_batch_evidence_alignment": (
            "Regenerate evidence for the current scratch batch before review."
        ),
        "prepare_next_review_batch": "Prepare the next review batch before filling fields.",
        "address_quality_gate_blockers": (
            "No pending rows remain; re-review failed gold labels or refresh the gold "
            "candidate set to expand document coverage."
        ),
        "run_prepare_command": "Run the prepare command to create the review input.",
        "review_or_apply_source_license_policy": (
            "Review the source-license policy, build the import, then dry-run/apply."
        ),
        "wait_for_prior_manual_gates": (
            "Wait until listed upstream manual gates are ready."
        ),
        "complete_lockbox_decision_then_dry_run": (
            "Fill the lockbox decision only after upstream gates are ready."
        ),
        "prepare_lockbox_review": "Prepare the lockbox review after upstream gates pass.",
    }
    hint = hints.get(action, "Inspect gate blockers before proceeding.")
    if action != "fill_current_batch_review_fields_then_dry_run":
        return hint
    overview = batch_overview if isinstance(batch_overview, Mapping) else {}
    covered_rows = int(overview.get("current_batch_target_covered_rows") or 0)
    pending_rows = int(overview.get("pending_rows") or 0)
    remaining_rows = int(overview.get("remaining_rows_after_current_batch") or 0)
    priority_missing_rows = int(
        overview.get("current_batch_evidence_priority_reason_missing_rows") or 0
    )
    priority_hint = (
        f" Regenerate evidence first to populate priority reason metadata for "
        f"{priority_missing_rows} rows."
        if priority_missing_rows > 0
        else ""
    )
    if covered_rows <= 0 or pending_rows <= 0:
        return f"{hint}{priority_hint}"
    if remaining_rows > 0:
        return (
            f"{hint} Current scratch covers {covered_rows} of {pending_rows} "
            f"pending target rows; after applying it, rerun review-progress and "
            f"prepare the remaining {remaining_rows} rows.{priority_hint}"
        )
    return (
        f"{hint} Current scratch covers all {pending_rows} pending target rows; "
        f"after applying it, rerun review-progress and prepare the promotion import.{priority_hint}"
    )


def _action_queue_state(action: str) -> str:
    states = {
        "ready_for_promotion_apply": "ready_to_apply",
        "already_applied": "already_applied",
        "fill_current_batch_review_fields_then_dry_run": "needs_human_review_fields",
        "repair_current_batch_evidence_alignment": "needs_evidence_repair",
        "prepare_next_review_batch": "needs_prepare",
        "address_quality_gate_blockers": "needs_quality_gate_work",
        "run_prepare_command": "needs_prepare",
        "review_or_apply_source_license_policy": "needs_policy_review",
        "wait_for_prior_manual_gates": "waiting_on_dependencies",
        "complete_lockbox_decision_then_dry_run": "needs_lockbox_decision",
        "prepare_lockbox_review": "needs_prepare",
    }
    return states.get(action, "needs_operator_inspection")


def _action_queue_can_run_now(
    action_state: str,
    *,
    dependency_blockers: Sequence[ReviewProgressKind],
) -> bool:
    if dependency_blockers:
        return False
    return action_state in {
        "ready_to_apply",
        "needs_human_review_fields",
        "needs_evidence_repair",
        "needs_prepare",
        "needs_policy_review",
        "needs_quality_gate_work",
        "needs_lockbox_decision",
    }


def build_manual_review_action_queue(
    report: ManualReviewProgressReport,
    *,
    path: str = MANUAL_REVIEW_PROGRESS_REPORT_PATH,
    runbook_path: str = MANUAL_REVIEW_RUNBOOK_MD_PATH,
    review_kinds: Sequence[ReviewProgressKind] | None = None,
    action_states: Sequence[str] | None = None,
) -> Mapping[str, Any]:
    """Return the next public-safe operator actions without full gate payloads."""
    requested_kinds = tuple(review_kinds or ())
    requested_kind_set = set(requested_kinds)
    requested_states = tuple(str(state) for state in (action_states or ()) if str(state))
    requested_state_set = set(requested_states)
    selected_gates = tuple(
        gate
        for gate in report.gates
        if not requested_kind_set or gate.review_kind in requested_kind_set
    )
    actions: list[Mapping[str, Any]] = []
    for action_rank, gate in enumerate(selected_gates, 1):
        current = (
            gate.current_batch_status
            if isinstance(gate.current_batch_status, Mapping)
            else {}
        )
        evidence = current.get("evidence_status")
        evidence_aligned = (
            bool(evidence.get("aligned")) if isinstance(evidence, Mapping) else None
        )
        dependency_blockers = _lockbox_dependency_blockers(gate, report.gates)
        action = _next_manual_action(
            gate,
            dependency_blockers=dependency_blockers,
        )
        action_state = _action_queue_state(action)
        if requested_state_set and action_state not in requested_state_set:
            continue
        can_run_now = _action_queue_can_run_now(
            action_state,
            dependency_blockers=dependency_blockers,
        )
        current_batch_path = str(current.get("path") or "")
        stale_current_batch = _current_batch_stale_after_promotion_ready(gate)
        active_manual_input_path = (
            gate.input_path
            if gate.ready_for_promotion
            else current_batch_path or gate.input_path
        )
        compact_current_batch_status = _compact_current_batch_status(current)
        batch_overview = _compact_batch_overview(gate)
        actions.append(
            {
                "action_rank": action_rank,
                "review_kind": gate.review_kind,
                "next_manual_action": action,
                "action_state": action_state,
                "can_run_now": can_run_now,
                "blocks_promotion": not gate.ready_for_promotion,
                "operator_hint": _action_queue_hint(
                    action,
                    batch_overview=batch_overview,
                ),
                "post_current_batch_action": _post_current_batch_action(
                    action,
                    batch_overview,
                ),
                "after_dry_run_accepts": dict(
                    _after_dry_run_accepts_commands(
                        gate,
                        action,
                        batch_overview,
                    )
                ),
                "ready_for_promotion": gate.ready_for_promotion,
                "blocked_by_review_kinds": list(dependency_blockers),
                "complete_rows": gate.complete_rows,
                "pending_rows": gate.pending_rows,
                "target_rows": gate.target_rows,
                "manual_input_path": active_manual_input_path,
                "promotion_input_path": gate.input_path,
                "current_batch_path": current_batch_path,
                "current_batch_pending_rows": (
                    0
                    if stale_current_batch
                    else int(current.get("pending_rows") or 0)
                ),
                "current_batch_malformed_rows": int(
                    current.get("malformed_rows") or 0
                ),
                "current_batch_stale_after_promotion_ready": stale_current_batch,
                "batch_overview": batch_overview,
                "backfill_status": compact_current_batch_status.get(
                    "backfill_status",
                    {},
                ),
                "review_aids": _review_aid_paths(gate),
                "field_contract": _review_field_contract(gate),
                "quality_gap_targets": _compact_quality_gap_targets(
                    gate.quality_gap_targets
                ),
                "missing_required_fields": dict(
                    {} if stale_current_batch else current.get("missing_required_fields") or {}
                ),
                "evidence_aligned": None if stale_current_batch else evidence_aligned,
                "commands": dict(
                    _action_queue_commands(
                        gate,
                        action,
                        batch_overview=batch_overview,
                    )
                ),
            }
        )
    selected_ready_for_promotion = bool(actions) and all(
        bool(action.get("ready_for_promotion")) for action in actions
    )
    action_state_counts = {
        state: sum(1 for action in actions if action.get("action_state") == state)
        for state in ACTION_QUEUE_STATES
    }
    return {
        "path": path,
        "runbook_path": runbook_path,
        "ready_for_promotion_dry_run": selected_ready_for_promotion,
        "total_ready_for_promotion_dry_run": report.ready_for_promotion_dry_run,
        "action_count": len(actions),
        "action_state_counts": {
            state: count for state, count in action_state_counts.items() if count
        },
        "total_gate_count": len(report.gates),
        "reported_review_kinds": [str(action["review_kind"]) for action in actions],
        "reported_action_states": list(requested_states),
        "actions": actions,
    }


def render_manual_review_runbook_markdown(report: ManualReviewProgressReport) -> str:
    gate_lookup = {gate.review_kind: gate for gate in report.gates}
    gold = gate_lookup["gold_set"]
    footprint = gate_lookup["footprint_review"]
    source_license = gate_lookup["source_license"]
    lockbox = gate_lookup["lockbox"]
    lockbox_dependency_blockers = _lockbox_dependency_blockers(lockbox, report.gates)
    lockbox_dependency_summary = (
        "ready"
        if not lockbox_dependency_blockers
        else "waiting_on " + ", ".join(lockbox_dependency_blockers)
    )
    lockbox_prepare_line = (
        f"- Lockbox: `{lockbox.prepare_command}`"
        if not lockbox_dependency_blockers
        else (
            f"- Lockbox: wait for upstream gates before running "
            f"`{lockbox.prepare_command}`"
        )
    )
    gold_full_prepare = operator_command(
        "mosaic-rke prepare-gold-review --root . --full --force "
        "--reviewer <name> --review-date <YYYY-MM-DD>"
    )
    gold_batch_prepare = operator_command(
        "mosaic-rke prepare-gold-review --root . --gold-batch-size 50 "
        "--offset 0 --force --reviewer <name> --review-date <YYYY-MM-DD>"
    )
    gold_batch_dry_run = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH} --dry-run"
    )
    gold_batch_apply = operator_command(
        f"mosaic-rke apply-gold-review --root . --input {GOLD_REVIEWED_IMPORT_PATH}"
    )
    gold_next_batch_commands = dict(gold.next_batch_commands)
    gold_evidence = str(
        gold_next_batch_commands.get("evidence")
        or operator_command(_gold_review_evidence_command_text(50))
    )
    footprint_batch_prepare = operator_command(
        "mosaic-rke prepare-footprint-review --root . --limit 50 --offset 0 "
        "--priority --reviewer <name> --review-date <YYYY-MM-DD> --overwrite"
    )
    footprint_batch_dry_run = operator_command(
        "mosaic-rke apply-footprint-review --root . "
        f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH} --dry-run"
    )
    footprint_batch_apply = operator_command(
        "mosaic-rke apply-footprint-review --root . "
        f"--input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
    footprint_assist = operator_command(
        "mosaic-rke write-footprint-review-assist --root . "
        f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
    footprint_evidence = operator_command(
        "mosaic-rke write-footprint-review-evidence --root . --limit 50 --offset 0 "
        f"--review-input {ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH}"
    )
    lines = [
        "# RKE Manual Review Runbook",
        "",
        "This artifact is a read-only operator checklist for the remaining manual RKE gates.",
        "It records paths, commands, row counts, acceptance criteria, and current blockers only.",
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
            "- Analytical-footprint review: "
            f"{footprint.complete_rows}/{footprint.target_rows} complete; "
            f"scratch exists: {str(footprint.input_exists).lower()}; "
            f"simulation accepted: {str(footprint.simulation_accepted).lower()}"
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
        f"- Lockbox dependency status: {lockbox_dependency_summary}",
        "",
        "## Current Batch Scratch",
        "",
        "This section reports aggregate completion counts for the current local batch or decision files only; it does not include source text, claim text, or reviewer notes.",
        *_render_batch_status_lines(
            "Gold-set batch",
            gold.current_batch_status,
            review_kind="gold_set",
        ),
        *_render_current_batch_coverage_lines("Gold-set batch", gold),
        *_render_batch_status_lines(
            "Analytical-footprint batch",
            footprint.current_batch_status,
            review_kind="footprint_review",
        ),
        *_render_current_batch_coverage_lines(
            "Analytical-footprint batch",
            footprint,
        ),
        *_render_batch_status_lines("Lockbox decision", lockbox.current_batch_status),
        "",
        "## Prepare Commands",
        "",
        f"- Temp workspace: `{RKE_OPERATOR_TMP_ENV_PREFIX}` keeps review-progress and promotion dry-run registry copies out of system `/tmp`; generated commands below include this prefix.",
        f"- Gold-set: `{gold.prepare_command}`",
        f"- Analytical-footprint: `{footprint.prepare_command}`",
        f"- Source-license: `{source_license.prepare_command}`",
        lockbox_prepare_line,
        "",
        "## Reviewer Inputs",
        "",
        f"- Gold-set reviewed scratch: `{GOLD_FULL_REVIEWED_IMPORT_PATH}`",
        f"- Analytical-footprint reviewed scratch: `{ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH}`",
        f"- Source-license reviewed policy: `{SOURCE_LICENSE_REVIEWED_POLICY_PATH}`",
        f"- Lockbox reviewed scratch: `{LOCKBOX_REVIEWED_IMPORT_PATH}`",
        "",
        "Reviewed scratch files are operator-local decision files. Do not commit them unless the operator explicitly chooses to publish signed review decisions.",
        "",
        "## Read-Only Checklists",
        "",
        f"- Gold-set workbook: `{GOLD_REVIEW_WORKBOOK_MD_PATH}`",
        f"- Gold-set evidence draft Markdown: `{GOLD_REVIEW_EVIDENCE_MD_PATH}`",
        f"- Gold-set evidence draft JSONL: `{GOLD_REVIEW_EVIDENCE_JSONL_PATH}`",
        "- Gold-set packet JSON: `registry/gold_sets/tushare_research_reports.review_packet.json`",
        "- Gold-set packet Markdown: `registry/gold_sets/tushare_research_reports.review_packet.md`",
        f"- Source-license workbook: `{SOURCE_LICENSE_REVIEW_WORKBOOK_MD_PATH}`",
        "- Source-license packet JSON: `registry/compliance/tushare_license_review_packet.json`",
        "- Source-license packet Markdown: `registry/compliance/tushare_license_review_packet.md`",
        f"- Source-license policy template: `{SOURCE_LICENSE_POLICY_TEMPLATE_PATH}`",
        f"- Analytical-footprint review template: `{ANALYTICAL_FOOTPRINT_REVIEW_TEMPLATE_PATH}`",
        f"- Analytical-footprint review workbook: `{ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH}`",
        f"- Analytical-footprint review assist JSONL: `{ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH}`",
        f"- Analytical-footprint evidence draft Markdown: `{ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH}`",
        f"- Analytical-footprint evidence draft JSONL: `{ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH}`",
        "- Lockbox policy packet: `registry/evaluation/lockbox/lockbox_policy.json`",
        "",
        "These checklist files are not import files. Use them to inspect IDs, hashes, counts, and short previews only.",
        "",
        "## Manual Field Contracts",
        "",
        "These contracts are public-safe field rules for reviewer-edited input files. They do not include source text, claim text, evidence snippets, or reviewer notes.",
        "",
        *_render_field_contract_lines(
            "Gold-set review",
            manual_review_field_contract("gold_set"),
        ),
        *_render_field_contract_lines(
            "Analytical-footprint review",
            manual_review_field_contract("footprint_review"),
        ),
        *_render_field_contract_lines(
            "Source-license review",
            manual_review_field_contract("source_license"),
        ),
        *_render_field_contract_lines(
            "Lockbox review",
            manual_review_field_contract("lockbox"),
        ),
        "## Gate Acceptance Criteria",
        "",
        "Gold-set review is accepted only when all current claim rows are completed and the dry run accepts the import.",
        "Each gold-set row must keep the template IDs and hashes intact and must fill `manual_claim_text`, `reviewer`, `review_date`, `claim_correct`, `source_span_supports_claim`, `direction_correct`, `target_correct`, `horizon_correct`, `variable_mapping_correct`, and `unsupported_field_false_grounded`.",
        f"Use `{gold_full_prepare}` to prefill reviewer identity and date only; claim text and boolean review decisions remain human judgments.",
        f"For batch work, use `{gold_batch_prepare}`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.",
        f"Batch gold-set imports use `{gold_batch_dry_run}`, then `{gold_batch_apply}` after the batch is accepted.",
        f"Use `{gold_evidence}` after preparing the current gold scratch batch to regenerate a batch-aligned private source-evidence draft.",
        "The resulting gold-set summary must satisfy the code-defined gate: at least 50 documents, at least 100 claims, claim precision >= 0.85, span-support precision >= 0.90, direction accuracy >= 0.85, target accuracy >= 0.85, horizon accuracy >= 0.85, variable mapping accuracy >= 0.80, and unsupported-field false grounding <= 0.05.",
        "",
        "Analytical-footprint review is accepted only when every footprint row is completed, the import dry run accepts it, and the review summary quality gate passes.",
        "Each analytical-footprint row must keep target IDs and hashes intact and must fill `reviewer`, `review_date`, `review_notes`, `footprint_correct`, `source_span_supports_footprint`, `metric_mapping_correct`, `inferred_steps_tagged_correctly`, `unknowns_used_when_uncertain`, and `no_proprietary_text_leakage`.",
        f"For batch work, use `{footprint_batch_prepare}`; after applying that batch, rerun with `--offset 0` because completed rows leave the pending set.",
        f"Batch analytical-footprint imports use `{footprint_batch_dry_run}`, then `{footprint_batch_apply}` after the batch is accepted.",
        f"Use `{footprint_assist}` and `{footprint_evidence}` after preparing the current footprint scratch batch to regenerate a batch-aligned private evidence draft.",
        "",
        "Source-license review is accepted only when the reviewed policy expands to all current source rows and both the build step and license import dry run accept it.",
        "The reviewed policy must fill `reviewer`, `review_date`, `approved_for_derived_claim_storage`, and `approved_for_production_runtime`; production promotion requires `approved_for_production_runtime=true` for every matched current source.",
        "The policy must keep `target_review_path`, `review_context_ref`, `matched_row_count`, `matched_rows_fingerprint`, publish-date bounds, and filter scope aligned with the current template; rerun prepare if the source scope changes.",
        "",
        "Lockbox review is accepted only after the final holdout is opened once, the import dry run accepts the signed row, and the lockbox decision allows production.",
        "The lockbox row must fill `opened_at`, `opened_by`, `open_count`, `result`, `parameter_search_after_open`, and `rule_design_after_open`; production requires `result=passed`, `open_count<=1`, no parameter search after open, no rule design after open, and matching target/context hashes.",
        "",
        "A promotion dry run is ready only when all manual gates above report ready for promotion. Missing scratch files, incomplete rows, failed dry runs, or failed quality thresholds keep the system in paper trading.",
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
        f"- Analytical-footprint: `{footprint.dry_run_command}`",
        f"- Source-license: `{source_license.dry_run_command}`",
        f"- Lockbox: `{lockbox.dry_run_command}`",
        "",
        "## Apply Commands",
        "",
        f"- Gold-set: `{gold.apply_command}`",
        f"- Analytical-footprint: `{footprint.apply_command}`",
        f"- Source-license: `{source_license.apply_command}`",
        f"- Lockbox: `{lockbox.apply_command}`",
        "",
        "## Promotion Dry Run",
        "",
        f"`{_promotion_dry_run_command(source_license)}`",
        "",
    ]
    lines.extend(
        [
            "## Full Pending Batch Plan",
            "",
            "This plan slices the current pending set before any new batch is applied. If you apply one accepted batch, rerun `review-progress` and use the refreshed offsets.",
            "",
            *_render_batch_plan_lines("Gold-set review", gold.batch_plan),
            "",
            *_render_batch_plan_lines("Analytical-footprint review", footprint.batch_plan),
            "",
            "## Next Batch Commands",
            "",
            "These commands operate on the current pending set. After applying an accepted batch, rerun review-progress and use the refreshed commands.",
            "",
        ]
    )
    for gate in (gold, footprint):
        if not gate.next_batch_commands:
            continue
        lines.append(f"### {gate.review_kind}")
        lines.append("")
        for command_name, command in gate.next_batch_commands.items():
            lines.append(f"- {command_name}: `{command}`")
        lines.append("")
    lines.extend(["## Current Blockers", ""])
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
