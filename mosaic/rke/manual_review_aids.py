"""Path-only manual review aid references for operator-facing commands."""

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
    return {}
