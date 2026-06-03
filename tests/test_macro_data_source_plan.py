from __future__ import annotations

import os
import tempfile

import pytest

from mosaic.dataflows import opencli_news
from mosaic.dataflows.tushare_catalog import (
    REQUIRED_MACRO_CATEGORIES,
    catalog_by_endpoint,
    list_endpoint_catalog,
    refresh_catalog,
    validate_catalog_coverage,
)
from mosaic.scorecard.macro_path_labels import (
    PRIMARY_LABEL_CONFIGS,
    compute_basket_path_label,
    compute_drawdown_aware_path_label,
    compute_relative_path_label,
)
from mosaic.scorecard.store import MACRO_AGENTS, ScorecardStore


def test_tushare_catalog_schema_and_required_macro_categories(tmp_path):
    rows = list_endpoint_catalog()
    assert len(rows) >= 30
    categories = {row["category"] for row in rows}
    assert REQUIRED_MACRO_CATEGORIES <= categories
    for row in rows:
        assert row["endpoint_name"]
        assert row["doc_url"].startswith("https://tushare.pro/document/2")
        assert row["catalog_status"] in {
            "scoring_candidate",
            "evidence_candidate",
            "deferred_unverified",
            "not_macro_relevant",
        }
        assert row["point_in_time_rule"]
    assert validate_catalog_coverage()["ok"] is True
    out = tmp_path / "catalog.json"
    written = refresh_catalog(out)
    assert out.exists()
    assert len(written) == len(rows)


def test_tushare_catalog_contains_plan_endpoints():
    by_endpoint = catalog_by_endpoint()
    for endpoint in (
        "daily",
        "index_daily",
        "fund_daily",
        "fund_nav",
        "fut_daily",
        "fx_daily",
        "cb_daily",
        "cn_pmi",
        "cn_gdp",
        "cn_cpi",
        "cn_ppi",
        "shibor",
        "shibor_quote",
        "hibor",
        "yc_cb",
        "moneyflow",
        "moneyflow_ind_ths",
        "fund_share",
        "top_list",
        "ths_hot",
        "dc_hot",
        "margin_secs",
        "limit_list_ths",
        "news",
        "research_report",
    ):
        assert endpoint in by_endpoint


def test_macro_series_and_documents_are_point_in_time_stores():
    with tempfile.TemporaryDirectory() as d:
        store = ScorecardStore(db_path=os.path.join(d, "t.db"))
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

        store.append_macro_documents(
            {
                "document_id": "doc-1",
                "source": "opencli",
                "channel": "google_news",
                "query": "PBOC MLF",
                "title": "PBOC injects liquidity",
                "url": "https://example.com/a",
                "published_at": "2024-01-02T09:00:00+08:00",
                "discovered_at": "2024-01-02T10:00:00+08:00",
                "content_hash": "hash-1",
                "content_excerpt": "liquidity support",
                "agent_tags": ["central_bank"],
                "event_tags": ["liquidity"],
                "sentiment_score": 0.3,
                "quality_score": 0.8,
            }
        )
        assert store.list_macro_documents(agent="central_bank", discovered_at_lte="2024-01-02T10:00:00+08:00")
        assert not store.list_macro_documents(agent="central_bank", discovered_at_lte="2024-01-02T09:30:00+08:00")


def test_opencli_macro_document_collection_and_persistence(monkeypatch):
    calls = []

    def fake_safe_run(args):
        calls.append(args)
        return (
            [
                {
                    "title": "PBOC adds liquidity",
                    "url": "https://example.com/pboc",
                    "date": "2024-01-02",
                    "snippet": "central bank operation",
                },
                {
                    "title": "Future item",
                    "url": "https://example.com/future",
                    "date": "2024-01-20",
                    "snippet": "should be filtered",
                },
            ],
            None,
        )

    monkeypatch.setattr(opencli_news, "_safe_run_opencli", fake_safe_run)
    docs = opencli_news.collect_macro_documents(
        "2024-01-05",
        look_back_days=7,
        agents=["central_bank"],
        per_query_limit=2,
        discovered_at="2024-01-05T23:59:59+08:00",
    )
    assert calls
    assert docs
    assert all(doc["source"] == "opencli" for doc in docs)
    assert all(doc["agent_tags"] == ["central_bank"] for doc in docs)
    assert all(doc["discovered_at"] == "2024-01-05T23:59:59+08:00" for doc in docs)
    assert "Future item" not in {doc["title"] for doc in docs}

    with tempfile.TemporaryDirectory() as d:
        store = ScorecardStore(db_path=os.path.join(d, "t.db"))
        n = opencli_news.persist_macro_documents(
            store,
            "2024-01-05",
            look_back_days=7,
            agents=["central_bank"],
            per_query_limit=2,
            discovered_at="2024-01-05T23:59:59+08:00",
        )
        assert n == len(docs)
        persisted = store.list_macro_documents(agent="central_bank", discovered_at_lte="2024-01-05T23:59:59+08:00")
        assert len(persisted) == len(docs)


def test_opencli_macro_document_collection_uses_crawl_time_by_default(monkeypatch):
    def fake_safe_run(args):
        return (
            [
                {
                    "title": "PBOC adds liquidity",
                    "url": "https://example.com/pboc",
                    "date": "2024-01-02",
                    "snippet": "central bank operation",
                }
            ],
            None,
        )

    monkeypatch.setattr(opencli_news, "_safe_run_opencli", fake_safe_run)
    monkeypatch.setattr(opencli_news, "_now_iso", lambda: "2026-06-03T00:00:00+00:00")
    docs = opencli_news.collect_macro_documents(
        "2024-01-05",
        look_back_days=7,
        agents=["central_bank"],
        per_query_limit=1,
    )
    assert docs
    assert all(doc["discovered_at"] == "2026-06-03T00:00:00+00:00" for doc in docs)


def test_opencli_macro_document_collection_dates_queries_and_filters_rfc822(monkeypatch):
    calls = []

    def fake_safe_run(args):
        calls.append(args)
        return (
            [
                {
                    "title": "China's response to the global financial crisis",
                    "url": "https://example.com/2010",
                    "date": "Sun, 24 Jan 2010 08:00:00 GMT",
                    "snippet": "January 2010 macro policy coverage",
                },
                {
                    "title": "Current PBOC framework",
                    "url": "https://example.com/current",
                    "date": "Tue, 17 Jun 2025 03:49:49 GMT",
                    "snippet": "should not be kept for a 2010 window",
                },
                {
                    "title": "Focusing on Bank Interest Rate Risk Exposure",
                    "url": "https://www.federalreserve.gov/newsevents/speech/kohn20100129a.htm",
                    "snippet": "undated Google Search result with date embedded in URL",
                },
                {
                    "title": "Undated unrelated result",
                    "url": "https://example.com/current",
                    "snippet": "no trustworthy publication date",
                },
            ],
            None,
        )

    monkeypatch.setattr(opencli_news, "_safe_run_opencli", fake_safe_run)
    docs = opencli_news.collect_macro_documents(
        "2010-01-31",
        look_back_days=30,
        agents=["central_bank"],
        per_query_limit=2,
        discovered_at="2026-06-03T00:00:00+00:00",
    )

    assert calls
    assert all("after:2010-01-01 before:2010-02-01" in args[2] for args in calls)
    titles = {doc["title"] for doc in docs}
    assert "China's response to the global financial crisis" in titles
    assert "Focusing on Bank Interest Rate Risk Exposure" in titles
    assert "Current PBOC framework" not in titles
    assert "Undated unrelated result" not in titles


def test_macro_label_source_store_and_all_primary_configs():
    with tempfile.TemporaryDirectory() as d:
        store = ScorecardStore(db_path=os.path.join(d, "t.db"))
        store.upsert_macro_label_source(
            {
                "agent": "dollar",
                "label_type": "cny_pressure_path_5d",
                "primary_series_id": "fx:USDCNH",
                "proxy_series_ids": ["fx:USDCNH"],
                "orientation_rule": "risk_on = -USDCNH_return",
                "lookback_days": 5,
                "forward_horizon_trading_days": 5,
                "fallback_label": "benchmark_fallback_5d",
                "availability_status": "available",
                "implementation_status": "implemented",
            }
        )
        rows = store.list_macro_label_sources("dollar")
        assert rows[0]["primary_series_id"] == "fx:USDCNH"
        assert "USDCNH" in rows[0]["proxy_series_ids_json"]

    assert {cfg.agent for cfg in PRIMARY_LABEL_CONFIGS.values()} == set(MACRO_AGENTS)


def test_drawdown_aware_label_requires_two_points_and_penalises_path():
    with pytest.raises(ValueError):
        compute_drawdown_aware_path_label(
            label_type="x",
            closes=[100.0],
            vote=1,
            confidence=1.0,
            neutral_band=0.005,
            vol_scale=0.01,
            source_series_id="test",
        )
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
    assert smooth.max_drawdown_5d == pytest.approx(0.0)
    assert choppy.max_drawdown_5d < -0.1
    assert choppy.path_metric_5d < smooth.path_metric_5d


def test_relative_and_basket_path_helpers():
    relative = compute_relative_path_label([100.0, 104.0], [100.0, 101.0])
    assert relative == pytest.approx([1.0, 1.03])
    basket = compute_basket_path_label([[100.0, 110.0], [200.0, 190.0]])
    assert basket == pytest.approx([1.0, 1.025])
    dated_relative = compute_relative_path_label(
        [("2024-01-01", 100.0), ("2024-01-03", 104.0)],
        [("2024-01-01", 100.0), ("2024-01-02", 100.5), ("2024-01-03", 101.0)],
    )
    assert dated_relative == pytest.approx([1.0, 1.03])
    dated_basket = compute_basket_path_label(
        [
            [("2024-01-01", 100.0), ("2024-01-02", 105.0), ("2024-01-03", 110.0)],
            [("2024-01-01", 200.0), ("2024-01-03", 210.0)],
        ]
    )
    assert dated_basket == pytest.approx([1.0, 1.075])


# ---------------------------------------------------------------------------
# P6: rollout gate (macro_full_label_sources_enabled) + integration
# ---------------------------------------------------------------------------

import datetime as _dt  # noqa: E402
from unittest.mock import patch  # noqa: E402

from mosaic.bridge.handlers.autoresearch import _select_agent  # noqa: E402
from mosaic.bridge.handlers.prompts import _LAYER_BY_AGENT  # noqa: E402
from mosaic.default_config import DEFAULT_CONFIG  # noqa: E402
from mosaic.scorecard.macro_labels import primary_label_for_agent  # noqa: E402
from mosaic.scorecard.scorer import MacroScorer  # noqa: E402


def _ntd(d: str, n: int) -> str:
    return (_dt.date.fromisoformat(d) + _dt.timedelta(days=n)).isoformat()


def _ptd(d: str, n: int) -> str:
    return (_dt.date.fromisoformat(d) - _dt.timedelta(days=n)).isoformat()


def _cal():
    return patch.multiple(
        "mosaic.dataflows.calendar", next_trading_day=_ntd, previous_trading_day=_ptd
    )


def _macro_state(outputs: dict, date: str = "2024-01-02") -> dict:
    return {
        "active_cohort": "cohort_default",
        "as_of_date": date,
        "layer1_outputs": outputs,
        "layer1_consensus": {"stance": "BULLISH", "confidence": 0.6},
    }


def test_full_label_sources_gate_controls_primary_labels():
    # Gate OFF: no agent's primary is a new proxy/path label; the two PR #73
    # agents still keep a (benchmark-derived) primary.
    for agent in MACRO_AGENTS:
        off = primary_label_for_agent(agent, full_label_sources_enabled=False)
        assert off is None or off.label_type not in PRIMARY_LABEL_CONFIGS
        assert primary_label_for_agent(agent, full_label_sources_enabled=True) is not None
    assert (
        primary_label_for_agent("volatility", full_label_sources_enabled=False).label_type
        == "max_drawdown_5d"
    )


def test_scorer_default_gate_off_keeps_proxy_agent_off_path_label(tmp_path):
    # dollar's primary is a proxy path label → gated off by default → must NOT be
    # recorded as cny_pressure_path_5d.
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    d0 = "2024-01-02"
    store.append_macro_signals_from_state(
        _macro_state({"dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5}}, d0)
    )
    t5 = _ntd(d0, 5)
    with _cal(), \
         patch("mosaic.scorecard.scorer._fetch_close", lambda ts, date: {d0: 100.0, t5: 102.0}.get(date)), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]), \
         patch("mosaic.scorecard.scorer._fetch_instrument_series", lambda *a: [100, 101, 102]):
        MacroScorer(store, benchmark="000300.SH").score_pending("cohort_default", "2024-02-01")  # default flag
    with store._connect() as conn:
        row = conn.execute("SELECT label_type FROM macro_signals").fetchone()
    assert row["label_type"] != "cny_pressure_path_5d"  # rolled back to PR #73 behavior


def test_scorer_relative_label_falls_back_when_dates_do_not_overlap(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    d0 = "2024-01-02"
    store.append_macro_signals_from_state(
        _macro_state(
            {"central_bank": {"agent": "central_bank", "stance": "ACCOMMODATIVE", "confidence": 0.7}},
            d0,
        )
    )
    t5 = _ntd(d0, 5)
    proxy = [(d0, 100.0), (t5, 104.0)]
    benchmark = [(d0, 100.0), (_ntd(d0, 1), 101.0)]
    with _cal(), \
         patch("mosaic.scorecard.scorer._fetch_close", lambda ts, date: {d0: 100.0, t5: 102.0}.get(date)), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100.0, 102.0]), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series_dated", lambda *a: benchmark), \
         patch("mosaic.scorecard.scorer._fetch_instrument_series_dated", lambda *a: proxy):
        MacroScorer(store, benchmark="000300.SH", full_label_sources_enabled=True).score_pending(
            "cohort_default", "2024-02-01"
        )

    with store._connect() as conn:
        row = conn.execute(
            "SELECT label_type, label_source_status, source_series_id FROM macro_signals"
        ).fetchone()
    assert row["label_type"] == "rate_sensitive_path_5d"
    assert row["label_source_status"] == "fallback"
    assert row["source_series_id"].startswith("fallback:benchmark:")


def test_p6_integration_ingest_score_skill_select(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    d0 = "2024-01-02"
    outputs = {
        "central_bank": {"agent": "central_bank", "stance": "TIGHTENING", "confidence": 0.7},
        "china": {"agent": "china", "policy_direction": "PRO_GROWTH", "confidence": 0.6},
        "geopolitical": {"agent": "geopolitical", "escalation_level": 5, "confidence": 0.6},
        "dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5},
        "yield_curve": {"agent": "yield_curve", "recession_signal": "GREEN", "confidence": 0.5},
        "commodities": {"agent": "commodities", "china_demand_signal": "ACCELERATING", "confidence": 0.5},
        "volatility": {"agent": "volatility", "regime_filter": "RISK_ON", "confidence": 0.7},
        "emerging_markets": {"agent": "emerging_markets", "em_relative": "OUTPERFORMING", "confidence": 0.6},
        "news_sentiment": {"agent": "news_sentiment", "retail_sentiment_score": 0.5, "confidence": 0.6},
        "institutional_flow": {"agent": "institutional_flow", "sectors_in_out": [{"net_amount_cny": 1500}], "confidence": 0.6},
    }
    assert store.append_macro_signals_from_state(_macro_state(outputs, d0)) == 10
    t5 = _ntd(d0, 5)
    dated = [(d0, 100.0), (_ntd(d0, 1), 101.0), (t5, 102.0)]
    with _cal(), \
         patch("mosaic.scorecard.scorer._fetch_close", lambda ts, date: {d0: 100.0, t5: 102.0}.get(date)), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]), \
         patch("mosaic.scorecard.scorer._fetch_instrument_series", lambda *a: [100, 101, 102]), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series_dated", lambda *a: dated), \
         patch("mosaic.scorecard.scorer._fetch_instrument_series_dated", lambda *a: dated):
        out = MacroScorer(store, benchmark="000300.SH", full_label_sources_enabled=True).score_pending(
            "cohort_default", "2024-02-01"
        )
    assert out["macro_scored"] == 10
    skill = {r["agent"]: r for r in store.list_macro_skill("cohort_default")}
    assert len(skill) == 10
    now = _dt.datetime(2024, 3, 1, tzinfo=_dt.timezone.utc)
    chosen = _select_agent(store, "cohort_default", None, DEFAULT_CONFIG, now)
    assert _LAYER_BY_AGENT[chosen] == "macro"  # selection picks a scored macro agent


# ---------------------------------------------------------------------------
# Backtest comparison harness + Tushare document crawler
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402

from mosaic.dataflows.tushare_documents import crawl_macro_documents, _default_tushare_fetch  # noqa: E402
from mosaic.scorecard.macro_backtest import compare_label_sources  # noqa: E402


def test_compare_label_sources_reports_both_families(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    d0 = "2024-01-02"
    store.append_macro_signals_from_state(
        _macro_state(
            {
                "volatility": {"agent": "volatility", "regime_filter": "RISK_ON", "confidence": 0.7},
                "dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.6},
            },
            d0,
        )
    )
    t5 = _ntd(d0, 5)
    dated = [(d0, 100.0), (_ntd(d0, 1), 101.0), (t5, 103.0)]
    with _cal(), \
         patch("mosaic.scorecard.scorer._fetch_close", lambda ts, date: {d0: 100.0, t5: 103.0}.get(date)), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 103]), \
         patch("mosaic.scorecard.scorer._fetch_instrument_series", lambda *a: [100, 101, 103]), \
         patch("mosaic.scorecard.scorer._fetch_benchmark_series_dated", lambda *a: dated), \
         patch("mosaic.scorecard.scorer._fetch_instrument_series_dated", lambda *a: dated):
        # Compare matured raw macro_signals read-only; normal scoring has not run.
        report = compare_label_sources(store, "cohort_default", today="2024-02-01")

    assert report["n_signals"] == 2
    assert set(report["by_agent"]) == {"volatility", "dollar"}
    assert report["benchmark"]["n"] == 2
    assert report["agent_specific"]["n"] == 2
    assert 0.0 <= report["agent_specific"]["primary_rate"] <= 1.0
    assert set(report["delta"]) == {"mean_raw", "hit_rate", "sharpe"}
    with store._connect() as conn:
        scored = conn.execute("SELECT COUNT(*) FROM macro_signals WHERE scored_at IS NOT NULL").fetchone()[0]
    assert scored == 0


def test_crawl_macro_documents_persists_dedupes_and_tags(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    items = [
        {"title": "央行宣布降准", "content": "释放流动性", "datetime": "2024-01-02 09:00:00"},
        {"title": "地缘冲突升级", "content": "避险升温", "datetime": "2024-01-03 10:00:00"},
        {"title": "央行宣布降准", "content": "释放流动性", "datetime": "2024-01-02 09:00:00"},  # dup
    ]
    out = crawl_macro_documents(
        store,
        start_date="2024-01-01",
        end_date="2024-01-05",
        discovered_at="2024-01-06T00:00:00+00:00",
        fetch=lambda ep, s, e: items,
    )
    assert out["fetched"] == 3
    assert out["persisted"] == 2  # third item deduped by content hash
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT discovered_at, agent_tags_json, published_at, title, "
            "event_tags_json, sentiment_score FROM macro_documents"
        ).fetchall()
    assert len(rows) == 2
    assert all(r["discovered_at"] == "2024-01-06T00:00:00+00:00" for r in rows)
    tags = _json.loads(rows[0]["agent_tags_json"])
    assert "news_sentiment" in tags  # news endpoint's macro agents
    assert all(r["published_at"] for r in rows)
    # P4: crawler classifies at ingest — "央行宣布降准" → policy_support (risk-on),
    # "地缘冲突升级" → geopolitical_escalation (risk-off).
    by_title = {r["title"]: r for r in rows}
    easing = _json.loads(by_title["央行宣布降准"]["event_tags_json"])
    assert "policy_support" in easing
    assert by_title["央行宣布降准"]["sentiment_score"] > 0
    risk = _json.loads(by_title["地缘冲突升级"]["event_tags_json"])
    assert "geopolitical_escalation" in risk
    assert by_title["地缘冲突升级"]["sentiment_score"] < 0


def test_default_tushare_news_fetch_supplies_src(monkeypatch):
    import pandas as pd
    import mosaic.dataflows.tushare as tushare_mod

    captured = {}

    class FakePro:
        def query(self, endpoint, **params):
            captured["endpoint"] = endpoint
            captured["params"] = params
            return pd.DataFrame(
                [{"title": "央行宣布降准", "content": "释放流动性", "datetime": "2024-01-02 09:00:00"}]
            )

    monkeypatch.setattr(tushare_mod, "_get_pro_client", lambda: FakePro())
    rows = _default_tushare_fetch("news", "2024-01-01", "2024-01-05")
    assert rows
    assert captured["endpoint"] == "news"
    assert captured["params"]["src"] == "sina"
    assert captured["params"]["start_date"] == "20240101"
    assert captured["params"]["end_date"] == "20240105"


def test_crawl_macro_documents_reports_endpoint_errors(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))

    def failing_fetch(ep, start, end):
        raise RuntimeError("vendor unavailable")

    out = crawl_macro_documents(
        store,
        start_date="2024-01-01",
        end_date="2024-01-05",
        endpoints=["news"],
        fetch=failing_fetch,
    )
    assert out["fetched"] == 0
    assert out["persisted"] == 0
    assert out["errors"] == [{"endpoint": "news", "error": "RuntimeError: vendor unavailable"}]


from mosaic.scorecard.macro_events import (  # noqa: E402
    build_sentiment_index,
    classify_persisted_documents,
    classify_text,
    event_orientation,
)


def test_classify_text_is_deterministic_and_bilingual():
    up = classify_text("央行降准释放流动性，市场大涨 rally")
    assert "policy_support" in up["event_tags"]
    assert up["sentiment_score"] > 0
    assert classify_text("央行降准释放流动性，市场大涨 rally") == up  # deterministic

    down = classify_text("地缘冲突升级，避险情绪升温 selloff")
    assert "geopolitical_escalation" in down["event_tags"]
    assert "risk_off" in down["event_tags"]
    assert down["sentiment_score"] < 0

    neutral = classify_text("某公司发布季度公告")
    assert neutral == {"event_tags": [], "sentiment_score": 0.0}


def test_sentiment_index_is_point_in_time_and_requires_published_at(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    store.append_macro_documents(
        [
            # in-window, dated, discovered before as-of → counts
            {"content_hash": "h1", "source": "tushare", "agent_tags": ["news_sentiment"],
             "title": "市场大涨 rally 利好", "published_at": "2024-01-04",
             "discovered_at": "2024-01-04T00:00:00+00:00"},
            # discovered AFTER as-of → excluded (look-ahead)
            {"content_hash": "h2", "source": "tushare", "agent_tags": ["news_sentiment"],
             "title": "暴跌 risk-off", "published_at": "2024-01-04",
             "discovered_at": "2024-01-09T00:00:00+00:00"},
            # no published_at → evidence-only, never in index
            {"content_hash": "h3", "source": "tushare", "agent_tags": ["news_sentiment"],
             "title": "暴跌 risk-off", "published_at": None,
             "discovered_at": "2024-01-04T00:00:00+00:00"},
            # different agent → not counted for news_sentiment
            {"content_hash": "h4", "source": "tushare", "agent_tags": ["dollar"],
             "title": "暴跌 risk-off", "published_at": "2024-01-04",
             "discovered_at": "2024-01-04T00:00:00+00:00"},
        ]
    )
    classify_persisted_documents(store)
    idx = build_sentiment_index(store, "news_sentiment", "2024-01-05", lookback_days=7)
    assert idx["n_documents"] == 1  # only h1
    assert idx["n_evidence_only"] == 1  # h3 (undated)
    assert idx["sentiment_index"] > 0
    orient = event_orientation(idx)
    assert orient["orientation"] == 1
    assert 0.0 <= orient["strength"] <= 1.0


def test_classify_persisted_documents_is_idempotent_and_safe(tmp_path):
    store = ScorecardStore(db_path=os.path.join(tmp_path, "t.db"))
    store.append_macro_documents(
        {"content_hash": "x1", "source": "tushare", "agent_tags": ["china"],
         "title": "降准 stimulus", "published_at": "2024-01-04",
         "discovered_at": "2024-01-04T00:00:00+00:00"}
    )
    first = classify_persisted_documents(store)
    assert first["classified"] == 1
    second = classify_persisted_documents(store)  # already classified → skipped
    assert second["classified"] == 0 and second["skipped"] == 1
    # empty store never raises
    empty = ScorecardStore(db_path=os.path.join(tmp_path, "empty.db"))
    assert classify_persisted_documents(empty) == {"classified": 0, "skipped": 0, "total": 0}
