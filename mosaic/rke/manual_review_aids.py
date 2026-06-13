"""Public-safe manual review aid references for operator-facing commands."""

from __future__ import annotations

from typing import Any, Mapping


def manual_review_aid_paths(review_kind: str) -> Mapping[str, Any]:
    """Return public-safe path references for private review aids."""
    if review_kind == "gold_set":
        return {
            "policy": "private_review_aids_only_not_import_files",
            "fill_import_path": "registry/review_batches/gold_set_reviewed.jsonl",
            "promotion_import_path": (
                "registry/review_batches/gold_set_full_reviewed.jsonl"
            ),
            "assist_jsonl": "registry/review_batches/gold_set_review_assist.jsonl",
            "assist_markdown": "registry/review_batches/gold_set_review_assist.md",
            "evidence_jsonl": (
                "registry/review_batches/gold_set_review_evidence.jsonl"
            ),
            "evidence_markdown": (
                "registry/review_batches/gold_set_review_evidence.md"
            ),
            "batch_workbook_markdown": (
                "registry/review_batches/gold_set_review_workbook.md"
            ),
        }
    if review_kind == "footprint_review":
        return {
            "policy": "private_review_aids_only_not_import_files",
            "fill_import_path": (
                "registry/report_intelligence/"
                "analytical_footprint_review_batch.jsonl"
            ),
            "promotion_import_path": (
                "registry/report_intelligence/analytical_footprint_reviewed.jsonl"
            ),
            "assist_jsonl": (
                "registry/report_intelligence/"
                "analytical_footprint_review_assist.jsonl"
            ),
            "assist_workbook_markdown": (
                "registry/report_intelligence/"
                "analytical_footprint_review_workbook.md"
            ),
            "evidence_jsonl": (
                "registry/report_intelligence/"
                "analytical_footprint_review_evidence.jsonl"
            ),
            "evidence_markdown": (
                "registry/report_intelligence/"
                "analytical_footprint_review_evidence.md"
            ),
        }
    if review_kind == "source_license":
        return {
            "policy": "private_review_aids_only_not_import_files",
            "fill_policy_path": (
                "registry/review_batches/source_license_policy_reviewed.json"
            ),
            "policy_template_path": (
                "registry/review_batches/source_license_policy_template.json"
            ),
            "workbook_markdown": (
                "registry/review_batches/source_license_review_workbook.md"
            ),
        }
    if review_kind == "lockbox":
        return {
            "policy": "wait_for_prior_manual_gates_before_opening",
            "fill_import_path": "registry/review_batches/lockbox_reviewed.json",
        }
    return {}


def manual_review_field_contract(review_kind: str) -> Mapping[str, Any]:
    """Return public-safe manual field contracts for reviewer-edited inputs."""
    if review_kind == "gold_set":
        return {
            "policy": "human_decisions_only_preserve_ids_hashes_and_context_refs",
            "required_fields": [
                "manual_claim_text",
                "claim_correct",
                "source_span_supports_claim",
                "direction_correct",
                "target_correct",
                "horizon_correct",
                "variable_mapping_correct",
                "unsupported_field_false_grounded",
                "reviewer",
                "review_date",
            ],
            "optional_fields": ["review_notes"],
            "boolean_fields": [
                "claim_correct",
                "source_span_supports_claim",
                "direction_correct",
                "target_correct",
                "horizon_correct",
                "variable_mapping_correct",
                "unsupported_field_false_grounded",
            ],
            "boolean_allowed_values": [True, False],
            "date_fields": {"review_date": "YYYY-MM-DD"},
            "text_fields": ["manual_claim_text", "reviewer", "review_notes"],
            "preserve_fields": [
                "claim_id",
                "target_row_hash",
                "review_context_ref",
                "target_review_path",
            ],
        }
    if review_kind == "footprint_review":
        return {
            "policy": "human_decisions_only_preserve_ids_hashes_and_context_refs",
            "required_fields": [
                "footprint_correct",
                "source_span_supports_footprint",
                "metric_mapping_correct",
                "inferred_steps_tagged_correctly",
                "unknowns_used_when_uncertain",
                "no_proprietary_text_leakage",
                "reviewer",
                "review_date",
                "review_notes",
            ],
            "optional_fields": [],
            "boolean_fields": [
                "footprint_correct",
                "source_span_supports_footprint",
                "metric_mapping_correct",
                "inferred_steps_tagged_correctly",
                "unknowns_used_when_uncertain",
                "no_proprietary_text_leakage",
            ],
            "boolean_allowed_values": [True, False],
            "date_fields": {"review_date": "YYYY-MM-DD"},
            "text_fields": ["reviewer", "review_date", "review_notes"],
            "preserve_fields": [
                "footprint_id",
                "target_row_hash",
                "review_context_ref",
                "target_review_path",
            ],
        }
    if review_kind == "source_license":
        return {
            "policy": "policy_decision_fields_only_preserve_source_ids",
            "required_fields": [
                "approved_for_derived_claim_storage",
                "approved_for_production_runtime",
                "reviewer",
                "review_date",
            ],
            "optional_fields": ["notes"],
            "boolean_fields": [
                "approved_for_derived_claim_storage",
                "approved_for_production_runtime",
            ],
            "boolean_allowed_values": [True, False],
            "date_fields": {"review_date": "YYYY-MM-DD"},
            "text_fields": ["reviewer", "review_date", "notes"],
            "preserve_fields": ["source_id", "target_row_hash"],
        }
    if review_kind == "lockbox":
        return {
            "policy": "only_fill_after_upstream_manual_gates_are_ready",
            "required_fields": [
                "experiment_family_id",
                "experiment_id",
                "opened_at",
                "opened_by",
                "open_count",
                "result",
                "parameter_search_after_open",
                "rule_design_after_open",
            ],
            "optional_fields": ["notes"],
            "boolean_fields": [
                "parameter_search_after_open",
                "rule_design_after_open",
            ],
            "boolean_allowed_values": [True, False],
            "allowed_results": ["failed", "passed"],
            "date_fields": {"opened_at": "ISO-8601 datetime or date"},
            "text_fields": ["opened_by", "result", "notes"],
            "numeric_fields": ["open_count"],
            "preserve_fields": [],
        }
    return {}
