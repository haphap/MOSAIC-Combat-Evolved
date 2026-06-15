from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from mosaic.rke import (
    build_gold_candidate_claim_summary,
    build_gold_candidate_claims,
    merge_candidate_claims_into_review_template,
    write_gold_candidate_claims,
)
from mosaic.rke.gold_candidate_claims import _direction, _source_sentences, _variable_pair
from mosaic.rke.gold_candidate_claims import _candidate_claim_from_report_intelligence
from mosaic.rke.manual_review_batches import gold_candidate_reviewable
from mosaic.rke.manual_review_batches import write_gold_review_starter
from mosaic.rke.phase_minus1 import _gold_set_domain_evidence

GOLD_REVIEW_BOOL_FIELDS = (
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "target_correct",
    "horizon_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
)


def _clear_manual_review_fields(rows: list[dict]) -> None:
    for row in rows:
        row["manual_claim_text"] = ""
        for field in GOLD_REVIEW_BOOL_FIELDS:
            row[field] = None
        row["reviewer"] = ""
        row["review_date"] = ""
        row["review_notes"] = ""


def test_gold_candidate_claims_cover_current_manual_queue():
    claims = build_gold_candidate_claims(".")
    summary = build_gold_candidate_claim_summary(".", candidate_claims=claims)
    per_source = Counter(claim.source_id for claim in claims)

    assert 50 <= len(claims) <= 150
    assert summary.candidate_claim_count == len(claims)
    assert summary.candidate_available_count == len(claims)
    assert summary.missing_variable_mapping_count < len(claims)
    assert len(per_source) >= 30
    assert max(per_source.values()) <= 3
    assert {claim.verifier_status for claim in claims} == {"requires_review"}
    assert all(claim.claim_id.startswith("GOLD-SRC-TSRR-") for claim in claims)
    assert all(claim.source_text_hash.startswith("sha256:") for claim in claims)
    assert any(claim.cause_variables and claim.target_variables for claim in claims)
    assert not any("candidate_unavailable" in claim.review_risk_flags for claim in claims)
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


def test_gold_candidate_reviewable_excludes_low_confidence_pipeline_outputs():
    base_row = {
        "proposed_candidate_current": True,
        "proposed_claim_text": "若政策支持延续，行业景气有望提升。",
        "proposed_cause_variables": ["industry_policy_catalyst"],
        "proposed_target_variables": ["industry_etf_forward_return"],
        "proposed_direction": "positive",
        "proposed_review_risk_flags": [],
    }

    assert gold_candidate_reviewable(base_row) is True
    for flag in (
        "canonical_variable_mapping_needed",
        "direction_conflict_requires_review",
        "sentence_fallback_requires_context_synthesis",
    ):
        assert gold_candidate_reviewable({**base_row, "proposed_review_risk_flags": [flag]}) is False
    for flag in ("forecast_mapping_insufficient", "forecast_not_testable"):
        assert gold_candidate_reviewable({**base_row, "proposed_review_risk_flags": [flag]}) is True
    for direction in ("", "neutral", "ambiguous", "unknown"):
        assert gold_candidate_reviewable({**base_row, "proposed_direction": direction}) is False


def test_source_sentences_prioritize_research_claims_over_descriptive_facts():
    sentences = _source_sentences(
        "工业金属品种价格涨跌不一。"
        "黑钨精矿65%国产的价格涨跌幅为600%。"
        "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。"
    )

    assert [row[2] for row in sentences] == [
        "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。"
    ]


def test_source_sentences_skip_risk_warning_section_enumerations():
    sentences = _source_sentences(
        "投资线索\n"
        "若AI算力需求持续增长，计算机板块有望跑赢市场。\n"
        "风险提示\n"
        "1、政策落地不及预期；2、技术发展不及预期；3、市场竞争加剧。"
    )

    assert [row[2] for row in sentences] == [
        "若AI算力需求持续增长，计算机板块有望跑赢市场。"
    ]


def test_source_sentences_skip_risk_warning_with_full_stop_and_unprefixed_list():
    sentences = _source_sentences(
        "风险提示。境外期货客户权益增长不达预期，美联储货币政策风险，境内期货行业竞争加剧风险。"
        "若实体企业出海带动跨境风险管理需求增长，境外期货业务收入有望提升。"
    )

    assert [row[2] for row in sentences] == [
        "若实体企业出海带动跨境风险管理需求增长，境外期货业务收入有望提升。"
    ]


def test_source_sentences_skip_toc_and_short_heading_rows():
    sentences = _source_sentences(
        "四、投资建议....8\n"
        "## 全球格局 · 中美双核 · 未来\n"
        "若AI算力需求持续增长，计算机板块有望跑赢市场。"
    )

    assert [row[2] for row in sentences] == [
        "若AI算力需求持续增长，计算机板块有望跑赢市场。"
    ]


def test_source_sentences_skip_rating_slogans_and_descriptive_news():
    sentences = _source_sentences(
        "国防军工行业评级为看好，预期未来6个月内行业指数优于市场指数5%以上。\n"
        "计算机设备行业预期未来6个月内行业指数优于市场指数5%以上。\n"
        "本公司的资产管理和证券自营部门可能独立做出与本报告中的意见和建议不一致的投资决策。\n"
        "2、《电子行业研究周报：国产代工季报景气 受益涨价效应和订单外溢》\n"
        "关注行业估值修复机会。\n"
        "据工业和信息化部消息，一季度我国数字产业实现良好开局，行业利润大幅改善。\n"
        "若AI算力需求持续增长，计算机板块有望跑赢市场。"
    )

    assert [row[2] for row in sentences] == [
        "若AI算力需求持续增长，计算机板块有望跑赢市场。"
    ]


def test_variable_pair_normalizes_stock_report_target_and_avoids_generic_price_commodity():
    known_variable_ids = {
        "bank_credit_supply",
        "bank_net_interest_margin_pressure",
        "commodity_price_cycle",
        "company_fundamental_momentum",
        "industry_demand_cycle",
        "stock_forward_excess_return",
    }

    cause, target, _ = _variable_pair(
        "平安银行净息差环比回升且负债成本改善，减轻利息净收入拖累并支撑利润修复。",
        query_key="000001.SZ",
        industry="银行",
        ts_code="000001.SZ",
        known_variable_ids=known_variable_ids,
    )

    assert "bank_credit_supply" in cause
    assert "company_fundamental_momentum" in cause
    assert "commodity_price_cycle" not in cause
    assert target == ("stock_forward_excess_return",)


def test_variable_pair_maps_wealth_management_nav_pressure_without_bank_nim():
    known_variable_ids = {
        "bank_credit_supply",
        "bank_net_interest_margin_pressure",
        "competitive_intensity_pressure",
        "industry_demand_cycle",
        "pboc_net_injection",
        "short_term_liquidity_pressure",
        "wealth_management_nav_pressure",
    }

    cause, target, _ = _variable_pair(
        "低利率环境下固收收益空间收窄，银行理财通过多资产配置提升风险调整后收益。",
        query_key="银行理财",
        industry="银行",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "industry_demand_cycle" in cause
    assert "competitive_intensity_pressure" in cause
    assert "pboc_net_injection" not in cause
    assert "bank_credit_supply" not in cause
    assert "short_term_liquidity_pressure" not in target
    assert "bank_net_interest_margin_pressure" not in target
    assert target == ("wealth_management_nav_pressure",)


def test_variable_pair_maps_bank_credit_growth_expectation():
    known_variable_ids = {
        "bank_credit_growth_expectation",
        "bank_credit_supply",
        "bank_net_interest_margin_pressure",
    }

    cause, target, _ = _variable_pair(
        "地产销售稳步回温、乘用车销售持续火热推动下，预计居民中长期消费贷款边际改善。",
        query_key="银行5月金融数据",
        industry="银行",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert cause == ("bank_credit_supply",)
    assert target == ("bank_credit_growth_expectation",)


def test_report_claim_mapping_filters_variable_types_and_normalizes_stock_target():
    known_variable_ids = {
        "bank_net_interest_margin_pressure",
        "company_fundamental_momentum",
        "industry_etf_forward_return",
        "stock_forward_excess_return",
    }
    variable_type_by_id = {
        "bank_net_interest_margin_pressure": "target",
        "company_fundamental_momentum": "cause",
        "industry_etf_forward_return": "target",
        "stock_forward_excess_return": "target",
    }

    claim = _candidate_claim_from_report_intelligence(
        {
            "source_id": "SRC-TEST-STOCK",
            "query_key": "000001.SZ",
            "industry": "银行",
            "ts_code": "000001.SZ",
        },
        {
            "claim_id": "GOLD-SRC-TEST-STOCK-001",
            "source_span_id": "SRC-TEST-STOCK:abstract",
        },
        {
            "claim_provenance": "source_grounded",
            "claim_text": "平安银行净息差环比回升且负债成本改善，推动公司利润修复。",
            "direction": "positive",
            "extraction_quality": {"mapping_gaps": []},
            "forecast_claim_id": "FC-STOCK-001",
            "forecast_testability": "testable",
            "forecast_type": "fundamental",
            "metric_proxy_mapping": [
                "industry_etf_forward_return",
                "company_fundamental_momentum",
            ],
            "source_span_ids": ["SRC-TEST-STOCK:original_markdown:chunk-001"],
            "target": {"target_id": "bank_net_interest_margin_pressure"},
        },
        0,
        known_variable_ids,
        variable_type_by_id,
        {"SRC-TEST-STOCK"},
    )

    assert claim.cause_variables == ("company_fundamental_momentum",)
    assert claim.target_variables == ("stock_forward_excess_return",)


def test_gold_set_domain_does_not_treat_foreign_revenue_amount_as_dollar_macro():
    evidence = _gold_set_domain_evidence(
        {
            "query_key": "India tourism",
            "industry": "旅游",
            "title": "印度旅游业发展",
            "abstract": "2024年印度从旅游业获得的汇率收入达351.16亿美元，基础设施改善推动游客增长。",
            "report_type": "行业研报",
            "ts_code": "",
        }
    )

    assert "dollar" not in evidence


def test_gold_set_domain_keeps_dollar_macro_context():
    evidence = _gold_set_domain_evidence(
        {
            "query_key": "美元",
            "industry": "宏观",
            "title": "美元指数与美联储政策",
            "abstract": "美元指数走强，美联储降息预期影响人民币汇率。",
            "report_type": "宏观研报",
            "ts_code": "",
        }
    )

    assert "dollar" in evidence


def test_source_sentences_dedupe_normalized_duplicate_claims():
    sentences = _source_sentences(
        "若供给约束延续，铜价有望震荡偏强。"
        "若供给约束延续， 铜价有望震荡偏强。"
    )

    assert [row[2] for row in sentences] == ["若供给约束延续，铜价有望震荡偏强。"]


def test_direction_handles_price_positive_terms_despite_supply_pressure():
    assert _direction("冶炼厂利润承压但非美库存紧张，短期铜价仍震荡偏强。") == "positive"
    assert _direction("企业出海带来跨境风险管理需求增长，为境外期货业务提供增量。") == "positive"
    assert _direction("国资直接介入有利于后续部署推进化解风险、保障交付等工作。") == "positive"
    assert _direction("2025年业绩承压，2026Q1盈利能力显著改善。") == "positive"
    assert (
        _direction("公司仍有减值压力，下调2026-2027年盈利预测，预计2027-2028年净利润转正并改善。")
        == "ambiguous"
    )


def test_report_claim_direction_conflict_requires_review_and_no_unsupported_fields():
    known_variable_ids = {
        "industry_policy_catalyst",
        "industry_etf_forward_return",
    }
    variable_type_by_id = {
        "industry_policy_catalyst": "cause",
        "industry_etf_forward_return": "target",
    }

    claim = _candidate_claim_from_report_intelligence(
        {
            "source_id": "SRC-DIRECTION-CONFLICT",
            "query_key": "有色金属",
            "industry": "有色金属",
            "ts_code": "",
        },
        {
            "claim_id": "GOLD-SRC-DIRECTION-CONFLICT-001",
            "source_span_id": "SRC-DIRECTION-CONFLICT:abstract",
        },
        {
            "claim_provenance": "source_grounded",
            "claim_text": "若政策支持延续，行业景气有望提升。",
            "direction": "negative",
            "extraction_quality": {"mapping_gaps": []},
            "forecast_claim_id": "FC-DIRECTION-CONFLICT-001",
            "forecast_testability": "testable",
            "forecast_type": "industry_outlook",
            "metric_proxy_mapping": ["industry_policy_catalyst"],
            "source_span_ids": ["SRC-DIRECTION-CONFLICT:original_markdown:chunk-001"],
            "target": {"target_id": "industry_etf_forward_return"},
        },
        0,
        known_variable_ids,
        variable_type_by_id,
        {"SRC-DIRECTION-CONFLICT"},
    )

    assert claim.direction == "ambiguous"
    assert "direction_conflict_requires_review" in claim.review_risk_flags
    assert claim.unsupported_fields == ()


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


def test_variable_pair_does_not_map_generic_consumption_to_liquor_or_dollar_liquidity_to_bank():
    known_variable_ids = {
        "bank_credit_supply",
        "bank_net_interest_margin_pressure",
        "commodity_price_cycle",
        "consumer_leader_profitability_expectation",
        "global_dollar_liquidity_pressure",
        "industry_demand_cycle",
        "industry_etf_forward_return",
        "liquor_demand_recovery",
        "pboc_net_injection",
        "short_term_liquidity_pressure",
    }

    cause, target, _ = _variable_pair(
        "美国收入与消费端偏弱，美元宏观流动性紧缺压制贵金属价格。",
        query_key="有色金属",
        industry="有色金属",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "liquor_demand_recovery" not in cause
    assert "consumer_leader_profitability_expectation" not in target
    assert "pboc_net_injection" not in cause
    assert "bank_net_interest_margin_pressure" not in target
    assert "global_dollar_liquidity_pressure" in cause
    assert "commodity_price_cycle" in cause


def test_variable_pair_does_not_map_foreign_revenue_amount_to_dollar_liquidity():
    known_variable_ids = {
        "global_dollar_liquidity_pressure",
        "industry_demand_cycle",
        "industry_etf_forward_return",
    }

    cause, target, _ = _variable_pair(
        "2024年印度从旅游业获得的汇率收入达351.16亿美元，基础设施改善推动游客增长。",
        query_key="India tourism",
        industry="旅游",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "global_dollar_liquidity_pressure" not in cause
    assert "industry_demand_cycle" in cause
    assert target == ()


def test_variable_pair_maps_cleanroom_construction_to_industry_proxy_not_semiconductor_target():
    known_variable_ids = {
        "ai_compute_demand",
        "industry_demand_cycle",
        "industry_etf_forward_return",
        "semiconductor_policy_substitution_alpha",
        "semiconductor_storage_cycle",
        "trade_friction_intensity",
    }

    cause, target, flags = _variable_pair(
        "AI算力爆发带动存储芯片景气上行，国产替代加速打开洁净室工程空间。",
        query_key="建筑装饰",
        industry="建筑装饰",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "ai_compute_demand" in cause
    assert "trade_friction_intensity" in cause
    assert target == ("industry_etf_forward_return",)
    assert flags == ()


def test_variable_pair_requires_storage_chip_context_for_semiconductor_storage_target():
    known_variable_ids = {
        "ai_compute_demand",
        "industry_demand_cycle",
        "industry_etf_forward_return",
        "semiconductor_storage_cycle",
    }

    cause, target, _ = _variable_pair(
        "预计未来一年，AI相关产品收入占比将突破50%，成为阿里云收入增长的主要引擎。",
        query_key="通信设备",
        industry="通信设备",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "ai_compute_demand" in cause
    assert "semiconductor_storage_cycle" not in target
    assert target == ("industry_etf_forward_return",)


def test_variable_pair_keeps_explicit_storage_chip_cycle_target():
    known_variable_ids = {
        "ai_compute_demand",
        "industry_demand_cycle",
        "industry_etf_forward_return",
        "semiconductor_storage_cycle",
    }

    cause, target, flags = _variable_pair(
        "AI算力需求增长带动存储芯片景气上行，DRAM和HBM价格周期有望延续。",
        query_key="半导体",
        industry="半导体",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "ai_compute_demand" in cause
    assert "semiconductor_storage_cycle" in target
    assert flags == ()


def test_variable_pair_does_not_map_domestic_machine_tools_to_semiconductor_substitution():
    known_variable_ids = {
        "industry_demand_cycle",
        "industry_etf_forward_return",
        "semiconductor_policy_substitution_alpha",
        "trade_friction_intensity",
    }

    cause, target, flags = _variable_pair(
        "国产高端机床整机加速落地，上游核心零部件配套需求有望持续放量。",
        query_key="通用设备",
        industry="通用设备",
        ts_code="",
        known_variable_ids=known_variable_ids,
    )

    assert "trade_friction_intensity" in cause
    assert "semiconductor_policy_substitution_alpha" not in target
    assert target == ("industry_etf_forward_return",)
    assert flags == ()


def test_variable_pair_does_not_treat_cross_border_risk_management_as_pboc_or_competition():
    known_variable_ids = {
        "competitive_intensity_pressure",
        "commodity_price_cycle",
        "global_dollar_liquidity_pressure",
        "industry_demand_cycle",
        "industry_etf_forward_return",
        "pboc_net_injection",
        "short_term_liquidity_pressure",
        "stock_forward_excess_return",
    }

    cause, target, _ = _variable_pair(
        "随着实体企业向海外延伸，大宗商品价格风险、汇率风险、利率风险及跨境资金管理风险上升，全球期货及期权风险管理需求增加。",
        query_key="603093.SH",
        industry="非银金融",
        ts_code="603093.SH",
        known_variable_ids=known_variable_ids,
    )

    assert "pboc_net_injection" not in cause
    assert "short_term_liquidity_pressure" not in target
    assert "competitive_intensity_pressure" not in cause
    assert "commodity_price_cycle" in cause
    assert "global_dollar_liquidity_pressure" in cause
    assert "industry_demand_cycle" in cause
    assert target == ("stock_forward_excess_return",)


def test_gold_candidate_claims_merge_preserves_manual_fields(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    _clear_manual_review_fields(rows)
    rows[0]["manual_claim_text"] = "manual label"
    rows[0]["claim_correct"] = True
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    result = merge_candidate_claims_into_review_template(tmp_path, candidate_claims=claims)
    merged = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]

    assert 0 < result["rows_with_candidate_fields"] <= len(claims)
    assert len(merged) <= len(claims)
    assert result["manual_fields_preserved"] is True
    assert merged[0]["manual_claim_text"] == "manual label"
    assert merged[0]["claim_correct"] is True
    assert merged[0]["proposed_claim_text"]
    assert merged[0]["proposed_verifier_status"] == "requires_review"


def test_gold_candidate_claims_merge_drops_unclaimed_blank_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    _clear_manual_review_fields(rows)
    source_id = rows[0]["source_id"]
    blank_same_source_ids = [
        row["claim_id"]
        for row in rows
        if row["source_id"] == source_id and row["claim_id"] != rows[0]["claim_id"]
    ]
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    result = merge_candidate_claims_into_review_template(
        tmp_path,
        candidate_claims=[build_gold_candidate_claims(tmp_path)[0]],
    )
    merged = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    merged_ids = {row["claim_id"] for row in merged}

    assert result["rows_with_candidate_fields"] == 1
    assert rows[0]["claim_id"] in merged_ids
    assert merged_ids.isdisjoint(blank_same_source_ids)


def test_gold_candidate_claims_merge_drops_prefilled_identity_only_stale_rows(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    _clear_manual_review_fields(rows)
    claims = build_gold_candidate_claims(tmp_path)
    kept_claim = claims[0]
    stale_identity_only = next(row for row in rows if row["claim_id"] != kept_claim.claim_id)
    stale_identity_only["reviewer"] = "hap"
    stale_manual = next(
        row
        for row in rows
        if row["claim_id"] not in {kept_claim.claim_id, stale_identity_only["claim_id"]}
    )
    stale_manual["reviewer"] = "hap"
    stale_manual["manual_claim_text"] = "reviewed stale claim"
    stale_manual["claim_correct"] = False
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = merge_candidate_claims_into_review_template(
        tmp_path,
        candidate_claims=[kept_claim],
    )
    merged = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    merged_ids = {row["claim_id"] for row in merged}

    assert result["manual_fields_preserved"] is True
    assert kept_claim.claim_id in merged_ids
    assert stale_identity_only["claim_id"] not in merged_ids
    assert stale_manual["claim_id"] in merged_ids
    merged_by_id = {row["claim_id"]: row for row in merged}
    assert merged_by_id[kept_claim.claim_id]["proposed_candidate_current"] is True
    assert merged_by_id[stale_manual["claim_id"]]["proposed_candidate_current"] is False


def test_gold_review_starter_skips_unreviewable_candidates_and_caps_source(
    tmp_path: Path,
):
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(1, 6):
        rows.append(
            {
                "claim_id": f"GOLD-SRC-001-{index:03d}",
                "document_id": "SRC-001",
                "source_id": "SRC-001",
                "source_span_id": "SRC-001:abstract",
                "gold_set_domain": "semiconductor",
                "proposed_claim_text": f"若AI算力需求持续增长，半导体板块有望跑赢市场 {index}。",
                "proposed_cause_variables": ["ai_compute_demand"],
                "proposed_target_variables": ["semiconductor_storage_cycle"],
                "proposed_direction": "positive",
                "proposed_review_risk_flags": [],
                "manual_claim_text": "",
                "claim_correct": None,
                "source_span_supports_claim": None,
                "direction_correct": None,
                "target_correct": None,
                "horizon_correct": None,
                "variable_mapping_correct": None,
                "unsupported_field_false_grounded": None,
                "reviewer": "",
                "review_date": "",
                "review_notes": "",
            }
        )
    rows[1]["proposed_review_risk_flags"] = ["candidate_unavailable"]
    rows[1]["proposed_claim_text"] = (
        "Candidate extraction did not find a source-grounded mechanism sentence; manual claim required."
    )
    rows[4]["proposed_claim_text"] = "本报告中的信息、建议等均仅供参考，不构成投资建议。"
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = write_gold_review_starter(tmp_path, force=True, gold_batch_size=50)
    exported = [
        json.loads(line)
        for line in (tmp_path / result.path).read_text(encoding="utf-8").splitlines()
    ]

    assert [row["claim_id"] for row in exported] == [
        "GOLD-SRC-001-001",
    ]


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


def test_gold_candidate_claims_dedupes_report_claims_and_uses_nonduplicate_fallback(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    source_id = review_rows[0]["source_id"]
    same_source_rows = [row for row in review_rows if row["source_id"] == source_id]
    assert len(same_source_rows) >= 2
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    report_claim_path.write_text(
        "".join(
            json.dumps(
                {
                    "claim_provenance": "source_grounded",
                    "claim_text": "若政策支持延续，行业景气有望提升。",
                    "direction": "positive",
                    "extraction_quality": {"mapping_gaps": []},
                    "forecast_claim_id": f"FC-DUP-{index}",
                    "forecast_testability": "testable",
                    "forecast_type": "industry_outlook",
                    "metric_proxy_mapping": ["industry_policy_catalyst"],
                    "source_id": source_id,
                    "source_span_ids": [f"{source_id}:original_markdown:chunk-001"],
                    "target": {"target_id": "industry_etf_forward_return"},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for index in range(2)
        ),
        encoding="utf-8",
    )
    markdown_path = tmp_path / ".mosaic/rke/report_intelligence/markdown" / f"{source_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        "若政策支持延续，行业景气有望提升。"
        "若订单需求修复且库存下降，行业盈利有望改善。",
        encoding="utf-8",
    )
    (tmp_path / "registry/report_intelligence/report_metadata.jsonl").write_text(
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
    by_id = {claim.claim_id: claim for claim in claims}
    first_claim = by_id[same_source_rows[0]["claim_id"]]
    second_claim = by_id[same_source_rows[1]["claim_id"]]

    assert first_claim.claim_text == "若政策支持延续，行业景气有望提升。"
    assert "original_markdown_forecast_claim" in first_claim.review_risk_flags
    assert second_claim.claim_text == "若订单需求修复且库存下降，行业盈利有望改善。"
    assert "original_markdown_sentence_fallback" in second_claim.review_risk_flags


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


def test_gold_candidate_claims_skip_generic_risk_enumeration_report_claims(tmp_path: Path):
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
                "claim_text": "1、政策落地不及预期；",
                "direction": "negative",
                "extraction_quality": {"mapping_gaps": []},
                "forecast_claim_id": "FC-RISK-ENUM-001",
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

    assert first_claim.claim_text != "1、政策落地不及预期；"
    assert "original_markdown_forecast_claim" not in first_claim.review_risk_flags


def test_gold_candidate_claims_skip_unprefixed_generic_risk_list_report_claims(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    risk_text = "存在模型和经验测算判断误差、假设与实际偏离、宏观经济修复不及预期、外部事件超预期恶化、不良资产大面积暴露等风险。"
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    report_claim_path.write_text(
        json.dumps(
            {
                "claim_provenance": "source_grounded",
                "claim_text": risk_text,
                "direction": "negative",
                "extraction_quality": {"mapping_gaps": []},
                "forecast_claim_id": "FC-RISK-LIST-001",
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

    assert first_claim.claim_text != risk_text
    assert "original_markdown_forecast_claim" not in first_claim.review_risk_flags


def test_gold_candidate_claims_skip_disclaimer_and_rating_definition_report_claims(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    boilerplate_claims = [
        "理财产品业绩比较基准及过往业绩并不预示其未来表现，亦不构成投资建议，不代表推介。",
        "<table><tr><td>公司评级</td><td>行业评级</td></tr><tr><td>强烈推荐</td><td>预期未来6个月内股价相对市场基准指数升幅在15%以上</td></tr></table>",
    ]
    report_claim_path.write_text(
        "".join(
            json.dumps(
                {
                    "claim_provenance": "source_grounded",
                    "claim_text": claim_text,
                    "direction": "neutral",
                    "extraction_quality": {"mapping_gaps": []},
                    "forecast_claim_id": f"FC-BOILERPLATE-{index}",
                    "forecast_testability": "testable",
                    "forecast_type": "source_context_requires_review",
                    "metric_proxy_mapping": ["industry_policy_catalyst"],
                    "source_id": source_id,
                    "source_span_ids": [f"{source_id}:original_markdown:chunk-001"],
                    "target": {"target_id": "industry_etf_forward_return"},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for index, claim_text in enumerate(boilerplate_claims, 1)
        ),
        encoding="utf-8",
    )

    claims = build_gold_candidate_claims(tmp_path)
    first_claim = next(claim for claim in claims if claim.claim_id == first_review["claim_id"])

    assert first_claim.claim_text not in boilerplate_claims
    assert "original_markdown_forecast_claim" not in first_claim.review_risk_flags


def test_gold_candidate_claims_skip_rating_forecast_type_report_claims(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    report_claim_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    report_claim_path.parent.mkdir(parents=True, exist_ok=True)
    rating_text = "首次覆盖，给予买入评级。"
    report_claim_path.write_text(
        json.dumps(
            {
                "claim_provenance": "source_grounded",
                "claim_text": rating_text,
                "direction": "positive",
                "extraction_quality": {"mapping_gaps": []},
                "forecast_claim_id": "FC-RATING-TYPE-001",
                "forecast_testability": "testable",
                "forecast_type": "rating",
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

    assert first_claim.claim_text != rating_text
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


def test_gold_candidate_claims_skip_disclaimer_and_rating_definition_markdown_sentences(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    review_rows = [json.loads(line) for line in review_path.read_text(encoding="utf-8").splitlines()]
    first_review = review_rows[0]
    source_id = first_review["source_id"]
    markdown_text = (
        "理财产品业绩比较基准及过往业绩并不预示其未来表现，亦不构成投资建议，不代表推介。\n"
        "<table><tr><td>公司评级</td><td>行业评级</td></tr><tr><td>看淡</td>"
        "<td>预期未来6个月内行业指数弱于市场指数5%以上</td></tr></table>\n"
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
    assert "不构成投资建议" not in first_claim.claim_text
    assert "行业评级" not in first_claim.claim_text


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

    assert 50 <= len(claims) <= 150
    assert merge_result["applied"] is False
    assert merge_result["rows"] == review_count + 1
    assert f"gold-set review row must be object at row(s): {review_count + 1}" in merge_result["blockers"]
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == len(claims)
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

    assert 50 <= len(claims) <= 150
    assert merge_result["applied"] is False
    assert merge_result["rows"] == review_count + 1
    assert any(
        f"gold-set review row {review_count + 1} must contain valid JSON" in blocker
        for blocker in merge_result["blockers"]
    )
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == len(claims)
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

    assert 50 <= len(claims) <= 150
    assert merge_result["applied"] is False
    assert any("claim_variable_vocabulary.json must contain valid JSON" in blocker for blocker in merge_result["blockers"])
    assert review_path.read_text(encoding="utf-8") == original_review
    assert summary["candidate_claim_count"] == len(claims)
    assert summary["missing_variable_mapping_count"] == len(claims)
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

    assert 50 <= len(claims) <= 150
    assert summary["candidate_claim_count"] == len(claims)
    assert 0 < summary["review_rows_with_candidate_fields"] <= len(claims)
    assert summary["manual_fields_preserved"] is True
    merged_rows = [
        json.loads(line)
        for line in (tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(merged_rows) == summary["review_rows_with_candidate_fields"]
    assert all(gold_candidate_reviewable(row) for row in merged_rows)
    assert review_row["proposed_claim_text"]
    assert review_row["manual_claim_text"] == ""
