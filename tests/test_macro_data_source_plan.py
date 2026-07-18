from __future__ import annotations

import os
from pathlib import Path

import pytest

from mosaic.dataflows.tushare_catalog import (
    DISABLED_PERMISSION_ENDPOINTS,
    DYNAMIC_PERMISSION_DENIAL_ENDPOINTS,
    OPERATOR_DISABLED_PERMISSION_ENDPOINTS,
    PREFLIGHT_ENDPOINT_CHECKS,
    TUSHARE_ENDPOINT_IDS,
    TUSHARE_ENDPOINT_REGISTRY_VERSION,
    VERIFIED_ENDPOINT_PREFLIGHTS,
    assert_endpoint_runtime_enabled,
    catalog_by_endpoint,
    endpoint_registration,
    list_endpoint_catalog,
    promote_verified_endpoint,
    refresh_catalog,
    validate_catalog_coverage,
)
from mosaic.dataflows.tushare_documents import crawl_macro_documents
from mosaic.scorecard.macro_labels import (
    MACRO_LABEL_INVENTORY,
    primary_label_for_agent,
)
from mosaic.scorecard.macro_aggregation import MACRO_AGENTS as MACRO_AGENT_ORDER
from mosaic.scorecard.macro_path_labels import (
    PRIMARY_LABEL_CONFIGS,
    compute_basket_path_label,
    compute_drawdown_aware_path_label,
    compute_relative_path_label,
)
from mosaic.scorecard.store import MACRO_AGENTS, ScorecardStore


def test_closed_tushare_registry_covers_exact_v2_endpoint_union(tmp_path: Path):
    rows = list_endpoint_catalog()
    assert len(rows) == len(TUSHARE_ENDPOINT_IDS) == len(set(TUSHARE_ENDPOINT_IDS))
    assert {row["endpoint"] for row in rows} == set(TUSHARE_ENDPOINT_IDS)
    assert all(
        row["registry_version"] == TUSHARE_ENDPOINT_REGISTRY_VERSION for row in rows
    )
    assert all(row["agent_tool_exposed"] is False for row in rows)
    assert validate_catalog_coverage()["ok"] is True

    output = tmp_path / "tushare-registry.json"
    assert refresh_catalog(output) == rows
    assert output.exists()
    assert "content" not in output.read_text(encoding="utf-8")


def test_permission_denied_endpoints_are_hard_disabled_and_never_promoted():
    by_endpoint = catalog_by_endpoint()
    assert OPERATOR_DISABLED_PERMISSION_ENDPOINTS == {
        "major_news",
        "news",
        "npr",
        "monetary_policy",
    }
    assert DYNAMIC_PERMISSION_DENIAL_ENDPOINTS == {"yc_cb"}
    assert DISABLED_PERMISSION_ENDPOINTS == (
        OPERATOR_DISABLED_PERMISSION_ENDPOINTS | DYNAMIC_PERMISSION_DENIAL_ENDPOINTS
    )
    for endpoint in DISABLED_PERMISSION_ENDPOINTS:
        row = by_endpoint[endpoint]
        assert row["status"] == "DISABLED_PERMISSION_DENIED"
        assert row["runtime_client_enabled"] is False
        assert row["permission_evidence_id"]
        with pytest.raises(PermissionError, match="NOT_ACTIVE"):
            assert_endpoint_runtime_enabled(endpoint)
        with pytest.raises(ValueError, match="new registry revision"):
            promote_verified_endpoint(
                endpoint,
                permission_checked_at="2026-07-17T00:00:00Z",
                permission_evidence_id="permission-smoke",
                schema_contract_version="schema-v1",
            )


def test_verified_eco_cal_and_precheck_endpoints_have_distinct_runtime_permissions():
    assert set(PREFLIGHT_ENDPOINT_CHECKS) == set(TUSHARE_ENDPOINT_IDS)
    eco_cal = endpoint_registration("eco_cal")
    assert eco_cal.status == "ACTIVE_VERIFIED"
    assert eco_cal.runtime_client_enabled is True
    assert (
        eco_cal.permission_evidence_id
        == (VERIFIED_ENDPOINT_PREFLIGHTS["eco_cal"]["permission_evidence_id"])
    )
    assert_endpoint_runtime_enabled("eco_cal")

    registration = endpoint_registration("cn_pmi")
    assert registration.status == "PRECHECK_REQUIRED"
    assert registration.runtime_client_enabled is False
    with pytest.raises(PermissionError, match="PRECHECK_REQUIRED"):
        assert_endpoint_runtime_enabled("cn_pmi")
    with pytest.raises(ValueError, match="DENY_UNKNOWN_ENDPOINT"):
        endpoint_registration("another_news_fallback")

    promoted = promote_verified_endpoint(
        "cn_pmi",
        permission_checked_at="2026-07-17T00:00:00Z",
        permission_evidence_id="permission-smoke-cn-pmi",
        schema_contract_version="cn_pmi_pit_schema_v1",
    )
    assert promoted.status == "ACTIVE_VERIFIED"
    assert promoted.runtime_client_enabled is True


def test_disabled_document_crawler_does_not_construct_client_or_call_fetch():
    called = False

    def forbidden_fetch(*_args):
        nonlocal called
        called = True
        raise AssertionError("fetch callback must not run")

    result = crawl_macro_documents(
        object(),
        start_date="2026-07-01",
        end_date="2026-07-17",
        endpoints=["news", "major_news", "npr", "monetary_policy"],
        fetch=forbidden_fetch,
    )
    assert called is False
    assert result["fetched"] == result["persisted"] == 0
    assert result["runtime_client_constructed"] is False
    assert {row["endpoint"] for row in result["errors"]} == (
        OPERATOR_DISABLED_PERMISSION_ENDPOINTS
    )
    assert all("DISABLED_PERMISSION_DENIED" in row["error"] for row in result["errors"])


def test_macro_series_store_enforces_point_in_time_cutoff(tmp_path: Path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "scorecard.db"))
    store.append_macro_series(
        {
            "series_id": "fx:USDCNH",
            "source": "tushare",
            "endpoint_name": "fx_daily",
            "instrument": "USDCNH.FXCM",
            "date": "2024-01-02",
            "close": 7.1,
            "as_of_date": "2024-01-02",
            "metadata": {"field": "bid_close"},
        }
    )
    store.append_macro_series(
        {
            "series_id": "fx:USDCNH",
            "source": "tushare",
            "endpoint_name": "fx_daily",
            "instrument": "USDCNH.FXCM",
            "date": "2024-01-03",
            "close": 7.0,
            "as_of_date": "2024-01-03",
        }
    )
    rows = store.list_macro_series(
        "fx:USDCNH",
        start_date="2024-01-01",
        end_date="2024-01-03",
        as_of_date="2024-01-02",
    )
    assert [row["date"] for row in rows] == ["2024-01-02"]
    assert rows[0]["metadata_json"]


def test_all_ten_macro_agents_have_unique_v2_labels_and_no_implicit_fallback():
    assert tuple(spec.agent for spec in MACRO_LABEL_INVENTORY) == MACRO_AGENT_ORDER
    assert len(MACRO_LABEL_INVENTORY) == len(PRIMARY_LABEL_CONFIGS) == 10
    assert {spec.label_type for spec in MACRO_LABEL_INVENTORY} == set(
        PRIMARY_LABEL_CONFIGS
    )
    assert all(spec.fallback_label is None for spec in MACRO_LABEL_INVENTORY)
    assert all(
        spec.outcome_contract_version == "macro_transmission_outcome_v2"
        for spec in MACRO_LABEL_INVENTORY
    )
    for agent in MACRO_AGENTS:
        assert (
            primary_label_for_agent(agent, full_label_sources_enabled=True) is not None
        )
        assert primary_label_for_agent(agent, full_label_sources_enabled=False) is None
    for legacy in (
        "dollar",
        "yield_curve",
        "volatility",
        "emerging_markets",
        "news_sentiment",
    ):
        assert primary_label_for_agent(legacy) is None


def test_path_helpers_preserve_dates_and_drawdown_penalty():
    relative = compute_relative_path_label(
        [("2024-01-01", 100.0), ("2024-01-03", 104.0)],
        [("2024-01-01", 100.0), ("2024-01-02", 100.5), ("2024-01-03", 101.0)],
    )
    assert relative == pytest.approx([1.0, 1.03])
    basket = compute_basket_path_label(
        [
            [("2024-01-01", 100.0), ("2024-01-03", 110.0)],
            [("2024-01-01", 200.0), ("2024-01-03", 210.0)],
        ]
    )
    assert basket == pytest.approx([1.0, 1.075])

    smooth = compute_drawdown_aware_path_label(
        label_type="smooth",
        closes=[100.0, 101.0, 102.0],
        vote=1,
        confidence=1.0,
        neutral_band=0.005,
        vol_scale=0.01,
        source_series_id="smooth",
    )
    choppy = compute_drawdown_aware_path_label(
        label_type="choppy",
        closes=[100.0, 80.0, 102.0],
        vote=1,
        confidence=1.0,
        neutral_band=0.005,
        vol_scale=0.01,
        source_series_id="choppy",
    )
    assert choppy.max_drawdown_5d < -0.1
    assert choppy.path_metric_5d < smooth.path_metric_5d
