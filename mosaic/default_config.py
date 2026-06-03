"""MOSAIC runtime default configuration.

Ported from ``etfagents/default_config.py`` with the following adaptations:

* env vars renamed ``ETFAGENTS_*`` → ``MOSAIC_*`` (ETF/legacy fallbacks dropped — MOSAIC is a fresh repo)
* default LLM provider switched to Anthropic Claude Sonnet (per Plan §1)
* ``output_language`` defaults to ``Chinese``
* a ``cohorts`` block added describing the Phase 5 PRISM training pool with
  ``euphoria_2021`` as the startup cohort (Plan §1, §9)
* ``data_vendors`` extended with ``macro_data`` (Phase 0 Day 3 / Phase 2 Layer-1)
"""

from __future__ import annotations

import os

_MOSAIC_HOME = os.path.join(os.path.expanduser("~"), ".mosaic")

# Repo-relative directory used as the default for data/ when MOSAIC_DATA_DIR is unset.
# Resolved lazily so tests can move the repo around without restart.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")


DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "data_dir": os.getenv("MOSAIC_DATA_DIR", _DEFAULT_DATA_DIR),
    "results_dir": os.getenv(
        "MOSAIC_RESULTS_DIR",
        os.path.join(_MOSAIC_HOME, "logs"),
    ),
    "data_cache_dir": os.getenv(
        "MOSAIC_CACHE_DIR",
        os.path.join(_MOSAIC_HOME, "cache"),
    ),
    # ============== LLM settings ==============
    # Default to Anthropic Claude Sonnet (Plan §1). Local Lemonade Qwen and
    # DeepSeek can be swapped in via config.set at runtime to control cost.
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-sonnet-4",
    "quick_think_llm": "claude-sonnet-4",
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": "medium",
    # Output language for analyst reports + final decision
    # Internal agent debate stays in English for reasoning quality.
    "output_language": "Chinese",
    "research_depth_name": "标准",
    # ============== Debate / discussion ==============
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "report_context_char_limit": 16000,
    "debate_history_char_limit": 12000,
    "memory_min_similarity": 0.15,
    "benchmark_ticker": os.getenv("MOSAIC_BENCHMARK_TICKER"),
    "checkpoint_enabled": False,
    "memory_log_path": os.path.join(
        os.getenv("MOSAIC_RESULTS_DIR", os.path.join(_MOSAIC_HOME, "logs")),
        "trading_memory.md",
    ),
    "memory_log_max_entries": None,
    "validation_mode": "static_plus_llm",
    "memory_mode": "full",
    "memory_in_backtest": False,
    "continuity_max_age_days": 30,
    "continuity_brief_char_limit": 2000,
    "lesson_brief_char_limit": 1500,
    "method_brief_char_limit": 1500,
    "playbook_active_days": 90,
    "playbook_max_active_per_scope": 20,
    "role_brief_specs": {
        "analyst": ["summary", "key_drivers", "watch_items", "invalidation_signals"],
        "trader": ["trader_summary", "stance", "trigger_summary", "invalidation_signals"],
        "research_manager": ["summary", "stance", "research_summary", "watch_items", "invalidation_signals"],
        "portfolio_manager": ["summary", "stance", "portfolio_summary", "watch_items", "invalidation_signals"],
    },
    # ============== Data vendors ==============
    # Category-level configuration (default for all tools in category).
    # Phase 0 Day 2/3 will populate macro_data + sector vendor maps fully.
    "data_vendors": {
        "core_stock_apis": "tushare,akshare,yfinance",
        "technical_indicators": "tushare,yfinance",
        "fundamental_data": "tushare,yfinance",
        "news_data": "opencli,brave,yfinance",
        "etf_market_data": "tushare",
        "etf_reference_data": "tushare",
        "broker_research": "tushare",
        "stock_research": "tushare",
        "macro_data": "tushare,fred,akshare",
    },
    # Tool-level configuration (takes precedence over category-level).
    "tool_vendors": {
        "get_stock_data": "tushare",
        "get_indicators": "tushare",
        "get_fundamentals": "tushare",
        "get_balance_sheet": "tushare",
        "get_cashflow": "tushare",
        "get_income_statement": "tushare",
        "get_news": "opencli",
        "get_global_news": "opencli",
        "get_insider_transactions": "tushare",
        "get_etf_price_data": "tushare",
        "get_etf_indicators": "tushare",
        "get_etf_info": "tushare",
        "get_etf_nav": "tushare",
        "get_etf_holdings": "tushare",
        "get_etf_share": "tushare",
        "get_etf_universe": "tushare",
        "get_broker_research": "tushare",
        "get_stock_research": "tushare",
        # Macro layer (Phase 0 Day 3+)
        "get_pboc_ops": "tushare",
        "get_lhb_ranking": "tushare",
        "get_yield_curve_cn": "tushare",
        "get_us_china_spread": "tushare,fred",
        "get_xueqiu_heat": "akshare",
        "get_industry_policy": "tushare",
        "get_fred_series": "fred",
        # Macro layer gap-fill (Plan §14 #8 / §11.5 4.0 P1)
        "get_usdcny": "tushare",
        "get_commodity_prices": "tushare",
        "get_ivx": "yfinance",
        "get_etf_indicator": "tushare",
        "get_fund_flow": "tushare",
        "get_caixin_sentiment": "opencli",
        "get_us_china_relations": "tsinghua",
        "get_property_data": "akshare",
        "get_stock_moneyflow": "tushare",
        "get_industry_moneyflow": "tushare",
    },
    "snapshot_max_age_days": 30,
    "backtest_cache_max_age_days": 90,
    "checkpoint_max_age_days": 30,
    # ============== Cohorts (Phase 5 PRISM, Plan §9) ==============
    "active_cohort": "euphoria_2021",
    "cohorts": {
        "bull_2007":        {"start": "2006-01-04", "end": "2007-10-16"},
        "crisis_2008":      {"start": "2007-10-17", "end": "2008-10-28"},
        "bull_2016":        {"start": "2016-01-29", "end": "2017-12-29"},
        "crisis_covid":     {"start": "2018-10-19", "end": "2020-03-23"},
        "recovery_2020":    {"start": "2020-03-24", "end": "2020-12-31"},
        "euphoria_2021":    {"start": "2020-07-01", "end": "2021-02-18"},
        "rate_tightening":  {"start": "2022-04-01", "end": "2023-12-31"},
    },
    # Autoresearch constraints (Plan §1, §8)
    "autoresearch": {
        "agent_mutation_cooldown_hours": 24,
        "keep_revert_lockout_days": 3,
        "keep_threshold_delta_sharpe": 0.1,
        "monthly_modification_cap_per_cohort": 100,
        "evaluation_horizon_trading_days": 5,
        # Macro layer-aware selection (autoresearch macro plan MVP). macro agents
        # are ranked within their own layer; the interval gates how often macro
        # is picked (~the 20% quota in steady state). macro_neutral_band is the
        # single source for both the macro scorer and selection.
        "macro_quota": 0.2,
        "min_macro_interval_days": 5,
        "macro_neutral_band": 0.005,
        "recent_revert_penalty_days": 14,
        # Mirror kept (merged-to-main) prompt mutations to a self-hosted git
        # server. OPT-IN; default OFF keeps autoresearch 100% local. When push
        # is True, the keep-path runs `git push <remote> main` after the merge
        # (operator must pre-configure the remote + credentials). A push failure
        # never aborts the keep decision — it is logged and swallowed.
        "git": {
            "push": False,
            "remote": "origin",
        },
    },
    # MiroFish forward-simulation (Plan §11.8 / §11.8.1). 'engine' selects the
    # scenario generator: 'montecarlo' (default — i.i.d. correlated paths +
    # optional per-asset reflexivity kernel) or 'swarm' (Phase 7M.1 agent-to-
    # agent interaction engine). Swarm is OPT-IN; default keeps the cheap,
    # well-validated Monte-Carlo path.
    "mirofish": {
        "engine": "montecarlo",
        # 'scorer' selects how a rec is graded against a scenario's paths:
        # 'terminal' (default — direction × cumulative return) or 'path_aware'
        # (direction-adjusted equity curve with a max-drawdown penalty, so the
        # realised path shape the swarm engine varies reaches the signal).
        # OPT-IN; default keeps the terminal scorer byte-identical.
        "scorer": "terminal",
        # 'inject_context': when True, the CIO (Layer 4) prompt gets an appended
        # MiroFish forward-looking section (latest persisted scenario context:
        # regime / highest-conviction direction / tail risk) with a "simulation
        # only" disclaimer (7M Step 2). OPT-IN; default OFF — daily-cycle prompts
        # are byte-identical unless turned on.
        "inject_context": False,
    },
}
