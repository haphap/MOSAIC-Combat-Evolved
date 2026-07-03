import json

import pytest

from mosaic.rke.agent_research_context import (
    SAFE_ACTIONABILITY,
    assert_public_safe_context,
    build_rke_agent_research_context_from_rows,
    format_rke_agent_research_context,
    normalize_agent_id,
)
from mosaic.agents.utils import rke_research_tools


def test_macro_context_redacts_private_claim_text_and_maps_agent():
    forecasts = [
        {
            "forecast_claim_id": "FC-PRIVATE-1",
            "claim_id": "CLAIM-PRIVATE-1",
            "claim_text": "未来1-3个月人民币仍有贬值压力，USD/CNY中枢可能上移。",
            "source_span_ids": ["SRC-PRIVATE:p4:chunk2"],
            "report_id": "RPT-1",
            "source_id": "SRC-1",
            "target": {
                "target_type": "macro_series",
                "target_id": "USDCNY",
                "metric_family": "fx_rate",
            },
            "direction": "positive",
            "horizon": {"bucket": "medium", "source_text": "1-3个月"},
            "forecast_testability": "direct_macro_series_observable",
            "failure_modes": [{"text": "央行逆周期调节可能缓解贬值压力。"}],
            "claim_regime_trace": {
                "macro": {
                    "macro.dollar": {
                        "regime_types": ["fx_usd_cycle"],
                        "source_text_regime_types": ["fx_usd_cycle"],
                    }
                }
            },
        }
    ]

    context = build_rke_agent_research_context_from_rows(
        agent_id="dollar",
        layer="macro",
        as_of_date="2026-06-27",
        forecasts=forecasts,
        metadata=[
            {
                "report_id": "RPT-1",
                "source_id": "SRC-1",
                "publish_datetime": "2026-06-20T00:00:00+08:00",
                "institution_id": "INST-1",
                "author_ids": ["AUTH-1"],
            }
        ],
        source_profiles=[
            {
                "entity_id": "INST-1",
                "n_effective": 3.0,
                "shrunk_performance_bucket": "insufficient_data",
                "statistical_reliability_bucket": "limited",
            }
        ],
        viewpoint_profiles=[
            {
                "mechanism_chain": ["fx_rate"],
                "n_effective": 8.5,
                "shrunk_performance_bucket": "supportive_evidence",
                "statistical_reliability_bucket": "limited",
                "known_failure_modes": ["政策干预风险"],
            }
        ],
        recipes=[
            {
                "analysis_recipe_id": "AR-USDCNY-DIRECTIONAL",
                "decision_scope": "fx_rate_directional_check",
            }
        ],
        tool_gaps=[
            {
                "tool_gap_id": "TG-CNH-FORWARD-POINTS",
                "metric_name": "fx_rate_forward_points",
            }
        ],
    )

    assert context["agent_id"] == "macro.dollar"
    assert context["research_only"] is True
    assert context["production_signal_allowed"] is False
    assert context["actionability"] == SAFE_ACTIONABILITY
    item = context["context_items"][0]
    assert item["redacted_claim_id"].startswith("FCRED-")
    assert item["target_id"] == "USDCNY"
    assert item["metric_family"] == "fx_rate"
    assert item["regime_types"] == ["fx_usd_cycle"]
    assert item["viewpoint_performance_bucket"] == "supportive_evidence"
    assert item["recipe_ids"] == ["AR-USDCNY-DIRECTIONAL"]
    assert item["tool_gap_ids"] == ["TG-CNH-FORWARD-POINTS"]

    payload = json.dumps(context, ensure_ascii=False)
    assert "claim_text" not in payload
    assert "source_span_ids" not in payload
    assert "未来1-3个月人民币" not in payload
    assert "央行逆周期调节" not in payload


def test_superinvestor_context_filters_by_style_fit():
    forecasts = [
        {
            "forecast_claim_id": "FC-STOCK-1",
            "report_id": "RPT-STOCK-1",
            "target": {
                "target_type": "stock",
                "target_id": "600519.SH",
            },
            "metric_proxy_mapping": ["quality", "roe", "free_cash_flow"],
            "direction": "positive",
            "horizon": {"bucket": "long_horizon"},
        }
    ]
    metadata = [
        {
            "report_id": "RPT-STOCK-1",
            "report_type": "个股研报",
            "sector": "食品饮料",
            "ts_code": "600519.SH",
        }
    ]

    context = build_rke_agent_research_context_from_rows(
        agent_id="munger",
        layer="superinvestor",
        forecasts=forecasts,
        metadata=metadata,
    )

    assert context["agent_id"] == "superinvestor.munger"
    item = context["context_items"][0]
    assert item["ticker"] == "600519.SH"
    assert item["style_fit"] in {"medium", "high"}
    assert item["context_snapshot_status"] == "missing"
    assert item["context_snapshot_missing_reasons"] == [
        "stock_context_snapshot_missing"
    ]
    assert "stock_context_snapshot_missing" in item["ranking_reason_codes"]


def test_context_ranks_all_matches_before_truncating():
    forecasts = [
        {
            "forecast_claim_id": "FC-LOW",
            "report_id": "RPT-LOW",
            "target": {
                "target_type": "macro_series",
                "target_id": "USDCNY_LOW",
                "metric_family": "fx_rate",
            },
            "direction": "positive",
        },
        {
            "forecast_claim_id": "FC-HIGH",
            "report_id": "RPT-HIGH",
            "target": {
                "target_type": "macro_series",
                "target_id": "USDCNY_HIGH",
                "metric_family": "fx_rate",
            },
            "direction": "positive",
        },
    ]

    context = build_rke_agent_research_context_from_rows(
        agent_id="dollar",
        layer="macro",
        max_items=1,
        forecasts=forecasts,
        metadata=[
            {
                "report_id": "RPT-LOW",
                "report_type": "宏观策略",
                "publish_datetime": "2026-06-01T00:00:00+08:00",
            },
            {
                "report_id": "RPT-HIGH",
                "report_type": "宏观策略",
                "publish_datetime": "2026-06-01T00:00:00+08:00",
            },
        ],
        weighted_research_contexts=[
            {
                "agent_id": "macro.dollar",
                "retrieved_claims": [
                    {
                        "forecast_claim_id": "FC-LOW",
                        "combined_research_prior_weight": 0.9,
                        "performance_context_match": "insufficient_data",
                    },
                    {
                        "forecast_claim_id": "FC-HIGH",
                        "combined_research_prior_weight": 1.2,
                        "performance_context_match": "source_and_viewpoint_profile_match",
                    },
                ],
            }
        ],
    )

    assert context["ranking_policy_id"] == "rke_agent_research_context_rank_v1"
    assert context["summary"]["matched_item_count"] == 2
    assert context["summary"]["truncated_item_count"] == 1
    item = context["context_items"][0]
    assert item["target_id"] == "USDCNY_HIGH"
    assert item["retrieval_rank"] == 1
    assert item["priority_bucket"] == "high"
    assert item["combined_research_prior_weight"] == 1.2
    assert "source_and_viewpoint_profile_match" in item["ranking_reason_codes"]
    assert "research_prior_weight_above_neutral" in item["ranking_reason_codes"]
    assert item["current_data_required"] is True
    assert item["production_signal_allowed"] is False


def test_decision_context_reads_redacted_prior_with_current_data_guard():
    context = build_rke_agent_research_context_from_rows(
        agent_id="cio",
        layer="decision",
        forecasts=[
            {
                "forecast_claim_id": "FC-STOCK-CIO",
                "report_id": "RPT-STOCK-CIO",
                "target": {"target_type": "stock", "target_id": "600519.SH"},
                "metric_proxy_mapping": ["stock_forward_return"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-STOCK-CIO",
                "report_type": "个股研报",
                "sector": "食品饮料",
                "ts_code": "600519.SH",
            }
        ],
    )

    item = context["context_items"][0]
    assert context["agent_id"] == "decision.cio"
    assert item["domain"] == "stock"
    assert item["use_policy"] == "shadow_research_prior_only_not_current_signal"
    assert item["actionability_guard"] == SAFE_ACTIONABILITY
    assert "portfolio_context" in item["current_data_required_fields"]
    assert item["context_snapshot_missing_reasons"] == [
        "stock_context_snapshot_missing"
    ]


def test_sector_context_marks_missing_industry_snapshot_boundary():
    context = build_rke_agent_research_context_from_rows(
        agent_id="semiconductor",
        layer="sector",
        forecasts=[
            {
                "forecast_claim_id": "FC-SEMI",
                "report_id": "RPT-SEMI",
                "target": {"target_type": "sector", "target_id": "半导体"},
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-SEMI",
                "report_type": "行业研报",
                "sector": "半导体",
            }
        ],
    )

    item = context["context_items"][0]
    assert context["agent_id"] == "sector.semiconductor"
    assert item["domain"] == "industry"
    assert item["context_snapshot_status"] == "missing"
    assert item["context_snapshot_missing_reasons"] == [
        "industry_context_snapshot_missing"
    ]
    assert "industry_context_snapshot_missing" in item["ranking_reason_codes"]


def test_context_safety_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="forbidden field"):
        assert_public_safe_context({"claim_text": "private prose"})


def test_max_items_zero_returns_no_context_items():
    context = build_rke_agent_research_context_from_rows(
        agent_id="dollar",
        layer="macro",
        max_items=0,
        forecasts=[
            {
                "forecast_claim_id": "FC-1",
                "target": {
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                },
            }
        ],
    )

    assert context["context_items"] == []


def test_rke_research_tool_formats_context(monkeypatch):
    def fake_context(**_kwargs):
        return {
            "schema_version": "rke_agent_research_context_v1",
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "context_items": [],
            "summary": {"private_text_included": False},
        }

    monkeypatch.setattr(rke_research_tools, "build_rke_agent_research_context", fake_context)
    output = rke_research_tools.get_rke_research_context.invoke(
        {"agent_id": "dollar", "as_of_date": "2026-06-27", "layer": "macro"}
    )

    assert "RKE research context for macro.dollar" in output
    assert "research_only=true" in output


def test_normalize_agent_id_accepts_ts_and_rke_forms():
    assert normalize_agent_id("dollar", "macro") == "macro.dollar"
    assert normalize_agent_id("sector.semiconductor") == "sector.semiconductor"
    assert normalize_agent_id("ackman", "superinvestor") == "superinvestor.ackman"
    assert format_rke_agent_research_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "context_items": [],
        }
    )
