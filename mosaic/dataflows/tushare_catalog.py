"""Tushare endpoint catalog for macro-agent data-source planning.

The live Tushare document site is the source of truth, but CI and backtests
must work offline. This module therefore keeps a tracked snapshot of the
endpoint categories MOSAIC currently depends on and exposes a refresh/validate
surface that can later be wired to a live document crawler without changing
callers.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CATALOG_STATUSES = {
    "scoring_candidate",
    "evidence_candidate",
    "deferred_unverified",
    "not_macro_relevant",
}

REQUIRED_MACRO_CATEGORIES = {
    "沪深股票",
    "指数",
    "ETF",
    "公募基金",
    "期货",
    "期权",
    "外汇",
    "债券",
    "宏观经济",
    "资金流",
    "两融",
    "港股",
    "美股",
    "热榜",
    "新闻快讯",
    "券商研报",
    "大模型语料专题",
}


@dataclass(frozen=True)
class TushareEndpointCatalogEntry:
    endpoint_name: str
    doc_path: str
    doc_url: str
    category: str
    sub_category: str
    params: tuple[str, ...]
    default_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    date_fields: tuple[str, ...]
    update_frequency: str
    min_points_or_permission: str
    path_capable: bool
    event_capable: bool
    point_in_time_rule: str
    agent_tags: tuple[str, ...]
    label_candidate_tags: tuple[str, ...]
    catalog_status: str
    verification_status: str = "snapshot"
    verified_at: str = ""

    def as_dict(self) -> dict:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        return data


def _entry(
    endpoint_name: str,
    category: str,
    sub_category: str,
    *,
    params: Iterable[str] = (),
    fields: Iterable[str] = (),
    optional_fields: Iterable[str] = (),
    date_fields: Iterable[str] = (),
    update_frequency: str = "unknown",
    permission: str = "see Tushare Pro points/permission",
    path_capable: bool = False,
    event_capable: bool = False,
    point_in_time_rule: str = "filter by as_of date; do not use rows published later",
    agent_tags: Iterable[str] = (),
    label_tags: Iterable[str] = (),
    status: str = "deferred_unverified",
    doc_id: str = "",
) -> TushareEndpointCatalogEntry:
    if status not in CATALOG_STATUSES:
        raise ValueError(f"unsupported catalog status {status!r}")
    doc_url = "https://tushare.pro/document/2"
    if doc_id:
        doc_url = f"{doc_url}?doc_id={doc_id}"
    return TushareEndpointCatalogEntry(
        endpoint_name=endpoint_name,
        doc_path=f"/数据接口/{category}/{sub_category}",
        doc_url=doc_url,
        category=category,
        sub_category=sub_category,
        params=tuple(params),
        default_fields=tuple(fields),
        optional_fields=tuple(optional_fields),
        date_fields=tuple(date_fields),
        update_frequency=update_frequency,
        min_points_or_permission=permission,
        path_capable=path_capable,
        event_capable=event_capable,
        point_in_time_rule=point_in_time_rule,
        agent_tags=tuple(agent_tags),
        label_candidate_tags=tuple(label_tags),
        catalog_status=status,
    )


DEFAULT_ENDPOINT_CATALOG: tuple[TushareEndpointCatalogEntry, ...] = (
    _entry(
        "daily", "沪深股票", "行情数据/历史日线",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("institutional_flow", "news_sentiment", "china"),
        label_tags=("basket_path", "market_breadth_path"),
        status="scoring_candidate",
        doc_id="27",
    ),
    _entry(
        "index_daily", "指数", "指数日线行情",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("central_bank", "china", "yield_curve", "volatility", "news_sentiment"),
        label_tags=("relative_path", "benchmark_path", "drawdown_path"),
        status="scoring_candidate",
    ),
    _entry(
        "index_basic", "指数", "指数基本信息",
        params=("ts_code", "market", "publisher", "category", "name"),
        fields=("ts_code", "name", "fullname", "market", "publisher", "category"),
        update_frequency="reference",
        agent_tags=("china", "central_bank", "yield_curve"),
        label_tags=("proxy_discovery",),
        status="evidence_candidate",
    ),
    _entry(
        "index_member", "指数", "申万行业成分",
        params=("index_code", "ts_code", "is_new"),
        fields=("index_code", "con_code", "in_date", "out_date", "is_new"),
        date_fields=("in_date", "out_date"),
        update_frequency="reference",
        event_capable=True,
        agent_tags=("china", "institutional_flow"),
        label_tags=("sector_basket_construction",),
        status="evidence_candidate",
    ),
    _entry(
        "fund_daily", "ETF", "ETF日线行情",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("central_bank", "yield_curve", "volatility", "emerging_markets"),
        label_tags=("rate_sensitive_path", "em_hk_relative_path", "volatility_proxy_path"),
        status="scoring_candidate",
    ),
    _entry(
        "fund_nav", "公募基金", "基金净值",
        params=("ts_code", "nav_date", "start_date", "end_date", "market"),
        fields=("ts_code", "nav_date", "unit_nav", "accum_nav", "adj_nav"),
        date_fields=("nav_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("emerging_markets", "central_bank"),
        label_tags=("fund_proxy_path",),
        status="scoring_candidate",
    ),
    _entry(
        "fund_basic", "公募基金", "基金列表",
        params=("ts_code", "market", "status"),
        fields=("ts_code", "name", "fund_type", "benchmark", "status", "market"),
        update_frequency="reference",
        agent_tags=("central_bank", "emerging_markets"),
        label_tags=("proxy_discovery",),
        status="evidence_candidate",
    ),
    _entry(
        "fund_share", "公募基金", "基金规模",
        params=("ts_code", "trade_date", "start_date", "end_date", "market"),
        fields=("ts_code", "trade_date", "fd_share"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=False,
        event_capable=True,
        agent_tags=("institutional_flow",),
        label_tags=("flow_followthrough_path",),
        status="evidence_candidate",
    ),
    _entry(
        "etf_index", "ETF", "ETF基准指数",
        params=("ts_code", "pub_date", "base_date"),
        fields=("ts_code", "indx_name", "indx_csname", "pub_party_name", "pub_date"),
        date_fields=("pub_date", "base_date"),
        update_frequency="reference",
        agent_tags=("central_bank", "emerging_markets"),
        label_tags=("proxy_discovery",),
        status="evidence_candidate",
    ),
    _entry(
        "fut_daily", "期货", "日线行情",
        params=("ts_code", "trade_date", "start_date", "end_date", "exchange"),
        fields=("ts_code", "trade_date", "open", "high", "low", "close", "settle", "vol", "oi"),
        optional_fields=("oi_chg", "delv_settle"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("commodities", "geopolitical"),
        label_tags=("commodity_basket_path", "oil_or_gold_shock_path"),
        status="scoring_candidate",
    ),
    _entry(
        "fut_basic", "期货", "合约信息",
        params=("exchange", "fut_code", "fut_type", "list_date"),
        fields=("ts_code", "symbol", "exchange", "name", "fut_code", "list_date", "delist_date"),
        date_fields=("list_date", "delist_date"),
        update_frequency="reference",
        agent_tags=("commodities",),
        label_tags=("commodity_contract_mapping",),
        status="evidence_candidate",
    ),
    _entry(
        "rt_fut_min", "期货", "实时分钟行情",
        params=("ts_code", "freq"),
        fields=("code", "freq", "time", "open", "close", "high", "low", "vol", "amount", "oi"),
        date_fields=("time",),
        update_frequency="realtime",
        path_capable=True,
        agent_tags=("commodities", "volatility"),
        label_tags=("intraday_shock_detection",),
        status="deferred_unverified",
    ),
    _entry(
        "opt_basic", "期权", "期权合约信息",
        params=("ts_code", "exchange", "opt_code", "call_put", "list_date"),
        fields=("ts_code", "exchange", "name", "call_put", "exercise_price", "maturity_date"),
        date_fields=("list_date", "maturity_date"),
        update_frequency="reference",
        agent_tags=("volatility",),
        label_tags=("volatility_proxy_discovery",),
        status="deferred_unverified",
    ),
    _entry(
        "ft_tick", "期权", "TICK数据",
        params=("symbol", "start_date", "end_date"),
        fields=("symbol", "trade_time", "price", "vol", "amount", "oi"),
        date_fields=("trade_time", "start_date", "end_date"),
        update_frequency="realtime",
        path_capable=True,
        agent_tags=("volatility", "commodities"),
        label_tags=("volatility_shock_path",),
        status="deferred_unverified",
    ),
    _entry(
        "fx_daily", "外汇", "外汇日线行情",
        params=("ts_code", "trade_date", "start_date", "end_date", "exchange"),
        fields=("ts_code", "trade_date", "bid_open", "bid_close", "ask_open", "ask_close"),
        optional_fields=("tick_qty", "exchange"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("dollar", "emerging_markets", "geopolitical"),
        label_tags=("cny_pressure_path", "risk_appetite_path"),
        status="scoring_candidate",
        doc_id="179",
    ),
    _entry(
        "fx_obasic", "外汇", "外汇基础信息（海外）",
        params=("exchange", "classify"),
        fields=("ts_code", "name", "exchange", "classify"),
        optional_fields=("min_unit", "max_unit", "pip", "pip_cost"),
        update_frequency="reference",
        path_capable=False,
        event_capable=False,
        agent_tags=("dollar", "emerging_markets"),
        label_tags=("dollar_proxy_discovery", "fx_proxy_discovery"),
        status="evidence_candidate",
        doc_id="178",
    ),
    _entry(
        "yc_cb", "债券", "国债收益率曲线",
        params=("ts_code", "trade_date", "start_date", "end_date", "curve_type", "curve_term"),
        fields=("trade_date", "ts_code", "curve_name", "curve_type", "curve_term", "yield"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=False,
        event_capable=True,
        agent_tags=("central_bank", "yield_curve", "dollar"),
        label_tags=("curve_state_feature",),
        status="evidence_candidate",
    ),
    _entry(
        "us_tycr", "国际宏观", "美国国债收益率曲线利率",
        params=("date", "start_date", "end_date", "fields"),
        fields=("date", "m1", "m2", "m3", "m6", "y1", "y2", "y3", "y5", "y7", "y10", "y20", "y30"),
        date_fields=("date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        event_capable=True,
        agent_tags=("yield_curve", "dollar", "emerging_markets"),
        label_tags=("us_curve_state_feature", "rate_spread_path"),
        status="evidence_candidate",
        doc_id="219",
    ),
    _entry(
        "cb_daily", "债券", "可转债行情",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("ts_code", "trade_date", "open", "high", "low", "close", "pct_chg"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        path_capable=True,
        agent_tags=("central_bank", "yield_curve"),
        label_tags=("rate_sensitive_path",),
        status="scoring_candidate",
    ),
    _entry(
        "cb_rate", "债券", "可转债票面利率",
        params=("ts_code",),
        fields=("ts_code", "coupon_rate", "rate_start_date", "rate_end_date"),
        date_fields=("rate_start_date", "rate_end_date"),
        update_frequency="reference",
        status="not_macro_relevant",
    ),
    _entry(
        "cn_pmi", "宏观经济", "国内宏观/景气度/采购经理指数",
        params=("m", "start_m", "end_m"),
        fields=("month", "pmi010000", "pmi010100", "pmi010200"),
        date_fields=("month", "start_m", "end_m"),
        update_frequency="monthly",
        event_capable=True,
        agent_tags=("china",),
        label_tags=("china_growth_event",),
        status="evidence_candidate",
    ),
    _entry(
        "cn_gdp", "宏观经济", "国内宏观/国民经济/GDP",
        params=("q", "start_q", "end_q"),
        fields=("quarter", "gdp", "gdp_yoy", "pi_yoy", "si_yoy", "ti_yoy"),
        date_fields=("quarter", "start_q", "end_q"),
        update_frequency="quarterly",
        event_capable=True,
        agent_tags=("china",),
        label_tags=("china_growth_event",),
        status="evidence_candidate",
    ),
    _entry(
        "cn_cpi", "宏观经济", "国内宏观/价格指数/CPI",
        params=("m", "start_m", "end_m"),
        fields=("month", "nt_val", "nt_yoy", "nt_mom"),
        date_fields=("month", "start_m", "end_m"),
        update_frequency="monthly",
        event_capable=True,
        agent_tags=("china", "central_bank"),
        label_tags=("inflation_event",),
        status="evidence_candidate",
    ),
    _entry(
        "cn_ppi", "宏观经济", "国内宏观/价格指数/PPI",
        params=("m", "start_m", "end_m"),
        fields=("month", "ppi_yoy", "ppi_mom", "ppi_accu"),
        date_fields=("month", "start_m", "end_m"),
        update_frequency="monthly",
        event_capable=True,
        agent_tags=("china", "commodities"),
        label_tags=("inflation_event", "commodity_demand_event"),
        status="evidence_candidate",
    ),
    _entry(
        "shibor", "宏观经济", "国内宏观/利率数据/Shibor利率",
        params=("date", "start_date", "end_date"),
        fields=("date", "on", "1w", "2w", "1m", "3m", "6m", "9m", "1y"),
        date_fields=("date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("central_bank", "yield_curve"),
        label_tags=("liquidity_state_feature",),
        status="evidence_candidate",
    ),
    _entry(
        "shibor_quote", "宏观经济", "国内宏观/利率数据/Shibor报价数据",
        params=("date", "start_date", "end_date", "bank"),
        fields=("date", "bank", "on_b", "on_a", "1w_b", "1w_a", "3m_b", "3m_a"),
        date_fields=("date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("central_bank",),
        label_tags=("liquidity_state_feature",),
        status="evidence_candidate",
    ),
    _entry(
        "hibor", "宏观经济", "国内宏观/利率数据/Hibor利率",
        params=("date", "start_date", "end_date"),
        fields=("date", "on", "1w", "1m", "3m", "6m", "12m"),
        date_fields=("date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("yield_curve", "dollar", "emerging_markets"),
        label_tags=("offshore_liquidity_feature",),
        status="evidence_candidate",
    ),
    _entry(
        "moneyflow", "资金流", "沪深股票/个股资金流向",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("ts_code", "trade_date", "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount", "net_mf_amount"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("institutional_flow",),
        label_tags=("flow_followthrough_path",),
        status="evidence_candidate",
    ),
    _entry(
        "moneyflow_ind_ths", "资金流", "沪深股票/行业资金流向（THS）",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("trade_date", "ts_code", "industry", "lead_stock", "net_amount", "pct_change"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("institutional_flow", "china", "news_sentiment"),
        label_tags=("sector_flow_followthrough_path", "market_breadth_path"),
        status="evidence_candidate",
    ),
    _entry(
        "top_list", "资金流", "沪深股票/龙虎榜",
        params=("trade_date",),
        fields=("trade_date", "ts_code", "name", "close", "pct_change", "net_amount"),
        date_fields=("trade_date",),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("institutional_flow",),
        label_tags=("concentrated_flow_event",),
        status="evidence_candidate",
    ),
    _entry(
        "margin_secs", "两融", "融资融券标的（盘前）",
        params=("ts_code", "trade_date", "start_date", "end_date", "exchange"),
        fields=("trade_date", "ts_code", "name", "exchange"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("institutional_flow", "news_sentiment"),
        label_tags=("risk_appetite_feature",),
        status="evidence_candidate",
    ),
    _entry(
        "limit_list_ths", "热榜", "同花顺涨跌停榜单",
        params=("ts_code", "trade_date", "start_date", "end_date", "limit_type", "market"),
        fields=("trade_date", "ts_code", "name", "pct_chg", "limit_type", "tag", "status"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        agent_tags=("news_sentiment", "institutional_flow"),
        label_tags=("market_heat_breadth_path",),
        status="evidence_candidate",
    ),
    _entry(
        "ths_hot", "热榜", "同花顺App热榜数",
        params=("ts_code", "trade_date", "market", "is_new"),
        fields=("trade_date", "data_type", "ts_code", "ts_name", "rank", "pct_change", "hot", "rank_time"),
        date_fields=("trade_date", "rank_time"),
        update_frequency="intraday",
        event_capable=True,
        agent_tags=("news_sentiment", "commodities"),
        label_tags=("sentiment_followthrough_path", "market_heat_breadth_path"),
        status="evidence_candidate",
    ),
    _entry(
        "dc_hot", "热榜", "东方财富App热榜",
        params=("ts_code", "trade_date", "market", "hot_type", "is_new"),
        fields=("trade_date", "data_type", "ts_code", "ts_name", "rank", "pct_change", "rank_time"),
        date_fields=("trade_date", "rank_time"),
        update_frequency="intraday",
        event_capable=True,
        agent_tags=("news_sentiment",),
        label_tags=("sentiment_followthrough_path",),
        status="evidence_candidate",
    ),
    _entry(
        "news", "新闻快讯", "大模型语料专题/新闻快讯（短讯）",
        params=("src", "start_date", "end_date"),
        fields=("datetime", "content", "title"),
        optional_fields=("channels",),
        date_fields=("datetime", "start_date", "end_date"),
        update_frequency="realtime",
        event_capable=True,
        point_in_time_rule="published datetime must be <= signal as_of datetime",
        agent_tags=("china", "geopolitical", "news_sentiment"),
        label_tags=("policy_event", "sentiment_event", "geopolitical_event"),
        status="evidence_candidate",
    ),
    _entry(
        "llm_corpus_topic", "大模型语料专题", "语料专题目录",
        params=("src", "start_date", "end_date"),
        fields=("datetime", "content", "title", "channels"),
        date_fields=("datetime", "start_date", "end_date"),
        update_frequency="realtime",
        event_capable=True,
        point_in_time_rule="corpus rows must be discovered/published before signal scoring",
        agent_tags=("china", "geopolitical", "news_sentiment"),
        label_tags=("document_event_pipeline",),
        status="evidence_candidate",
    ),
    _entry(
        "research_report", "券商研报", "券商研究报告",
        params=("ts_code", "trade_date", "start_date", "end_date", "report_type", "ind_name", "inst_csname"),
        fields=("trade_date", "abstr", "title", "report_type", "author", "name", "ts_code", "inst_csname", "ind_name", "url"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="twice daily",
        event_capable=True,
        point_in_time_rule="trade_date must be <= signal date; publication lag must be respected when available",
        agent_tags=("china", "commodities", "news_sentiment", "geopolitical"),
        label_tags=("policy_event", "commodity_demand_event", "sentiment_event"),
        status="evidence_candidate",
    ),
    _entry(
        "hk_basic", "港股", "港股基础信息",
        params=("ts_code", "list_status"),
        fields=("ts_code", "name", "fullname", "market", "list_status", "list_date", "delist_date"),
        date_fields=("list_date", "delist_date"),
        update_frequency="reference",
        agent_tags=("emerging_markets", "dollar"),
        label_tags=("hk_proxy_discovery",),
        status="evidence_candidate",
    ),
    _entry(
        "hk_tradecal", "港股", "港股交易日历",
        params=("start_date", "end_date", "is_open"),
        fields=("cal_date", "is_open", "pretrade_date"),
        date_fields=("cal_date", "start_date", "end_date"),
        update_frequency="calendar",
        agent_tags=("emerging_markets",),
        label_tags=("calendar_alignment",),
        status="evidence_candidate",
    ),
    _entry(
        "rt_hk_tick", "港股", "港股实时行情",
        params=("ts_code",),
        fields=("code", "trade_time", "pre_close", "price", "high", "open", "low", "close", "vol", "amount"),
        date_fields=("trade_time",),
        update_frequency="realtime",
        path_capable=True,
        agent_tags=("emerging_markets", "dollar"),
        label_tags=("intraday_hk_proxy_path",),
        status="deferred_unverified",
    ),
    _entry(
        "us_basic", "美股", "美股基础信息",
        params=("ts_code", "classify", "limit", "offset"),
        fields=("ts_code", "name", "classify", "list_date", "delist_date"),
        date_fields=("list_date", "delist_date"),
        update_frequency="reference",
        agent_tags=("emerging_markets", "dollar", "geopolitical"),
        label_tags=("us_proxy_discovery",),
        status="evidence_candidate",
    ),
    _entry(
        "stock_basic", "沪深股票", "基础数据/股票列表",
        params=("ts_code", "name", "market", "list_status", "exchange", "is_hs"),
        fields=("ts_code", "symbol", "name", "area", "industry", "market", "list_date", "delist_date"),
        date_fields=("list_date", "delist_date"),
        update_frequency="reference",
        agent_tags=("institutional_flow", "china", "news_sentiment"),
        label_tags=("basket_construction", "industry_mapping"),
        status="evidence_candidate",
    ),
    _entry(
        "stock_vx", "沪深股票", "小佩数据/估值因子",
        params=("ts_code", "trade_date", "start_date", "end_date"),
        fields=("trade_date", "ts_code", "level1", "level2", "vxx", "vs"),
        date_fields=("trade_date", "start_date", "end_date"),
        update_frequency="daily",
        event_capable=True,
        status="not_macro_relevant",
    ),
)


def list_endpoint_catalog() -> list[dict]:
    """Return the tracked endpoint catalog as JSON-serialisable dictionaries."""
    return [entry.as_dict() for entry in DEFAULT_ENDPOINT_CATALOG]


def catalog_by_endpoint() -> dict[str, dict]:
    return {row["endpoint_name"]: row for row in list_endpoint_catalog()}


def validate_catalog_coverage(
    entries: Iterable[TushareEndpointCatalogEntry] = DEFAULT_ENDPOINT_CATALOG,
) -> dict[str, object]:
    rows = list(entries)
    categories = {row.category for row in rows}
    missing_categories = sorted(REQUIRED_MACRO_CATEGORIES - categories)
    invalid_status = sorted(
        {row.catalog_status for row in rows if row.catalog_status not in CATALOG_STATUSES}
    )
    missing_pit = sorted(row.endpoint_name for row in rows if not row.point_in_time_rule)
    return {
        "ok": not missing_categories and not invalid_status and not missing_pit,
        "n_endpoints": len(rows),
        "categories": sorted(categories),
        "missing_categories": missing_categories,
        "invalid_status": invalid_status,
        "missing_point_in_time_rule": missing_pit,
    }


def refresh_catalog(snapshot_path: str | Path | None = None) -> list[dict]:
    """Write the current tracked snapshot to disk and return it.

    The function name is intentionally future-proof: a live document crawler can
    replace the body later while keeping CLI/tests stable.
    """
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = []
    for entry in DEFAULT_ENDPOINT_CATALOG:
        data = entry.as_dict()
        data["verified_at"] = data.get("verified_at") or generated_at
        rows.append(data)
    if snapshot_path is not None:
        path = Path(snapshot_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return rows


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or validate the Tushare endpoint catalog snapshot.")
    parser.add_argument("command", choices=("refresh", "validate", "list"))
    parser.add_argument("--out", default="", help="Optional JSON snapshot output path for refresh.")
    args = parser.parse_args(argv)
    if args.command == "refresh":
        rows = refresh_catalog(args.out or None)
        print(json.dumps({"n_endpoints": len(rows)}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "validate":
        result = validate_catalog_coverage()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    print(json.dumps(list_endpoint_catalog(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = [
    "CATALOG_STATUSES",
    "DEFAULT_ENDPOINT_CATALOG",
    "REQUIRED_MACRO_CATEGORIES",
    "TushareEndpointCatalogEntry",
    "catalog_by_endpoint",
    "list_endpoint_catalog",
    "refresh_catalog",
    "validate_catalog_coverage",
]
