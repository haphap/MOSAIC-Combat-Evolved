from __future__ import annotations

import json

from mosaic.rke import (
    audit_research_report_corpus,
    load_jsonl,
    select_gold_set_candidates,
    write_gold_set_candidates,
)


def _row(source_id: str, query_key: str, report_type: str = "个股研报") -> dict:
    return {
        "source_id": source_id,
        "source_span_id": f"{source_id}:abstract",
        "source_type": "tushare_research_report",
        "report_type": report_type,
        "query_key": query_key,
        "publish_date": "2026-06-05",
        "discovered_at": "2026-06-05T12:00:00+00:00",
        "title": f"title {source_id}",
        "abstract": f"abstract {source_id}",
        "source_hash": f"sha256:{source_id}",
        "point_in_time_available": True,
        "license_status": "pending_review",
    }


def test_phase_minus1_audits_tushare_source_rows():
    rows = [_row("SRC-1", "600519.SH"), _row("SRC-2", "银行", "行业研报")]

    audit = audit_research_report_corpus(rows)

    assert audit.row_count == 2
    assert audit.rows_with_abstract == 2
    assert audit.ready_for_gold_set_sampling
    assert audit.report_type_counts == {"个股研报": 1, "行业研报": 1}
    assert len(audit.production_blockers) == 2
    assert all("pending_review" in blocker for blocker in audit.production_blockers)


def test_phase_minus1_detects_missing_fields_and_duplicate_hashes():
    rows = [_row("SRC-1", "600519.SH"), {**_row("SRC-2", "600519.SH"), "source_hash": "sha256:SRC-1", "abstract": ""}]

    audit = audit_research_report_corpus(rows)

    assert not audit.ready_for_gold_set_sampling
    assert audit.duplicate_source_hashes == ("sha256:SRC-1",)
    assert audit.missing_required_fields["SRC-2"] == ("abstract",)


def test_phase_minus1_selects_and_writes_gold_set_candidates(tmp_path):
    rows = [
        _row("SRC-1", "600519.SH"),
        _row("SRC-2", "银行", "行业研报"),
        _row("SRC-3", "300750.SZ"),
    ]

    candidates = select_gold_set_candidates(rows, max_documents=2)
    out = write_gold_set_candidates(candidates, tmp_path / "gold_candidates.jsonl")

    assert len(candidates) == 2
    assert out["rows"] == 2
    loaded = [json.loads(line) for line in (tmp_path / "gold_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["source_id"] for row in loaded} == {row["source_id"] for row in candidates}


def test_phase_minus1_loads_jsonl(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_row("SRC-1", "600519.SH"), ensure_ascii=False) + "\n", encoding="utf-8")

    assert load_jsonl(path)[0]["source_id"] == "SRC-1"
