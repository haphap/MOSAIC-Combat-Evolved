from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    summarize_gold_set_review,
    summarize_source_license_review,
    write_gold_set_review_summary,
    write_source_license_review_summary,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_current_review_summaries_show_manual_blockers():
    source_rows = [
        json.loads(line)
        for line in Path("registry/sources/tushare_research_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    gold = summarize_gold_set_review(".")
    license_summary = summarize_source_license_review(".")

    assert gold.total_claims == 500
    assert gold.reviewed_claims == 0
    assert gold.pending_claims == 500
    assert not gold.passed
    assert "500 gold-set claim review rows still pending" in gold.blockers
    assert license_summary.total_sources == len(source_rows)
    assert license_summary.reviewed_sources == 0
    assert license_summary.pending_sources == len(source_rows)
    assert license_summary.approved_for_production_runtime == 0
    assert not license_summary.passed


def test_gold_set_summary_passes_when_all_review_rows_pass(tmp_path: Path):
    rows = []
    for document_idx in range(50):
        source_id = f"SRC-{document_idx:03d}"
        for claim_idx in range(10):
            rows.append(
                {
                    "source_id": source_id,
                    "source_span_id": f"{source_id}:abstract",
                    "claim_id": f"GOLD-{source_id}-{claim_idx:03d}",
                    "document_id": source_id,
                    "claim_correct": True,
                    "source_span_supports_claim": True,
                    "direction_correct": True,
                    "variable_mapping_correct": True,
                    "unsupported_field_false_grounded": False,
                }
            )
    _write_jsonl(tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl", rows)

    summary = summarize_gold_set_review(tmp_path)
    out = write_gold_set_review_summary(tmp_path)

    assert summary.review_complete
    assert summary.passed
    assert summary.metrics["sample_size_documents"] == 50
    assert summary.metrics["sample_size_claims"] == 500
    assert not summary.blockers
    assert Path(out["path"]).exists()


def test_gold_set_summary_rejects_non_object_review_rows(tmp_path: Path):
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    _write_jsonl(
        review_path,
        [
            {
                "source_id": "SRC-A",
                "source_span_id": "SRC-A:abstract",
                "claim_id": "GOLD-SRC-A-001",
                "document_id": "SRC-A",
                "claim_correct": True,
                "source_span_supports_claim": True,
                "direction_correct": True,
                "variable_mapping_correct": True,
                "unsupported_field_false_grounded": False,
            }
        ],
    )
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    summary = summarize_gold_set_review(tmp_path)

    assert not summary.review_complete
    assert not summary.passed
    assert summary.total_claims == 2
    assert summary.reviewed_claims == 1
    assert summary.pending_claims == 1
    assert "gold-set review row must be object at row(s): 2" in summary.blockers


def test_license_summary_passes_when_all_sources_are_approved(tmp_path: Path):
    sources = [
        {
            "source_id": "SRC-A",
            "source_type": "tushare_research_report",
            "title": "A",
            "publish_date": "2026-06-05",
            "source_hash": "sha256:a",
            "point_in_time_available": True,
            "license_status": "pending_review",
        },
        {
            "source_id": "SRC-B",
            "source_type": "tushare_research_report",
            "title": "B",
            "publish_date": "2026-06-05",
            "source_hash": "sha256:b",
            "point_in_time_available": True,
            "license_status": "pending_review",
        },
    ]
    reviews = [
        {
            "source_id": source["source_id"],
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
        }
        for source in sources
    ]
    _write_jsonl(tmp_path / "registry/sources/tushare_research_reports.jsonl", sources)
    _write_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl", reviews)

    summary = summarize_source_license_review(tmp_path)
    out = write_source_license_review_summary(tmp_path)

    assert summary.review_complete
    assert summary.passed
    assert summary.reviewed_sources == 2
    assert summary.pending_sources == 0
    assert summary.approved_for_production_runtime == 2
    assert not summary.blockers
    assert Path(out["path"]).exists()


def test_license_summary_rejects_non_object_review_rows(tmp_path: Path):
    sources = [
        {
            "source_id": "SRC-A",
            "source_type": "tushare_research_report",
            "title": "A",
            "publish_date": "2026-06-05",
            "source_hash": "sha256:a",
            "point_in_time_available": True,
            "license_status": "pending_review",
        }
    ]
    reviews = [
        {
            "source_id": "SRC-A",
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
        }
    ]
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    _write_jsonl(tmp_path / "registry/sources/tushare_research_reports.jsonl", sources)
    _write_jsonl(review_path, reviews)
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    summary = summarize_source_license_review(tmp_path)

    assert not summary.review_complete
    assert not summary.passed
    assert summary.reviewed_sources == 1
    assert summary.approved_for_production_runtime == 1
    assert "source license review row must be object at row(s): 2" in summary.blockers


def test_license_summary_rejects_non_object_source_rows(tmp_path: Path):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    sources = [
        {
            "source_id": "SRC-A",
            "source_type": "tushare_research_report",
            "title": "A",
            "publish_date": "2026-06-05",
            "source_hash": "sha256:a",
            "point_in_time_available": True,
            "license_status": "pending_review",
        }
    ]
    reviews = [
        {
            "source_id": "SRC-A",
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": True,
            "reviewer": "compliance",
            "review_date": "2026-06-06",
        }
    ]
    _write_jsonl(source_path, sources)
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl", reviews)

    summary = summarize_source_license_review(tmp_path)

    assert not summary.review_complete
    assert not summary.passed
    assert summary.total_sources == 1
    assert "source registry row must be object at row(s): 2" in summary.blockers
