"""Public-safe RKE research context for MOSAIC agents.

The full report-intelligence registry is private and may contain licensed
report prose, source spans, reviewer notes, and local file paths. This module
builds a small allowlisted view that agents can consume through the bridge as
research prior only.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .private_registries import resolve_report_intelligence_registry_dir

SCHEMA_VERSION = "rke_agent_research_context_v1"
SAFE_ACTIONABILITY = "no_trade_without_current_data_confirmation"
RESEARCH_PRIOR_USE_POLICY = "shadow_research_prior_only_not_current_signal"
RANKING_POLICY_ID = "rke_agent_research_context_rank_v1"
FORBIDDEN_FIELD_POLICY = "source_prose_and_private_references_omitted"
DEFAULT_REGISTRY_DIR = "registry/report_intelligence"
RATING_BUCKETS = frozenset(
    {
        "supportive_evidence",
        "mixed_evidence",
        "contradictory_evidence",
        "pending_or_unrated",
    }
)
RELIABILITY_BUCKETS = frozenset(
    {
        "high_effective_n",
        "medium_effective_n",
        "low_effective_n",
        "limited",
        "insufficient_data",
    }
)
AGENT_TARGET_SPECIFICITY_BUCKETS = frozenset(
    {
        "direct_agent_target_match",
        "explicit_agent_candidate",
        "strong_role_style_match",
        "sector_target_match",
        "metric_or_regime_match",
        "role_style_match",
        "decision_stock_prior",
        "decision_industry_prior",
        "decision_macro_prior",
        "generic_agent_match",
    }
)
PERFORMANCE_CONTEXT_BUCKETS = frozenset(
    {
        "source_and_viewpoint_profile_match",
        "viewpoint_profile_match",
        "source_profile_match",
        "insufficient_data",
    }
)
_METRIC_FAMILY_KEY_CACHE: dict[int, tuple[Sequence[Mapping[str, Any]], set[str]]] = {}
_RECIPE_ID_INDEX_CACHE: dict[
    tuple[int, tuple[str, ...]],
    tuple[Sequence[Mapping[str, Any]], dict[str, list[str]]],
] = {}
_TOOL_GAP_ID_INDEX_CACHE: dict[
    tuple[int, tuple[str, ...]],
    tuple[Sequence[Mapping[str, Any]], dict[str, dict[str, list[str]]]],
] = {}

MACRO_AGENTS = frozenset(
    {
        "central_bank",
        "china",
        "commodities",
        "dollar",
        "emerging_markets",
        "geopolitical",
        "institutional_flow",
        "news_sentiment",
        "volatility",
        "yield_curve",
    }
)
SECTOR_AGENTS = frozenset(
    {
        "biotech",
        "consumer",
        "energy",
        "financials",
        "industrials",
        "relationship_mapper",
        "semiconductor",
    }
)
SUPERINVESTOR_AGENTS = frozenset({"ackman", "burry", "druckenmiller", "munger"})
DECISION_AGENTS = frozenset(
    {"alpha_discovery", "autonomous_execution", "cio", "cro", "execution"}
)

MACRO_AGENT_BY_METRIC_FAMILY: Mapping[str, tuple[str, ...]] = {
    "policy_rate_level": ("macro.central_bank",),
    "money_market_rate": ("macro.central_bank",),
    "bond_yield_level": ("macro.yield_curve", "macro.central_bank"),
    "yield_curve_slope": ("macro.yield_curve",),
    "cross_market_yield_spread": ("macro.yield_curve", "macro.dollar"),
    "fx_rate": ("macro.dollar", "macro.emerging_markets"),
    "equity_index_forward_return": ("macro.china", "macro.emerging_markets"),
    "bond_etf_forward_return": ("macro.central_bank", "macro.yield_curve"),
    "macro_asset_forward_return": ("macro.china", "macro.emerging_markets"),
    "commodity_price": ("macro.commodities",),
    "commodity_price_cycle": ("macro.commodities",),
    "gold_etf_forward_return": ("macro.commodities", "macro.geopolitical"),
    "volatility_index": ("macro.volatility",),
    "risk_off_asset_path": ("macro.geopolitical", "macro.volatility"),
    "growth_inflation_release": ("macro.china", "macro.commodities"),
    "liquidity_credit_condition": ("macro.central_bank", "macro.yield_curve"),
}
MACRO_AGENT_BY_ASSET_TARGET: Mapping[str, tuple[str, ...]] = {
    "CN_A_SHARE_BROAD": ("macro.china",),
    "CN_A_SHARE_LARGE_CAP": ("macro.china",),
    "CN_A_SHARE_MID_SMALL": ("macro.china",),
    "CN_A_SHARE_GROWTH": ("macro.china",),
    "HK_EQUITY": ("macro.china", "macro.emerging_markets"),
    "US_EQUITY_NASDAQ": ("macro.emerging_markets",),
    "US_EQUITY_SP500": ("macro.emerging_markets",),
    "CN_BOND": ("macro.central_bank", "macro.yield_curve"),
    "CN_CREDIT_BOND": ("macro.central_bank", "macro.yield_curve"),
    "CN_POLICY_BANK_BOND": ("macro.central_bank", "macro.yield_curve"),
    "GOLD": ("macro.commodities", "macro.geopolitical"),
}
MACRO_AGENT_BY_REGIME: Mapping[str, tuple[str, ...]] = {
    "us_rate_cut_cycle": ("macro.central_bank", "macro.yield_curve"),
    "china_countercyclical_policy": ("macro.china", "macro.central_bank"),
    "monetary_liquidity_condition": ("macro.central_bank", "macro.china"),
    "china_monetary_easing_cycle": ("macro.central_bank", "macro.china"),
    "credit_cycle": ("macro.central_bank", "macro.yield_curve"),
    "fx_usd_cycle": ("macro.dollar", "macro.emerging_markets"),
    "rmb_fx_stability_window": (
        "macro.dollar",
        "macro.china",
        "macro.emerging_markets",
    ),
    "global_growth_inflation": ("macro.commodities", "macro.yield_curve"),
    "fiscal_policy": ("macro.china", "macro.central_bank"),
    "regulatory_policy": ("macro.china",),
    "trade_friction_intensity": (
        "macro.geopolitical",
        "macro.dollar",
        "macro.emerging_markets",
    ),
    "commodity_price_cycle": ("macro.commodities",),
    "volatility_shock": ("macro.volatility",),
    "market_volatility_regime": ("macro.volatility",),
}

SECTOR_AGENT_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "sector.semiconductor": (
        "半导体",
        "芯片",
        "电子元件",
        "通信设备",
        "ai",
        "人工智能",
        "算力",
        "液冷",
    ),
    "sector.energy": (
        "能源",
        "煤炭",
        "石油",
        "天然气",
        "电力",
        "公用事业",
        "油气",
    ),
    "sector.biotech": (
        "医药",
        "生物",
        "医疗",
        "制药",
        "医疗器械",
        "创新药",
    ),
    "sector.consumer": (
        "食品",
        "饮料",
        "消费",
        "家电",
        "纺织",
        "服装",
        "造纸",
        "包装印刷",
        "教育",
    ),
    "sector.industrials": (
        "机械",
        "军工",
        "交运",
        "设备",
        "汽车",
        "材料",
        "有色",
        "稀土",
        "小金属",
        "新材料",
    ),
    "sector.financials": ("银行", "证券", "保险", "金融", "非银"),
}

SUPERINVESTOR_STYLE_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "superinvestor.ackman": (
        "cashflow",
        "free_cash_flow",
        "roe",
        "gross_margin",
        "earnings_growth",
        "dividend",
        "定价权",
        "现金流",
        "高端",
        "龙头",
    ),
    "superinvestor.munger": (
        "quality",
        "moat",
        "roic",
        "gross_margin",
        "free_cash_flow",
        "predictability",
        "cashflow",
        "roe",
        "护城河",
        "定价权",
        "自由现金流",
        "低负债",
        "可预测",
        "复利",
    ),
    "superinvestor.burry": (
        "value",
        "deep_value",
        "fcf_yield",
        "ev_ebit",
        "balance_sheet",
        "debt",
        "cash",
        "buyback",
        "contrarian",
        "downside",
        "stock_forward_return",
        "深度价值",
        "逆向",
        "低估",
        "资产负债表",
        "现金",
        "回购",
    ),
    "superinvestor.druckenmiller": (
        "momentum",
        "price",
        "policy",
        "cycle",
        "commodity",
        "stock_forward_return",
        "政策",
        "周期",
        "景气",
    ),
}

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "abstract",
        "claim_text",
        "markdown",
        "markdown_path",
        "pdf",
        "pdf_path",
        "review_note",
        "source_excerpt",
        "source_span_id",
        "source_span_ids",
        "source_text",
        "source_url",
        "text",
        "title",
        "url",
    }
)


def normalize_agent_id(agent_id: str, layer: str = "") -> str:
    """Return the RKE-style agent id, accepting TS ids without prefixes."""
    raw = _slug(agent_id)
    if raw.startswith(("macro.", "sector.", "superinvestor.")):
        return raw
    layer_slug = _slug(layer)
    if layer_slug == "macro" or raw in MACRO_AGENTS:
        return f"macro.{raw}"
    if layer_slug == "sector" or raw in SECTOR_AGENTS:
        return f"sector.{raw}"
    if layer_slug in {"superinvestor", "investor"} or raw in SUPERINVESTOR_AGENTS:
        return f"superinvestor.{raw}"
    if layer_slug == "decision" or raw in DECISION_AGENTS:
        return f"decision.{raw}"
    return raw


def build_rke_agent_research_context(
    *,
    root: str | Path = ".",
    registry_dir: str | Path | None = None,
    agent_id: str,
    as_of_date: str = "",
    layer: str = "",
    ticker: str = "",
    sector: str = "",
    max_items: int = 12,
) -> dict[str, Any]:
    """Build a public-safe context from local private RKE artifacts."""
    root_path = Path(root).expanduser().resolve()
    registry_path = resolve_report_intelligence_registry_dir(root_path, registry_dir)

    rows = {
        "forecasts": _read_jsonl(registry_path / "forecast_claims.jsonl"),
        "metadata": _read_jsonl(registry_path / "report_metadata.jsonl"),
        "outcomes": _read_jsonl(registry_path / "report_outcome_labels.jsonl"),
        "source_profiles": _read_jsonl(
            registry_path / "source_performance_profiles.jsonl"
        ),
        "viewpoint_profiles": _read_jsonl(
            registry_path / "viewpoint_performance_profiles.jsonl"
        ),
        "recipes": _read_jsonl(registry_path / "analysis_recipes.jsonl"),
        "tool_gaps": _read_jsonl(registry_path / "tool_gaps.jsonl"),
        "weighted_research_contexts": _read_jsonl(
            registry_path / "weighted_research_contexts.jsonl"
        ),
        "stock_context_snapshots": _read_jsonl(
            registry_path / "stock_context_snapshots.jsonl"
        ),
        "industry_context_snapshots": _read_jsonl(
            registry_path / "industry_context_snapshots.jsonl"
        ),
    }
    return build_rke_agent_research_context_from_rows(
        agent_id=agent_id,
        as_of_date=as_of_date,
        layer=layer,
        ticker=ticker,
        sector=sector,
        max_items=max_items,
        **rows,
    )


def build_rke_agent_research_context_from_rows(
    *,
    agent_id: str,
    forecasts: Sequence[Mapping[str, Any]],
    metadata: Sequence[Mapping[str, Any]] = (),
    outcomes: Sequence[Mapping[str, Any]] = (),
    source_profiles: Sequence[Mapping[str, Any]] = (),
    viewpoint_profiles: Sequence[Mapping[str, Any]] = (),
    recipes: Sequence[Mapping[str, Any]] = (),
    tool_gaps: Sequence[Mapping[str, Any]] = (),
    weighted_research_contexts: Sequence[Mapping[str, Any]] = (),
    stock_context_snapshots: Sequence[Mapping[str, Any]] = (),
    industry_context_snapshots: Sequence[Mapping[str, Any]] = (),
    as_of_date: str = "",
    layer: str = "",
    ticker: str = "",
    sector: str = "",
    max_items: int = 12,
) -> dict[str, Any]:
    normalized_agent = normalize_agent_id(agent_id, layer=layer)
    max_count = max(0, int(max_items or 0))
    metadata_by_report = _index_metadata(metadata)
    outcomes_by_claim = _group_by(
        [row for row in outcomes if _outcome_available_as_of(row, as_of_date)],
        "forecast_claim_id",
    )
    weighted_by_claim = _weighted_claims_by_forecast_id(
        weighted_research_contexts,
        normalized_agent,
        as_of_date=as_of_date,
    )
    metric_family_keys = _cached_known_metric_family_keys(forecasts)
    recipe_id_index = _cached_recipe_id_index(recipes, metric_family_keys)
    tool_gap_id_index = _cached_tool_gap_id_index(tool_gaps, metric_family_keys)

    items: list[dict[str, Any]] = []
    for original_index, claim in enumerate(forecasts):
        if as_of_date and _claim_as_of_date(claim, metadata_by_report) > as_of_date:
            continue
        report_meta = metadata_by_report.get(_claim_report_key(claim), {})
        if not _claim_matches_request(
            claim,
            report_meta,
            agent_id=normalized_agent,
            ticker=ticker,
            sector=sector,
        ):
            continue
        claim_id = str(claim.get("forecast_claim_id") or "")
        item = _public_claim_item(
            claim,
            report_meta=report_meta,
            agent_id=normalized_agent,
            as_of_date=as_of_date,
            original_input_index=original_index,
            weighted_claim=weighted_by_claim.get(claim_id, {}),
            source_profiles=source_profiles,
            viewpoint_profiles=viewpoint_profiles,
            outcomes=outcomes_by_claim.get(claim_id, []),
            recipe_id_index=recipe_id_index,
            tool_gap_id_index=tool_gap_id_index,
            stock_context_snapshots=stock_context_snapshots,
            industry_context_snapshots=industry_context_snapshots,
        )
        items.append(item)
    ranked_items = _rank_context_items(items)
    for rank, item in enumerate(ranked_items, 1):
        item["retrieval_rank"] = rank
        item["priority_bucket"] = _priority_bucket(rank, len(ranked_items))
        item["ranking_reason_codes"] = _ranking_reason_codes(item)
    visible_items = ranked_items[:max_count]

    context = {
        "schema_version": SCHEMA_VERSION,
        "agent_id": normalized_agent,
        "requested_agent_id": str(agent_id or ""),
        "layer": normalized_agent.split(".", 1)[0] if "." in normalized_agent else "",
        "as_of_date": as_of_date,
        "research_only": True,
        "production_signal_allowed": False,
        "actionability": SAFE_ACTIONABILITY,
        "ranking_policy_id": RANKING_POLICY_ID,
        "context_items": visible_items,
        "summary": {
            "item_count": len(visible_items),
            "matched_item_count": len(ranked_items),
            "truncated_item_count": max(0, len(ranked_items) - len(visible_items)),
            "no_prior_reason": _no_prior_reason(normalized_agent, ranked_items),
            "private_text_included": False,
            "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
            "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
            "current_data_required": True,
            "ranking_policy_id": RANKING_POLICY_ID,
        },
    }
    assert_public_safe_context(context)
    return context


def format_rke_agent_research_context(context: Mapping[str, Any]) -> str:
    """Format context as compact Markdown for LangChain tool output."""
    agent_id = str(context.get("agent_id") or "")
    policy = (
        f"research_only={str(context.get('research_only')).lower()}; "
        f"production_signal_allowed={str(context.get('production_signal_allowed')).lower()}; "
        f"actionability={context.get('actionability')}"
    )
    lines = [f"## RKE research context for {agent_id}", "", f"Policy: {policy}."]
    items = list(_ensure_list(context.get("context_items")))
    if not items:
        lines.append("")
        lines.append("No matching RKE context was available for this agent/request.")
        return "\n".join(lines)
    for item in items:
        item_map = _ensure_mapping(item)
        outcome_summary = _ensure_mapping(item_map.get("outcome_label_summary"))
        lines.extend(
            [
                "",
                f"### Prior {item_map.get('redacted_claim_id')}",
                (
                    f"- Target: {item_map.get('target_type')} "
                    f"{item_map.get('target_id')}, "
                    f"metric_family={item_map.get('metric_family')}"
                ),
                (
                    "- Ranking: "
                    f"rank={item_map.get('retrieval_rank')}; "
                    f"priority={item_map.get('priority_bucket')}; "
                    "reasons="
                    f"{', '.join(_ensure_str_list(item_map.get('ranking_reason_codes'))) or 'none'}"
                ),
                f"- Expected direction: {item_map.get('expected_direction')}",
                f"- Horizon: {item_map.get('horizon_bucket')}",
                (
                    f"- Regime: {item_map.get('regime_bucket')} "
                    f"({', '.join(_ensure_str_list(item_map.get('regime_types'))) or 'none'})"
                ),
                (
                    "- Performance: "
                    f"source={item_map.get('source_performance_bucket')}, "
                    f"viewpoint={item_map.get('viewpoint_performance_bucket')}, "
                    f"reliability={item_map.get('statistical_reliability_bucket')}, "
                    f"n_effective={item_map.get('n_effective')}"
                ),
                (
                    "- Failure tags: "
                    f"{', '.join(_ensure_str_list(item_map.get('known_failure_mode_tags'))) or 'none'}"
                ),
                (
                    "- Outcome labels: "
                    f"count={outcome_summary.get('label_count')}; "
                    f"pending_share={outcome_summary.get('pending_share')}; "
                    "types="
                    f"{', '.join(_ensure_str_list(outcome_summary.get('label_types'))) or 'none'}; "
                    f"latest_completed_exit={outcome_summary.get('latest_completed_exit_date') or 'none'}"
                ),
                (
                    "- Recipes: "
                    f"{', '.join(_ensure_str_list(item_map.get('recipe_ids'))) or 'none'}"
                ),
                (
                    "- Tool gaps: "
                    f"{', '.join(_ensure_str_list(item_map.get('tool_gap_ids'))) or 'none'}"
                ),
                (
                    "- Current data required: "
                    f"{str(item_map.get('current_data_required') is True).lower()}; "
                    "fields="
                    f"{', '.join(_ensure_str_list(item_map.get('current_data_required_fields'))) or 'none'}"
                ),
                (
                    "- Prior guard: "
                    f"use_policy={item_map.get('use_policy')}; "
                    f"actionability_guard={item_map.get('actionability_guard')}; "
                    "production_signal_allowed="
                    f"{str(item_map.get('production_signal_allowed')).lower()}"
                ),
            ]
        )
        if item_map.get("ticker"):
            lines.append(f"- Ticker: {item_map.get('ticker')}")
        if item_map.get("style_fit"):
            lines.append(f"- Style fit: {item_map.get('style_fit')}")
    return "\n".join(lines)


def assert_public_safe_context(value: Any) -> None:
    """Fail if a context contains fields known to carry source prose/private refs."""
    for path, key, field_value in _walk_mapping(value):
        key_text = str(key)
        if key_text in FORBIDDEN_FIELD_NAMES or key_text.endswith("_path"):
            raise ValueError(f"RKE agent context contains forbidden field {path}")
        if isinstance(field_value, str) and _looks_like_private_reference(field_value):
            raise ValueError(f"RKE agent context contains private reference at {path}")


def _public_claim_item(
    claim: Mapping[str, Any],
    *,
    report_meta: Mapping[str, Any],
    agent_id: str,
    as_of_date: str,
    original_input_index: int,
    weighted_claim: Mapping[str, Any],
    source_profiles: Sequence[Mapping[str, Any]],
    viewpoint_profiles: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    recipe_id_index: Mapping[str, Sequence[str]],
    tool_gap_id_index: Mapping[str, Mapping[str, Sequence[str]]],
    stock_context_snapshots: Sequence[Mapping[str, Any]],
    industry_context_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target = _ensure_mapping(claim.get("target"))
    domain = _claim_domain(claim, report_meta)
    metric_families = _claim_metric_families(claim)
    regime_types = _claim_regime_types(claim, agent_id)
    source_profile = _best_source_profile(
        report_meta,
        source_profiles,
        as_of_date=as_of_date,
    )
    viewpoint_profile = _best_viewpoint_profile(
        metric_families,
        viewpoint_profiles,
        as_of_date=as_of_date,
        horizon_bucket=_horizon_bucket(claim.get("horizon")),
    )
    matched_gaps = _matching_tool_gap_ids(metric_families, agent_id, tool_gap_id_index)
    matched_recipes = _matching_recipe_ids(metric_families, recipe_id_index)
    outcome_summary = _outcome_summary(outcomes)
    combined_weight = _round_float(
        weighted_claim.get("combined_research_prior_weight") or 1.0
    )
    performance_context_match = _performance_context_bucket(
        weighted_claim.get("performance_context_match")
    )
    stock_context_snapshot = (
        _matching_stock_context_snapshot(claim, report_meta, stock_context_snapshots)
        if domain == "stock"
        else {}
    )
    industry_context_snapshot = (
        _matching_industry_context_snapshot(
            claim,
            report_meta,
            industry_context_snapshots,
        )
        if domain == "industry"
        else {}
    )
    context_snapshot_missing_reasons = _context_snapshot_missing_reasons(
        agent_id,
        claim,
        report_meta,
        stock_context_snapshot=stock_context_snapshot,
        industry_context_snapshot=industry_context_snapshot,
    )
    item = {
        "redacted_claim_id": _redacted_id(
            "FCRED",
            claim.get("forecast_claim_id") or claim.get("claim_id") or "",
        ),
        "domain": domain,
        "target_type": _safe_token(target.get("target_type") or "unknown"),
        "target_id": _safe_token(target.get("target_id") or target.get("target_name") or "unknown"),
        "metric_family": metric_families[0] if metric_families else "unknown",
        "expected_direction": _safe_token(claim.get("direction") or "unknown"),
        "horizon_bucket": _horizon_bucket(claim.get("horizon")),
        "forecast_testability": _safe_token(
            claim.get("forecast_testability") or "unknown"
        ),
        "regime_bucket": "|".join(regime_types) if regime_types else "unknown",
        "regime_types": regime_types,
        "source_performance_bucket": _rating_bucket(
            source_profile.get("shrunk_performance_bucket")
        ),
        "viewpoint_performance_bucket": _rating_bucket(
            viewpoint_profile.get("shrunk_performance_bucket")
        ),
        "n_effective": _round_float(
            viewpoint_profile.get("n_effective") or source_profile.get("n_effective")
        ),
        "statistical_reliability_bucket": _reliability_bucket(
            viewpoint_profile.get("statistical_reliability_bucket")
            or source_profile.get("statistical_reliability_bucket")
        ),
        "source_weight_multiplier": _round_float(
            weighted_claim.get("source_weight_multiplier") or 1.0
        ),
        "viewpoint_weight_multiplier": _round_float(
            weighted_claim.get("viewpoint_weight_multiplier") or 1.0
        ),
        "combined_research_prior_weight": combined_weight,
        "performance_context_match": performance_context_match,
        "agent_target_specificity_bucket": _agent_target_specificity_bucket(
            agent_id, claim, report_meta
        ),
        "known_failure_mode_tags": _failure_mode_tags(claim, viewpoint_profile),
        "role_filter_reason_codes": _role_filter_reason_codes(
            agent_id, claim, report_meta
        ),
        "recipe_ids": matched_recipes,
        "tool_gap_ids": matched_gaps,
        "outcome_label_summary": outcome_summary,
        "latest_completed_exit_date": outcome_summary.get("latest_completed_exit_date")
        or "",
        "freshness_bucket": _freshness_bucket(
            latest_completed_exit_date=str(
                outcome_summary.get("latest_completed_exit_date") or ""
            ),
            as_of_date=as_of_date,
        ),
        "current_data_required": True,
        "current_data_required_fields": _current_data_required_fields(agent_id),
        "context_snapshot_status": _context_snapshot_status(
            stock_context_snapshot,
            industry_context_snapshot,
            context_snapshot_missing_reasons,
        ),
        "context_snapshot_missing_reasons": context_snapshot_missing_reasons,
        "actionability": SAFE_ACTIONABILITY,
        "actionability_guard": SAFE_ACTIONABILITY,
        "use_policy": RESEARCH_PRIOR_USE_POLICY,
        "production_signal_allowed": False,
        "no_prior_reason": "",
        "original_input_index": original_input_index,
    }
    if agent_id.startswith("sector."):
        item["sector"] = _safe_token(
            report_meta.get("sector") or target.get("target_name") or target.get("target_id") or ""
        )
    if agent_id.startswith("superinvestor."):
        item["ticker"] = _safe_token(
            report_meta.get("ts_code") or target.get("target_id") or ""
        )
        item["style_fit"] = _style_fit_bucket(agent_id, claim, report_meta)
    if stock_context_snapshot:
        item.update(
            {
                "context_snapshot_id": str(
                    stock_context_snapshot.get("snapshot_id") or ""
                ),
                "market_cap_bucket": _safe_token(
                    stock_context_snapshot.get("market_cap_bucket") or "unknown"
                ),
                "liquidity_bucket": _safe_token(
                    stock_context_snapshot.get("liquidity_bucket") or "unknown"
                ),
                "stock_outcome_age_bucket": _safe_token(
                    stock_context_snapshot.get("stock_outcome_age_bucket")
                    or "unknown"
                ),
                "benchmark_family": _safe_token(
                    stock_context_snapshot.get("benchmark_family") or "unknown"
                ),
                "fundamental_metric_family_counts": dict(
                    sorted(
                        _ensure_mapping(
                            stock_context_snapshot.get(
                                "fundamental_metric_family_counts"
                            )
                        ).items()
                    )
                ),
                "context_snapshot_feature_missing_reasons": _ensure_str_list(
                    stock_context_snapshot.get("missing_feature_reasons")
                ),
            }
        )
    if industry_context_snapshot:
        known_proxy_limitations = _ensure_str_list(
            industry_context_snapshot.get("known_proxy_limitations")
        )
        item["known_failure_mode_tags"] = list(
            dict.fromkeys(
                [
                    *_ensure_str_list(item.get("known_failure_mode_tags")),
                    *known_proxy_limitations,
                ]
            )
        )
        item.update(
            {
                "context_snapshot_id": str(
                    industry_context_snapshot.get("snapshot_id") or ""
                ),
                "industry_cycle_bucket": _safe_token(
                    industry_context_snapshot.get("industry_cycle_bucket")
                    or "unknown"
                ),
                "proxy_symbol": _safe_token(
                    industry_context_snapshot.get("proxy_symbol") or "unknown"
                ),
                "proxy_liquidity_bucket": _safe_token(
                    industry_context_snapshot.get("proxy_liquidity_bucket")
                    or "unknown"
                ),
                "mapping_confidence": _safe_token(
                    industry_context_snapshot.get("mapping_confidence") or "unknown"
                ),
                "benchmark_family": _safe_token(
                    industry_context_snapshot.get("benchmark_family") or "unknown"
                ),
                "known_proxy_limitations": known_proxy_limitations,
                "context_snapshot_feature_missing_reasons": _ensure_str_list(
                    industry_context_snapshot.get("missing_feature_reasons")
                ),
            }
        )
    return item


def _claim_matches_request(
    claim: Mapping[str, Any],
    report_meta: Mapping[str, Any],
    *,
    agent_id: str,
    ticker: str,
    sector: str,
) -> bool:
    if ticker:
        wanted = ticker.strip().upper()
        claim_ticker = str(
            report_meta.get("ts_code")
            or _ensure_mapping(claim.get("target")).get("target_id")
            or ""
        ).upper()
        if claim_ticker != wanted:
            return False
    if sector:
        sector_text = _combined_text(report_meta.get("sector"), claim.get("target"))
        if sector.strip().lower() not in sector_text.lower():
            return False
    if agent_id.startswith("macro."):
        return _is_macro_claim(claim, report_meta) and agent_id in _macro_agent_candidates(claim)
    if agent_id.startswith("sector."):
        return _sector_agent_for_claim(claim, report_meta) == agent_id
    if agent_id.startswith("superinvestor."):
        if str(report_meta.get("report_type") or "") != "个股研报":
            return False
        return _style_fit_score(agent_id, claim, report_meta) > 0
    if agent_id.startswith("decision."):
        return _claim_domain(claim, report_meta) in {"stock", "industry", "macro"}
    return False


def _claim_domain(claim: Mapping[str, Any], report_meta: Mapping[str, Any]) -> str:
    target = _ensure_mapping(claim.get("target"))
    target_type = str(target.get("target_type") or "")
    report_type = str(report_meta.get("report_type") or "")
    if target_type in {"stock", "company"} or report_type == "个股研报":
        return "stock"
    if target_type in {"sector", "industry"} or report_type == "行业研报":
        return "industry"
    if _is_macro_claim(claim, report_meta):
        return "macro"
    return "unknown"


def _agent_target_specificity_bucket(
    agent_id: str, claim: Mapping[str, Any], report_meta: Mapping[str, Any]
) -> str:
    target = _ensure_mapping(claim.get("target"))
    explicit_agents = {
        str(value).strip()
        for value in [
            *_ensure_list(claim.get("target_agent_candidates")),
            *_ensure_list(target.get("target_agent_candidates")),
        ]
        if str(value).strip()
    }
    if agent_id in explicit_agents:
        return "explicit_agent_candidate"
    if agent_id.startswith("superinvestor.") and _style_fit_score(
        agent_id, claim, report_meta
    ) >= 3:
        return "strong_role_style_match"
    if agent_id.startswith("superinvestor."):
        return "role_style_match"
    if agent_id.startswith("sector.") and _sector_agent_for_claim(claim, report_meta):
        return "sector_target_match"
    if agent_id.startswith("macro.") and agent_id in _macro_agent_candidates(claim):
        return "metric_or_regime_match"
    if agent_id.startswith("decision."):
        return f"decision_{_claim_domain(claim, report_meta)}_prior"
    return "generic_agent_match"


def _is_macro_claim(claim: Mapping[str, Any], report_meta: Mapping[str, Any]) -> bool:
    report_type = str(report_meta.get("report_type") or "")
    sector = str(report_meta.get("sector") or "")
    target = _ensure_mapping(claim.get("target"))
    target_type = str(target.get("target_type") or "")
    target_id = str(target.get("target_id") or target.get("target_name") or "")
    if target_type in {"stock", "company", "sector", "industry"}:
        return False
    macro_target_types = {
        "macro_asset",
        "market_index",
        "equity_index",
        "bond",
        "credit_spread",
        "commodity",
        "macro_series",
        "macro_curve",
        "macro_variable",
    }
    if report_type in {"个股研报", "行业研报"} and target_type not in macro_target_types:
        return False
    if report_type.startswith("宏观策略") or sector == "宏观策略":
        return True
    if target_type in macro_target_types:
        return True
    if target_id in MACRO_AGENT_BY_ASSET_TARGET:
        return True
    return any(family in MACRO_AGENT_BY_METRIC_FAMILY for family in _claim_metric_families(claim))


def _macro_agent_candidates(claim: Mapping[str, Any]) -> tuple[str, ...]:
    target = _ensure_mapping(claim.get("target"))
    agents: list[str] = []
    for value in [*(_ensure_list(claim.get("target_agent_candidates"))), *(_ensure_list(target.get("target_agent_candidates")))]:
        text = str(value or "").strip()
        if text.startswith("macro."):
            agents.append(text)
    for family in _claim_metric_families(claim):
        agents.extend(MACRO_AGENT_BY_METRIC_FAMILY.get(family, ()))
    target_id = str(target.get("target_id") or target.get("target_name") or "")
    agents.extend(MACRO_AGENT_BY_ASSET_TARGET.get(target_id, ()))
    if agents:
        return tuple(dict.fromkeys(agents))
    for regime in _claim_regime_types(claim, ""):
        agents.extend(MACRO_AGENT_BY_REGIME.get(regime, ()))
    return tuple(dict.fromkeys(agents))


def _claim_regime_types(claim: Mapping[str, Any], agent_id: str) -> list[str]:
    trace = _ensure_mapping(claim.get("claim_regime_trace"))
    macro = _ensure_mapping(trace.get("macro"))
    traces: Iterable[Mapping[str, Any]]
    if agent_id and agent_id in macro:
        traces = (_ensure_mapping(macro.get(agent_id)),)
    else:
        traces = (_ensure_mapping(value) for value in macro.values())
    regimes: list[str] = []
    for agent_trace in traces:
        regimes.extend(_ensure_str_list(agent_trace.get("regime_types")))
        regimes.extend(_ensure_str_list(agent_trace.get("as_of_date_regime_types")))
    return list(dict.fromkeys(regimes))


def _sector_agent_for_claim(
    claim: Mapping[str, Any], report_meta: Mapping[str, Any]
) -> str:
    text = _combined_text(report_meta.get("sector"), report_meta.get("subsectors"), claim.get("target"))
    lowered = text.lower()
    for agent_id, keywords in SECTOR_AGENT_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return agent_id
    return ""


def _style_fit_score(
    agent_id: str, claim: Mapping[str, Any], report_meta: Mapping[str, Any]
) -> int:
    text = _combined_text(
        report_meta.get("sector"),
        report_meta.get("subsectors"),
        claim.get("forecast_type"),
        claim.get("metric_proxy_mapping"),
        claim.get("target"),
    ).lower()
    keywords = SUPERINVESTOR_STYLE_KEYWORDS.get(agent_id, ())
    return sum(1 for keyword in keywords if keyword.lower() in text)


def _style_fit_bucket(
    agent_id: str, claim: Mapping[str, Any], report_meta: Mapping[str, Any]
) -> str:
    score = _style_fit_score(agent_id, claim, report_meta)
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _claim_metric_families(claim: Mapping[str, Any]) -> list[str]:
    target = _ensure_mapping(claim.get("target"))
    values = [
        *_ensure_list(claim.get("metric_proxy_mapping")),
        *_ensure_list(target.get("metric_proxy_mapping")),
        target.get("metric_family") or "",
    ]
    return list(dict.fromkeys(_safe_token(value) for value in values if str(value).strip()))


def _best_source_profile(
    report_meta: Mapping[str, Any],
    source_profiles: Sequence[Mapping[str, Any]],
    *,
    as_of_date: str,
) -> Mapping[str, Any]:
    ids = {
        str(report_meta.get("institution_id") or ""),
        *[str(item) for item in _ensure_list(report_meta.get("author_ids"))],
    }
    report_sector = str(
        report_meta.get("sector") or report_meta.get("industry") or ""
    ).strip()
    candidates = [
        row
        for row in source_profiles
        if str(row.get("entity_id") or "") in ids
        and _profile_available_as_of(row, as_of_date)
        and _profile_context_matches_sector(row, report_sector)
    ]
    return _best_by_effective_n(candidates)


def _best_viewpoint_profile(
    metric_families: Sequence[str],
    viewpoint_profiles: Sequence[Mapping[str, Any]],
    *,
    as_of_date: str,
    horizon_bucket: str,
) -> Mapping[str, Any]:
    wanted = set(metric_families)
    candidates = [
        row
        for row in viewpoint_profiles
        if wanted.intersection(_ensure_str_list(row.get("mechanism_chain")))
        and _profile_available_as_of(row, as_of_date)
        and _profile_context_matches_horizon(row, horizon_bucket)
    ]
    return _best_by_effective_n(candidates)


def _best_by_effective_n(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not rows:
        return {}
    return sorted(rows, key=lambda row: float(row.get("n_effective") or 0), reverse=True)[0]


def _weighted_claims_by_forecast_id(
    contexts: Sequence[Mapping[str, Any]],
    agent_id: str,
    *,
    as_of_date: str,
) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for context in contexts:
        if not _dated_row_available_before(
            context,
            as_of_date,
            fields=("as_of_datetime", "as_of_date"),
        ):
            continue
        context_agent = str(context.get("agent_id") or "")
        priority = 0 if context_agent == agent_id else 1 if context_agent == "research.general" else 2
        for claim in _ensure_list(context.get("retrieved_claims")):
            claim_map = _ensure_mapping(claim)
            forecast_claim_id = str(claim_map.get("forecast_claim_id") or "")
            if not forecast_claim_id:
                continue
            previous = rows.get(forecast_claim_id)
            if previous is None or priority < previous[0]:
                rows[forecast_claim_id] = (priority, claim_map)
    return {claim_id: row for claim_id, (_, row) in rows.items()}


def _dated_row_available_before(
    row: Mapping[str, Any],
    as_of_date: str,
    *,
    fields: Sequence[str],
) -> bool:
    if not as_of_date:
        return True
    available_date = next(
        (_date_key(row.get(field)) for field in fields if _date_key(row.get(field))),
        "",
    )
    return bool(available_date) and available_date < as_of_date


def _outcome_available_as_of(row: Mapping[str, Any], as_of_date: str) -> bool:
    return _dated_row_available_before(
        row,
        as_of_date,
        fields=(
            "label_available_at",
            "data_as_of_datetime",
            "exit_datetime",
            "exit_date",
            "observed_at",
        ),
    )


def _profile_available_as_of(row: Mapping[str, Any], as_of_date: str) -> bool:
    return _dated_row_available_before(
        row,
        as_of_date,
        fields=("as_of_datetime", "last_revalidated_at"),
    )


def _profile_context_matches_sector(
    row: Mapping[str, Any], report_sector: str
) -> bool:
    profile_sector = str(_ensure_mapping(row.get("context")).get("sector") or "").strip()
    if not profile_sector or profile_sector == "unknown" or not report_sector:
        return True
    return _slug(profile_sector) == _slug(report_sector)


def _profile_context_matches_horizon(
    row: Mapping[str, Any], horizon_bucket: str
) -> bool:
    profile_horizon = str(
        _ensure_mapping(row.get("context")).get("horizon_bucket") or ""
    ).strip()
    if not profile_horizon or profile_horizon == "unknown" or not horizon_bucket:
        return True
    return profile_horizon == horizon_bucket


def _rank_context_items(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=_context_item_rank_key)


def _context_item_rank_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _specificity_rank(item.get("agent_target_specificity_bucket")),
        _performance_context_rank(item.get("performance_context_match")),
        -_safe_float(item.get("combined_research_prior_weight"), 1.0),
        _reliability_rank(item.get("statistical_reliability_bucket")),
        -_safe_float(item.get("n_effective"), 0.0),
        _freshness_rank(item.get("freshness_bucket")),
        _reverse_date_key(item.get("latest_completed_exit_date")),
        _safe_int(item.get("original_input_index"), 0),
    )


def _specificity_rank(value: Any) -> int:
    ranks = {
        "direct_agent_target_match": 0,
        "explicit_agent_candidate": 0,
        "strong_role_style_match": 1,
        "sector_target_match": 1,
        "metric_or_regime_match": 1,
        "role_style_match": 2,
        "decision_stock_prior": 2,
        "decision_industry_prior": 2,
        "decision_macro_prior": 2,
        "generic_agent_match": 3,
    }
    return ranks.get(str(value or ""), 9)


def _performance_context_rank(value: Any) -> int:
    ranks = {
        "source_and_viewpoint_profile_match": 0,
        "viewpoint_profile_match": 1,
        "source_profile_match": 1,
        "insufficient_data": 2,
    }
    return ranks.get(str(value or ""), 9)


def _reliability_rank(value: Any) -> int:
    ranks = {
        "high_effective_n": 0,
        "medium_effective_n": 1,
        "low_effective_n": 2,
        "limited": 3,
        "insufficient_data": 4,
    }
    return ranks.get(str(value or ""), 9)


def _freshness_rank(value: Any) -> int:
    ranks = {
        "historical_completed_exit": 0,
        "completed_exit_after_prior_as_of": 1,
        "pending_no_completed_exit": 2,
    }
    return ranks.get(str(value or ""), 9)


def _reverse_date_key(value: Any) -> str:
    date = _date_key(value)
    return "".join(str(9 - int(char)) if char.isdigit() else char for char in date)


def _priority_bucket(rank: int, total: int) -> str:
    if total <= 0:
        return "low"
    if rank <= 3:
        return "high"
    if rank <= 10:
        return "medium"
    return "low"


def _ranking_reason_codes(item: Mapping[str, Any]) -> list[str]:
    reasons = [str(item.get("agent_target_specificity_bucket") or "generic_agent_match")]
    reasons.extend(_ensure_str_list(item.get("role_filter_reason_codes")))
    performance_context = str(item.get("performance_context_match") or "insufficient_data")
    if performance_context != "insufficient_data":
        reasons.append(performance_context)
    weight = _safe_float(item.get("combined_research_prior_weight"), 1.0)
    if weight > 1.0:
        reasons.append("research_prior_weight_above_neutral")
    elif weight < 1.0:
        reasons.append("research_prior_weight_below_neutral")
    reliability = str(item.get("statistical_reliability_bucket") or "insufficient_data")
    if reliability != "insufficient_data":
        reasons.append(f"reliability_{reliability}")
    freshness = str(item.get("freshness_bucket") or "")
    if freshness:
        reasons.append(freshness)
    outcome_summary = _ensure_mapping(item.get("outcome_label_summary"))
    if _safe_int(outcome_summary.get("label_count"), 0) > 0:
        reasons.append("market_feedback_available")
    reasons.extend(_ensure_str_list(item.get("context_snapshot_missing_reasons")))
    return list(dict.fromkeys(reasons))


def _role_filter_reason_codes(
    agent_id: str,
    claim: Mapping[str, Any],
    report_meta: Mapping[str, Any],
) -> list[str]:
    if not agent_id.startswith("superinvestor."):
        return []
    if _style_fit_score(agent_id, claim, report_meta) <= 0:
        return []
    if agent_id == "superinvestor.munger":
        return ["role_filter_quality_moat_cashflow"]
    if agent_id == "superinvestor.burry":
        return ["role_filter_value_contrarian_balance_sheet"]
    if agent_id == "superinvestor.ackman":
        return ["role_filter_quality_catalyst_capital_allocation"]
    if agent_id == "superinvestor.druckenmiller":
        return ["role_filter_cycle_trend_policy_momentum"]
    return ["role_filter_unknown_superinvestor_style"]


def _no_prior_reason(agent_id: str, ranked_items: Sequence[Mapping[str, Any]]) -> str:
    if ranked_items:
        return ""
    if agent_id.startswith("superinvestor."):
        raw_agent = agent_id.split(".", 1)[1]
        if raw_agent not in SUPERINVESTOR_AGENTS:
            return "unsupported_superinvestor_agent"
        return "no_role_filtered_stock_prior_for_superinvestor"
    return "no_applicable_prior_for_agent_request"


def _cached_known_metric_family_keys(
    forecasts: Sequence[Mapping[str, Any]],
) -> set[str]:
    cache_key = id(forecasts)
    cached = _METRIC_FAMILY_KEY_CACHE.get(cache_key)
    if cached and cached[0] is forecasts:
        return cached[1]
    value = _known_metric_family_keys(forecasts)
    _METRIC_FAMILY_KEY_CACHE[cache_key] = (forecasts, value)
    return value


def _cached_recipe_id_index(
    recipes: Sequence[Mapping[str, Any]], metric_family_keys: set[str]
) -> dict[str, list[str]]:
    metric_tuple = tuple(sorted(metric_family_keys))
    cache_key = (id(recipes), metric_tuple)
    cached = _RECIPE_ID_INDEX_CACHE.get(cache_key)
    if cached and cached[0] is recipes:
        return cached[1]
    value = _index_recipe_ids(recipes, metric_family_keys)
    _RECIPE_ID_INDEX_CACHE[cache_key] = (recipes, value)
    return value


def _cached_tool_gap_id_index(
    tool_gaps: Sequence[Mapping[str, Any]], metric_family_keys: set[str]
) -> dict[str, dict[str, list[str]]]:
    metric_tuple = tuple(sorted(metric_family_keys))
    cache_key = (id(tool_gaps), metric_tuple)
    cached = _TOOL_GAP_ID_INDEX_CACHE.get(cache_key)
    if cached and cached[0] is tool_gaps:
        return cached[1]
    value = _index_tool_gap_ids(tool_gaps, metric_family_keys)
    _TOOL_GAP_ID_INDEX_CACHE[cache_key] = (tool_gaps, value)
    return value


def _known_metric_family_keys(forecasts: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        key
        for claim in forecasts
        for key in (_safe_token(metric).lower() for metric in _claim_metric_families(claim))
        if key
    }


def _index_tool_gap_ids(
    tool_gaps: Sequence[Mapping[str, Any]], metric_family_keys: set[str]
) -> dict[str, dict[str, list[str]]]:
    by_agent: dict[str, list[str]] = defaultdict(list)
    by_metric: dict[str, list[str]] = defaultdict(list)
    for gap in tool_gaps:
        gap_id = str(gap.get("tool_gap_id") or "")
        if not gap_id:
            continue
        for agent in _ensure_str_list(gap.get("target_agents")):
            by_agent[agent].append(gap_id)
        metric_name = _safe_token(gap.get("metric_name")).lower()
        for key in metric_family_keys:
            if key in metric_name:
                by_metric[key].append(gap_id)
    return {"by_agent": dict(by_agent), "by_metric": dict(by_metric)}


def _index_recipe_ids(
    recipes: Sequence[Mapping[str, Any]], metric_family_keys: set[str]
) -> dict[str, list[str]]:
    by_metric: dict[str, list[str]] = defaultdict(list)
    for recipe in recipes:
        recipe_id = str(recipe.get("analysis_recipe_id") or recipe.get("recipe_id") or "")
        if not recipe_id:
            continue
        haystack = _combined_text(
            recipe.get("decision_scope"),
            recipe.get("required_data"),
            recipe.get("name"),
        ).lower()
        for key in metric_family_keys:
            if key in haystack:
                by_metric[key].append(recipe_id)
    return dict(by_metric)


def _matching_tool_gap_ids(
    metric_families: Sequence[str],
    agent_id: str,
    tool_gap_id_index: Mapping[str, Mapping[str, Sequence[str]]],
) -> list[str]:
    by_agent = tool_gap_id_index.get("by_agent", {})
    by_metric = tool_gap_id_index.get("by_metric", {})
    ids: list[str] = []
    for gap_id in by_agent.get(agent_id, ()):
        if gap_id not in ids:
            ids.append(gap_id)
        if len(ids) >= 5:
            break
    for metric in metric_families:
        if len(ids) >= 5:
            break
        key = _safe_token(metric).lower()
        for gap_id in by_metric.get(key, ()):
            if gap_id not in ids:
                ids.append(gap_id)
            if len(ids) >= 5:
                break
    return ids


def _matching_recipe_ids(
    metric_families: Sequence[str], recipe_id_index: Mapping[str, Sequence[str]]
) -> list[str]:
    ids: list[str] = []
    for metric in metric_families:
        key = _safe_token(metric).lower()
        for recipe_id in recipe_id_index.get(key, ()):
            if recipe_id not in ids:
                ids.append(recipe_id)
            if len(ids) >= 5:
                break
        if len(ids) >= 5:
            break
    return ids


def _failure_mode_tags(
    claim: Mapping[str, Any],
    viewpoint_profile: Mapping[str, Any],
) -> list[str]:
    texts = [
        _combined_text(mode)
        for mode in [*_ensure_list(claim.get("failure_modes")), *_ensure_list(viewpoint_profile.get("known_failure_modes"))]
    ]
    joined = " ".join(texts).lower()
    tags: list[str] = []
    rules = (
        ("policy_intervention_risk", ("政策", "央行", "监管", "intervention")),
        ("liquidity_reversal_risk", ("流动性", "美元", "liquidity")),
        ("demand_shortfall_risk", ("需求", "demand")),
        ("supply_response_risk", ("供给", "产能", "supply")),
        ("valuation_compression_risk", ("估值", "valuation")),
        ("earnings_miss_risk", ("盈利", "业绩", "earnings")),
        ("crowded_viewpoint_risk", ("拥挤", "一致预期", "crowded")),
    )
    for tag, keywords in rules:
        if any(keyword in joined for keyword in keywords):
            tags.append(tag)
    if tags:
        return tags
    return ["known_failure_modes_present"] if texts else []


def _outcome_summary(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not outcomes:
        return {
            "label_count": 0,
            "directional_hit_count": 0,
            "pending_label_count": 0,
            "pending_share": 0.0,
            "label_types": [],
            "latest_completed_exit_date": "",
        }
    pending_count = sum(
        1
        for row in outcomes
        if str(row.get("label_status") or row.get("status") or "completed")
        == "pending"
    )
    completed_exit_dates = [
        _date_key(row.get("exit_datetime") or row.get("exit_date") or "")
        for row in outcomes
        if str(row.get("label_status") or row.get("status") or "completed")
        == "completed"
    ]
    return {
        "label_count": len(outcomes),
        "directional_hit_count": sum(1 for row in outcomes if row.get("directional_hit") is True),
        "pending_label_count": pending_count,
        "pending_share": round(pending_count / len(outcomes), 4),
        "label_types": sorted(
            {
                str(row.get("label_type") or "")
                for row in outcomes
                if str(row.get("label_type") or "")
            }
        ),
        "latest_completed_exit_date": max(completed_exit_dates, default=""),
    }


def _freshness_bucket(*, latest_completed_exit_date: str, as_of_date: str) -> str:
    if not latest_completed_exit_date:
        return "pending_no_completed_exit"
    if as_of_date and latest_completed_exit_date >= as_of_date:
        return "completed_exit_after_prior_as_of"
    return "historical_completed_exit"


def _rating_bucket(value: Any) -> str:
    bucket = _safe_token(value or "pending_or_unrated")
    return bucket if bucket in RATING_BUCKETS else "pending_or_unrated"


def _reliability_bucket(value: Any) -> str:
    bucket = _safe_token(value or "insufficient_data")
    return bucket if bucket in RELIABILITY_BUCKETS else "insufficient_data"


def _performance_context_bucket(value: Any) -> str:
    bucket = _safe_token(value or "insufficient_data")
    return bucket if bucket in PERFORMANCE_CONTEXT_BUCKETS else "insufficient_data"


def _current_data_required_fields(agent_id: str) -> list[str]:
    if agent_id == "superinvestor.munger":
        return [
            "roic_roe",
            "gross_margin",
            "free_cash_flow",
            "balance_sheet",
            "valuation",
            "business_predictability",
        ]
    if agent_id == "superinvestor.burry":
        return [
            "valuation_metrics",
            "fcf_yield",
            "balance_sheet",
            "debt_cash",
            "catalyst_status",
            "downside_risk",
        ]
    if agent_id == "superinvestor.ackman":
        return [
            "free_cash_flow",
            "pricing_power",
            "management_actions",
            "capital_allocation",
            "valuation",
        ]
    if agent_id == "superinvestor.druckenmiller":
        return [
            "price_trend",
            "earnings_revision",
            "policy_liquidity",
            "risk_reward",
        ]
    if agent_id.startswith("sector."):
        return ["orders", "inventory", "prices", "policy", "supply_chain", "liquidity"]
    if agent_id.startswith("macro."):
        return [
            "latest_macro_series",
            "market_price_or_rate",
            "policy_event_status",
            "risk_flags",
        ]
    if agent_id.startswith("decision."):
        return [
            "current_price",
            "portfolio_context",
            "risk_budget",
            "liquidity",
            "prior_conflict_check",
        ]
    return ["current_data_confirmation"]


def _claim_context_as_of_date(
    claim: Mapping[str, Any],
    report_meta: Mapping[str, Any],
) -> str:
    return _date_key(
        claim.get("signal_datetime")
        or claim.get("as_of_datetime")
        or report_meta.get("publish_datetime")
        or report_meta.get("accessible_datetime")
        or report_meta.get("publish_date")
    )


def _latest_snapshot_on_or_before(
    snapshots: Sequence[Mapping[str, Any]],
    as_of_date: str,
) -> Mapping[str, Any]:
    if not snapshots:
        return {}
    if not as_of_date:
        return sorted(
            snapshots,
            key=lambda row: str(row.get("as_of_date") or ""),
            reverse=True,
        )[0]
    exact = [row for row in snapshots if str(row.get("as_of_date") or "") == as_of_date]
    if exact:
        return exact[0]
    eligible = [
        row
        for row in snapshots
        if str(row.get("as_of_date") or "") <= as_of_date
    ]
    return sorted(
        eligible,
        key=lambda row: str(row.get("as_of_date") or ""),
        reverse=True,
    )[0] if eligible else {}


def _matching_stock_context_snapshot(
    claim: Mapping[str, Any],
    report_meta: Mapping[str, Any],
    snapshots: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    target = _ensure_mapping(claim.get("target"))
    stock_symbol = str(
        report_meta.get("ts_code") or target.get("target_id") or ""
    ).strip().upper()
    if not stock_symbol:
        return {}
    candidates = [
        row
        for row in snapshots
        if str(row.get("stock_symbol") or "").strip().upper() == stock_symbol
    ]
    return _latest_snapshot_on_or_before(
        candidates,
        _claim_context_as_of_date(claim, report_meta),
    )


def _matching_industry_context_snapshot(
    claim: Mapping[str, Any],
    report_meta: Mapping[str, Any],
    snapshots: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    target = _ensure_mapping(claim.get("target"))
    sector = str(
        report_meta.get("sector")
        or report_meta.get("industry")
        or target.get("target_id")
        or target.get("target_name")
        or ""
    ).strip()
    if not sector:
        return {}
    candidates = [
        row
        for row in snapshots
        if sector in str(row.get("canonical_sector") or "")
        or str(row.get("canonical_sector") or "") in sector
    ]
    return _latest_snapshot_on_or_before(
        candidates,
        _claim_context_as_of_date(claim, report_meta),
    )


def _context_snapshot_status(
    stock_context_snapshot: Mapping[str, Any],
    industry_context_snapshot: Mapping[str, Any],
    missing_reasons: Sequence[str],
) -> str:
    if missing_reasons:
        return "missing"
    if stock_context_snapshot or industry_context_snapshot:
        return "available"
    return "not_required"


def _context_snapshot_missing_reasons(
    agent_id: str,
    claim: Mapping[str, Any],
    report_meta: Mapping[str, Any],
    *,
    stock_context_snapshot: Mapping[str, Any] | None = None,
    industry_context_snapshot: Mapping[str, Any] | None = None,
) -> list[str]:
    domain = _claim_domain(claim, report_meta)
    if domain == "stock" and (
        agent_id.startswith("superinvestor.")
        or agent_id.startswith("decision.")
        or agent_id == "sector.relationship_mapper"
    ):
        if stock_context_snapshot:
            return []
        return ["stock_context_snapshot_missing"]
    if domain == "industry" and (
        agent_id.startswith("sector.") or agent_id.startswith("decision.")
    ):
        if industry_context_snapshot:
            return []
        return ["industry_context_snapshot_missing"]
    return []


def _index_metadata(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by_key: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        for key in (row.get("report_id"), row.get("source_id")):
            text = str(key or "")
            if text:
                by_key[text] = row
    return by_key


def _claim_report_key(claim: Mapping[str, Any]) -> str:
    return str(claim.get("report_id") or claim.get("source_id") or "")


def _claim_as_of_date(
    claim: Mapping[str, Any], metadata_by_report: Mapping[str, Mapping[str, Any]]
) -> str:
    report_meta = metadata_by_report.get(_claim_report_key(claim), {})
    return _date_key(
        claim.get("signal_datetime")
        or claim.get("as_of_datetime")
        or report_meta.get("publish_datetime")
        or report_meta.get("accessible_datetime")
        or ""
    )


def _horizon_bucket(value: Any) -> str:
    horizon = _ensure_mapping(value)
    bucket = str(horizon.get("bucket") or "").strip()
    if bucket:
        return _safe_token(bucket)
    max_days = _int_or_none(horizon.get("max_days"))
    if max_days is None:
        return "unknown"
    if max_days <= 10:
        return "short"
    if max_days <= 120:
        return "medium"
    return "long"


def _group_by(
    rows: Sequence[Mapping[str, Any]], key: str
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    return grouped


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    stat = path.stat()
    return _read_jsonl_cached(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _read_jsonl_cached(
    path: str, mtime_ns: int, size: int
) -> tuple[dict[str, Any], ...]:
    del mtime_ns, size
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return tuple(rows)


def _redacted_id(prefix: str, raw: Any) -> str:
    digest = sha256(str(raw or "").encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _safe_token(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "_", text)
    return text[:80] if text else "unknown"


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = re.sub(r"[^a-z0-9_.]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_.")


def _date_key(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else ""


def _round_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(number, 4) if isfinite(number) else 0.0


def _safe_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _ensure_str_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _ensure_list(value) if str(item).strip()]


def _combined_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            parts.extend(_combined_text(v) for v in value.values())
        elif isinstance(value, (list, tuple)):
            parts.extend(_combined_text(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _walk_mapping(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key), child
            yield from _walk_mapping(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_mapping(child, f"{path}[{index}]")


def _looks_like_private_reference(value: str) -> bool:
    lowered = value.lower()
    if ".pdf" in lowered or ".md" in lowered or "source_span" in lowered:
        return True
    return ".mosaic/" in lowered or "registry/report_intelligence/markdown" in lowered
