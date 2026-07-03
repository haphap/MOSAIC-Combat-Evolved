"""RKE all-agent benchmark planning RPCs.

These handlers build formal benchmark manifests and preflight evidence. They do
not run LLMs or write private artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..protocol import INVALID_PARAMS, RpcError
from ..registry import method
from .prompts import _AGENTS_BY_LAYER
from .prompts import _ALL_AGENTS
from .prompts import _DEFAULT_COHORT
from .prompts import _LAYER_BY_AGENT
from .prompts import _repo_root
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

_CAPTURE_REL_PATH = Path(".mosaic/rke/all_agent_evolution/agent_claim_footprints.jsonl")
_PROMPT_MUTATION_CANDIDATES_REL_PATH = Path(
    "registry/report_intelligence/prompt_mutation_candidates.jsonl"
)
_CLAIM_TYPES_BY_LAYER: dict[str, tuple[str, ...]] = {
    "macro": ("macro_regime_claim", "macro_series_claim", "macro_asset_claim"),
    "sector": ("sector_claim", "ticker_metric_claim"),
    "superinvestor": ("style_candidate_claim", "rejection_reason"),
    "decision": ("portfolio_action_claim", "risk_claim", "dissent_note"),
}
_FORBIDDEN_CAPTURE_FIELDS = frozenset(
    {
        "abstract",
        "claim_text",
        "content",
        "markdown",
        "markdown_path",
        "pdf",
        "pdf_path",
        "prompt",
        "prompt_body",
        "raw_output",
        "review_note",
        "source_span_id",
        "source_span_ids",
        "source_text",
        "source_url",
        "text",
        "title",
        "url",
    }
)
_TARGET_FIELDS = ("target_type", "target_id", "metric_family", "ticker", "sector")


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


@method("rke_benchmark.capture_agent_claim_footprints")
def capture_agent_claim_footprints(params: dict[str, Any]) -> dict[str, Any]:
    """Write redacted agent claim/footprint rows to the local private store."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    rows = params.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RpcError(INVALID_PARAMS, "'rows' must be a non-empty list")

    sanitized: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            failures.append(f"rows[{index}]: must be an object")
            continue
        forbidden_paths = _forbidden_paths(row)
        if forbidden_paths:
            failures.append(
                f"rows[{index}]: forbidden private/prose fields "
                + ", ".join(forbidden_paths[:5])
            )
            continue
        try:
            sanitized.append(_sanitize_claim_footprint_row(benchmark_run_id, row, index))
        except ValueError as exc:
            failures.append(f"rows[{index}]: {exc}")

    if failures:
        return {
            "capture_status": "blocked",
            "captured_count": 0,
            "private_rows_path": _CAPTURE_REL_PATH.as_posix(),
            "failures": failures,
            "privacy_scan": {
                "private_text_included": False,
                "source_prose_included": False,
                "forbidden_field_violation_count": len(failures),
            },
        }

    output_path = _repo_root() / _CAPTURE_REL_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for row in sanitized:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    layer_counts: dict[str, int] = {}
    claim_type_counts: dict[str, int] = {}
    for row in sanitized:
        _increment(layer_counts, row["layer"])
        _increment(claim_type_counts, row["claim_type"])
    return {
        "capture_status": "captured",
        "captured_count": len(sanitized),
        "private_rows_path": _CAPTURE_REL_PATH.as_posix(),
        "aggregate_profile_summary": {
            "benchmark_run_id": benchmark_run_id,
            "layer_counts": dict(sorted(layer_counts.items())),
            "claim_type_counts": dict(sorted(claim_type_counts.items())),
            "current_data_confirmed_count": sum(
                1 for row in sanitized if row["current_data_confirmed"] is True
            ),
            "rke_context_hash_count": sum(
                1 for row in sanitized if row.get("rke_context_hash")
            ),
        },
        "privacy_scan": {
            "private_text_included": False,
            "source_prose_included": False,
            "forbidden_field_violation_count": 0,
        },
    }


@method("rke_benchmark.agent_footprint_summary")
def agent_footprint_summary(params: dict[str, Any]) -> dict[str, Any]:
    """Summarize private captured rows without returning row bodies."""
    benchmark_run_id = _clean_str(params.get("benchmark_run_id"))
    path = _repo_root() / _CAPTURE_REL_PATH
    if not path.exists():
        return _empty_footprint_summary(benchmark_run_id)

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"line {line_number}: invalid json")
                continue
            if not isinstance(row, dict):
                failures.append(f"line {line_number}: row must be object")
                continue
            if benchmark_run_id and row.get("benchmark_run_id") != benchmark_run_id:
                continue
            forbidden_paths = _forbidden_paths(row)
            if forbidden_paths:
                failures.append(
                    f"line {line_number}: forbidden private/prose fields "
                    + ", ".join(forbidden_paths[:5])
                )
                continue
            rows.append(row)

    layer_counts: dict[str, int] = {}
    claim_type_counts: dict[str, int] = {}
    prior_quality_counts: dict[str, int] = {}
    for row in rows:
        _increment(layer_counts, _clean_str(row.get("layer")) or "unknown")
        _increment(claim_type_counts, _clean_str(row.get("claim_type")) or "unknown")
        _increment(
            prior_quality_counts,
            _clean_str(row.get("rke_prior_usage_quality")) or "unknown",
        )
    return {
        "summary_status": "blocked" if failures else "ready",
        "private_rows_path": _CAPTURE_REL_PATH.as_posix(),
        "benchmark_run_id": benchmark_run_id,
        "row_count": len(rows),
        "layer_counts": dict(sorted(layer_counts.items())),
        "claim_type_counts": dict(sorted(claim_type_counts.items())),
        "rke_prior_usage_quality_counts": dict(sorted(prior_quality_counts.items())),
        "current_data_confirmed_count": sum(
            1 for row in rows if row.get("current_data_confirmed") is True
        ),
        "stale_prior_rejected_count": sum(
            1 for row in rows if row.get("stale_prior_rejected") is True
        ),
        "contradictory_prior_handled_count": sum(
            1 for row in rows if row.get("contradictory_prior_handled") is True
        ),
        "rke_context_hash_count": sum(1 for row in rows if row.get("rke_context_hash")),
        "privacy_scan": {
            "private_text_included": False,
            "source_prose_included": False,
            "forbidden_field_violation_count": len(failures),
        },
        "failures": failures,
    }


def _empty_footprint_summary(benchmark_run_id: str) -> dict[str, Any]:
    return {
        "summary_status": "empty",
        "private_rows_path": _CAPTURE_REL_PATH.as_posix(),
        "benchmark_run_id": benchmark_run_id,
        "row_count": 0,
        "layer_counts": {},
        "claim_type_counts": {},
        "rke_prior_usage_quality_counts": {},
        "current_data_confirmed_count": 0,
        "stale_prior_rejected_count": 0,
        "contradictory_prior_handled_count": 0,
        "rke_context_hash_count": 0,
        "privacy_scan": {
            "private_text_included": False,
            "source_prose_included": False,
            "forbidden_field_violation_count": 0,
        },
        "failures": [],
    }


@method("rke_benchmark.darwinian_autoresearch_input_manifest")
def darwinian_autoresearch_input_manifest(params: dict[str, Any]) -> dict[str, Any]:
    """Build the E5 manifest consumed by Darwinian/autoresearch scoring."""
    benchmark_run_id = _clean_str(params.get("benchmark_run_id"))
    summary = agent_footprint_summary({"benchmark_run_id": benchmark_run_id})
    outcome_metrics = params.get("downstream_outcome_metrics")
    if not isinstance(outcome_metrics, dict):
        outcome_metrics = {}
    prompt_provenance = params.get("prompt_mutation_provenance")
    if not isinstance(prompt_provenance, dict):
        prompt_provenance = {}

    outcome_ready = _outcome_metrics_ready(outcome_metrics)
    provenance_ready = _prompt_mutation_provenance_ready(prompt_provenance)
    blocked_reasons: list[str] = []
    if summary["summary_status"] != "ready" or summary["row_count"] == 0:
        blocked_reasons.append("agent_footprint_summary_missing")
    if not outcome_ready:
        blocked_reasons.append("downstream_outcome_metrics_missing")
    if not provenance_ready:
        blocked_reasons.append("prompt_mutation_provenance_missing")
    if summary["privacy_scan"]["forbidden_field_violation_count"]:
        blocked_reasons.append("agent_footprint_privacy_scan_failed")

    return {
        "schema_version": "rke_darwinian_autoresearch_input_manifest_v1",
        "manifest_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "blocked_reasons": blocked_reasons,
        "rke_prior_treated_as_current_data": False,
        "skill_inputs": {
            "current_data_skill": {
                "current_data_confirmed_count": summary[
                    "current_data_confirmed_count"
                ],
                "source": "agent_claim_footprint_summary",
            },
            "research_prior_usage_skill": {
                "rke_prior_usage_quality_counts": summary[
                    "rke_prior_usage_quality_counts"
                ],
                "rke_context_hash_count": summary["rke_context_hash_count"],
                "source": "agent_claim_footprint_summary",
            },
            "stale_prior_rejection_skill": {
                "stale_prior_rejected_count": summary["stale_prior_rejected_count"],
                "contradictory_prior_handled_count": summary[
                    "contradictory_prior_handled_count"
                ],
                "source": "agent_claim_footprint_summary",
            },
            "schema_contract_reliability": {
                "summary_status": summary["summary_status"],
                "privacy_scan": summary["privacy_scan"],
                "source": "agent_claim_footprint_summary",
            },
            "risk_adjusted_downstream_outcome": {
                "status": "ready" if outcome_ready else "missing",
                "metrics": _safe_metric_subset(
                    outcome_metrics,
                    ("risk_adjusted_return", "alpha", "max_drawdown"),
                ),
            },
            "turnover_cost_discipline": {
                "status": "ready" if outcome_ready else "missing",
                "metrics": _safe_metric_subset(outcome_metrics, ("turnover", "cost_bps")),
            },
            "prompt_mutation_provenance": {
                "status": "ready" if provenance_ready else "missing",
                "prompt_repo_id": _clean_str(prompt_provenance.get("prompt_repo_id")),
                "prompt_repo_revision": _clean_str(
                    prompt_provenance.get("prompt_repo_revision")
                ),
                "prompt_sha256": _clean_str(prompt_provenance.get("prompt_sha256")),
                "prompt_commit_hash": _clean_str(
                    prompt_provenance.get("prompt_commit_hash")
                ),
            },
        },
        "privacy_scan": summary["privacy_scan"],
        "promotion_allowed": False,
    }


@method("rke_benchmark.candidate_consumption_manifest")
def candidate_consumption_manifest(params: dict[str, Any]) -> dict[str, Any]:
    """Summarize Part 1 mutation candidates for Part 2 private lifecycle use."""
    supplied_candidates = params.get("candidates")
    if supplied_candidates is None:
        candidates, load_failures = _read_prompt_mutation_candidate_rows()
    elif isinstance(supplied_candidates, list):
        candidates, load_failures = supplied_candidates, []
    else:
        raise RpcError(INVALID_PARAMS, "'candidates' must be a list when provided")

    failures = list(load_failures)
    summaries: list[dict[str, Any]] = []
    candidate_type_counts: dict[str, int] = {}
    target_scope_counts: dict[str, int] = {}
    blocked_reason_counts: dict[str, int] = {}
    refusal_count = 0
    for index, row in enumerate(candidates, 1):
        if not isinstance(row, dict):
            failures.append(f"candidate {index}: must be an object")
            continue
        forbidden_paths = _forbidden_paths(row)
        if forbidden_paths:
            failures.append(
                f"candidate {index}: forbidden private/prose fields "
                + ", ".join(forbidden_paths[:5])
            )
            continue
        row_failures = _candidate_contract_failures(row, index)
        if row_failures:
            failures.extend(row_failures)
            continue
        candidate_type = _clean_str(row.get("candidate_type")) or "unknown"
        target_scope = _clean_str(row.get("target_scope")) or "unknown"
        blocked_by = _safe_str_list(row.get("blocked_by"))
        summaries.append(
            {
                "mutation_candidate_id": _clean_str(row.get("mutation_candidate_id")),
                "candidate_type": candidate_type,
                "target_scope": target_scope,
                "target_component": _clean_str(row.get("target_component")),
                "severity": _clean_str(row.get("severity")),
                "blocked_by": blocked_by,
                "promotion_state": _clean_str(row.get("promotion_state")),
                "manual_review_required": row.get("manual_review_required") is True,
                "production_prompt_change_allowed": False,
                "private_text_included": False,
                "trigger_sources": _safe_str_list(row.get("trigger_sources")),
                "validation_requirements": _safe_str_list(
                    row.get("validation_requirements")
                ),
            }
        )
        _increment(candidate_type_counts, candidate_type)
        _increment(target_scope_counts, target_scope)
        if "refusal" in candidate_type:
            refusal_count += 1
        for reason in blocked_by:
            _increment(blocked_reason_counts, reason)

    missing_artifact = "prompt_mutation_candidates_missing" in failures
    manifest_status = (
        "blocked_preflight"
        if failures or not summaries
        else "ready_for_private_prompt_lifecycle"
    )
    return {
        "schema_version": "rke_candidate_consumption_manifest_v1",
        "manifest_status": manifest_status,
        "artifact_path": _PROMPT_MUTATION_CANDIDATES_REL_PATH.as_posix(),
        "candidate_count": len(summaries),
        "refusal_count": refusal_count,
        "candidate_type_counts": dict(sorted(candidate_type_counts.items())),
        "target_scope_counts": dict(sorted(target_scope_counts.items())),
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "candidate_summaries": summaries,
        "manifest_blockers": failures,
        "missing_artifact": missing_artifact,
        "private_prompt_mutation_required": True,
        "production_prompt_change_allowed": False,
        "candidate_consumption_policy": (
            "part1_candidates_are_evidence_only_no_direct_prompt_write"
        ),
        "privacy_scan": {
            "private_text_included": False,
            "source_prose_included": False,
            "forbidden_field_violation_count": len(failures),
        },
    }


def _read_prompt_mutation_candidate_rows() -> tuple[list[dict[str, Any]], list[str]]:
    path = _repo_root() / _PROMPT_MUTATION_CANDIDATES_REL_PATH
    if not path.exists():
        return [], ["prompt_mutation_candidates_missing"]
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"line {line_number}: invalid json")
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                failures.append(f"line {line_number}: row must be object")
    return rows, failures


def _candidate_contract_failures(row: dict[str, Any], index: int) -> list[str]:
    failures: list[str] = []
    prefix = f"candidate {index}"
    if row.get("private_text_included") is not False:
        failures.append(f"{prefix}: private_text_included must be false")
    if row.get("production_prompt_change_allowed") is not False:
        failures.append(f"{prefix}: production_prompt_change_allowed must be false")
    if row.get("manual_review_required") is not True:
        failures.append(f"{prefix}: manual_review_required must be true")
    if _clean_str(row.get("promotion_state")) != "shadow_candidate_only":
        failures.append(f"{prefix}: promotion_state must remain shadow_candidate_only")
    for key in (
        "mutation_candidate_id",
        "candidate_type",
        "target_scope",
        "target_component",
        "severity",
    ):
        if not _clean_str(row.get(key)):
            failures.append(f"{prefix}: {key} is required")
    if not _safe_str_list(row.get("validation_requirements")):
        failures.append(f"{prefix}: validation_requirements are required")
    return failures


def _outcome_metrics_ready(metrics: dict[str, Any]) -> bool:
    required = ("risk_adjusted_return", "alpha", "max_drawdown", "turnover", "cost_bps")
    return all(isinstance(metrics.get(key), (int, float)) for key in required)


def _prompt_mutation_provenance_ready(provenance: dict[str, Any]) -> bool:
    return all(
        bool(_clean_str(provenance.get(key)))
        for key in ("prompt_repo_id", "prompt_repo_revision", "prompt_sha256")
    )


def _safe_metric_subset(metrics: dict[str, Any], keys: tuple[str, ...]) -> dict[str, float]:
    return {
        key: float(metrics[key])
        for key in keys
        if isinstance(metrics.get(key), (int, float))
    }


def _sanitize_claim_footprint_row(
    benchmark_run_id: str, row: dict[str, Any], index: int
) -> dict[str, Any]:
    agent = _clean_str(row.get("agent"))
    if agent not in _LAYER_BY_AGENT:
        raise ValueError(f"unknown agent {agent!r}")
    layer = _clean_str(row.get("layer")) or _LAYER_BY_AGENT[agent]
    if layer != _LAYER_BY_AGENT[agent]:
        raise ValueError(f"layer {layer!r} does not match agent {agent!r}")
    claim_type = _clean_str(row.get("claim_type"))
    if claim_type not in _CLAIM_TYPES_BY_LAYER[layer]:
        raise ValueError(f"unsupported claim_type {claim_type!r} for layer {layer!r}")
    as_of_date = _clean_str(row.get("as_of_date"))
    if not as_of_date:
        raise ValueError("as_of_date is required")
    target = _safe_target(row.get("target"))
    if not target:
        raise ValueError("target is required")
    record_key = "|".join(
        [
            benchmark_run_id,
            agent,
            as_of_date,
            claim_type,
            str(target.get("target_id") or ""),
            str(index),
        ]
    )
    return {
        "schema_version": "rke_agent_claim_footprint_v1",
        "agent_claim_footprint_id": hashlib.sha256(record_key.encode("utf-8")).hexdigest()[:24],
        "benchmark_run_id": benchmark_run_id,
        "agent": agent,
        "layer": layer,
        "as_of_date": as_of_date,
        "claim_type": claim_type,
        "target": target,
        "direction": _clean_str(row.get("direction")) or "not_applicable",
        "horizon_bucket": _clean_str(row.get("horizon_bucket")) or "unknown",
        "confidence_bucket": _clean_str(row.get("confidence_bucket")) or "unknown",
        "rke_context_hash": _clean_str(row.get("rke_context_hash")),
        "retrieval_rank": _optional_int(row.get("retrieval_rank")),
        "rke_prior_usage_quality": _clean_str(row.get("rke_prior_usage_quality"))
        or "not_evaluated",
        "current_data_confirmed": row.get("current_data_confirmed") is True,
        "stale_prior_rejected": row.get("stale_prior_rejected") is True,
        "contradictory_prior_handled": row.get("contradictory_prior_handled") is True,
        "reason_codes": _safe_str_list(row.get("reason_codes")),
        "failure_mode_tags": _safe_str_list(row.get("failure_mode_tags")),
        "tool_refs": _safe_str_list(row.get("tool_refs")),
        "production_signal_allowed": False,
        "private_text_included": False,
        "source_prose_included": False,
        "use_policy": "shadow_agent_claim_footprint_only",
    }


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value.strip()


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _safe_target(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key].strip()
        for key in _TARGET_FIELDS
        if isinstance(value.get(key), str) and value[key].strip()
    }


def _safe_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _forbidden_paths(value: Any, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text in _FORBIDDEN_CAPTURE_FIELDS or key_text.endswith("_path"):
                paths.append(child_path)
            paths.extend(_forbidden_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_paths(child, f"{path}[{index}]"))
        return paths
    if isinstance(value, str) and _looks_private(value):
        return [path]
    return []


def _looks_private(value: str) -> bool:
    lowered = value.lower()
    return (
        ".pdf" in lowered
        or ".md" in lowered
        or ".mosaic/" in lowered
        or "source_span" in lowered
        or "registry/report_intelligence/markdown" in lowered
    )


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
