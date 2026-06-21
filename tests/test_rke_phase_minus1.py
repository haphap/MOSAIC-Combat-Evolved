from __future__ import annotations

import json

import pytest

from mosaic.rke import (
    GoldSetReviewRecord,
    REQUIRED_GOLD_SET_DOMAINS,
    audit_research_report_corpus,
    build_gold_set_review_template,
    evaluate_gold_set_reviews,
    load_jsonl,
    select_gold_set_candidates,
    write_gold_set_candidates,
    write_gold_set_review_template,
)
from mosaic.rke.phase_minus1 import DEFAULT_GOLD_SET_DOCUMENTS


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


def test_phase_minus1_audit_reports_malformed_source_rows():
    rows = [_row("SRC-1", "600519.SH"), "not an object"]

    audit = audit_research_report_corpus(rows)

    assert audit.row_count == 2
    assert audit.rows_with_abstract == 1
    assert not audit.ready_for_gold_set_sampling
    assert "<non-object-row-2>" in audit.missing_required_fields
    assert "<non-object-row-2>: source row must be object" in audit.production_blockers


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


def test_phase_minus1_default_gold_set_candidates_are_oversampled():
    rows = [
        _row(f"SRC-{idx:03d}", f"行业{idx:03d}", "行业研报")
        | {"publish_date": f"2026-06-{1 + idx % 28:02d}"}
        for idx in range(DEFAULT_GOLD_SET_DOCUMENTS + 10)
    ]

    candidates = select_gold_set_candidates(rows)

    assert DEFAULT_GOLD_SET_DOCUMENTS == 75
    assert len(candidates) == DEFAULT_GOLD_SET_DOCUMENTS


def test_phase_minus1_candidate_selection_rejects_malformed_source_rows():
    rows = [_row("SRC-1", "600519.SH"), ["not", "an", "object"]]

    with pytest.raises(ValueError, match=r"source row must be object at row\(s\): 2"):
        select_gold_set_candidates(rows, max_documents=2)


def test_phase_minus1_gold_candidate_writer_rejects_malformed_rows(tmp_path):
    candidates = [_row("SRC-1", "600519.SH"), "not an object"]

    with pytest.raises(ValueError, match=r"gold candidate row must be object at row\(s\): 2"):
        write_gold_set_candidates(candidates, tmp_path / "gold_candidates.jsonl")


def test_phase_minus1_selects_gold_set_candidates_by_required_domains():
    rows = [
        _row("SRC-CB-1", "银行", "行业研报")
        | {"abstract": "央行公开市场逆回购提升流动性，信贷利率边际改善。"},
        _row("SRC-DOLLAR-1", "外资", "行业研报")
        | {"abstract": "美元指数和人民币汇率影响外资风险偏好。"},
        _row("SRC-VOL-1", "策略", "行业研报")
        | {"abstract": "市场波动上升，风险偏好下降，回撤压力增加。"},
        _row("SRC-SEMI-1", "半导体", "行业研报")
        | {"abstract": "半导体芯片国产替代和AI算力需求提升。"},
        _row("SRC-OTHER-1", "食品饮料", "个股研报")
        | {"abstract": "消费需求修复。"},
    ]

    candidates = select_gold_set_candidates(rows, max_documents=5)

    assert set(REQUIRED_GOLD_SET_DOMAINS).issubset(
        {candidate["gold_set_domain"] for candidate in candidates}
    )
    assert "other" in {candidate["gold_set_domain"] for candidate in candidates}
    assert all(candidate["gold_set_domains"] for candidate in candidates)
    assert all(candidate["gold_set_domain_scores"] for candidate in candidates if candidate["gold_set_domain"] != "other")
    assert all(
        candidate["gold_set_domain_matches"] for candidate in candidates if candidate["gold_set_domain"] != "other"
    )


def test_phase_minus1_domain_matching_requires_strong_or_multiple_weak_terms():
    rows = [
        _row("SRC-WEAK-ONLY", "银行", "行业研报") | {"abstract": "银行盈利修复。"},
        _row("SRC-CB-WEAKS", "资金面", "行业研报") | {"abstract": "资金面和利率共同影响短端流动性。"},
        _row("SRC-DOLLAR-STRONG", "策略", "行业研报") | {"abstract": "美元指数上行压制人民币汇率。"},
    ]

    candidates = select_gold_set_candidates(rows, max_documents=3)
    by_id = {candidate["source_id"]: candidate for candidate in candidates}

    assert by_id["SRC-WEAK-ONLY"]["gold_set_domains"] == ("other",)
    assert by_id["SRC-CB-WEAKS"]["gold_set_domains"][0] == "central_bank"
    assert by_id["SRC-CB-WEAKS"]["gold_set_domain_scores"]["central_bank"] >= 2
    assert by_id["SRC-DOLLAR-STRONG"]["gold_set_domains"][0] == "dollar"


def test_phase_minus1_domain_quota_prefers_primary_domain_rows():
    rows = [
        _row("SRC-Z-MIXED", "工业金属", "行业研报")
        | {
            "abstract": (
                "美元指数与美联储预期影响风险偏好，降息和利率变化只是行业估值背景。"
            )
        },
        _row("SRC-A-CENTRAL", "资金面", "行业研报")
        | {"abstract": "央行公开市场操作和MLF续作影响资金面与国债收益率。"},
    ]

    candidates = select_gold_set_candidates(rows, max_documents=1)

    assert candidates[0]["source_id"] == "SRC-A-CENTRAL"
    assert candidates[0]["gold_set_domain"] == "central_bank"
    assert candidates[0]["gold_set_domains"][0] == "central_bank"


def test_phase_minus1_loads_jsonl(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_row("SRC-1", "600519.SH"), ensure_ascii=False) + "\n", encoding="utf-8")

    assert load_jsonl(path)[0]["source_id"] == "SRC-1"


def test_phase_minus1_gold_set_template_and_gate(tmp_path):
    candidates = [_row(f"SRC-{idx:02d}", "银行", "行业研报") for idx in range(50)]

    template = build_gold_set_review_template(candidates, claims_per_document=10)
    out = write_gold_set_review_template(
        candidates,
        tmp_path / "gold_review_template.jsonl",
        claims_per_document=10,
    )
    reviewed = [
        GoldSetReviewRecord(
            source_id=row["source_id"],
            source_span_id=row["source_span_id"],
            claim_id=row["claim_id"],
            document_id=row["document_id"],
            claim_correct=True,
            source_span_supports_claim=True,
            direction_correct=True,
            target_correct=True,
            horizon_correct=True,
            variable_mapping_correct=True,
            unsupported_field_false_grounded=False,
        )
        for row in template
    ]

    gold_set = evaluate_gold_set_reviews(reviewed, gold_set_id="GOLD-CLAIM-2026Q2")

    assert len(template) == 500
    assert out["rows"] == 500
    assert template[0]["claim_correct"] is None
    assert template[0]["target_correct"] is None
    assert template[0]["horizon_correct"] is None
    assert "gold_set_domain_scores" in template[0]
    assert "gold_set_domain_matches" in template[0]
    assert gold_set.sample_size_documents == 50
    assert gold_set.sample_size_claims == 500
    assert gold_set.passed


def test_phase_minus1_gold_set_template_rejects_malformed_candidates():
    candidates = [_row("SRC-1", "银行", "行业研报"), "not an object"]

    with pytest.raises(ValueError, match=r"gold candidate row must be object at row\(s\): 2"):
        build_gold_set_review_template(candidates, claims_per_document=1)


def test_phase_minus1_gold_set_gate_rejects_small_or_unreviewed_samples():
    unreviewed = build_gold_set_review_template([_row("SRC-1", "600519.SH")], claims_per_document=2)

    gold_set = evaluate_gold_set_reviews(unreviewed, gold_set_id="GOLD-INCOMPLETE")

    assert not gold_set.passed
    assert gold_set.sample_size_documents == 1
    assert gold_set.sample_size_claims == 2
    assert "gold set requires >= 50 documents" in gold_set.gate_failures()


def test_phase_minus1_gold_set_gate_counts_malformed_review_rows_as_failures():
    gold_set = evaluate_gold_set_reviews(
        ["not an object", ["also", "not", "object"]],
        gold_set_id="GOLD-MALFORMED",
    )

    assert not gold_set.passed
    assert gold_set.sample_size_documents == 2
    assert gold_set.sample_size_claims == 2
    assert gold_set.claim_precision == 0.0
    assert gold_set.source_span_support_precision == 0.0
    assert gold_set.direction_accuracy == 0.0
    assert gold_set.target_accuracy == 0.0
    assert gold_set.horizon_accuracy == 0.0
    assert gold_set.variable_mapping_accuracy == 0.0
    assert gold_set.unsupported_field_false_grounding_rate == 1.0
    assert "claim_precision below 0.85" in gold_set.gate_failures()
    assert "unsupported_field_false_grounding_rate above 0.05" in gold_set.gate_failures()


def test_tushare_gold_set_review_template_has_completed_manual_labels():
    rows = load_jsonl("registry/gold_sets/tushare_research_reports.review_template.jsonl")

    assert len(rows) >= 100
    assert len({row["source_id"] for row in rows}) >= 50
    assert set(REQUIRED_GOLD_SET_DOMAINS).issubset({row["gold_set_domain"] for row in rows})
    assert all(isinstance(row["claim_correct"], bool) for row in rows)
    assert all(isinstance(row["source_span_supports_claim"], bool) for row in rows)
    assert all(isinstance(row["direction_correct"], bool) for row in rows)
    assert all(isinstance(row["target_correct"], bool) for row in rows)
    assert all(isinstance(row["horizon_correct"], bool) for row in rows)
    assert all(isinstance(row["variable_mapping_correct"], bool) for row in rows)
    assert all(row["reviewer"] for row in rows)
    assert all(row["review_date"] for row in rows)
    assert all(row["proposed_claim_text"] for row in rows)
    assert {row["proposed_verifier_status"] for row in rows} == {"requires_review"}
