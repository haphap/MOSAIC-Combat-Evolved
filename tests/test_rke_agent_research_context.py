import json

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.rke.agent_research_context import (
    FORBIDDEN_FIELD_NAMES,
    FORBIDDEN_FIELD_POLICY,
    RESEARCH_PRIOR_USE_POLICY,
    SECTOR_DIRECTION_KEYWORDS,
    SAFE_ACTIONABILITY,
    SCHEMA_VERSION,
    assert_research_context_boundary,
    build_rke_agent_research_materialization,
    build_rke_agent_research_context,
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


def test_trusted_rke_materialization_returns_selected_source_ids_outside_public_context(
    tmp_path,
):
    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True)
    _write_jsonl(
        registry_dir / "forecast_claims.jsonl",
        [
            {
                "forecast_claim_id": "FC-SELECTED",
                "report_id": "RPT-SELECTED",
                "source_id": "SRC-SELECTED",
                "target": {"target_type": "industry", "target_id": "银行"},
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "positive",
            },
            {
                "forecast_claim_id": "FC-OTHER",
                "report_id": "RPT-OTHER",
                "source_id": "SRC-OTHER",
                "target": {"target_type": "industry", "target_id": "半导体"},
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "negative",
            },
        ],
    )
    _write_jsonl(
        registry_dir / "report_metadata.jsonl",
        [
            {
                "report_id": "RPT-SELECTED",
                "source_id": "SRC-SELECTED",
                "report_type": "行业研报",
                "sector": "银行",
                "publish_datetime": "2026-07-01T09:00:00+08:00",
            },
            {
                "report_id": "RPT-OTHER",
                "source_id": "SRC-OTHER",
                "report_type": "行业研报",
                "sector": "半导体",
                "publish_datetime": "2026-07-01T09:00:00+08:00",
            },
        ],
    )

    materialization = build_rke_agent_research_materialization(
        root=tmp_path,
        agent_id="financials",
        layer="sector",
        sector="银行",
        as_of_date="2026-07-09",
        max_items=12,
    )

    for filename in (
        "report_outcome_labels.jsonl", "source_performance_profiles.jsonl",
        "viewpoint_performance_profiles.jsonl", "analysis_recipes.jsonl",
        "tool_gaps.jsonl", "weighted_research_contexts.jsonl",
        "stock_context_snapshots.jsonl", "industry_context_snapshots.jsonl",
    ):
        (registry_dir / filename).write_text("not valid json", encoding="utf-8")
    query = dict(
        root=tmp_path, agent_id="financials", layer="sector", sector="银行",
        as_of_date="2026-07-09", max_items=12,
    )
    assert build_rke_agent_research_materialization(**query) == materialization
    assert build_rke_agent_research_context(**query) == materialization["context"]

    assert set(materialization) == {"context", "source_ids", "input_bytes", "metadata"}
    assert materialization["source_ids"] == ("SRC-SELECTED",)
    assert materialization["context"]["summary"]["item_count"] == 1
    assert "SRC-SELECTED" not in json.dumps(
        materialization["context"], ensure_ascii=False
    )


@pytest.mark.parametrize(
    ("agent_id", "direction_id", "sector_label", "expected_count"),
    [
        ("agriculture", "livestock_aquaculture", "农牧饲渔", 1),
        ("biotech", "biological_products", "生物制品", 1),
        ("consumer", "food_beverage", "食品饮料", 1),
        ("energy", "coal", "煤炭行业", 1),
        ("financials", "banking", "银行", 1),
        ("industrials", "machinery", "通用设备", 1),
        ("real_estate_construction", "real_estate", "房地产开发", 1),
        ("semiconductor", "semiconductor_equipment_materials", "半导体", 1),
        ("technology", "computer", "计算机设备", 1),
        ("consumer", "food_beverage", "家电", 0),
        ("energy", "coal", "光伏", 0),
    ],
)
def test_sector_direction_id_matches_existing_chinese_keyword_authority(
    agent_id, direction_id, sector_label, expected_count
):
    context = build_rke_agent_research_context_from_rows(
        agent_id=agent_id,
        layer="sector",
        sector=direction_id,
        as_of_date="2026-07-09",
        max_items=12,
        forecasts=[
            {
                "forecast_claim_id": f"FC-{agent_id}",
                "report_id": f"RPT-{agent_id}",
                "source_id": f"SRC-{agent_id}",
                "target": {"target_type": "industry", "target_id": sector_label},
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": f"RPT-{agent_id}",
                "source_id": f"SRC-{agent_id}",
                "report_type": "行业研报",
                "sector": sector_label,
                "publish_datetime": "2026-07-01T09:00:00+08:00",
            }
        ],
    )

    assert context["agent_id"] == f"sector.{agent_id}"
    assert context["summary"]["item_count"] == expected_count


def test_sector_direction_keyword_authority_closes_frozen_directions():
    from mosaic.dataflows.sector_snapshots import SECTOR_DIRECTION_IDS

    expected_keys = {
        (agent_id, direction_id)
        for agent_id, direction_ids in SECTOR_DIRECTION_IDS.items()
        for direction_id in direction_ids
    }
    assert set(SECTOR_DIRECTION_KEYWORDS) == expected_keys


def test_relationship_mapper_selects_matching_stock_sector_claim() -> None:
    context = build_rke_agent_research_context_from_rows(
        agent_id="relationship_mapper",
        layer="relationship",
        ticker="000001.SZ",
        sector="sector-energy",
        as_of_date="2026-07-17",
        max_items=12,
        forecasts=[
            {
                "forecast_claim_id": "FC-RELATIONSHIP",
                "report_id": "RPT-RELATIONSHIP",
                "source_id": "SRC-RELATIONSHIP",
                "target": {"target_type": "stock", "target_id": "000001.SZ"},
                "metric_proxy_mapping": ["stock_forward_return"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-RELATIONSHIP",
                "source_id": "SRC-RELATIONSHIP",
                "report_type": "个股研报",
                "ts_code": "000001.SZ",
                "sector": "sector-energy",
                "publish_datetime": "2026-07-16T09:00:00+08:00",
            }
        ],
    )

    assert context["agent_id"] == "sector.relationship_mapper"
    assert context["summary"]["item_count"] == 1


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
    assert payload["ranking_policy_id"] == "rke_agent_research_context_rank_v4"
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
            for reason in item["role_filter_reason_codes"]
        }
        assert code in reason_codes
        assert all(
            item["domain"] == "stock" and item["use_policy"].startswith("shadow_")
            for item in context["context_items"]
        )


def test_superinvestor_runtime_preflight_blocks_generic_unfiltered_context():
    context = build_rke_agent_research_context_from_rows(
        agent_id="munger",
        layer="superinvestor",
        as_of_date="2026-06-27",
        forecasts=[
            {
                "forecast_claim_id": "FC-MUNGER-RUNTIME",
                "report_id": "RPT-MUNGER-RUNTIME",
                "target": {"target_type": "stock", "target_id": "600519.SH"},
                "metric_proxy_mapping": ["moat", "roic", "free_cash_flow"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-MUNGER-RUNTIME",
                "report_type": "个股研报",
                "ts_code": "600519.SH",
            }
        ],
    )
    item = context["context_items"][0]
    item["role_filter_reason_codes"] = []


    error = pytest.raises(
        DataVendorUnavailable, rke_research_tools.format_rke_runtime_context, context
    )

    assert "superinvestor_role_filter_missing" in str(error.value)


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
                "publish_datetime": "2026-06-02T00:00:00+08:00",
            },
        ],
    )

    assert context["ranking_policy_id"] == "rke_agent_research_context_rank_v4"
    assert context["summary"]["matched_item_count"] == 2
    assert context["summary"]["truncated_item_count"] == 1
    item = context["context_items"][0]
    assert item["target_id"] == "USDCNY_HIGH"
    assert item["retrieval_rank"] == 1
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


def test_sector_ascii_keyword_matching_uses_token_boundaries() -> None:
    consumer = build_rke_agent_research_context_from_rows(
        agent_id="consumer",
        layer="sector",
        ticker="600025.SH",
        forecasts=[
            {
                "forecast_claim_id": "FC-RETAIL",
                "report_id": "RPT-RETAIL",
                "target": {"target_type": "stock", "target_id": "600025.SH"},
                "metric_proxy_mapping": ["stock_forward_return"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-RETAIL",
                "report_type": "个股研报",
                "sector": "retail",
                "subsectors": ["食品"],
                "ts_code": "600025.SH",
            }
        ],
    )
    technology = build_rke_agent_research_context_from_rows(
        agent_id="technology",
        layer="sector",
        forecasts=[
            {
                "forecast_claim_id": "FC-AI",
                "report_id": "RPT-AI",
                "target": {
                    "target_type": "industry",
                    "target_id": "AI infrastructure",
                },
                "metric_proxy_mapping": ["industry_etf_forward_return"],
                "direction": "positive",
            }
        ],
        metadata=[
            {
                "report_id": "RPT-AI",
                "report_type": "行业研报",
                "sector": "AI infrastructure",
            }
        ],
    )

    assert consumer["summary"]["item_count"] == 1
    assert technology["summary"]["item_count"] == 1


def test_context_safety_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="forbidden field"):
        assert_research_context_boundary({"claim_text": "private prose"})
    with pytest.raises(ValueError, match="forbidden field"):
        assert_research_context_boundary({"source_excerpt": "private prose"})


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
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }

    monkeypatch.setattr(rke_research_tools, "build_rke_agent_research_context", fake_context)
    output = rke_research_tools.get_rke_research_context.invoke(
        {"agent_id": "dollar", "as_of_date": "2026-06-27", "layer": "macro"}
    )

    assert "Runtime preflight:" not in output
    assert "RKE research context for macro.dollar" in output
    assert "research_only=true" in output


def test_rke_preflight_failure_is_a_tool_execution_error(monkeypatch):
    from types import SimpleNamespace

    from mosaic.bridge.handlers import tools as bridge_tools
    from mosaic.bridge.protocol import RpcError, TOOL_EXECUTION_ERROR

    monkeypatch.setattr(
        rke_research_tools, "build_rke_agent_research_context", lambda **_kwargs: {}
    )
    monkeypatch.setattr(
        bridge_tools,
        "get_capability_store",
        lambda: SimpleNamespace(
            call_tool_result=lambda _capability, _name, args: (
                rke_research_tools.get_rke_research_context.invoke(args)
            )
        ),
    )
    with pytest.raises(RpcError) as error:
        bridge_tools.tools_call(
            {
                "capability": {},
                "name": "get_rke_research_context",
                "args": {"agent_id": "cro", "as_of_date": "2026-07-09"},
            }
        )
    assert error.value.code == TOOL_EXECUTION_ERROR
    assert error.value.data == {"reason_code": "RKE_CONTEXT_PREFLIGHT_FAILED"}
    assert "RKE context preflight failed" in error.value.message
    assert "context_items_missing" in error.value.message


def test_rke_runtime_context_preflight_blocks_summary_current_data_missing():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "summary_current_data_required_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_current_data_guard():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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

    assert "current_data_required_missing" in str(error.value)
    assert "current_data_required_fields_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_bad_current_data_fields():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": [],
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "current_data_required_fields_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_bad_item_shadow_policy():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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
                    "actionability": "trade_allowed",
                    "actionability_guard": "none",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "item_production_signal_not_disabled" in str(error.value)
    assert "item_use_policy_invalid" in str(error.value)
    assert "item_actionability_invalid" in str(error.value)
    assert "item_actionability_guard_invalid" in str(error.value)


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
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "available_date": "2026-06-20",
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
                    "freshness_bucket": "historical_completed_exit",
                    "latest_completed_exit_date": "2026-06-20",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "context_snapshot_status": "not_required",
                    "context_snapshot_missing_reasons": [],
                    "outcome_label_summary": {
                        "label_count": 1,
                        "directional_hit_count": 1,
                        "pending_label_count": 0,
                        "pending_share": 0.0,
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
                    "actionability": SAFE_ACTIONABILITY,
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
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "Available date: 2026-06-20" in output
    assert f"use_policy={RESEARCH_PRIOR_USE_POLICY}" in output
    assert f"actionability_guard={SAFE_ACTIONABILITY}" in output
    assert "production_signal_allowed=false" in output
    assert "Outcome labels:" not in output


def test_rke_runtime_context_preflight_blocks_missing_context_metadata():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "regime_types": ["", 3],
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
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "item_context_metadata_missing" in str(error.value)
    assert "item_regime_types_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_item_target_metadata():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "item_target_metadata_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_redacted_claim_id():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "redacted_claim_id_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_empty_context_without_no_prior_reason():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "no_prior_reason_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_requested_agent_mismatch():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "burry",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "requested_agent_id_mismatch" in str(error.value)


def test_rke_runtime_context_preflight_blocks_bad_as_of_date():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026/06/27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "as_of_date_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_layer_agent_mismatch():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "sector",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "layer_agent_mismatch" in str(error.value)


def test_rke_runtime_context_preflight_blocks_schema_version_mismatch():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "schema_version": "legacy_context",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "schema_version_mismatch" in str(error.value)


def test_rke_runtime_context_preflight_blocks_forbidden_field_policy():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": "not_enforced",
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "forbidden_field_policy_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_top_level_policy_boundary():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": False,
            "production_signal_allowed": False,
            "actionability": "trade_allowed",
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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
                "private_text_included": True,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "research_only_missing" in str(error.value)
    assert "context_actionability_guard_invalid" in str(error.value)
    assert "private_text_boundary_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_hidden_private_fields():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
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

    assert "public_safe_context_violation" in str(error.value)
    assert ".mosaic/rke/private.pdf" not in str(error.value)


def test_rke_runtime_context_preflight_blocks_malformed_context_items():
    malformed = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": "not-a-list",
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )
    non_object = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": ["not-an-object"],
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "context_items_malformed" in str(malformed.value)
    assert "context_item_not_object" in str(non_object.value)


def test_normalize_agent_id_accepts_ts_and_rke_forms():
    assert normalize_agent_id("dollar", "macro") == "macro.dollar"
    assert normalize_agent_id("sector.semiconductor") == "sector.semiconductor"
    assert normalize_agent_id("ackman", "superinvestor") == "superinvestor.ackman"
    assert (
        normalize_agent_id("autonomous_execution", "decision")
        == "decision.autonomous_execution"
    )
    assert format_rke_agent_research_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "context_items": [],
        }
    )


@pytest.mark.parametrize("optional_value", [None, {"invalid": True}])
def test_rke_runtime_context_omits_optional_research_metadata(optional_value):
    context = build_rke_agent_research_context_from_rows(
        agent_id="financials", layer="sector", as_of_date="2026-07-09",
        forecasts=[{
            "forecast_claim_id": "FC-BASIC",
            "signal_datetime": "2026-07-01",
            "target": {"target_type": "industry", "target_id": "银行"},
            "metric_proxy_mapping": ["industry_etf_forward_return"],
            "direction": "positive",
        }],
    )
    assert len(context["context_items"]) == 1
    for item in context["context_items"]:
        for field in (
            "statistical_reliability_bucket", "source_performance_bucket",
            "viewpoint_performance_bucket", "performance_context_match",
            "agent_target_specificity_bucket", "freshness_bucket",
            "latest_completed_exit_date", "combined_research_prior_weight",
            "n_effective", "known_failure_mode_tags", "recipe_ids", "tool_gap_ids",
            "context_snapshot_status", "context_snapshot_missing_reasons",
            "outcome_label_summary",
        ):
            if optional_value is None:
                item.pop(field, None)
            else:
                item[field] = optional_value
    context["summary"].pop("forbidden_field_count", None)
    output = rke_research_tools.format_rke_runtime_context(context)
    assert "### Prior FCRED-" in output
    assert "Expected direction: positive" in output
    assert "Current data required: true" in output
    for label in ("Performance:", "Outcome labels:", "Recipes:", "Tool gaps:", "Failure tags:"):
        assert label not in output

    context["context_items"][0]["outcome_label_summary"] = {"claim_text": "private prose"}
    with pytest.raises(DataVendorUnavailable, match="public_safe_context_violation"):
        rke_research_tools.format_rke_runtime_context(context)


def test_basic_context_orders_by_match_availability_and_stable_identity():
    forecasts = [
        {
            "forecast_claim_id": claim_id,
            "signal_datetime": available,
            "target": {"target_type": "industry", "target_id": "银行"},
            "metric_proxy_mapping": ["industry_etf_forward_return"],
            "direction": direction,
        }
        for claim_id, available, direction in [
            ("FC-OLD", "2026-06-01", "negative"),
            ("FC-NEW-A", "2026-07-01", "positive"),
            ("FC-NEW-B", "2026-07-01", "neutral"),
            ("FC-FUTURE", "2026-08-01", "negative"),
        ]
    ]
    kwargs = dict(agent_id="financials", layer="sector", as_of_date="2026-07-09", max_items=2)
    context = build_rke_agent_research_context_from_rows(forecasts=forecasts, **kwargs)
    assert context == build_rke_agent_research_context_from_rows(forecasts=list(reversed(forecasts)), **kwargs)
    items = context["context_items"]
    assert len(items) == 2
    assert all(item["available_date"] == "2026-07-01" for item in items)
    assert [item["redacted_claim_id"] for item in items] == sorted(item["redacted_claim_id"] for item in items)
    assert not any("weight" in key or "snapshot" in key or "performance" in key for item in items for key in item)
    output = rke_research_tools.format_rke_runtime_context(context)
    assert "context_hash=" not in output
    assert "Runtime ranking audit:" not in output

    # Explicit target matching precedes recency, independent of input order.
    forecasts[0]["target_agent_candidates"] = ["sector.financials"]
    specific = build_rke_agent_research_context_from_rows(forecasts=forecasts, **kwargs)
    assert specific["context_items"][0]["expected_direction"] == "negative"
    assert specific["context_items"][0]["available_date"] == "2026-06-01"


@pytest.mark.parametrize("available_date", [None, "invalid", "2026-07-10"])
def test_runtime_rejects_unknown_invalid_or_future_availability(available_date):
    context = build_rke_agent_research_context_from_rows(
        agent_id="financials", layer="sector", as_of_date="2026-07-09",
        forecasts=[{
            "forecast_claim_id": "FC-PIT",
            "signal_datetime": "2026-07-01",
            "target": {"target_type": "industry", "target_id": "银行"},
            "metric_proxy_mapping": ["industry_etf_forward_return"],
        }],
    )
    assert "### Prior" in rke_research_tools.format_rke_runtime_context(context)
    context["context_items"][0]["available_date"] = available_date
    with pytest.raises(DataVendorUnavailable, match="item_available_date_"):
        rke_research_tools.format_rke_runtime_context(context)


def test_basic_context_respects_later_report_accessibility():
    context = build_rke_agent_research_context_from_rows(
        agent_id="financials", layer="sector", as_of_date="2026-07-09",
        forecasts=[{
            "forecast_claim_id": "FC-ACCESS", "report_id": "RPT-ACCESS",
            "signal_datetime": "2026-07-01",
            "target": {"target_type": "industry", "target_id": "银行"},
            "metric_proxy_mapping": ["industry_etf_forward_return"],
        }],
        metadata=[{
            "report_id": "RPT-ACCESS", "publish_datetime": "2026-07-01",
            "accessible_datetime": "2026-07-10",
        }],
    )
    assert context["context_items"] == []


def test_basic_query_observes_same_size_same_mtime_input_updates(tmp_path):
    import os

    registry_dir = tmp_path / "registry/report_intelligence"
    registry_dir.mkdir(parents=True)
    path = registry_dir / "forecast_claims.jsonl"
    claim = {
        "forecast_claim_id": "FC-1", "source_id": "SRC-1",
        "signal_datetime": "2026-07-01",
        "target": {"target_type": "industry", "target_id": "银行"},
        "metric_proxy_mapping": ["industry_etf_forward_return"], "direction": "positive",
    }
    _write_jsonl(path, [claim])
    (registry_dir / "report_metadata.jsonl").write_text("")
    args = dict(root=tmp_path, agent_id="financials", layer="sector", sector="银行", as_of_date="2026-07-09")
    before = build_rke_agent_research_context(**args)
    assert len(before["context_items"]) == 1
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"2026-07-01", b"2026-08-01"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    assert build_rke_agent_research_context(**args)["context_items"] == []
def test_research_cases_reach_runtime_with_authorization_pit_and_source_diversity(tmp_path):
    case = {
        "question": "Inventory and margins", "historical_regime": "Inventory liquidation",
        "reasoning_chain": ["Inventory falls", "Discounting slows", "Margins recover"],
        "evidence": [], "assumptions": [], "invalidation_conditions": [], "conclusion": "",
    }
    metadata = [
        {"report_id": report, "source_id": f"SRC-{report}", "report_type": "行业研报",
         "sector": "半导体", "publish_datetime": "2025-01-01",
         "license_class": "operator_approved_internal_research_use",
         "derived_claim_storage_allowed": "operator_approved_internal_use"}
        for report in ("R1", "R2", "UNAUTHORIZED", "FUTURE")
    ]
    metadata[2]["derived_claim_storage_allowed"] = False
    metadata[3]["accessible_datetime"] = "2027-01-01"
    footprints = [
        {"footprint_id": ident, "report_id": report, "source_id": f"SRC-{report}",
         "source_span_ids": ["PRIVATE-SPAN"], "sector": "半导体", "research_case": case,
         "target_agent_candidates": ["sector.semiconductor"]}
        for ident, report in (("A", "R1"), ("B", "R1"), ("C", "R2"),
                              ("D", "UNAUTHORIZED"), ("E", "FUTURE"))
    ]
    context = build_rke_agent_research_context_from_rows(
        agent_id="semiconductor", as_of_date="2026-01-01", footprints=footprints,
        metadata=metadata, max_items=2,
    )
    assert len(context["context_items"]) == 2
    assert context["summary"]["matched_item_count"] == 2
    assert context["summary"]["private_text_included"] is True
    rendered = rke_research_tools.format_rke_runtime_context(context)
    assert "Inventory falls → Discounting slows → Margins recover" in rendered
    assert "Current applicability: unassessed" in rendered
    assert "PRIVATE-SPAN" not in rendered
    assert "SRC-R1" not in json.dumps(context)
    assert all(item["research_case"] == case for item in context["context_items"])
    directory = tmp_path / "registry/report_intelligence"
    directory.mkdir(parents=True)
    for name, rows in (("analytical_footprints", footprints), ("report_metadata", metadata),
                       ("forecast_claims", [])):
        _write_jsonl(directory / f"{name}.jsonl", rows)
    materialized = build_rke_agent_research_materialization(
        root=tmp_path, agent_id="semiconductor", as_of_date="2026-01-01", max_items=2,
    )
    assert materialized["context"] == context
    assert set(materialized["source_ids"]) == {"SRC-R1", "SRC-R2"}
    assert materialized["input_bytes"]["analytical_footprints.jsonl"] == (
        directory / "analytical_footprints.jsonl"
    ).read_bytes()

    first_only = build_rke_agent_research_context_from_rows(
        agent_id="semiconductor", as_of_date="2026-01-01", footprints=footprints[:2],
        metadata=metadata, max_items=2,
    )
    assert {r["redacted_claim_id"] for r in context["context_items"]} != {
        r["redacted_claim_id"] for r in first_only["context_items"]
    }


def test_historical_regime_provenance_is_not_collapsed():
    context = build_rke_agent_research_context_from_rows(
        agent_id="cio", as_of_date="2026-01-01", forecasts=[{
            "forecast_claim_id": "F", "signal_datetime": "2025-01-01",
            "target": {"target_type": "stock", "target_id": "000001.SZ"},
            "claim_regime_trace": {"macro": {"macro.china": {
                "regime_types": ["source_condition", "external_historical_background"],
                "source_text_regime_types": ["source_condition"],
                "as_of_date_regime_types": ["external_historical_background"],
            }}},
        }],
    )
    item = context["context_items"][0]
    assert item["source_stated_regime_types"] == ["source_condition"]
    assert item["historical_date_regime_types"] == ["external_historical_background"]


def test_macro_research_case_is_not_routed_as_a_generic_industry():
    case = {"question": "How does tightening affect liquidity?",
            "historical_regime": "Monetary tightening",
            "reasoning_chain": ["Funding costs rise", "Liquidity demand increases"]}
    context = build_rke_agent_research_context_from_rows(
        agent_id="cio", as_of_date="2026-01-01",
        metadata=[{"report_id": "R", "source_id": "S", "report_type": "宏观策略-海外",
                   "sector": "宏观策略", "publish_datetime": "2025-01-01",
                   "license_class": "operator_approved_internal_research_use",
                   "derived_claim_storage_allowed": True}],
        footprints=[{"footprint_id": "F", "report_id": "R", "source_id": "S",
                     "source_span_ids": ["PRIVATE"], "sector": "宏观策略",
                     "research_case": case}],
    )
    item = context["context_items"][0]
    assert item["domain"] == "macro"
    assert item["target_type"] == "unknown"
    assert item["target_id"] == "unknown"
    assert item["research_case"]["historical_regime"] == "Monetary tightening"


def test_research_case_transfer_keeps_original_target_and_prefers_requested_stock():
    case = {"question": "Inventory and margins", "historical_regime": "",
            "reasoning_chain": ["Inventory falls", "Discounting slows"],
            "evidence": [], "assumptions": [], "invalidation_conditions": [], "conclusion": ""}
    metadata = [{"report_id": ticker, "source_id": ticker, "ts_code": ticker,
                 "publish_datetime": "2025-01-01", "sector": "半导体",
                 "license_class": "operator_approved_internal_research_use",
                 "derived_claim_storage_allowed": True}
                for ticker in ("000001.SZ", "000002.SZ")]
    footprints = [{"footprint_id": ticker, "report_id": ticker, "source_id": ticker,
                   "source_span_ids": ["PRIVATE"], "research_case": case,
                   "target_agent_candidates": ["superinvestor.munger"]}
                  for ticker in ("000001.SZ", "000002.SZ")]
    context = build_rke_agent_research_context_from_rows(
        agent_id="superinvestor.munger", ticker="000002.SZ", as_of_date="2026-01-01",
        metadata=metadata, footprints=footprints,
    )
    items = context["context_items"]
    assert [item["ticker"] for item in items] == ["000002.SZ", "000001.SZ"]
    assert all(item["case_transfer_requires_current_data"] for item in items)
    assert items[1]["ticker_match"] is False


@pytest.mark.parametrize("agent_id", [
    "macro.us_financial_conditions", "macro.central_bank", "sector.financials",
    "superinvestor.munger", "decision.cio",
])
def test_research_case_access_does_not_require_entity_industry_or_role_tags(agent_id):
    case = {"question": "融资成本如何影响银行收入？", "historical_regime": "高利率与市场波动",
            "reasoning_chain": ["企业提前融资", "银行的融资中介需求增加"]}
    metadata = [{"report_id": "R", "source_id": "S", "report_type": "宏观策略-海外",
                 "sector": "宏观策略", "publish_datetime": "2025-01-01",
                 "license_class": "operator_approved_internal_research_use",
                 "derived_claim_storage_allowed": True}]
    footprint = {"footprint_id": "F", "report_id": "R", "source_id": "S",
                 "source_span_ids": ["PRIVATE"], "research_case": case}
    context = build_rke_agent_research_context_from_rows(
        agent_id=agent_id, ticker="600519.SH", sector="food_beverage",
        as_of_date="2026-01-01", metadata=metadata, footprints=[footprint],
    )
    assert context["summary"]["matched_item_count"] == 1
    assert context["context_items"][0]["research_case"]["question"] == case["question"]
    assert context["context_items"][0]["ticker_match"] is False
    assert case["question"] in rke_research_tools.format_rke_runtime_context(context)
    assert build_rke_agent_research_context_from_rows(
        agent_id="macro.not_a_real_agent", as_of_date="2026-01-01",
        metadata=metadata, footprints=[footprint],
    )["context_items"] == []


def test_case_reasoning_relevance_precedes_directory_labels_and_ticker_match():
    metadata = [{"report_id": report, "source_id": report,
                 "ts_code": "600519.SH" if report == "unrelated" else "",
                 "sector": "银行" if report == "unrelated" else "宏观策略",
                 "publish_datetime": "2025-01-01",
                 "license_class": "operator_approved_internal_research_use",
                 "derived_claim_storage_allowed": True}
                for report in ("related", "unrelated")]
    footprints = [{"footprint_id": report, "report_id": report, "source_id": report,
                   "source_span_ids": ["PRIVATE"], "research_case": case}
                  for report, case in [
                      ("related", {"question": "银行在高利率环境下如何增加融资收入？",
                                   "historical_regime": "流动性收紧，融资成本上升",
                                   "reasoning_chain": ["企业提前融资", "银行中介收入增加"]}),
                      ("unrelated", {"question": "新品投放能否提高销量？",
                                     "reasoning_chain": ["新品投放", "渠道铺货增加"]}),
                  ]]
    for agent_id in ("sector.financials", "macro.us_financial_conditions"):
        context = build_rke_agent_research_context_from_rows(
            agent_id=agent_id, ticker="600519.SH", as_of_date="2026-01-01",
            metadata=metadata, footprints=footprints,
        )
        assert context["summary"]["matched_item_count"] == 2
        assert context["context_items"][0]["research_case"]["question"].startswith("银行")


@pytest.mark.parametrize("agent_id", ["cio", "decision.cio"])
@pytest.mark.parametrize("layer", ["", "decision"])
def test_decision_agent_name_is_stable_through_runtime_preflight(agent_id, layer):
    assert normalize_agent_id(agent_id, layer=layer) == "decision.cio"
    context = build_rke_agent_research_context_from_rows(
        agent_id=agent_id, layer=layer, as_of_date="2026-09-12",
    )
    assert "No matching RKE context" in rke_research_tools.format_rke_runtime_context(context)
