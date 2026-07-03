import json

import pytest

from mosaic.rke.agent_research_context import (
    FORBIDDEN_FIELD_NAMES,
    FORBIDDEN_FIELD_POLICY,
    RESEARCH_PRIOR_USE_POLICY,
    SAFE_ACTIONABILITY,
    SCHEMA_VERSION,
    assert_public_safe_context,
    build_rke_agent_research_context_from_rows,
    format_rke_agent_research_context,
    normalize_agent_id,
)
from mosaic.rke.cli import main
from mosaic.agents.utils import rke_research_tools


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_export_rke_agent_context_cli_outputs_three_domain_context(capsys, tmp_path):
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True)
    _write_jsonl(
        registry_dir / "forecast_claims.jsonl",
        [
            {
                "forecast_claim_id": "FC-STOCK-CLI",
                "report_id": "RPT-STOCK-CLI",
                "target": {"target_type": "stock", "target_id": "600519.SH"},
                "metric_proxy_mapping": ["stock_forward_return"],
                "direction": "positive",
            },
            {
                "forecast_claim_id": "FC-INDUSTRY-CLI",
                "report_id": "RPT-INDUSTRY-CLI",
                "target": {"target_type": "industry", "target_id": "半导体"},
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "positive",
            },
            {
                "forecast_claim_id": "FC-MACRO-CLI",
                "report_id": "RPT-MACRO-CLI",
                "target": {
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                },
                "direction": "positive",
            },
        ],
    )
    _write_jsonl(
        registry_dir / "report_metadata.jsonl",
        [
            {
                "report_id": "RPT-STOCK-CLI",
                "report_type": "个股研报",
                "ts_code": "600519.SH",
                "publish_datetime": "2026-01-01T00:00:00+08:00",
            },
            {
                "report_id": "RPT-INDUSTRY-CLI",
                "report_type": "行业研报",
                "sector": "半导体",
                "publish_datetime": "2026-01-02T00:00:00+08:00",
            },
            {
                "report_id": "RPT-MACRO-CLI",
                "report_type": "宏观策略",
                "publish_datetime": "2026-01-03T00:00:00+08:00",
            },
        ],
    )

    exit_code = main(
        (
            "export-rke-agent-context",
            "--root",
            str(tmp_path),
            "--agent-id",
            "cio",
            "--layer",
            "decision",
            "--as-of-date",
            "2026-02-01",
        )
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent_id"] == "decision.cio"
    assert payload["production_signal_allowed"] is False
    assert payload["ranking_policy_id"] == "rke_agent_research_context_rank_v1"
    assert payload["summary"]["item_count"] == 3
    assert {item["domain"] for item in payload["context_items"]} == {
        "stock",
        "industry",
        "macro",
    }
    assert "claim_text" not in json.dumps(payload, ensure_ascii=False)


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


def test_superinvestor_context_uses_role_filtered_reason_codes():
    forecasts = [
        {
            "forecast_claim_id": "FC-MUNGER",
            "report_id": "RPT-MUNGER",
            "target": {"target_type": "stock", "target_id": "600519.SH"},
            "metric_proxy_mapping": ["moat", "roic", "predictability"],
            "direction": "positive",
        },
        {
            "forecast_claim_id": "FC-BURRY",
            "report_id": "RPT-BURRY",
            "target": {"target_type": "stock", "target_id": "000001.SZ"},
            "metric_proxy_mapping": ["deep_value", "fcf_yield", "balance_sheet"],
            "direction": "positive",
        },
        {
            "forecast_claim_id": "FC-ACKMAN",
            "report_id": "RPT-ACKMAN",
            "target": {"target_type": "stock", "target_id": "600036.SH"},
            "metric_proxy_mapping": ["free_cash_flow", "earnings_growth", "dividend"],
            "direction": "positive",
        },
        {
            "forecast_claim_id": "FC-DRUCK",
            "report_id": "RPT-DRUCK",
            "target": {"target_type": "stock", "target_id": "601899.SH"},
            "metric_proxy_mapping": ["momentum", "policy", "cycle"],
            "direction": "positive",
        },
    ]
    metadata = [
        {"report_id": row["report_id"], "report_type": "个股研报"}
        for row in forecasts
    ]
    expected_codes = {
        "munger": "role_filter_quality_moat_cashflow",
        "burry": "role_filter_value_contrarian_balance_sheet",
        "ackman": "role_filter_quality_catalyst_capital_allocation",
        "druckenmiller": "role_filter_cycle_trend_policy_momentum",
    }

    for agent, code in expected_codes.items():
        context = build_rke_agent_research_context_from_rows(
            agent_id=agent,
            layer="superinvestor",
            forecasts=forecasts,
            metadata=metadata,
        )

        reason_codes = {
            reason
            for item in context["context_items"]
            for reason in item["ranking_reason_codes"]
        }
        assert code in reason_codes
        assert all(
            item["domain"] == "stock" and item["use_policy"].startswith("shadow_")
            for item in context["context_items"]
        )


def test_superinvestor_context_uses_available_stock_snapshot():
    context = build_rke_agent_research_context_from_rows(
        agent_id="munger",
        layer="superinvestor",
        forecasts=[
            {
                "forecast_claim_id": "FC-STOCK-SNAPSHOT",
                "report_id": "RPT-STOCK-SNAPSHOT",
                "target": {"target_type": "stock", "target_id": "600519.SH"},
                "metric_proxy_mapping": ["moat", "roic", "free_cash_flow"],
                "direction": "positive",
                "signal_datetime": "2026-01-10T09:00:00+08:00",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-STOCK-SNAPSHOT",
                "report_type": "个股研报",
                "ts_code": "600519.SH",
                "sector": "食品饮料",
                "publish_datetime": "2026-01-10T09:00:00+08:00",
            }
        ],
        stock_context_snapshots=[
            {
                "snapshot_id": "SCS-1",
                "as_of_date": "2026-01-10",
                "stock_symbol": "600519.SH",
                "market_cap_bucket": "large_cap",
                "liquidity_bucket": "tradable_proxy_observed",
                "stock_outcome_age_bucket": "stock_outcome_pending",
                "benchmark_family": "CSI300_ETF_PROXY",
                "missing_feature_reasons": [],
            }
        ],
    )

    item = context["context_items"][0]
    assert item["context_snapshot_status"] == "available"
    assert item["context_snapshot_missing_reasons"] == []
    assert item["context_snapshot_id"] == "SCS-1"
    assert item["market_cap_bucket"] == "large_cap"
    assert item["liquidity_bucket"] == "tradable_proxy_observed"
    assert "stock_context_snapshot_missing" not in item["ranking_reason_codes"]


def test_removed_superinvestor_gets_explicit_no_prior_reason():
    context = build_rke_agent_research_context_from_rows(
        agent_id="aschenbrenner",
        layer="superinvestor",
        forecasts=[
            {
                "forecast_claim_id": "FC-REMOVED",
                "report_id": "RPT-REMOVED",
                "target": {"target_type": "stock", "target_id": "600519.SH"},
                "metric_proxy_mapping": ["moat", "roic"],
                "direction": "positive",
            }
        ],
        metadata=[{"report_id": "RPT-REMOVED", "report_type": "个股研报"}],
    )

    assert context["context_items"] == []
    assert context["summary"]["no_prior_reason"] == "unsupported_superinvestor_agent"


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


def test_sector_context_uses_available_industry_snapshot():
    context = build_rke_agent_research_context_from_rows(
        agent_id="semiconductor",
        layer="sector",
        forecasts=[
            {
                "forecast_claim_id": "FC-SEMI-SNAPSHOT",
                "report_id": "RPT-SEMI-SNAPSHOT",
                "target": {"target_type": "sector", "target_id": "半导体"},
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "positive",
                "signal_datetime": "2026-01-10T09:00:00+08:00",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-SEMI-SNAPSHOT",
                "report_type": "行业研报",
                "sector": "半导体",
                "publish_datetime": "2026-01-10T09:00:00+08:00",
            }
        ],
        industry_context_snapshots=[
            {
                "snapshot_id": "ICS-1",
                "as_of_date": "2026-01-10",
                "canonical_sector": "半导体",
                "industry_cycle_bucket": "unknown",
                "proxy_symbol": "512480.SH",
                "mapping_confidence": "operator_seeded_exact_sector",
                "proxy_liquidity_bucket": "pit_available",
                "benchmark_family": "CSI300_ETF_PROXY",
                "known_proxy_limitations": [
                    "broad_etf_proxy_not_direct_industry_portfolio"
                ],
                "missing_feature_reasons": ["industry_cycle_bucket_missing"],
            }
        ],
    )

    item = context["context_items"][0]
    assert item["context_snapshot_status"] == "available"
    assert item["context_snapshot_missing_reasons"] == []
    assert item["context_snapshot_id"] == "ICS-1"
    assert item["proxy_symbol"] == "512480.SH"
    assert item["proxy_liquidity_bucket"] == "pit_available"
    assert item["known_proxy_limitations"] == [
        "broad_etf_proxy_not_direct_industry_portfolio"
    ]
    assert "broad_etf_proxy_not_direct_industry_portfolio" in item[
        "known_failure_mode_tags"
    ]
    assert "industry_context_snapshot_missing" not in item["ranking_reason_codes"]


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
            "schema_version": SCHEMA_VERSION,
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "no_prior_reason": "no_applicable_prior_for_agent_request",
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }

    monkeypatch.setattr(rke_research_tools, "build_rke_agent_research_context", fake_context)
    output = rke_research_tools.get_rke_research_context.invoke(
        {"agent_id": "dollar", "as_of_date": "2026-06-27", "layer": "macro"}
    )

    assert "runtime_preflight_status=passed" in output
    assert "ranking_policy_id=rke_agent_research_context_rank_v1" in output
    assert "context_hash=" in output
    assert "RKE research context for macro.dollar" in output
    assert "research_only=true" in output


def test_rke_runtime_context_preflight_flags_rank_order_without_sorting():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-2",
                    "retrieval_rank": 2,
                    "priority_bucket": "medium",
                },
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                },
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "retrieval_rank_order_changed" in output
    assert output.index("### Prior FCRED-2") < output.index("### Prior FCRED-1")


def test_rke_runtime_context_preflight_blocks_wrong_ranking_policy():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "other_ranker",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "ranking_policy_id_mismatch" in output


def test_rke_runtime_context_preflight_blocks_summary_ranking_policy_mismatch():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "other_ranker",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "summary_ranking_policy_id_mismatch" in output


def test_rke_runtime_context_preflight_blocks_summary_current_data_missing():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": False,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "summary_current_data_required_missing" in output
    assert "current_data_required=false" in output


def test_rke_runtime_context_preflight_blocks_unsupported_priority_bucket():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "agent_specific",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "priority_bucket_unsupported" in output


def test_rke_runtime_context_preflight_blocks_invalid_truncation_count():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                }
            ],
            "summary": {"truncated_item_count": -1, "current_data_required": True},
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "truncated_item_count_invalid" in output


def test_rke_runtime_context_preflight_blocks_missing_current_data_guard():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "current_data_required_missing" in output
    assert "current_data_required_fields_missing" in output
    assert "current_data_required=false" in output
    assert "- Current data required: false; fields=none" in output


def test_rke_runtime_context_preflight_blocks_bad_item_shadow_policy():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": True,
                    "use_policy": "production_signal",
                    "actionability_guard": "none",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_production_signal_not_disabled" in output
    assert "item_use_policy_invalid" in output
    assert "item_actionability_guard_invalid" in output
    assert "use_policy=production_signal" in output


def test_rke_runtime_context_formats_good_item_shadow_policy():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "expected_direction": "positive",
                    "horizon_bucket": "medium",
                    "regime_bucket": "fx_usd_cycle",
                    "regime_types": ["fx_usd_cycle"],
                    "source_performance_bucket": "supportive_evidence",
                    "viewpoint_performance_bucket": "supportive_evidence",
                    "agent_target_specificity_bucket": "direct_agent_target_match",
                    "performance_context_match": "source_and_viewpoint_profile_match",
                    "combined_research_prior_weight": 1.2,
                    "freshness_bucket": "completed_before_as_of_date",
                    "latest_completed_exit_date": "2026-06-20",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "outcome_label_summary": {
                        "label_count": 1,
                        "directional_hit_count": 1,
                        "label_types": ["macro_series_directional"],
                        "latest_completed_exit_date": "2026-06-20",
                    },
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=passed" in output
    assert "rank=1; priority=high; reasons=agent_specific_match" in output
    assert f"use_policy={RESEARCH_PRIOR_USE_POLICY}" in output
    assert f"actionability_guard={SAFE_ACTIONABILITY}" in output
    assert "production_signal_allowed=false" in output


def test_rke_runtime_context_preflight_blocks_bad_outcome_summary():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "expected_direction": "positive",
                    "horizon_bucket": "medium",
                    "regime_bucket": "fx_usd_cycle",
                    "regime_types": ["fx_usd_cycle"],
                    "source_performance_bucket": "supportive_evidence",
                    "viewpoint_performance_bucket": "supportive_evidence",
                    "agent_target_specificity_bucket": "direct_agent_target_match",
                    "performance_context_match": "source_and_viewpoint_profile_match",
                    "combined_research_prior_weight": 1.2,
                    "freshness_bucket": "completed_before_as_of_date",
                    "latest_completed_exit_date": "2026-06-20",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "outcome_label_summary": {"label_count": "1"},
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "outcome_label_summary_invalid" in output


def test_rke_runtime_context_preflight_blocks_missing_ranking_metadata():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "expected_direction": "positive",
                    "horizon_bucket": "medium",
                    "regime_bucket": "fx_usd_cycle",
                    "regime_types": ["fx_usd_cycle"],
                    "source_performance_bucket": "supportive_evidence",
                    "viewpoint_performance_bucket": "supportive_evidence",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_ranking_metadata_missing" in output
    assert "item_latest_exit_date_missing" in output
    assert "item_combined_weight_invalid" in output


def test_rke_runtime_context_preflight_blocks_missing_performance_buckets():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "expected_direction": "positive",
                    "horizon_bucket": "medium",
                    "regime_bucket": "fx_usd_cycle",
                    "regime_types": ["fx_usd_cycle"],
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_performance_bucket_missing" in output


def test_rke_runtime_context_preflight_blocks_missing_context_metadata():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_context_metadata_missing" in output
    assert "item_regime_types_invalid" in output


def test_rke_runtime_context_preflight_blocks_bad_recipe_tool_gap_ids():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_recipe_tool_gap_ids_invalid" in output


def test_rke_runtime_context_preflight_blocks_missing_failure_tags():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "known_failure_mode_tags_missing" in output


def test_rke_runtime_context_preflight_blocks_missing_reliability_metadata():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_reliability_bucket_missing" in output
    assert "item_n_effective_invalid" in output


def test_rke_runtime_context_preflight_blocks_missing_item_target_metadata():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_target_metadata_missing" in output


def test_rke_runtime_context_preflight_blocks_missing_redacted_claim_id():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "redacted_claim_id_missing" in output


def test_rke_runtime_context_preflight_blocks_empty_context_without_no_prior_reason():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "no_prior_reason_missing" in output


def test_rke_runtime_context_preflight_blocks_requested_agent_mismatch():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "burry",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "requested_agent_id_mismatch" in output


def test_rke_runtime_context_preflight_blocks_bad_as_of_date():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026/06/27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "as_of_date_invalid" in output


def test_rke_runtime_context_preflight_blocks_layer_agent_mismatch():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "sector",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "layer_agent_mismatch" in output


def test_rke_runtime_context_preflight_blocks_schema_version_mismatch():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "schema_version": "legacy_context",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "schema_version_mismatch" in output


def test_rke_runtime_context_preflight_blocks_forbidden_field_count():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": 0,
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "forbidden_field_count_invalid" in output


def test_rke_runtime_context_preflight_blocks_forbidden_field_policy():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": "not_enforced",
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v1",
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "forbidden_field_policy_invalid" in output


def test_rke_runtime_context_preflight_blocks_top_level_policy_boundary():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": False,
            "production_signal_allowed": False,
            "actionability": "trade_allowed",
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "private_text_included": True,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "research_only_missing" in output
    assert "context_actionability_guard_invalid" in output
    assert "private_text_boundary_missing" in output


def test_rke_runtime_context_preflight_blocks_hidden_private_fields():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_asset",
                    "target_id": ".mosaic/rke/private.pdf",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                    "claim_text": "private prose",
                }
            ],
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "public_safe_context_violation" in output
    assert "RKE context body withheld: public-safe context violation." in output
    assert ".mosaic/rke/private.pdf" not in output


def test_rke_runtime_context_preflight_blocks_malformed_context_items():
    malformed = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": "not-a-list",
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )
    non_object = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": ["not-an-object"],
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "context_items_malformed" in malformed
    assert "context_item_not_object" in non_object
    assert "runtime_preflight_status=blocked" in malformed
    assert "runtime_preflight_status=blocked" in non_object


def test_rke_runtime_context_preflight_blocks_count_metadata_mismatch():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 2,
                "matched_item_count": 1,
                "private_text_included": False,
                "truncated_item_count": 1,
                "current_data_required": True,
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "item_count_mismatch" in output
    assert "truncated_item_count_mismatch" in output


def test_rke_runtime_context_preflight_blocks_missing_ranking_reasons():
    output = rke_research_tools.format_rke_runtime_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v1",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "runtime_preflight_status=blocked" in output
    assert "ranking_reason_codes_missing" in output


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
