"""Shared manual-review integrity checks for RKE gates."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping


GOLD_REVIEW_FIELDS = (
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "target_correct",
    "horizon_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
)

LICENSE_APPROVAL_FIELDS = (
    "approved_for_derived_claim_storage",
    "approved_for_production_runtime",
)


def required_string_failure(
    row: Mapping[str, Any],
    field: str,
    *,
    label: str,
    row_number: int,
) -> str:
    value = row.get(field)
    if value is None or value == "":
        return f"{label} row {row_number} {field} required"
    if not isinstance(value, str):
        return f"{label} row {row_number} {field} must be string"
    if not value.strip():
        return f"{label} row {row_number} {field} required"
    return ""


def iso_date_failure(
    row: Mapping[str, Any],
    field: str,
    *,
    label: str,
    row_number: int,
) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return f"{label} row {row_number} {field} must be YYYY-MM-DD"
    if parsed.isoformat() != value:
        return f"{label} row {row_number} {field} must be YYYY-MM-DD"
    return ""


def duplicate_values(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def gold_review_row_complete(row: Mapping[str, Any]) -> bool:
    return (
        all(isinstance(row.get(field), bool) for field in GOLD_REVIEW_FIELDS)
        and isinstance(row.get("manual_claim_text"), str)
        and bool(str(row.get("manual_claim_text") or "").strip())
        and isinstance(row.get("reviewer"), str)
        and bool(str(row.get("reviewer") or "").strip())
        and isinstance(row.get("review_date"), str)
        and bool(str(row.get("review_date") or "").strip())
        and not iso_date_failure(
            row,
            "review_date",
            label="gold-set review",
            row_number=1,
        )
    )


def gold_review_integrity_failures(rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    failures: list[str] = []
    claim_ids: list[str] = []
    for index, row in enumerate(rows, 1):
        for field in ("source_id", "source_span_id", "claim_id", "document_id"):
            failure = required_string_failure(
                row,
                field,
                label="gold-set review",
                row_number=index,
            )
            if failure:
                failures.append(failure)
        claim_id = str(row.get("claim_id") or "").strip()
        if claim_id:
            claim_ids.append(claim_id)

        any_review_started = False
        all_review_complete = True
        for field in GOLD_REVIEW_FIELDS:
            value = row.get(field)
            if value is None:
                all_review_complete = False
                continue
            any_review_started = True
            if not isinstance(value, bool):
                all_review_complete = False
                failures.append(f"gold-set review row {index} {field} must be boolean")
        if any_review_started and all_review_complete:
            for field in ("manual_claim_text", "reviewer", "review_date"):
                failure = required_string_failure(
                    row,
                    field,
                    label="gold-set review",
                    row_number=index,
                )
                if failure:
                    failures.append(failure)
            date_failure = iso_date_failure(
                row,
                "review_date",
                label="gold-set review",
                row_number=index,
            )
            if date_failure:
                failures.append(date_failure)
    duplicates = duplicate_values(claim_ids)
    if duplicates:
        failures.append(
            f"gold-set review claim_id duplicated: {', '.join(duplicates[:10])}"
        )
    return tuple(failures)


def license_review_row_complete(row: Mapping[str, Any]) -> bool:
    return (
        all(isinstance(row.get(field), bool) for field in LICENSE_APPROVAL_FIELDS)
        and isinstance(row.get("reviewer"), str)
        and bool(str(row.get("reviewer") or "").strip())
        and isinstance(row.get("review_date"), str)
        and bool(str(row.get("review_date") or "").strip())
        and not iso_date_failure(
            row,
            "review_date",
            label="source license review",
            row_number=1,
        )
    )


def license_review_integrity_failures(
    sources: list[Mapping[str, Any]],
    reviews: list[Mapping[str, Any]],
) -> tuple[str, ...]:
    failures: list[str] = []
    source_ids: list[str] = []
    for index, source in enumerate(sources, 1):
        source_id = str(source.get("source_id") or "").strip()
        if not source_id:
            failures.append(f"source registry row {index} source_id required")
            continue
        source_ids.append(source_id)
    duplicate_source_ids = duplicate_values(source_ids)
    if duplicate_source_ids:
        failures.append(
            "source registry source_id duplicated: "
            + ", ".join(duplicate_source_ids[:10])
        )

    review_ids: list[str] = []
    for index, row in enumerate(reviews, 1):
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            failures.append(f"source license review row {index} source_id required")
        else:
            review_ids.append(source_id)

        review_started = False
        approval_values: dict[str, Any] = {}
        for field in LICENSE_APPROVAL_FIELDS:
            value = row.get(field)
            approval_values[field] = value
            if value is None:
                continue
            review_started = True
            if not isinstance(value, bool):
                failures.append(
                    f"source license review row {index} {field} must be boolean"
                )
        if review_started:
            for field in LICENSE_APPROVAL_FIELDS:
                if approval_values[field] is None:
                    failures.append(
                        f"source license review row {index} {field} required"
                    )
            for field in ("reviewer", "review_date"):
                failure = required_string_failure(
                    row,
                    field,
                    label="source license review",
                    row_number=index,
                )
                if failure:
                    failures.append(failure)
            date_failure = iso_date_failure(
                row,
                "review_date",
                label="source license review",
                row_number=index,
            )
            if date_failure:
                failures.append(date_failure)
            if (
                approval_values.get("approved_for_production_runtime") is True
                and approval_values.get("approved_for_derived_claim_storage")
                is not True
            ):
                failures.append(
                    "source license review row "
                    f"{index} production approval requires derived-claim approval"
                )

    duplicate_review_ids = duplicate_values(review_ids)
    if duplicate_review_ids:
        failures.append(
            "source license review source_id duplicated: "
            + ", ".join(duplicate_review_ids[:10])
        )

    source_id_set = set(source_ids)
    review_id_set = set(review_ids)
    missing_review_ids = tuple(sorted(source_id_set - review_id_set))
    unknown_review_ids = tuple(sorted(review_id_set - source_id_set))
    if missing_review_ids:
        failures.append(
            f"{len(missing_review_ids)} source registry rows missing license review rows"
        )
    if unknown_review_ids:
        failures.append(
            "source license review rows reference unknown source_id: "
            + ", ".join(unknown_review_ids[:10])
        )
    return tuple(failures)
