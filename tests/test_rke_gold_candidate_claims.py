from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_gold_candidate_claim_summary,
    build_gold_candidate_claims,
    merge_candidate_claims_into_review_template,
    write_gold_candidate_claims,
)
from mosaic.rke.gold_candidate_claims import _source_sentences, _variable_pair


def test_gold_candidate_claims_cover_current_manual_queue():
    claims = build_gold_candidate_claims(".")
    summary = build_gold_candidate_claim_summary(".", candidate_claims=claims)

    assert len(claims) == 500
    assert summary.candidate_claim_count == 500
    assert summary.candidate_available_count == 500
    assert summary.missing_variable_mapping_count < 500
    assert {claim.verifier_status for claim in claims} == {"requires_review"}
    assert all(claim.claim_id.startswith("GOLD-SRC-TSRR-") for claim in claims)
    assert all(claim.source_text_hash.startswith("sha256:") for claim in claims)
    assert any(claim.cause_variables and claim.target_variables for claim in claims)
    fallback_claims = [
        claim
        for claim in claims
        if "original_markdown_forecast_claim" not in claim.review_risk_flags
    ]
    assert fallback_claims
    assert all(claim.extraction_confidence_bin == "low" for claim in fallback_claims)
    assert all(
        "sentence_fallback_requires_context_synthesis" in claim.review_risk_flags
        for claim in fallback_claims
    )


def test_source_sentences_prioritize_research_claims_over_descriptive_facts():
    sentences = _source_sentences(
        "工业金属品种价格涨跌不一。"
        "黑钨精矿65%国产的价格涨跌幅为600%。"
        "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。"
    )

    assert [row[2] for row in sentences] == [
        "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。"
    ]


def test_variable_pair_does_not_infer_causes_from_metadata_context():
    known_variable_ids = {
        "bank_credit_supply",
        "bank_net_interest_margin_pressure",
        "commodity_price_cycle",
        "industry_etf_forward_return",
    }

    cause, target, flags = _variable_pair(
        "部分理财子公司选择通过多资产组合策略应对波动。",
        query_key="银行",
        industry="有色金属",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert cause == ()
    assert target == ()
    assert flags == ("canonical_variable_mapping_needed",)


def test_gold_candidate_claims_merge_preserves_manual_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["manual_claim_text"] = "manual label"
    rows[0]["claim_correct"] = True
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = merge_candidate_claims_into_review_template(tmp_path)
    merged = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]

    assert result["rows_with_candidate_fields"] == 500
    assert result["manual_fields_preserved"] is True
    assert merged[0]["manual_claim_text"] == "manual label"
    assert merged[0]["claim_correct"] is True
    assert merged[0]["proposed_claim_text"]
    assert merged[0]["proposed_verifier_status"] == "requires_review"


def test_gold_candidate_claims_prefer_original_markdown_forecast_claims(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    original_claim_text = "原文Markdown预测：未来两个季度流动性改善将推升短端资金利率下行。"
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    report_claim_path.write_text(
        json.dumps(
            {
                "claim_provenance": "source_grounded",
                "claim_text": original_claim_text,
                "direction": "positive",
                "extraction_quality": {"mapping_gaps": []},
                "forecast_claim_id": "FC-ORIGINAL-MARKDOWN-001",
                "forecast_testability": "testable",
                "forecast_type": "liquidity_forecast",
                "metric_proxy_mapping": ["pboc_net_injection"],
                "source_id": source_id,
                "source_span_ids": [f"{source_id}:original_markdown:chunk-001"],
                "target": {"target_id": "short_term_liquidity_pressure"},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    first_claim = next(claim for claim in claims if claim.claim_id == first_review["claim_id"])
    paths = write_gold_candidate_claims(tmp_path)
    merged_review = json.loads(
        (tmp_path / paths["review_template"])
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )

    assert first_claim.claim_text == original_claim_text
    assert first_claim.cause_variables == ("pboc_net_injection",)
    assert first_claim.target_variables == ("short_term_liquidity_pressure",)
    assert first_claim.source_span_ref_id == f"{source_id}:original_markdown:chunk-001:forecast-FC-ORIGINAL-MARKDOWN-001"
    assert "original_markdown_forecast_claim" in first_claim.review_risk_flags
    assert "canonical_variable_mapping_needed" not in first_claim.review_risk_flags
    assert "forecast_not_testable" not in first_claim.review_risk_flags
    assert merged_review["proposed_claim_text"] == original_claim_text
    assert merged_review["proposed_cause_variables"] == ["pboc_net_injection"]
    assert merged_review["proposed_target_variables"] == ["short_term_liquidity_pressure"]


def test_gold_candidate_claims_map_report_claims_with_local_vocabulary_fallback(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    original_claim_text = "看好风电行业，政策催化叠加装机需求增长，预期未来6个月内行业指数优于市场。"
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    report_claim_path.write_text(
        json.dumps(
            {
                "claim_provenance": "source_grounded",
                "claim_text": original_claim_text,
                "direction": "positive",
                "extraction_quality": {"mapping_gaps": ["horizon"]},
                "forecast_claim_id": "FC-LOCAL-VOCAB-FALLBACK-001",
                "forecast_testability": "insufficient_mapping",
                "forecast_type": "industry_outlook",
                "metric_proxy_mapping": [],
                "source_id": source_id,
                "source_span_ids": [f"{source_id}:original_markdown:chunk-001"],
                "target": {"target_id": "wind_power", "target_type": "industry"},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    first_claim = next(claim for claim in claims if claim.claim_id == first_review["claim_id"])

    assert first_claim.claim_text == original_claim_text
    assert "industry_policy_catalyst" in first_claim.cause_variables
    assert "industry_demand_cycle" in first_claim.cause_variables
    assert "industry_etf_forward_return" in first_claim.target_variables
    assert "canonical_variable_mapping_needed" not in first_claim.review_risk_flags
    assert "forecast_mapping_insufficient" in first_claim.review_risk_flags


def test_gold_candidate_claims_skip_boilerplate_risk_warning_report_claims(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    report_claim_path.write_text(
        json.dumps(
            {
                "claim_provenance": "source_grounded",
                "claim_text": "风险提示：宏观经济、货币政策超预期变化、数据误差等风险。",
                "direction": "negative",
                "extraction_quality": {"mapping_gaps": []},
                "forecast_claim_id": "FC-RISK-WARNING-001",
                "forecast_testability": "testable",
                "forecast_type": "risk_warning",
                "metric_proxy_mapping": ["industry_policy_catalyst"],
                "source_id": source_id,
                "source_span_ids": [f"{source_id}:original_markdown:chunk-001"],
                "target": {"target_id": "industry_etf_forward_return"},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    first_claim = next(claim for claim in claims if claim.claim_id == first_review["claim_id"])

    assert not first_claim.claim_text.startswith("风险提示")
    assert "original_markdown_forecast_claim" not in first_claim.review_risk_flags


def test_gold_candidate_claims_fallback_to_original_markdown_sentences(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    markdown_text = "原文Markdown句子显示，政策支持与流动性改善将推动行业景气提升。"
    markdown_path = tmp_path / ".mosaic/rke/report_intelligence/markdown" / f"{source_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown_text, encoding="utf-8")
    report_dir = tmp_path / "registry/report_intelligence"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "forecast_claims.jsonl").write_text("", encoding="utf-8")
    (report_dir / "report_metadata.jsonl").write_text(
        json.dumps(
            {
                "markdown": {"path": f".mosaic/rke/report_intelligence/markdown/{source_id}.md"},
                "source_id": source_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    first_claim = next(claim for claim in claims if claim.claim_id == first_review["claim_id"])

    assert first_claim.claim_text == markdown_text
    assert first_claim.source_span_id == f"{source_id}:original_markdown"
    assert "original_markdown_sentence_fallback" in first_claim.review_risk_flags


def test_gold_candidate_claims_skip_boilerplate_risk_warning_markdown_sentences(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    markdown_text = (
        "风险提示：宏观经济、货币政策超预期变化、数据误差等风险。"
        "原文Markdown句子显示，政策支持与流动性改善将推动行业景气提升。"
    )
    markdown_path = tmp_path / ".mosaic/rke/report_intelligence/markdown" / f"{source_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown_text, encoding="utf-8")
    report_dir = tmp_path / "registry/report_intelligence"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "forecast_claims.jsonl").write_text("", encoding="utf-8")
    (report_dir / "report_metadata.jsonl").write_text(
        json.dumps(
            {
                "markdown": {"path": f".mosaic/rke/report_intelligence/markdown/{source_id}.md"},
                "source_id": source_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    first_claim = next(claim for claim in claims if claim.claim_id == first_review["claim_id"])

    assert first_claim.claim_text == "原文Markdown句子显示，政策支持与流动性改善将推动行业景气提升。"
    assert not first_claim.claim_text.startswith("风险提示")


def test_gold_candidate_claims_report_malformed_rows_without_rewriting_review_template(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    candidates_path = tmp_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    candidate_count = sum(1 for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip())
    review_count = sum(1 for line in review_path.read_text(encoding="utf-8").splitlines() if line.strip())
    candidates_path.write_text(
        candidates_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )
    original_review = review_path.read_text(encoding="utf-8")

    claims = build_gold_candidate_claims(tmp_path)
    merge_result = merge_candidate_claims_into_review_template(tmp_path)
    paths = write_gold_candidate_claims(tmp_path)
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))

    assert len(claims) == review_count
    assert merge_result["applied"] is False
    assert merge_result["rows"] == review_count + 1
    assert f"gold-set review row must be object at row(s): {review_count + 1}" in merge_result["blockers"]
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == review_count
    assert f"gold candidate row must be object at row(s): {candidate_count + 1}" in summary["blockers"]
    assert f"gold-set review row must be object at row(s): {review_count + 1}" in summary["blockers"]


def test_gold_candidate_claims_report_malformed_jsonl_without_rewriting_review_template(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    candidates_path = tmp_path / "registry/sources/tushare_research_reports.gold_candidates.jsonl"
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    candidate_count = sum(1 for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip())
    review_count = sum(1 for line in review_path.read_text(encoding="utf-8").splitlines() if line.strip())
    candidates_path.write_text(candidates_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    review_path.write_text(review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    original_review = review_path.read_text(encoding="utf-8")

    claims = build_gold_candidate_claims(tmp_path)
    merge_result = merge_candidate_claims_into_review_template(tmp_path)
    paths = write_gold_candidate_claims(tmp_path)
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))

    assert len(claims) == review_count
    assert merge_result["applied"] is False
    assert merge_result["rows"] == review_count + 1
    assert any(
        f"gold-set review row {review_count + 1} must contain valid JSON" in blocker
        for blocker in merge_result["blockers"]
    )
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == review_count
    assert any(
        f"gold candidate row {candidate_count + 1} must contain valid JSON" in blocker
        for blocker in summary["blockers"]
    )
    assert any(
        f"gold-set review row {review_count + 1} must contain valid JSON" in blocker
        for blocker in summary["blockers"]
    )


def test_gold_candidate_claims_report_malformed_vocabulary_without_rewriting_review_template(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    vocabulary_path = tmp_path / "registry/vocabularies/claim_variable_vocabulary.json"
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    vocabulary_path.write_text("{\n", encoding="utf-8")
    original_review = review_path.read_text(encoding="utf-8")

    claims = build_gold_candidate_claims(tmp_path)
    merge_result = merge_candidate_claims_into_review_template(tmp_path)
    paths = write_gold_candidate_claims(tmp_path)
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))

    assert len(claims) == 500
    assert merge_result["applied"] is False
    assert any("claim_variable_vocabulary.json must contain valid JSON" in blocker for blocker in merge_result["blockers"])
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == 500
    assert summary["missing_variable_mapping_count"] == 500
    assert any("claim_variable_vocabulary.json must contain valid JSON" in blocker for blocker in summary["blockers"])


def test_gold_candidate_claim_writer_outputs_claims_summary_and_review_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    for row in review_rows:
        row["manual_claim_text"] = ""
        row["claim_correct"] = None
        row["source_span_supports_claim"] = None
        row["direction_correct"] = None
        row["target_correct"] = None
        row["horizon_correct"] = None
        row["variable_mapping_correct"] = None
        row["unsupported_field_false_grounded"] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["review_notes"] = ""
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in review_rows),
        encoding="utf-8",
    )

    paths = write_gold_candidate_claims(tmp_path)
    claims = (tmp_path / paths["candidate_claims"]).read_text(encoding="utf-8").splitlines()
    summary = json.loads((tmp_path / paths["summary"]).read_text(encoding="utf-8"))
    review_row = json.loads(
        (tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )

    assert len(claims) == 500
    assert summary["candidate_claim_count"] == 500
    assert summary["review_rows_with_candidate_fields"] == 500
    assert summary["manual_fields_preserved"] is True
    assert review_row["proposed_claim_text"]
    assert review_row["manual_claim_text"] == ""
