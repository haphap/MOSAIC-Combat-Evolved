"""RKE all-agent benchmark planning RPCs.

These handlers build formal benchmark manifests and preflight evidence. They do
not run LLMs or write private artifacts.
"""

from __future__ import annotations

from typing import Any

from ..registry import method
from .prompts import _AGENTS_BY_LAYER
from .prompts import _ALL_AGENTS
from .prompts import _DEFAULT_COHORT
from .prompts import prompts_preflight

_EPISODES: tuple[dict[str, Any], ...] = (
    {
        "episode_id": "2009_post_crisis_recovery",
        "regime": "post-crisis recovery / liquidity expansion",
        "as_of_dates": ["2009-03-16", "2009-07-01"],
    },
    {
        "episode_id": "2011_inflation_tightening_pressure",
        "regime": "inflation and tightening pressure",
        "as_of_dates": ["2011-03-01", "2011-08-08"],
    },
    {
        "episode_id": "2015_china_equity_bubble_crash",
        "regime": "China equity bubble/crash",
        "as_of_dates": ["2015-04-20", "2015-07-08"],
    },
    {
        "episode_id": "2018_deleveraging_trade_friction",
        "regime": "deleveraging / trade friction",
        "as_of_dates": ["2018-03-22", "2018-10-08"],
    },
    {
        "episode_id": "2020_pandemic_policy_response",
        "regime": "pandemic shock and policy response",
        "as_of_dates": ["2020-02-03", "2020-03-24"],
    },
    {
        "episode_id": "2021_commodity_inflation_cycle",
        "regime": "commodity and inflation cycle",
        "as_of_dates": ["2021-02-18", "2021-10-15"],
    },
    {
        "episode_id": "2022_usd_rate_china_stress",
        "regime": "USD strength / rate shock / China stress",
        "as_of_dates": ["2022-03-16", "2022-10-24"],
    },
    {
        "episode_id": "2024_2026_ai_liquidity_sector_rotation",
        "regime": "AI/liquidity/sector-rotation regime",
        "as_of_dates": ["2024-02-05", "2025-09-01", "2026-06-18"],
    },
)

_MODEL_CONFIGS: tuple[dict[str, Any], ...] = (
    {
        "model_config_id": "baseline_current_config",
        "runner": "configured_default",
        "required": True,
    },
    {
        "model_config_id": "local_qwen_27b",
        "runner": "local_vllm",
        "model_family": "qwen_27b",
        "required": True,
    },
    {
        "model_config_id": "local_qwen3_6_35b",
        "runner": "local_vllm",
        "model_family": "qwen3.6_35b",
        "required": True,
    },
    {
        "model_config_id": "api_model_if_available",
        "runner": "api",
        "required": False,
    },
)

_INPUT_REQUIREMENTS = (
    "private_prompt_hash_and_repo_revision",
    "pit_tool_data",
    "redacted_rke_priors",
    "tool_summaries",
    "output_schema",
    "context_hash",
    "model_parameters",
)

_SCORING_METRICS = (
    "schema_validity",
    "json_parse_failure",
    "timeout_or_content_empty_rate",
    "directional_hit",
    "subsequent_after_cost_return",
    "benchmark_relative_alpha",
    "drawdown",
    "turnover_cost",
    "confidence_calibration",
    "rke_prior_usage_quality",
    "stale_contradictory_prior_rejection",
    "current_data_confirmation",
    "safety_violations",
)


@method("rke_benchmark.fixed_episode_manifest")
def fixed_episode_manifest(params: dict[str, Any]) -> dict[str, Any]:
    """Return the E2 fixed-episode benchmark manifest and prompt preflight."""
    cohort = params.get("cohort") or _DEFAULT_COHORT
    if not isinstance(cohort, str) or not cohort.strip():
        cohort = _DEFAULT_COHORT
    prompt_preflight = prompts_preflight(
        {"cohort": cohort, "agents": list(_ALL_AGENTS), "langs": ["zh", "en"]}
    )
    as_of_date_count = sum(len(episode["as_of_dates"]) for episode in _EPISODES)
    model_count = len(_MODEL_CONFIGS)
    planned_run_count = as_of_date_count * len(_ALL_AGENTS) * model_count
    blocked_reasons = sorted(
        {
            str(row.get("blocked_reason"))
            for row in prompt_preflight["rows"]
            if row.get("status") != "ready" and row.get("blocked_reason")
        }
    )
    return {
        "schema_version": "rke_fixed_episode_benchmark_manifest_v1",
        "benchmark_status": (
            "ready_to_run" if prompt_preflight["ready"] else "blocked_preflight"
        ),
        "cohort": cohort,
        "episode_count": len(_EPISODES),
        "as_of_date_count": as_of_date_count,
        "agent_count": len(_ALL_AGENTS),
        "model_config_count": model_count,
        "planned_run_count": planned_run_count,
        "episodes": [dict(episode) for episode in _EPISODES],
        "agents_by_layer": {
            layer: list(agents) for layer, agents in _AGENTS_BY_LAYER.items()
        },
        "model_configs": [dict(config) for config in _MODEL_CONFIGS],
        "input_requirements": list(_INPUT_REQUIREMENTS),
        "scoring_metrics": list(_SCORING_METRICS),
        "prompt_preflight": {
            "ready": prompt_preflight["ready"],
            "row_count": prompt_preflight["row_count"],
            "blocked_count": prompt_preflight["blocked_count"],
            "blocked_reasons": blocked_reasons,
            "fallback_used": False,
        },
        "manual_review": {
            "status": "not_run",
            "required": True,
            "reviewer_timestamp": None,
        },
        "promotion_allowed": False,
    }
