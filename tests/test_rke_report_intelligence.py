from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from mosaic.rke.cli import main
from mosaic.rke.registry_manifest import PRIVATE_LOCAL_REGISTRY_FILES
from mosaic.rke.temp_paths import RKE_OPERATOR_TMP_ENV_PREFIX
from mosaic.rke.report_intelligence import (
    ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_IMPORT_REPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH,
    ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH,
    DEFAULT_MINERU_ARGS_TEMPLATE,
    DEFAULT_VLLM_TIMEOUT_SECONDS,
    MAX_STORED_CLAIM_TEXT_CHARS,
    MineruBatchConversionTask,
    ReportIntelligenceConfig,
    REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS,
    build_analysis_recipes,
    build_report_intelligence_pit_leakage_audit,
    apply_analytical_footprint_review_import,
    build_confidence_impact_monitor,
    build_confidence_impact_observations,
    build_analytical_footprint_review_evidence,
    build_analytical_footprint_review_summary,
    build_local_macro_strategy_report_sources,
    build_markdown_coverage_summary,
    build_prompt_mutation_candidates,
    build_industry_etf_proxy_outcome_labels,
    build_industry_etf_proxy_readiness,
    build_report_intelligence_evolution_readiness_gate,
    build_method_performance_profiles,
    build_outcome_labeling_readiness_report,
    build_recipe_paper_trading_runs,
    build_recipe_paper_trading_summary,
    build_report_intelligence_extraction_provenance_audit,
    build_source_performance_profiles,
    build_data_acquisition_proposals,
    build_tool_design_proposals,
    build_viewpoint_performance_profiles,
    build_weighted_research_contexts,
    call_vllm_extractor,
    classify_tool_coverage,
    convert_pdfs_with_mineru_batch,
    merge_report_intelligence_batch_outputs,
    prepare_analytical_footprint_review_import,
    run_report_intelligence_refresh,
    run_report_intelligence_derived_refresh,
    write_analytical_footprint_review_assist,
    write_analytical_footprint_review_evidence,
    write_report_intelligence_evolution_readiness_gate,
    write_report_intelligence_patch_v1_5_coverage_report,
    _append_evolution_history_record,
    _append_unique_method_patterns,
    _backfill_tool_gaps_from_metric_candidates,
    _context_seed_indicator_mentions,
    _direct_pit_binding_gap_details,
    _entry_calendar_index,
    _read_industry_etf_proxy_map_rows,
    _markdown_quality_gap,
    _normalize_indicator_mentions,
    _normalize_method_patterns,
    _normalize_forecast_claims,
    _max_non_positive_after_cost_exit_date_streak,
    _tail_non_positive_after_cost_exit_date_streak,
    _paper_trading_chronological_split_metrics,
    _paper_trading_train_oos_split_items,
    _select_report_forecast_claims,
    _user_prompt,
    _refresh_analytical_footprint_indicator_governance,
    _refresh_forecast_mapping_governance,
    _infer_claim_component_roles,
    _infer_claim_mechanism_roles,
    _infer_report_temporal_context_from_markdown,
)


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_report_intelligence_entry_calendar_index_uses_explicit_lag():
    calendar = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]

    assert (
        _entry_calendar_index(
            calendar,
            "2026-01-02T15:00:00+08:00",
            entry_lag_trading_days=1,
        )
        == 1
    )
    assert (
        _entry_calendar_index(
            calendar,
            "2026-01-02T15:00:00+08:00",
            entry_lag_trading_days=2,
        )
        == 2
    )


def test_call_vllm_extractor_sends_authorization_header(monkeypatch):
    seen: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "forecast_claims": [],
                                        "analytical_footprints": [],
                                        "metric_candidates": [],
                                        "method_patterns": [],
                                        "tool_gaps": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def _fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(
        "mosaic.rke.report_intelligence.urllib.request.urlopen",
        _fake_urlopen,
    )

    result = call_vllm_extractor(
        {
            "source_id": "SRC-1",
            "title": "测试报告",
            "publish_date": "2024-01-02",
        },
        "原文 Markdown",
        "SRC-1:chunk-1",
        0,
        1,
        base_url="https://example.test/v1",
        model="mimo-v2.5-pro",
        api_key="secret-token",
    )

    assert result["status"] == "ok"
    assert result["model"] == "mimo-v2.5-pro"
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer secret-token"
    assert seen["payload"]["model"] == "mimo-v2.5-pro"


def test_user_prompt_requires_context_synthesized_forecast_claims():
    prompt = _user_prompt(
        {
            "source_id": "SRC-PROMPT",
            "title": "测试报告",
            "publish_date": "2026-06-11",
        },
        "股债市场双向波动，理财子通过多资产组合应对波动并获取超额收益。",
        "SRC-PROMPT:chunk-1",
        0,
        1,
    )

    assert "compact synthesis over the full supported report context" in prompt
    assert "does not need to be a verbatim sentence" in prompt
    assert "For Chinese source text, output claim_text in Chinese" in prompt
    assert "under <macro regime if present>" in prompt
    assert "finance-relevant target impact" in prompt
    assert "analytical_footprints, not forecast_claims" in prompt
    assert "pure historical/statistical descriptions" in prompt
    assert "Check report temporal context before leaving horizon empty" in prompt
    assert "90/180/360 days" in prompt
    assert "2026-2028年" in prompt
    assert "metric_proxy_mapping" in prompt
    assert "stock_forward_return" in prompt
    assert "Do not merge macro regime, industry-cycle regime" in prompt
    assert "company labs reaching designed utilization" in prompt
    assert "Make the economic mechanism explicit" in prompt
    assert "price/cost pass-through" in prompt
    assert "macro regime" in prompt
    assert "Emit at most two forecast_claims for this chunk" in prompt
    assert "Prefer fewer, higher value claims" in prompt
    assert "do not leave indicator_mentions empty" in prompt
    assert "canonical metric candidate" in prompt
    assert "industry-cycle regime" in prompt
    assert "rate-cut cycle" in prompt
    assert "global copper supply is structurally tight" in prompt


def test_user_prompt_includes_stock_subject_metadata_for_stock_reports():
    prompt = _user_prompt(
        {
            "source_id": "SRC-STOCK-SUBJECT",
            "title": "方大新材点评报告",
            "publish_date": "2026-06-11",
            "report_type": "个股研报",
            "ts_code": "920163.BJ",
            "abstract": "方大新材(920163)\n高端复合材料业务持续放量。",
        },
        "公司高端复合材料业务持续放量，预计2026-2028年利润增长。",
        "SRC-STOCK-SUBJECT:chunk-1",
        0,
        1,
    )

    assert '"stock_subject"' in prompt
    assert "方大新材" in prompt
    assert "920163.BJ" in prompt
    assert "Do not output a stock forecast_claim whose subject is only 公司" in prompt


def test_user_prompt_includes_report_context_metadata():
    prompt = _user_prompt(
        {
            "source_id": "SRC-CONTEXT",
            "title": "2026年度宏观策略",
            "publish_date": "2025-11-24",
            "report_context": {
                "benchmark_context": {
                    "default_benchmark": {
                        "benchmark_type": "market_index",
                        "benchmark_id": "沪深300",
                    }
                },
                "rating_context": {"rating_terms": ["买入"]},
            },
            "section_context": {"section_title": "展望2026年"},
        },
        "展望2026年，A股风险偏好有望修复。",
        "SRC-CONTEXT:chunk-1",
        0,
        1,
    )

    assert '"report_context"' in prompt
    assert '"section_context"' in prompt
    assert "沪深300" in prompt
    assert "展望2026年" in prompt


def test_select_report_forecast_claims_caps_and_preserves_source_order():
    def claim(
        claim_id: str,
        *,
        provenance: str = "unknown",
        testability: str = "insufficient_mapping",
        direction: str = "ambiguous",
        target_id: str = "unknown",
        preferred_days: int | None = None,
        metrics: tuple[str, ...] = (),
        mechanism: bool = False,
        impact: bool = False,
        regime: bool = False,
        conviction: str = "unknown",
    ) -> dict[str, object]:
        return {
            "forecast_claim_id": claim_id,
            "claim_provenance": provenance,
            "forecast_testability": testability,
            "direction": direction,
            "target": {"target_id": target_id},
            "horizon": (
                {"preferred_days": preferred_days} if preferred_days is not None else {}
            ),
            "metric_proxy_mapping": list(metrics),
            "source_conviction": conviction,
            "extraction_quality": {
                "claim_component_roles": {"has_regime_context": regime},
                "claim_mechanism_roles": {
                    "has_economic_mechanism": mechanism,
                    "mechanism_connects_to_evaluable_impact": impact,
                },
            },
        }

    records = [
        claim("weak-early"),
        claim(
            "strong-1",
            provenance="source_grounded",
            testability="testable",
            direction="positive",
            target_id="000001.SZ",
            preferred_days=60,
            metrics=("stock_forward_return",),
            mechanism=True,
            impact=True,
            regime=True,
            conviction="high",
        ),
        claim(
            "strong-2",
            provenance="source_grounded",
            testability="testable",
            direction="negative",
            target_id="000002.SZ",
            preferred_days=20,
            metrics=("stock_forward_return",),
            mechanism=True,
            impact=True,
            regime=True,
            conviction="medium",
        ),
        claim(
            "partial",
            provenance="source_grounded",
            target_id="000003.SZ",
            preferred_days=5,
        ),
        claim(
            "strong-3",
            provenance="source_grounded",
            testability="testable",
            direction="positive",
            target_id="有色金属",
            preferred_days=120,
            metrics=("industry_etf_forward_return",),
            mechanism=True,
            impact=True,
            conviction="medium",
        ),
        claim(
            "strong-4",
            provenance="source_grounded",
            testability="testable",
            direction="negative",
            target_id="铜",
            preferred_days=120,
            metrics=("commodity_spot_price",),
            mechanism=True,
            impact=True,
            regime=True,
            conviction="low",
        ),
        claim(
            "direction-only",
            provenance="source_grounded",
            testability="testable",
            direction="positive",
        ),
        claim(
            "strong-5",
            provenance="source_grounded",
            testability="testable",
            direction="positive",
            target_id="云计算",
            preferred_days=60,
            metrics=("industry_etf_forward_return",),
            regime=True,
            conviction="high",
        ),
    ]

    selected = _select_report_forecast_claims(records)

    assert [row["forecast_claim_id"] for row in selected] == [
        "strong-1",
        "strong-2",
        "strong-3",
        "strong-4",
        "strong-5",
    ]


def test_report_intelligence_caps_forecast_claims_per_report(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": (
                            f"在需求改善和成本下降带动下，测试行业{i}盈利有望提升，"
                            "并带来行业ETF相对收益改善。"
                        ),
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "sector_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": f"测试行业{i}",
                        },
                        "direction": "positive",
                        "horizon": {"preferred_days": 60},
                        "metric_proxy_mapping": ["industry_etf_forward_return"],
                        "source_conviction": "medium",
                    }
                    for i in range(7)
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.forecast_claim_rows == 5
    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert [row["target"]["target_id"] for row in forecasts] == [
        "测试行业0",
        "测试行业1",
        "测试行业2",
        "测试行业3",
        "测试行业4",
    ]


def test_refresh_forecast_mapping_governance_caps_existing_rows_per_report():
    def claim(report_id: str, index: int) -> dict[str, object]:
        return {
            "forecast_claim_id": f"{report_id}-{index}",
            "report_id": report_id,
            "source_id": report_id,
            "claim_text": (
                f"在需求改善和成本下降带动下，{report_id}测试行业{index}"
                "盈利预计改善，未来股价有望上涨。"
            ),
            "claim_provenance": "source_grounded",
            "forecast_testability": "testable",
            "forecast_type": "stock_outlook",
            "target": {"target_type": "stock", "target_id": f"00000{index}.SZ"},
            "benchmark": {"benchmark_id": "SH510300"},
            "direction": "positive",
            "horizon": {"preferred_days": 60},
            "metric_proxy_mapping": ["stock_forward_return"],
            "source_conviction": "medium",
            "extraction_quality": {},
            "signal_datetime": "2026-06-01",
        }

    rows = [claim("R1", index) for index in range(7)] + [
        claim("R2", index) for index in range(6)
    ]

    refreshed = _refresh_forecast_mapping_governance(rows)

    assert [row["forecast_claim_id"] for row in refreshed] == [
        "R1-0",
        "R1-1",
        "R1-2",
        "R1-3",
        "R1-4",
        "R2-0",
        "R2-1",
        "R2-2",
        "R2-3",
        "R2-4",
    ]


def test_refresh_forecast_mapping_governance_keeps_structured_stock_rating_claim():
    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-RATING",
                "report_id": "RPT-RATING",
                "source_id": "SRC-RATING",
                "claim_text": "维持买入",
                "claim_provenance": "source_grounded",
                "forecast_testability": "insufficient_mapping",
                "forecast_type": "investment_rating",
                "target": {"target_type": "stock", "target_id": "603380.SH"},
                "benchmark": {
                    "benchmark_type": "broad_market",
                    "benchmark_id": "沪深300",
                },
                "direction": "positive",
                "horizon": {},
                "metric_proxy_mapping": ["stock_forward_return"],
                "source_conviction": "medium",
                "extraction_quality": {},
                "signal_datetime": "2025-01-01",
            }
        ]
    )

    assert [row["forecast_claim_id"] for row in refreshed] == ["FC-RATING"]
    assert refreshed[0]["target"] == {"target_type": "stock", "target_id": "603380.SH"}
    assert refreshed[0]["metric_proxy_mapping"] == ["stock_forward_return"]
    assert refreshed[0]["forecast_testability"] == "insufficient_mapping"
    assert "horizon" in refreshed[0]["extraction_quality"]["mapping_gaps"]


def test_refresh_forecast_mapping_governance_binds_stock_subject_from_metadata():
    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-OLD",
                "claim_id": "CLAIM-OLD",
                "report_id": "RPT-STOCK-SUBJECT-REFRESH",
                "source_id": "SRC-STOCK-SUBJECT-REFRESH",
                "source_span_ids": ["SRC-STOCK-SUBJECT-REFRESH:chunk-001"],
                "claim_text": (
                    "在复合材料行业需求改善、公司高端产品放量的背景下，"
                    "公司预计2026-2028年收入和归母净利润将保持增长。"
                ),
                "claim_provenance": "source_grounded",
                "forecast_testability": "testable",
                "forecast_type": "earnings",
                "target": {"target_id": "920163.BJ"},
                "benchmark": {"benchmark_type": "broad_market"},
                "direction": "positive",
                "horizon": {},
                "metric_proxy_mapping": ["earnings_growth"],
                "source_conviction": "medium",
                "extraction_quality": {},
                "signal_datetime": "2026-06-11",
            }
        ],
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-SUBJECT-REFRESH",
                "stock_subject": {
                    "target_id": "920163.BJ",
                    "target_name": "方大新材",
                    "subject_label": "方大新材（920163.BJ）",
                },
            }
        ],
    )

    assert len(refreshed) == 1
    record = refreshed[0]
    assert "方大新材（920163.BJ）" in record["claim_text"]
    assert record["target"]["target_type"] == "stock"
    assert record["target"]["target_name"] == "方大新材"
    assert record["forecast_claim_id"] != "FC-OLD"
    assert record["claim_id"] != "CLAIM-OLD"
    assert record["extraction_quality"]["stock_subject_bound_from_metadata"] is True


def test_refresh_forecast_mapping_governance_drops_rating_definition_table():
    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-RATING-DEFINITION",
                "report_id": "RPT-RATING-DEFINITION",
                "source_id": "SRC-RATING-DEFINITION",
                "claim_text": (
                    "<table><tr><td>公司评级</td><td>买入：预期未来6个月内"
                    "股价相对市场基准指数涨幅在20%以上</td></tr></table>"
                ),
                "claim_provenance": "source_grounded",
                "forecast_testability": "testable",
                "forecast_type": "rating_definition",
                "target": {"target_type": "stock", "target_id": "603380.SH"},
                "benchmark": {"benchmark_type": "broad_market"},
                "direction": "positive",
                "horizon": {"preferred_days": 120},
                "metric_proxy_mapping": ["stock_forward_return"],
                "source_conviction": "medium",
                "extraction_quality": {},
                "signal_datetime": "2025-01-01",
            }
        ]
    )

    assert refreshed == []


def test_normalize_forecast_claims_filters_boilerplate_and_descriptive_facts():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": "风险提示：宏观经济、货币政策超预期变化、数据误差等风险。",
                    "claim_provenance": "source_grounded",
                },
                {
                    "claim_text": "1、政策落地不及预期；",
                    "claim_provenance": "source_grounded",
                    "direction": "negative",
                    "forecast_testability": "testable",
                    "forecast_type": "risk_warning",
                    "metric_proxy_mapping": ["industry_policy_catalyst"],
                    "target": {"target_id": "有色金属", "target_type": "sector"},
                },
                {
                    "claim_text": "黑钨精矿65%国产的价格涨跌幅为600%。",
                    "claim_provenance": "source_grounded",
                },
                {
                    "claim_text": (
                        "在医院业务扩张需求下，通过构建数据资源中心，"
                        "预期将提升管理决策效率、医疗服务质量和患者就医体验。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "target": {"target_id": "IT服务Ⅱ", "target_type": "sector"},
                },
                {
                    "claim_text": (
                        "通过开发自动数据上报平台，预期将综合上报效率提升90%，"
                        "错误率下降，时间周期缩短，从而降低人工成本。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "target": {"target_id": "IT服务Ⅱ", "target_type": "sector"},
                },
                {
                    "claim_text": (
                        "建议租赁公司健全合规管理体系，加强租赁物全生命周期管理，"
                        "完善租赁物估值、监控和处置体系。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "target": {"target_id": "多元金融", "target_type": "sector"},
                },
                {
                    "claim_text": "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。",
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "forecast_type": "sector_outlook",
                    "horizon": {"max_days": 60, "unit": "trading_day"},
                    "metric_proxy_mapping": ["commodity_price_cycle"],
                    "target": {"target_id": "有色金属", "target_type": "sector"},
                },
            ]
        },
        {
            "source_id": "SRC-CLAIM-FILTER",
            "publish_date": "2026-06-11",
        },
        run_id="RUN-CLAIM-FILTER",
        model="fake-vllm",
        report_id="RPT-CLAIM-FILTER",
        chunk_span_id="SRC-CLAIM-FILTER:chunk-1",
    )

    assert [record["claim_text"] for record in records] == [
        "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。"
    ]


def test_normalize_forecast_claims_keeps_long_risk_regime_mechanism_claims():
    claim_text = (
        "在监管政策趋严、息差收窄、信用风险暴露及行业竞争加剧的背景下，"
        "租赁公司通过向产业化业务转型并强化资产筛选机制，有望改善资产质量并提升盈利韧性。"
    )

    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": claim_text,
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "forecast_type": "sector_outlook",
                    "metric_proxy_mapping": ["industry_etf_forward_return"],
                    "target": {"target_id": "多元金融", "target_type": "sector"},
                }
            ]
        },
        {
            "source_id": "SRC-LONG-RISK-REGIME",
            "publish_date": "2026-06-11",
        },
        run_id="RUN-LONG-RISK-REGIME",
        model="fake-vllm",
        report_id="RPT-LONG-RISK-REGIME",
        chunk_span_id="SRC-LONG-RISK-REGIME:chunk-1",
    )

    assert [record["claim_text"] for record in records] == [claim_text]


def test_normalize_forecast_claims_infers_horizon_and_metric_proxy_mapping():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": (
                        "在金属材料检测行业需求持续增长、公司全国布局实验室投产达效的背景下，"
                        "公司预计2026-2028年营业收入和归母净利润将保持增长，维持买入评级。"
                    ),
                    "analyst_claim": (
                        "在行业需求增长和公司实验室投产达效背景下，"
                        "300797.SZ的收入与利润预计在2026-2028年继续增长。"
                    ),
                    "pre_review_decision": "include",
                    "pre_review_reason": "机制、公司能力、盈利影响和期限均完整。",
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "forecast_type": "earnings",
                    "horizon": {},
                    "metric_proxy_mapping": [],
                    "target": {"target_id": "300797.SZ", "target_type": "stock"},
                    "benchmark": {
                        "benchmark_id": "SH510300",
                        "benchmark_type": "broad_market",
                    },
                }
            ]
        },
        {
            "source_id": "SRC-MAPPING-INFER",
            "publish_date": "2026-06-11",
        },
        run_id="RUN-MAPPING-INFER",
        model="fake-vllm",
        report_id="RPT-MAPPING-INFER",
        chunk_span_id="SRC-MAPPING-INFER:chunk-1",
    )

    assert len(records) == 1
    record = records[0]
    assert record["forecast_testability"] == "testable"
    assert record["analyst_claim"].startswith("在行业需求增长和公司实验室投产达效背景下")
    assert record["pre_review"]["decision"] == "include"
    assert record["pre_review"]["perspective"] == "financial_practitioner"
    assert record["pre_review"]["quality_checks"]["analyst_claim_adjusted"] is True
    assert (
        record["pre_review"]["claim_regime_trace_policy"]
        == "background_only_not_claim_validation"
    )
    assert record["horizon"]["max_days"] > 900
    assert record["horizon"]["source_text"] == "2026-2028年"
    component_roles = record["extraction_quality"]["claim_component_roles"]
    details = component_roles.pop("as_of_date_macro_regime_context_details")
    assert component_roles == {
        "has_regime_context": True,
        "has_macro_regime_context": True,
        "has_industry_cycle_regime_context": True,
        "regime_context_types": [
            "us_rate_cut_cycle",
            "china_monetary_easing_cycle",
            "rmb_fx_stability_window",
            "industry_demand_growth",
        ],
        "macro_regime_context_types": [
            "us_rate_cut_cycle",
            "china_monetary_easing_cycle",
            "rmb_fx_stability_window",
        ],
        "source_text_macro_regime_context_types": [],
        "as_of_date_macro_regime_context_types": [
            "us_rate_cut_cycle",
            "china_monetary_easing_cycle",
            "rmb_fx_stability_window",
        ],
        "macro_regime_context_sources": {
            "us_rate_cut_cycle": (
                "as_of_date:2026-06-11; US policy-rate cycle remained in a "
                "post-cut/easing-evaluation window after 2025 cuts"
            ),
            "china_monetary_easing_cycle": (
                "as_of_date:2026-06-11; China monetary policy remained in a "
                "moderately loose support window in 2026"
            ),
            "rmb_fx_stability_window": (
                "as_of_date:2026-06-11; RMB exchange-rate policy remained in a "
                "managed-stability window in 2026"
            ),
        },
        "industry_cycle_regime_context_types": ["industry_demand_growth"],
        "has_company_capability_or_action": True,
        "has_market_or_fundamental_impact": True,
        "target_type": "stock",
        "mixed_regime_and_company_capability": True,
        "role_policy": (
            "separate_macro_regime_industry_cycle_regime_company_capability_"
            "mechanism_and_impact"
        ),
        "as_of_regime_policy": (
            "macro regime may be inferred from PIT as_of_datetime; industry-cycle "
            "regime must be source-text derived"
        ),
    }
    assert details[0]["regime_id"] == "MACRO-REGIME-US-RATE-CUT-20260101"
    assert details[0]["regime_type"] == "us_rate_cut_cycle"
    assert details[0]["as_of_date"] == "2026-06-11"
    assert details[0]["source_basis"] == "as_of_date"
    assert details[0]["source_text_grounded"] is False
    regime_trace = record["claim_regime_trace"]
    assert regime_trace["schema_version"] == "claim_regime_trace_v1"
    assert regime_trace["as_of_date"] == "2026-06-11"
    assert regime_trace["macro"]["macro.central_bank"]["as_of_date_regime_types"] == (
        "us_rate_cut_cycle",
        "china_monetary_easing_cycle",
    )
    assert regime_trace["macro"]["macro.volatility"]["background_only"] is True
    assert regime_trace["macro"]["macro.volatility"]["regime_types"] == ()
    assert "validate claim correctness" in regime_trace["policy"]
    mechanism = record["extraction_quality"]["claim_mechanism_roles"]
    assert set(mechanism["channels"]) >= {
        "demand_pull",
        "capacity_release_or_supply",
    }
    assert "expand_capacity_or_coverage" in mechanism["actions"]
    assert set(mechanism["impact_variables"]) >= {
        "demand_growth",
        "revenue_growth",
        "earnings_growth",
    }
    assert mechanism["has_economic_mechanism"] is True
    assert mechanism["mechanism_connects_to_evaluable_impact"] is True
    assert set(record["metric_proxy_mapping"]) >= {
        "demand_growth",
        "revenue_growth",
        "earnings_growth",
        "stock_forward_return",
    }
    assert "commodity_price_cycle" not in record["metric_proxy_mapping"]
    assert (
        record["extraction_quality"]["metric_proxy_mapping_inferred_from_claim_text"]
        is True
    )


def test_normalize_forecast_claims_filters_generic_price_from_commodity_proxy():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": (
                        "AI高容MLCC供需错配带动产品涨价和毛利率改善，"
                        "预计电子元件板块盈利上行。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "电子元件", "target_type": "sector"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "horizon": {},
                    "metric_proxy_mapping": [
                        "commodity_price_cycle",
                        "margin_profitability",
                    ],
                }
            ]
        },
        {
            "source_id": "SRC-GENERIC-PRICE-MAPPING",
            "publish_date": "2026-06-11",
        },
        run_id="RUN-GENERIC-PRICE-MAPPING",
        model="fake-vllm",
        report_id="RPT-GENERIC-PRICE-MAPPING",
        chunk_span_id="SRC-GENERIC-PRICE-MAPPING:chunk-1",
    )

    assert "commodity_price_cycle" not in records[0]["metric_proxy_mapping"]
    assert "liquidity_credit_condition" not in records[0]["metric_proxy_mapping"]
    assert "margin_profitability" in records[0]["metric_proxy_mapping"]


def test_normalize_forecast_claims_binds_stock_subject_from_report_metadata():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": (
                        "在复合材料行业需求改善、公司高端产品放量的背景下，"
                        "公司预计2026-2028年收入和归母净利润将保持增长。"
                    ),
                    "analyst_claim": (
                        "在行业需求改善和公司高端产品放量背景下，"
                        "公司收入与利润预计在2026-2028年继续增长。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "forecast_type": "earnings",
                    "horizon": {},
                    "metric_proxy_mapping": ["earnings_growth"],
                    "target": {"target_id": "920163.BJ"},
                }
            ]
        },
        {
            "source_id": "SRC-STOCK-SUBJECT-BIND",
            "publish_date": "2026-06-11",
            "report_type": "个股研报",
            "ts_code": "920163.BJ",
            "abstract": "方大新材(920163)\n高端复合材料业务持续放量。",
        },
        run_id="RUN-STOCK-SUBJECT-BIND",
        model="fake-vllm",
        report_id="RPT-STOCK-SUBJECT-BIND",
        chunk_span_id="SRC-STOCK-SUBJECT-BIND:chunk-1",
    )

    assert len(records) == 1
    record = records[0]
    assert "方大新材（920163.BJ）" in record["claim_text"]
    assert "方大新材（920163.BJ）" in record["analyst_claim"]
    assert record["target"]["target_type"] == "stock"
    assert record["target"]["target_name"] == "方大新材"
    assert record["extraction_quality"]["stock_target_bound_from_metadata"] is True
    assert record["extraction_quality"]["stock_subject_bound_from_metadata"] is True
    assert record["extraction_quality"]["claim_text_stock_subject_bound"] is True
    assert record["extraction_quality"]["analyst_claim_stock_subject_bound"] is True


def test_normalize_forecast_claims_infers_chinese_relative_and_qualitative_horizon():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": "行业未来三年需求增长有望推动景气度改善并带动板块跑赢市场。",
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "计算机", "target_type": "sector"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "horizon": {},
                },
                {
                    "claim_text": "长期供需格局改善将支撑商品价格中枢上行。",
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "铜", "target_type": "commodity"},
                    "benchmark": {"benchmark_type": "spot_price"},
                    "horizon": {},
                },
            ]
        },
        {
            "source_id": "SRC-HORIZON-INFER",
            "publish_date": "2026-06-11",
        },
        run_id="RUN-HORIZON-INFER",
        model="fake-vllm",
        report_id="RPT-HORIZON-INFER",
        chunk_span_id="SRC-HORIZON-INFER:chunk-1",
    )

    assert records[0]["horizon"]["max_days"] == 1096
    assert records[0]["horizon"]["source_text"] == "未来三年"
    assert set(records[0]["metric_proxy_mapping"]) >= {
        "demand_growth",
        "industry_prosperity",
        "industry_etf_forward_return",
        "relative_alpha",
    }
    assert records[1]["horizon"]["preferred_days"] == 120
    assert records[1]["horizon"]["source_text"] == "长期"
    assert set(records[1]["metric_proxy_mapping"]) >= {
        "commodity_price_cycle",
        "commodity_spot_price",
    }


def test_normalize_forecast_claims_prefers_forward_year_horizon_over_history():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": (
                        "公司2021-2025年收入CAGR较高，预计2026-2028年营业收入"
                        "和归母净利润继续增长。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "300797.SZ", "target_type": "stock"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "horizon": {},
                },
                {
                    "claim_text": "预计26-28年归母净利润分别增长，盈利能力持续改善。",
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "300797.SZ", "target_type": "stock"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "horizon": {},
                },
                {
                    "claim_text": (
                        "预计2027年公司净利润恢复增长，2028年盈利中枢进一步抬升。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "300797.SZ", "target_type": "stock"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "horizon": {},
                },
            ]
        },
        {
            "source_id": "SRC-FORWARD-HORIZON",
            "publish_date": "2026-06-11",
        },
        run_id="RUN-FORWARD-HORIZON",
        model="fake-vllm",
        report_id="RPT-FORWARD-HORIZON",
        chunk_span_id="SRC-FORWARD-HORIZON:chunk-1",
    )

    assert records[0]["horizon"]["source_text"] == "2026-2028年"
    assert records[0]["horizon"]["max_days"] > 900
    assert records[1]["horizon"]["source_text"] == "26-28年"
    assert records[1]["horizon"]["max_days"] > 900
    assert records[2]["horizon"]["source_text"] == "2028年"
    assert records[2]["horizon"]["max_days"] > 900


def test_normalize_forecast_claims_replaces_unreasonable_model_horizon():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": (
                        "受光纤、半导体等下游高增长需求拉动，预计2026年全球"
                        "半导体级氦气需求增长9%，需求高增长与供给紧缺在2026年内同时出现。"
                    ),
                    "claim_provenance": "source_grounded",
                    "direction": "positive",
                    "forecast_testability": "testable",
                    "target": {"target_id": "化学制品", "target_type": "sector"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "horizon": {"max_days": 739996, "unit": "calendar_day"},
                }
            ]
        },
        {
            "source_id": "SRC-UNREASONABLE-HORIZON",
            "publish_date": None,
        },
        run_id="RUN-UNREASONABLE-HORIZON",
        model="fake-vllm",
        report_id="RPT-UNREASONABLE-HORIZON",
        chunk_span_id="SRC-UNREASONABLE-HORIZON:chunk-1",
    )

    assert len(records) == 1
    assert records[0]["horizon"]["max_days"] == 365
    assert records[0]["horizon"]["invalid_model_horizon_replaced"] is True
    assert records[0]["extraction_quality"]["horizon_inferred_from_claim_text"] is True


def test_normalize_forecast_claims_inherits_report_level_stock_rating_horizon():
    report_level_horizon = {
        "max_days": 183,
        "unit": "calendar_day",
        "source": "report_level_rating_definition",
        "source_text": "未来6个月内",
    }
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": "维持公司买入评级，预计公司股价表现优于市场基准指数。",
                    "claim_provenance": "source_grounded",
                    "forecast_testability": "testable",
                    "forecast_type": "investment_rating",
                    "target": {"target_type": "stock", "target_id": "000001.SZ"},
                    "benchmark": {
                        "benchmark_type": "market_index",
                        "benchmark_id": "沪深300",
                    },
                    "direction": "positive",
                    "horizon": {},
                    "metric_proxy_mapping": ["stock_forward_return"],
                }
            ]
        },
        {
            "source_id": "SRC-REPORT-LEVEL-HORIZON",
            "publish_date": "2026-01-02",
        },
        run_id="RUN-REPORT-LEVEL-HORIZON",
        model="fake-vllm",
        report_id="RPT-REPORT-LEVEL-HORIZON",
        chunk_span_id="SRC-REPORT-LEVEL-HORIZON:chunk-1",
        report_level_horizon=report_level_horizon,
    )

    assert len(records) == 1
    assert records[0]["horizon"]["max_days"] == 183
    assert records[0]["horizon"]["source"] == "report_level_rating_definition"
    assert records[0]["horizon"]["inherited_from_report_level"] is True
    quality = records[0]["extraction_quality"]
    assert quality["horizon_inferred_from_report_level"] is True
    assert quality["report_level_horizon"]["source_text"] == "未来6个月内"
    assert "horizon_inferred_from_claim_text" not in quality


def test_normalize_forecast_claims_inherits_report_level_industry_horizon():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": "供需改善推动有色金属行业景气度上行，板块盈利有望改善。",
                    "claim_provenance": "source_grounded",
                    "forecast_testability": "testable",
                    "forecast_type": "industry_outlook",
                    "target": {"target_type": "sector", "target_id": "有色金属"},
                    "benchmark": {"benchmark_type": "broad_market"},
                    "direction": "positive",
                    "horizon": {},
                    "metric_proxy_mapping": ["industry_etf_forward_return"],
                }
            ]
        },
        {
            "source_id": "SRC-REPORT-LEVEL-INDUSTRY",
            "publish_date": "2026-01-02",
        },
        run_id="RUN-REPORT-LEVEL-INDUSTRY",
        model="fake-vllm",
        report_id="RPT-REPORT-LEVEL-INDUSTRY",
        chunk_span_id="SRC-REPORT-LEVEL-INDUSTRY:chunk-1",
        report_level_horizon={
            "max_days": 183,
            "unit": "calendar_day",
            "source": "report_level_rating_definition",
            "source_text": "未来6个月内",
        },
    )

    assert len(records) == 1
    assert records[0]["horizon"]["max_days"] == 183
    assert records[0]["horizon"]["source"] == "report_level_rating_definition"
    assert records[0]["extraction_quality"]["horizon_inferred_from_report_level"] is True
    assert "mapping_gaps" not in records[0]["extraction_quality"]


def test_normalize_forecast_claims_inherits_report_temporal_context_horizon():
    report_temporal_context = _infer_report_temporal_context_from_markdown(
        "# 2026年度宏观策略\n\n## 展望2026年\nA股风险偏好有望修复。",
        "2025-11-24",
        title="2026年度宏观策略",
        report_type="年度策略",
    )

    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": "政策宽松和风险偏好修复将支撑A股震荡上行。",
                    "claim_provenance": "source_grounded",
                    "forecast_testability": "testable",
                    "forecast_type": "macro_asset_outlook",
                    "target": {
                        "target_type": "macro_asset",
                        "target_id": "CN_A_SHARE_BROAD",
                    },
                    "benchmark": {"benchmark_type": "cash_zero_return"},
                    "direction": "positive",
                    "horizon": {},
                    "metric_proxy_mapping": ["macro_asset_forward_return"],
                }
            ]
        },
        {
            "source_id": "SRC-REPORT-TEMPORAL-CONTEXT",
            "publish_date": "2025-11-24",
        },
        run_id="RUN-REPORT-TEMPORAL-CONTEXT",
        model="fake-vllm",
        report_id="RPT-REPORT-TEMPORAL-CONTEXT",
        chunk_span_id="SRC-REPORT-TEMPORAL-CONTEXT:chunk-1",
        report_temporal_context=report_temporal_context,
    )

    assert len(records) == 1
    assert records[0]["horizon"]["source"] == "report_temporal_context"
    assert records[0]["horizon"]["source_text"] == "2026年"
    assert records[0]["horizon"]["inherited_from_report_context"] is True
    assert records[0]["extraction_quality"][
        "horizon_inferred_from_report_temporal_context"
    ] is True
    assert "mapping_gaps" not in records[0]["extraction_quality"]


def test_normalize_forecast_claims_records_report_and_section_context():
    records = _normalize_forecast_claims(
        {
            "forecast_claims": [
                {
                    "claim_text": "政策宽松和风险偏好修复将支撑A股震荡上行。",
                    "claim_provenance": "source_grounded",
                    "forecast_testability": "testable",
                    "forecast_type": "macro_asset_outlook",
                    "target": {
                        "target_type": "macro_asset",
                        "target_id": "CN_A_SHARE_BROAD",
                    },
                    "benchmark": {"benchmark_type": "cash_zero_return"},
                    "direction": "positive",
                    "horizon": {"max_days": 365, "unit": "calendar_day"},
                    "metric_proxy_mapping": ["macro_asset_forward_return"],
                }
            ]
        },
        {
            "source_id": "SRC-REPORT-CONTEXT",
            "publish_date": "2025-11-24",
        },
        run_id="RUN-REPORT-CONTEXT",
        model="fake-vllm",
        report_id="RPT-REPORT-CONTEXT",
        chunk_span_id="SRC-REPORT-CONTEXT:chunk-1",
        report_context={
            "subject_context": {"covered_asset_universe": ["A股"]},
            "benchmark_context": {
                "default_benchmark": {
                    "benchmark_type": "market_index",
                    "benchmark_id": "沪深300",
                }
            },
            "rating_context": {"rating_terms": ["买入"]},
            "frequency_context": {"frequency": "annual"},
        },
        section_context={"section_title": "展望2026年"},
    )

    context = records[0]["extraction_quality"]["report_context"]
    assert context["subject_context"]["covered_asset_universe"] == ["A股"]
    assert context["benchmark_context"]["default_benchmark"]["benchmark_id"] == "沪深300"
    assert context["rating_context"]["rating_terms"] == ["买入"]
    assert context["frequency_context"]["frequency"] == "annual"
    assert context["section_context"]["section_title"] == "展望2026年"


def test_refresh_forecast_mapping_governance_reads_report_level_horizon_from_markdown(
    tmp_path: Path,
):
    markdown_path = tmp_path / ".mosaic/rke/report_intelligence/markdown/SRC-RATING.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "公司评级 买入：预期未来6个月内股价相对市场基准指数涨幅在20%以上。",
        encoding="utf-8",
    )

    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-RATING-HORIZON",
                "report_id": "RPT-RATING-HORIZON",
                "source_id": "SRC-RATING-HORIZON",
                "claim_text": "维持买入评级，公司股价相对市场基准指数有望跑赢。",
                "claim_provenance": "source_grounded",
                "forecast_testability": "insufficient_mapping",
                "forecast_type": "investment_rating",
                "target": {"target_type": "stock", "target_id": "000001.SZ"},
                "benchmark": {
                    "benchmark_type": "market_index",
                    "benchmark_id": "沪深300",
                },
                "direction": "positive",
                "horizon": {},
                "metric_proxy_mapping": ["stock_forward_return"],
                "source_conviction": "medium",
                "extraction_quality": {},
                "signal_datetime": "2026-01-02",
            }
        ],
        metadata_rows=[
            {
                "source_id": "SRC-RATING-HORIZON",
                "publish_datetime": "2026-01-02T00:00:00+08:00",
                "markdown": {
                    "path": str(markdown_path.relative_to(tmp_path)),
                },
            }
        ],
        root_path=tmp_path,
    )

    assert len(refreshed) == 1
    assert refreshed[0]["horizon"]["max_days"] == 183
    assert refreshed[0]["horizon"]["source"] == "report_level_rating_definition"
    assert refreshed[0]["forecast_testability"] == "testable"
    assert "mapping_gaps" not in refreshed[0]["extraction_quality"]


def test_refresh_forecast_mapping_governance_reads_report_temporal_context(
    tmp_path: Path,
):
    markdown_path = tmp_path / ".mosaic/rke/report_intelligence/markdown/SRC-MACRO.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "# 2026年度宏观策略\n\n展望2026年，A股风险偏好有望修复。",
        encoding="utf-8",
    )

    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-MACRO-HORIZON",
                "report_id": "RPT-MACRO-HORIZON",
                "source_id": "SRC-MACRO-HORIZON",
                "claim_text": "政策宽松和风险偏好修复将支撑A股震荡上行。",
                "claim_provenance": "source_grounded",
                "forecast_testability": "insufficient_mapping",
                "forecast_type": "macro_asset_outlook",
                "target": {
                    "target_type": "macro_asset",
                    "target_id": "CN_A_SHARE_BROAD",
                },
                "benchmark": {"benchmark_type": "cash_zero_return"},
                "direction": "positive",
                "horizon": {},
                "metric_proxy_mapping": ["macro_asset_forward_return"],
                "source_conviction": "medium",
                "extraction_quality": {},
                "signal_datetime": "2025-11-24",
            }
        ],
        metadata_rows=[
            {
                "source_id": "SRC-MACRO-HORIZON",
                "publish_datetime": "2025-11-24T00:00:00+08:00",
                "title": "2026年度宏观策略",
                "report_type": "年度策略",
                "markdown": {
                    "path": str(markdown_path.relative_to(tmp_path)),
                },
            }
        ],
        root_path=tmp_path,
    )

    assert len(refreshed) == 1
    assert refreshed[0]["horizon"]["source"] == "report_temporal_context"
    assert refreshed[0]["horizon"]["source_text"] == "2026年"
    assert refreshed[0]["horizon"]["inherited_from_report_context"] is True
    assert refreshed[0]["extraction_quality"][
        "horizon_inferred_from_report_temporal_context"
    ] is True
    assert (
        refreshed[0]["extraction_quality"]["report_context"]["frequency_context"][
            "frequency"
        ]
        == "annual"
    )
    assert refreshed[0]["forecast_testability"] == "testable"
    assert "mapping_gaps" not in refreshed[0]["extraction_quality"]


def test_refresh_forecast_mapping_governance_records_report_context(
    tmp_path: Path,
):
    markdown_path = tmp_path / ".mosaic/rke/report_intelligence/markdown/SRC-CONTEXT.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "公司评级 买入：预期未来6个月内股价相对沪深300涨幅在20%以上。",
        encoding="utf-8",
    )

    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-CONTEXT",
                "report_id": "RPT-CONTEXT",
                "source_id": "SRC-CONTEXT",
                "claim_text": "维持公司买入评级，公司股价相对市场基准指数有望跑赢。",
                "claim_provenance": "source_grounded",
                "forecast_testability": "insufficient_mapping",
                "forecast_type": "investment_rating",
                "target": {"target_type": "stock", "target_id": "000001.SZ"},
                "benchmark": {
                    "benchmark_type": "market_index",
                    "benchmark_id": "沪深300",
                },
                "direction": "positive",
                "horizon": {},
                "metric_proxy_mapping": ["stock_forward_return"],
                "source_conviction": "medium",
                "extraction_quality": {},
                "signal_datetime": "2026-01-02",
            }
        ],
        metadata_rows=[
            {
                "source_id": "SRC-CONTEXT",
                "publish_datetime": "2026-01-02T00:00:00+08:00",
                "title": "平安银行点评报告",
                "report_type": "个股研报",
                "ts_code": "000001.SZ",
                "markdown": {
                    "path": str(markdown_path.relative_to(tmp_path)),
                },
            }
        ],
        root_path=tmp_path,
    )

    context = refreshed[0]["extraction_quality"]["report_context"]
    assert context["subject_context"]["covered_entity"]["target_id"] == "000001.SZ"
    assert context["benchmark_context"]["default_benchmark"]["benchmark_id"] == "沪深300"
    assert context["rating_context"]["rating_terms"] == ["买入"]


def test_refresh_forecast_mapping_governance_drops_stale_non_financial_claims():
    refreshed = _refresh_forecast_mapping_governance(
        [
            {
                "forecast_claim_id": "FC-STALE",
                "claim_text": (
                    "建议租赁公司健全合规管理体系，加强租赁物全生命周期管理，"
                    "完善租赁物估值、监控和处置体系。"
                ),
                "target": {"target_id": "多元金融", "target_type": "sector"},
                "benchmark": {"benchmark_type": "broad_market"},
                "direction": "positive",
                "horizon": {"max_days": 120},
                "forecast_testability": "testable",
            },
            {
                "forecast_claim_id": "FC-VALID",
                "claim_text": "若供给约束延续且库存继续下降，有色金属景气周期有望推动板块后续跑赢市场。",
                "target": {"target_id": "有色金属", "target_type": "sector"},
                "benchmark": {"benchmark_type": "broad_market"},
                "direction": "positive",
                "horizon": {"max_days": 120},
                "forecast_testability": "testable",
            },
        ]
    )

    assert [row["forecast_claim_id"] for row in refreshed] == ["FC-VALID"]


def test_infer_claim_mechanism_roles_covers_business_mix_and_overseas_channels():
    business_mix = _infer_claim_mechanism_roles(
        "公司高毛利配件业务占比提升，耗材属性凸显，有望推动公司利润持续增长。",
        target={"target_type": "stock", "target_id": "688392.SH"},
        metric_proxy_mapping=["earnings_growth", "margin_profitability"],
    )
    overseas = _infer_claim_mechanism_roles(
        "海外盈利优于国内，建议关注出海主线。",
        target={"target_type": "sector", "target_id": "汽车零部件"},
        metric_proxy_mapping=["margin_profitability"],
    )
    cost_efficiency = _infer_claim_mechanism_roles(
        "公司管理费用率下降并持续控制成本，提质增效有助于提升盈利能力。",
        target={"target_type": "stock", "target_id": "300797.SZ"},
        metric_proxy_mapping=["margin_profitability"],
    )

    assert "business_mix_shift" in business_mix["channels"]
    assert "shift_business_mix" in business_mix["actions"]
    assert business_mix["mechanism_connects_to_evaluable_impact"] is True
    assert "overseas_expansion" in overseas["channels"]
    assert "expand_overseas_market" in overseas["actions"]
    assert overseas["mechanism_connects_to_evaluable_impact"] is True
    assert "margin_expansion_or_pressure" in cost_efficiency["channels"]
    assert "optimize_cost_or_efficiency" in cost_efficiency["actions"]
    assert cost_efficiency["mechanism_connects_to_evaluable_impact"] is True


def test_infer_claim_component_roles_separates_macro_and_industry_regime():
    macro = _infer_claim_component_roles(
        "美国2024年9月开启降息周期，中国同时期开始加大货币政策逆周期调节力度，流动性改善有望推动高beta风格跑赢市场。",
        target={"target_type": "sector", "target_id": "有色金属"},
    )
    copper = _infer_claim_component_roles(
        "当前全球铜市场呈现供给长期偏紧、需求动能切换的格局，铜价中枢上行有望支撑有色板块景气度。",
        target={"target_type": "sector", "target_id": "工业金属"},
    )

    assert set(macro["macro_regime_context_types"]) >= {
        "us_rate_cut_cycle",
        "china_countercyclical_policy",
        "monetary_liquidity_condition",
    }
    assert macro["industry_cycle_regime_context_types"] == []
    assert macro["has_macro_regime_context"] is True
    assert macro["has_industry_cycle_regime_context"] is False
    assert set(copper["industry_cycle_regime_context_types"]) >= {
        "supply_tightness",
        "demand_transition",
        "price_cycle",
        "prosperity_cycle",
    }
    assert copper["macro_regime_context_types"] == []
    assert copper["has_macro_regime_context"] is False
    assert copper["has_industry_cycle_regime_context"] is True


def test_infer_claim_component_roles_adds_pit_as_of_macro_regime():
    roles = _infer_claim_component_roles(
        "公司加快推进数字化转型和智能化升级，有助于提质增效并支撑业绩增长。",
        target={"target_type": "stock", "target_id": "300797.SZ"},
        as_of_datetime="2025-06-05",
    )

    assert set(roles["macro_regime_context_types"]) >= {
        "us_rate_cut_cycle",
        "china_countercyclical_policy",
        "monetary_liquidity_condition",
    }
    assert roles["source_text_macro_regime_context_types"] == []
    assert set(roles["as_of_date_macro_regime_context_types"]) >= {
        "us_rate_cut_cycle",
        "china_countercyclical_policy",
        "monetary_liquidity_condition",
    }
    assert roles["has_macro_regime_context"] is True
    assert roles["has_regime_context"] is True
    assert roles["has_company_capability_or_action"] is True
    assert roles["macro_regime_context_sources"]["us_rate_cut_cycle"].startswith(
        "as_of_date:2025-06-05"
    )
    detail_by_type = {
        detail["regime_type"]: detail
        for detail in roles["as_of_date_macro_regime_context_details"]
    }
    assert detail_by_type["us_rate_cut_cycle"] == {
        "regime_id": "MACRO-REGIME-US-RATE-CUT-20240918",
        "regime_type": "us_rate_cut_cycle",
        "as_of_date": "2025-06-05",
        "start_date": "2024-09-18",
        "end_date": "2025-12-31",
        "source": "Fed rate-cut cycle after the September 2024 FOMC cut",
        "source_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20240918a.htm",
        "source_basis": "as_of_date",
        "source_text_grounded": False,
        "pit_available": True,
        "policy": (
            "macro regime calendar is public aggregate governance metadata; it may "
            "supplement forecast claims by PIT as_of_datetime but must not claim "
            "source-text grounding"
        ),
    }


def test_infer_claim_component_roles_adds_2026_china_macro_regimes():
    roles = _infer_claim_component_roles(
        "公司加快推进数字化转型和智能化升级，有助于提质增效并支撑业绩增长。",
        target={"target_type": "stock", "target_id": "300797.SZ"},
        as_of_datetime="2026-01-15",
    )

    assert roles["source_text_macro_regime_context_types"] == []
    assert set(roles["as_of_date_macro_regime_context_types"]) >= {
        "us_rate_cut_cycle",
        "china_monetary_easing_cycle",
        "rmb_fx_stability_window",
    }
    detail_by_type = {
        detail["regime_type"]: detail
        for detail in roles["as_of_date_macro_regime_context_details"]
    }
    assert detail_by_type["china_monetary_easing_cycle"]["regime_id"] == (
        "MACRO-REGIME-CN-MONETARY-EASING-20260101"
    )
    assert detail_by_type["rmb_fx_stability_window"]["regime_id"] == (
        "MACRO-REGIME-RMB-FX-STABILITY-20260101"
    )


def test_infer_claim_component_roles_uses_governed_macro_regime_calendar():
    roles = _infer_claim_component_roles(
        "公司加快推进数字化转型和智能化升级，有助于提质增效并支撑业绩增长。",
        target={"target_type": "stock", "target_id": "300797.SZ"},
        as_of_datetime="2026-06-05",
        macro_regime_calendar_rows=[
            {
                "regime_id": "MACRO-REGIME-TEST-20260101",
                "regime_type": "test_macro_liquidity_window",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "source": "test governed PIT macro regime row",
                "pit_available": True,
                "policy": "test only",
                "version": 1,
            }
        ],
    )

    assert roles["macro_regime_context_types"] == ["test_macro_liquidity_window"]
    assert roles["source_text_macro_regime_context_types"] == []
    assert roles["as_of_date_macro_regime_context_types"] == [
        "test_macro_liquidity_window"
    ]
    assert roles["macro_regime_context_sources"] == {
        "test_macro_liquidity_window": (
            "as_of_date:2026-06-05; test governed PIT macro regime row"
        )
    }
    assert roles["as_of_date_macro_regime_context_details"] == [
        {
            "regime_id": "MACRO-REGIME-TEST-20260101",
            "regime_type": "test_macro_liquidity_window",
            "as_of_date": "2026-06-05",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "source": "test governed PIT macro regime row",
            "source_url": "",
            "source_basis": "as_of_date",
            "source_text_grounded": False,
            "pit_available": True,
            "policy": "test only",
        }
    ]


def test_infer_claim_component_roles_covers_common_industry_cycle_buckets():
    specialty_gas = _infer_claim_component_roles(
        "在地缘冲突导致全球氦气供给中长期紧张、半导体材料国产替代深化的背景下，电子特气企业具备价值重估空间。",
        target={"target_type": "sector", "target_id": "化学制品"},
    )
    steel = _infer_claim_component_roles(
        "在原材料价格近期上涨且出口限制扩大的背景下，钢铁行业面临投入成本上升和利润空间挤压。",
        target={"target_type": "sector", "target_id": "普钢"},
    )
    ai_compute = _infer_claim_component_roles(
        "在AI技术商业化加速、推理算力需求爆发和算力供需持续错配的背景下，AIGC算力主线是当前行业增长方向。",
        target={"target_type": "sector", "target_id": "IT服务Ⅱ"},
    )
    broker = _infer_claim_component_roles(
        "自营业务已成为券商行业第一大收入来源和业绩分化的核心变量，当前券商板块估值处于历史低位。",
        target={"target_type": "sector", "target_id": "证券Ⅱ"},
    )

    assert set(specialty_gas["industry_cycle_regime_context_types"]) >= {
        "supply_tightness",
        "import_substitution_cycle",
    }
    assert set(steel["industry_cycle_regime_context_types"]) >= {
        "raw_material_cost_pressure",
        "industry_policy_catalyst",
    }
    assert set(ai_compute["industry_cycle_regime_context_types"]) >= {
        "technology_cycle",
        "supply_tightness",
    }
    assert set(broker["industry_cycle_regime_context_types"]) >= {
        "business_model_shift",
        "competition_cycle",
        "industry_valuation_cycle",
    }


def test_outcome_readiness_marks_company_only_claims_as_diagnostic_regime_gap():
    readiness = build_outcome_labeling_readiness_report(
        forecast_rows=[
            {
                "forecast_claim_id": "FC-COMPANY-ONLY",
                "claim_text": "公司特种装备业务提升显著、产能与交付能力增强，有助于提质增效并支撑业绩增长。",
                "target": {"target_type": "stock", "target_id": "300797.SZ"},
                "metric_proxy_mapping": ["earnings_growth"],
                "extraction_quality": {},
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-COMPANY-ONLY",
                "test_status": "ready_for_outcome_labeling",
            }
        ],
    )

    assert readiness["macro_regime_counts"] == {}
    assert readiness["source_text_macro_regime_counts"] == {}
    assert readiness["as_of_date_macro_regime_counts"] == {}
    assert readiness["macro_regime_source_counts"] == {}
    assert readiness["industry_cycle_regime_counts"] == {}
    assert readiness["regime_gap_counts"] == {
        "company_capability_only_no_regime_context": 1
    }
    assert readiness["regime_gap_forecast_claim_ids"] == ["FC-COMPANY-ONLY"]


def test_outcome_readiness_counts_as_of_date_macro_regime_separately():
    readiness = build_outcome_labeling_readiness_report(
        forecast_rows=[
            {
                "forecast_claim_id": "FC-ASOF-MACRO",
                "claim_text": "公司特种装备业务提升显著、产能与交付能力增强，有助于提质增效并支撑业绩增长。",
                "signal_datetime": "2025-06-05",
                "target": {"target_type": "stock", "target_id": "300797.SZ"},
                "metric_proxy_mapping": ["earnings_growth"],
                "extraction_quality": {},
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-ASOF-MACRO",
                "test_status": "ready_for_outcome_labeling",
            }
        ],
    )

    assert set(readiness["macro_regime_counts"]) >= {
        "us_rate_cut_cycle",
        "china_countercyclical_policy",
        "monetary_liquidity_condition",
    }
    assert readiness["source_text_macro_regime_counts"] == {}
    assert set(readiness["as_of_date_macro_regime_counts"]) >= {
        "us_rate_cut_cycle",
        "china_countercyclical_policy",
        "monetary_liquidity_condition",
    }
    assert readiness["macro_regime_source_counts"] == {"as_of_date": 3}
    assert readiness["regime_gap_counts"] == {}
    assert "PIT as_of_datetime" in readiness["as_of_date_macro_regime_policy"]


def test_outcome_readiness_excludes_pending_proxy_claims_from_unlabelable_gaps():
    readiness = build_outcome_labeling_readiness_report(
        forecast_rows=[
            {
                "forecast_claim_id": "FC-PENDING-STOCK",
                "claim_text": "公司盈利改善有望推动股价表现。",
                "target": {"target_type": "stock", "target_id": "300001.SZ"},
                "direction": "positive",
                "extraction_quality": {"mapping_gaps": ["horizon"]},
            },
            {
                "forecast_claim_id": "FC-BLOCKED",
                "claim_text": "行业需求改善。",
                "target": {"target_type": "sector", "target_id": "未知行业"},
                "direction": "positive",
                "extraction_quality": {"mapping_gaps": ["horizon"]},
            },
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-PENDING-STOCK",
                "test_status": "not_ready_insufficient_mapping",
            },
            {
                "forecast_claim_id": "FC-BLOCKED",
                "test_status": "not_ready_insufficient_mapping",
            },
        ],
        stock_price_proxy_readiness={
            "pending_future_forecast_claim_ids": ["FC-PENDING-STOCK"],
        },
    )

    assert readiness["mapping_gap_counts"] == {"horizon": 2}
    assert readiness["unlabelable_mapping_gap_counts"] == {"horizon": 1}
    assert readiness["blocked_forecast_claim_ids"] == ["FC-BLOCKED"]
    assert readiness["proxy_label_pending_count"] == 1
    assert readiness["stock_proxy_label_pending_count"] == 1
    assert readiness["proxy_label_pending_only_count"] == 1
    assert readiness["proxy_label_pending_only_forecast_claim_ids"] == [
        "FC-PENDING-STOCK"
    ]


def _passing_forecast_gold_review_summary(**overrides):
    summary = {
        "passed": True,
        "review_complete": True,
        "reviewed_claims": 100,
        "pending_claims": 0,
        "total_documents": 50,
        "metrics": {
            "claim_precision": 0.90,
            "source_span_support_precision": 0.92,
            "target_accuracy": 0.88,
            "direction_accuracy": 0.89,
            "horizon_accuracy": 0.87,
            "variable_mapping_accuracy": 0.82,
            "unsupported_field_false_grounding_rate": 0.02,
        },
    }
    summary.update(overrides)
    return summary


def _passing_recipe_paper_trading_summary(**overrides):
    summary = {
        "paper_trading_run_count": 20,
        "validation_pass_count": 20,
        "mean_cost_adjusted_alpha": 0.012,
        "after_cost_paper_trading_summary": {
            "status": "computed",
            "validated_recipe_count": 20,
            "mean_after_cost_alpha": 0.012,
            "median_after_cost_alpha": 0.012,
            "min_after_cost_alpha": 0.004,
            "max_after_cost_alpha": 0.02,
            "positive_after_cost_recipe_count": 20,
            "policy": "test summary",
        },
    }
    summary.update(overrides)
    return summary


def _full_evolution_outcome_fixture() -> tuple[
    list[dict[str, str]],
    list[dict[str, object]],
]:
    outcome_rows: list[dict[str, object]] = []
    forecast_rows: list[dict[str, str]] = []
    for index in range(100):
        if index < 30:
            label_type = "stock_price_proxy"
            prefix = "STOCK"
        elif index < 60:
            label_type = "industry_etf_proxy"
            prefix = "IND"
        else:
            label_type = "standard_outcome"
            prefix = "STD"
        claim_id = f"FC-{prefix}-{index:03d}"
        forecast_rows.append({"forecast_claim_id": claim_id})
        outcome_rows.append(
            {
                "forecast_claim_id": claim_id,
                "label_type": label_type,
                "horizon_days": 20,
                "effective_n_weight": 1.0,
            }
        )
    return forecast_rows, outcome_rows


def _write_source(
    path: Path,
    *,
    url: str = "https://example.invalid/report.pdf",
    industry: str = "宏观",
    report_type: str = "宏观研报",
    publish_date: str = "2026-06-05",
    ts_code: str = "",
) -> str:
    source_id = "SRC-TSRR-20260605-LIQUIDITY"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "abstract": "摘要不能作为本测试的抽取输入。",
                "author": "Analyst A",
                "discovered_at": "2026-06-06T00:00:00+00:00",
                "industry": industry,
                "institution": "Broker A",
                "license_status": "pending_review",
                "point_in_time_available": True,
                "publish_date": publish_date,
                "query_key": "liquidity",
                "report_type": report_type,
                "source_hash": "sha256:test",
                "source_id": source_id,
                "source_span_id": f"{source_id}:abstract",
                "source_type": "tushare_research_report",
                "title": "Liquidity report",
                "ts_code": ts_code,
                "url": url,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return source_id


def _write_qlib_series(
    root: Path,
    symbol: str,
    values: list[float],
    *,
    field: str = "adjclose",
    start_index: float = 0.0,
) -> None:
    if "." in symbol:
        code, market = symbol.split(".", 1)
        qlib_symbol = market.lower() + code
    else:
        qlib_symbol = symbol.lower()
    path = root / "features" / qlib_symbol / f"{field}.day.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(f"<{len(values) + 1}f", start_index, *values))


def _write_qlib_calendar(root: Path, dates: list[str]) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")


def _stock_fixture_dates() -> list[str]:
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    return dates


def _write_qlib_stock_fixture(
    root: Path,
    *,
    symbol: str = "000001.SZ",
    values: list[float] | None = None,
    volume: list[float] | None = None,
) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    if values is None:
        values = []
        for index in range(len(dates)):
            if index <= 2:
                values.append(1.0)
            elif index <= 7:
                values.append(1.0 - (index - 2) * 0.005)
            else:
                values.append(0.975 + (index - 7) * 0.004)
    volume_values = volume or [100.0 for _ in dates]
    for field, field_values in {
        "adjclose": values,
        "close": values,
        "open": values,
        "high": [value * 1.001 for value in values],
        "low": [value * 0.999 for value in values],
        "volume": volume_values,
    }.items():
        _write_qlib_series(root, symbol, field_values, field=field)


def _write_qlib_stock_entry_limit_locked_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    entry_index = 2
    values[entry_index - 1] = 1.0
    values[entry_index] = 1.1
    open_values = list(values)
    high_values = [value * 1.001 for value in values]
    low_values = [value * 0.999 for value in values]
    close_values = list(values)
    for field_values in (open_values, high_values, low_values, close_values):
        field_values[entry_index] = 1.1
    for field, field_values in {
        "adjclose": values,
        "close": close_values,
        "open": open_values,
        "high": high_values,
        "low": low_values,
        "volume": [100.0 for _ in dates],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_exit_limit_locked_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    exit_index = 7
    values[exit_index - 1] = 1.0
    values[exit_index] = 0.9
    open_values = list(values)
    high_values = [value * 1.001 for value in values]
    low_values = [value * 0.999 for value in values]
    close_values = list(values)
    for field_values in (open_values, high_values, low_values, close_values):
        field_values[exit_index] = 0.9
    for field, field_values in {
        "adjclose": values,
        "close": close_values,
        "open": open_values,
        "high": high_values,
        "low": low_values,
        "volume": [100.0 for _ in dates],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_exit_liquidity_unverified_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    exit_index = 7
    open_values = list(values)
    high_values = [value * 1.001 for value in values]
    low_values = [value * 0.999 for value in values]
    close_values = list(values)
    open_values[exit_index] = float("nan")
    for field, field_values in {
        "adjclose": values,
        "close": close_values,
        "open": open_values,
        "high": high_values,
        "low": low_values,
        "volume": [100.0 for _ in dates],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_truncated_fixture(root: Path) -> None:
    dates = _stock_fixture_dates()
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(7)]
    for field, field_values in {
        "adjclose": values,
        "close": values,
        "open": values,
        "high": [value * 1.001 for value in values],
        "low": [value * 0.999 for value in values],
        "volume": [100.0 for _ in values],
    }.items():
        _write_qlib_series(root, "000001.SZ", field_values, field=field)


def _write_qlib_stock_benchmark_fixture(root: Path) -> None:
    stock_dates = _stock_fixture_dates()
    dates = ["2025-12-31", *stock_dates]
    _write_qlib_calendar(root, dates)
    values = [1.0 + index * 0.001 for index in range(len(dates))]
    _write_qlib_series(root, "SH510300", values)


def _write_misaligned_qlib_stock_benchmark_fixture(root: Path) -> None:
    stock_dates = _stock_fixture_dates()
    dates = ["2025-12-29", "2025-12-30", "2025-12-31", *stock_dates]
    _write_qlib_calendar(root, dates)
    values = [100.0 for _ in dates]
    values[dates.index("2026-01-03")] = 10.0
    values[dates.index("2026-01-08")] = 11.0
    _write_qlib_series(root, "SH510300", values)


def _write_qlib_etf_fixture(root: Path, *, long_calendar: bool = False) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    if long_calendar:
        dates += [f"2026-06-{day:02d}" for day in range(1, 31)]
        dates += [f"2026-07-{day:02d}" for day in range(1, 32)]
        dates += [f"2026-08-{day:02d}" for day in range(1, 32)]
        dates += [f"2026-09-{day:02d}" for day in range(1, 31)]
        dates += [f"2026-10-{day:02d}" for day in range(1, 32)]
        dates += [f"2026-11-{day:02d}" for day in range(1, 31)]
        dates += [f"2026-12-{day:02d}" for day in range(1, 32)]
        dates += [f"2027-01-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH560860", [1.00 + index * 0.002 for index in range(len(dates))])
    _write_qlib_series(root, "SH512400", [1.00 + index * 0.002 for index in range(len(dates))])
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.001 for index in range(len(dates))])


def _write_qlib_etf_custom_benchmark_fixture(root: Path) -> None:
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    _write_qlib_calendar(root, dates)
    _write_qlib_series(root, "SH560860", [1.00 + index * 0.002 for index in range(len(dates))])
    _write_qlib_series(root, "SH512400", [1.00 + index * 0.002 for index in range(len(dates))])
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.001 for index in range(len(dates))])
    _write_qlib_series(root, "SH510500", [1.00 + index * 0.005 for index in range(len(dates))])


def _write_qlib_etf_without_benchmark_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH560860", [1.00 + index * 0.002 for index in range(len(dates))])
    _write_qlib_series(root, "SH512400", [1.00 + index * 0.002 for index in range(len(dates))])


def _write_qlib_etf_without_proxy_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.001 for index in range(len(dates))])


def _write_qlib_etf_mixed_window_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    values: list[float] = []
    for index in range(len(dates)):
        if index <= 25:
            values.append(1.00 - index * 0.002)
        else:
            values.append(0.95 + (index - 25) * 0.002)
    _write_qlib_series(root, "SH560860", values)
    _write_qlib_series(root, "SH512400", values)
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.0005 for index in range(len(dates))])


def _write_qlib_etf_bearish_fixture(root: Path) -> None:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-02-{day:02d}" for day in range(1, 29)]
    dates += [f"2026-03-{day:02d}" for day in range(1, 32)]
    dates += [f"2026-04-{day:02d}" for day in range(1, 31)]
    dates += [f"2026-05-{day:02d}" for day in range(1, 32)]
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    _write_qlib_series(root, "SH560860", [1.00 - index * 0.0015 for index in range(len(dates))])
    _write_qlib_series(root, "SH512400", [1.00 - index * 0.0015 for index in range(len(dates))])
    _write_qlib_series(root, "SH510300", [1.00 + index * 0.0002 for index in range(len(dates))])


def _fake_downloader(url: str, path: Path, overwrite: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake report")
    return {
        "status": "downloaded",
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _fake_text_downloader(url: str, path: Path, overwrite: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "【报告摘要】\r\n电子材料平台迎来结构性拐点。\r\n2026年公司经营有望改善。"
    path.write_bytes(text.encode("gb18030"))
    return {
        "status": "downloaded",
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _fake_converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
    assert pdf.exists()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(
        "\n".join(
            [
                "# 流动性脉冲",
                "报告原文讨论7日公开市场净投放，并用DR007与政策利率利差确认资金压力。",
                "若公开市场净投放改善且DR007回落，高 beta 风格相对沪深300可能占优。",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "status": "converted",
        "path": str(markdown),
        "bytes": markdown.stat().st_size,
        "sha256": _sha(markdown),
    }


def test_local_macro_strategy_sources_scan_pdf_folder_not_file_list(tmp_path: Path):
    input_dir = tmp_path / "macro_pdfs"
    nested = input_dir / "nested"
    nested.mkdir(parents=True)
    first_pdf = input_dir / "2026-01-02_BrokerA_宏观策略周报.pdf"
    second_pdf = nested / "2026-01-03_BrokerB_A股市场策略.pdf"
    first_pdf.write_bytes(b"%PDF-1.4 first")
    second_pdf.write_bytes(b"%PDF-1.4 second")
    (input_dir / "文件清单.txt").write_text(first_pdf.name + "\n", encoding="utf-8")

    result = build_local_macro_strategy_report_sources(
        root=tmp_path,
        input_dir=input_dir,
    )

    assert result.scanned_pdf_count == 2
    assert result.written_rows == 2
    rows = _read_jsonl(tmp_path / "registry/sources/local_macro_strategy_reports.jsonl")
    assert {Path(row["local_pdf_path"]).name for row in rows} == {
        first_pdf.name,
        second_pdf.name,
    }
    assert {row["source_type"] for row in rows} == {"local_macro_strategy_report"}
    assert all(str(row["url"]).startswith("file://") for row in rows)
    manifest = json.loads(
        (tmp_path / "registry/sources/local_macro_strategy_reports.manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["scanned_pdf_count"] == 2
    assert manifest["privacy_policy"]


def test_report_intelligence_labels_macro_strategy_claims_with_asset_proxy_windows(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="宏观策略",
        report_type="宏观策略-A股",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir, long_calendar=True)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": (
                            "国内逆周期政策加码、流动性改善的宏观环境下，"
                            "权益风险偏好有望修复，A股宽基指数中期看多。"
                        ),
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "macro_asset_outlook",
                        "target": {
                            "target_type": "macro_asset",
                            "target_id": "CN_A_SHARE_BROAD",
                            "target_name": "A股宽基",
                        },
                        "benchmark": {
                            "benchmark_type": "cash_zero_return",
                            "benchmark_id": "CASH_0",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                        "metric_proxy_mapping": ["macro_asset_forward_return"],
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.macro_asset_proxy_outcome_label_rows == 3
    assert result.macro_asset_proxy_eligible_claim_rows == 1
    assert result.macro_asset_proxy_labelable_window_rows == 3
    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert {row["label_type"] for row in outcome_labels} == {"macro_asset_proxy"}
    assert [row["horizon_days"] for row in outcome_labels] == [90, 180, 360]
    assert {row["proxy_symbol"] for row in outcome_labels} == {"SH510300"}
    assert {row["macro_asset_target_id"] for row in outcome_labels} == {
        "CN_A_SHARE_BROAD"
    }
    assert {row["benchmark_symbol"] for row in outcome_labels} == {"CASH_0"}
    assert {row["benchmark_return"] for row in outcome_labels} == {0.0}
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_macro_asset_etf_price_window"
    }
    assert {row["decision_basis"] for row in outcome_labels} == {
        "directional_macro_asset_proxy_return"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert {row["entry_lag_trading_days"] for row in outcome_labels} == {1}
    assert [row["effective_n_weight"] for row in outcome_labels] == [
        0.333333,
        0.333333,
        0.333334,
    ]
    assert all(row["directional_hit"] is True for row in outcome_labels)

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    macro_readiness = readiness["macro_asset_proxy_readiness"]
    assert readiness["macro_proxy_label_ready_count"] == 1
    assert readiness["proxy_label_ready_count"] == 1
    assert macro_readiness["qlib_etf_dir_configured"].startswith("qlib://")
    assert macro_readiness["eligible_claim_count"] == 1
    assert macro_readiness["labelable_forecast_claim_count"] == 1
    assert macro_readiness["labelable_window_count"] == 3
    assert macro_readiness["data_gap_counts"] == {}
    assert macro_readiness["mapping_policy"]["crude_oil_mapping_enabled"] is False


def _fake_llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
    assert "摘要不能作为本测试" not in chunk
    assert "7日公开市场净投放" in chunk
    return {
        "status": "ok",
        "model": "fake-vllm",
        "payload": {
            "forecast_claims": [
                {
                    "claim_text": "公开市场净投放改善且DR007回落时，高 beta 风格相对沪深300可能占优。",
                    "claim_provenance": "source_grounded",
                    "forecast_testability": "testable",
                    "forecast_type": "macro_regime_to_style_relative_direction",
                    "target": {
                        "target_type": "style_index",
                        "target_id": "CN_A_SHARE_HIGH_BETA",
                    },
                    "benchmark": {
                        "benchmark_type": "broad_index",
                        "benchmark_id": "CSI300",
                    },
                    "direction": "positive",
                    "horizon": {
                        "min_days": 5,
                        "max_days": 20,
                        "unit": "trading_day",
                    },
                    "explicitness": "explicit",
                    "source_conviction": "medium",
                    "metric_proxy_mapping": [
                        "pboc_net_injection_7d",
                        "dr007_policy_rate_spread",
                    ],
                    "failure_modes": ["资金面重新收紧"],
                    "extraction_quality": {"needs_human_review": False},
                }
            ],
            "analytical_footprints": [
                {
                    "topic": "liquidity_impulse_and_funding_stress_confirmation",
                    "indicator_mentions": [
                        {
                            "indicator_text": "7日公开市场净投放",
                            "canonical_metric_candidate": "pboc_net_injection_7d",
                            "data_source_mentioned": "PBOC open market operation announcement",
                            "frequency": "daily",
                            "lookback_window": {
                                "value": 7,
                                "unit": "trading_day",
                            },
                            "transformation": "rolling_sum",
                            "role_in_argument": "liquidity_condition_proxy",
                            "source_grounded": True,
                        },
                        {
                            "indicator_text": "DR007与政策利率利差",
                            "canonical_metric_candidate": "dr007_policy_rate_spread",
                            "data_source_mentioned": "interbank repo market",
                            "frequency": "daily",
                            "lookback_window": {
                                "value": 20,
                                "unit": "trading_day",
                            },
                            "transformation": "zscore",
                            "role_in_argument": "funding_stress_confirmation",
                            "source_grounded": True,
                        },
                    ],
                    "analysis_patterns": [
                        {
                            "pattern_candidate": "liquidity_impulse_confirmation",
                            "steps": [
                                "calculate pboc_net_injection_7d",
                                "check dr007_policy_rate_spread",
                            ],
                        }
                    ],
                    "target_agent_candidates": ["macro.central_bank"],
                }
            ],
            "metric_candidates": [],
            "method_patterns": [],
            "tool_gaps": [],
        },
    }


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _git_ls_files(prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", prefix],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _copy_committed_report_intelligence_public_artifacts(tmp_path: Path) -> Path:
    registry = tmp_path / "registry/report_intelligence"
    for relative in _git_ls_files("registry/report_intelligence"):
        if relative in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS:
            continue
        source = Path(relative)
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return registry


def _iter_json_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_json_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_keys(item)


def _read_committed_json_artifact(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def test_private_report_intelligence_outputs_are_gitignored():
    assert set(REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS) <= PRIVATE_LOCAL_REGISTRY_FILES

    result = subprocess.run(
        ["git", "check-ignore", *sorted(REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS)],
        check=False,
        capture_output=True,
        text=True,
    )

    ignored = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert ignored == set(REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS)


def test_committed_report_intelligence_outputs_do_not_store_private_text_fields():
    forbidden_fields = {
        "abstract",
        "claim_text",
        "manual_claim_text",
        "source_span_id",
        "source_span_ids",
        "source_text",
        "source_text_hash",
        "span_preview",
    }
    leaked: list[str] = []
    for relative in _git_ls_files("registry/report_intelligence"):
        if relative in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS:
            continue
        payload = _read_committed_json_artifact(Path(relative))
        present = set(_iter_json_keys(payload)) & forbidden_fields
        if present:
            leaked.append(f"{relative}: {sorted(present)}")

    assert not leaked


def test_report_intelligence_derived_refresh_refuses_clean_checkout_overwrite(
    tmp_path: Path,
):
    registry = _copy_committed_report_intelligence_public_artifacts(tmp_path)
    ledger_path = registry / "report_forecast_ledger.jsonl"
    readiness_path = registry / "outcome_labeling_readiness.json"
    before_ledger = ledger_path.read_text(encoding="utf-8")
    before_readiness = readiness_path.read_text(encoding="utf-8")

    result = run_report_intelligence_derived_refresh(
        ReportIntelligenceConfig(root=tmp_path, refresh_derived_only=True)
    )

    assert result.blocker_count == 1
    assert "private report-intelligence inputs missing" in result.blockers[0]
    assert ledger_path.read_text(encoding="utf-8") == before_ledger
    assert readiness_path.read_text(encoding="utf-8") == before_readiness


def test_report_intelligence_derived_refresh_refuses_empty_private_inputs_overwrite(
    tmp_path: Path,
):
    registry = _copy_committed_report_intelligence_public_artifacts(tmp_path)
    private_dir = registry
    private_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "analytical_footprints.jsonl",
        "forecast_claims.jsonl",
        "report_metadata.jsonl",
    ):
        (private_dir / name).write_text("", encoding="utf-8")
    ledger_path = registry / "report_forecast_ledger.jsonl"
    readiness_path = registry / "outcome_labeling_readiness.json"
    before_ledger = ledger_path.read_text(encoding="utf-8")
    before_readiness = readiness_path.read_text(encoding="utf-8")

    result = run_report_intelligence_derived_refresh(
        ReportIntelligenceConfig(root=tmp_path, refresh_derived_only=True)
    )

    assert result.blocker_count == 1
    assert "private report-intelligence inputs missing" in result.blockers[0]
    assert "forecast_claims.jsonl" in result.blockers[0]
    assert ledger_path.read_text(encoding="utf-8") == before_ledger
    assert readiness_path.read_text(encoding="utf-8") == before_readiness


def test_report_intelligence_uses_original_markdown_and_writes_loop_artifacts(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )

    assert result.blocker_count == 0
    assert result.selected_reports == 1
    assert result.pdf_ready_count == 1
    assert result.markdown_ready_count == 1
    assert result.llm_processed_reports == 1
    assert result.forecast_claim_rows == 1
    assert result.analytical_footprint_rows == 1
    assert result.metric_candidate_rows == 2
    assert result.tool_gap_rows == 1
    assert result.forecast_ledger_rows == 1
    assert result.outcome_label_rows == 0
    assert result.tool_coverage_match_rows == 2
    assert result.data_acquisition_proposal_rows == 1
    assert result.tool_design_proposal_rows == 1
    assert result.analysis_recipe_rows == 1
    assert result.prompt_mutation_candidate_rows >= 1
    assert result.weighted_research_context_rows == 1
    assert result.runtime_tool_gap_observation_rows == 1
    assert result.outcome_labeling_ready_count == 1
    assert result.outcome_labeling_blocked_count == 0
    assert "runtime_safety_audit" in result.outputs
    assert "pit_leakage_audit" in result.outputs
    assert "extraction_provenance_audit" in result.outputs
    assert "statistical_robustness_audit" in result.outputs
    assert "tool_feasibility_audit" in result.outputs
    assert "recipe_validation_audit" in result.outputs
    assert "patch_v1_5_coverage_report" in result.outputs
    assert "recipe_paper_trading_runs" in result.outputs
    assert "recipe_paper_trading_summary" in result.outputs
    assert "confidence_impact_observations" in result.outputs
    assert "confidence_impact_monitor" in result.outputs
    assert "monitor_refresh_history" in result.outputs
    assert "audit_refresh_history" in result.outputs
    assert "gap_distribution_history" in result.outputs
    assert "prompt_mutation_candidates" in result.outputs
    assert "markdown_coverage_summary" in result.outputs
    assert "industry_etf_proxy_map" in result.outputs
    assert "industry_etf_proxy_pit_availability" in result.outputs

    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    assert metadata[0]["source_id"] == source_id
    assert metadata[0]["version"] == "original_pdf_markdown"
    assert metadata[0]["extraction"]["abstract_only_fallback_used"] is False
    assert metadata[0]["extraction"]["llm_model"] == "fake-vllm"
    assert metadata[0]["source_row_license_status"] == "pending_review"
    assert metadata[0]["license_class"] == "operator_approved_internal_research_use"

    markdown_coverage = json.loads(
        (
            tmp_path / "registry/report_intelligence/markdown_coverage_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert markdown_coverage["selected_report_count"] == 1
    assert markdown_coverage["markdown_ready_count"] == 1
    assert markdown_coverage["markdown_quality_pass_count"] == 1
    assert markdown_coverage["llm_extraction_processed_count"] == 1
    assert markdown_coverage["llm_extraction_without_quality_pass_count"] == 0
    assert markdown_coverage["industry_report_count"] == 0
    assert markdown_coverage["stock_report_count"] == 0
    assert markdown_coverage["coverage_targets"] == {
        "industry_report_count_min": 80,
        "llm_extraction_processed_count_min": 100,
        "markdown_quality_pass_count_min": 300,
        "markdown_ready_count_min": 300,
        "sector_bucket_min_report_count": 5,
        "selected_report_count_min": 300,
        "stock_report_count_min": 80,
        "stock_outcome_120d_ready_report_count_min": 30,
    }
    assert markdown_coverage["coverage_shortfalls"]["selected_report_count"] == {
        "blocker": "selected_report_count_below_p9_target",
        "current": 1,
        "next_action": "add_stratified_real_reports_to_private_source_pool",
        "remaining": 299,
        "target": 300,
    }
    assert markdown_coverage["coverage_shortfalls"]["markdown_ready_count"][
        "remaining"
    ] == 299
    assert markdown_coverage["coverage_shortfalls"][
        "llm_extraction_processed_count"
    ]["remaining"] == 99
    assert markdown_coverage["coverage_shortfalls"]["stock_report_count"][
        "remaining"
    ] == 80
    assert markdown_coverage["coverage_gate_status"] == "blocked"
    assert set(markdown_coverage["coverage_gate_blockers"]) == {
        "evaluability_bucket_coverage_below_p9_target",
        "horizon_bucket_coverage_below_p9_target",
        "llm_extraction_processed_count_below_p9_target",
        "industry_report_count_below_p9_target",
        "institution_bucket_coverage_below_p9_target",
        "markdown_quality_pass_count_below_p9_target",
        "markdown_ready_count_below_p9_target",
        "sector_bucket_coverage_below_p9_target",
        "selected_report_count_below_p9_target",
        "stock_report_count_below_p9_target",
        "stock_outcome_120d_ready_count_below_p9_target",
        "stock_outcome_age_bucket_coverage_below_p9_target",
        "time_bucket_coverage_below_p9_target",
    }
    assert markdown_coverage["report_type_counts"] == {"宏观研报": 1}
    assert markdown_coverage["time_bucket_counts"] == {"recent_1y": 1}
    assert markdown_coverage["institution_bucket_counts"] == {
        "long_tail_institution": 1
    }
    assert markdown_coverage["report_horizon_bucket_counts"] == {"20d": 1}
    assert markdown_coverage["evaluability_bucket_counts"] == {
        "macro_asset_proxy_candidate": 1
    }
    assert markdown_coverage["sector_bucket_coverage_gaps"] == [
        "sector_bucket:other_sector"
    ]
    assert markdown_coverage["sector_bucket_below_min_count"] == 1
    assert {
        "time_bucket:recent_3y",
        "time_bucket:long_cycle_history",
        "institution_bucket:head_institution",
        "horizon_bucket:5d",
        "horizon_bucket:60d",
        "horizon_bucket:long_horizon",
        "evaluability_bucket:stock_proxy_candidate",
        "evaluability_bucket:industry_proxy_candidate",
        "evaluability_bucket:mapping_gap_candidate",
        "stock_outcome_age_bucket:stock_outcome_120d_calendar_ready",
    } <= set(markdown_coverage["coverage_strata_missing"])
    assert markdown_coverage["stratified_sampling_policy"]["privacy_boundary"] == (
        "aggregate_counts_only"
    )
    coverage_dump = json.dumps(markdown_coverage, ensure_ascii=False)
    assert source_id not in coverage_dump
    assert "Liquidity report" not in coverage_dump
    assert "https://example.invalid/report.pdf" not in coverage_dump

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["source_span_ids"] == [
        f"{source_id}:original_markdown:chunk-001"
    ]
    assert forecasts[0]["claim_provenance"] == "source_grounded"
    assert forecasts[0]["failure_modes"] == [
        {
            "provenance": "analyst_or_llm_hypothesis",
            "requires_independent_validation": True,
            "text": "资金面重新收紧",
        }
    ]

    footprint_review = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    assert len(footprint_review) == 1
    assert footprint_review[0]["review_kind"] == "analytical_footprint_gold_set"
    assert footprint_review[0]["manual_review_required"] is True
    assert footprint_review[0]["footprint_correct"] is None
    assert footprint_review[0]["metric_mapping_correct"] is None
    assert footprint_review[0]["target_row_hash"].startswith("sha256:")
    assert footprint_review[0]["indicator_mentions_review_preview"][0][
        "canonical_metric_candidate"
    ] == "pboc_net_injection_7d"

    footprint_review_summary = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert footprint_review_summary["accepted"] is False
    assert footprint_review_summary["review_complete"] is False
    assert footprint_review_summary["quality_gate_passed"] is False
    assert footprint_review_summary["total_rows"] == 1
    assert footprint_review_summary["pending_rows"] == 1
    assert (
        footprint_review_summary["precision_recall_report"]["recall_status"]
        == "requires_human_negative_examples"
    )
    assert "analytical footprint review rows still pending" in " ".join(
        footprint_review_summary["blockers"]
    )

    footprint_taxonomy = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_error_taxonomy.json"
        ).read_text(encoding="utf-8")
    )
    assert {
        "hallucinated_metric",
        "ambiguous_metric_not_unknown",
        "proprietary_text_leakage",
    } <= {row["tag"] for row in footprint_taxonomy["error_tags"]}

    metrics = _read_jsonl(tmp_path / "registry/report_intelligence/metric_candidates.jsonl")
    coverage = {row["canonical_name"]: row["current_tool_coverage"] for row in metrics}
    assert coverage["pboc_net_injection_7d"] == "exact_match"
    assert coverage["dr007_policy_rate_spread"] == "partial_match"

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "ready_for_outcome_labeling"
    assert ledger[0]["immutable"] is True

    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert outcome_labels == []

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["ready_for_outcome_labeling_count"] == 1
    assert readiness["blocked_count"] == 0
    assert readiness["mapping_gap_counts"] == {}
    assert readiness["macro_regime_counts"] == {
        "china_monetary_easing_cycle": 1,
        "monetary_liquidity_condition": 1,
        "rmb_fx_stability_window": 1,
        "us_rate_cut_cycle": 1,
    }
    assert readiness["source_text_macro_regime_counts"] == {
        "monetary_liquidity_condition": 1
    }
    assert readiness["as_of_date_macro_regime_counts"] == {
        "china_monetary_easing_cycle": 1,
        "rmb_fx_stability_window": 1,
        "us_rate_cut_cycle": 1,
    }
    assert readiness["macro_regime_source_counts"] == {
        "as_of_date": 3,
        "report_text": 1,
    }
    assert readiness["industry_cycle_regime_counts"] == {}
    assert readiness["regime_gap_counts"] == {}
    assert readiness["regime_gap_forecast_claim_ids"] == []
    assert readiness["mechanism_channel_counts"] == {
        "policy_liquidity_transmission": 1
    }
    assert readiness["mechanism_impact_variable_counts"] == {
        "dr007_policy_rate_spread": 1,
        "equity_index_forward_return": 1,
        "pboc_net_injection_7d": 1,
    }
    assert readiness["mechanism_gap_counts"] == {}
    assert readiness["mechanism_gap_forecast_claim_ids"] == []
    assert "regime, mechanism, company capability, and impact" in readiness[
        "mechanism_policy"
    ]

    feature_flags = json.loads(
        (tmp_path / "registry/report_intelligence/feature_flags.json").read_text(
            encoding="utf-8"
        )
    )
    assert feature_flags["rollout_mode"] == "shadow_tooling"
    assert feature_flags["flags"]["weighted_research_retriever_enabled"] is True
    assert feature_flags["flags"]["shadow_tool_runtime_enabled"] is True
    assert feature_flags["flags"]["production_use_of_weighted_reports"] is False
    assert "no agent decision impact" in feature_flags["runtime_behavior"]

    coverage_matches = _read_jsonl(
        tmp_path / "registry/report_intelligence/tool_coverage_matches.jsonl"
    )
    coverage_by_metric = {
        row["metric_candidate_id"]: row["coverage_status"]
        for row in coverage_matches
    }
    metric_ids = {row["canonical_name"]: row["metric_candidate_id"] for row in metrics}
    assert coverage_by_metric[metric_ids["pboc_net_injection_7d"]] == "exact_match"
    assert coverage_by_metric[metric_ids["dr007_policy_rate_spread"]] == "partial_match"

    tool_gaps = _read_jsonl(tmp_path / "registry/report_intelligence/tool_gaps.jsonl")
    assert tool_gaps[0]["priority_bucket"] == "high"
    assert "missing_or_partial_data_blocks_named_agent" in tool_gaps[0][
        "priority_reasons"
    ]
    assert tool_gaps[0]["owner"] == "data_engineering"

    data_proposals = _read_jsonl(
        tmp_path / "registry/report_intelligence/data_acquisition_proposals.jsonl"
    )
    assert data_proposals[0]["decision_status"] == "pending_review"
    assert data_proposals[0]["owner"] == "data_engineering"
    assert data_proposals[0]["license_status"] == "pending_review"
    assert data_proposals[0]["pit_feasibility_status"] == (
        "pit_feasible_pending_vendor_review"
    )
    assert data_proposals[0]["source_tool_gap_priority"] == "high"

    tool_proposals = _read_jsonl(
        tmp_path / "registry/report_intelligence/tool_design_proposals.jsonl"
    )
    assert tool_proposals[0]["status"] == "shadow_build_requested"
    assert tool_proposals[0]["owner"] == "data_engineering"
    assert tool_proposals[0]["license_status"] == "pending_review"
    assert tool_proposals[0]["pit_feasibility_status"] == (
        "pit_feasible_pending_vendor_review"
    )
    assert tool_proposals[0]["engineering_estimate"] == "high"

    recipes = _read_jsonl(tmp_path / "registry/report_intelligence/analysis_recipes.jsonl")
    assert recipes[0]["runtime_mode"] == "shadow_only"

    weighted_contexts = _read_jsonl(
        tmp_path / "registry/report_intelligence/weighted_research_contexts.jsonl"
    )
    assert weighted_contexts[0]["research_only"] is True
    assert (
        weighted_contexts[0]["actionability"]
        == "no_trade_without_current_data_confirmation"
    )
    weighted_claim = weighted_contexts[0]["retrieved_claims"][0]
    assert weighted_claim["forecast_family_id"] == ledger[0]["forecast_family_id"]
    assert weighted_claim["consensus_cluster_id"] == ledger[0]["consensus_cluster_id"]
    assert weighted_claim["dedup_cluster_id"] == ledger[0]["dedup_cluster_id"]
    assert (
        weighted_claim["independent_confirmation_policy"]
        == "consensus_cluster_not_independent_confirmation"
    )
    assert weighted_claim["current_tool_evidence_ids"] == []

    runtime_gaps = _read_jsonl(
        tmp_path / "registry/report_intelligence/runtime_tool_gap_observations.jsonl"
    )
    assert runtime_gaps[0]["suggested_tool_gap_id"] == data_proposals[0]["tool_gap_id"]
    assert runtime_gaps[0]["runtime_role"] == "gap_observation_only"
    assert runtime_gaps[0]["research_only"] is True
    assert runtime_gaps[0]["allowed_runtime_mode"] == "shadow_only"
    assert runtime_gaps[0]["current_data_confirmation"] == "missing"
    assert (
        runtime_gaps[0]["actionability"]
        == "no_trade_without_current_data_confirmation"
    )

    runtime_safety = json.loads(
        (
            tmp_path / "registry/report_intelligence/runtime_safety_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert runtime_safety["accepted"] is True
    assert runtime_safety["blocker_count"] == 0
    assert {row["check_id"] for row in runtime_safety["checks"]} == {
        f"RI-SAFE-{index:02d}" for index in range(10)
    }
    assert (
        "sector_score"
        in runtime_safety["checks"][3]["evidence"]["forbidden_fields"]
    )
    assert (
        runtime_safety["checks"][7]["evidence"]["consensus_cluster_count"] == 1
    )

    pit_audit = json.loads(
        (
            tmp_path / "registry/report_intelligence/pit_leakage_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert pit_audit["accepted"] is True
    assert pit_audit["blocker_count"] == 0
    assert {row["check_id"] for row in pit_audit["checks"]} == {
        f"RI-PIT-{index:02d}" for index in range(8)
    }
    assert pit_audit["checks"][1]["evidence"]["forecast_claim_rows"] == 1
    assert pit_audit["checks"][2]["evidence"]["outcome_label_rows"] == 0

    provenance_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/extraction_provenance_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert provenance_audit["accepted"] is True
    assert provenance_audit["blocker_count"] == 0
    assert {row["check_id"] for row in provenance_audit["checks"]} == {
        f"RI-PROV-{index:02d}" for index in range(6)
    }
    assert (
        provenance_audit["checks"][1]["evidence"]["source_grounded_claim_count"]
        == 1
    )
    assert (
        provenance_audit["checks"][2]["evidence"][
            "source_grounded_or_mixed_footprint_count"
        ]
        == 1
    )

    statistical_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/statistical_robustness_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert statistical_audit["accepted"] is True
    assert statistical_audit["blocker_count"] == 0
    assert {row["check_id"] for row in statistical_audit["checks"]} == {
        f"RI-STAT-{index:02d}" for index in range(8)
    }
    assert statistical_audit["checks"][1]["evidence"]["outcome_label_rows"] == 0
    assert (
        statistical_audit["checks"][7]["evidence"]["fdr_or_reality_check_status"]
        == "deferred_until_paper_trading_or_production_candidate"
    )

    tool_feasibility_audit = json.loads(
        (
            tmp_path / "registry/report_intelligence/tool_feasibility_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert tool_feasibility_audit["accepted"] is True
    assert tool_feasibility_audit["blocker_count"] == 0
    assert {row["check_id"] for row in tool_feasibility_audit["checks"]} == {
        f"RI-TOOL-{index:02d}" for index in range(7)
    }
    assert tool_feasibility_audit["checks"][1]["evidence"][
        "metric_candidate_rows"
    ] == 2
    assert tool_feasibility_audit["checks"][2]["evidence"][
        "non_exact_coverage_rows"
    ] == 1
    assert tool_feasibility_audit["checks"][4]["evidence"][
        "minimum_shadow_runtime_days"
    ] == 60

    recipe_validation_audit = json.loads(
        (
            tmp_path / "registry/report_intelligence/recipe_validation_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert recipe_validation_audit["accepted"] is True
    assert recipe_validation_audit["blocker_count"] == 0
    assert {row["check_id"] for row in recipe_validation_audit["checks"]} == {
        f"RI-RECIPE-{index:02d}" for index in range(8)
    }
    assert recipe_validation_audit["checks"][1]["evidence"][
        "analysis_recipe_rows"
    ] == 1
    assert recipe_validation_audit["checks"][2]["evidence"][
        "validation_status_counts"
    ] == {"candidate": 1}
    assert recipe_validation_audit["checks"][4]["evidence"][
        "validation_candidate_recipe_count"
    ] == 0

    monitoring = json.loads(
        (tmp_path / "registry/report_intelligence/monitoring_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert monitoring["report_corpus"]["forecast_claim_rows"] == 1
    assert monitoring["report_weighting_monitoring"][
        "weighted_vs_unweighted_retrieval_difference"
    ] == 0.0
    assert monitoring["tooling_loop_monitoring"]["tool_gap_open_count"] == 1
    assert monitoring["tooling_loop_monitoring"][
        "runtime_fallback_observation_count"
    ] == 1
    assert monitoring["rollout_mode"] == "shadow_tooling"
    alpha_decay = monitoring["alpha_decay_monitoring"]
    assert alpha_decay["monitoring_spec_ready"] is True
    assert alpha_decay["alpha_decay_monitor_ready"] is True
    assert alpha_decay["live_alpha_decay_monitor_active"] is False
    assert alpha_decay["blocked_reason"] == "no_live_production_recipe_current_rollout"
    assert {
        "rolling_after_cost_alpha",
        "calibration_drift",
        "current_vs_backtest_performance_divergence",
    } <= set(alpha_decay["required_decay_metrics"])
    assert {
        "soft_rollback",
        "hard_rollback",
        "compliance_rollback",
    } <= set(alpha_decay["required_rollback_modes"])

    patch_coverage = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/patch_v1_5_coverage_report.json"
        ).read_text(encoding="utf-8")
    )
    assert patch_coverage["phase_count"] == 8
    assert patch_coverage["source_plan_path"] == (
        "MOSAIC_RKE_REPORT_INTELLIGENCE_LOOP_PATCH_V1_5_MERGED.md"
    )
    assert "/home/hap" not in json.dumps(patch_coverage, ensure_ascii=False)
    assert {row["phase_id"] for row in patch_coverage["phase_records"]} == set("ABCDEFGH")
    assert patch_coverage["phase_records"][0]["status"] == "passed"
    assert patch_coverage["phase_records"][1]["status"] == "blocked"
    assert patch_coverage["deferred_phase_ids"] == ["G", "H"]
    assert {
        row["phase_id"]: row["status"]
        for row in patch_coverage["phase_records"]
        if row["phase_id"] in {"G", "H"}
    } == {"G": "deferred_by_rollout", "H": "deferred_by_rollout"}
    phase_g = next(
        row for row in patch_coverage["phase_records"] if row["phase_id"] == "G"
    )
    assert (
        "registry/report_intelligence/recipe_paper_trading_summary.json"
        in phase_g["evidence_artifacts"]
    )
    assert phase_g["evidence_counts"]["paper_trading_recipe_count"] == 0
    assert phase_g["evidence_counts"]["shadow_paper_trading_run_count"] == 1
    assert phase_g["evidence_counts"]["paper_trading_validation_pass_count"] == 0
    assert phase_g["evidence_counts"]["paper_trading_blocked_count"] == 1
    assert alpha_decay["unmonitored_production_recipe_ids"] == []
    confidence_monitoring = monitoring["confidence_impact_monitoring"]
    assert confidence_monitoring["observation_count"] == 1
    assert confidence_monitoring["paper_trading_validated_recipe_count"] == 0
    assert confidence_monitoring["production_decision_impact_allowed"] is False

    paper_trading_runs = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/recipe_paper_trading_runs.jsonl"
    )
    assert len(paper_trading_runs) == 1
    assert paper_trading_runs[0]["paper_trading_status"] == "blocked"
    assert paper_trading_runs[0]["production_decision_impact_allowed"] is False
    assert {
        "no_direct_recipe_outcome_binding",
        "insufficient_effective_n",
    } <= set(paper_trading_runs[0]["blocked_reasons"])

    confidence_observations = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/confidence_impact_observations.jsonl"
    )
    assert confidence_observations[0]["confidence_delta"] == 0.0
    assert confidence_observations[0]["drift_status"] == "paper_trading_blocked"
    assert confidence_observations[0]["recommended_action"] == "keep_shadow"

    prompt_candidates = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/prompt_mutation_candidates.jsonl"
    )
    assert prompt_candidates
    assert {
        "recipe_paper_trading_rule",
        "confidence_gate_rule",
        "tool_gap_prioritization_rule",
    } <= {row["candidate_type"] for row in prompt_candidates}
    assert all(row["production_prompt_change_allowed"] is False for row in prompt_candidates)
    assert all(row["private_text_included"] is False for row in prompt_candidates)
    candidate_dump = json.dumps(prompt_candidates, ensure_ascii=False)
    assert "claim_text" not in candidate_dump
    assert "source_span_ids" not in candidate_dump
    assert source_id not in candidate_dump


def test_report_intelligence_backfills_source_grounded_footprint_metrics_from_chunk(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="房地产开发",
        report_type="行业研报",
    )

    def converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
        assert pdf.exists()
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(
            "\n".join(
                [
                    "# 房地产周度跟踪",
                    "30城月度累计成交面积同比增长，重点城市项目开盘去化率回升。",
                    "报告同时跟踪营业收入、归母净利润和毛利率变化。",
                ]
            ),
            encoding="utf-8",
        )
        return {
            "status": "converted",
            "path": str(markdown),
            "bytes": markdown.stat().st_size,
            "sha256": _sha(markdown),
        }

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        assert "成交面积" in chunk
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [
                    {
                        "topic": (
                            "Monthly transaction, sell-through, and financial "
                            "performance tracking"
                        ),
                        "indicator_mentions": [],
                        "analysis_patterns": [
                            "monthly cumulative aggregation",
                            "sell-through monitoring",
                            "financial YoY margin analysis",
                        ],
                        "target_agent_candidates": ["Real Estate Data Analyst"],
                    }
                ],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=converter,
        llm_extractor=llm,
    )

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    mentions = footprints[0]["indicator_mentions"]
    by_canonical = {row["canonical_metric_candidate"]: row for row in mentions}
    assert {
        "real_estate_transaction_area",
        "real_estate_sell_through_rate",
        "revenue_growth",
        "forecast_net_profit",
        "forecast_gross_margin",
    } <= set(by_canonical)
    assert all(row["source_grounded"] is True for row in by_canonical.values())
    assert {
        row["inference_source"] for row in mentions if "inference_source" in row
    } == {"source_chunk_indicator_seed_rule"}

    review_rows = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    preview_canonicals = {
        row["canonical_metric_candidate"]
        for row in review_rows[0]["indicator_mentions_review_preview"]
    }
    assert "real_estate_transaction_area" in preview_canonicals
    assert "real_estate_sell_through_rate" in preview_canonicals
    assert review_rows[0]["indicator_mentions_review_preview"][0][
        "source_grounded"
    ] is True

    footprints[0]["indicator_mentions"] = []
    metadata_rows = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    refreshed_footprints = _refresh_analytical_footprint_indicator_governance(
        footprints,
        metadata_rows=metadata_rows,
        root_path=tmp_path,
    )
    refreshed_canonicals = {
        row["canonical_metric_candidate"]
        for row in refreshed_footprints[0]["indicator_mentions"]
    }
    assert "real_estate_transaction_area" in refreshed_canonicals
    assert "real_estate_sell_through_rate" in refreshed_canonicals


def test_report_intelligence_prioritizes_source_grounded_footprint_metrics_in_preview(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="房地产开发",
        report_type="行业研报",
    )

    def converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
        assert pdf.exists()
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(
            "\n".join(
                [
                    "# 房地产周度跟踪",
                    "报告按月跟踪商品房成交面积和重点项目开盘去化率。",
                    "这些指标用于判断地产需求景气和项目销售动能。",
                ]
            ),
            encoding="utf-8",
        )
        return {
            "status": "converted",
            "path": str(markdown),
            "bytes": markdown.stat().st_size,
            "sha256": _sha(markdown),
        }

    unknown_mentions = [
        {
            "indicator_text": f"未规范指标{i}",
            "canonical_metric_candidate": "unknown",
            "data_source_mentioned": "unknown",
            "frequency": "unknown",
            "transformation": "unknown",
            "source_grounded": False,
        }
        for i in range(6)
    ]

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        assert "成交面积" in chunk
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [
                    {
                        "topic": "Monthly real estate transaction monitoring",
                        "indicator_mentions": unknown_mentions,
                        "analysis_patterns": [
                            "monthly cumulative transaction tracking",
                            "sell-through monitoring",
                        ],
                        "target_agent_candidates": ["Real Estate Data Analyst"],
                    }
                ],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=converter,
        llm_extractor=llm,
    )

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    mentions = footprints[0]["indicator_mentions"]
    assert {row["canonical_metric_candidate"] for row in mentions[:2]} == {
        "real_estate_transaction_area",
        "real_estate_sell_through_rate",
    }
    assert all(row["source_grounded"] is True for row in mentions[:2])
    assert any(
        mention["canonical_metric_candidate"] == "unknown"
        for mention in mentions[2:]
    )

    review_rows = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    preview = review_rows[0]["indicator_mentions_review_preview"]
    assert {row["canonical_metric_candidate"] for row in preview[:2]} == {
        "real_estate_transaction_area",
        "real_estate_sell_through_rate",
    }
    assert all(row["source_grounded"] is True for row in preview[:2])
    assert review_rows[0]["indicator_mentions_review_summary"] == {
        "complete_source_grounded_count": 2,
        "hidden_count": 3,
        "hidden_ungrounded_count": 3,
        "hidden_unknown_canonical_count": 3,
        "mapping_complete": False,
        "mention_count": 8,
        "preview_count": 5,
        "preview_limit": 5,
        "ungrounded_count": 6,
        "unknown_canonical_count": 6,
    }


def test_report_intelligence_repairs_specialized_indicator_sources():
    mentions = _normalize_indicator_mentions(
        [
            {
                "indicator_text": "industry_revenue",
                "canonical_metric_candidate": "industry_revenue",
                "data_source_mentioned": "company_financials_or_report_forecast",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "category_sales_revenue",
                "canonical_metric_candidate": "category_sales_revenue",
                "data_source_mentioned": "company_financials_or_report_forecast",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "express_delivery_monthly_revenue",
                "canonical_metric_candidate": "express_delivery_monthly_revenue",
                "data_source_mentioned": "company_financials_or_report_forecast",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "policy_event",
                "canonical_metric_candidate": "policy_event",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "供需/库存/商品价格",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "CTFI指数",
                "canonical_metric_candidate": "CTFI指数",
                "data_source_mentioned": "stock_etf_or_index_price",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "category_monthly_sales_revenue",
                "canonical_metric_candidate": "category_monthly_sales_revenue",
                "data_source_mentioned": "company_financials_or_report_forecast",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "碳酸锂均价",
                "canonical_metric_candidate": "ecommerce_price_segment_distribution",
                "data_source_mentioned": "ecommerce_platform_price_distribution_data",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "offshore_wind_project_pipeline",
                "canonical_metric_candidate": "clinical_trial_milestone_status",
                "data_source_mentioned": "company_disclosure_or_clinical_trial_registry",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "应收租赁款不良率",
                "canonical_metric_candidate": "technology_product_milestone",
                "data_source_mentioned": "company_disclosure_or_report_business_update",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "日均Token调用量",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "sector_pe_ttm",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "wind_turbine_bidding_volume",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "沪深股基成交额",
                "canonical_metric_candidate": "reported_sales_volume_or_value",
                "data_source_mentioned": "industry_or_platform_operation_report_table",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "核定产能",
                "canonical_metric_candidate": "commodity_price_cycle",
                "data_source_mentioned": "commodity_price_supply_demand_inventory_data",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "旅游消费活跃度",
                "canonical_metric_candidate": "ecommerce_store_product_rank_activity",
                "data_source_mentioned": "ecommerce_platform_category_store_product_data",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "股息率",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "Weekly Market Performance",
                "canonical_metric_candidate": "valuation_multiple",
                "data_source_mentioned": "market_valuation_data_or_report_forecast",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "碳市场价格与成交量",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "保险偿付能力充足率",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "股权激励授予股票数量",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "生猪价格和出栏规模",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "影片预售/供给热度",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "Comparable Companies",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "csi_300_index",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "IGBT",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "Single-store output",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "1-2 billion RMB A-share repurchase",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "launch_frequency",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "IND_approvals",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "LVEF改善数据",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
            {
                "indicator_text": "30k_ton_carbonate",
                "canonical_metric_candidate": "unknown",
                "data_source_mentioned": "unknown",
                "frequency": "unknown",
                "transformation": "unknown",
                "source_grounded": False,
            },
        ]
    )

    by_text = {row["indicator_text"]: row for row in mentions}
    assert by_text["industry_revenue"]["data_source_mentioned"] == (
        "industry_operation_statistics_or_report_table"
    )
    assert by_text["category_sales_revenue"]["data_source_mentioned"] == (
        "ecommerce_platform_category_store_product_data"
    )
    assert by_text["express_delivery_monthly_revenue"]["data_source_mentioned"] == (
        "transportation_operation_statistics_or_report_table"
    )
    assert by_text["policy_event"]["data_source_mentioned"] == (
        "policy_announcement_or_regulatory_disclosure"
    )
    assert by_text["供需/库存/商品价格"]["data_source_mentioned"] == (
        "commodity_price_supply_demand_inventory_data"
    )
    assert by_text["CTFI指数"]["data_source_mentioned"] == (
        "transportation_operation_statistics_or_report_table"
    )
    assert by_text["category_monthly_sales_revenue"]["data_source_mentioned"] == (
        "ecommerce_platform_category_store_product_data"
    )
    assert by_text["碳酸锂均价"]["data_source_mentioned"] == (
        "commodity_price_supply_demand_inventory_data"
    )
    assert by_text["offshore_wind_project_pipeline"]["data_source_mentioned"] == (
        "energy_project_or_installation_statistics"
    )
    assert by_text["应收租赁款不良率"]["data_source_mentioned"] == (
        "company_financials_or_regulatory_disclosure"
    )
    assert by_text["日均Token调用量"]["data_source_mentioned"] == (
        "ai_platform_usage_or_cost_benchmark"
    )
    assert by_text["sector_pe_ttm"]["data_source_mentioned"] == (
        "market_valuation_data_or_report_forecast"
    )
    assert by_text["wind_turbine_bidding_volume"]["data_source_mentioned"] == (
        "energy_project_or_tender_statistics"
    )
    assert by_text["沪深股基成交额"]["data_source_mentioned"] == (
        "exchange_market_trading_data"
    )
    assert by_text["核定产能"]["data_source_mentioned"] == (
        "industry_capacity_or_production_statistics"
    )
    assert by_text["旅游消费活跃度"]["data_source_mentioned"] == (
        "tourism_operation_statistics_or_survey"
    )
    assert by_text["股息率"]["data_source_mentioned"] == (
        "company_financials_or_dividend_disclosure"
    )
    assert by_text["Weekly Market Performance"]["data_source_mentioned"] == (
        "stock_etf_or_index_price"
    )
    assert by_text["碳市场价格与成交量"]["data_source_mentioned"] == (
        "carbon_market_exchange_statistics"
    )
    assert by_text["保险偿付能力充足率"]["data_source_mentioned"] == (
        "insurance_company_or_regulatory_disclosure"
    )
    assert by_text["股权激励授予股票数量"]["data_source_mentioned"] == (
        "company_equity_incentive_disclosure"
    )
    assert by_text["生猪价格和出栏规模"]["data_source_mentioned"] == (
        "livestock_operation_statistics"
    )
    assert by_text["影片预售/供给热度"]["data_source_mentioned"] == (
        "movie_ticketing_platform_pre_sale_data"
    )
    assert by_text["Comparable Companies"]["data_source_mentioned"] == (
        "market_valuation_data_or_report_forecast"
    )
    assert by_text["csi_300_index"]["data_source_mentioned"] == (
        "stock_etf_or_index_price"
    )
    assert by_text["IGBT"]["data_source_mentioned"] == (
        "company_disclosure_or_report_business_update"
    )
    assert by_text["Single-store output"]["data_source_mentioned"] == (
        "company_channel_or_segment_operation_disclosure"
    )
    assert by_text["1-2 billion RMB A-share repurchase"][
        "data_source_mentioned"
    ] == "company_financials_or_dividend_disclosure"
    assert by_text["launch_frequency"]["data_source_mentioned"] == (
        "industry_operation_statistics_or_report_table"
    )
    assert by_text["IND_approvals"]["data_source_mentioned"] == (
        "healthcare_policy_or_drug_procurement_disclosure"
    )
    assert by_text["LVEF改善数据"]["data_source_mentioned"] == (
        "clinical_trial_or_real_world_evidence"
    )
    assert by_text["30k_ton_carbonate"]["data_source_mentioned"] == (
        "commodity_price_supply_demand_inventory_data"
    )
    assert all(row["source_grounded"] is True for row in by_text.values())


def test_report_intelligence_repairs_unknown_footprint_indicator_mentions(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="公用事业",
        report_type="行业研报",
    )

    def converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
        assert pdf.exists()
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(
            "报告跟踪发电量、用电量、发电装机容量、平均利用小时和电源工程投资。",
            encoding="utf-8",
        )
        return {
            "status": "converted",
            "path": str(markdown),
            "bytes": markdown.stat().st_size,
            "sha256": _sha(markdown),
        }

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        assert "发电量" in chunk
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [
                    {
                        "topic": "Fundamental Data Tracking",
                        "indicator_mentions": [
                            {
                                "indicator_text": "发电量",
                                "canonical_metric_candidate": "unknown",
                                "data_source_mentioned": "unknown",
                                "frequency": "unknown",
                                "transformation": "unknown",
                                "source_grounded": False,
                            },
                            {
                                "indicator_text": "用电量",
                                "canonical_metric_candidate": "unknown",
                                "data_source_mentioned": "unknown",
                                "frequency": "unknown",
                                "transformation": "unknown",
                                "source_grounded": False,
                            },
                        ],
                        "analysis_patterns": [
                            "time_series_analysis",
                            "capacity_utilization_tracking",
                        ],
                        "target_agent_candidates": ["data_analyst"],
                    }
                ],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=converter,
        llm_extractor=llm,
    )

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    mentions = footprints[0]["indicator_mentions"]
    assert {row["canonical_metric_candidate"] for row in mentions} == {
        "power_operation_metric"
    }
    assert {row["data_source_mentioned"] for row in mentions} == {
        "energy_operation_statistics_or_report_table"
    }
    assert all(row["source_grounded"] is True for row in mentions)

    review_rows = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    preview = review_rows[0]["indicator_mentions_review_preview"]
    assert {row["canonical_metric_candidate"] for row in preview} == {
        "power_operation_metric"
    }
    assert all(row["source_grounded"] is True for row in preview)


def test_report_intelligence_adds_context_seed_for_empty_footprint_indicators():
    mentions = _context_seed_indicator_mentions(
        "宏观经济与政策环境 PMI分项分析 财政政策节奏分析 投资结构分析"
    )

    assert mentions
    assert mentions[0]["canonical_metric_candidate"] == (
        "macro_activity_or_credit_metric"
    )
    assert mentions[0]["data_source_mentioned"] == (
        "macroeconomic_statistics_or_policy_report"
    )
    assert mentions[0]["source_grounded"] is True
    assert mentions[0]["inference_source"] == "footprint_context_indicator_seed_rule"

    finance_mentions = _context_seed_indicator_mentions(
        "财务预测与估值 财务建模 相对估值法"
    )
    finance_canonicals = {
        mention["canonical_metric_candidate"] for mention in finance_mentions
    }
    assert {"revenue_growth", "forecast_net_profit", "valuation_multiple"} <= (
        finance_canonicals
    )

    performance_mentions = _context_seed_indicator_mentions(
        "市场表现回顾 相对强弱比较 板块轮动"
    )
    assert {
        mention["canonical_metric_candidate"] for mention in performance_mentions
    } == {"market_or_sector_index_return"}


def test_report_intelligence_can_skip_processed_batch_source_ids(tmp_path: Path):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    base_row = {
        "abstract": "摘要不能作为本测试的抽取输入。",
        "author": "Analyst A",
        "discovered_at": "2026-06-06T00:00:00+00:00",
        "industry": "宏观",
        "institution": "Broker A",
        "license_status": "pending_review",
        "point_in_time_available": True,
        "query_key": "liquidity",
        "report_type": "宏观研报",
        "source_hash": "sha256:test",
        "source_type": "tushare_research_report",
        "title": "Liquidity report",
        "ts_code": "",
        "url": "https://example.invalid/report.pdf",
    }
    _write_jsonl(
        source_path,
        [
            {
                **base_row,
                "publish_date": "2026-06-05",
                "source_id": "SRC-NEWER-PROCESSED",
                "source_span_id": "SRC-NEWER-PROCESSED:abstract",
            },
            {
                **base_row,
                "publish_date": "2026-06-04",
                "source_id": "SRC-OLDER-UNPROCESSED",
                "source_span_id": "SRC-OLDER-UNPROCESSED:abstract",
            },
        ],
    )
    processed_registry = tmp_path / "previous_batch"
    _write_jsonl(
        processed_registry / "processing_status.jsonl",
        [{"source_id": "SRC-NEWER-PROCESSED", "llm_status": "processed"}],
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            exclude_processed_registry_dirs=("previous_batch",),
            limit=1,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )

    status = _read_jsonl(
        tmp_path / "registry/report_intelligence/processing_status.jsonl"
    )
    assert result.blocker_count == 0
    assert result.selected_reports == 1
    assert status[0]["source_id"] == "SRC-OLDER-UNPROCESSED"


def test_report_intelligence_can_require_cached_markdown_before_limit(tmp_path: Path):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    base_row = {
        "abstract": "摘要不能作为本测试的抽取输入。",
        "author": "Analyst A",
        "discovered_at": "2026-06-06T00:00:00+00:00",
        "industry": "宏观",
        "institution": "Broker A",
        "license_status": "pending_review",
        "point_in_time_available": True,
        "query_key": "liquidity",
        "report_type": "宏观研报",
        "source_hash": "sha256:test",
        "source_type": "tushare_research_report",
        "title": "Liquidity report",
        "ts_code": "",
        "url": "https://example.invalid/report.pdf",
    }
    _write_jsonl(
        source_path,
        [
            {
                **base_row,
                "publish_date": "2026-06-05",
                "source_id": "SRC-NEWER-MISSING-MARKDOWN",
                "source_span_id": "SRC-NEWER-MISSING-MARKDOWN:abstract",
            },
            {
                **base_row,
                "publish_date": "2026-06-04",
                "source_id": "SRC-OLDER-CACHED-MARKDOWN",
                "source_span_id": "SRC-OLDER-CACHED-MARKDOWN:abstract",
            },
        ],
    )
    markdown_path = (
        tmp_path
        / ".mosaic/rke/report_intelligence/markdown/SRC-OLDER-CACHED-MARKDOWN.md"
    )
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "# 流动性脉冲\n报告原文讨论7日公开市场净投放，并用DR007确认资金压力。",
        encoding="utf-8",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            require_cached_markdown=True,
            limit=1,
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    status = _read_jsonl(
        tmp_path / "registry/report_intelligence/processing_status.jsonl"
    )
    assert result.blocker_count == 0
    assert result.selected_reports == 1
    assert result.markdown_ready_count == 1
    assert status[0]["source_id"] == "SRC-OLDER-CACHED-MARKDOWN"


@pytest.mark.parametrize(
    ("markdown_text", "expected_gap"),
    [
        (
            "\n".join(
                [
                    "# 目录",
                    "宏观概览 ................ 1",
                    "行业观点 ................ 2",
                    "公司研究 ................ 3",
                    "投资建议 ................ 4",
                    "风险提示 ................ 5",
                ]
            ),
            "markdown_toc_only",
        ),
        (
            "\n".join(
                [
                    "# 行业报告",
                    "| 指标 | 数值 | 备注 |",
                    "| --- | --- | --- |",
                    "|  |  |  |",
                    "|  |  |  |",
                    "|  |  |  |",
                    "|  |  |  |",
                ]
            ),
            "markdown_empty_table_dominant",
        ),
        (
            "\n".join(
                [
                    "# 公司报告",
                    "![page-1](page-1.png)",
                    "![page-2](page-2.png)",
                    "图片未识别",
                ]
            ),
            "markdown_image_only",
        ),
        (
            "\n".join(
                ["证券研究报告"] * 8
                + ["# 行业观点", "投资建议需要结合更多正文验证。"]
            ),
            "markdown_repeated_line_noise",
        ),
    ],
)
def test_markdown_quality_gate_flags_p9_quality_gaps(
    markdown_text: str,
    expected_gap: str,
):
    markdown = {
        "status": "converted",
        "bytes": len(markdown_text.encode("utf-8")),
        "backend": "hybrid-auto-engine",
    }

    assert _markdown_quality_gap(markdown, markdown_text) == expected_gap


def test_markdown_quality_gate_flags_conversion_instability():
    markdown = {
        "status": "converted",
        "bytes": 200,
        "backend": "hybrid-auto-engine",
        "conversion_instability": True,
    }

    assert _markdown_quality_gap(markdown, "# 行业报告\n投资建议和正文结构存在。") == (
        "markdown_conversion_instability"
    )


def test_report_intelligence_blocks_llm_on_low_quality_markdown(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def low_quality_converter(
        pdf: Path,
        output_dir: Path,
        markdown: Path,
        overwrite: bool,
    ):
        assert pdf.exists()
        output_dir.mkdir(parents=True)
        markdown.parent.mkdir(parents=True)
        markdown.write_text("免责声明\n投资有风险", encoding="utf-8")
        return {
            "status": "converted",
            "path": str(markdown),
            "bytes": markdown.stat().st_size,
            "sha256": _sha(markdown),
            "duration_seconds": 1.25,
        }

    def llm_should_not_run(*args, **kwargs):
        raise AssertionError("LLM extraction must not run on low-quality Markdown")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=low_quality_converter,
        llm_extractor=llm_should_not_run,
    )

    assert result.forecast_claim_rows == 0
    assert result.llm_processed_reports == 0
    assert result.blocker_count == 1
    assert "markdown_disclaimer_only" in result.blockers[0]

    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    markdown = metadata[0]["markdown"]
    assert markdown["quality_gate_status"] == "blocked"
    assert markdown["quality_gap"] == "markdown_disclaimer_only"
    assert markdown["duration_seconds"] == 1.25
    assert metadata[0]["extraction"]["llm_status"] == "blocked"

    status = _read_jsonl(tmp_path / "registry/report_intelligence/processing_status.jsonl")
    assert status[0]["markdown_quality_gate_status"] == "blocked"
    assert status[0]["markdown_quality_gap"] == "markdown_disclaimer_only"
    assert status[0]["markdown_duration_seconds"] == 1.25

    coverage = json.loads(
        (
            tmp_path / "registry/report_intelligence/markdown_coverage_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert coverage["markdown_ready_count"] == 1
    assert coverage["markdown_quality_pass_count"] == 0
    assert coverage["llm_extraction_processed_count"] == 0
    assert coverage["llm_extraction_without_quality_pass_count"] == 0
    assert coverage["industry_report_count"] == 0
    assert coverage["stock_report_count"] == 0
    assert coverage["markdown_quality_gap_counts"] == {"markdown_disclaimer_only": 1}
    assert coverage["markdown_quality_review_queue_count"] == 1
    assert coverage["markdown_quality_review_gap_counts"] == {
        "markdown_disclaimer_only": 1
    }
    assert coverage["markdown_false_positive_review_queue_count"] == 0
    assert coverage["markdown_false_positive_risk_gap_counts"] == {}
    assert coverage["markdown_quality_spot_check_required"] is True
    assert coverage["private_text_included"] is False


def test_markdown_coverage_flags_llm_processed_without_quality_pass():
    summary = build_markdown_coverage_summary(
        run_id="RIR-MARKDOWN-QUALITY-VIOLATION-TEST",
        metadata_rows=[
            {
                "report_type": "公司研报",
                "sector": "bank",
                "pdf": {"status": "downloaded"},
                "markdown": {
                    "status": "converted",
                    "bytes": 200,
                    "backend": "hybrid-auto-engine",
                    "quality_gap": "markdown_disclaimer_only",
                },
                "extraction": {"llm_status": "processed"},
            }
        ],
    )

    assert summary["markdown_ready_count"] == 1
    assert summary["markdown_quality_pass_count"] == 0
    assert summary["llm_extraction_processed_count"] == 1
    assert summary["llm_extraction_without_quality_pass_count"] == 1
    assert summary["industry_report_count"] == 0
    assert summary["stock_report_count"] == 0
    assert summary["markdown_quality_gap_counts"] == {"markdown_disclaimer_only": 1}
    assert summary["markdown_quality_review_queue_count"] == 1
    assert summary["markdown_quality_review_gap_counts"] == {
        "markdown_disclaimer_only": 1
    }
    assert summary["markdown_false_positive_review_queue_count"] == 0
    assert summary["markdown_false_positive_risk_gap_counts"] == {}
    assert summary["markdown_quality_spot_check_required"] is True
    assert summary["private_text_included"] is False
    assert "llm_extraction_without_quality_pass" in summary["coverage_gate_blockers"]
    assert "stock_report_count_below_p9_target" in summary["coverage_gate_blockers"]
    dump = json.dumps(summary, ensure_ascii=False)
    assert "claim_text" not in dump
    assert "source_span_ids" not in dump


def test_markdown_coverage_does_not_bucket_stock_query_key_as_sector():
    summary = build_markdown_coverage_summary(
        run_id="RIR-MARKDOWN-STOCK-SECTOR-BUCKET-TEST",
        metadata_rows=[
            {
                "report_type": "个股研报",
                "query_key": "920003.BJ",
                "ts_code": "920003.BJ",
                "industry": "",
                "sector": "",
                "pdf": {"status": "downloaded"},
                "markdown": {
                    "status": "converted",
                    "bytes": 200,
                    "backend": "hybrid-auto-engine",
                },
                "extraction": {"llm_status": "processed"},
            },
            {
                "report_type": "个股研报",
                "query_key": "832317.BJ",
                "ts_code": "832317.BJ",
                "industry": "832317.BJ",
                "sector": "",
                "pdf": {"status": "downloaded"},
                "markdown": {
                    "status": "converted",
                    "bytes": 200,
                    "backend": "hybrid-auto-engine",
                },
                "extraction": {"llm_status": "processed"},
            }
        ],
    )

    assert summary["stock_report_count"] == 1
    assert summary["sector_bucket_counts"] == {"other_sector": 2}
    assert "920003.BJ" not in summary["sector_bucket_counts"]
    assert "832317.BJ" not in summary["sector_bucket_counts"]
    assert all(
        "920003.BJ" not in gap and "832317.BJ" not in gap
        for gap in summary["sector_bucket_coverage_gaps"]
    )


def test_markdown_coverage_tracks_quality_review_false_positive_risk():
    summary = build_markdown_coverage_summary(
        run_id="RIR-MARKDOWN-REVIEW-QUEUE-TEST",
        metadata_rows=[
            {
                "report_type": "行业研报",
                "sector": "metals",
                "pdf": {"status": "downloaded"},
                "markdown": {
                    "status": "converted",
                    "bytes": 1000,
                    "backend": "hybrid-auto-engine",
                    "quality_gap": "markdown_repeated_line_noise",
                },
                "extraction": {"llm_status": "blocked"},
            },
            {
                "report_type": "公司研报",
                "sector": "bank",
                "pdf": {"status": "downloaded"},
                "markdown": {
                    "status": "blocked",
                    "bytes": 0,
                    "backend": "hybrid-auto-engine",
                    "quality_gap": "mineru_timeout",
                },
                "extraction": {"llm_status": "blocked"},
            },
        ],
    )

    assert summary["retry_queue_count"] == 1
    assert summary["industry_report_count"] == 1
    assert summary["stock_report_count"] == 0
    assert summary["markdown_quality_review_queue_count"] == 1
    assert summary["markdown_quality_review_gap_counts"] == {
        "markdown_repeated_line_noise": 1
    }
    assert summary["markdown_false_positive_review_queue_count"] == 1
    assert summary["markdown_false_positive_risk_gap_counts"] == {
        "markdown_repeated_line_noise": 1
    }
    assert summary["markdown_quality_spot_check_required"] is True
    assert summary["private_text_included"] is False


def test_markdown_coverage_requires_stratified_industry_and_stock_samples():
    def ready_row(
        index: int,
        *,
        report_type: str,
        ts_code: str = "",
    ) -> dict[str, object]:
        if index < 100:
            publish_datetime = "2026-06-01T00:00:00+08:00"
        elif index < 200:
            publish_datetime = "2024-06-01T00:00:00+08:00"
        else:
            publish_datetime = "2020-06-01T00:00:00+08:00"
        return {
            "source_id": f"SRC-STRATA-{index:03d}",
            "report_type": report_type,
            "institution": "Head Broker" if index < 20 else f"Tail Broker {index}",
            "publish_datetime": publish_datetime,
            "sector": f"sector-{index % 6}",
            "ts_code": ts_code,
            "pdf": {"status": "downloaded"},
            "markdown": {
                "status": "converted",
                "bytes": 200,
                "backend": "hybrid-auto-engine",
            },
            "extraction": {"llm_status": "processed"},
        }

    def forecast_row(index: int, *, mapping_gap: bool = False) -> dict[str, object]:
        horizons = [5, 20, 60, 120]
        if 80 <= index < 159:
            target = {"target_type": "stock", "target_id": "000001.SZ"}
        elif index >= 159:
            target = {
                "target_type": "macro_asset",
                "target_id": "CN_A_SHARE_BROAD",
            }
        else:
            target = {"target_type": "sector", "target_id": "半导体"}
        return {
            "source_id": f"SRC-STRATA-{index:03d}",
            "target": {} if mapping_gap else target,
            "benchmark": {} if mapping_gap else {"benchmark_id": "SH510300"},
            "direction": "positive",
            "horizon": {"preferred_days": horizons[index % len(horizons)]},
        }

    rows = [
        *[ready_row(index, report_type="行业研报") for index in range(80)],
        *[
            ready_row(index, report_type="公司研报", ts_code=f"000{index:03d}.SZ")
            for index in range(80, 159)
        ],
        *[ready_row(index, report_type="宏观研报") for index in range(159, 300)],
    ]
    forecast_rows = [
        forecast_row(index, mapping_gap=index == 159)
        for index in range(300)
    ]

    summary = build_markdown_coverage_summary(
        run_id="RIR-MARKDOWN-STRATA-TEST",
        metadata_rows=rows,
        forecast_rows=forecast_rows,
    )

    assert summary["industry_report_count"] == 80
    assert summary["stock_report_count"] == 79
    assert summary["coverage_gate_status"] == "blocked"
    assert summary["coverage_gate_blockers"] == [
        "stock_report_count_below_p9_target"
    ]
    assert summary["stratified_sampling_policy"]["required_dimensions"] == [
        "report_type",
        "time_bucket",
        "institution_bucket",
        "sector_bucket",
        "stock_ts_code",
        "stock_outcome_age_bucket",
        "horizon_bucket",
        "evaluability_bucket",
    ]
    assert summary["time_bucket_counts"] == {
        "long_cycle_history": 100,
        "recent_1y": 100,
        "recent_3y": 100,
    }
    assert summary["institution_bucket_counts"] == {
        "head_institution": 20,
        "long_tail_institution": 280,
    }
    assert set(summary["report_horizon_bucket_counts"]) == {
        "5d",
        "20d",
        "60d",
        "long_horizon",
    }
    assert summary["sector_bucket_coverage_gaps"] == []
    assert summary["sector_bucket_below_min_count"] == 0
    assert {
        "industry_proxy_candidate",
        "mapping_gap_candidate",
        "stock_proxy_candidate",
    } <= set(summary["evaluability_bucket_counts"])
    assert summary["stock_outcome_120d_ready_report_count"] == 59
    assert summary["stock_outcome_age_bucket_counts"] == {
        "stock_outcome_120d_calendar_ready": 59,
        "stock_outcome_pending": 20,
    }

    passing = build_markdown_coverage_summary(
        run_id="RIR-MARKDOWN-STRATA-PASS-TEST",
        metadata_rows=[
            *rows,
            ready_row(999, report_type="公司研报", ts_code="000999.SZ"),
        ],
        forecast_rows=[
            *forecast_rows,
            {
                "source_id": "SRC-STRATA-999",
                "target": {"target_type": "stock", "target_id": "000999.SZ"},
                "benchmark": {"benchmark_id": "SH510300"},
                "direction": "positive",
                "horizon": {"preferred_days": 120},
            },
        ],
    )
    assert passing["stock_report_count"] == 80
    assert passing["coverage_gate_status"] == "passed"
    assert passing["coverage_gate_blockers"] == []


def test_report_intelligence_analysis_recipes_pin_required_data():
    recipes = build_analysis_recipes(
        [
            {
                "method_pattern_id": "METHOD-REQUIRED-DATA",
                "name": "Required Data Method",
                "required_current_data": ["stock_price", "benchmark_return"],
                "steps": ["compare stock price with benchmark return"],
            },
            {
                "method_pattern_id": "METHOD-INFERRED-DATA",
                "name": "Inferred Data Method",
                "required_current_data": [],
                "steps": ["calculate sector index return"],
            },
            {
                "method_pattern_id": "METHOD-REASONING-STEP",
                "name": "Reasoning Step Method",
                "required_current_data": [],
                "steps": ["identify key catalysts and compare scenarios"],
            },
        ]
    )

    by_id = {row["method_pattern_id"]: row for row in recipes}
    assert by_id["METHOD-REQUIRED-DATA"]["promotion_state"] == "shadow_candidate"
    assert by_id["METHOD-REQUIRED-DATA"]["recipe_id"] == by_id[
        "METHOD-REQUIRED-DATA"
    ]["analysis_recipe_id"]
    assert by_id["METHOD-REQUIRED-DATA"]["source_method_pattern_ids"] == [
        "METHOD-REQUIRED-DATA"
    ]
    assert by_id["METHOD-REQUIRED-DATA"]["decision_scope"] == (
        "required_data_method_score"
    )
    assert by_id["METHOD-REQUIRED-DATA"][
        "entry_condition"
    ] == "T+1_or_more_conservative_shadow_entry"
    assert by_id["METHOD-REQUIRED-DATA"]["exit_condition"] == "fixed_horizon_shadow_exit"
    assert by_id["METHOD-REQUIRED-DATA"]["expected_horizon_days"] == 60
    assert "no_production_order" in by_id["METHOD-REQUIRED-DATA"]["risk_controls"]
    assert "turnover_cost_decay_blocks_validation" in by_id[
        "METHOD-REQUIRED-DATA"
    ]["risk_controls"]
    assert by_id["METHOD-REQUIRED-DATA"]["required_data"] == [
        "metric:stock_price",
        "metric:benchmark_return",
    ]
    assert by_id["METHOD-INFERRED-DATA"]["required_data"] == [
        "metric:calculate_sector_index_return"
    ]
    assert by_id["METHOD-INFERRED-DATA"]["required_tools"] == [
        "market.price_proxy"
    ]
    assert by_id["METHOD-INFERRED-DATA"]["steps"][0]["tool"] == (
        "market.price_proxy"
    )
    assert by_id["METHOD-REASONING-STEP"]["required_tools"] == []
    assert by_id["METHOD-REASONING-STEP"]["required_data"] == [
        "metric:stock_price",
        "metric:benchmark_return",
    ]
    assert by_id["METHOD-REASONING-STEP"]["steps"][0]["tool"] == (
        "analysis.reasoning_step"
    )
    assert by_id["METHOD-REASONING-STEP"]["steps"][0][
        "requires_external_tool"
    ] is False


def test_report_intelligence_method_patterns_keep_source_footprint_refs():
    methods = _normalize_method_patterns(
        {},
        [
            {
                "footprint_id": "AFP-1",
                "analysis_patterns": [
                    "compare target return with benchmark",
                    {"pattern": "check valuation and liquidity"},
                ],
                "target_agent_candidates": ["stock_agent"],
            }
        ],
        run_id="RIR-TEST",
        model="test-model",
    )

    assert len(methods) == 2
    assert all(row["source_footprint_ids"] == ["AFP-1"] for row in methods)
    assert {row["name"] for row in methods} == {
        "compare target return with benchmark",
        "check valuation and liquidity",
    }
    assert all(row["steps"] for row in methods)


def test_report_intelligence_method_pattern_ids_use_canonical_key():
    first = _normalize_method_patterns(
        {
            "method_patterns": [
                {"name": "Peer comparison", "steps": ["compare peers"]},
                {"name": "Peer-comparison", "steps": ["compare peer group"]},
            ]
        },
        [],
        run_id="RIR-TEST",
        model="test-model",
    )
    reversed_order = _normalize_method_patterns(
        {
            "method_patterns": [
                {"name": "Peer-comparison", "steps": ["compare peer group"]},
                {"name": "Peer comparison", "steps": ["compare peers"]},
            ]
        },
        [],
        run_id="RIR-TEST",
        model="test-model",
    )

    assert len(first) == 1
    assert len(reversed_order) == 1
    assert first[0]["canonical_name"] == "peer_comparison"
    assert reversed_order[0]["canonical_name"] == "peer_comparison"
    assert first[0]["method_pattern_id"] == reversed_order[0]["method_pattern_id"]
    assert first[0]["steps"] == ["compare peers", "compare peer group"]
    assert reversed_order[0]["steps"] == ["compare peer group", "compare peers"]


def test_report_intelligence_method_pattern_merge_upgrades_legacy_ids():
    rows = [
        {
            "method_pattern_id": "METHOD-legacy",
            "name": "Peer comparison",
            "steps": ["compare peers"],
            "source_footprint_ids": ["AFP-1"],
        }
    ]

    _append_unique_method_patterns(
        rows,
        [
            {
                "method_pattern_id": "METHOD-new",
                "canonical_name": "peer_comparison",
                "name": "Peer-comparison",
                "steps": ["compare peer group"],
                "source_footprint_ids": ["AFP-2"],
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0]["method_pattern_id"] != "METHOD-legacy"
    assert rows[0]["method_pattern_id"] != "METHOD-new"
    assert rows[0]["method_pattern_id"].startswith("METHOD-")
    assert rows[0]["canonical_name"] == "peer_comparison"
    assert rows[0]["steps"] == ["compare peers", "compare peer group"]
    assert rows[0]["source_footprint_ids"] == ["AFP-1", "AFP-2"]


def test_report_intelligence_recipe_paper_trading_requires_direct_pit_evidence():
    recipe = {
        "analysis_recipe_id": "RECIPE-DIRECT-PIT",
        "recipe_id": "RECIPE-DIRECT-PIT",
        "method_pattern_id": "METHOD-DIRECT-PIT",
        "source_method_pattern_ids": ["METHOD-DIRECT-PIT"],
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "required_data": ["stock_price", "benchmark_return"],
        "decision_scope": "explicit_direct_pit_scope",
        "entry_condition": "T+1_or_more_conservative_shadow_entry",
        "exit_condition": "fixed_horizon_shadow_exit",
        "risk_controls": [
            "no_production_order",
            "no_position_sizing",
            "after_cost_alpha_required",
            "consecutive_after_cost_decay_blocks_validation",
            "turnover_cost_decay_blocks_validation",
            "drawdown_threshold_pre_registered",
        ],
        "expected_horizon_days": 120,
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "direct_pit_score"},
    }
    labels = []
    for day, value, hit, horizon, regime in (
        (10, 0.01, True, 5, "base"),
        (11, 0.02, False, 20, "stress"),
        (12, 0.015, True, 60, "recovery"),
        (13, 0.018, False, 120, "base"),
        (14, 0.02, True, 20, "stress"),
    ):
        labels.append(
            {
                "analysis_recipe_id": "RECIPE-DIRECT-PIT",
                "method_pattern_id": "METHOD-DIRECT-PIT",
                "exit_datetime": f"2026-01-{day:02d}",
                "directional_after_cost_return": value,
                "benchmark_return": 0.005,
                "directional_hit": hit,
                "horizon_days": horizon,
                "market_regime": regime,
                "effective_n_weight": 1.0,
            }
        )

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=runs,
    )
    observations = build_confidence_impact_observations(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=runs,
    )
    monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-PAPER",
        confidence_observation_rows=observations,
        recipe_paper_trading_summary=summary,
    )

    assert runs[0]["paper_trading_status"] == "passed"
    assert runs[0]["blocked_reasons"] == []
    assert str(runs[0]["pre_registration_hash"]).startswith("sha256:")
    assert runs[0]["source_method_pattern_ids"] == ["METHOD-DIRECT-PIT"]
    assert runs[0]["required_data"] == [
        "metric:stock_price",
        "metric:benchmark_return",
    ]
    assert runs[0]["decision_scope"] == "explicit_direct_pit_scope"
    assert runs[0]["expected_horizon_days"] == 120
    assert runs[0]["profile_weight_support"]["profile_only_validation_allowed"] is False
    assert runs[0]["pre_registered_protocol"][
        "parameter_tuning_after_results_allowed"
    ] is False
    assert runs[0]["pre_registered_protocol"]["alpha_decay_fail_streak"] == 2
    assert runs[0]["pre_registered_protocol"]["benchmark_source"] == "cn_etf"
    assert runs[0]["pre_registered_protocol"]["cost_decay_turnover_threshold"] == 6.0
    assert runs[0]["pre_registered_protocol"]["slippage_model_id"] == (
        "included_in_round_trip_cost_20bps_v1"
    )
    assert runs[0]["pre_registered_protocol"]["backtest_window_policy"] == (
        "chronological_pre_oos_exit_windows_v1"
    )
    assert runs[0]["pre_registered_protocol"]["out_of_sample_window_policy"] == (
        "chronological_last_20pct_min_effective_n_exit_windows_v1"
    )
    assert runs[0]["pre_registered_protocol"][
        "minimum_out_of_sample_effective_n"
    ] == 1.0
    assert "turnover_cost_decay_blocks_validation" in runs[0]["risk_controls"]
    assert runs[0]["metrics"]["brier_score"] == 0.01
    assert runs[0]["metrics"]["non_positive_after_cost_window_streak"] == 0
    assert runs[0]["metrics"]["backtest_label_count"] == 4
    assert runs[0]["metrics"]["backtest_effective_n"] == 4.0
    assert runs[0]["metrics"]["backtest_cost_adjusted_alpha"] == 0.01575
    assert runs[0]["metrics"]["out_of_sample_label_count"] == 1
    assert runs[0]["metrics"]["out_of_sample_effective_n"] == 1.0
    assert runs[0]["metrics"]["out_of_sample_cost_adjusted_alpha"] == 0.02
    assert runs[0]["metrics"]["out_of_sample_start_exit_datetime"] == "2026-01-14"
    assert runs[0]["metrics"]["max_horizon_contribution_share"] == 0.4
    assert runs[0]["metrics"]["observed_horizon_count"] == 4
    assert runs[0]["metrics"]["horizon_missing_count"] == 0
    assert runs[0]["metrics"]["max_regime_contribution_share"] == 0.4
    assert runs[0]["metrics"]["observed_regime_count"] == 3
    assert summary["validation_pass_count"] == 1
    assert summary["paper_trading_validated_recipe_count"] == 1
    assert summary["after_cost_paper_trading_summary"] == {
        "status": "computed",
        "validated_recipe_count": 1,
        "mean_after_cost_alpha": 0.0166,
        "median_after_cost_alpha": 0.0166,
        "min_after_cost_alpha": 0.0166,
        "max_after_cost_alpha": 0.0166,
        "positive_after_cost_recipe_count": 1,
        "policy": (
            "computed from passed pre-registered paper-trading runs only; "
            "blocked or profile-only recipes are excluded"
        ),
    }
    assert summary["direct_pit_bound_recipe_count"] == 1
    assert summary["direct_pit_bound_recipe_ids"] == ["RECIPE-DIRECT-PIT"]
    assert summary["direct_pit_bound_blocker_counts"] == {}
    assert summary["direct_pit_binding_diagnostics"] == {
        "status": "ready_for_validation",
        "diagnostic_only": True,
        "policy": (
            "profile weights and method names are insufficient; recipe "
            "paper-trading requires direct PIT outcome labels bound to the "
            "recipe or its source method pattern"
        ),
        "recipe_count": 1,
        "direct_pit_bound_recipe_count": 1,
        "no_direct_recipe_outcome_binding_count": 0,
        "insufficient_effective_n_count": 0,
        "required_tools_not_shadow_implemented_count": 0,
        "next_actions": ["monitor validated paper-trading drift"],
    }
    assert summary["validation_candidate_recipe_count"] == 1
    assert summary["tool_only_blocked_recipe_count"] == 0
    assert summary["tool_only_blocked_tool_gap_count"] == 0
    assert summary["tool_only_blocked_tool_proposal_count"] == 0
    assert summary["tool_implementation_queue"]["blocked_recipe_count"] == 0
    assert summary["tool_implementation_queue"]["requested_tools"] == []
    assert summary["tool_implementation_queue"]["tool_gap_ids"] == []
    assert summary["validation_protocol"] == runs[0]["pre_registered_protocol"]
    assert observations[0]["confidence_delta"] > 0
    assert observations[0]["drift_status"] == "stable_shadow"
    assert observations[0]["brier_score"] == 0.01
    assert observations[0]["regime"] == "base"
    assert observations[0]["regime_status"] == "dominant_observed"
    assert observations[0]["regime_contribution_shares"] == {
        "base": 0.4,
        "recovery": 0.2,
        "stress": 0.4,
    }
    assert observations[0]["max_regime_contribution_share"] == 0.4
    assert observations[0]["observed_regime_count"] == 3
    assert observations[0]["market_regime_missing_count"] == 0
    assert observations[0]["market_regime_coverage_status"] == "observed"
    assert monitor["paper_trading_validated_recipe_count"] == 1
    assert monitor["tracked_recipe_ids"] == ["RECIPE-DIRECT-PIT"]
    assert monitor["alpha_decay_recipe_ids"] == []
    assert monitor["production_decision_impact_allowed"] is False

    multi_regime_labels = [dict(label) for label in labels]
    multi_regime_labels[0]["market_regime_types"] = ["base", "stress"]
    multi_regime_labels[0]["market_regime"] = "base|stress"
    multi_regime_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=multi_regime_labels,
        method_performance_profile_rows=[],
    )
    assert multi_regime_runs[0]["paper_trading_status"] == "passed"
    assert multi_regime_runs[0]["metrics"]["regime_contribution_shares"] == {
        "base": 0.3,
        "recovery": 0.2,
        "stress": 0.5,
    }

    no_regime_labels = []
    for label in labels:
        no_regime_label = dict(label)
        no_regime_label.pop("market_regime", None)
        no_regime_labels.append(no_regime_label)
    no_regime_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=no_regime_labels,
        method_performance_profile_rows=[],
    )

    assert no_regime_runs[0]["paper_trading_status"] == "passed"
    assert no_regime_runs[0]["metrics"]["market_regime_coverage_status"] == (
        "missing_diagnostic_only"
    )
    no_regime_observations = build_confidence_impact_observations(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=no_regime_runs,
    )
    assert no_regime_observations[0]["regime"] == "unknown"
    assert no_regime_observations[0]["regime_status"] == "missing_diagnostic"
    assert no_regime_observations[0]["regime_contribution_shares"] == {}
    assert no_regime_observations[0]["market_regime_coverage_status"] == (
        "missing_diagnostic_only"
    )
    assert "market_regime_missing" not in no_regime_runs[0]["blocked_reasons"]
    assert "single_regime_concentration" not in no_regime_runs[0]["blocked_reasons"]

    blocked_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=[],
        method_performance_profile_rows=[
            {
                "method_pattern_id": "METHOD-DIRECT-PIT",
                "method_profile_id": "MPP-DIRECT-PIT",
                "source_support": {"n_effective_reports": 5.0},
            }
        ],
    )
    blocked_observations = build_confidence_impact_observations(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=blocked_runs,
    )
    blocked_summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=blocked_runs,
    )
    blocked_monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-PAPER",
        confidence_observation_rows=blocked_observations,
        recipe_paper_trading_summary=blocked_summary,
    )

    assert blocked_runs[0]["paper_trading_status"] == "blocked"
    assert "no_direct_recipe_outcome_binding" in blocked_runs[0]["blocked_reasons"]
    assert (
        blocked_runs[0]["profile_weight_support"][
            "profile_paper_trade_disagreement"
        ]
        is True
    )
    assert blocked_observations[0]["confidence_delta"] == 0.0
    assert (
        blocked_observations[0]["drift_status"]
        == "profile_paper_trade_disagreement"
    )
    assert blocked_observations[0]["recommended_action"] == "send_to_manual_review"
    assert blocked_summary["profile_paper_trade_disagreement_count"] == 1
    assert blocked_summary["direct_pit_bound_recipe_count"] == 0
    assert blocked_summary["direct_pit_binding_diagnostics"]["status"] == (
        "blocked_no_direct_pit_binding"
    )
    assert blocked_summary["direct_pit_binding_diagnostics"][
        "no_direct_recipe_outcome_binding_count"
    ] == 1
    assert blocked_monitor["profile_paper_trade_disagreement_count"] == 1
    assert blocked_monitor["profile_paper_trade_disagreement_recipe_ids"] == [
        "RECIPE-DIRECT-PIT"
    ]
    assert blocked_monitor["manual_review_recipe_ids"] == ["RECIPE-DIRECT-PIT"]

    missing_required_data = dict(recipe)
    missing_required_data["required_data"] = []
    missing_data_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[missing_required_data],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    assert missing_data_runs[0]["paper_trading_status"] == "blocked"
    assert "required_data_missing" in missing_data_runs[0]["blocked_reasons"]

    changed_recipe = dict(recipe)
    changed_recipe["required_data"] = ["stock_price", "benchmark_return", "liquidity"]
    changed_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[changed_recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    assert changed_runs[0]["pre_registration_hash"] != runs[0][
        "pre_registration_hash"
    ]
    assert changed_runs[0]["required_data"] == [
        "metric:stock_price",
        "metric:benchmark_return",
        "metric:liquidity",
    ]

    tool_blocked_recipe = dict(recipe)
    tool_blocked_recipe["analysis_recipe_id"] = "RECIPE-TOOL-BLOCKED"
    tool_blocked_recipe["recipe_id"] = "RECIPE-TOOL-BLOCKED"
    tool_blocked_recipe["method_pattern_id"] = "METHOD-TOOL-BLOCKED"
    tool_blocked_recipe["source_method_pattern_ids"] = ["METHOD-TOOL-BLOCKED"]
    tool_blocked_recipe["required_tools"] = [
        "tool.requested.market_unimplemented_proxy"
    ]
    tool_blocked_recipe["steps"] = [
        {"step": 1, "tool": "tool.requested.market_unimplemented_proxy"}
    ]
    tool_blocked_labels = [
        dict(
            label,
            analysis_recipe_id="RECIPE-TOOL-BLOCKED",
            method_pattern_id="METHOD-TOOL-BLOCKED",
        )
        for label in labels
    ]
    tool_blocked_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[tool_blocked_recipe],
        outcome_label_rows=tool_blocked_labels,
        method_performance_profile_rows=[],
    )
    tool_blocked_summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=tool_blocked_runs,
        tool_gap_rows=[
            {
                "tool_gap_id": "TG-TOOL-BLOCKED",
                "method_pattern_ids": ["METHOD-TOOL-BLOCKED"],
            }
        ],
        tool_design_proposal_rows=[
            {
                "tool_proposal_id": "TDP-TOOL-BLOCKED",
                "tool_gap_id": "TG-TOOL-BLOCKED",
            }
        ],
    )

    assert tool_blocked_runs[0]["paper_trading_status"] == "blocked"
    assert tool_blocked_runs[0]["blocked_reasons"] == [
        "required_tools_not_shadow_implemented"
    ]
    assert tool_blocked_summary["direct_pit_bound_recipe_count"] == 1
    assert tool_blocked_summary["direct_pit_binding_diagnostics"]["status"] == (
        "partial_direct_pit_binding"
    )
    assert tool_blocked_summary["direct_pit_binding_diagnostics"][
        "required_tools_not_shadow_implemented_count"
    ] == 1
    assert tool_blocked_summary["tool_only_blocked_recipe_ids"] == [
        "RECIPE-TOOL-BLOCKED"
    ]
    assert tool_blocked_summary["tool_only_blocked_tool_gap_ids"] == [
        "TG-TOOL-BLOCKED"
    ]
    assert tool_blocked_summary["tool_only_blocked_tool_proposal_ids"] == [
        "TDP-TOOL-BLOCKED"
    ]
    assert tool_blocked_summary["tool_implementation_queue"]["tool_gap_ids"] == [
        "TG-TOOL-BLOCKED"
    ]
    assert tool_blocked_summary["tool_implementation_queue"]["tool_proposal_ids"] == [
        "TDP-TOOL-BLOCKED"
    ]
    assert tool_blocked_summary["tool_implementation_queue"][
        "blocked_recipe_ids"
    ] == ["RECIPE-TOOL-BLOCKED"]
    assert tool_blocked_summary["tool_implementation_queue"]["requested_tools"] == [
        "tool.requested.market_unimplemented_proxy"
    ]

    multi_blocked_recipe = dict(tool_blocked_recipe)
    multi_blocked_recipe["analysis_recipe_id"] = "RECIPE-MULTI-BLOCKED"
    multi_blocked_recipe["recipe_id"] = "RECIPE-MULTI-BLOCKED"
    multi_blocked_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-PAPER",
        analysis_recipe_rows=[multi_blocked_recipe],
        outcome_label_rows=[],
        method_performance_profile_rows=[],
    )
    multi_blocked_summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-PAPER",
        recipe_paper_trading_runs=multi_blocked_runs,
        tool_gap_rows=[
            {
                "tool_gap_id": "TG-TOOL-BLOCKED",
                "method_pattern_ids": ["METHOD-TOOL-BLOCKED"],
            }
        ],
    )

    assert set(multi_blocked_runs[0]["blocked_reasons"]) == {
        "insufficient_effective_n",
        "no_direct_recipe_outcome_binding",
        "required_tools_not_shadow_implemented",
    }
    assert multi_blocked_summary["tool_only_blocked_recipe_ids"] == []
    assert multi_blocked_summary["tool_implementation_queue"][
        "blocked_recipe_ids"
    ] == ["RECIPE-MULTI-BLOCKED"]
    assert multi_blocked_summary["tool_implementation_queue"]["requested_tools"] == [
        "tool.requested.market_unimplemented_proxy"
    ]
    assert multi_blocked_summary["tool_implementation_queue"]["tool_gap_ids"] == [
        "TG-TOOL-BLOCKED"
    ]


def test_direct_pit_binding_gap_details_trace_missing_method_links():
    details = _direct_pit_binding_gap_details(
        analysis_recipe_rows=[
            {
                "analysis_recipe_id": "RECIPE-GAP",
                "method_pattern_id": "METHOD-GAP",
                "source_method_pattern_ids": ["METHOD-GAP"],
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-GAP",
                "forecast_claim_id": "CLAIM-GAP",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "CLAIM-GAP",
                "source_id": "SRC-GAP",
                "report_id": "REPORT-GAP",
            }
        ],
        footprint_rows=[
            {
                "footprint_id": "FP-GAP",
                "source_id": "SRC-GAP",
                "report_id": "REPORT-GAP",
            }
        ],
        method_rows=[
            {
                "method_pattern_id": "METHOD-GAP",
                "source_footprint_ids": [],
            }
        ],
    )

    assert details["artifact_counts"] == {
        "analysis_recipe_rows": 1,
        "outcome_label_rows": 1,
        "forecast_claim_rows": 1,
        "analytical_footprint_rows": 1,
        "method_pattern_rows": 1,
    }
    assert details["method_source_linkage"][
        "method_patterns_without_source_footprints"
    ] == 1
    assert details["forecast_outcome_linkage"][
        "outcome_label_forecast_ids_missing_from_forecast_artifact"
    ] == 0
    assert details["recipe_binding_linkage"][
        "recipes_with_direct_or_method_outcome_binding"
    ] == 0
    assert details["missing_artifact_flags"] == ["method_source_footprints_empty"]

    linked_details = _direct_pit_binding_gap_details(
        analysis_recipe_rows=[
            {
                "analysis_recipe_id": "RECIPE-LINKED",
                "method_pattern_id": "METHOD-LINKED",
                "source_method_pattern_ids": ["METHOD-LINKED"],
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-LINKED",
                "forecast_claim_id": "CLAIM-LINKED",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "CLAIM-LINKED",
                "source_id": "SRC-LINKED",
            }
        ],
        footprint_rows=[
            {
                "footprint_id": "FP-LINKED",
                "source_id": "SRC-LINKED",
            }
        ],
        method_rows=[
            {
                "method_pattern_id": "METHOD-LINKED",
                "source_footprint_ids": ["FP-LINKED"],
            }
        ],
    )

    assert linked_details["method_source_linkage"][
        "method_patterns_with_source_footprints"
    ] == 1
    assert linked_details["recipe_binding_linkage"][
        "inferred_method_pattern_label_count"
    ] == 1
    assert linked_details["recipe_binding_linkage"][
        "recipes_with_direct_or_method_outcome_binding"
    ] == 1


def test_recipe_paper_trading_summary_carries_public_binding_gap_details():
    summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-GAP-SUMMARY",
        recipe_paper_trading_runs=[
            {
                "analysis_recipe_id": "RECIPE-GAP",
                "paper_trading_status": "blocked",
                "blocked_reasons": ["no_direct_recipe_outcome_binding"],
                "metrics": {"effective_n": 0.0},
                "source_method_pattern_ids": ["METHOD-GAP"],
                "required_tools": [],
            }
        ],
        direct_pit_binding_gap_details={
            "diagnostic_version": "direct_pit_binding_gap_v1",
            "artifact_counts": {"analysis_recipe_rows": 1},
            "method_source_linkage": {
                "method_patterns_without_source_footprints": 1
            },
            "forecast_outcome_linkage": {"forecast_claim_count": 0},
            "footprint_source_linkage": {"analytical_footprint_count": 0},
            "recipe_binding_linkage": {
                "recipes_with_direct_or_method_outcome_binding": 0
            },
            "missing_artifact_flags": ["method_source_footprints_empty"],
            "next_actions": ["regenerate method patterns with source links"],
        },
    )

    diagnostics = summary["direct_pit_binding_diagnostics"]
    assert diagnostics["status"] == "blocked_no_direct_pit_binding"
    assert diagnostics["binding_gap_details"]["diagnostic_version"] == (
        "direct_pit_binding_gap_v1"
    )
    assert diagnostics["binding_gap_details"]["missing_artifact_flags"] == [
        "method_source_footprints_empty"
    ]


def test_report_intelligence_patch_coverage_uses_public_counts_without_private_inputs(
    tmp_path: Path,
):
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True, exist_ok=True)
    source_registry = Path("registry/report_intelligence")
    for filename in (
        "feature_flags.json",
        "extraction_report.json",
        "metric_candidates.jsonl",
        "method_patterns.jsonl",
        "tool_coverage_matches.jsonl",
        "tool_gaps.jsonl",
        "data_acquisition_proposals.jsonl",
        "tool_design_proposals.jsonl",
        "report_forecast_ledger.jsonl",
        "outcome_labeling_readiness.json",
        "source_performance_profiles.jsonl",
        "viewpoint_performance_profiles.jsonl",
        "method_performance_profiles.jsonl",
        "analysis_recipes.jsonl",
        "weighted_research_contexts.jsonl",
        "runtime_tool_gap_observations.jsonl",
        "monitoring_report.json",
        "runtime_safety_audit.json",
        "pit_leakage_audit.json",
        "extraction_provenance_audit.json",
        "statistical_robustness_audit.json",
        "tool_feasibility_audit.json",
        "recipe_validation_audit.json",
        "analytical_footprint_review_summary.json",
        "analytical_footprint_error_taxonomy.json",
    ):
        shutil.copy2(source_registry / filename, registry_dir / filename)
    gold_dir = tmp_path / "registry/gold_sets"
    gold_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path("registry/gold_sets/tushare_research_reports.review_summary.json"),
        gold_dir / "tushare_research_reports.review_summary.json",
    )

    write_report_intelligence_patch_v1_5_coverage_report(
        registry_dir,
        run_id="RIR-PATCH-FALLBACK-TEST",
    )

    report = json.loads(
        (registry_dir / "patch_v1_5_coverage_report.json").read_text(
            encoding="utf-8"
        )
    )
    extraction_report = json.loads(
        (registry_dir / "extraction_report.json").read_text(encoding="utf-8")
    )
    assert report["corpus_counts"]["forecast_claim_rows"] == extraction_report[
        "forecast_claim_rows"
    ]
    assert report["corpus_counts"]["outcome_label_rows"] == extraction_report[
        "outcome_label_rows"
    ]
    assert "forecast_claims" in report["count_only_public_fallbacks"]
    assert "report_outcome_labels" in report["count_only_public_fallbacks"]
    assert "forecast_claims: missing" not in report["blockers"]
    phase_c = next(row for row in report["phase_records"] if row["phase_id"] == "C")
    assert phase_c["accepted"] is True
    assert phase_c["failure_count"] == 0


def test_report_intelligence_recipe_paper_trading_infers_unique_method_binding():
    recipe = {
        "analysis_recipe_id": "RECIPE-INFERRED-PIT",
        "recipe_id": "RECIPE-INFERRED-PIT",
        "method_pattern_id": "METHOD-INFERRED-PIT",
        "source_method_pattern_ids": ["METHOD-INFERRED-PIT"],
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "required_data": ["stock_price", "benchmark_return"],
        "decision_scope": "inferred_direct_pit_scope",
        "entry_condition": "T+1_or_more_conservative_shadow_entry",
        "exit_condition": "fixed_horizon_shadow_exit",
        "risk_controls": [
            "no_production_order",
            "no_position_sizing",
            "after_cost_alpha_required",
            "consecutive_after_cost_decay_blocks_validation",
            "turnover_cost_decay_blocks_validation",
            "drawdown_threshold_pre_registered",
        ],
        "expected_horizon_days": 120,
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "inferred_pit_score"},
    }
    forecast_rows = [
        {
            "forecast_claim_id": "FC-INFERRED",
            "source_id": "SRC-INFERRED",
            "report_id": "RPT-INFERRED",
        }
    ]
    footprint_rows = [
        {
            "footprint_id": "AFP-INFERRED",
            "source_id": "SRC-INFERRED",
            "report_id": "RPT-INFERRED",
        }
    ]
    method_rows = [
        {
            "method_pattern_id": "METHOD-INFERRED-PIT",
            "source_footprint_ids": ["AFP-INFERRED"],
        }
    ]
    labels = [
        {
            "forecast_claim_id": "FC-INFERRED",
            "exit_datetime": f"2026-02-{day:02d}",
            "directional_after_cost_return": 0.02,
            "benchmark_return": 0.005,
            "directional_hit": True,
            "horizon_days": horizon,
            "market_regime": regime,
            "effective_n_weight": 1.0,
        }
        for day, horizon, regime in (
            (10, 5, "base"),
            (11, 20, "stress"),
            (12, 60, "recovery"),
            (13, 120, "base"),
            (14, 20, "stress"),
        )
    ]

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-INFERRED-PAPER",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        forecast_rows=forecast_rows,
        footprint_rows=footprint_rows,
        method_rows=method_rows,
    )

    assert runs[0]["paper_trading_status"] == "passed"
    assert runs[0]["blocked_reasons"] == []
    assert runs[0]["metrics"]["backtest_effective_n"] == 4.0


def test_recipe_paper_trading_binds_all_source_method_pattern_ids():
    recipe = {
        "analysis_recipe_id": "RECIPE-SOURCE-METHODS",
        "recipe_id": "RECIPE-SOURCE-METHODS",
        "method_pattern_id": "METHOD-PRIMARY",
        "source_method_pattern_ids": ["METHOD-PRIMARY", "METHOD-SECONDARY"],
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": [],
        "required_data": ["metric:stock_price", "metric:benchmark_return"],
        "decision_scope": "source_method_binding_scope",
        "entry_condition": "T+1_or_more_conservative_shadow_entry",
        "exit_condition": "fixed_horizon_shadow_exit",
        "risk_controls": [
            "no_production_order",
            "no_position_sizing",
            "after_cost_alpha_required",
            "consecutive_after_cost_decay_blocks_validation",
            "turnover_cost_decay_blocks_validation",
            "drawdown_threshold_pre_registered",
        ],
        "expected_horizon_days": 120,
        "steps": [{"step": 1, "tool": "analysis.reasoning_step"}],
        "output_signal": {"name": "source_method_binding_score"},
    }
    labels = [
        {
            "outcome_id": f"OUT-SOURCE-METHOD-{index}",
            "method_pattern_id": "METHOD-SECONDARY",
            "exit_datetime": f"2026-02-{10 + index:02d}",
            "directional_after_cost_return": 0.02,
            "benchmark_return": 0.005,
            "directional_hit": True,
            "horizon_days": horizon,
            "market_regime": regime,
            "effective_n_weight": 1.0,
        }
        for index, (horizon, regime) in enumerate(
            (
                (5, "base"),
                (20, "stress"),
                (60, "recovery"),
                (120, "base"),
            )
        )
    ]

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-SOURCE-METHODS",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
    )

    assert runs[0]["paper_trading_status"] == "passed"
    assert runs[0]["blocked_reasons"] == []
    assert runs[0]["metrics"]["effective_n"] == 4.0


def test_report_intelligence_paper_trading_split_sorts_exit_datetime():
    metrics = _paper_trading_chronological_split_metrics(
        [
            {
                "exit_datetime": "2026-01-14",
                "after_cost": 0.03,
                "hit": 1.0,
                "weight": 1.0,
            },
            {
                "exit_datetime": "2026-01-10",
                "after_cost": 0.01,
                "hit": 1.0,
                "weight": 1.0,
            },
            {
                "exit_datetime": "2026-01-12",
                "after_cost": -0.01,
                "hit": 0.0,
                "weight": 2.0,
            },
        ]
    )

    assert metrics["start_exit_datetime"] == "2026-01-10"
    assert metrics["end_exit_datetime"] == "2026-01-14"
    assert metrics["effective_n"] == 4.0
    assert metrics["cost_adjusted_alpha"] == 0.005


def test_paper_trading_oos_split_extends_to_min_effective_weight():
    items = [
        {
            "exit_datetime": "2026-01-10",
            "after_cost": 0.01,
            "hit": 1.0,
            "weight": 1.0,
        },
        {
            "exit_datetime": "2026-01-12",
            "after_cost": 0.02,
            "hit": 1.0,
            "weight": 1.0,
        },
        {
            "exit_datetime": "2026-01-14",
            "after_cost": 0.03,
            "hit": 1.0,
            "weight": 0.4,
        },
        {
            "exit_datetime": "2026-01-15",
            "after_cost": 0.04,
            "hit": 1.0,
            "weight": 0.5,
        },
    ]

    backtest_items, oos_items = _paper_trading_train_oos_split_items(items)

    assert [row["exit_datetime"] for row in backtest_items] == ["2026-01-10"]
    assert [row["exit_datetime"] for row in oos_items] == [
        "2026-01-12",
        "2026-01-14",
        "2026-01-15",
    ]
    assert sum(row["weight"] for row in oos_items) == 1.9


def test_paper_trading_exit_date_streak_deduplicates_same_day_labels():
    items = [
        {
            "exit_datetime": "2026-01-10",
            "after_cost": -0.02,
            "weight": 1.0,
        },
        {
            "exit_datetime": "2026-01-10",
            "after_cost": -0.01,
            "weight": 1.0,
        },
        {
            "exit_datetime": "2026-01-11",
            "after_cost": 0.01,
            "weight": 1.0,
        },
        {
            "exit_datetime": "2026-01-12",
            "after_cost": -0.03,
            "weight": 1.0,
        },
    ]

    assert _max_non_positive_after_cost_exit_date_streak(items) == 1
    assert _tail_non_positive_after_cost_exit_date_streak(items) == 1


def test_report_intelligence_recipe_paper_trading_flags_alpha_decay_fail():
    recipe = {
        "analysis_recipe_id": "RECIPE-DECAY-FAIL",
        "method_pattern_id": "METHOD-DECAY-FAIL",
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "required_data": ["stock_price", "benchmark_return"],
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "decay_sensitive_score"},
    }
    labels = []
    for day, value, horizon, regime in (
        (10, 0.04, 5, "base"),
        (11, 0.03, 20, "stress"),
        (12, -0.01, 60, "recovery"),
        (13, -0.02, 120, "base"),
    ):
        labels.append(
            {
                "analysis_recipe_id": "RECIPE-DECAY-FAIL",
                "method_pattern_id": "METHOD-DECAY-FAIL",
                "exit_datetime": f"2026-01-{day:02d}",
                "directional_after_cost_return": value,
                "benchmark_return": 0.001,
                "directional_hit": True,
                "horizon_days": horizon,
                "market_regime": regime,
                "effective_n_weight": 1.0,
            }
        )

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-DECAY",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-DECAY",
        recipe_paper_trading_runs=runs,
    )
    observations = build_confidence_impact_observations(
        run_id="RIR-TEST-DECAY",
        recipe_paper_trading_runs=runs,
    )
    monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-DECAY",
        confidence_observation_rows=observations,
        recipe_paper_trading_summary=summary,
    )

    assert runs[0]["paper_trading_status"] == "blocked"
    assert runs[0]["metrics"]["cost_adjusted_alpha"] > 0
    assert runs[0]["metrics"]["non_positive_after_cost_window_streak"] == 2
    assert "consecutive_non_positive_after_cost_windows" in runs[0]["blocked_reasons"]
    assert observations[0]["drift_status"] == "alpha_decay_fail"
    assert observations[0]["recommended_action"] == "freeze_recipe"
    assert observations[0]["confidence_delta"] == 0.0
    assert monitor["alpha_decay_fail_count"] == 1
    assert monitor["alpha_decay_recipe_ids"] == ["RECIPE-DECAY-FAIL"]
    assert monitor["reduce_confidence_impact_recipe_ids"] == []
    assert monitor["freeze_recipe_ids"] == ["RECIPE-DECAY-FAIL"]


def test_report_intelligence_recipe_paper_trading_keeps_recovered_long_window_alpha():
    recipe = {
        "analysis_recipe_id": "RECIPE-RECOVERED-ALPHA",
        "method_pattern_id": "METHOD-RECOVERED-ALPHA",
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "required_data": ["stock_price", "benchmark_return"],
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "recovered_alpha_score"},
    }
    labels = []
    for day, value, horizon, regime in (
        (10, 0.04, 5, "base"),
        (11, -0.01, 20, "stress"),
        (12, -0.02, 60, "recovery"),
        (13, 0.04, 120, "base"),
    ):
        labels.append(
            {
                "analysis_recipe_id": "RECIPE-RECOVERED-ALPHA",
                "method_pattern_id": "METHOD-RECOVERED-ALPHA",
                "exit_datetime": f"2026-01-{day:02d}",
                "directional_after_cost_return": value,
                "benchmark_return": 0.001,
                "directional_hit": True,
                "horizon_days": horizon,
                "market_regime": regime,
                "effective_n_weight": 1.0,
            }
        )

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-RECOVERED-ALPHA",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )

    assert runs[0]["paper_trading_status"] == "passed"
    assert runs[0]["metrics"]["max_non_positive_after_cost_window_streak"] == 2
    assert runs[0]["metrics"]["non_positive_after_cost_window_streak"] == 0
    assert "consecutive_non_positive_after_cost_windows" not in runs[0]["blocked_reasons"]


def test_report_intelligence_recipe_paper_trading_flags_regime_fragile_alpha():
    recipe = {
        "analysis_recipe_id": "RECIPE-REGIME-FRAGILE",
        "method_pattern_id": "METHOD-REGIME-FRAGILE",
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "required_data": ["stock_price", "benchmark_return"],
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "regime_fragile_score"},
    }
    labels = []
    for day, value in (
        (10, 0.03),
        (11, 0.02),
        (12, 0.025),
        (13, 0.018),
    ):
        labels.append(
            {
                "analysis_recipe_id": "RECIPE-REGIME-FRAGILE",
                "method_pattern_id": "METHOD-REGIME-FRAGILE",
                "exit_datetime": f"2026-01-{day:02d}",
                "directional_after_cost_return": value,
                "benchmark_return": 0.001,
                "directional_hit": True,
                "horizon_days": 20,
                "market_regime": "single_regime",
                "effective_n_weight": 1.0,
            }
        )

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-REGIME-FRAGILE",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-REGIME-FRAGILE",
        recipe_paper_trading_runs=runs,
    )
    observations = build_confidence_impact_observations(
        run_id="RIR-TEST-REGIME-FRAGILE",
        recipe_paper_trading_runs=runs,
    )
    monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-REGIME-FRAGILE",
        confidence_observation_rows=observations,
        recipe_paper_trading_summary=summary,
    )

    assert runs[0]["paper_trading_status"] == "blocked"
    assert runs[0]["metrics"]["cost_adjusted_alpha"] > 0
    assert runs[0]["metrics"]["max_horizon_contribution_share"] == 1.0
    assert runs[0]["metrics"]["observed_horizon_count"] == 1
    assert runs[0]["metrics"]["max_regime_contribution_share"] == 1.0
    assert runs[0]["metrics"]["observed_regime_count"] == 1
    assert {
        "single_window_concentration",
        "single_regime_concentration",
        "recipe_instability_gap",
    } <= set(runs[0]["blocked_reasons"])
    assert summary["recipe_instability_gap_count"] == 1
    assert observations[0]["drift_status"] == "regime_fragile_alpha"
    assert observations[0]["recommended_action"] == "send_to_manual_review"
    assert observations[0]["confidence_delta"] == 0.0
    assert monitor["regime_fragile_alpha_count"] == 1
    assert monitor["regime_fragile_recipe_ids"] == ["RECIPE-REGIME-FRAGILE"]
    assert monitor["manual_review_recipe_ids"] == ["RECIPE-REGIME-FRAGILE"]

    missing_horizon_labels = []
    for label in labels:
        row = dict(label)
        row.pop("horizon_days")
        missing_horizon_labels.append(row)
    missing_horizon_runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-MISSING-HORIZON",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=missing_horizon_labels,
        method_performance_profile_rows=[],
    )
    missing_horizon_observations = build_confidence_impact_observations(
        run_id="RIR-TEST-MISSING-HORIZON",
        recipe_paper_trading_runs=missing_horizon_runs,
    )
    assert "window_horizon_missing" in missing_horizon_runs[0]["blocked_reasons"]
    assert "recipe_instability_gap" in missing_horizon_runs[0]["blocked_reasons"]
    assert missing_horizon_observations[0]["drift_status"] == "regime_fragile_alpha"


def test_report_intelligence_recipe_paper_trading_flags_cost_decay_fail():
    recipe = {
        "analysis_recipe_id": "RECIPE-COST-DECAY",
        "method_pattern_id": "METHOD-COST-DECAY",
        "version": "0.1.0",
        "runtime_mode": "shadow_only",
        "required_tools": ["market.price_proxy"],
        "required_data": ["stock_price", "benchmark_return"],
        "steps": [{"step": 1, "tool": "market.price_proxy"}],
        "output_signal": {"name": "turnover_sensitive_score"},
    }
    labels = []
    for day, horizon, regime in (
        (10, 20, "base"),
        (11, 20, "stress"),
        (12, 30, "recovery"),
        (13, 30, "base"),
    ):
        labels.append(
            {
                "analysis_recipe_id": "RECIPE-COST-DECAY",
                "method_pattern_id": "METHOD-COST-DECAY",
                "exit_datetime": f"2026-01-{day:02d}",
                "relative_alpha": 0.001,
                "direction_evaluated": "positive",
                "directional_after_cost_return": -0.001,
                "benchmark_return": 0.001,
                "directional_hit": False,
                "horizon_days": horizon,
                "market_regime": regime,
                "effective_n_weight": 1.0,
            }
        )

    runs = build_recipe_paper_trading_runs(
        run_id="RIR-TEST-COST-DECAY",
        analysis_recipe_rows=[recipe],
        outcome_label_rows=labels,
        method_performance_profile_rows=[],
    )
    summary = build_recipe_paper_trading_summary(
        run_id="RIR-TEST-COST-DECAY",
        recipe_paper_trading_runs=runs,
    )
    observations = build_confidence_impact_observations(
        run_id="RIR-TEST-COST-DECAY",
        recipe_paper_trading_runs=runs,
    )
    monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-COST-DECAY",
        confidence_observation_rows=observations,
        recipe_paper_trading_summary=summary,
    )

    assert runs[0]["paper_trading_status"] == "blocked"
    assert runs[0]["metrics"]["pre_cost_alpha"] == 0.001
    assert runs[0]["metrics"]["cost_adjusted_alpha"] == -0.001
    assert runs[0]["metrics"]["estimated_cost_drag"] == 0.002
    assert runs[0]["metrics"]["turnover"] > 6.0
    assert "cost_decay_fail" in runs[0]["blocked_reasons"]
    assert observations[0]["drift_status"] == "cost_decay_fail"
    assert observations[0]["recommended_action"] == "freeze_recipe"
    assert observations[0]["pre_cost_realized_alpha"] == 0.001
    assert observations[0]["estimated_cost_drag"] == 0.002
    assert monitor["cost_decay_fail_count"] == 1
    assert monitor["cost_decay_recipe_ids"] == ["RECIPE-COST-DECAY"]
    assert monitor["freeze_recipe_ids"] == ["RECIPE-COST-DECAY"]


def test_report_intelligence_confidence_monitor_tracks_aggregate_calibration_drift():
    observations = [
        {
            "recipe_id": "RECIPE-HIGH-BAD",
            "agent_id": "report_intelligence.shadow",
            "confidence_delta": 0.03,
            "paper_trading_status": "passed",
            "drift_status": "stable_shadow",
            "recommended_action": "keep_shadow",
            "after_cost_realized_alpha": -0.01,
            "hit_rate_recent": 0.45,
            "hit_rate_baseline": 0.50,
            "calibration_error": 0.30,
            "regime": "policy_shift",
            "regime_status": "new_regime",
            "blocker_reasons": [],
        },
        {
            "recipe_id": "RECIPE-LOW-GOOD",
            "agent_id": "report_intelligence.shadow",
            "confidence_delta": 0.01,
            "paper_trading_status": "passed",
            "drift_status": "stable_shadow",
            "recommended_action": "keep_shadow",
            "after_cost_realized_alpha": 0.02,
            "hit_rate_recent": 0.60,
            "hit_rate_baseline": 0.50,
            "calibration_error": 0.05,
            "regime": "base",
            "blocker_reasons": [],
        },
    ]

    monitor = build_confidence_impact_monitor(
        run_id="RIR-TEST-AGG-CALIBRATION",
        confidence_observation_rows=observations,
        recipe_paper_trading_summary={
            "recipe_count": 2,
            "validation_pass_count": 2,
            "blocked_count": 0,
        },
    )

    rule_counts = monitor["calibration_drift_rule_counts"]
    assert rule_counts["positive_confidence_hit_nonimprovement"] == 1
    assert rule_counts["high_confidence_underperformance"] == 1
    assert rule_counts["new_regime_miscalibration"] == 1
    assert rule_counts["negative_confidence_alpha_correlation"] == 1
    assert monitor["aggregate_calibration_drift_count"] == 4
    assert monitor["confidence_alpha_correlation"] < 0
    assert monitor["confidence_alpha_correlation_status"] == "negative"
    assert monitor["confidence_delta_bucket_outcomes"]["high_positive"][
        "mean_realized_alpha"
    ] == -0.01
    assert monitor["new_regime_miscalibration_recipe_ids"] == ["RECIPE-HIGH-BAD"]
    assert monitor["aggregate_calibration_drift_recipe_ids"] == [
        "RECIPE-HIGH-BAD",
        "RECIPE-LOW-GOOD",
    ]
    assert monitor["calibration_drift_recipe_ids"] == [
        "RECIPE-HIGH-BAD",
        "RECIPE-LOW-GOOD",
    ]
    assert monitor["manual_review_recipe_ids"] == [
        "RECIPE-HIGH-BAD",
        "RECIPE-LOW-GOOD",
    ]
    assert monitor["production_decision_impact_allowed"] is False


def test_report_intelligence_evolution_gate_blocks_aggregate_calibration_drift():
    forecast_rows, outcome_rows = _full_evolution_outcome_fixture()
    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "aggregate_calibration_drift_count": 0,
        "calibration_drift_rule_counts": {},
        "blocker_counts": {},
    }
    drift_monitor = {
        **clean_monitor,
        "aggregate_calibration_drift_count": 1,
        "calibration_drift_rule_counts": {
            "negative_confidence_alpha_correlation": 1
        },
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    previous_vintage_1 = "sha256:" + "1" * 64
    previous_vintage_2 = "sha256:" + "2" * 64

    current_drift_gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-CURRENT-AGG-CALIBRATION-DRIFT",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=drift_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {**clean_monitor, "data_vintage_hash": previous_vintage_2},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    monitor_check = next(
        row
        for row in current_drift_gate["checks"]
        if row["check_id"] == "RI-EVOL-03"
    )
    assert current_drift_gate["gate_status"] == "blocked"
    assert "confidence_impact_monitor_current_blocked" in monitor_check["blockers"]
    assert monitor_check["evidence"]["aggregate_calibration_drift_count"] == 1
    assert monitor_check["evidence"]["calibration_drift_rule_counts"] == {
        "negative_confidence_alpha_correlation": 1
    }

    history_drift_gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-HISTORY-AGG-CALIBRATION-DRIFT",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=clean_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {
                **drift_monitor,
                "accepted": True,
                "data_vintage_hash": previous_vintage_2,
            },
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    history_monitor_check = next(
        row
        for row in history_drift_gate["checks"]
        if row["check_id"] == "RI-EVOL-03"
    )
    assert history_drift_gate["gate_status"] == "blocked"
    assert {
        "confidence_impact_monitor_history_below_threshold",
    } <= set(history_monitor_check["blockers"])
    assert history_monitor_check["evidence"]["trailing_monitor_pass_count"] == 1


def test_report_intelligence_evolution_gate_blocks_until_objective_thresholds_pass():
    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION",
        forecast_rows=[{"forecast_claim_id": "FC-1"}],
        outcome_label_rows=[],
        recipe_paper_trading_summary={
            "paper_trading_run_count": 5,
            "validation_pass_count": 0,
            "mean_cost_adjusted_alpha": None,
            "after_cost_paper_trading_summary": {
                "status": "insufficient_validated_runs",
                "validated_recipe_count": 0,
                "mean_after_cost_alpha": None,
                "median_after_cost_alpha": None,
                "min_after_cost_alpha": None,
                "max_after_cost_alpha": None,
                "positive_after_cost_recipe_count": 0,
                "policy": "test summary present but insufficient",
            },
        },
        confidence_impact_monitor={
            "observation_count": 5,
            "blocked_recipe_count": 5,
            "unvalidated_confidence_impact_count": 0,
            "alpha_decay_fail_count": 0,
            "calibration_drift_count": 0,
            "blocker_counts": {"no_direct_recipe_outcome_binding": 5},
        },
        markdown_coverage_summary={
            "coverage_gate_status": "blocked",
            "coverage_gate_blockers": ["selected_report_count_below_p9_target"],
            "coverage_targets": {"selected_report_count_min": 300},
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {"horizon": 3}},
    )

    assert gate["gate_status"] == "blocked"
    assert gate["production_prompt_change_allowed"] is False
    assert gate["private_text_included"] is False
    assert {
        "unique_outcome_claim_count_below_threshold",
        "stock_proxy_claim_count_below_threshold",
        "industry_proxy_claim_count_below_threshold",
        "paper_trading_validated_recipe_count_below_threshold",
        "audit_refresh_history_below_threshold",
        "gap_distribution_history_below_threshold",
        "selected_report_count_below_p9_target",
    } <= set(gate["blockers"])
    assert "after_cost_paper_trading_summary_missing" not in gate["blockers"]
    assert "confidence_impact_monitor_current_blocked" not in gate["blockers"]
    assert gate["requirement_shortfalls"]["unique_outcome_claim_count"] == {
        "blocker": "unique_outcome_claim_count_below_threshold",
        "current": 0,
        "next_action": "produce_more_non_llm_pit_outcome_labels",
        "remaining": 100,
        "target": 100,
    }
    assert gate["requirement_shortfalls"]["paper_trading_validated_recipe_count"][
        "remaining"
    ] == 20
    assert gate["requirement_shortfalls"]["monitor_current_global_blocker_count"][
        "remaining"
    ] == 0
    audit_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-04"
    )
    assert audit_check["evidence"]["audit_history_dependency"] == {
        "blocking_components": [],
        "current_failure_counts": {
            "pit": 0,
            "provenance": 0,
            "schema": 0,
            "statistical": 0,
        },
        "current_failure_refs": {
            "pit": [],
            "provenance": [],
            "schema": [],
            "statistical": [],
        },
        "history_counts_only_passing_current_audits": True,
        "min_consecutive_audit_refreshes": 3,
        "next_action": "run_distinct_derived_refreshes_after_current_audits_pass",
        "refresh_without_current_audit_pass_can_satisfy_history": False,
        "status": "history_below_threshold",
        "trailing_audit_pass_count": 1,
    }
    assert gate["requirement_shortfalls"]["markdown_coverage"] == {}
    gate_dump = json.dumps(gate, ensure_ascii=False)
    assert "claim_text" not in gate_dump
    assert "source_span_ids" not in gate_dump


def test_report_intelligence_evolution_gate_explains_schema_blocked_audit_history():
    forecast_rows, outcome_rows = _full_evolution_outcome_fixture()
    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "blocker_counts": {},
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    previous_vintage_1 = "sha256:" + "1" * 64
    previous_vintage_2 = "sha256:" + "2" * 64

    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-SCHEMA-BLOCKED-AUDIT-HISTORY",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=clean_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": False},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {**clean_monitor, "data_vintage_hash": previous_vintage_2},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    audit_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-04"
    )
    assert {
        "current_schema_or_audit_gate_blocked",
        "audit_refresh_history_below_threshold",
    } <= set(audit_check["blockers"])
    assert audit_check["evidence"]["audit_history_dependency"] == {
        "blocking_components": ["schema"],
        "current_failure_counts": {
            "pit": 0,
            "provenance": 0,
            "schema": 1,
            "statistical": 0,
        },
        "current_failure_refs": {
            "pit": [],
            "provenance": [],
            "schema": [],
            "statistical": [],
        },
        "history_counts_only_passing_current_audits": True,
        "min_consecutive_audit_refreshes": 3,
        "next_action": (
            "clear_current_schema_pit_provenance_statistical_blockers_before_"
            "counting_audit_refresh_history"
        ),
        "refresh_without_current_audit_pass_can_satisfy_history": False,
        "status": "current_gate_blocked",
        "trailing_audit_pass_count": 0,
    }
    assert (
        gate["requirement_shortfalls"]["audit_distinct_vintage_count"]["next_action"]
        == audit_check["evidence"]["audit_history_dependency"]["next_action"]
    )


def test_report_intelligence_evolution_gate_ignores_self_schema_rule_for_current_audit():
    forecast_rows, outcome_rows = _full_evolution_outcome_fixture()
    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "blocker_counts": {},
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    previous_vintage_1 = "sha256:" + "1" * 64
    previous_vintage_2 = "sha256:" + "2" * 64

    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-SELF-SCHEMA-IGNORED",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=clean_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={
            "accepted": False,
            "failure_count": 5,
            "records": [
                {
                    "accepted": False,
                    "schema_path": (
                        "schemas/"
                        "report_intelligence_evolution_readiness_gate_rules"
                    ),
                    "failures": [
                        "self-referential evolution gate contract is stale",
                    ],
                }
            ],
        },
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {**clean_monitor, "data_vintage_hash": previous_vintage_2},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    audit_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-04"
    )
    assert audit_check["passed"] is True
    assert "current_schema_or_audit_gate_blocked" not in audit_check["blockers"]
    assert audit_check["evidence"]["schema_accepted"] is True
    assert audit_check["evidence"]["audit_history_dependency"] == {
        "blocking_components": [],
        "current_failure_counts": {
            "pit": 0,
            "provenance": 0,
            "schema": 0,
            "statistical": 0,
        },
        "current_failure_refs": {
            "pit": [],
            "provenance": [],
            "schema": [],
            "statistical": [],
        },
        "history_counts_only_passing_current_audits": True,
        "min_consecutive_audit_refreshes": 3,
        "next_action": "none",
        "refresh_without_current_audit_pass_can_satisfy_history": False,
        "status": "ready",
        "trailing_audit_pass_count": 3,
    }


def test_report_intelligence_evolution_gate_filters_self_schema_from_failure_refs():
    forecast_rows, outcome_rows = _full_evolution_outcome_fixture()

    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-SELF-SCHEMA-FILTERED-REFS",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor={
            "observation_count": 20,
            "blocked_recipe_count": 0,
            "unvalidated_confidence_impact_count": 0,
            "alpha_decay_fail_count": 0,
            "calibration_drift_count": 0,
            "blocker_counts": {},
        },
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={
            "accepted": False,
            "failure_count": 8,
            "records": [
                {
                    "accepted": False,
                    "schema_path": (
                        "schemas/"
                        "report_intelligence_evolution_readiness_gate_rules"
                    ),
                    "failures": [
                        "self-referential evolution gate contract is stale",
                    ],
                },
                {
                    "accepted": False,
                    "schema_path": (
                        "schemas/report_intelligence_gold_review_gate_rules"
                    ),
                    "failures": [
                        "direction accuracy below threshold",
                        "variable mapping accuracy below threshold",
                        "unsupported field false grounding above threshold",
                    ],
                },
            ],
        },
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
    )

    audit_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-04"
    )
    dependency = audit_check["evidence"]["audit_history_dependency"]
    assert audit_check["evidence"]["schema_accepted"] is False
    assert dependency["blocking_components"] == ["schema"]
    assert dependency["current_failure_counts"]["schema"] == 3
    assert dependency["current_failure_refs"]["schema"] == [
        "schemas/report_intelligence_gold_review_gate_rules"
    ]


def test_report_intelligence_evolution_gate_uses_unlabelable_gap_basis():
    forecast_rows, outcome_rows = _full_evolution_outcome_fixture()
    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "blocker_counts": {},
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    previous_vintage_1 = "sha256:" + "1" * 64
    previous_vintage_2 = "sha256:" + "2" * 64

    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-UNLABELABLE-GAPS",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=clean_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={
            "mapping_gap_counts": {"horizon": 100, "target": 1},
            "unlabelable_mapping_gap_counts": {"target": 1, "direction": 1},
        },
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {**clean_monitor, "data_vintage_hash": previous_vintage_2},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    gap_check = next(row for row in gate["checks"] if row["check_id"] == "RI-EVOL-06")
    assert gap_check["passed"] is True
    assert gap_check["evidence"]["gap_count_basis"] == "unlabelable_mapping_gap_counts"
    assert gap_check["evidence"]["current_mapping_gap_counts"] == {
        "direction": 1,
        "target": 1,
    }
    assert gap_check["evidence"]["current_all_mapping_gap_counts"] == {
        "horizon": 100,
        "target": 1,
    }


def test_report_intelligence_evolution_gate_requires_gold_precision_and_conflict_review():
    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-GOLD-GATE",
        forecast_rows=[{"forecast_claim_id": "FC-1"}],
        outcome_label_rows=[],
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor={
            "observation_count": 20,
            "blocked_recipe_count": 0,
            "unvalidated_confidence_impact_count": 0,
            "alpha_decay_fail_count": 0,
            "calibration_drift_count": 0,
            "blocker_counts": {},
        },
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
                "markdown_quality_pass_count_min": 300,
                "llm_extraction_processed_count_min": 100,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(
            metrics={
                "claim_precision": 0.84,
                "source_span_support_precision": 0.92,
                "direction_accuracy": 0.89,
                "variable_mapping_accuracy": 0.82,
                "unsupported_field_false_grounding_rate": 0.02,
            },
        ),
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {
                "data_gap_counts": {"stock_target_conflict": 2},
            },
        },
    )

    gold_check = next(row for row in gate["checks"] if row["check_id"] == "RI-EVOL-05")
    assert gold_check["passed"] is False
    assert {
        "claim_precision_below_threshold",
        "target_accuracy_missing",
        "horizon_accuracy_missing",
        "stock_target_conflict_unexplained",
    } <= set(gold_check["blockers"])
    assert gold_check["evidence"]["metrics"]["claim_precision"] == 0.84
    assert gold_check["evidence"]["stock_target_conflict_count"] == 2
    assert gold_check["evidence"]["stock_target_conflict_explained"] is False


def test_report_intelligence_evolution_gate_treats_zero_stock_conflicts_as_explained():
    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-GOLD-NO-STOCK-CONFLICT",
        forecast_rows=[{"forecast_claim_id": "FC-1"}],
        outcome_label_rows=[],
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor={
            "observation_count": 20,
            "blocked_recipe_count": 0,
            "unvalidated_confidence_impact_count": 0,
            "alpha_decay_fail_count": 0,
            "calibration_drift_count": 0,
            "blocker_counts": {},
        },
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
                "markdown_quality_pass_count_min": 300,
                "llm_extraction_processed_count_min": 100,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {
                "data_gap_counts": {},
            },
        },
    )

    gold_check = next(row for row in gate["checks"] if row["check_id"] == "RI-EVOL-05")
    assert "stock_target_conflict_unexplained" not in gold_check["blockers"]
    assert gold_check["evidence"]["stock_target_conflict_count"] == 0
    assert gold_check["evidence"]["stock_target_conflict_reviewed_count"] == 0
    assert gold_check["evidence"]["stock_target_conflict_explained"] is True


def test_report_intelligence_evolution_gate_blocks_markdown_spot_check_queue():
    outcome_rows = []
    forecast_rows = []
    for index in range(100):
        if index < 30:
            label_type = "stock_price_proxy"
            prefix = "STOCK"
        elif index < 60:
            label_type = "industry_etf_proxy"
            prefix = "IND"
        else:
            label_type = "standard_outcome"
            prefix = "STD"
        claim_id = f"FC-{prefix}-{index:03d}"
        forecast_rows.append({"forecast_claim_id": claim_id})
        outcome_rows.append(
            {
                "forecast_claim_id": claim_id,
                "label_type": label_type,
                "horizon_days": 20,
                "effective_n_weight": 1.0,
            }
        )
    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "blocker_counts": {},
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    previous_vintage_1 = "sha256:" + "1" * 64
    previous_vintage_2 = "sha256:" + "2" * 64

    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION-MARKDOWN-SPOT-CHECK",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=clean_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
                "markdown_quality_pass_count_min": 300,
                "llm_extraction_processed_count_min": 100,
            },
            "markdown_quality_review_queue_count": 2,
            "markdown_false_positive_review_queue_count": 1,
            "markdown_quality_spot_check_required": True,
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {**clean_monitor, "data_vintage_hash": previous_vintage_2},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    markdown_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-07"
    )
    assert gate["gate_status"] == "blocked"
    assert markdown_check["passed"] is False
    assert {
        "markdown_quality_review_queue_pending",
        "markdown_false_positive_review_queue_pending",
        "markdown_quality_spot_check_required",
    } <= set(markdown_check["blockers"])
    assert markdown_check["evidence"]["markdown_quality_review_queue_count"] == 2
    assert (
        markdown_check["evidence"]["markdown_false_positive_review_queue_count"]
        == 1
    )


def test_report_intelligence_evolution_gate_passes_with_full_objective_evidence():
    outcome_rows = []
    forecast_rows = []
    for index in range(100):
        if index < 30:
            label_type = "stock_price_proxy"
            prefix = "STOCK"
        elif index < 60:
            label_type = "industry_etf_proxy"
            prefix = "IND"
        else:
            label_type = "standard_outcome"
            prefix = "STD"
        claim_id = f"FC-{prefix}-{index:03d}"
        forecast_rows.append({"forecast_claim_id": claim_id})
        outcome_rows.append(
            {
                "forecast_claim_id": claim_id,
                "label_type": label_type,
                "horizon_days": 20,
                "effective_n_weight": 1.0,
            }
        )

    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "blocker_counts": {},
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    previous_vintage_1 = "sha256:" + "1" * 64
    previous_vintage_2 = "sha256:" + "2" * 64
    gate = build_report_intelligence_evolution_readiness_gate(
        run_id="RIR-TEST-EVOLUTION",
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
        recipe_paper_trading_summary=_passing_recipe_paper_trading_summary(),
        confidence_impact_monitor=clean_monitor,
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        pit_leakage_audit={"accepted": True},
        extraction_provenance_audit={"accepted": True},
        statistical_robustness_audit={"accepted": True},
        schema_validation_report={"accepted": True},
        gold_review_summary=_passing_forecast_gold_review_summary(),
        outcome_labeling_readiness={"mapping_gap_counts": {}},
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": previous_vintage_1},
            {**clean_monitor, "data_vintage_hash": previous_vintage_2},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": previous_vintage_1},
            {**accepted_audit, "data_vintage_hash": previous_vintage_2},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": previous_vintage_1},
            {"stable": True, "data_vintage_hash": previous_vintage_2},
        ],
    )

    assert gate["gate_status"] == "passed"
    assert str(gate["data_vintage_hash"]).startswith("sha256:")
    assert gate["blocker_count"] == 0
    assert gate["promotion_state"] == "ready_for_shadow_evolution_candidate"
    assert all(row["passed"] is True for row in gate["checks"])
    outcome_check = next(row for row in gate["checks"] if row["check_id"] == "RI-EVOL-01")
    assert outcome_check["evidence"]["unique_outcome_claim_count"] == 100
    assert outcome_check["evidence"]["stock_proxy_unique_claim_count"] == 30
    assert outcome_check["evidence"]["industry_proxy_unique_claim_count"] == 30


def test_report_intelligence_evolution_gate_requires_distinct_data_vintages():
    outcome_rows = []
    forecast_rows = []
    for index in range(100):
        if index < 30:
            label_type = "stock_price_proxy"
            prefix = "STOCK"
        elif index < 60:
            label_type = "industry_etf_proxy"
            prefix = "IND"
        else:
            label_type = "standard_outcome"
            prefix = "STD"
        claim_id = f"FC-{prefix}-{index:03d}"
        forecast_rows.append({"forecast_claim_id": claim_id})
        outcome_rows.append(
            {
                "forecast_claim_id": claim_id,
                "label_type": label_type,
                "horizon_days": 20,
                "effective_n_weight": 1.0,
            }
        )
    clean_monitor = {
        "observation_count": 20,
        "blocked_recipe_count": 0,
        "unvalidated_confidence_impact_count": 0,
        "alpha_decay_fail_count": 0,
        "calibration_drift_count": 0,
        "blocker_counts": {},
    }
    accepted_audit = {
        "schema_accepted": True,
        "pit_accepted": True,
        "provenance_accepted": True,
        "statistical_accepted": True,
    }
    common_kwargs = {
        "run_id": "RIR-TEST-EVOLUTION-REPEATED-VINTAGE",
        "forecast_rows": forecast_rows,
        "outcome_label_rows": outcome_rows,
        "recipe_paper_trading_summary": _passing_recipe_paper_trading_summary(),
        "confidence_impact_monitor": clean_monitor,
        "markdown_coverage_summary": {
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
            },
        },
        "pit_leakage_audit": {"accepted": True},
        "extraction_provenance_audit": {"accepted": True},
        "statistical_robustness_audit": {"accepted": True},
        "schema_validation_report": {"accepted": True},
        "gold_review_summary": _passing_forecast_gold_review_summary(),
        "outcome_labeling_readiness": {"mapping_gap_counts": {}},
    }
    current_hash = build_report_intelligence_evolution_readiness_gate(
        **common_kwargs
    )["data_vintage_hash"]

    gate = build_report_intelligence_evolution_readiness_gate(
        **common_kwargs,
        monitor_refresh_history_rows=[
            {**clean_monitor, "data_vintage_hash": current_hash},
            {**clean_monitor, "data_vintage_hash": current_hash},
        ],
        audit_refresh_history_rows=[
            {**accepted_audit, "data_vintage_hash": current_hash},
            {**accepted_audit, "data_vintage_hash": current_hash},
        ],
        gap_distribution_history_rows=[
            {"stable": True, "data_vintage_hash": current_hash},
            {"stable": True, "data_vintage_hash": current_hash},
        ],
    )

    assert gate["gate_status"] == "blocked"
    assert {
        "confidence_impact_monitor_history_below_threshold",
        "audit_refresh_history_below_threshold",
        "gap_distribution_history_below_threshold",
    } <= set(gate["blockers"])
    monitor_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-03"
    )
    audit_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-04"
    )
    gap_check = next(
        row for row in gate["checks"] if row["check_id"] == "RI-EVOL-06"
    )
    assert monitor_check["evidence"]["trailing_monitor_distinct_vintage_count"] == 1
    assert audit_check["evidence"]["trailing_audit_distinct_vintage_count"] == 1
    assert audit_check["evidence"]["audit_history_dependency"]["status"] == (
        "history_below_threshold"
    )
    assert audit_check["evidence"]["audit_history_dependency"]["next_action"] == (
        "run_distinct_derived_refreshes_after_current_audits_pass"
    )
    assert (
        gap_check["evidence"]["trailing_gap_distribution_distinct_vintage_count"]
        == 1
    )


def test_report_intelligence_evolution_history_replaces_same_data_vintage():
    data_vintage_hash = "sha256:" + "a" * 64
    history = _append_evolution_history_record(
        [
            {
                "run_id": "RIR-OLD",
                "data_vintage_hash": data_vintage_hash,
                "accepted": True,
            }
        ],
        {
            "run_id": "RIR-NEW",
            "data_vintage_hash": data_vintage_hash,
            "accepted": True,
        },
    )

    assert len(history) == 1
    assert history[0]["run_id"] == "RIR-NEW"


def test_report_intelligence_evolution_history_append_drops_unvintaged_rows():
    previous_hash = "sha256:" + "a" * 64
    current_hash = "sha256:" + "b" * 64

    history = _append_evolution_history_record(
        [
            {"run_id": "RIR-LEGACY", "accepted": True},
            {
                "run_id": "RIR-PREVIOUS",
                "data_vintage_hash": previous_hash,
                "accepted": True,
            },
        ],
        {
            "run_id": "RIR-CURRENT",
            "data_vintage_hash": current_hash,
            "accepted": True,
        },
    )

    assert [row["run_id"] for row in history] == ["RIR-PREVIOUS", "RIR-CURRENT"]
    assert {row["data_vintage_hash"] for row in history} == {
        previous_hash,
        current_hash,
    }


def test_report_intelligence_prompt_mutation_candidates_track_markdown_coverage_gate():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={
            "selected_report_count": 42,
            "markdown_ready_count": 20,
            "markdown_quality_pass_count": 18,
            "llm_extraction_processed_count": 7,
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
                "markdown_quality_pass_count_min": 300,
                "llm_extraction_processed_count_min": 100,
            },
            "coverage_gate_status": "blocked",
            "coverage_gate_blockers": [
                "selected_report_count_below_target",
                "llm_extraction_processed_count_below_target",
            ],
            "markdown_quality_gap_counts": {},
        },
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    coverage = [
        row
        for row in candidates
        if row["candidate_type"] == "markdown_coverage_expansion_rule"
    ]
    assert len(coverage) == 1
    candidate = coverage[0]
    assert candidate["target_component"] == "report_selection_and_mineru_pipeline"
    assert candidate["severity"] == "high"
    assert "p9_markdown_coverage_target_pending" in candidate["blocked_by"]
    evidence = candidate["evidence_refs"][0]
    assert evidence["coverage_gate_status"] == "blocked"
    assert evidence["coverage_targets"]["selected_report_count_min"] == 300
    assert evidence["selected_report_count"] == 42
    assert evidence["llm_extraction_processed_count"] == 7
    assert candidate["production_prompt_change_allowed"] is False
    assert candidate["private_text_included"] is False
    candidate_dump = json.dumps(candidate, ensure_ascii=False)
    assert "claim_text" not in candidate_dump
    assert "source_span_ids" not in candidate_dump


def test_report_intelligence_prompt_mutation_candidates_track_regime_mechanism_gaps():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "regime_gap_counts": {
                "regime_context_unclassified": 2,
                "company_capability_only_no_regime_context": 3,
            },
            "mechanism_gap_counts": {"economic_mechanism_missing": 1},
            "macro_regime_counts": {"us_rate_cut_cycle": 1},
            "source_text_macro_regime_counts": {},
            "as_of_date_macro_regime_counts": {"us_rate_cut_cycle": 1},
            "macro_regime_source_counts": {"as_of_date": 1},
            "industry_cycle_regime_counts": {"price_cycle": 2},
            "regime_gap_forecast_claim_ids": ["FC-R1", "FC-R2", "FC-R3"],
            "mechanism_gap_forecast_claim_ids": ["FC-M1"],
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "markdown_quality_gap_counts": {},
        },
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    regime = [
        row
        for row in candidates
        if row["candidate_type"] == "regime_mechanism_extraction_rule"
    ]
    assert len(regime) == 1
    candidate = regime[0]
    assert candidate["severity"] == "high"
    evidence = candidate["evidence_refs"][0]
    assert evidence["regime_gap_counts"] == {
        "company_capability_only_no_regime_context": 3,
        "regime_context_unclassified": 2,
    }
    assert evidence["mechanism_gap_counts"] == {"economic_mechanism_missing": 1}
    assert evidence["source_text_macro_regime_counts"] == {}
    assert evidence["as_of_date_macro_regime_counts"] == {"us_rate_cut_cycle": 1}
    assert evidence["macro_regime_source_counts"] == {"as_of_date": 1}
    assert evidence["hard_gap_count"] == 3
    assert evidence["regime_gap_forecast_claim_count"] == 3
    assert evidence["mechanism_gap_forecast_claim_count"] == 1
    assert candidate["private_text_included"] is False
    candidate_dump = json.dumps(candidate, ensure_ascii=False)
    assert "claim_text" not in candidate_dump
    assert "source_span_ids" not in candidate_dump


def test_report_intelligence_prompt_mutation_candidates_keep_company_only_regime_gap_diagnostic():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "regime_gap_counts": {"company_capability_only_no_regime_context": 7},
            "mechanism_gap_counts": {},
            "macro_regime_counts": {},
            "source_text_macro_regime_counts": {},
            "as_of_date_macro_regime_counts": {},
            "macro_regime_source_counts": {},
            "industry_cycle_regime_counts": {"prosperity_cycle": 3},
            "regime_gap_forecast_claim_ids": ["FC-COMPANY"],
            "mechanism_gap_forecast_claim_ids": [],
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "markdown_quality_gap_counts": {},
        },
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    candidate = next(
        row
        for row in candidates
        if row["candidate_type"] == "regime_mechanism_extraction_rule"
    )
    assert candidate["severity"] == "medium"
    evidence = candidate["evidence_refs"][0]
    assert evidence["hard_gap_count"] == 0
    assert evidence["source_text_macro_regime_counts"] == {}
    assert evidence["as_of_date_macro_regime_counts"] == {}
    assert evidence["macro_regime_source_counts"] == {}
    assert "company_capability_only_no_regime_context is diagnostic" in evidence[
        "diagnostic_gap_policy"
    ]


def test_report_intelligence_prompt_mutation_candidates_track_markdown_spot_check_gate():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={
            "selected_report_count": 300,
            "markdown_ready_count": 300,
            "markdown_quality_pass_count": 300,
            "llm_extraction_processed_count": 100,
            "coverage_targets": {
                "selected_report_count_min": 300,
                "markdown_ready_count_min": 300,
                "markdown_quality_pass_count_min": 300,
                "llm_extraction_processed_count_min": 100,
            },
            "coverage_gate_status": "passed",
            "coverage_gate_blockers": [],
            "markdown_quality_gap_counts": {
                "markdown_repeated_line_noise": 2,
            },
            "stock_outcome_120d_ready_report_count": 7,
            "stock_outcome_age_bucket_counts": {
                "stock_outcome_120d_calendar_ready": 7,
                "stock_outcome_pending": 3,
            },
            "markdown_quality_review_queue_count": 2,
            "markdown_false_positive_review_queue_count": 2,
            "markdown_quality_spot_check_required": True,
        },
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    coverage = [
        row
        for row in candidates
        if row["candidate_type"] == "markdown_coverage_expansion_rule"
    ]
    assert len(coverage) == 1
    evidence = coverage[0]["evidence_refs"][0]
    assert evidence["coverage_gate_status"] == "passed"
    assert evidence["stock_outcome_120d_ready_report_count"] == 7
    assert evidence["stock_outcome_age_bucket_counts"] == {
        "stock_outcome_120d_calendar_ready": 7,
        "stock_outcome_pending": 3,
    }
    assert evidence["markdown_quality_review_queue_count"] == 2
    assert evidence["markdown_false_positive_review_queue_count"] == 2
    assert evidence["markdown_quality_spot_check_required"] is True
    assert "manual_corpus_quality_review_required" in coverage[0]["blocked_by"]


def test_report_intelligence_prompt_mutation_candidates_track_evolution_thresholds():
    forecast_rows = [{"forecast_claim_id": f"FC-TEST-{index:03d}"} for index in range(10)]
    outcome_rows = [
        {
            "forecast_claim_id": f"FC-STOCK-{index:03d}",
            "label_type": "stock_price_proxy",
        }
        for index in range(5)
    ]
    paper_runs = [
        {
            "analysis_recipe_id": f"RECIPE-THRESHOLD-{index:03d}",
            "paper_trading_status": "passed",
            "blocked_reasons": [],
        }
        for index in range(4)
    ]

    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=paper_runs,
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
    )

    by_type = {row["candidate_type"]: row for row in candidates}
    outcome = by_type["outcome_coverage_expansion_rule"]
    outcome_evidence = outcome["evidence_refs"][0]
    assert outcome["severity"] == "high"
    assert outcome["target_component"] == "report_selection_and_outcome_labeling"
    assert outcome_evidence["unique_outcome_claim_count"] == 5
    assert outcome_evidence["stock_proxy_unique_claim_count"] == 5
    assert outcome_evidence["industry_proxy_unique_claim_count"] == 0
    assert outcome_evidence["threshold_gaps"] == {
        "industry_proxy_unique_claim_count": 30,
        "stock_proxy_unique_claim_count": 25,
        "unique_outcome_claim_count": 95,
    }

    paper = by_type["recipe_paper_trading_expansion_rule"]
    paper_evidence = paper["evidence_refs"][0]
    assert paper["target_component"] == "pre_registered_recipe_paper_trading_queue"
    assert paper_evidence["paper_trading_run_count"] == 4
    assert paper_evidence["validation_pass_count"] == 4
    assert paper_evidence["threshold_gaps"] == {
        "paper_trading_run_count": 16,
        "validation_pass_count": 16,
    }
    dump = json.dumps(candidates, ensure_ascii=False)
    assert "claim_text" not in dump
    assert "source_span_ids" not in dump
    assert all(row["production_prompt_change_allowed"] is False for row in candidates)
    assert all(row["private_text_included"] is False for row in candidates)


def test_report_intelligence_prompt_mutation_candidates_include_binding_gap_details():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[
            {
                "analysis_recipe_id": "RECIPE-BLOCKED",
                "paper_trading_status": "blocked",
                "blocked_reasons": [
                    "no_direct_recipe_outcome_binding",
                    "insufficient_effective_n",
                    "required_tools_not_shadow_implemented",
                ],
            }
        ],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
        recipe_paper_trading_summary={
            "direct_pit_binding_diagnostics": {
                "status": "blocked_no_direct_pit_binding",
                "recipe_count": 1,
                "direct_pit_bound_recipe_count": 0,
                "no_direct_recipe_outcome_binding_count": 1,
                "insufficient_effective_n_count": 1,
                "required_tools_not_shadow_implemented_count": 1,
                "next_actions": [
                    "link recipes to source-grounded method patterns and PIT outcome labels"
                ],
                "binding_gap_details": {
                    "diagnostic_version": "direct_pit_binding_gap_v1",
                    "artifact_counts": {
                        "analysis_recipe_rows": 1,
                        "forecast_claim_rows": 0,
                        "outcome_label_rows": 0,
                        "analytical_footprint_rows": 1,
                        "method_pattern_rows": 1,
                    },
                    "method_source_linkage": {
                        "method_pattern_count": 1,
                        "method_patterns_with_source_footprints": 1,
                        "method_patterns_without_source_footprints": 0,
                    },
                    "forecast_outcome_linkage": {
                        "forecast_claim_count": 0,
                        "outcome_labels_with_forecast_claim_id": 0,
                    },
                    "footprint_source_linkage": {
                        "analytical_footprint_count": 1,
                        "footprints_with_source_or_report": 1,
                    },
                    "recipe_binding_linkage": {
                        "recipe_count": 1,
                        "recipes_with_direct_or_method_outcome_binding": 0,
                    },
                    "missing_artifact_flags": [
                        "forecast_claims_absent",
                        "outcome_labels_absent",
                    ],
                    "next_actions": [
                        "keep forecast claims and analytical footprints available for derived refresh"
                    ],
                },
            }
        },
    )

    by_type = {row["candidate_type"]: row for row in candidates}
    paper_rule = by_type["recipe_paper_trading_rule"]
    assert {
        "direct_pit_outcome_binding_required",
        "effective_sample_expansion_required",
        "requested_shadow_tools_required",
        "private_forecast_claims_required",
        "private_outcome_labels_required",
    } <= set(paper_rule["blocked_by"])
    diagnostic_evidence = [
        row
        for row in paper_rule["evidence_refs"]
        if row["field"] == "direct_pit_binding_diagnostics"
    ][0]
    assert diagnostic_evidence["status"] == "blocked_no_direct_pit_binding"
    assert diagnostic_evidence["binding_gap_details"]["artifact_counts"] == {
        "analysis_recipe_rows": 1,
        "analytical_footprint_rows": 1,
        "forecast_claim_rows": 0,
        "method_pattern_rows": 1,
        "outcome_label_rows": 0,
    }
    assert diagnostic_evidence["binding_gap_details"]["missing_artifact_flags"] == [
        "forecast_claims_absent",
        "outcome_labels_absent",
    ]
    expansion = by_type["recipe_paper_trading_expansion_rule"]
    assert any(
        row["field"] == "direct_pit_binding_diagnostics"
        for row in expansion["evidence_refs"]
    )
    dump = json.dumps(candidates, ensure_ascii=False)
    assert "claim_text" not in dump
    assert "source_span_ids" not in dump
    assert all(row["production_prompt_change_allowed"] is False for row in candidates)
    assert all(row["private_text_included"] is False for row in candidates)


def test_report_intelligence_prompt_mutation_candidates_use_public_outcome_gate_fallback():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
        forecast_rows=[],
        outcome_label_rows=[],
        evolution_readiness_gate={
            "checks": [
                {
                    "check_id": "RI-EVOL-01",
                    "passed": False,
                    "evidence": {
                        "forecast_claim_count": 189,
                        "unique_outcome_claim_count": 49,
                        "stock_proxy_unique_claim_count": 37,
                        "industry_proxy_unique_claim_count": 12,
                    },
                }
            ]
        },
    )

    by_type = {row["candidate_type"]: row for row in candidates}
    outcome = by_type["outcome_coverage_expansion_rule"]
    evidence = outcome["evidence_refs"][0]
    assert evidence["forecast_claim_count"] == 189
    assert evidence["unique_outcome_claim_count"] == 49
    assert evidence["stock_proxy_unique_claim_count"] == 37
    assert evidence["industry_proxy_unique_claim_count"] == 12
    assert evidence["threshold_gaps"] == {
        "industry_proxy_unique_claim_count": 18,
        "stock_proxy_unique_claim_count": 0,
        "unique_outcome_claim_count": 51,
    }


def test_report_intelligence_prompt_mutation_candidates_track_gate_remediation():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
        evolution_readiness_gate={
            "thresholds": {
                "min_consecutive_monitor_refreshes": 3,
                "min_consecutive_audit_refreshes": 3,
                "min_gap_distribution_refreshes": 3,
            },
            "checks": [
                {
                    "check_id": "RI-EVOL-03",
                    "passed": False,
                    "blockers": [
                        "confidence_impact_monitor_current_blocked",
                        "confidence_impact_monitor_history_below_threshold",
                    ],
                    "evidence": {
                        "monitor_observation_count": 5,
                        "blocked_recipe_count": 2,
                        "trailing_monitor_pass_count": 1,
                    },
                },
                {
                    "check_id": "RI-EVOL-04",
                    "passed": False,
                    "blockers": ["audit_refresh_history_below_threshold"],
                    "evidence": {
                        "schema_accepted": True,
                        "pit_accepted": True,
                        "provenance_accepted": True,
                        "statistical_accepted": True,
                        "trailing_audit_pass_count": 1,
                    },
                },
                {
                    "check_id": "RI-EVOL-05",
                    "passed": False,
                    "blockers": ["forecast_gold_set_gate_not_passed"],
                    "evidence": {
                        "gold_set_passed": False,
                        "reviewed_claims": 12,
                        "pending_claims": 8,
                    },
                },
                {
                    "check_id": "RI-EVOL-06",
                    "passed": False,
                    "blockers": ["gap_distribution_history_below_threshold"],
                    "evidence": {
                        "trailing_gap_distribution_stable_count": 1,
                        "current_mapping_gap_counts": {"horizon": 7},
                    },
                },
            ],
        },
    )

    by_type = {row["candidate_type"]: row for row in candidates}
    gold = by_type["forecast_gold_set_review_rule"]
    assert gold["target_component"] == "forecast_gold_set_review_queue"
    assert gold["severity"] == "high"
    assert "manual_forecast_gold_set_review_required" in gold["blocked_by"]
    gold_evidence = gold["evidence_refs"][0]
    assert gold_evidence["reviewed_claims"] == 12
    assert gold_evidence["pending_claims"] == 8
    assert gold_evidence["blockers"] == ["forecast_gold_set_gate_not_passed"]

    stability = by_type["evolution_refresh_stability_rule"]
    assert stability["target_component"] == "derived_refresh_history_gate"
    assert stability["severity"] == "high"
    assert (
        "three_distinct_clean_data_vintages_required"
        in stability["blocked_by"]
    )
    check_ids = {row["check_id"] for row in stability["evidence_refs"]}
    assert check_ids == {"RI-EVOL-03", "RI-EVOL-04", "RI-EVOL-06"}
    assert any(
        row["evidence"].get("trailing_gap_distribution_stable_count") == 1
        for row in stability["evidence_refs"]
    )

    dump = json.dumps(candidates, ensure_ascii=False)
    assert "claim_text" not in dump
    assert "source_span_ids" not in dump
    assert all(row["production_prompt_change_allowed"] is False for row in candidates)
    assert all(row["private_text_included"] is False for row in candidates)


def test_report_intelligence_prompt_mutation_candidates_track_gold_quality_failures():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
        evolution_readiness_gate={
            "checks": [
                {
                    "check_id": "RI-EVOL-05",
                    "passed": False,
                    "blockers": [
                        "forecast_gold_set_gate_not_passed",
                        "gold_reviewed_documents_below_threshold",
                        "direction_accuracy_below_threshold",
                        "variable_mapping_accuracy_below_threshold",
                        "unsupported_field_false_grounding_rate_above_threshold",
                    ],
                    "evidence": {
                        "gold_set_passed": False,
                        "reviewed_claims": 158,
                        "pending_claims": 0,
                        "total_documents": 37,
                        "metrics": {
                            "claim_precision": 0.917722,
                            "direction_accuracy": 0.626582,
                            "horizon_accuracy": 0.936709,
                            "source_span_support_precision": 0.993671,
                            "target_accuracy": 0.85443,
                            "unsupported_field_false_grounding_rate": 0.227848,
                            "variable_mapping_accuracy": 0.189873,
                        },
                        "thresholds": {
                            "claim_precision_min": 0.85,
                            "direction_accuracy_min": 0.85,
                            "horizon_accuracy_min": 0.85,
                            "min_documents": 50,
                            "min_reviewed_claims": 100,
                            "source_span_support_precision_min": 0.9,
                            "target_accuracy_min": 0.85,
                            "unsupported_field_false_grounding_rate_max": 0.05,
                            "variable_mapping_accuracy_min": 0.8,
                        },
                    },
                }
            ]
        },
    )

    by_type = {row["candidate_type"]: row for row in candidates}
    repair = by_type["gold_quality_prompt_repair_rule"]
    assert repair["target_component"] == "forecast_extraction_prompt"
    assert repair["severity"] == "high"
    evidence = repair["evidence_refs"][0]
    assert evidence["field"] == "checks.RI-EVOL-05.evidence"
    assert evidence["metric_failure_count"] == 3
    assert evidence["metric_failures"]["direction_accuracy"] == {
        "blocker": "direction_accuracy_below_threshold",
        "current_rate": 0.626582,
        "operator": ">=",
        "threshold": 0.85,
    }
    assert evidence["metric_failures"]["variable_mapping_accuracy"] == {
        "blocker": "variable_mapping_accuracy_below_threshold",
        "current_rate": 0.189873,
        "operator": ">=",
        "threshold": 0.8,
    }
    assert evidence["metric_failures"][
        "unsupported_field_false_grounding_rate"
    ] == {
        "blocker": "unsupported_field_false_grounding_rate_above_threshold",
        "current_rate": 0.227848,
        "operator": "<=",
        "threshold": 0.05,
    }
    assert evidence["document_coverage_gap"]["minimum_additional_count"] == 13
    assert {
        "gold_quality_prompt_repair_required",
        "offline_gold_set_replay_required",
        "document_coverage_expansion_required",
    } <= set(repair["blocked_by"])
    assert repair["production_prompt_change_allowed"] is False
    assert repair["private_text_included"] is False
    assert "claim_text" not in json.dumps(repair, ensure_ascii=False)


def test_report_intelligence_prompt_mutation_candidates_track_footprint_quality_failures():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
        footprint_review_summary={
            "accepted": False,
            "review_complete": False,
            "quality_gate_passed": False,
            "complete_rows": 34,
            "pending_rows": 1017,
            "total_rows": 1051,
            "precision_recall_report": {
                "footprint_precision": 1.0,
                "inferred_step_tagging_accuracy": 1.0,
                "metric_mapping_accuracy": 0.558824,
                "proprietary_leakage_free_rate": 1.0,
                "span_support_precision": 1.0,
                "unknown_on_ambiguity_rate": 0.941176,
            },
            "quality_gate_thresholds": {
                "footprint_precision": 0.8,
                "inferred_step_tagging_accuracy": 0.8,
                "metric_mapping_accuracy": 0.8,
                "proprietary_leakage_free_rate": 1.0,
                "span_support_precision": 0.9,
                "unknown_on_ambiguity_rate": 0.8,
            },
            "quality_gate_blockers": [
                "metric_mapping_accuracy 0.558824 below threshold 0.80"
            ],
            "error_counts": {
                "metric_mapping_incorrect": 15,
                "unknown_indicator_should_use_alias_repair_candidate": 2,
            },
        },
    )

    by_type = {row["candidate_type"]: row for row in candidates}
    repair = by_type["footprint_quality_prompt_repair_rule"]
    assert repair["target_component"] == "analytical_footprint_extraction_prompt"
    assert repair["severity"] == "high"
    evidence = repair["evidence_refs"][0]
    assert evidence["field"] == "precision_recall_report"
    assert evidence["complete_rows"] == 34
    assert evidence["pending_rows"] == 1017
    assert evidence["metric_failure_count"] == 1
    assert evidence["metric_failures"]["metric_mapping_accuracy"] == {
        "blocker": "metric_mapping_accuracy_below_threshold",
        "current_rate": 0.558824,
        "operator": ">=",
        "threshold": 0.8,
    }
    assert evidence["error_counts"] == {
        "metric_mapping_incorrect": 15,
        "unknown_indicator_should_use_alias_repair_candidate": 2,
    }
    assert {
        "analytical_footprint_quality_prompt_repair_required",
        "manual_analytical_footprint_review_required",
        "footprint_metric_mapping_repair_required",
    } <= set(repair["blocked_by"])
    assert repair["production_prompt_change_allowed"] is False
    assert repair["private_text_included"] is False
    assert "source_span_ids" not in json.dumps(repair, ensure_ascii=False)


def test_report_intelligence_prompt_mutation_candidates_track_industry_mapping_actions():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {
                "data_gap_counts": {"sector_etf_mapping_missing": 3}
            },
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={"drift_status_counts": {}},
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={
            "pit_gap_counts": {"insufficient_window_history": 1},
            "labelability_action_summary": {
                "coverage_gate_status": "actionable_gaps_present",
                "remaining_action_count": 4,
                "sector_etf_mapping_missing_count": 3,
                "pit_unavailable_mapping_count": 1,
                "labelability_rate": 0.25,
                "primary_mapping_coverage_rate": 0.7,
                "next_actions": [
                    "add_primary_etf_mapping_for_unmapped_industry_sectors",
                    "refresh_or_replace_pit_unavailable_etf_mappings",
                ],
            },
        },
    )

    candidates_by_type = {row["candidate_type"]: row for row in candidates}
    industry = candidates_by_type["industry_proxy_mapping_rule"]
    action_ref = next(
        row
        for row in industry["evidence_refs"]
        if row["field"] == "labelability_action_summary"
    )
    assert action_ref["coverage_gate_status"] == "actionable_gaps_present"
    assert action_ref["remaining_action_count"] == 4
    assert action_ref["sector_etf_mapping_missing_count"] == 3
    assert action_ref["pit_unavailable_mapping_count"] == 1
    assert action_ref["next_actions"] == [
        "add_primary_etf_mapping_for_unmapped_industry_sectors",
        "refresh_or_replace_pit_unavailable_etf_mappings",
    ]
    assert {
        "operator_mapping_review_required",
        "add_primary_etf_mapping_for_unmapped_industry_sectors",
        "refresh_or_replace_pit_unavailable_etf_mappings",
    } <= set(industry["blocked_by"])
    assert industry["production_prompt_change_allowed"] is False
    assert industry["private_text_included"] is False


def test_report_intelligence_prompt_mutation_candidates_track_calibration_drift():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[
            {
                "recipe_id": "RECIPE-DECAY",
                "paper_trading_status": "passed",
                "drift_status": "alpha_decay_watch",
                "recommended_action": "reduce_confidence_impact",
                "confidence_delta": 0.0,
            }
        ],
        confidence_impact_monitor={
            "alpha_decay_fail_count": 1,
            "calibration_drift_count": 1,
            "cost_decay_fail_count": 1,
            "regime_fragile_alpha_count": 1,
            "drift_status_counts": {
                "alpha_decay_watch": 1,
                "cost_decay_fail": 1,
                "regime_fragile_alpha": 1,
            },
            "calibration_drift_rule_counts": {
                "negative_confidence_alpha_correlation": 1,
                "high_confidence_underperformance": 1,
            },
            "confidence_alpha_correlation": -0.72,
            "confidence_alpha_correlation_status": "negative",
            "recommended_action_counts": {
                "freeze_recipe": 2,
                "keep_shadow": 3,
                "reduce_confidence_impact": 1,
                "send_to_manual_review": 1,
            },
        },
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    calibration = [
        row for row in candidates if row["candidate_type"] == "calibration_fix_required"
    ]
    assert len(calibration) == 1
    assert calibration[0]["target_component"] == "confidence_calibration_policy"
    drift_counts = calibration[0]["evidence_refs"][0]["drift_status_counts"]
    assert drift_counts["alpha_decay_watch"] == 1
    assert drift_counts["cost_decay_fail"] == 1
    assert drift_counts["regime_fragile_alpha"] == 1
    rule_counts = calibration[0]["evidence_refs"][0]["calibration_drift_rule_counts"]
    assert rule_counts["negative_confidence_alpha_correlation"] == 1
    assert rule_counts["high_confidence_underperformance"] == 1
    assert calibration[0]["evidence_refs"][0]["confidence_alpha_correlation"] == -0.72
    recipe_level_monitor = calibration[0]["evidence_refs"][0][
        "recipe_level_monitor"
    ]
    assert recipe_level_monitor["recipe_level_risk_counts"] == {
        "alpha_decay_fail_count": 1,
        "calibration_drift_count": 1,
        "cost_decay_fail_count": 1,
        "regime_fragile_alpha_count": 1,
    }
    assert recipe_level_monitor["recommended_action_counts"] == {
        "freeze_recipe": 2,
        "keep_shadow": 3,
        "reduce_confidence_impact": 1,
        "send_to_manual_review": 1,
    }
    assert recipe_level_monitor["actionable_recipe_level_action_counts"] == {
        "freeze_recipe": 2,
        "reduce_confidence_impact": 1,
        "send_to_manual_review": 1,
    }
    assert "shadow_regime_and_cost_replay_required" in calibration[0]["blocked_by"]
    assert (
        "recipe_level_monitor_action_review_required"
        in calibration[0]["blocked_by"]
    )
    assert calibration[0]["production_prompt_change_allowed"] is False
    assert calibration[0]["private_text_included"] is False


def test_report_intelligence_prompt_mutation_candidates_track_aggregate_calibration_only():
    candidates = build_prompt_mutation_candidates(
        run_id="RIR-TEST-MUTATION",
        outcome_labeling_readiness={
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {"data_gap_counts": {}},
            "industry_etf_proxy_readiness": {"data_gap_counts": {}},
        },
        tool_gap_rows=[],
        recipe_paper_trading_runs=[],
        confidence_impact_observation_rows=[],
        confidence_impact_monitor={
            "drift_status_counts": {},
            "calibration_drift_rule_counts": {
                "positive_confidence_hit_nonimprovement": 2,
            },
            "confidence_alpha_correlation": None,
            "confidence_alpha_correlation_status": "insufficient_data",
        },
        markdown_coverage_summary={"markdown_quality_gap_counts": {}},
        industry_etf_proxy_pit_availability={"pit_gap_counts": {}},
    )

    calibration = [
        row for row in candidates if row["candidate_type"] == "calibration_fix_required"
    ]
    assert len(calibration) == 1
    evidence = calibration[0]["evidence_refs"][0]
    assert evidence["calibration_drift_rule_counts"] == {
        "positive_confidence_hit_nonimprovement": 2,
    }
    assert calibration[0]["production_prompt_change_allowed"] is False


def test_report_intelligence_can_select_historical_sources_by_date(
    tmp_path: Path,
):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for source_id, publish_date in (
        ("SRC-TSRR-20260102-NEW", "2026-01-02"),
        ("SRC-TSRR-20250203-OLD", "2025-02-03"),
        ("SRC-TSRR-20250304-MID", "2025-03-04"),
    ):
        rows.append(
            {
                "abstract": "historical report",
                "author": "Analyst A",
                "discovered_at": "2026-06-06T00:00:00+00:00",
                "industry": "有色金属",
                "institution": "Broker A",
                "license_status": "pending_review",
                "point_in_time_available": True,
                "publish_date": publish_date,
                "query_key": "有色金属",
                "report_type": "行业研报",
                "source_hash": f"sha256:{source_id.lower()}",
                "source_id": source_id,
                "source_span_id": f"{source_id}:abstract",
                "source_type": "tushare_research_report",
                "title": f"Historical report {source_id}",
                "ts_code": "",
                "url": "https://example.invalid/report.pdf",
            }
        )
    _write_jsonl(source_path, rows)

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            limit=1,
            min_publish_date="2025-01-01",
            max_publish_date="2025-12-31",
            selection_order="oldest",
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    metadata = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    assert result.selected_reports == 1
    assert metadata[0]["source_id"] == "SRC-TSRR-20250203-OLD"


def test_extraction_provenance_allows_governed_industry_etf_proxy_outcomes():
    audit = build_report_intelligence_extraction_provenance_audit(
        run_id="RIR-TEST",
        forecast_rows=[
            {
                "forecast_claim_id": "FC-INDUSTRY-1",
                "claim_provenance": "source_grounded",
                "source_span_ids": ["SRC-1:original_markdown:chunk-001"],
                "forecast_testability": "not_testable",
                "direction": "positive",
                "target": {"target_type": "sector", "target_id": "有色金属"},
                "horizon": {"max_days": 120, "unit": "trading_day"},
            }
        ],
        footprint_rows=[],
        metric_rows=[],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-INDUSTRY-1",
                "test_status": "blocked_mapping_missing",
            }
        ],
        outcome_label_rows=[
            {
                "forecast_claim_id": "FC-INDUSTRY-1",
                "label_type": "industry_etf_proxy",
                "outcome_label_source": "pit_industry_etf_price_window",
                "llm_outcome_labeling_allowed": False,
                "decision_basis": "absolute_proxy_return_direction",
            }
        ],
        outcome_labeling_readiness={
            "ready_for_outcome_labeling_count": 0,
            "standard_blocked_count": 1,
            "blocked_count": 0,
        },
    )

    by_id = {row["check_id"]: row for row in audit["checks"]}
    assert audit["accepted"] is True
    assert by_id["RI-PROV-04"]["accepted"] is True
    assert by_id["RI-PROV-04"]["evidence"][
        "industry_etf_proxy_outcome_claim_count"
    ] == 1


def test_report_intelligence_labels_industry_claims_with_etf_proxy_windows(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_label_rows == 3
    assert result.industry_etf_proxy_outcome_label_rows == 3
    assert result.industry_etf_proxy_eligible_claim_rows == 1
    assert result.industry_etf_proxy_labelable_window_rows == 3
    assert result.industry_etf_proxy_pending_window_rows == 0

    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}
    assert {row["label_type"] for row in outcome_labels} == {"industry_etf_proxy"}
    assert {row["proxy_symbol"] for row in outcome_labels} == {"SH560860"}
    assert {row["benchmark_symbol"] for row in outcome_labels} == {"SH510300"}
    assert {row["benchmark_source"] for row in outcome_labels} == {"cn_etf"}
    assert {row["benchmark_family"] for row in outcome_labels} == {
        "CSI300_ETF_PROXY"
    }
    assert {row["cost_model_id"] for row in outcome_labels} == {
        "industry_etf_round_trip_10bps_v1"
    }
    assert all(str(row["mapping_id"]).startswith("IETF-MAP-") for row in outcome_labels)
    assert {row["mapping_version"] for row in outcome_labels} == {1}
    assert {row["pit_availability_status"] for row in outcome_labels} == {"available"}
    assert {row["decision_basis"] for row in outcome_labels} == {
        "absolute_proxy_return_direction"
    }
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_industry_etf_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert {row["source_horizon_days"] for row in outcome_labels} == {120}
    assert {row["source_horizon_bucket"] for row in outcome_labels} == {
        "long_horizon"
    }
    assert {row["claim_window_alignment"] for row in outcome_labels} == {
        "within_source_horizon"
    }
    assert {row["evaluation_policy"] for row in outcome_labels} == {
        "industry_etf_t_plus_1_multi_window_proxy_retains_long_horizon_evidence"
    }
    assert {row["entry_datetime"] for row in outcome_labels} == {
        "2026-01-03T00:00:00+08:00"
    }
    assert {row["entry_lag_trading_days"] for row in outcome_labels} == {1}
    assert {row["round_trip_cost"] for row in outcome_labels} == {0.001}
    assert {row["market_regime"] for row in outcome_labels} == {
        "us_rate_cut_cycle|china_monetary_easing_cycle|rmb_fx_stability_window"
    }
    assert {tuple(row["market_regime_types"]) for row in outcome_labels} == {
        (
            "us_rate_cut_cycle",
            "china_monetary_easing_cycle",
            "rmb_fx_stability_window",
        )
    }
    assert {row["market_regime_source"] for row in outcome_labels} == {"as_of_date"}
    assert {row["market_regime_source_text_grounded"] for row in outcome_labels} == {
        False
    }
    assert {
        row["market_regime_details"][0]["source_basis"] for row in outcome_labels
    } == {"as_of_date"}
    assert {
        row["market_regime_details"][0]["source_text_grounded"]
        for row in outcome_labels
    } == {False}
    assert all(row["directional_hit"] is True for row in outcome_labels)
    assert all(row["relative_alpha"] > 0 for row in outcome_labels)

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    proxy_readiness = readiness["industry_etf_proxy_readiness"]
    readiness_dump = json.dumps(readiness, ensure_ascii=False)
    assert "/home/hap" not in readiness_dump
    assert proxy_readiness["qlib_etf_dir_configured"].startswith("qlib://")
    assert proxy_readiness["eligible_claim_count"] == 1
    assert proxy_readiness["labelable_forecast_claim_count"] == 1
    assert proxy_readiness["labelable_forecast_claim_ids"] == [
        outcome_labels[0]["forecast_claim_id"]
    ]
    assert proxy_readiness["labelable_window_count"] == 3
    assert proxy_readiness["pending_future_window_count"] == 0
    assert proxy_readiness["latest_calendar_date"] == "2026-05-31"
    assert proxy_readiness["entry_lag_trading_days"] == 1
    assert readiness["ready_for_outcome_labeling_count"] == 1
    assert readiness["standard_blocked_count"] == 0
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["proxy_label_only_ready_count"] == 0

    mapping_rows = _read_jsonl(
        tmp_path / "registry/report_intelligence/industry_etf_proxy_map.jsonl"
    )
    assert any(row["sector_name"] == "工业金属" for row in mapping_rows)
    assert {row["status"] for row in mapping_rows} == {"primary"}

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    assert pit_availability["mapping_count"] == len(mapping_rows)
    industrial_metals = next(
        row for row in pit_availability["mapping_records"] if row["sector_name"] == "工业金属"
    )
    assert industrial_metals["pit_available"] is True
    assert industrial_metals["available_window_days"] == [20, 60, 120]
    labelability = pit_availability["labelability_summary"]
    assert labelability["eligible_claim_count"] == proxy_readiness[
        "eligible_claim_count"
    ]
    assert labelability["labelable_claim_count"] == proxy_readiness[
        "labelable_forecast_claim_count"
    ]
    assert labelability["labelable_window_count"] == proxy_readiness[
        "labelable_window_count"
    ]
    assert labelability["pending_future_window_count"] == proxy_readiness[
        "pending_future_window_count"
    ]
    assert labelability["data_gap_counts"] == proxy_readiness["data_gap_counts"]
    action_summary = pit_availability["labelability_action_summary"]
    assert action_summary["coverage_gate_status"] == "actionable_gaps_present"
    assert action_summary["eligible_claim_count"] == labelability[
        "eligible_claim_count"
    ]
    assert action_summary["labelable_claim_count"] == labelability[
        "labelable_claim_count"
    ]
    assert action_summary["sector_etf_mapping_missing_count"] == labelability[
        "sector_etf_mapping_missing_count"
    ]
    assert action_summary["pit_unavailable_mapping_count"] == (
        pit_availability["mapping_count"]
        - pit_availability["pit_available_mapping_count"]
    )
    assert "refresh_or_replace_pit_unavailable_etf_mappings" in action_summary[
        "next_actions"
    ]
    availability_dump = json.dumps(pit_availability, ensure_ascii=False)
    assert "/home/hap" not in availability_dump
    assert pit_availability["qlib_etf_dir_configured"].startswith("qlib://")
    assert all(
        row["calendar_source"].startswith("qlib://")
        for row in pit_availability["mapping_records"]
    )
    assert source_id not in availability_dump
    assert "Liquidity report" not in availability_dump
    assert readiness["blocked_count"] == 0


def test_report_intelligence_industry_pit_availability_blocks_labels(
    tmp_path: Path,
):
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)
    mapping_rows = [
        {
            "mapping_id": "IETF-MAP-PIT-BLOCKED",
            "mapping_version": 1,
            "sector_name": "工业金属",
            "sector_aliases": ["工业金属"],
            "taxonomy": "test_taxonomy",
            "etf_symbol": "SH512400",
            "etf_name": "有色金属ETF",
            "mapping_label": "有色金属ETF",
            "benchmark_symbol": "SH510300",
            "benchmark_source": "cn_etf",
            "benchmark_family": "CSI300_ETF_PROXY",
            "cost_model_id": "industry_etf_round_trip_10bps_v1",
            "mapping_confidence": "operator_seeded_exact_sector",
            "mapping_rationale": "test PIT availability gate",
            "effective_from": "",
            "effective_to": "",
            "status": "primary",
            "review_required": False,
        }
    ]
    metadata_rows = [
        {
            "source_id": "SRC-PIT-BLOCKED",
            "report_type": "行业研究",
            "sector": "工业金属",
        }
    ]
    forecast_rows = [
        {
            "forecast_claim_id": "FC-PIT-BLOCKED",
            "source_id": "SRC-PIT-BLOCKED",
            "signal_datetime": "2026-01-02T00:00:00+08:00",
            "direction": "positive",
            "target": {"target_type": "sector", "target_id": "工业金属"},
            "horizon": {"preferred_days": 120},
        }
    ]
    pit_availability = {
        "mapping_records": [
            {
                "mapping_id": "IETF-MAP-PIT-BLOCKED",
                "pit_available": False,
                "pit_gap_reasons": ["insufficient_window_history"],
            }
        ]
    }

    readiness = build_industry_etf_proxy_readiness(
        root_path=tmp_path,
        qlib_etf_dir=qlib_etf_dir,
        forecast_rows=forecast_rows,
        metadata_rows=metadata_rows,
        mapping_rows=mapping_rows,
        pit_availability=pit_availability,
    )
    labels = build_industry_etf_proxy_outcome_labels(
        root_path=tmp_path,
        qlib_etf_dir=qlib_etf_dir,
        forecast_rows=forecast_rows,
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-PIT-BLOCKED",
                "forecast_family_id": "FF-PIT-BLOCKED",
            }
        ],
        metadata_rows=metadata_rows,
        mapping_rows=mapping_rows,
        pit_availability=pit_availability,
    )

    assert readiness["eligible_claim_count"] == 1
    assert readiness["labelable_forecast_claim_count"] == 0
    assert readiness["labelable_window_count"] == 0
    assert readiness["data_gap_counts"] == {
        "pit_availability_insufficient_window_history": 1
    }
    assert labels == []


def test_report_intelligence_merges_default_industry_etf_mapping_fallbacks(
    tmp_path: Path,
):
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True)
    stale_default_mapping = {
        "mapping_id": "IETF-MAP-STALE-DEFAULT",
        "mapping_version": 1,
        "sector_name": "工业金属",
        "sector_aliases": ["工业金属"],
        "taxonomy": "operator_seeded_tushare_industry",
        "etf_symbol": "SH512400",
        "etf_name": "有色ETF",
        "mapping_label": "有色ETF",
        "benchmark_symbol": "SH510300",
        "benchmark_source": "cn_etf",
        "benchmark_family": "CSI300_ETF_PROXY",
        "cost_model_id": "industry_etf_round_trip_10bps_v1",
        "mapping_confidence": "operator_seeded_exact_sector",
        "mapping_rationale": "old default should be refreshed",
        "effective_from": "",
        "effective_to": "",
        "status": "primary",
        "review_required": False,
    }
    existing_mapping = {
        "mapping_id": "IETF-MAP-EXISTING",
        "mapping_version": 1,
        "sector_name": "有色金属",
        "sector_aliases": ["有色金属"],
        "taxonomy": "test_taxonomy",
        "etf_symbol": "SH512400",
        "etf_name": "有色ETF",
        "mapping_label": "有色ETF",
        "benchmark_symbol": "SH510300",
        "benchmark_source": "cn_etf",
        "benchmark_family": "CSI300_ETF_PROXY",
        "cost_model_id": "industry_etf_round_trip_10bps_v1",
        "mapping_confidence": "operator_override",
        "mapping_rationale": "operator override should remain authoritative",
        "effective_from": "",
        "effective_to": "",
        "status": "primary",
        "review_required": False,
    }
    (registry_dir / "industry_etf_proxy_map.jsonl").write_text(
        "\n".join(
            [
                json.dumps(stale_default_mapping, ensure_ascii=False),
                json.dumps(existing_mapping, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    mapping_rows = _read_industry_etf_proxy_map_rows(registry_dir)

    by_sector = {str(row["sector_name"]): row for row in mapping_rows}
    assert by_sector["工业金属"]["etf_symbol"] == "SH560860"
    assert by_sector["有色金属"]["etf_symbol"] == "SH512400"
    assert by_sector["有色金属"]["mapping_confidence"] == "operator_override"
    assert by_sector["通信设备"]["etf_symbol"] == "SH515880"
    assert by_sector["IT服务Ⅱ"]["etf_symbol"] == "SH515230"
    assert by_sector["旅游及景区"]["etf_symbol"] == "SZ159766"
    assert sum(1 for row in mapping_rows if row["sector_name"] == "工业金属") == 1


def test_report_intelligence_industry_pit_availability_records_missing_benchmark(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_without_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    assert result.industry_etf_proxy_eligible_claim_rows == 1
    assert result.industry_etf_proxy_labelable_window_rows == 0

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "benchmark_series_missing": 1
    }
    assert readiness["industry_proxy_label_ready_count"] == 0
    assert readiness["proxy_label_ready_count"] == 0

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    assert pit_availability["pit_gap_counts"]["benchmark_series_missing"] >= 1
    labelability = pit_availability["labelability_summary"]
    assert labelability["eligible_claim_count"] == 1
    assert labelability["labelable_claim_count"] == 0
    assert labelability["labelable_window_count"] == 0
    assert labelability["benchmark_series_missing_count"] == 1
    assert labelability["data_gap_counts"] == {"benchmark_series_missing": 1}
    action_summary = pit_availability["labelability_action_summary"]
    assert action_summary["pit_unavailable_mapping_count"] > 0
    assert "refresh_or_replace_pit_unavailable_etf_mappings" in action_summary[
        "next_actions"
    ]


def test_report_intelligence_industry_readiness_records_missing_proxy_series(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_without_proxy_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    assert result.industry_etf_proxy_eligible_claim_rows == 1
    assert result.industry_etf_proxy_labelable_window_rows == 0

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "proxy_series_missing": 1
    }
    assert readiness["industry_proxy_label_ready_count"] == 0

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    labelability = pit_availability["labelability_summary"]
    assert labelability["eligible_claim_count"] == 1
    assert labelability["labelable_claim_count"] == 0
    assert labelability["proxy_series_missing_count"] == 1
    assert labelability["data_gap_counts"] == {"proxy_series_missing": 1}
    action_summary = pit_availability["labelability_action_summary"]
    assert action_summary["pit_unavailable_mapping_count"] > 0
    assert "refresh_or_replace_pit_unavailable_etf_mappings" in action_summary[
        "next_actions"
    ]


def test_report_intelligence_industry_candidate_mapping_does_not_label(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    _write_jsonl(
        tmp_path / "registry/report_intelligence/industry_etf_proxy_map.jsonl",
        [
            {
                "mapping_id": "IETF-MAP-CANDIDATE-INDUSTRIAL-METALS",
                "mapping_version": 1,
                "sector_name": "工业金属",
                "sector_aliases": ["工业金属", "有色金属"],
                "taxonomy": "test_taxonomy",
                "etf_symbol": "SH512400",
                "etf_name": "有色金属ETF",
                "mapping_label": "有色金属ETF",
                "benchmark_symbol": "SH510300",
                "benchmark_source": "cn_etf",
                "benchmark_family": "CSI300_ETF_PROXY",
                "cost_model_id": "industry_etf_round_trip_10bps_v1",
                "mapping_confidence": "candidate_requires_review",
                "mapping_rationale": "candidate mappings must not label by default",
                "effective_from": "",
                "effective_to": "",
                "status": "candidate",
                "review_required": True,
            }
        ],
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "sector_etf_mapping_missing": 1
    }
    assert readiness["industry_proxy_label_ready_count"] == 0


def test_report_intelligence_industry_mapping_uses_registry_benchmark_symbol(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    _write_jsonl(
        tmp_path / "registry/report_intelligence/industry_etf_proxy_map.jsonl",
        [
            {
                "mapping_id": "IETF-MAP-CUSTOM-BENCHMARK",
                "mapping_version": 1,
                "sector_name": "工业金属",
                "sector_aliases": ["工业金属", "有色金属"],
                "taxonomy": "test_taxonomy",
                "etf_symbol": "SH512400",
                "etf_name": "有色金属ETF",
                "mapping_label": "有色金属ETF",
                "benchmark_symbol": "SH510500",
                "benchmark_source": "cn_etf",
                "benchmark_family": "CSI500_ETF_PROXY",
                "cost_model_id": "industry_etf_round_trip_10bps_v1",
                "mapping_confidence": "test_custom_benchmark",
                "mapping_rationale": "custom benchmark must drive relative alpha",
                "effective_from": "",
                "effective_to": "",
                "status": "primary",
                "review_required": False,
            }
        ],
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_custom_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {
                            "benchmark_type": "sector_registry_benchmark",
                            "benchmark_id": "SH510500",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 3
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["benchmark_symbol"] for row in outcome_labels} == {"SH510500"}
    assert {row["benchmark_family"] for row in outcome_labels} == {
        "CSI500_ETF_PROXY"
    }
    assert all(row["proxy_return"] > 0 for row in outcome_labels)
    assert all(row["benchmark_return"] > row["proxy_return"] for row in outcome_labels)
    assert all(row["relative_alpha"] < 0 for row in outcome_labels)
    assert all(row["relative_directional_hit"] is False for row in outcome_labels)

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert "SH510500" in readiness["industry_etf_proxy_readiness"]["benchmark_symbols"]

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    mapping_record = pit_availability["mapping_records"][0]
    assert mapping_record["mapping_id"] == "IETF-MAP-CUSTOM-BENCHMARK"
    assert mapping_record["benchmark_symbol"] == "SH510500"
    assert mapping_record["benchmark_family"] == "CSI500_ETF_PROXY"
    assert mapping_record["pit_available"] is True


def test_report_intelligence_industry_mapping_effective_from_blocks_early_claim(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    _write_jsonl(
        tmp_path / "registry/report_intelligence/industry_etf_proxy_map.jsonl",
        [
            {
                "mapping_id": "IETF-MAP-FUTURE-EFFECTIVE",
                "mapping_version": 1,
                "sector_name": "工业金属",
                "sector_aliases": ["工业金属", "有色金属"],
                "taxonomy": "test_taxonomy",
                "etf_symbol": "SH512400",
                "etf_name": "有色金属ETF",
                "mapping_label": "有色金属ETF",
                "benchmark_symbol": "SH510300",
                "benchmark_source": "cn_etf",
                "benchmark_family": "CSI300_ETF_PROXY",
                "cost_model_id": "industry_etf_round_trip_10bps_v1",
                "mapping_confidence": "future_effective_test",
                "mapping_rationale": "future effective mappings must not backfill early labels",
                "effective_from": "2026-02-01",
                "effective_to": "",
                "status": "primary",
                "review_required": False,
            }
        ],
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "工业金属",
                        },
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["industry_etf_proxy_readiness"]["data_gap_counts"] == {
        "sector_etf_mapping_missing": 1
    }

    pit_availability = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/industry_etf_proxy_pit_availability.json"
        ).read_text(encoding="utf-8")
    )
    mapping_record = pit_availability["mapping_records"][0]
    assert mapping_record["mapping_id"] == "IETF-MAP-FUTURE-EFFECTIVE"
    assert mapping_record["effective_from"] == "2026-02-01"
    assert pit_availability["labelability_summary"]["data_gap_counts"] == {
        "sector_etf_mapping_missing": 1
    }
    action_summary = pit_availability["labelability_action_summary"]
    assert action_summary["sector_etf_mapping_missing_count"] == 1
    assert "add_primary_etf_mapping_for_unmapped_industry_sectors" in action_summary[
        "next_actions"
    ]


def test_report_intelligence_pit_audit_rejects_t0_industry_etf_entry():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-T0-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-T0",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-T0",
                "source_id": "SRC-T0",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-T0",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-T0",
                "forecast_claim_id": "FC-T0",
                "entry_datetime": "2026-01-02T00:00:00+08:00",
                "exit_datetime": "2026-01-22T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": True,
                "label_type": "industry_etf_proxy",
                "entry_lag_trading_days": 0,
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("entry_datetime must be after signal date" in item for item in audit["blockers"])
    assert any("entry_lag_trading_days" in item for item in audit["blockers"])


def test_report_intelligence_labels_stock_claims_with_qlib_price_windows(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来一个季度股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {
                            "target_type": "stock",
                            "target_id": "000001.SZ",
                            "target_name": "平安银行",
                            "target_price": {
                                "value": "1.02 CNY",
                                "provenance": "source_grounded",
                            },
                        },
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {
                            "min_days": 5,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    assert result.stock_price_proxy_eligible_claim_rows == 1
    assert result.stock_price_proxy_labelable_window_rows == 4

    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert {row["label_type"] for row in outcome_labels} == {"stock_price_proxy"}
    assert [row["horizon_days"] for row in outcome_labels] == [5, 20, 60, 120]
    assert [row["effective_n_weight"] for row in outcome_labels] == [
        0.2,
        0.25,
        0.25,
        0.3,
    ]
    assert {row["proxy_symbol"] for row in outcome_labels} == {"000001.SZ"}
    assert {row["benchmark_symbol"] for row in outcome_labels} == {"SH510300"}
    assert {row["benchmark_source"] for row in outcome_labels} == {"cn_etf"}
    assert {row["benchmark_alignment"] for row in outcome_labels} == {
        "date_key_cross_qlib_dir"
    }
    assert {row["cost_model_id"] for row in outcome_labels} == {
        "single_stock_round_trip_20bps_v1"
    }
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_stock_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert {row["entry_datetime"] for row in outcome_labels} == {
        "2026-01-03T00:00:00+08:00"
    }
    assert {row["entry_lag_trading_days"] for row in outcome_labels} == {1}
    assert {row["round_trip_cost"] for row in outcome_labels} == {0.002}
    assert {row["target_resolution_source"] for row in outcome_labels} == {
        "metadata_and_llm_target_id"
    }
    assert {row["survivorship_safe"] for row in outcome_labels} == {False}
    assert {row["survivorship_check"] for row in outcome_labels} == {
        "survivorship_unverified_qlib_cn_data"
    }
    assert {row["entry_tradable"] for row in outcome_labels} == {True}
    assert {row["exit_tradable"] for row in outcome_labels} == {True}
    assert {row["entry_limit_locked"] for row in outcome_labels} == {False}
    assert {row["exit_limit_locked"] for row in outcome_labels} == {False}
    assert {row["entry_liquidity_check"] for row in outcome_labels} == {
        "positive_volume_and_limit_lock_screen"
    }
    assert {row["exit_liquidity_check"] for row in outcome_labels} == {
        "positive_volume_and_limit_lock_screen"
    }
    assert {row["market_regime"] for row in outcome_labels} == {
        "us_rate_cut_cycle|china_monetary_easing_cycle|rmb_fx_stability_window"
    }
    assert {tuple(row["market_regime_types"]) for row in outcome_labels} == {
        (
            "us_rate_cut_cycle",
            "china_monetary_easing_cycle",
            "rmb_fx_stability_window",
        )
    }
    assert {row["market_regime_source"] for row in outcome_labels} == {"as_of_date"}
    assert {row["market_regime_source_text_grounded"] for row in outcome_labels} == {
        False
    }
    assert {
        row["market_regime_details"][0]["source_basis"] for row in outcome_labels
    } == {"as_of_date"}
    assert {
        row["market_regime_details"][0]["source_text_grounded"]
        for row in outcome_labels
    } == {False}
    assert outcome_labels[0]["stock_return"] < 0
    assert outcome_labels[0]["directional_hit"] is False
    assert outcome_labels[0]["target_price_hit"] is False
    assert outcome_labels[-1]["stock_return"] > 0
    assert outcome_labels[-1]["directional_hit"] is True
    assert outcome_labels[-1]["target_price_hit"] is True
    assert {row["target_price"] for row in outcome_labels} == {1.02}
    assert {row["target_price_source_grounded"] for row in outcome_labels} == {True}
    assert {row["target_price_provenance"] for row in outcome_labels} == {
        "source_grounded"
    }
    assert outcome_labels[-1]["directional_after_cost_return"] > 0
    assert outcome_labels[0]["temporal_validation_summary"][
        "temporal_validation_bucket"
    ] == "short_miss_long_hit"

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    stock_readiness = readiness["stock_price_proxy_readiness"]
    readiness_dump = json.dumps(readiness, ensure_ascii=False)
    assert "/home/hap" not in readiness_dump
    assert stock_readiness["qlib_stock_dir_configured"].startswith("qlib://")
    assert stock_readiness["qlib_benchmark_dir_configured"].startswith("qlib://")
    assert stock_readiness["eligible_claim_count"] == 1
    assert stock_readiness["labelable_forecast_claim_count"] == 1
    assert stock_readiness["labelable_window_count"] == 4
    assert stock_readiness["data_gap_counts"] == {}
    assert stock_readiness["ordinary_stock_code_policy"] == {
        "policy_id": "ordinary_a_share_stock_codes_v1",
        "allowed_prefixes": {
            "SH": ["60", "68"],
            "SZ": ["00", "30"],
            "BJ": ["92"],
        },
        "rejected_code_families": [
            "fund",
            "etf",
            "lof",
            "index",
            "legacy_bj_8_prefix",
        ],
        "fund_like_prefix_examples": {
            "SH": ["50", "51", "52"],
            "SZ": ["15", "16", "18"],
        },
        "fallback_action": "stock_target_mapping_missing",
    }
    assert stock_readiness["pit_realism_policy"]["survivorship_unverified"] is True
    assert (
        stock_readiness["pit_realism_policy"]["survivorship_status"]
        == "survivorship_unverified"
    )
    assert readiness["stock_proxy_label_ready_count"] == 1
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["blocked_count"] == 0

    statistical_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/statistical_robustness_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert statistical_audit["accepted"] is True
    assert statistical_audit["checks"][1]["evidence"][
        "stock_price_proxy_label_rows"
    ] == 4
    assert statistical_audit["checks"][3]["evidence"][
        "complete_stock_price_window_set_count"
    ] == 1
    assert statistical_audit["checks"][6]["evidence"][
        "short_miss_long_hit_window_set_count"
    ] == 1


def test_report_intelligence_counts_stock_price_proxy_as_labelable_channel(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_labeling_ready_count == 0
    assert result.outcome_labeling_blocked_count == 0
    assert result.stock_price_proxy_outcome_label_rows == 4
    assert result.stock_price_proxy_eligible_claim_rows == 1
    assert result.stock_price_proxy_labelable_window_rows == 4

    forecasts = _read_jsonl(
        tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    )
    forecast_claim_id = forecasts[0]["forecast_claim_id"]
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "benchmark",
        "horizon",
    ]

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["standard_blocked_count"] == 1
    assert readiness["standard_blocked_forecast_claim_ids"] == [forecast_claim_id]
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["stock_proxy_label_ready_count"] == 1
    assert readiness["industry_proxy_label_ready_count"] == 0
    assert readiness["stock_proxy_label_ready_forecast_claim_ids"] == [
        forecast_claim_id
    ]
    assert readiness["proxy_label_only_ready_count"] == 1
    assert readiness["blocked_count"] == 0
    assert readiness["unlabelable_mapping_gap_counts"] == {}


def test_report_intelligence_keeps_long_window_stock_hits(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行短期可能震荡，但中长期基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert [row["label_type"] for row in outcome_labels] == [
        "stock_price_proxy",
        "stock_price_proxy",
        "stock_price_proxy",
        "stock_price_proxy",
    ]
    assert [row["horizon_days"] for row in outcome_labels] == [5, 20, 60, 120]
    assert [row["window_role"] for row in outcome_labels] == [
        "short",
        "short",
        "medium",
        "long",
    ]
    assert outcome_labels[0]["directional_hit"] is False
    assert outcome_labels[0]["directional_stock_return"] < 0
    assert all(row["directional_hit"] is True for row in outcome_labels[1:])
    assert outcome_labels[-1]["directional_stock_return"] > 0
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_stock_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}

    summary = outcome_labels[0]["temporal_validation_summary"]
    assert summary["temporal_validation_bucket"] == "short_miss_long_hit"
    assert summary["miss_window_days"] == [5]
    assert summary["hit_window_days"] == [20, 60, 120]
    assert summary["short_window_directional_hit"] is False
    assert summary["long_window_directional_hit"] is True
    assert summary["long_window_hit_retained"] is True
    assert summary["window_evidence_policy"] == (
        "do_not_collapse_multi_window_outcome_to_single_label"
    )


def test_report_intelligence_marks_stock_proxy_future_windows_as_pending(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-05-30",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    assert result.stock_price_proxy_eligible_claim_rows == 1
    assert result.stock_price_proxy_labelable_window_rows == 0

    forecasts = _read_jsonl(
        tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    )
    forecast_claim_id = forecasts[0]["forecast_claim_id"]
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    stock_readiness = readiness["stock_price_proxy_readiness"]
    assert stock_readiness["eligible_claim_count"] == 1
    assert stock_readiness["labelable_forecast_claim_count"] == 0
    assert stock_readiness["pending_future_window_count"] == 4
    assert stock_readiness["pending_future_forecast_claim_count"] == 1
    assert stock_readiness["pending_future_forecast_claim_ids"] == [
        forecast_claim_id
    ]
    assert readiness["standard_blocked_count"] == 1
    assert readiness["proxy_label_pending_count"] == 1
    assert readiness["stock_proxy_label_pending_count"] == 1
    assert readiness["proxy_label_pending_only_count"] == 1
    assert readiness["proxy_label_pending_only_forecast_claim_ids"] == [
        forecast_claim_id
    ]
    assert readiness["blocked_count"] == 0
    assert readiness["unlabelable_mapping_gap_counts"] == {}

    provenance_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/extraction_provenance_audit.json"
        ).read_text(encoding="utf-8")
    )
    by_id = {row["check_id"]: row for row in provenance_audit["checks"]}
    assert by_id["RI-PROV-04"]["accepted"] is True
    assert by_id["RI-PROV-04"]["evidence"]["proxy_label_pending_only_count"] == 1
    assert by_id["RI-PROV-04"]["evidence"]["unlabelable_forecast_count"] == 0


def test_report_intelligence_stock_benchmark_aligns_by_date_across_qlib_dirs(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_misaligned_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来五个交易日股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 5, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    five_day_label = next(row for row in outcome_labels if row["horizon_days"] == 5)
    assert five_day_label["entry_datetime"] == "2026-01-03T00:00:00+08:00"
    assert five_day_label["exit_datetime"] == "2026-01-08T00:00:00+08:00"
    assert five_day_label["benchmark_alignment"] == "date_key_cross_qlib_dir"
    assert five_day_label["benchmark_calendar_source"] == str(qlib_etf_dir)
    assert five_day_label["stock_calendar_source"] == str(qlib_stock_dir)
    assert five_day_label["benchmark_return"] == pytest.approx(0.1)


def test_report_intelligence_labels_bearish_stock_claims(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    _write_qlib_stock_fixture(
        qlib_stock_dir,
        values=[1.0 - index * 0.002 for index in range(len(dates))],
    )
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行盈利承压，未来一个季度股价可能下跌。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "negative",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["direction_evaluated"] for row in outcome_labels} == {"negative"}
    assert all(row["stock_return"] < 0 for row in outcome_labels)
    assert all(row["directional_stock_return"] > 0 for row in outcome_labels)
    assert all(row["directional_hit"] is True for row in outcome_labels)
    assert all(row["relative_directional_hit"] is True for row in outcome_labels)


def test_report_intelligence_stock_readiness_records_price_gaps(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_calendar(qlib_stock_dir, _stock_fixture_dates())
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_series_missing": 1
    }
    assert readiness["blocked_count"] == 1


def test_report_intelligence_stock_readiness_records_series_start_gap(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    _write_qlib_calendar(qlib_stock_dir, dates)
    late_values = [1.0 + index * 0.001 for index in range(len(dates) - 10)]
    for field, values in {
        "adjclose": late_values,
        "close": late_values,
        "open": late_values,
        "high": [value * 1.001 for value in late_values],
        "low": [value * 0.999 for value in late_values],
        "volume": [100.0 for _ in late_values],
    }.items():
        _write_qlib_series(
            qlib_stock_dir,
            "000001.SZ",
            values,
            field=field,
            start_index=10.0,
        )
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    stock_readiness = readiness["stock_price_proxy_readiness"]
    assert stock_readiness["data_gap_counts"] == {
        "entry_price_before_series_start": 1
    }
    assert stock_readiness["stock_series_coverage_summary"] == {
        "target_series_count": 1,
        "target_series_missing_count": 0,
        "earliest_price_date_min": "2026-01-11",
        "earliest_price_date_max": "2026-01-11",
        "latest_price_date_min": "2026-05-31",
        "latest_price_date_max": "2026-05-31",
        "latest_calendar_date": "2026-05-31",
        "latest_aligned_series_count": 1,
        "stale_before_latest_calendar_count": 0,
        "future_dated_series_count": 0,
        "series_lifecycle_status_counts": {"latest_aligned": 1},
        "entry_before_series_start_count": 1,
        "entry_after_series_end_count": 0,
        "entry_within_series_range_count": 0,
    }


def test_report_intelligence_stock_target_conflict_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000002.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_target_conflict": 1
    }


@pytest.mark.parametrize("bj_ts_code", ("920001.BJ", "921001.BJ"))
def test_report_intelligence_accepts_bj_92_stock_codes(
    tmp_path: Path,
    bj_ts_code: str,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="北交所",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code=bj_ts_code,
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir, symbol=bj_ts_code)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "北交所公司基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": bj_ts_code},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 4
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["proxy_symbol"] for row in outcome_labels} == {bj_ts_code}
    assert {row["metadata_ts_code"] for row in outcome_labels} == {bj_ts_code}
    assert {row["llm_target_id"] for row in outcome_labels} == {bj_ts_code}


def test_report_intelligence_rejects_legacy_bj_8_stock_codes(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="北交所",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="830001.BJ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir, symbol="830001.BJ")
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "北交所公司基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "830001.BJ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_target_mapping_missing": 1
    }


@pytest.mark.parametrize("fund_like_code", ("501001.SH", "160621.SZ"))
def test_report_intelligence_rejects_fund_like_codes_as_stock_targets(
    tmp_path: Path,
    fund_like_code: str,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="基金",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code=fund_like_code,
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "基金类代码不应被普通股票评价通道处理。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": fund_like_code},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_target_mapping_missing": 1
    }


def test_report_intelligence_stock_entry_suspension_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    volume = [100.0 for _ in dates]
    volume[2] = 0.0
    _write_qlib_stock_fixture(qlib_stock_dir, volume=volume)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_entry_suspended": 1
    }


def test_report_intelligence_stock_entry_limit_locked_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_entry_limit_locked_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "entry_limit_locked": 1
    }


def test_report_intelligence_stock_long_suspension_blocks_window(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    dates = _stock_fixture_dates()
    volume = [100.0 for _ in dates]
    volume[7] = 0.0
    _write_qlib_stock_fixture(qlib_stock_dir, volume=volume)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 3
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_long_suspension_window": 1
    }


def test_report_intelligence_stock_delisted_before_exit_blocks_labeling(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_truncated_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 0
    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "stock_delisted_before_exit": 4
    }
    assert readiness["stock_price_proxy_readiness"][
        "stock_series_coverage_summary"
    ]["series_lifecycle_status_counts"] == {
        "stale_before_latest_calendar": 1
    }
    assert readiness["stock_price_proxy_readiness"][
        "stock_series_coverage_summary"
    ]["stale_before_latest_calendar_count"] == 1


def test_report_intelligence_stock_exit_limit_locked_blocks_window(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_exit_limit_locked_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 3
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "exit_limit_locked": 1
    }
    assert readiness["stock_price_proxy_readiness"]["labelable_window_count"] == 3


def test_report_intelligence_stock_exit_liquidity_unverified_blocks_window(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="银行",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )
    qlib_stock_dir = tmp_path / "qlib_stock"
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_stock_exit_liquidity_unverified_fixture(qlib_stock_dir)
    _write_qlib_stock_benchmark_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "平安银行基本面改善，未来股价有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "stock_outlook",
                        "target": {"target_type": "stock", "target_id": "000001.SZ"},
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {"max_days": 120, "unit": "trading_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_stock_dir=qlib_stock_dir,
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.stock_price_proxy_outcome_label_rows == 3
    outcome_labels = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    )
    assert {row["horizon_days"] for row in outcome_labels} == {20, 60, 120}

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["stock_price_proxy_readiness"]["data_gap_counts"] == {
        "exit_liquidity_unverified": 1
    }
    assert readiness["stock_price_proxy_readiness"]["labelable_window_count"] == 3


def test_report_intelligence_pit_audit_rejects_t0_stock_entry():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-T0-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-T0",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-T0",
                "source_id": "SRC-STOCK-T0",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-T0",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-T0",
                "forecast_claim_id": "FC-STOCK-T0",
                "entry_datetime": "2026-01-02T00:00:00+08:00",
                "exit_datetime": "2026-01-22T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": True,
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 0,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "stock_calendar_index",
                "latest_calendar_date": "2026-05-31",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("stock entry_datetime must be after signal date" in item for item in audit["blockers"])
    assert any("stock entry_lag_trading_days" in item for item in audit["blockers"])
    assert any("stock benchmark must align by date" in item for item in audit["blockers"])


def test_report_intelligence_pit_audit_rejects_stock_exit_limit_locked_label():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-EXIT-LOCKED-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-EXIT-LOCKED",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-EXIT-LOCKED",
                "source_id": "SRC-STOCK-EXIT-LOCKED",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-EXIT-LOCKED",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-EXIT-LOCKED",
                "forecast_claim_id": "FC-STOCK-EXIT-LOCKED",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
                "readiness_gaps": ["exit_limit_locked"],
                "entry_tradable": True,
                "exit_tradable": False,
                "entry_limit_locked": False,
                "exit_limit_locked": True,
                "entry_liquidity_check": "positive_volume_and_limit_lock_screen",
                "exit_liquidity_check": "positive_volume_and_limit_lock_screen",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("exit_limit_locked" in item for item in audit["blockers"])


def test_report_intelligence_pit_audit_rejects_stock_long_suspension_label():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-LONG-SUSPENSION-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-LONG-SUSPENSION",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-LONG-SUSPENSION",
                "source_id": "SRC-STOCK-LONG-SUSPENSION",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-LONG-SUSPENSION",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-LONG-SUSPENSION",
                "forecast_claim_id": "FC-STOCK-LONG-SUSPENSION",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
                "readiness_gaps": ["stock_long_suspension_window"],
                "entry_tradable": True,
                "exit_tradable": True,
                "entry_limit_locked": False,
                "exit_limit_locked": False,
                "entry_liquidity_check": "positive_volume_and_limit_lock_screen",
                "exit_liquidity_check": "positive_volume_and_limit_lock_screen",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("stock_long_suspension_window" in item for item in audit["blockers"])


def test_report_intelligence_pit_audit_allows_shadow_stock_survivorship_unverified():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-SURVIVORSHIP-SHADOW-TEST",
        feature_flags={
            "rollout_mode": "shadow_tooling",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-SURVIVORSHIP",
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
                "entry_tradable": True,
                "exit_tradable": True,
                "entry_limit_locked": False,
                "exit_limit_locked": False,
                "entry_liquidity_check": "positive_volume_and_limit_lock_screen",
                "exit_liquidity_check": "positive_volume_and_limit_lock_screen",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is True
    by_id = {row["check_id"]: row for row in audit["checks"]}
    assert by_id["RI-PIT-02"]["evidence"][
        "stock_survivorship_unverified_count"
    ] == 1


def test_report_intelligence_pit_audit_blocks_promoted_stock_survivorship_unverified():
    audit = build_report_intelligence_pit_leakage_audit(
        run_id="RIR-PIT-STOCK-SURVIVORSHIP-PROMOTED-TEST",
        feature_flags={
            "rollout_mode": "paper_trading",
            "flags": {"production_use_of_weighted_reports": False},
        },
        metadata_rows=[
            {
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "accessible_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "source_id": "SRC-STOCK-SURVIVORSHIP",
                "signal_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        forecast_ledger_rows=[
            {
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "as_of_datetime": "2026-01-02T00:00:00+08:00",
            }
        ],
        outcome_label_rows=[
            {
                "outcome_id": "OUT-STOCK-SURVIVORSHIP",
                "forecast_claim_id": "FC-STOCK-SURVIVORSHIP",
                "entry_datetime": "2026-01-03T00:00:00+08:00",
                "exit_datetime": "2026-01-08T00:00:00+08:00",
                "pit_valid": True,
                "survivorship_safe": False,
                "survivorship_check": "survivorship_unverified_qlib_cn_data",
                "label_type": "stock_price_proxy",
                "entry_lag_trading_days": 1,
                "benchmark_source": "cn_etf",
                "benchmark_alignment": "date_key_cross_qlib_dir",
                "latest_calendar_date": "2026-05-31",
                "entry_tradable": True,
                "exit_tradable": True,
                "entry_limit_locked": False,
                "exit_limit_locked": False,
                "entry_liquidity_check": "positive_volume_and_limit_lock_screen",
                "exit_liquidity_check": "positive_volume_and_limit_lock_screen",
            }
        ],
        source_performance_profile_rows=[],
        tool_coverage_match_rows=[],
        analysis_recipe_rows=[],
        weighted_research_context_rows=[],
    )

    assert audit["accepted"] is False
    assert any("survivorship_unverified cannot support" in item for item in audit["blockers"])


def test_report_intelligence_cli_help_exposes_stock_qlib_dir(capsys):
    with pytest.raises(SystemExit) as exc:
        main(("report-intelligence", "--help"))

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--qlib-stock-dir" in help_text
    assert "--registry-dir" in help_text
    assert "--env-file" in help_text
    assert "--exclude-processed-registry-dir" in help_text
    assert "--require-cached-markdown" in help_text
    assert "--vllm-timeout-seconds" in help_text
    assert "--max-llm-output-tokens" in help_text
    assert "--progress-jsonl" in help_text
    assert "stratified" in help_text
    assert ReportIntelligenceConfig().qlib_stock_dir == "~/.qlib/qlib_data/cn_data"
    assert ReportIntelligenceConfig().vllm_timeout_seconds == DEFAULT_VLLM_TIMEOUT_SECONDS
    assert ReportIntelligenceConfig().vllm_timeout_seconds >= 7200


def test_report_intelligence_progress_jsonl_is_redacted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研究",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
            progress_jsonl=True,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    stderr = capsys.readouterr().err
    progress_rows = [
        json.loads(line)
        for line in stderr.splitlines()
        if line.strip()
    ]
    assert {row["event"] for row in progress_rows} >= {
        "selected",
        "llm_start",
        "llm_done",
        "summary",
    }
    assert source_id not in stderr
    assert "http" not in stderr


def test_report_intelligence_cli_loads_env_file_before_vllm_key_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "MOSAIC_VLLM_API_KEY=from-env-file",
                "MOSAIC_RKE_VLLM_BASE_URL=https://example.invalid/v1",
                "MOSAIC_RKE_VLLM_MODEL=test-model",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MOSAIC_VLLM_API_KEY", raising=False)
    monkeypatch.delenv("MOSAIC_RKE_VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("MOSAIC_RKE_VLLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_refresh(config: ReportIntelligenceConfig):
        assert config.vllm_api_key == "from-env-file"
        assert config.vllm_base_url == "https://example.invalid/v1"
        assert config.vllm_model == "test-model"
        raise RuntimeError("captured config")

    monkeypatch.setattr("mosaic.rke.cli.run_report_intelligence_refresh", fake_refresh)

    with pytest.raises(RuntimeError, match="captured config"):
        main(("report-intelligence", "--env-file", str(env_path), "--skip-llm"))


def test_report_intelligence_evolution_gate_writer_preserves_stock_coverage_evidence(
    tmp_path: Path,
):
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True, exist_ok=True)

    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    _write_jsonl(
        registry_dir / "report_forecast_ledger.jsonl",
        [{"forecast_claim_id": "FC-001", "source_id": "SRC-001"}],
    )
    for filename in (
        "monitor_refresh_history.jsonl",
        "audit_refresh_history.jsonl",
        "gap_distribution_history.jsonl",
    ):
        _write_jsonl(registry_dir / filename, [])

    write_json(
        registry_dir / "recipe_paper_trading_summary.json",
        {
            "paper_trading_run_count": 0,
            "validation_pass_count": 0,
            "mean_cost_adjusted_alpha": None,
        },
    )
    write_json(
        registry_dir / "confidence_impact_monitor.json",
        {
            "observation_count": 0,
            "blocked_recipe_count": 0,
            "unvalidated_confidence_impact_count": 0,
            "calibration_drift_count": 0,
            "aggregate_calibration_drift_count": 0,
            "calibration_drift_rule_counts": {},
        },
    )
    write_json(
        registry_dir / "markdown_coverage_summary.json",
        {
            "coverage_gate_status": "blocked",
            "coverage_gate_blockers": [
                "stock_outcome_120d_ready_count_below_p9_target"
            ],
            "coverage_targets": {"stock_outcome_120d_ready_report_count_min": 30},
            "coverage_shortfalls": {
                "stock_outcome_120d_ready_report_count": {
                    "blocker": "stock_outcome_120d_ready_count_below_p9_target",
                    "current": 0,
                    "next_action": (
                        "prefer_historical_stock_reports_with_120d_outcome_windows"
                    ),
                    "remaining": 30,
                    "target": 30,
                }
            },
            "coverage_strata_targets": {
                "stock_outcome_age_bucket_required": [
                    "stock_outcome_120d_calendar_ready"
                ]
            },
            "coverage_strata_missing": [
                "stock_outcome_age_bucket:stock_outcome_120d_calendar_ready"
            ],
            "selected_report_count": 0,
            "markdown_ready_count": 0,
            "markdown_quality_pass_count": 0,
            "llm_extraction_processed_count": 0,
            "industry_report_count": 0,
            "stock_report_count": 0,
            "stock_outcome_120d_ready_report_count": 0,
            "stock_outcome_age_bucket_counts": {},
        },
    )
    for filename in (
        "pit_leakage_audit.json",
        "extraction_provenance_audit.json",
        "statistical_robustness_audit.json",
    ):
        write_json(registry_dir / filename, {"accepted": True, "blockers": []})
    write_json(
        registry_dir / "analytical_footprint_review_summary.json",
        {
            "accepted": False,
            "review_complete": True,
            "quality_gate_passed": False,
            "complete_rows": 34,
            "pending_rows": 0,
            "precision_recall_report": {
                "footprint_precision": 1.0,
                "span_support_precision": 1.0,
                "metric_mapping_accuracy": 0.558824,
                "inferred_step_tagging_accuracy": 1.0,
                "unknown_on_ambiguity_rate": 0.941176,
                "proprietary_leakage_free_rate": 1.0,
            },
        },
    )
    write_json(
        registry_dir / "outcome_labeling_readiness.json",
        {
            "mapping_gap_counts": {},
            "stock_price_proxy_readiness": {
                "labelable_forecast_claim_count": 1,
                "labelable_forecast_claim_ids": ["FC-STOCK-001"],
            },
            "industry_etf_proxy_readiness": {
                "labelable_forecast_claim_count": 1,
                "labelable_forecast_claim_ids": ["FC-IND-001"],
            },
        },
    )
    write_json(
        tmp_path / "registry/gold_sets/tushare_research_reports.review_summary.json",
        {
            "passed": False,
            "review_complete": False,
            "reviewed_claims": 0,
            "total_documents": 0,
            "metrics": {},
        },
    )
    write_json(
        tmp_path / "registry/schemas/rke_schema_validation_report.json",
        {"accepted": False, "failure_count": 1, "records": []},
    )
    _write_jsonl(
        tmp_path / "registry/review_batches/gold_set_reviewed.jsonl",
        [
            {"claim_id": "GC-1", "target_row_hash": "sha256:" + "1" * 64},
            {"claim_id": "GC-2", "target_row_hash": "sha256:" + "2" * 64},
            {"claim_id": "GC-3", "target_row_hash": "sha256:" + "3" * 64},
        ],
    )

    result = write_report_intelligence_evolution_readiness_gate(
        registry_dir,
        run_id="RIR-TEST-GATE",
    )

    assert result["input_load_blockers"] == []
    assert result["count_only_public_fallbacks"] == ["report_outcome_labels"]
    assert set(result["blocked_check_ids"]) >= {"RI-EVOL-05", "RI-EVOL-07"}
    assert any(
        row["check_id"] == "RI-EVOL-05" for row in result["blocked_checks"]
    )
    audit_blocked_check = next(
        row for row in result["blocked_checks"] if row["check_id"] == "RI-EVOL-04"
    )
    audit_failure_summary = audit_blocked_check["current_audit_failure_summary"]
    assert audit_failure_summary["dependency_status"] == "current_gate_blocked"
    assert audit_failure_summary["blocking_components"] == ["schema"]
    assert audit_failure_summary["current_failure_counts"]["schema"] == 1
    assert audit_failure_summary["current_failure_refs"]["schema"] == []
    active_shortfalls = result["active_requirement_shortfalls"]
    assert {
        "audit_distinct_vintage_count",
        "gold_reviewed_claims",
        "gold_quality_metric_gaps",
        "markdown_coverage",
    } <= set(active_shortfalls)
    assert active_shortfalls["audit_distinct_vintage_count"]["blocker"] == (
        "audit_refresh_history_below_threshold"
    )
    assert active_shortfalls["gold_reviewed_claims"]["blocker"] == (
        "gold_reviewed_claims_below_threshold"
    )
    assert active_shortfalls["gold_quality_metric_gaps"]["blocker"] == (
        "forecast_gold_set_gate_not_passed"
    )
    assert (
        active_shortfalls["markdown_coverage"][
            "stock_outcome_120d_ready_report_count"
        ]["blocker"]
        == "stock_outcome_120d_ready_count_below_p9_target"
    )
    assert "monitor_current_global_blocker_count" not in active_shortfalls
    next_actions = {action["action_id"]: action for action in result["next_actions"]}
    assert {
        "complete_manual_forecast_gold_review",
        "complete_manual_analytical_footprint_review",
        "clear_current_schema_and_audit_blockers",
        "build_distinct_clean_audit_refresh_history",
        "expand_quality_gated_markdown_coverage",
    } <= set(next_actions)
    assert (
        "review-progress --root . --actions-only --no-write --review-kind gold_set"
        in next_actions["complete_manual_forecast_gold_review"]["commands"]["inspect"]
    )
    assert next_actions["complete_manual_forecast_gold_review"]["commands"][
        "inspect"
    ].startswith(RKE_OPERATOR_TMP_ENV_PREFIX)
    assert (
        "write-gold-review-assist --root . --review-input "
        "registry/review_batches/gold_set_reviewed.jsonl"
        in next_actions["complete_manual_forecast_gold_review"]["commands"][
            "write_assist"
        ]
    )
    assert (
        "write-gold-review-evidence --root . --limit 3 --offset 0 "
        "--review-input registry/review_batches/gold_set_reviewed.jsonl"
        in next_actions["complete_manual_forecast_gold_review"]["commands"][
            "write_evidence"
        ]
    )
    assert next_actions["complete_manual_forecast_gold_review"]["review_aids"][
        "evidence_markdown"
    ] == "registry/review_batches/gold_set_review_evidence.md"
    assert next_actions["complete_manual_forecast_gold_review"][
        "quality_gap_targets"
    ]["sample_size_claims"]["minimum_additional_count"] == 100
    assert next_actions["complete_manual_forecast_gold_review"][
        "quality_gap_targets"
    ]["sample_size_documents"]["minimum_additional_count"] == 50
    assert "manual_claim_text" in next_actions[
        "complete_manual_forecast_gold_review"
    ]["field_contract"]["required_fields"]
    assert (
        "schema-status --root . --failures-only --no-write"
        in next_actions["clear_current_schema_and_audit_blockers"]["commands"][
            "schema_failures"
        ]
    )
    assert next_actions["clear_current_schema_and_audit_blockers"]["review_aids"][
        "footprint_review"
    ]["evidence_markdown"] == (
        "registry/report_intelligence/analytical_footprint_review_evidence.md"
    )
    assert next_actions["clear_current_schema_and_audit_blockers"][
        "field_contract"
    ]["footprint_review"]["optional_fields"] == []
    assert (
        "review-progress --root . --actions-only --no-write --review-kind footprint_review"
        in next_actions["complete_manual_analytical_footprint_review"]["commands"][
            "inspect"
        ]
    )
    assert next_actions["complete_manual_analytical_footprint_review"][
        "review_aids"
    ]["fill_import_path"] == (
        "registry/report_intelligence/analytical_footprint_review_batch.jsonl"
    )
    assert "review_notes" in next_actions[
        "complete_manual_analytical_footprint_review"
    ]["field_contract"]["required_fields"]
    footprint_gap = next_actions["complete_manual_analytical_footprint_review"][
        "quality_gap_targets"
    ]["metrics"]["metric_mapping_accuracy"]
    assert footprint_gap["current_pass_count"] == 19
    assert (
        footprint_gap["minimum_additional_pass_count_if_denominator_unchanged"]
        == 9
    )
    assert (
        "apply-footprint-review --root . --input registry/report_intelligence/"
        "analytical_footprint_review_batch.jsonl --dry-run"
        in next_actions["complete_manual_analytical_footprint_review"]["commands"][
            "dry_run_current_batch"
        ]
    )
    assert (
        "data_vintage_hash"
        in next_actions["build_distinct_clean_audit_refresh_history"]["notes"][0]
    )
    gate = json.loads(
        (registry_dir / "evolution_readiness_gate.json").read_text(encoding="utf-8")
    )
    assert gate["count_only_public_fallbacks"] == ["report_outcome_labels"]
    assert "private_input_fallback_policy" in gate
    outcome_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-01"
    )
    assert outcome_check["evidence"]["unique_outcome_claim_count"] == 2
    assert outcome_check["evidence"]["stock_proxy_unique_claim_count"] == 1
    assert outcome_check["evidence"]["industry_proxy_unique_claim_count"] == 1
    markdown_check = next(
        check for check in gate["checks"] if check["check_id"] == "RI-EVOL-07"
    )
    assert markdown_check["evidence"]["stock_outcome_120d_ready_report_count"] == 0
    assert markdown_check["evidence"]["stock_outcome_age_bucket_counts"] == {}
    assert "stock_outcome_120d_ready_count_below_p9_target" in gate["blockers"]
    gate_path = registry_dir / "evolution_readiness_gate.json"
    before_no_write = gate_path.read_text(encoding="utf-8")

    no_write_result = write_report_intelligence_evolution_readiness_gate(
        registry_dir,
        run_id="RIR-NO-WRITE-GATE",
        write=False,
    )

    assert no_write_result["written"] is False
    assert set(no_write_result["blocked_check_ids"]) >= {"RI-EVOL-05", "RI-EVOL-07"}
    assert no_write_result["next_actions"] == result["next_actions"]
    assert (
        no_write_result["active_requirement_shortfalls"]
        == result["active_requirement_shortfalls"]
    )
    assert gate_path.read_text(encoding="utf-8") == before_no_write


def test_report_intelligence_evolution_gate_writer_preserves_existing_gate_without_private_outcomes(
    tmp_path: Path,
):
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True, exist_ok=True)
    existing_gate = {
        "gate_id": "RKE-REPORT-INTELLIGENCE-EVOLUTION-READINESS-GATE",
        "run_id": "RIR-EXISTING",
        "gate_status": "blocked",
        "blocker_count": 1,
        "blockers": ["manual_review_pending"],
        "checks": [
            {
                "check_id": "RI-EVOL-01",
                "passed": False,
                "requirement": "preserve existing outcome coverage evidence",
                "evidence": {
                    "forecast_claim_count": 189,
                    "unique_outcome_claim_count": 49,
                    "stock_proxy_unique_claim_count": 37,
                    "industry_proxy_unique_claim_count": 12,
                },
                "blockers": [],
            }
        ],
    }
    (registry_dir / "evolution_readiness_gate.json").write_text(
        json.dumps(existing_gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        registry_dir / "report_forecast_ledger.jsonl",
        [{"forecast_claim_id": "FC-001", "source_id": "SRC-001"}],
    )
    _write_jsonl(registry_dir / "report_outcome_labels.jsonl", [])

    result = write_report_intelligence_evolution_readiness_gate(
        registry_dir,
        run_id="RIR-EMPTY-PRIVATE-OUTCOMES",
    )

    assert result["preserved_existing_gate"] is True
    assert result["gate_status"] == "blocked"
    assert result["blocker_count"] == 1
    assert result["blockers"] == ["manual_review_pending"]
    assert result["blocked_check_ids"] == ["RI-EVOL-01"]
    assert result["active_requirement_shortfalls"] == {}
    assert "report_outcome_labels: missing_or_empty_private_input" in result[
        "input_load_blockers"
    ]
    assert json.loads(
        (registry_dir / "evolution_readiness_gate.json").read_text(encoding="utf-8")
    ) == existing_gate


def test_report_intelligence_stratified_source_selection_covers_p9_buckets(
    tmp_path: Path,
):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    def row(
        source_id: str,
        *,
        publish_date: str,
        report_type: str,
        industry: str,
        ts_code: str = "",
        institution: str = "Broker",
    ) -> dict[str, object]:
        return {
            "author": "Analyst A",
            "discovered_at": f"{publish_date}T00:00:00+00:00",
            "industry": industry,
            "institution": institution,
            "license_status": "pending_review",
            "point_in_time_available": True,
            "publish_date": publish_date,
            "query_key": industry,
            "report_type": report_type,
            "source_hash": f"sha256:{source_id}",
            "source_id": source_id,
            "source_type": "tushare_research_report",
            "title": f"{report_type} {industry}",
            "ts_code": ts_code,
            "url": f"https://example.invalid/{source_id}.pdf",
        }

    rows = [
        row(
            f"SRC-MACRO-{index}",
            publish_date=f"2026-06-0{index + 1}",
            report_type="宏观研报",
            industry="宏观",
            institution="Head Broker",
        )
        for index in range(4)
    ]
    rows.extend(
        [
            row(
                "SRC-IND-METALS",
                publish_date="2024-06-01",
                report_type="行业研报",
                industry="有色金属",
                institution="Tail Broker A",
            ),
            row(
                "SRC-STOCK-BANK",
                publish_date="2020-06-01",
                report_type="公司研报",
                industry="银行",
                ts_code="000001.SZ",
                institution="Tail Broker B",
            ),
        ]
    )
    source_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows),
        encoding="utf-8",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_path=source_path,
            limit=3,
            selection_order="stratified",
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    assert result.selected_reports == 3
    metadata = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    selected_ids = {row["source_id"] for row in metadata}
    assert selected_ids == {"SRC-MACRO-3", "SRC-IND-METALS", "SRC-STOCK-BANK"}

    coverage = json.loads(
        (
            tmp_path / "registry/report_intelligence/markdown_coverage_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert coverage["report_type_counts"] == {
        "公司研报": 1,
        "宏观研报": 1,
        "行业研报": 1,
    }
    assert coverage["time_bucket_counts"] == {
        "long_cycle_history": 1,
        "recent_1y": 1,
        "recent_3y": 1,
    }
    assert coverage["stock_report_count"] == 1
    assert coverage["industry_report_count"] == 1


def test_report_intelligence_stratified_source_selection_uses_horizon_and_evaluability_hints(
    tmp_path: Path,
):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    def row(
        source_id: str,
        *,
        publish_date: str,
        preferred_horizon_days: int,
        evaluability_bucket: str,
    ) -> dict[str, object]:
        return {
            "author": "Analyst A",
            "discovered_at": f"{publish_date}T00:00:00+00:00",
            "evaluability_bucket": evaluability_bucket,
            "industry": "银行",
            "institution": "Broker",
            "license_status": "pending_review",
            "point_in_time_available": True,
            "preferred_horizon_days": preferred_horizon_days,
            "publish_date": publish_date,
            "query_key": "银行",
            "report_type": "行业研报",
            "source_hash": f"sha256:{source_id}",
            "source_id": source_id,
            "source_type": "tushare_research_report",
            "title": f"行业研报 {source_id}",
            "url": f"https://example.invalid/{source_id}.pdf",
        }

    rows = [
        row(
            "SRC-RECENT-STANDARD",
            publish_date="2026-06-05",
            preferred_horizon_days=5,
            evaluability_bucket="standard_evaluable_candidate",
        ),
        row(
            "SRC-MID-STANDARD",
            publish_date="2026-06-04",
            preferred_horizon_days=5,
            evaluability_bucket="standard_evaluable_candidate",
        ),
        row(
            "SRC-OLDER-LONG-STOCK",
            publish_date="2026-06-03",
            preferred_horizon_days=120,
            evaluability_bucket="stock_proxy_candidate",
        ),
    ]
    source_path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in rows
        ),
        encoding="utf-8",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_path=source_path,
            limit=2,
            selection_order="stratified",
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    assert result.selected_reports == 2
    metadata = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    assert {row["source_id"] for row in metadata} == {
        "SRC-RECENT-STANDARD",
        "SRC-OLDER-LONG-STOCK",
    }


def test_report_intelligence_stratified_source_selection_covers_outcome_ready_stock(
    tmp_path: Path,
):
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    def stock_row(
        source_id: str,
        *,
        publish_date: str,
        ts_code: str,
    ) -> dict[str, object]:
        return {
            "author": "Analyst A",
            "discovered_at": f"{publish_date}T00:00:00+00:00",
            "industry": "银行",
            "institution": "Broker",
            "license_status": "pending_review",
            "point_in_time_available": True,
            "publish_date": publish_date,
            "query_key": ts_code,
            "report_type": "公司研报",
            "source_hash": f"sha256:{source_id}",
            "source_id": source_id,
            "source_type": "tushare_research_report",
            "title": f"公司研报 {ts_code}",
            "ts_code": ts_code,
            "url": f"https://example.invalid/{source_id}.pdf",
        }

    rows = [
        stock_row(
            "SRC-STOCK-RECENT-1",
            publish_date="2026-06-05",
            ts_code="000001.SZ",
        ),
        stock_row(
            "SRC-STOCK-RECENT-2",
            publish_date="2026-06-04",
            ts_code="000002.SZ",
        ),
        stock_row(
            "SRC-STOCK-OUTCOME-READY",
            publish_date="2025-01-02",
            ts_code="000003.SZ",
        ),
    ]
    source_path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in rows
        ),
        encoding="utf-8",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_path=source_path,
            limit=2,
            selection_order="stratified",
            skip_download=True,
            skip_convert=True,
            skip_llm=True,
        )
    )

    assert result.selected_reports == 2
    metadata = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    selected_ids = {row["source_id"] for row in metadata}
    assert selected_ids == {"SRC-STOCK-RECENT-1", "SRC-STOCK-OUTCOME-READY"}

    coverage = json.loads(
        (
            tmp_path / "registry/report_intelligence/markdown_coverage_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert coverage["stock_outcome_age_bucket_counts"] == {
        "stock_outcome_120d_calendar_ready": 1,
        "stock_outcome_pending": 1,
    }


def test_report_intelligence_extractor_prompt_guides_industry_proxy_fields():
    prompt = _user_prompt(
        {
            "source_id": "SRC-IND-PROMPT",
            "title": "有色金属行业深度",
            "institution": "Broker A",
            "author": "Analyst A",
            "publish_date": "2026-01-02",
            "report_type": "行业研报",
            "query_key": "有色金属",
            "industry": "有色金属",
            "ts_code": "",
        },
        "有色金属行业景气度改善，建议超配，后续有望跑赢市场。",
        "SPAN-IND-PROMPT-001",
        0,
        1,
    )

    assert "target.target_type='sector'" in prompt
    assert "metadata.industry or metadata.query_key" in prompt
    assert "target.target_id to the metadata sector string" in prompt
    assert "expects the sector to outperform" in prompt
    assert "Use neutral, ambiguous, or unknown" in prompt
    assert "Never invent a horizon" in prompt


def test_report_intelligence_counts_industry_etf_proxy_as_labelable_channel(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="有色金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业景气度改善，板块后续有望上涨。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "有色金属",
                        },
                        "benchmark": {},
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_labeling_ready_count == 0
    assert result.outcome_labeling_blocked_count == 0
    assert result.industry_etf_proxy_outcome_label_rows == 3

    forecasts = _read_jsonl(
        tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    )
    forecast_claim_id = forecasts[0]["forecast_claim_id"]
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "benchmark",
        "horizon",
    ]

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "not_ready_insufficient_mapping"

    readiness = json.loads(
        (tmp_path / "registry/report_intelligence/outcome_labeling_readiness.json")
        .read_text(encoding="utf-8")
    )
    assert readiness["ready_for_outcome_labeling_count"] == 0
    assert readiness["standard_blocked_count"] == 1
    assert readiness["standard_blocked_forecast_claim_ids"] == [forecast_claim_id]
    assert readiness["proxy_label_ready_count"] == 1
    assert readiness["proxy_label_ready_forecast_claim_ids"] == [forecast_claim_id]
    assert readiness["proxy_label_only_ready_count"] == 1
    assert readiness["proxy_label_only_ready_forecast_claim_ids"] == [
        forecast_claim_id
    ]
    assert readiness["blocked_count"] == 0
    assert readiness["blocked_forecast_claim_ids"] == []
    assert readiness["blocked_reason"] == ""
    assert readiness["mapping_gap_counts"] == {"benchmark": 1, "horizon": 1}
    assert readiness["unlabelable_mapping_gap_counts"] == {}

    provenance_audit = json.loads(
        (tmp_path / "registry/report_intelligence/extraction_provenance_audit.json")
        .read_text(encoding="utf-8")
    )
    by_id = {row["check_id"]: row for row in provenance_audit["checks"]}
    assert provenance_audit["accepted"] is True
    assert by_id["RI-PROV-04"]["accepted"] is True
    assert by_id["RI-PROV-04"]["evidence"][
        "standard_blocked_forecast_count"
    ] == 1
    assert by_id["RI-PROV-04"]["evidence"]["unlabelable_forecast_count"] == 0


def test_report_intelligence_infers_explicit_horizon_from_claim_text(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="计算机",
        report_type="行业研报",
        publish_date="2026-01-02",
    )

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "计算机行业指数预期未来6个月内优于市场指数5%以上",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "计算机行业",
                        },
                        "benchmark": {
                            "benchmark_type": "market_index",
                            "benchmark_id": "市场基准指数",
                        },
                        "direction": "positive",
                        "horizon": {},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.outcome_labeling_ready_count == 1
    assert result.outcome_labeling_blocked_count == 0
    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["forecast_testability"] == "testable"
    assert forecasts[0]["horizon"]["max_days"] == 183
    assert forecasts[0]["horizon"]["source"] == "explicit_claim_text"
    assert forecasts[0]["extraction_quality"]["horizon_inferred_from_claim_text"] is True
    assert "mapping_gaps" not in forecasts[0]["extraction_quality"]

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "ready_for_outcome_labeling"
    assert ledger[0]["forecast_family_id"].startswith("FF-")


def test_report_intelligence_infers_report_level_rating_horizon_from_markdown(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        report_type="公司研报",
        publish_date="2026-01-02",
        ts_code="000001.SZ",
    )

    def converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
        assert pdf.exists()
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(
            "\n".join(
                [
                    "# 公司深度",
                    "公司评级 买入：预期未来6个月内股价相对市场基准指数涨幅在20%以上。",
                    "受益于订单增长和费用率下降，公司盈利能力有望改善。",
                ]
            ),
            encoding="utf-8",
        )
        return {
            "status": "converted",
            "path": str(markdown),
            "bytes": markdown.stat().st_size,
            "sha256": _sha(markdown),
        }

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "维持买入评级，公司股价相对市场基准指数有望跑赢。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "investment_rating",
                        "target": {
                            "target_type": "stock",
                            "target_id": "000001.SZ",
                        },
                        "benchmark": {
                            "benchmark_type": "market_index",
                            "benchmark_id": "沪深300",
                        },
                        "direction": "positive",
                        "horizon": {},
                        "metric_proxy_mapping": ["stock_forward_return"],
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=converter,
        llm_extractor=llm,
    )

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["forecast_testability"] == "testable"
    assert forecasts[0]["horizon"]["max_days"] == 183
    assert forecasts[0]["horizon"]["source"] == "report_level_rating_definition"
    assert forecasts[0]["horizon"]["inherited_from_report_level"] is True
    assert forecasts[0]["extraction_quality"]["horizon_inferred_from_report_level"] is True
    assert "horizon_inferred_from_claim_text" not in forecasts[0]["extraction_quality"]
    assert "mapping_gaps" not in forecasts[0]["extraction_quality"]


def test_report_intelligence_derived_refresh_backfills_explicit_horizon(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="计算机",
        report_type="行业研报",
        publish_date="2026-01-02",
    )

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "计算机行业指数预期未来6个月内优于市场指数5%以上",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {
                            "target_type": "sector",
                            "target_id": "计算机行业",
                        },
                        "benchmark": {
                            "benchmark_type": "market_index",
                            "benchmark_id": "市场基准指数",
                        },
                        "direction": "positive",
                        "horizon": {"max_days": 183, "unit": "calendar_day"},
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )
    forecast_path = tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    forecasts = _read_jsonl(forecast_path)
    forecasts[0]["horizon"] = {}
    forecasts[0]["forecast_testability"] = "insufficient_mapping"
    forecasts[0]["extraction_quality"]["mapping_gaps"] = ["horizon"]
    _write_jsonl(forecast_path, forecasts)
    schema_report_path = tmp_path / "registry/schemas/rke_schema_validation_report.json"
    schema_report_path.parent.mkdir(parents=True, exist_ok=True)
    schema_report_path.write_text(
        json.dumps({"accepted": True, "failure_count": 0, "records": []}),
        encoding="utf-8",
    )
    review_summary_path = (
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_summary.json"
    )
    review_summary = json.loads(review_summary_path.read_text(encoding="utf-8"))
    review_summary.update(
        {
            "accepted": True,
            "review_complete": True,
            "quality_gate_passed": True,
            "quality_gate_blockers": [],
            "blockers": [],
            "total_rows": 1,
            "complete_rows": 1,
            "pending_rows": 0,
        }
    )
    review_summary["precision_recall_report"] = {
        "footprint_precision": 1.0,
        "span_support_precision": 1.0,
        "metric_mapping_accuracy": 1.0,
        "inferred_step_tagging_accuracy": 1.0,
        "unknown_on_ambiguity_rate": 1.0,
        "proprietary_leakage_free_rate": 1.0,
        "recall_estimate": None,
        "recall_status": "requires_human_negative_examples",
    }
    review_summary_path.write_text(
        json.dumps(review_summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    result = run_report_intelligence_derived_refresh(
        ReportIntelligenceConfig(root=tmp_path, refresh_derived_only=True)
    )

    assert result.outcome_labeling_ready_count == 1
    assert "patch_v1_5_coverage_report" in result.outputs
    assert "monitor_refresh_history" in result.outputs
    assert "audit_refresh_history" in result.outputs
    assert "gap_distribution_history" in result.outputs
    refreshed = _read_jsonl(forecast_path)
    assert refreshed[0]["forecast_testability"] == "testable"
    assert refreshed[0]["horizon"]["max_days"] == 183
    assert "mapping_gaps" not in refreshed[0]["extraction_quality"]
    refreshed_review_summary = json.loads(
        review_summary_path.read_text(encoding="utf-8")
    )
    assert refreshed_review_summary["accepted"] is True
    assert refreshed_review_summary["review_complete"] is True
    assert refreshed_review_summary["quality_gate_passed"] is True
    assert refreshed_review_summary["pending_rows"] == 0
    patch_coverage = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/patch_v1_5_coverage_report.json"
        ).read_text(encoding="utf-8")
    )
    assert patch_coverage["phase_count"] == 8
    evolution_gate = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/evolution_readiness_gate.json"
        ).read_text(encoding="utf-8")
    )
    assert str(evolution_gate["data_vintage_hash"]).startswith("sha256:")
    audit_gate = next(
        row for row in evolution_gate["checks"] if row["check_id"] == "RI-EVOL-04"
    )
    assert audit_gate["evidence"]["schema_accepted"] is True
    assert audit_gate["evidence"]["trailing_audit_pass_count"] == 1
    assert audit_gate["evidence"]["data_vintage_hash"] == evolution_gate["data_vintage_hash"]
    audit_history = _read_jsonl(
        tmp_path / "registry/report_intelligence/audit_refresh_history.jsonl"
    )
    assert audit_history[-1]["history_type"] == (
        "schema_pit_provenance_statistical_audit"
    )
    assert audit_history[-1]["schema_accepted"] is True
    assert audit_history[-1]["data_vintage_hash"] == evolution_gate["data_vintage_hash"]
    assert audit_history[-1]["private_text_included"] is False
    markdown_gate = next(
        row for row in evolution_gate["checks"] if row["check_id"] == "RI-EVOL-07"
    )
    assert "stock_outcome_120d_ready_report_count" in markdown_gate["evidence"]
    assert "stock_outcome_age_bucket_counts" in markdown_gate["evidence"]
    gap_history = _read_jsonl(
        tmp_path / "registry/report_intelligence/gap_distribution_history.jsonl"
    )
    assert gap_history[-1]["history_type"] == "mapping_gap_distribution"
    assert gap_history[-1]["data_vintage_hash"] == evolution_gate["data_vintage_hash"]
    assert gap_history[-1]["private_text_included"] is False


def test_report_intelligence_keeps_long_window_industry_etf_hits(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="有色金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_mixed_window_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业长期景气向上，板块中长期看多。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {"target_type": "sector", "target_id": "有色金属"},
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 3
    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert [row["window_role"] for row in outcome_labels] == [
        "short",
        "medium",
        "long",
    ]
    assert [row["effective_n_weight"] for row in outcome_labels] == [0.25, 0.35, 0.4]
    assert outcome_labels[0]["directional_hit"] is False
    assert outcome_labels[-1]["directional_hit"] is True
    assert outcome_labels[0]["directional_after_cost_return"] < 0
    assert outcome_labels[-1]["directional_after_cost_return"] > 0
    assert {row["performance_value_basis"] for row in outcome_labels} == {
        "directional_after_cost_return"
    }
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_industry_etf_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}

    summary = outcome_labels[0]["temporal_validation_summary"]
    assert summary["temporal_validation_bucket"] == "short_miss_long_hit"
    assert summary["miss_window_days"] == [20]
    assert summary["hit_window_days"] == [60, 120]
    assert summary["short_window_directional_hit"] is False
    assert summary["long_window_directional_hit"] is True
    assert summary["long_window_hit_retained"] is True
    assert (
        summary["window_evidence_policy"]
        == "do_not_collapse_multi_window_outcome_to_single_label"
    )

    statistical_audit = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/statistical_robustness_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert statistical_audit["accepted"] is True
    assert statistical_audit["checks"][1]["evidence"][
        "industry_etf_proxy_label_rows"
    ] == 3
    assert (
        statistical_audit["checks"][1]["evidence"]["outcome_label_source"]
        == "pit_industry_etf_price_window"
    )
    assert (
        statistical_audit["checks"][1]["evidence"]["llm_outcome_labeling_allowed"]
        is False
    )
    assert statistical_audit["checks"][3]["evidence"][
        "complete_industry_etf_window_set_count"
    ] == 1
    assert statistical_audit["checks"][6]["evidence"][
        "short_miss_long_hit_window_set_count"
    ] == 1


def test_report_intelligence_scores_bearish_industry_reports_with_etf_declines(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="有色金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_bearish_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "有色金属行业需求承压，板块中期看空。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {"target_type": "sector", "target_id": "有色金属"},
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "negative",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.industry_etf_proxy_outcome_label_rows == 3
    outcome_labels = sorted(
        _read_jsonl(tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"),
        key=lambda row: row["horizon_days"],
    )
    assert {row["direction_evaluated"] for row in outcome_labels} == {"negative"}
    assert all(row["proxy_return"] < 0 for row in outcome_labels)
    assert all(row["directional_proxy_return"] > 0 for row in outcome_labels)
    assert all(row["directional_hit"] is True for row in outcome_labels)
    assert all(row["relative_directional_hit"] is True for row in outcome_labels)
    assert {row["outcome_label_source"] for row in outcome_labels} == {
        "pit_industry_etf_price_window"
    }
    assert {row["llm_outcome_labeling_allowed"] for row in outcome_labels} == {False}
    assert outcome_labels[0]["temporal_validation_summary"][
        "temporal_validation_bucket"
    ] == "consistent_hit"


def test_report_intelligence_refresh_derived_only_rebuilds_window_labels(
    tmp_path: Path,
):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        industry="工业金属",
        report_type="行业研报",
        publish_date="2026-01-02",
    )
    qlib_etf_dir = tmp_path / "qlib_etf"
    _write_qlib_etf_fixture(qlib_etf_dir)

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "工业金属行业景气向上，后续走势看多。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "industry_outlook",
                        "target": {"target_type": "sector", "target_id": "工业金属"},
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 20,
                            "max_days": 120,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            source_ids=(source_id,),
            qlib_etf_dir=qlib_etf_dir,
        ),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )
    labels_path = tmp_path / "registry/report_intelligence/report_outcome_labels.jsonl"
    labels_path.write_text("", encoding="utf-8")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            qlib_etf_dir=qlib_etf_dir,
            refresh_derived_only=True,
        )
    )

    assert result.run_id.startswith("RIR-DERIVED-")
    assert result.selected_reports == 1
    assert result.llm_processed_reports == 1
    assert result.outcome_label_rows == 3
    assert result.industry_etf_proxy_outcome_label_rows == 3
    labels = _read_jsonl(labels_path)
    assert {row["horizon_days"] for row in labels} == {20, 60, 120}


def test_report_intelligence_performance_profiles_use_shrunk_outcomes():
    metadata_rows = [
        {
            "source_id": "SRC-1",
            "institution_id": "INST-1",
            "institution": "Broker A",
            "author_ids": ["AUTH-1"],
            "author": "Analyst A",
            "market": "CN_A_SHARE",
            "sector": "工业金属",
            "accessible_datetime": "2026-01-02T00:00:00+08:00",
        }
    ]
    forecast_rows = [
        {
            "claim_id": "CLAIM-1",
            "forecast_claim_id": "FC-1",
            "source_id": "SRC-1",
            "source_span_ids": ["SRC-1:original_markdown:chunk-001"],
            "forecast_testability": "testable",
            "forecast_type": "industry_outlook",
            "direction": "positive",
            "metric_proxy_mapping": ["inventory_to_sales"],
            "horizon": {"min_days": 20, "max_days": 60, "unit": "trading_day"},
            "failure_modes": [{"text": "库存重新累积"}],
        }
    ]
    outcome_rows = [
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-01-31",
            "directional_hit": True,
            "after_cost_alpha": 0.02,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-02-10",
            "directional_hit": True,
            "after_cost_alpha": 0.01,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-02-20",
            "directional_hit": False,
            "after_cost_alpha": -0.005,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
        {
            "forecast_claim_id": "FC-1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-03-02",
            "directional_hit": True,
            "after_cost_alpha": 0.015,
            "effective_n_weight": 1.0,
            "pit_valid": True,
            "survivorship_safe": True,
        },
    ]

    source_profiles = build_source_performance_profiles(
        metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
    )
    institution = next(row for row in source_profiles if row["entity_type"] == "institution")
    author = next(row for row in source_profiles if row["entity_type"] == "author")
    assert institution["n_nominal"] == 4
    assert institution["n_effective"] == 4.0
    assert institution["hit_rate"] == 0.75
    assert institution["mean_after_cost_alpha"] == 0.01
    assert institution["shrunk_performance_bucket"] == "positive_low_effective_n"
    assert institution["weight_multiplier"] == 1.03
    assert institution["insufficient_data"] is False
    assert institution["as_of_datetime"] == "2026-03-02T00:00:00+00:00"
    assert institution["outcome_layer_support"]["layer_count"] == 1
    assert institution["outcome_layer_support"]["layer_summaries"][0][
        "label_type"
    ] == "standard"
    assert "performance_as_of_after_outcome_exit" in institution["methodology_notes"]
    assert author["shrunk_performance_bucket"] == institution["shrunk_performance_bucket"]

    viewpoint_profiles = build_viewpoint_performance_profiles(
        forecast_rows,
        outcome_label_rows=outcome_rows,
    )
    assert len(viewpoint_profiles) == 1
    viewpoint = viewpoint_profiles[0]
    assert viewpoint["mechanism_chain"] == ["inventory_to_sales"]
    assert viewpoint["n_effective"] == 4.0
    assert viewpoint["viewpoint_weight_multiplier"] == 1.03
    assert viewpoint["known_failure_modes"] == ["库存重新累积"]
    assert viewpoint["last_revalidated_at"] == "2026-03-02T00:00:00+00:00"
    assert "research_prior_only_not_signal" in viewpoint["methodology_notes"]

    contexts = build_weighted_research_contexts(
        forecast_rows=forecast_rows,
        footprint_rows=[],
        analysis_recipe_rows=[],
        tool_gap_rows=[],
        metadata_rows=metadata_rows,
        source_performance_profile_rows=source_profiles,
        viewpoint_performance_profile_rows=viewpoint_profiles,
    )
    weighted_claim = contexts[0]["retrieved_claims"][0]
    assert weighted_claim["source_weight_multiplier"] == 1.03
    assert weighted_claim["viewpoint_weight_multiplier"] == 1.03
    assert weighted_claim["combined_research_prior_weight"] == 1.0609
    assert weighted_claim["performance_context_match"] == "source_and_viewpoint_profile_match"
    assert weighted_claim["current_data_required"] is True
    assert contexts[0]["research_only"] is True
    assert contexts[0]["actionability"] == "no_trade_without_current_data_confirmation"


def test_report_intelligence_performance_profiles_keep_outcome_layers_separate():
    metadata_rows = [
        {
            "source_id": "SRC-LAYERED",
            "institution_id": "INST-LAYERED",
            "institution": "Layered Broker",
            "author_ids": ["AUTH-LAYERED"],
            "author": "Layered Analyst",
            "sector": "有色金属",
            "accessible_datetime": "2026-01-01T00:00:00+08:00",
        }
    ]
    forecast_rows = [
        {
            "forecast_claim_id": "FC-LAYERED",
            "source_id": "SRC-LAYERED",
            "forecast_type": "stock_and_industry_outlook",
            "direction": "positive",
            "metric_proxy_mapping": ["inventory_to_sales"],
            "horizon": {"min_days": 20, "max_days": 120},
        }
    ]
    outcome_rows = [
        {
            "forecast_claim_id": "FC-LAYERED",
            "label_type": "stock_price_proxy",
            "benchmark_family": "CSI300_ETF_PROXY",
            "cost_model_id": "single_stock_round_trip_20bps_v1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-01-30",
            "directional_hit": True,
            "directional_after_cost_return": 0.02,
            "performance_value_basis": "directional_after_cost_return",
            "effective_n_weight": 0.5,
            "pit_valid": True,
        },
        {
            "forecast_claim_id": "FC-LAYERED",
            "label_type": "industry_etf_proxy",
            "benchmark_family": "CSI500_ETF_PROXY",
            "cost_model_id": "industry_etf_round_trip_10bps_v1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-02-28",
            "directional_hit": False,
            "directional_after_cost_return": -0.01,
            "performance_value_basis": "directional_after_cost_return",
            "effective_n_weight": 0.5,
            "pit_valid": True,
        },
    ]

    source_profiles = build_source_performance_profiles(
        metadata_rows,
        forecast_rows=forecast_rows,
        outcome_label_rows=outcome_rows,
    )
    institution = next(row for row in source_profiles if row["entity_type"] == "institution")
    layer_support = institution["outcome_layer_support"]
    assert layer_support["mixed_layer_profile"] is True
    assert layer_support["layer_count"] == 2
    layer_keys = {
        (
            row["label_type"],
            row["benchmark_family"],
            row["cost_model_id"],
        )
        for row in layer_support["layer_summaries"]
    }
    assert layer_keys == {
        (
            "stock_price_proxy",
            "CSI300_ETF_PROXY",
            "single_stock_round_trip_20bps_v1",
        ),
        (
            "industry_etf_proxy",
            "CSI500_ETF_PROXY",
            "industry_etf_round_trip_10bps_v1",
        ),
    }
    stock_layer = next(
        row
        for row in layer_support["layer_summaries"]
        if row["label_type"] == "stock_price_proxy"
    )
    industry_layer = next(
        row
        for row in layer_support["layer_summaries"]
        if row["label_type"] == "industry_etf_proxy"
    )
    assert stock_layer["n_effective"] == 0.5
    assert stock_layer["mean_after_cost_alpha"] == 0.02
    assert industry_layer["n_effective"] == 0.5
    assert industry_layer["mean_after_cost_alpha"] == -0.01

    viewpoint_profiles = build_viewpoint_performance_profiles(
        forecast_rows,
        outcome_label_rows=outcome_rows,
    )
    viewpoint_support = viewpoint_profiles[0]["outcome_layer_support"]
    assert viewpoint_support["mixed_layer_profile"] is True
    assert viewpoint_support["layer_count"] == 2
    assert "label_type, benchmark_family, and cost_model_id" in viewpoint_support[
        "layering_policy"
    ]


def test_report_intelligence_method_profiles_use_direct_outcome_layers():
    method_rows = [
        {
            "method_pattern_id": "METHOD-LAYERED",
            "method_name": "Layered method",
            "target_agents": ["report_intelligence.shadow"],
        },
        {
            "method_pattern_id": "METHOD-NO-EVIDENCE",
            "method_name": "No evidence method",
            "target_agents": ["report_intelligence.shadow"],
        },
    ]
    outcome_rows = [
        {
            "forecast_claim_id": "FC-METHOD-1",
            "method_pattern_id": "METHOD-LAYERED",
            "label_type": "stock_price_proxy",
            "benchmark_family": "CSI300_ETF_PROXY",
            "cost_model_id": "single_stock_round_trip_20bps_v1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-01-30",
            "directional_hit": True,
            "directional_after_cost_return": 0.03,
            "performance_value_basis": "directional_after_cost_return",
            "effective_n_weight": 1.0,
            "pit_valid": True,
        },
        {
            "forecast_claim_id": "FC-METHOD-2",
            "method_pattern_id": "METHOD-LAYERED",
            "label_type": "industry_etf_proxy",
            "benchmark_family": "CSI500_ETF_PROXY",
            "cost_model_id": "industry_etf_round_trip_10bps_v1",
            "entry_datetime": "2026-01-03",
            "exit_datetime": "2026-02-28",
            "directional_hit": True,
            "directional_after_cost_return": 0.01,
            "performance_value_basis": "directional_after_cost_return",
            "effective_n_weight": 1.0,
            "pit_valid": True,
        },
        {
            "forecast_claim_id": "FC-METHOD-PRIVATE-BAD",
            "method_pattern_id": "METHOD-LAYERED",
            "label_type": "stock_price_proxy",
            "benchmark_family": "CSI300_ETF_PROXY",
            "cost_model_id": "single_stock_round_trip_20bps_v1",
            "directional_hit": False,
            "directional_after_cost_return": -0.50,
            "effective_n_weight": 1.0,
            "pit_valid": False,
        },
    ]

    profiles = build_method_performance_profiles(
        method_rows,
        outcome_label_rows=outcome_rows,
    )
    layered = next(row for row in profiles if row["method_pattern_id"] == "METHOD-LAYERED")
    assert layered["source_support"]["n_effective_reports"] == 2.0
    assert layered["source_support"]["outcome_label_row_count"] == 2
    assert layered["after_cost_alpha_delta_bucket"] == "positive_after_cost_alpha"
    assert layered["calibration_delta_bucket"] == "positive_hit_rate"
    assert layered["shrunk_method_priority"] == "candidate_insufficient_data"
    assert layered["allowed_runtime_mode"] == "shadow_only"
    assert layered["outcome_layer_support"]["mixed_layer_profile"] is True
    assert layered["outcome_layer_support"]["layer_count"] == 2
    assert {
        (
            row["label_type"],
            row["benchmark_family"],
            row["cost_model_id"],
        )
        for row in layered["outcome_layer_support"]["layer_summaries"]
    } == {
        (
            "stock_price_proxy",
            "CSI300_ETF_PROXY",
            "single_stock_round_trip_20bps_v1",
        ),
        (
            "industry_etf_proxy",
            "CSI500_ETF_PROXY",
            "industry_etf_round_trip_10bps_v1",
        ),
    }

    no_evidence = next(
        row for row in profiles if row["method_pattern_id"] == "METHOD-NO-EVIDENCE"
    )
    assert no_evidence["source_support"]["n_effective_reports"] == 0.0
    assert no_evidence["outcome_layer_support"]["layer_count"] == 0
    assert no_evidence["insufficient_data"] is True


def test_report_intelligence_does_not_fallback_to_abstract_when_markdown_missing(
    tmp_path: Path,
):
    _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        url="",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            skip_download=True,
            skip_convert=True,
        ),
        llm_extractor=_fake_llm,
    )

    assert result.blocker_count > 0
    assert result.forecast_claim_rows == 0
    assert any("original_markdown_missing" in blocker for blocker in result.blockers)


def test_report_intelligence_converts_text_source_without_mineru(tmp_path: Path):
    source_id = _write_source(
        tmp_path / "registry/sources/tushare_research_reports.jsonl",
        url="https://example.invalid/report.txt",
    )

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,), skip_llm=True),
        downloader=_fake_text_downloader,
    )

    assert result.blocker_count == 0
    assert result.pdf_ready_count == 1
    assert result.markdown_ready_count == 1
    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    markdown = metadata[0]["markdown"]
    assert markdown["status"] == "converted_text_source"
    markdown_path = tmp_path / markdown["path"]
    assert "电子材料平台迎来结构性拐点" in markdown_path.read_text(encoding="utf-8")


def test_report_intelligence_demotes_unmapped_forecasts_and_filters_agent_ids(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "行业景气度将继续向上。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "sector_outlook",
                        "direction": "positive",
                    }
                ],
                "analytical_footprints": [
                    {
                        "topic": "invalid_agent_candidate_filter",
                        "indicator_mentions": [],
                        "analysis_patterns": [],
                        "target_agent_candidates": ["Anthropic", "macro.central_bank"],
                    }
                ],
                "metric_candidates": [
                    {
                        "canonical_name": "private_metric",
                        "target_agents": ["SpaceX", "macro.central_bank"],
                    }
                ],
                "method_patterns": [
                    {
                        "name": "private_method",
                        "target_agents": ["英伟达", "macro.central_bank"],
                    }
                ],
                "tool_gaps": [
                    {
                        "gap_type": "missing_metric",
                        "metric_name": "private_metric",
                        "target_agents": ["行业分析师", "macro.central_bank"],
                    }
                ],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.forecast_claim_rows == 1
    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "target",
        "benchmark",
        "horizon",
    ]

    ledger = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_forecast_ledger.jsonl"
    )
    assert ledger[0]["test_status"] == "not_ready_insufficient_mapping"

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    assert footprints[0]["target_agent_candidates"] == ["macro.central_bank"]
    assert footprints[0]["target_entity_candidates"] == ["Anthropic"]

    metrics = _read_jsonl(tmp_path / "registry/report_intelligence/metric_candidates.jsonl")
    assert metrics[0]["target_agents"] == ["macro.central_bank"]

    tool_gaps = _read_jsonl(tmp_path / "registry/report_intelligence/tool_gaps.jsonl")
    assert tool_gaps[0]["target_agents"] == ["macro.central_bank"]

    weighted = _read_jsonl(
        tmp_path / "registry/report_intelligence/weighted_research_contexts.jsonl"
    )
    assert [row["agent_id"] for row in weighted] == ["macro.central_bank"]


def test_report_intelligence_filters_disclaimers_and_rating_definitions_from_forecasts(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "理财产品业绩比较基准及过往业绩并不预示其未来表现，亦不构成投资建议，不代表推介。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "source_context_requires_review",
                        "target": {"target_type": "sector", "target_id": "银行理财"},
                        "direction": "neutral",
                        "metric_proxy_mapping": ["industry_etf_forward_return"],
                    },
                    {
                        "claim_text": "<table><tr><td>公司评级</td><td>行业评级</td></tr><tr><td>强烈推荐</td><td>预期未来6个月内股价相对市场基准指数升幅在15%以上</td></tr></table>",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "rating_definition",
                        "target": {"target_type": "sector", "target_id": "计算机"},
                        "direction": "positive",
                        "metric_proxy_mapping": ["industry_etf_forward_return"],
                    },
                    {
                        "claim_text": "央行流动性呵护和信用利差收敛将缓解银行理财破净压力，银行理财行业相对表现有望改善。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "sector_outlook",
                        "target": {"target_type": "sector", "target_id": "银行理财"},
                        "direction": "positive",
                        "metric_proxy_mapping": ["industry_etf_forward_return"],
                    },
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    assert result.forecast_claim_rows == 1
    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["claim_text"] == "央行流动性呵护和信用利差收敛将缓解银行理财破净压力，银行理财行业相对表现有望改善。"
    assert "不构成投资建议" not in forecasts[0]["claim_text"]
    assert "行业评级" not in forecasts[0]["claim_text"]


def test_report_intelligence_normalizes_unsupported_forecast_direction(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": "利润增速有升有降，方向混合。",
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "historical_performance",
                        "target": {
                            "target_type": "stock",
                            "target_id": "000028.SZ",
                        },
                        "direction": "mixed",
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert forecasts[0]["direction"] == "ambiguous"
    assert forecasts[0]["forecast_testability"] == "insufficient_mapping"
    assert forecasts[0]["extraction_quality"]["mapping_gaps"] == [
        "benchmark",
        "direction",
        "horizon",
    ]


def test_apply_analytical_footprint_review_import_updates_summary(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = (
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    rows = _read_jsonl(template_path)
    reviewed_rows = []
    for row in rows:
        reviewed = dict(row)
        reviewed.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": [],
                "reviewer": "footprint-reviewer",
                "review_date": "2026-06-07",
                "review_notes": "fixture approval",
            }
        )
        reviewed_rows.append(reviewed)
    import_path = tmp_path / "registry/report_intelligence/footprint_reviewed.jsonl"
    _write_jsonl(import_path, reviewed_rows)

    dry_run = apply_analytical_footprint_review_import(
        tmp_path,
        import_path,
        dry_run=True,
    )
    report_path = tmp_path / ANALYTICAL_FOOTPRINT_REVIEW_IMPORT_REPORT_PATH

    assert not report_path.exists()
    report = apply_analytical_footprint_review_import(tmp_path, import_path)

    assert dry_run.accepted
    assert dry_run.applied_rows == 0
    assert report.accepted
    assert report.applied_rows == len(reviewed_rows)
    assert report_path.exists()
    written_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert written_report["dry_run"] is False
    invalid_path = tmp_path / "registry/report_intelligence/footprint_review_invalid.jsonl"
    invalid_row = dict(reviewed_rows[0])
    invalid_row["metric_mapping_correct"] = None
    _write_jsonl(invalid_path, [invalid_row])
    failed_dry_run = apply_analytical_footprint_review_import(
        tmp_path,
        invalid_path,
        dry_run=True,
    )

    assert not failed_dry_run.accepted
    assert failed_dry_run.invalid_reason_counts[
        "metric_mapping_correct must be boolean"
    ] == 1
    assert json.loads(report_path.read_text(encoding="utf-8")) == written_report
    summary = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["accepted"] is True
    assert summary["review_complete"] is True
    assert summary["quality_gate_passed"] is True
    assert summary["quality_gate_blockers"] == []
    assert summary["pending_rows"] == 0
    assert summary["complete_rows"] == len(reviewed_rows)


def test_prepare_analytical_footprint_review_import_scaffold(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    output_path = tmp_path / "footprint_review_scaffold.jsonl"

    report = prepare_analytical_footprint_review_import(
        tmp_path,
        output_path,
        reviewer="footprint-reviewer",
        review_date="2026-06-12",
    )

    assert report.accepted
    assert report.output_rows == 1
    assert report.requested_limit is None
    assert report.requested_offset == 0
    assert report.complete_rows == 0
    assert report.pending_rows == 1
    assert report.pending_required_fields["review_notes"] == 1
    assert report.pending_required_fields["footprint_correct"] == 1
    scaffold_rows = _read_jsonl(output_path)
    assert scaffold_rows[0]["reviewer"] == "footprint-reviewer"
    assert scaffold_rows[0]["review_date"] == "2026-06-12"
    assert scaffold_rows[0]["footprint_correct"] is None
    assert scaffold_rows[0]["target_row_hash"].startswith("sha256:")
    assert "source_text" not in scaffold_rows[0]

    dry_run = apply_analytical_footprint_review_import(
        tmp_path,
        output_path,
        dry_run=True,
    )
    assert not dry_run.accepted
    assert dry_run.applied_rows == 0

    completed_rows = []
    for row in scaffold_rows:
        completed = dict(row)
        completed.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": [],
                "review_notes": "fixture approval",
            }
        )
        completed_rows.append(completed)
    _write_jsonl(output_path, completed_rows)

    apply_report = apply_analytical_footprint_review_import(
        tmp_path,
        output_path,
    )

    assert apply_report.accepted
    assert apply_report.applied_rows == 1


def test_prepare_analytical_footprint_review_import_supports_offset_batches(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    duplicate = dict(rows[0])
    duplicate["footprint_id"] = f"{rows[0]['footprint_id']}-B"
    rows.append(duplicate)
    _write_jsonl(template_path, rows)
    output_path = tmp_path / "footprint_review_scaffold_batch.jsonl"

    report = prepare_analytical_footprint_review_import(
        tmp_path,
        output_path,
        reviewer="footprint-reviewer",
        review_date="2026-06-12",
        limit=1,
        offset=1,
    )
    scaffold_rows = _read_jsonl(output_path)

    assert report.accepted
    assert report.requested_limit == 1
    assert report.requested_offset == 1
    assert report.output_rows == 1
    assert scaffold_rows[0]["footprint_id"] == duplicate["footprint_id"]
    assert scaffold_rows[0]["reviewer"] == "footprint-reviewer"
    assert scaffold_rows[0]["review_date"] == "2026-06-12"


def test_prepare_analytical_footprint_review_import_batches_pending_rows(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    duplicate = dict(rows[0])
    duplicate["footprint_id"] = f"{rows[0]['footprint_id']}-B"
    rows.append(duplicate)
    rows[0].update(
        {
            "footprint_correct": True,
            "source_span_supports_footprint": True,
            "metric_mapping_correct": True,
            "inferred_steps_tagged_correctly": True,
            "unknowns_used_when_uncertain": True,
            "no_proprietary_text_leakage": True,
            "manual_error_tags": [],
            "reviewer": "footprint-reviewer",
            "review_date": "2026-06-12",
            "review_notes": "fixture approval",
        }
    )
    _write_jsonl(template_path, rows)
    output_path = tmp_path / "footprint_review_pending_batch.jsonl"

    report = prepare_analytical_footprint_review_import(
        tmp_path,
        output_path,
        reviewer="footprint-reviewer",
        review_date="2026-06-12",
        limit=1,
        offset=0,
    )
    scaffold_rows = _read_jsonl(output_path)

    assert report.accepted
    assert report.requested_limit == 1
    assert report.requested_offset == 0
    assert report.output_rows == 1
    assert scaffold_rows[0]["footprint_id"] == duplicate["footprint_id"]
    assert scaffold_rows[0]["footprint_correct"] is None


def test_prepare_analytical_footprint_review_import_selects_quality_gap_rows(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    passed = dict(rows[0])
    passed["footprint_id"] = "FOOTPRINT-PASSED"
    failed = dict(rows[0])
    failed["footprint_id"] = "FOOTPRINT-FAILED"
    rejected = dict(rows[0])
    rejected["footprint_id"] = "FOOTPRINT-REJECTED"
    pending = dict(rows[0])
    pending["footprint_id"] = "FOOTPRINT-PENDING"
    for row in (passed, failed, rejected):
        row.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": [],
                "reviewer": "footprint-reviewer",
                "review_date": "2026-06-12",
                "review_notes": "fixture review",
            }
        )
    failed["source_span_supports_footprint"] = False
    rejected["footprint_correct"] = False
    rejected["metric_mapping_correct"] = False
    pending["footprint_correct"] = None
    _write_jsonl(template_path, [passed, failed, rejected, pending])
    output_path = tmp_path / "footprint_review_quality_gap_batch.jsonl"

    report = prepare_analytical_footprint_review_import(
        tmp_path,
        output_path,
        reviewer="footprint-reviewer",
        review_date="2026-06-18",
        limit=10,
        quality_gap_only=True,
    )
    scaffold_rows = _read_jsonl(output_path)

    assert report.accepted
    assert report.selection_policy == "quality_gap_target_order"
    assert report.output_rows == 1
    assert report.complete_rows == 1
    assert scaffold_rows[0]["footprint_id"] == "FOOTPRINT-FAILED"
    assert scaffold_rows[0]["source_span_supports_footprint"] is False


def test_prepare_analytical_footprint_review_import_priority_sorts_pending_rows(
    tmp_path: Path,
):
    template_path = (
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    low_priority = {
        "footprint_id": "FOOTPRINT-LOW",
        "target_row_hash": "sha256:" + "1" * 64,
        "source_span_ids": ["span-low"],
        "indicator_mentions_review_preview": ["营收"],
        "analysis_patterns_review_preview": ["single metric trend"],
        "target_entity_candidates": ["fixture company"],
        "target_agent_candidates": ["sector.basic_materials"],
        "footprint_correct": None,
        "source_span_supports_footprint": None,
        "metric_mapping_correct": None,
        "inferred_steps_tagged_correctly": None,
        "unknowns_used_when_uncertain": None,
        "no_proprietary_text_leakage": None,
        "reviewer": "",
        "review_date": "",
        "review_notes": "",
    }
    high_priority = {
        "footprint_id": "FOOTPRINT-HIGH",
        "target_row_hash": "sha256:" + "2" * 64,
        "source_span_ids": ["span-a", "span-b", "span-c", "span-d"],
        "indicator_mentions_review_preview": [],
        "analysis_patterns_review_preview": [
            "macro regime",
            "industry cycle",
            "earnings transmission",
        ],
        "target_entity_candidates": [],
        "target_agent_candidates": [],
        "footprint_correct": None,
        "source_span_supports_footprint": None,
        "metric_mapping_correct": None,
        "inferred_steps_tagged_correctly": None,
        "unknowns_used_when_uncertain": None,
        "no_proprietary_text_leakage": None,
        "reviewer": "",
        "review_date": "",
        "review_notes": "",
    }
    _write_jsonl(template_path, [low_priority, high_priority])

    default_output_path = tmp_path / "footprint_default_batch.jsonl"
    default_report = prepare_analytical_footprint_review_import(
        tmp_path,
        default_output_path,
        limit=1,
    )
    priority_output_path = tmp_path / "footprint_priority_batch.jsonl"
    priority_report = prepare_analytical_footprint_review_import(
        tmp_path,
        priority_output_path,
        limit=1,
        priority=True,
    )

    assert default_report.accepted
    assert default_report.priority is False
    assert default_report.selection_policy == "pending_offset"
    assert default_report.selected_priority_score_counts == {"0": 1}
    assert default_report.selected_priority_reason_counts == {}
    assert _read_jsonl(default_output_path)[0]["footprint_id"] == "FOOTPRINT-LOW"
    assert priority_report.accepted
    assert priority_report.priority is True
    assert priority_report.selection_policy == "priority_sorted_pending"
    assert priority_report.selected_priority_score_counts == {"9": 1}
    assert priority_report.selected_priority_reason_counts == {
        "complex_multi_step_patterns": 1,
        "many_source_spans": 1,
        "missing_indicator_mentions": 1,
        "missing_target_agent_candidates": 1,
        "missing_target_entity_candidates": 1,
    }
    assert _read_jsonl(priority_output_path)[0]["footprint_id"] == "FOOTPRINT-HIGH"


def test_prepare_analytical_footprint_review_import_backs_up_overwrite(
    tmp_path: Path,
):
    from mosaic.rke.temp_paths import rke_tmp_root

    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    output_path = tmp_path / "footprint_review_existing_batch.jsonl"
    output_path.write_text(
        json.dumps({"footprint_id": "OLD", "review_notes": "preserve me"})
        + "\n",
        encoding="utf-8",
    )

    report = prepare_analytical_footprint_review_import(
        tmp_path,
        output_path,
        reviewer="footprint-reviewer",
        review_date="2026-06-12",
        limit=1,
        offset=0,
        overwrite=True,
    )
    backup_path = Path(report.backup_path)

    assert report.accepted
    assert report.backed_up_existing_output is True
    assert backup_path.exists()
    assert backup_path.is_relative_to(rke_tmp_root() / "review-backups")
    assert "preserve me" in backup_path.read_text(encoding="utf-8")
    scaffold_rows = _read_jsonl(output_path)
    assert scaffold_rows[0]["footprint_id"] != "OLD"


def test_prepare_footprint_review_cli_limit_defaults_to_batch_path(
    tmp_path: Path,
    capsys,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )

    code = main(
        (
            "prepare-footprint-review",
            "--root",
            str(tmp_path),
            "--limit",
            "1",
            "--offset",
            "0",
            "--priority",
            "--reviewer",
            "footprint-reviewer",
            "--review-date",
            "2026-06-12",
        )
    )
    output = json.loads(capsys.readouterr().out)
    batch_path = tmp_path / ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH

    assert code == 0
    assert output["output_path"] == str(batch_path)
    assert output["requested_limit"] == 1
    assert output["requested_offset"] == 0
    assert output["priority"] is True
    assert output["selection_policy"] == "priority_sorted_pending"
    assert output["output_rows"] == 1
    assert batch_path.exists()
    assert not (tmp_path / ANALYTICAL_FOOTPRINT_REVIEWED_IMPORT_PATH).exists()


def test_write_analytical_footprint_review_assist_is_private_not_import(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )

    report = write_analytical_footprint_review_assist(tmp_path)

    assert report.row_count == 1
    assert report.pending_rows == 1
    assert report.blockers == ()
    assert report.selection_source == "pending_template"
    assert report.review_input_path == ""
    assert report.jsonl_path == ANALYTICAL_FOOTPRINT_REVIEW_ASSIST_JSONL_PATH
    assert report.markdown_path == ANALYTICAL_FOOTPRINT_REVIEW_WORKBOOK_MD_PATH
    assert report.jsonl_path in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS
    assert report.markdown_path in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS
    assert report.jsonl_path in PRIVATE_LOCAL_REGISTRY_FILES
    assert report.markdown_path in PRIVATE_LOCAL_REGISTRY_FILES

    assist_rows = _read_jsonl(tmp_path / report.jsonl_path)
    assert assist_rows[0]["not_apply_footprint_review_input"] is True
    assert assist_rows[0]["human_review_required"] is True
    assert "reviewed_import_path" in assist_rows[0]
    assert "source_text" not in assist_rows[0]
    assert "source_span_ids" not in assist_rows[0]
    markdown = (tmp_path / report.markdown_path).read_text(encoding="utf-8")
    assert "RKE Analytical Footprint Review Workbook" in markdown
    assert "not an import file" in markdown


def test_analytical_footprint_review_assist_can_follow_review_input_batch(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    duplicate = dict(rows[0])
    duplicate["footprint_id"] = f"{rows[0]['footprint_id']}-B"
    rows.append(duplicate)
    _write_jsonl(template_path, rows)
    review_input_path = tmp_path / ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
    review_input_path.parent.mkdir(parents=True, exist_ok=True)
    review_input_rows = [rows[1], rows[0]]
    _write_jsonl(review_input_path, review_input_rows)

    report = write_analytical_footprint_review_assist(
        tmp_path,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    )
    assist_rows = _read_jsonl(tmp_path / report.jsonl_path)

    assert report.row_count == 2
    assert report.pending_rows == 2
    assert report.selection_source == "review_input"
    assert report.review_input_path == ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
    assert [row["footprint_id"] for row in assist_rows] == [
        row["footprint_id"] for row in review_input_rows
    ]
    assert [row["target_row_hash"] for row in assist_rows] == [
        row["target_row_hash"] for row in review_input_rows
    ]
    markdown = (tmp_path / report.markdown_path).read_text(encoding="utf-8")
    assert "Selection source: `review_input`" in markdown


def test_write_analytical_footprint_review_evidence_is_private_not_import(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)

    assert report.row_count == 1
    assert report.evidence_rows == 1
    assert report.blockers == ()
    assert report.jsonl_path == ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_JSONL_PATH
    assert report.markdown_path == ANALYTICAL_FOOTPRINT_REVIEW_EVIDENCE_MD_PATH
    assert report.jsonl_path in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS
    assert report.markdown_path in REPORT_INTELLIGENCE_PRIVATE_OUTPUT_PATHS
    assert report.jsonl_path in PRIVATE_LOCAL_REGISTRY_FILES
    assert report.markdown_path in PRIVATE_LOCAL_REGISTRY_FILES

    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)
    expected_score_counts = {str(evidence_rows[0]["priority_score"]): 1}
    expected_reason_counts = {
        str(reason): evidence_rows[0]["priority_reasons"].count(reason)
        for reason in evidence_rows[0]["priority_reasons"]
    }
    assert report.selected_priority_score_counts == expected_score_counts
    assert report.selected_priority_reason_counts == expected_reason_counts
    assert evidence_rows[0]["not_apply_footprint_review_input"] is True
    assert evidence_rows[0]["human_review_required"] is True
    assert evidence_rows[0]["evidence_kind"].endswith("_not_import")
    assert isinstance(evidence_rows[0]["priority_reasons"], list)
    assert evidence_rows[0]["suggested_review_rationales"]
    assert isinstance(
        evidence_rows[0]["suggested_review_decision"]["metric_mapping_correct"],
        bool,
    )
    assert evidence_rows[0]["evidence_snippets"]
    assert "source_span_ids" not in evidence_rows[0]
    markdown = (tmp_path / report.markdown_path).read_text(encoding="utf-8")
    assert "RKE Analytical Footprint Review Evidence Draft" in markdown
    assert "Priority reasons" in markdown
    assert "## Batch Triage Summary" in markdown
    assert "Suggested tag counts" in markdown
    assert "Sector counts" in markdown
    assert "Suggested decision counts" in markdown
    assert "## Quick Fill Checklist" in markdown
    assert "| # | footprint_id | sector | topic | footprint | span | metric | steps | unknowns | leakage | focus | tags |" in markdown
    assert "| 1 | `" in markdown
    assert "Suggested decision rationales" in markdown
    assert "not an import file" in markdown
    assert "Confirm each field against the evidence snippets" in markdown


def test_analytical_footprint_review_evidence_falls_back_to_cached_markdown(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    _write_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl",
        [{"source_id": "SRC-UNRELATED"}],
    )

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)
    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)

    assert report.row_count == 1
    assert report.evidence_rows == 1
    assert report.missing_markdown_rows == 0
    assert evidence_rows[0]["markdown_exists"] is True
    assert "markdown_missing" not in evidence_rows[0]["suggested_manual_error_tags"]
    assert evidence_rows[0]["evidence_snippets"]


def test_analytical_footprint_review_evidence_flags_risk_warning_footprints(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    rows[0]["topic_preview"] = "风险提示"
    rows[0]["analysis_patterns_review_preview"] = ["风险因素列举"]
    rows[0]["indicator_mentions_review_preview"] = []
    rows[0]["target_entity_candidates"] = ["风险管理师", "投资者"]
    _write_jsonl(template_path, rows)

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)
    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)
    decision = evidence_rows[0]["suggested_review_decision"]

    assert "boilerplate_risk_warning_footprint" in evidence_rows[0][
        "suggested_manual_error_tags"
    ]
    assert decision["footprint_correct"] is False
    assert decision["metric_mapping_correct"] is False
    assert decision["inferred_steps_tagged_correctly"] is False
    assert any(
        item["field"] == "footprint_correct"
        and item["suggested_value"] is False
        and "risk-warning" in item["reason"]
        for item in evidence_rows[0]["suggested_review_rationales"]
    )


def test_analytical_footprint_review_evidence_suggests_missing_metric_mapping(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    rows[0]["topic_preview"] = "Company Financial Forecasting"
    rows[0]["analysis_patterns_review_preview"] = [
        "earnings_forecast",
        "valuation_multiple_analysis",
    ]
    rows[0]["indicator_mentions_review_preview"] = []
    rows[0]["indicator_mentions_review_summary"] = {
        "mention_count": 0,
        "preview_count": 0,
        "preview_limit": 5,
        "hidden_count": 0,
        "unknown_canonical_count": 0,
        "ungrounded_count": 0,
        "complete_source_grounded_count": 0,
        "hidden_unknown_canonical_count": 0,
        "hidden_ungrounded_count": 0,
        "mapping_complete": False,
    }
    _write_jsonl(template_path, rows)

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)
    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)
    row = evidence_rows[0]

    assert row["suggested_review_decision"]["footprint_correct"] is False
    assert row["suggested_review_decision"]["source_span_supports_footprint"] is False
    assert row["suggested_review_decision"]["metric_mapping_correct"] is False
    assert row["suggested_review_decision"]["inferred_steps_tagged_correctly"] is False
    assert "missing_indicator_mentions" in row["priority_reasons"]
    assert "low_information_footprint" in row["suggested_manual_error_tags"]
    assert "metric_mapping_missing" in row["suggested_manual_error_tags"]
    assert "metric_mapping_inference_available" in row["suggested_manual_error_tags"]
    assert row["inferred_indicator_suggestions"]
    suggestion = row["inferred_indicator_suggestions"][0]
    assert suggestion["canonical_metric_candidate"] == "forecast_net_profit"
    assert suggestion["source_grounded"] is False
    assert suggestion["inference_source"] == "review_evidence_context_rule"
    assert any(
        item["field"] == "metric_mapping_correct"
        and "review aids" in item["reason"]
        for item in row["suggested_review_rationales"]
    )
    markdown = (tmp_path / report.markdown_path).read_text(encoding="utf-8")
    assert "Suggested indicator mapping candidates" in markdown
    assert "forecast_net_profit" in markdown
    assert "Suggested indicator candidate source counts" in markdown
    assert "Suggested indicator candidate canonical counts" in markdown


def test_analytical_footprint_review_evidence_flags_unknown_metric_mapping(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    rows[0]["topic_preview"] = "Financial Projections"
    rows[0]["analysis_patterns_review_preview"] = ["earnings_estimation"]
    rows[0]["indicator_mentions_review_preview"] = [
        {
            "indicator_text": "revenue_forecast",
            "canonical_metric_candidate": "unknown",
            "data_source_mentioned": "unknown",
            "frequency": "unknown",
            "transformation": "unknown",
            "source_grounded": False,
        },
        {
            "indicator_text": "net_profit_forecast",
            "canonical_metric_candidate": "forecast_net_profit",
            "data_source_mentioned": "report_financial_forecast",
            "frequency": "annual",
            "transformation": "extract_forecast",
            "source_grounded": True,
        },
    ]
    rows[0]["indicator_mentions_review_summary"] = {
        "mention_count": 2,
        "preview_count": 2,
        "preview_limit": 5,
        "hidden_count": 0,
        "unknown_canonical_count": 1,
        "ungrounded_count": 1,
        "complete_source_grounded_count": 1,
        "hidden_unknown_canonical_count": 0,
        "hidden_ungrounded_count": 0,
        "mapping_complete": False,
    }
    _write_jsonl(template_path, rows)

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)
    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)
    row = evidence_rows[0]

    assert row["suggested_review_decision"]["metric_mapping_correct"] is False
    assert row["suggested_review_decision"]["unknowns_used_when_uncertain"] is False
    assert "metric_mapping_correct" in row["quality_gap_focus_fields"]
    assert "unknowns_used_when_uncertain" in row["quality_gap_focus_fields"]
    assert "metric_mapping_unknown" in row["suggested_manual_error_tags"]
    assert "metric_mapping_ungrounded" in row["suggested_manual_error_tags"]
    assert "metric_mapping_missing" not in row["suggested_manual_error_tags"]
    assert row["inferred_indicator_suggestions"]
    repair_suggestion = row["inferred_indicator_suggestions"][0]
    assert repair_suggestion["indicator_text"] == "revenue_forecast"
    assert repair_suggestion["canonical_metric_candidate"] == "revenue_growth"
    assert repair_suggestion["source_grounded"] is False
    assert (
        repair_suggestion["inference_source"]
        == "review_evidence_indicator_alias_rule"
    )
    assert repair_suggestion["original_canonical_metric_candidate"] == "unknown"
    rationale = next(
        item
        for item in row["suggested_review_rationales"]
        if item["field"] == "metric_mapping_correct"
    )
    assert rationale["suggested_value"] is False
    assert rationale["diagnostics"] == {
        "complete_source_grounded_count": 1,
        "diagnostic_source": "indicator_mentions_review_summary",
        "hidden_count": 0,
        "hidden_ungrounded_count": 0,
        "hidden_unknown_canonical_count": 0,
        "mapping_complete": False,
        "mention_count": 2,
        "preview_count": 2,
        "preview_limit": 5,
        "ungrounded_count": 1,
        "unknown_canonical_count": 1,
    }
    unknown_rationale = next(
        item
        for item in row["suggested_review_rationales"]
        if item["field"] == "unknowns_used_when_uncertain"
    )
    assert unknown_rationale["suggested_value"] is False
    assert "repairable by governed alias rules" in unknown_rationale["reason"]
    markdown = (tmp_path / report.markdown_path).read_text(encoding="utf-8")
    assert "Indicator mapping summary" in markdown
    assert "Quality-gap focus field counts" in markdown
    assert "metric_mapping_correct" in markdown
    assert "Suggested indicator candidate source counts" in markdown
    assert "review_evidence_indicator_alias_rule" in markdown
    assert "revenue_growth" in markdown


def test_analytical_footprint_review_evidence_flags_hidden_metric_mapping_gaps(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    rows[0]["topic_preview"] = "Financial Indicator Monitoring"
    rows[0]["analysis_patterns_review_preview"] = ["metric_tracking"]
    rows[0]["indicator_mentions_review_preview"] = [
        {
            "indicator_text": f"metric_{index}",
            "canonical_metric_candidate": "forecast_net_profit",
            "data_source_mentioned": "report_financial_forecast",
            "frequency": "annual",
            "transformation": "extract_forecast",
            "source_grounded": True,
        }
        for index in range(5)
    ]
    rows[0]["indicator_mentions_review_summary"] = {
        "mention_count": 6,
        "preview_count": 5,
        "preview_limit": 5,
        "hidden_count": 1,
        "unknown_canonical_count": 1,
        "ungrounded_count": 1,
        "complete_source_grounded_count": 5,
        "hidden_unknown_canonical_count": 1,
        "hidden_ungrounded_count": 1,
        "mapping_complete": False,
    }
    _write_jsonl(template_path, rows)

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)
    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)
    row = evidence_rows[0]

    assert row["suggested_review_decision"]["metric_mapping_correct"] is False
    assert "metric_mapping_correct" in row["quality_gap_focus_fields"]
    assert "unknowns_used_when_uncertain" in row["quality_gap_focus_fields"]
    assert "metric_mapping_hidden_unknown" in row["suggested_manual_error_tags"]
    assert "metric_mapping_hidden_ungrounded" in row["suggested_manual_error_tags"]
    rationale = next(
        item
        for item in row["suggested_review_rationales"]
        if item["field"] == "metric_mapping_correct"
    )
    assert rationale["diagnostics"]["diagnostic_source"] == (
        "indicator_mentions_review_summary"
    )
    assert rationale["diagnostics"]["hidden_unknown_canonical_count"] == 1
    assert rationale["diagnostics"]["hidden_ungrounded_count"] == 1


def test_analytical_footprint_review_evidence_backfills_missing_indicator_summary(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    rows[0]["topic_preview"] = "Legacy Footprint Batch"
    rows[0]["analysis_patterns_review_preview"] = ["valuation tracking"]
    rows[0]["indicator_mentions_review_preview"] = [
        {
            "indicator_text": "valuation_multiple",
            "canonical_metric_candidate": "valuation_multiple",
            "data_source_mentioned": "market_valuation_data_or_report_forecast",
            "frequency": "daily_or_point_in_time",
            "transformation": "valuation_ratio",
            "source_grounded": True,
        },
        {
            "indicator_text": "unmapped_metric",
            "canonical_metric_candidate": "unknown",
            "data_source_mentioned": "unknown",
            "frequency": "unknown",
            "transformation": "unknown",
            "source_grounded": False,
        },
    ]
    rows[0].pop("indicator_mentions_review_summary", None)
    _write_jsonl(template_path, rows)

    report = write_analytical_footprint_review_evidence(tmp_path, limit=1)
    evidence_rows = _read_jsonl(tmp_path / report.jsonl_path)
    row = evidence_rows[0]

    assert row["indicator_mentions_summary"] == {
        "complete_source_grounded_count": 1,
        "hidden_count": 0,
        "hidden_ungrounded_count": 0,
        "hidden_unknown_canonical_count": 0,
        "mapping_complete": False,
        "mention_count": 2,
        "preview_count": 2,
        "preview_limit": 5,
        "summary_source": "indicator_mentions_review_preview",
        "ungrounded_count": 1,
        "unknown_canonical_count": 1,
    }
    rationale = next(
        item
        for item in row["suggested_review_rationales"]
        if item["field"] == "metric_mapping_correct"
    )
    assert rationale["diagnostics"]["diagnostic_source"] == (
        "indicator_mentions_review_preview"
    )
    markdown = (tmp_path / report.markdown_path).read_text(encoding="utf-8")
    assert "Indicator mapping summary" in markdown
    assert "indicator_mentions_review_preview" in markdown


def test_analytical_footprint_review_evidence_supports_offset_batches(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    duplicate = dict(rows[0])
    duplicate["footprint_id"] = f"{rows[0]['footprint_id']}-B"
    rows.append(duplicate)
    _write_jsonl(template_path, rows)

    first_report, first_rows = build_analytical_footprint_review_evidence(
        tmp_path,
        limit=1,
        offset=0,
    )
    second_report, second_rows = build_analytical_footprint_review_evidence(
        tmp_path,
        limit=1,
        offset=1,
    )
    written_report = write_analytical_footprint_review_evidence(
        tmp_path,
        limit=1,
        offset=1,
    )

    assert first_report.requested_offset == 0
    assert second_report.requested_offset == 1
    assert written_report.requested_offset == 1
    assert len(first_rows) == 1
    assert len(second_rows) == 1
    assert first_rows[0]["footprint_id"] != second_rows[0]["footprint_id"]


def test_analytical_footprint_review_evidence_can_follow_review_input_batch(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    template_path = tmp_path / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    rows = _read_jsonl(template_path)
    duplicate = dict(rows[0])
    duplicate["footprint_id"] = f"{rows[0]['footprint_id']}-B"
    rows.append(duplicate)
    _write_jsonl(template_path, rows)
    review_input_path = tmp_path / ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
    review_input_path.parent.mkdir(parents=True, exist_ok=True)
    review_input_rows = [rows[1], rows[0]]
    _write_jsonl(review_input_path, review_input_rows)

    summary, evidence_rows = build_analytical_footprint_review_evidence(
        tmp_path,
        limit=1,
        offset=99,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    )
    written_report = write_analytical_footprint_review_evidence(
        tmp_path,
        limit=1,
        offset=99,
        review_input_path=ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH,
    )

    assert summary.selection_source == "review_input"
    assert summary.review_input_path == ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
    assert written_report.selection_source == "review_input"
    assert written_report.review_input_path == ANALYTICAL_FOOTPRINT_REVIEW_BATCH_IMPORT_PATH
    assert [row["footprint_id"] for row in evidence_rows] == [
        row["footprint_id"] for row in review_input_rows
    ]
    assert [row["target_row_hash"] for row in evidence_rows] == [
        row["target_row_hash"] for row in review_input_rows
    ]


def test_analytical_footprint_review_summary_requires_quality_thresholds(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    rows = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )
    reviewed_rows = []
    for row in rows:
        reviewed = dict(row)
        reviewed.update(
            {
                "footprint_correct": True,
                "source_span_supports_footprint": True,
                "metric_mapping_correct": False,
                "inferred_steps_tagged_correctly": True,
                "unknowns_used_when_uncertain": True,
                "no_proprietary_text_leakage": True,
                "manual_error_tags": ["metric_mapping_error"],
                "reviewer": "footprint-reviewer",
                "review_date": "2026-06-07",
                "review_notes": "fixture low quality",
            }
        )
        reviewed_rows.append(reviewed)
    import_path = tmp_path / "registry/report_intelligence/footprint_reviewed.jsonl"
    _write_jsonl(import_path, reviewed_rows)

    report = apply_analytical_footprint_review_import(tmp_path, import_path)

    assert report.accepted
    summary = json.loads(
        (
            tmp_path
            / "registry/report_intelligence/analytical_footprint_review_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["review_complete"] is True
    assert summary["accepted"] is False
    assert summary["quality_gate_passed"] is False
    assert any(
        "metric_mapping_accuracy" in blocker
        for blocker in summary["quality_gate_blockers"]
    )
    metric_gap = summary["quality_gap_targets"]["metrics"]["metric_mapping_accuracy"]
    assert metric_gap["current_pass_count"] == 0
    assert (
        metric_gap["minimum_additional_pass_count_if_denominator_unchanged"]
        == metric_gap["required_pass_count"]
    )

    assist_report = write_analytical_footprint_review_assist(tmp_path)
    markdown = (tmp_path / assist_report.markdown_path).read_text(encoding="utf-8")
    evidence_report = write_analytical_footprint_review_evidence(tmp_path)
    evidence_markdown = (tmp_path / evidence_report.markdown_path).read_text(
        encoding="utf-8"
    )

    assert assist_report.quality_gap_targets is not None
    assert "## Quality Gate Gap Targets" in markdown
    assert evidence_report.quality_gap_targets is not None
    assert (
        evidence_report.quality_gap_targets["metrics"]["metric_mapping_accuracy"][
            "minimum_additional_pass_count_if_denominator_unchanged"
        ]
        == metric_gap["minimum_additional_pass_count_if_denominator_unchanged"]
    )
    assert "## Quality Gate Gap Targets" in evidence_markdown


def test_analytical_footprint_review_summary_maps_only_accepted_footprints():
    base = {
        "source_span_supports_footprint": True,
        "unknowns_used_when_uncertain": True,
        "no_proprietary_text_leakage": True,
        "reviewer": "footprint-reviewer",
        "review_date": "2026-06-19",
        "review_notes": "fixture",
    }
    summary = build_analytical_footprint_review_summary(
        [
            {
                **base,
                "footprint_correct": True,
                "metric_mapping_correct": True,
                "inferred_steps_tagged_correctly": True,
            },
            {
                **base,
                "footprint_correct": False,
                "metric_mapping_correct": False,
                "inferred_steps_tagged_correctly": False,
            },
        ]
    )

    metric = summary["quality_gap_targets"]["metrics"]["metric_mapping_accuracy"]
    assert summary["precision_recall_report"]["footprint_precision"] == 0.5
    assert summary["precision_recall_report"]["metric_mapping_accuracy"] == 1.0
    assert metric["denominator"] == 1
    assert metric["denominator_policy"] == "footprint_correct_true_rows"


def test_apply_analytical_footprint_review_import_rejects_stale_or_leaky_rows(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=_fake_llm,
    )
    row = _read_jsonl(
        tmp_path
        / "registry/report_intelligence/analytical_footprint_review_template.jsonl"
    )[0]
    row.update(
        {
            "footprint_correct": True,
            "source_span_supports_footprint": True,
            "metric_mapping_correct": True,
            "inferred_steps_tagged_correctly": True,
            "unknowns_used_when_uncertain": True,
            "no_proprietary_text_leakage": False,
            "manual_error_tags": ["proprietary_text_leakage"],
            "reviewer": "footprint-reviewer",
            "review_date": "2026-06-07",
            "review_notes": "fixture rejection",
            "claim_text": "claim prose must not enter footprint review import",
            "pdf_path": "registry/report_intelligence/pdfs/private.pdf",
            "source_text": "full source text must not enter review import",
            "target_row_hash": "sha256:stale",
        }
    )
    import_path = tmp_path / "registry/report_intelligence/footprint_reviewed.jsonl"
    _write_jsonl(import_path, [row])

    report = apply_analytical_footprint_review_import(tmp_path, import_path)
    reasons = " ".join(
        reason for invalid in report.invalid_rows for reason in invalid.reasons
    )

    assert not report.accepted
    assert "target_row_hash does not match target review row" in reasons
    assert "claim_text forbidden in analytical footprint review import" in reasons
    assert "pdf_path forbidden in analytical footprint review import" in reasons
    assert "source_text forbidden in analytical footprint review import" in reasons
    assert report.applied_rows == 0


def test_report_intelligence_structures_string_indicator_mentions(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [
                    {
                        "topic": "string_indicator_mention",
                        "indicator_mentions": ["DR007与政策利率利差"],
                        "analysis_patterns": [],
                        "target_agent_candidates": ["macro.central_bank"],
                    }
                ],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    mention = footprints[0]["indicator_mentions"][0]
    assert mention == {
        "canonical_metric_candidate": "dr007_policy_rate_spread",
        "data_source_mentioned": "interbank_repo_rate_and_policy_rate",
        "frequency": "daily",
        "indicator_text": "DR007与政策利率利差",
        "lookback_window": {},
        "role_in_argument": "funding_stress_proxy",
        "source_grounded": True,
        "transformation": "spread",
    }


def test_report_intelligence_structures_common_report_indicator_aliases(
    tmp_path: Path,
):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [],
                "analytical_footprints": [
                    {
                        "topic": "common_indicator_aliases",
                        "indicator_mentions": [
                            "computer_sector_return",
                            "hs300_return",
                            "relative_performance",
                            "pe_ratio",
                            "ev_ebitda",
                            "operating_cash_flow",
                            "自发自用比例",
                            "Semaglutide discontinuation rate due to AEs (4.1%)",
                            "Number of companies applying for listing",
                        ],
                        "analysis_patterns": [],
                        "target_agent_candidates": ["analyst"],
                    }
                ],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    footprints = _read_jsonl(
        tmp_path / "registry/report_intelligence/analytical_footprints.jsonl"
    )
    mentions = {
        mention["indicator_text"]: mention
        for mention in footprints[0]["indicator_mentions"]
    }

    assert mentions["computer_sector_return"]["canonical_metric_candidate"] == (
        "market_or_sector_index_return"
    )
    assert mentions["hs300_return"]["canonical_metric_candidate"] == (
        "market_or_sector_index_return"
    )
    assert mentions["relative_performance"]["canonical_metric_candidate"] == (
        "market_or_sector_index_return"
    )
    assert mentions["pe_ratio"]["canonical_metric_candidate"] == "valuation_multiple"
    assert mentions["ev_ebitda"]["canonical_metric_candidate"] == "valuation_multiple"
    assert mentions["operating_cash_flow"]["canonical_metric_candidate"] == (
        "operating_cash_flow"
    )
    assert mentions["自发自用比例"]["canonical_metric_candidate"] == (
        "policy_parameter_constraint"
    )
    assert mentions[
        "Semaglutide discontinuation rate due to AEs (4.1%)"
    ]["canonical_metric_candidate"] == "adverse_event_discontinuation_rate"
    assert mentions["Number of companies applying for listing"][
        "canonical_metric_candidate"
    ] == "clinical_trial_milestone_status"
    assert all(mention["source_grounded"] is True for mention in mentions.values())


def test_report_intelligence_bounds_stored_claim_text(tmp_path: Path):
    source_id = _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    long_claim_text = (
        "公开市场净投放连续改善并且DR007相对政策利率回落时，"
        "高beta风格相对沪深300在未来二十个交易日可能显著占优，"
        "但若资金面重新收紧则该判断需要下调。"
    ) * 8

    def llm(row, chunk: str, span_id: str, chunk_index: int, chunk_count: int):
        return {
            "status": "ok",
            "model": "fake-vllm",
            "payload": {
                "forecast_claims": [
                    {
                        "claim_text": long_claim_text,
                        "claim_provenance": "source_grounded",
                        "forecast_testability": "testable",
                        "forecast_type": "macro_regime_to_style_relative_direction",
                        "target": {
                            "target_type": "style_index",
                            "target_id": "CN_A_SHARE_HIGH_BETA",
                        },
                        "benchmark": {
                            "benchmark_type": "broad_index",
                            "benchmark_id": "CSI300",
                        },
                        "direction": "positive",
                        "horizon": {
                            "min_days": 5,
                            "max_days": 20,
                            "unit": "trading_day",
                        },
                    }
                ],
                "analytical_footprints": [],
                "metric_candidates": [],
                "method_patterns": [],
                "tool_gaps": [],
            },
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, source_ids=(source_id,)),
        downloader=_fake_downloader,
        converter=_fake_converter,
        llm_extractor=llm,
    )

    forecasts = _read_jsonl(tmp_path / "registry/report_intelligence/forecast_claims.jsonl")
    assert len(forecasts[0]["claim_text"]) <= MAX_STORED_CLAIM_TEXT_CHARS
    assert forecasts[0]["claim_text"].endswith("...")
    assert forecasts[0]["extraction_quality"]["claim_text_truncated_for_redaction"] is True
    assert long_claim_text not in forecasts[0]["claim_text"]


def test_report_intelligence_reports_missing_mineru_command(tmp_path: Path):
    _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    result = run_report_intelligence_refresh(
        ReportIntelligenceConfig(
            root=tmp_path,
            skip_llm=True,
            mineru_command="definitely-not-a-mineru-command",
        ),
        downloader=_fake_downloader,
    )

    assert result.blocker_count == 1
    assert "mineru_command_not_found" in result.blockers[0]
    status = _read_jsonl(tmp_path / "registry/report_intelligence/processing_status.jsonl")
    assert status[0]["markdown_status"] == "blocked"


def test_report_intelligence_redacts_runtime_log_fields(tmp_path: Path):
    _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")
    api_key = "sk-" + "abc123456789012345"
    provider_key = "tp-" + "abc123456789012345"
    token_name = "TUSHARE_" + "TOKEN"
    token_value = "abcdef123456"

    def converter(pdf: Path, output_dir: Path, markdown: Path, overwrite: bool):
        return {
            "status": "blocked",
            "blocker": "mineru_failed",
            "command": f"mineru -p {tmp_path}/secret.pdf --key={api_key}",
            "stderr_tail": f"failed in {tmp_path}; {token_name}={token_value}",
            "stdout_tail": f"provider key:{provider_key}",
        }

    run_report_intelligence_refresh(
        ReportIntelligenceConfig(root=tmp_path, skip_llm=True),
        downloader=_fake_downloader,
        converter=converter,
    )

    metadata = _read_jsonl(tmp_path / "registry/report_intelligence/report_metadata.jsonl")
    status = _read_jsonl(tmp_path / "registry/report_intelligence/processing_status.jsonl")
    markdown = metadata[0]["markdown"]
    assert str(tmp_path) not in markdown["command"]
    assert str(tmp_path) not in markdown["stderr_tail"]
    assert api_key not in markdown["command"]
    assert token_value not in markdown["stderr_tail"]
    assert provider_key not in markdown["stdout_tail"]
    assert str(tmp_path) not in status[0]["markdown_stderr_tail"]


def test_report_intelligence_cli_can_write_status_without_network(
    tmp_path: Path,
    capsys,
):
    _write_source(tmp_path / "registry/sources/tushare_research_reports.jsonl")

    code = main(
        (
            "report-intelligence",
            "--root",
            str(tmp_path),
            "--limit",
            "1",
            "--skip-download",
            "--skip-convert",
            "--skip-llm",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["selected_reports"] == 1
    assert output["blocker_count"] == 0
    assert (tmp_path / "registry/report_intelligence/extraction_report.json").exists()


def test_report_intelligence_tool_coverage_classifier():
    assert classify_tool_coverage("pboc_net_injection_7d")["coverage_status"] == "exact_match"
    assert classify_tool_coverage("dr007_policy_rate_spread")["coverage_status"] == "partial_match"
    fundamentals = classify_tool_coverage("forecast_net_profit")
    assert fundamentals["coverage_status"] == "exact_match"
    assert fundamentals["existing_tool_ids"] == ["tool.get_fundamentals"]
    balance_sheet = classify_tool_coverage("资产负债率")
    assert balance_sheet["coverage_status"] == "exact_match"
    assert balance_sheet["existing_tool_ids"] == ["tool.get_balance_sheet"]
    cashflow = classify_tool_coverage("经营活动现金流净额")
    assert cashflow["coverage_status"] == "exact_match"
    assert cashflow["existing_tool_ids"] == ["tool.get_cashflow"]
    price_proxy = classify_tool_coverage("stock_price_relative_alpha")
    assert price_proxy["coverage_status"] == "exact_match"
    assert price_proxy["existing_tool_ids"] == ["market.price_proxy"]
    sector_proxy = classify_tool_coverage("sector_relative_performance")
    assert sector_proxy["coverage_status"] == "exact_match"
    assert sector_proxy["existing_tool_ids"] == ["market.price_proxy"]
    index_proxy = classify_tool_coverage("collect_sector_index_data")
    assert index_proxy["coverage_status"] == "exact_match"
    assert index_proxy["existing_tool_ids"] == ["market.price_proxy"]
    relative_return_proxy = classify_tool_coverage("calculate_relative_return")
    assert relative_return_proxy["coverage_status"] == "exact_match"
    assert relative_return_proxy["existing_tool_ids"] == ["market.price_proxy"]
    assert classify_tool_coverage("missing_private_metric")["coverage_status"] == "missing"


def test_report_intelligence_retires_tool_gaps_with_existing_coverage():
    rows = _backfill_tool_gaps_from_metric_candidates(
        [
            {
                "tool_gap_id": "TG-SECTOR-RELATIVE",
                "gap_type": "missing_metric",
                "metric_candidate_id": "METRIC-SECTOR-RELATIVE",
                "metric_name": "sector_relative_performance",
                "method_pattern_ids": ["METHOD-SECTOR"],
                "priority_bucket": "medium",
                "priority_reasons": ["tool coverage is missing for extracted metric"],
                "blocking_issues": ["requires_engineering_review"],
                "owner": "data_engineering",
                "status": "proposal_pending",
            }
        ],
        metric_rows=[],
        method_rows=[],
        run_id="RIR-TEST",
        model="test-model",
    )

    assert rows[0]["status"] == "retired"
    assert rows[0]["priority_bucket"] == "resolved"
    assert rows[0]["blocking_issues"] == []
    assert "metric_now_has_existing_tool_coverage" in rows[0]["priority_reasons"]
    assert build_data_acquisition_proposals(rows) == []
    assert build_tool_design_proposals(rows) == []


def test_report_intelligence_defaults_to_hybrid_mineru_backend():
    config = ReportIntelligenceConfig()

    assert config.mineru_backend == "hybrid-auto-engine"
    assert "{backend}" in DEFAULT_MINERU_ARGS_TEMPLATE


def test_mineru_batch_conversion_uses_directory_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))
    cached_model = (
        tmp_path
        / "hf-home"
        / "hub"
        / "models--opendatalab--MinerU2.5-Pro-2605-1.2B"
    )
    (cached_model / "refs").mkdir(parents=True)
    (cached_model / "refs" / "main").write_text("local-snapshot\n", encoding="utf-8")
    (cached_model / "snapshots" / "local-snapshot").mkdir(parents=True)
    fake_mineru = tmp_path / "fake-mineru"
    fake_mineru.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "import os",
                "from pathlib import Path",
                "assert os.environ.get('MINERU_TABLE_ENABLE') == 'true'",
                "assert os.environ.get('MINERU_FORMULA_ENABLE') == 'true'",
                "assert os.environ.get('HF_HUB_OFFLINE') == '1'",
                "assert os.environ.get('TRANSFORMERS_OFFLINE') == '1'",
                "args = sys.argv[1:]",
                "input_dir = Path(args[args.index('-p') + 1])",
                "output_dir = Path(args[args.index('-o') + 1])",
                "backend = args[args.index('-b') + 1]",
                "assert input_dir.is_dir()",
                "for pdf in sorted(input_dir.glob('*.pdf')):",
                "    target = output_dir / pdf.stem / backend.replace('-', '_')",
                "    target.mkdir(parents=True, exist_ok=True)",
                "    (target / f'{pdf.stem}.md').write_text(",
                "        f'# {pdf.stem}\\nbackend={backend}\\n',",
                "        encoding='utf-8',",
                "    )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_mineru.chmod(0o755)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_a = pdf_dir / "SRC-A.pdf"
    pdf_b = pdf_dir / "SRC-B.pdf"
    pdf_a.write_bytes(b"%PDF A")
    pdf_b.write_bytes(b"%PDF B")

    results = convert_pdfs_with_mineru_batch(
        (
            MineruBatchConversionTask(
                source_id="SRC-A",
                pdf_path=pdf_a,
                markdown_path=tmp_path / "markdown" / "SRC-A.md",
            ),
            MineruBatchConversionTask(
                source_id="SRC-B",
                pdf_path=pdf_b,
                markdown_path=tmp_path / "markdown" / "SRC-B.md",
            ),
        ),
        tmp_path / "mineru_batch",
        overwrite=False,
        command=str(fake_mineru),
        backend="vlm-auto-engine",
        batch_size=2,
        max_batch_bytes=8,
    )

    assert results["SRC-A"]["status"] == "converted"
    assert results["SRC-B"]["status"] == "converted"
    assert results["SRC-A"]["backend"] == "vlm-auto-engine"
    assert results["SRC-A"]["duration_seconds"] >= 0
    assert results["SRC-B"]["duration_seconds"] >= 0
    assert (tmp_path / "mineru_batch" / "input-002").exists()
    assert (tmp_path / "markdown" / "SRC-A.md").read_text(encoding="utf-8").startswith("# SRC-A")


def test_mineru_batch_conversion_resolves_relative_command_before_changing_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    fake_mineru = tmp_path / "tools" / "fake-mineru"
    fake_mineru.parent.mkdir()
    fake_mineru.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import sys",
                "from pathlib import Path",
                "args = sys.argv[1:]",
                "input_dir = Path(args[args.index('-p') + 1])",
                "output_dir = Path(args[args.index('-o') + 1])",
                "backend = args[args.index('-b') + 1]",
                "for pdf in sorted(input_dir.glob('*.pdf')):",
                "    target = output_dir / pdf.stem / backend.replace('-', '_')",
                "    target.mkdir(parents=True, exist_ok=True)",
                "    (target / f'{pdf.stem}.md').write_text('# ok\\n', encoding='utf-8')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_mineru.chmod(0o755)
    pdf_path = tmp_path / "SRC-REL.pdf"
    pdf_path.write_bytes(b"%PDF relative command")

    results = convert_pdfs_with_mineru_batch(
        (
            MineruBatchConversionTask(
                source_id="SRC-REL",
                pdf_path=pdf_path,
                markdown_path=tmp_path / "markdown" / "SRC-REL.md",
            ),
        ),
        tmp_path / "mineru_batch",
        overwrite=False,
        command="tools/fake-mineru",
        backend="hybrid-auto-engine",
    )

    assert results["SRC-REL"]["status"] == "converted"
    assert (tmp_path / "markdown" / "SRC-REL.md").read_text(encoding="utf-8") == "# ok\n"


def test_merge_report_intelligence_batch_outputs_dedupes_batch_jsonl(
    tmp_path: Path,
):
    direct_batch = tmp_path / "batch-a"
    nested_batch = tmp_path / "batch-b/registry/report_intelligence"
    direct_batch.mkdir(parents=True)
    nested_batch.mkdir(parents=True)

    (direct_batch / "report_metadata.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"report_id": "RPT-1", "source_id": "SRC-1"}),
                json.dumps({"report_id": "RPT-2", "source_id": "SRC-2"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (nested_batch / "report_metadata.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"report_id": "RPT-2", "source_id": "SRC-2-DUP"}),
                json.dumps({"report_id": "RPT-3", "source_id": "SRC-3"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (direct_batch / "forecast_claims.jsonl").write_text(
        json.dumps({"forecast_claim_id": "FC-1", "report_id": "RPT-1"}) + "\n",
        encoding="utf-8",
    )
    (nested_batch / "forecast_claims.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"forecast_claim_id": "FC-1", "report_id": "RPT-1-DUP"}),
                json.dumps({"forecast_claim_id": "FC-2", "report_id": "RPT-3"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = merge_report_intelligence_batch_outputs(
        root=tmp_path,
        input_dirs=(direct_batch, tmp_path / "batch-b"),
    )

    assert result["blocker_count"] == 0
    assert result["row_counts"]["report_metadata.jsonl"] == 3
    assert result["row_counts"]["forecast_claims.jsonl"] == 2
    metadata = _read_jsonl(
        tmp_path / "registry/report_intelligence/report_metadata.jsonl"
    )
    forecasts = _read_jsonl(
        tmp_path / "registry/report_intelligence/forecast_claims.jsonl"
    )
    assert [row["report_id"] for row in metadata] == ["RPT-1", "RPT-2", "RPT-3"]
    assert [row["forecast_claim_id"] for row in forecasts] == ["FC-1", "FC-2"]


def test_merge_report_intelligence_batch_outputs_preserves_existing_registry(
    tmp_path: Path,
):
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    (registry / "report_metadata.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"report_id": "RPT-0", "source_id": "SRC-0"}),
                json.dumps({"report_id": "RPT-1", "source_id": "SRC-1-OLD"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (registry / "processing_status.jsonl").write_text(
        json.dumps({"source_id": "SRC-1", "llm_status": "skipped"}) + "\n",
        encoding="utf-8",
    )
    (registry / "method_patterns.jsonl").write_text(
        json.dumps(
            {
                "method_pattern_id": "METHOD-1",
                "name": "relative performance",
                "source_footprint_ids": [],
                "steps": ["compare returns"],
                "required_current_data": [],
                "optional_confirmation_data": [],
                "failure_modes": [],
                "target_agents": [],
                "validation_status": "candidate",
                "allowed_runtime_mode": "shadow_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "report_metadata.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"report_id": "RPT-1", "source_id": "SRC-1-NEW"}),
                json.dumps({"report_id": "RPT-2", "source_id": "SRC-2"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (batch / "processing_status.jsonl").write_text(
        json.dumps({"source_id": "SRC-1", "llm_status": "processed"}) + "\n",
        encoding="utf-8",
    )
    (batch / "method_patterns.jsonl").write_text(
        json.dumps(
            {
                "method_pattern_id": "METHOD-1",
                "name": "relative performance",
                "source_footprint_ids": ["AFP-1"],
                "steps": ["check benchmark alpha"],
                "required_current_data": ["benchmark_return"],
                "optional_confirmation_data": ["volume"],
                "failure_modes": ["benchmark_mismatch"],
                "target_agents": ["stock_agent"],
                "validation_status": "candidate",
                "allowed_runtime_mode": "shadow_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = merge_report_intelligence_batch_outputs(
        root=tmp_path,
        input_dirs=(batch,),
    )

    assert result["blocker_count"] == 0
    assert result["include_existing_registry"] is True
    assert result["existing_file_counts"]["report_metadata.jsonl"] == 1
    assert result["input_file_counts"]["report_metadata.jsonl"] == 1
    assert result["row_counts"]["report_metadata.jsonl"] == 3
    assert result["row_counts"]["processing_status.jsonl"] == 1
    assert result["row_counts"]["method_patterns.jsonl"] == 1
    metadata = _read_jsonl(registry / "report_metadata.jsonl")
    status = _read_jsonl(registry / "processing_status.jsonl")
    methods = _read_jsonl(registry / "method_patterns.jsonl")
    assert metadata == [
        {"report_id": "RPT-0", "source_id": "SRC-0"},
        {"report_id": "RPT-1", "source_id": "SRC-1-NEW"},
        {"report_id": "RPT-2", "source_id": "SRC-2"},
    ]
    assert status == [{"source_id": "SRC-1", "llm_status": "processed"}]
    assert methods[0]["source_footprint_ids"] == ["AFP-1"]
    assert methods[0]["steps"] == ["compare returns", "check benchmark alpha"]
    assert methods[0]["required_current_data"] == ["benchmark_return"]
    assert methods[0]["optional_confirmation_data"] == ["volume"]
    assert methods[0]["failure_modes"] == ["benchmark_mismatch"]
    assert methods[0]["target_agents"] == ["stock_agent"]


def test_merge_report_intelligence_batch_outputs_can_replace_existing_registry(
    tmp_path: Path,
):
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    (registry / "report_metadata.jsonl").write_text(
        json.dumps({"report_id": "RPT-0", "source_id": "SRC-0"}) + "\n",
        encoding="utf-8",
    )
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "report_metadata.jsonl").write_text(
        json.dumps({"report_id": "RPT-1", "source_id": "SRC-1"}) + "\n",
        encoding="utf-8",
    )

    result = merge_report_intelligence_batch_outputs(
        root=tmp_path,
        input_dirs=(batch,),
        include_existing_registry=False,
    )

    assert result["blocker_count"] == 0
    assert result["include_existing_registry"] is False
    assert result["existing_file_counts"]["report_metadata.jsonl"] == 0
    assert result["row_counts"]["report_metadata.jsonl"] == 1
    assert _read_jsonl(registry / "report_metadata.jsonl") == [
        {"report_id": "RPT-1", "source_id": "SRC-1"}
    ]


def test_merge_report_intelligence_batches_cli(capsys, tmp_path: Path):
    batch = tmp_path / "batch"
    batch.mkdir()
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    (registry / "tool_gaps.jsonl").write_text(
        json.dumps({"tool_gap_id": "TG-0"}) + "\n",
        encoding="utf-8",
    )
    (batch / "tool_gaps.jsonl").write_text(
        json.dumps({"tool_gap_id": "TG-1"}) + "\n",
        encoding="utf-8",
    )

    rc = main(
        (
            "merge-report-intelligence-batches",
            "--root",
            str(tmp_path),
            "--input-dir",
            str(batch),
        )
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["row_counts"]["tool_gaps.jsonl"] == 2
    assert payload["existing_file_counts"]["tool_gaps.jsonl"] == 1
    assert _read_jsonl(tmp_path / "registry/report_intelligence/tool_gaps.jsonl") == [
        {"tool_gap_id": "TG-0"},
        {"tool_gap_id": "TG-1"}
    ]


def test_merge_report_intelligence_batches_cli_replace(capsys, tmp_path: Path):
    batch = tmp_path / "batch"
    batch.mkdir()
    registry = tmp_path / "registry/report_intelligence"
    registry.mkdir(parents=True)
    (registry / "tool_gaps.jsonl").write_text(
        json.dumps({"tool_gap_id": "TG-0"}) + "\n",
        encoding="utf-8",
    )
    (batch / "tool_gaps.jsonl").write_text(
        json.dumps({"tool_gap_id": "TG-1"}) + "\n",
        encoding="utf-8",
    )

    rc = main(
        (
            "merge-report-intelligence-batches",
            "--root",
            str(tmp_path),
            "--input-dir",
            str(batch),
            "--replace",
        )
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["include_existing_registry"] is False
    assert payload["row_counts"]["tool_gaps.jsonl"] == 1
    assert payload["existing_file_counts"]["tool_gaps.jsonl"] == 0
    assert _read_jsonl(tmp_path / "registry/report_intelligence/tool_gaps.jsonl") == [
        {"tool_gap_id": "TG-1"}
    ]
