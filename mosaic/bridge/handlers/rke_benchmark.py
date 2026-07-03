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
_DELIVERY_EVIDENCE_REL_PATH = Path(
    ".mosaic/rke/all_agent_evolution/delivery_evidence.jsonl"
)
_PROMPT_MUTATION_CANDIDATES_REL_PATH = Path(
    "registry/report_intelligence/prompt_mutation_candidates.jsonl"
)
_DELIVERY_EVIDENCE_KEYS = (
    "all_agent_prompt_release_checks",
    "paired_output_count",
    "benchmark_evidence_refs",
    "manual_review",
    "profile_evidence",
    "downstream_outcome_metrics",
    "prompt_mutation_provenance",
    "candidates",
    "prompt_mutation_release_checks",
    "rollback_evidence",
    "paper_trading_plan",
    "promotion_evidence",
)
_DELIVERY_CONTEXT_KEYS = ("cohort", "prompt_source_status")
_DELIVERY_RECORD_KEYS = _DELIVERY_CONTEXT_KEYS + _DELIVERY_EVIDENCE_KEYS
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


@method("rke_benchmark.all_agent_prompt_provenance_readiness")
def all_agent_prompt_provenance_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Gate formal all-agent prompt pins before benchmark/replay."""
    cohort = params.get("cohort") or _DEFAULT_COHORT
    if not isinstance(cohort, str) or not cohort.strip():
        cohort = _DEFAULT_COHORT
    prompt_preflight = prompts_preflight(
        {"cohort": cohort, "agents": list(_ALL_AGENTS), "langs": ["zh", "en"]}
    )
    supplied = params.get("release_checks")
    if supplied is None:
        release_rows: list[Any] = []
    elif isinstance(supplied, list):
        release_rows = supplied
    else:
        raise RpcError(INVALID_PARAMS, "'release_checks' must be a list")

    release_by_prompt: dict[tuple[str, str], dict[str, Any]] = {}
    evidence_failures: list[str] = []
    for index, row in enumerate(release_rows, 1):
        if not isinstance(row, dict):
            evidence_failures.append(f"release_checks[{index}]: must be an object")
            continue
        if _forbidden_paths(row):
            evidence_failures.append(
                f"release_checks[{index}]: forbidden private/prose fields"
            )
            continue
        agent = _clean_str(row.get("agent"))
        lang = _clean_str(row.get("lang"))
        if agent and lang:
            release_by_prompt[(agent, lang)] = row

    rows: list[dict[str, Any]] = []
    for row in prompt_preflight["rows"]:
        agent = _clean_str(row.get("agent"))
        lang = _clean_str(row.get("lang"))
        release = release_by_prompt.get((agent, lang), {})
        blockers: list[str] = []
        if row.get("status") != "ready":
            blockers.append(_clean_str(row.get("blocked_reason")) or "prompt_not_ready")
        if row.get("fallback_used") is True:
            blockers.append("fallback_prompt_used")
        if not release:
            blockers.append("release_check_missing")
        if release.get("verify_release_passed") is not True:
            blockers.append("verify_release_not_passed")
        if release.get("leak_drift_passed") is not True:
            blockers.append("leak_drift_not_passed")
        if not isinstance(release.get("prompt_version_id"), int):
            blockers.append("prompt_version_id_missing")
        for key in ("prompt_sha256", "verify_release_ref", "leak_drift_check_ref"):
            if not _clean_str(release.get(key)):
                blockers.append(f"{key}_missing")
        if _clean_str(release.get("prompt_sha256")) and _clean_str(
            release.get("prompt_sha256")
        ) != _clean_str(row.get("prompt_sha256")):
            blockers.append("prompt_sha256_mismatch")
        rows.append(
            {
                "agent": agent,
                "layer": _clean_str(row.get("layer")),
                "lang": lang,
                "prompt_file_path": _clean_str(row.get("prompt_file_path")),
                "prompt_repo_id": _clean_str(row.get("prompt_repo_id")),
                "prompt_repo_revision": _clean_str(row.get("prompt_repo_revision")),
                "prompt_sha256": _clean_str(row.get("prompt_sha256")),
                "prompt_version_id": release.get("prompt_version_id")
                if isinstance(release.get("prompt_version_id"), int)
                else None,
                "verify_release_ref": _clean_str(release.get("verify_release_ref")),
                "leak_drift_check_ref": _clean_str(release.get("leak_drift_check_ref")),
                "fallback_used": row.get("fallback_used") is True,
                "ready": not blockers,
                "blockers": blockers,
            }
        )

    blocked_reasons = list(evidence_failures)
    if not prompt_preflight["ready"]:
        blocked_reasons.append("prompt_preflight_not_ready")
    for row in rows:
        blocked_reasons.extend(row["blockers"])

    return {
        "schema_version": "rke_all_agent_prompt_provenance_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "cohort": cohort,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "agent_count": len(_ALL_AGENTS),
        "prompt_row_count": len(rows),
        "ready_prompt_row_count": sum(1 for row in rows if row["ready"]),
        "release_check_count": len(release_by_prompt),
        "prompt_source_status": prompt_preflight.get("source_status", {}),
        "prompt_rows": rows,
        "all_agent_prompt_provenance_ready": bool(rows) and not blocked_reasons,
        "fallback_used": any(row["fallback_used"] for row in rows),
        "production_prompt_change_allowed": False,
    }


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
            "source_status": prompt_preflight.get("source_status", {}),
            "fallback_used": False,
        },
        "manual_review": {
            "status": "not_run",
            "required": True,
            "reviewer_timestamp": None,
        },
        "promotion_allowed": False,
    }


@method("rke_benchmark.fixed_episode_benchmark_evidence")
def fixed_episode_benchmark_evidence(params: dict[str, Any]) -> dict[str, Any]:
    """Check no-body evidence refs for the fixed-episode benchmark gate."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    manifest = fixed_episode_manifest({"cohort": params.get("cohort")})
    evidence_refs = params.get("evidence_refs")
    if not isinstance(evidence_refs, dict):
        evidence_refs = {}
    manual_review = params.get("manual_review")
    if not isinstance(manual_review, dict):
        manual_review = {}
    paired_output_count = params.get("paired_output_count")
    if not isinstance(paired_output_count, int) or isinstance(paired_output_count, bool):
        paired_output_count = 0

    required_model_count = sum(1 for config in _MODEL_CONFIGS if config["required"])
    required_paired_output_count = (
        manifest["as_of_date_count"] * manifest["agent_count"] * required_model_count
    )
    blocked_reasons: list[str] = []
    if manifest["benchmark_status"] != "ready_to_run":
        blocked_reasons.append("private_prompt_preflight_not_ready")
    if paired_output_count < required_paired_output_count:
        blocked_reasons.append("paired_output_count_below_required")
    for key in (
        "paired_output_manifest_ref",
        "output_schema_validation_report_ref",
        "deterministic_score_table_ref",
        "investment_outcome_table_ref",
    ):
        if not _clean_str(evidence_refs.get(key)):
            blocked_reasons.append(f"{key}_missing")
    if _clean_str(manual_review.get("decision")) != "approved":
        blocked_reasons.append("manual_review_not_approved")
    if not _clean_str(manual_review.get("reviewer_timestamp")):
        blocked_reasons.append("manual_review_timestamp_missing")
    if _forbidden_paths(evidence_refs) or _forbidden_paths(manual_review):
        blocked_reasons.append("private_or_source_prose_ref_detected")

    return {
        "schema_version": "rke_fixed_episode_benchmark_evidence_v1",
        "evidence_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "episode_count": manifest["episode_count"],
        "as_of_date_count": manifest["as_of_date_count"],
        "agent_count": manifest["agent_count"],
        "required_model_config_count": required_model_count,
        "required_paired_output_count": required_paired_output_count,
        "paired_output_count": paired_output_count,
        "prompt_source_status": manifest["prompt_preflight"].get("source_status", {}),
        "evidence_refs": {
            "paired_output_manifest_ref": _clean_str(
                evidence_refs.get("paired_output_manifest_ref")
            ),
            "output_schema_validation_report_ref": _clean_str(
                evidence_refs.get("output_schema_validation_report_ref")
            ),
            "deterministic_score_table_ref": _clean_str(
                evidence_refs.get("deterministic_score_table_ref")
            ),
            "investment_outcome_table_ref": _clean_str(
                evidence_refs.get("investment_outcome_table_ref")
            ),
        },
        "manual_review": {
            "decision": _clean_str(manual_review.get("decision")),
            "reviewer_timestamp": _clean_str(manual_review.get("reviewer_timestamp")),
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
    runtime_context_summary = _runtime_context_summary(sanitized)
    report_claim_ref_count = _report_claim_ref_count(sanitized)
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
            "report_claim_ref_count": report_claim_ref_count,
            **runtime_context_summary,
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
        "report_claim_ref_count": _report_claim_ref_count(rows),
        **_runtime_context_summary(rows),
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
        "report_claim_ref_count": 0,
        **_runtime_context_summary([]),
        "privacy_scan": {
            "private_text_included": False,
            "source_prose_included": False,
            "forbidden_field_violation_count": 0,
        },
        "failures": [],
    }


def _runtime_context_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranking_policy_id_counts: dict[str, int] = {}
    priority_bucket_counts: dict[str, int] = {}
    retrieval_rank_count = 0
    truncation_audit_count = 0
    for row in rows:
        ranking_policy_id = _clean_str(row.get("ranking_policy_id"))
        if ranking_policy_id:
            _increment(ranking_policy_id_counts, ranking_policy_id)
        priority_bucket = _clean_str(row.get("priority_bucket"))
        if priority_bucket:
            _increment(priority_bucket_counts, priority_bucket)
        if isinstance(row.get("retrieval_rank"), int) and not isinstance(
            row.get("retrieval_rank"), bool
        ):
            retrieval_rank_count += 1
        if isinstance(row.get("truncated_item_count"), int) and not isinstance(
            row.get("truncated_item_count"), bool
        ):
            truncation_audit_count += 1
    return {
        "ranking_policy_id_counts": dict(sorted(ranking_policy_id_counts.items())),
        "retrieval_rank_count": retrieval_rank_count,
        "priority_bucket_counts": dict(sorted(priority_bucket_counts.items())),
        "truncation_audit_count": truncation_audit_count,
    }


def _report_claim_ref_count(rows: list[dict[str, Any]]) -> int:
    return sum(len(_safe_str_list(row.get("report_claim_refs"))) for row in rows)


@method("rke_benchmark.agent_profile_evolution_readiness")
def agent_profile_evolution_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Gate redacted agent footprints before profile/evolution consumption."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    summary = agent_footprint_summary({"benchmark_run_id": benchmark_run_id})
    evidence = params.get("profile_evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    required_layers = sorted(_AGENTS_BY_LAYER)
    observed_layers = sorted(
        layer
        for layer, count in summary["layer_counts"].items()
        if isinstance(count, int) and count > 0
    )
    missing_layers = sorted(set(required_layers) - set(observed_layers))
    blocked_reasons: list[str] = []
    if summary["summary_status"] != "ready" or summary["row_count"] == 0:
        blocked_reasons.append("agent_footprint_summary_missing")
    if summary["privacy_scan"]["forbidden_field_violation_count"]:
        blocked_reasons.append("agent_footprint_privacy_scan_failed")
    if missing_layers:
        blocked_reasons.append("layer_coverage_incomplete")
    if not summary["rke_context_hash_count"]:
        blocked_reasons.append("rke_context_hash_missing")
    if not summary["report_claim_ref_count"]:
        blocked_reasons.append("report_claim_link_missing")
    for key in (
        "profile_update_ref",
        "evolution_input_ref",
        "no_source_prose_audit_ref",
    ):
        if not _clean_str(evidence.get(key)):
            blocked_reasons.append(f"{key}_missing")
    if _forbidden_paths(evidence):
        blocked_reasons.append("private_or_source_prose_ref_detected")

    return {
        "schema_version": "rke_agent_profile_evolution_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "blocked_reasons": blocked_reasons,
        "summary_status": summary["summary_status"],
        "row_count": summary["row_count"],
        "required_layers": required_layers,
        "observed_layers": observed_layers,
        "missing_layers": missing_layers,
        "layer_counts": summary["layer_counts"],
        "claim_type_counts": summary["claim_type_counts"],
        "rke_context_hash_count": summary["rke_context_hash_count"],
        "report_claim_ref_count": summary["report_claim_ref_count"],
        "privacy_scan": summary["privacy_scan"],
        "profile_evidence": {
            "profile_update_ref": _clean_str(evidence.get("profile_update_ref")),
            "evolution_input_ref": _clean_str(evidence.get("evolution_input_ref")),
            "no_source_prose_audit_ref": _clean_str(
                evidence.get("no_source_prose_audit_ref")
            ),
        },
        "profile_evolution_ready": not blocked_reasons,
        "production_signal_allowed": False,
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
                "ranking_policy_id_counts": summary["ranking_policy_id_counts"],
                "retrieval_rank_count": summary["retrieval_rank_count"],
                "priority_bucket_counts": summary["priority_bucket_counts"],
                "truncation_audit_count": summary["truncation_audit_count"],
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


@method("rke_benchmark.prompt_mutation_lifecycle_manifest")
def prompt_mutation_lifecycle_manifest(params: dict[str, Any]) -> dict[str, Any]:
    """Plan private prompt mutation lifecycle records without applying prompts."""
    candidate_manifest = candidate_consumption_manifest(
        {"candidates": params.get("candidates")}
        if "candidates" in params
        else {}
    )
    affected_agents = sorted(
        {
            agent
            for item in candidate_manifest["candidate_summaries"]
            for agent in _affected_agents_from_candidate(item)
        }
    )
    prompt_preflight = (
        prompts_preflight({"agents": affected_agents, "langs": ["zh", "en"]})
        if affected_agents
        else {"ready": False, "rows": [], "blocked_count": 0}
    )
    prompt_rows_by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in prompt_preflight.get("rows", []):
        if isinstance(row, dict):
            prompt_rows_by_agent.setdefault(_clean_str(row.get("agent")), []).append(row)

    records: list[dict[str, Any]] = []
    for item in candidate_manifest["candidate_summaries"]:
        candidate_agents = _affected_agents_from_candidate(item)
        is_refusal = "refusal" in item["candidate_type"]
        prompt_pins = [
            {
                "agent": _clean_str(row.get("agent")),
                "lang": _clean_str(row.get("lang")),
                "prompt_repo_id": _clean_str(row.get("prompt_repo_id")),
                "prompt_repo_revision": _clean_str(row.get("prompt_repo_revision")),
                "prompt_file_path": _clean_str(row.get("prompt_file_path")),
                "prompt_sha256": _clean_str(row.get("prompt_sha256")),
                "fallback_used": row.get("fallback_used") is True,
            }
            for agent in candidate_agents
            for row in prompt_rows_by_agent.get(agent, [])
            if row.get("status") == "ready"
        ]
        if is_refusal:
            records.append(
                {
                    "mutation_candidate_id": item["mutation_candidate_id"],
                    "candidate_type": item["candidate_type"],
                    "target_component": item["target_component"],
                    "affected_agents": candidate_agents,
                    "candidate_action": "record_refusal_no_prompt_branch",
                    "private_prompt_branch": "",
                    "overwrite_target_paths": [],
                    "prompt_pins": [],
                    "lifecycle_stages": [
                        "refusal_recorded",
                        "benchmark_replay_visibility",
                        "no_prompt_write",
                    ],
                    "rke_prior_usage_hypothesis": "preserve_refusal_reason_visibility",
                    "expected_improvement_metric": "refusal_quality",
                    "fallback_rollback_rule": "not_applicable_refusal_no_prompt_change",
                    "benchmark_evidence_required": True,
                    "manual_review_required": True,
                    "promotion_allowed": False,
                    "blocked_by": item["blocked_by"],
                }
            )
            continue
        records.append(
            {
                "mutation_candidate_id": item["mutation_candidate_id"],
                "candidate_type": item["candidate_type"],
                "target_component": item["target_component"],
                "affected_agents": candidate_agents,
                "candidate_action": "private_prompt_branch_after_blockers_clear",
                "private_prompt_branch": (
                    "rke/"
                    + _slug(item["mutation_candidate_id"])
                    + "/"
                    + _slug(item["target_component"])
                ),
                "overwrite_target_paths": [
                    pin["prompt_file_path"] for pin in prompt_pins if pin["prompt_file_path"]
                ],
                "prompt_pins": prompt_pins,
                "lifecycle_stages": [
                    "candidate",
                    "private_prompt_branch",
                    "overwrite_current_private_prompt_file",
                    "leak_drift_check",
                    "fixed_episode_benchmark",
                    "manual_review",
                    "shadow_replay",
                    "paper_trading",
                    "promotion_gate",
                    "rollback_monitor",
                ],
                "rke_prior_usage_hypothesis": (
                    "improve_rke_prior_usage_or_refusal_quality_without_current_data_bypass"
                ),
                "expected_improvement_metric": (
                    "rke_prior_usage_quality_and_refusal_quality"
                ),
                "fallback_rollback_rule": (
                    "rollback by restoring previous private prompt git revision "
                    "and prompt_sha256; public repo prompt writes remain forbidden"
                ),
                "benchmark_evidence_required": True,
                "manual_review_required": True,
                "promotion_allowed": False,
                "blocked_by": item["blocked_by"],
            }
        )

    blocked_reasons: list[str] = []
    if candidate_manifest["manifest_status"] != "ready_for_private_prompt_lifecycle":
        blocked_reasons.append("candidate_consumption_manifest_not_ready")
    if not affected_agents:
        blocked_reasons.append("affected_agent_resolution_missing")
    if not prompt_preflight.get("ready"):
        blocked_reasons.append("private_prompt_preflight_not_ready")
    if any(pin.get("fallback_used") for record in records for pin in record["prompt_pins"]):
        blocked_reasons.append("fallback_prompt_used")
    if records and all(
        record["candidate_action"] == "record_refusal_no_prompt_branch"
        for record in records
    ):
        blocked_reasons.append("refusal_only_no_prompt_branch_candidate")

    return {
        "schema_version": "rke_prompt_mutation_lifecycle_manifest_v1",
        "manifest_status": "blocked_preflight" if blocked_reasons else "ready_for_private_branch",
        "blocked_reasons": blocked_reasons,
        "candidate_count": candidate_manifest["candidate_count"],
        "affected_agents": affected_agents,
        "prompt_preflight": {
            "ready": bool(prompt_preflight.get("ready")),
            "row_count": len(prompt_preflight.get("rows", [])),
            "blocked_count": int(prompt_preflight.get("blocked_count") or 0),
        },
        "lifecycle_records": records,
        "private_prompt_repo_required": True,
        "direct_prompt_write_allowed": False,
        "promotion_allowed": False,
        "rollback_required_before_promotion": True,
    }


@method("rke_benchmark.prompt_mutation_release_readiness")
def prompt_mutation_release_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Gate prompt mutation release checks before replay/benchmark use."""
    lifecycle = prompt_mutation_lifecycle_manifest(
        {"candidates": params.get("candidates")}
        if "candidates" in params
        else {}
    )
    supplied = params.get("release_checks")
    if supplied is None:
        release_rows: list[Any] = []
    elif isinstance(supplied, list):
        release_rows = supplied
    else:
        raise RpcError(INVALID_PARAMS, "'release_checks' must be a list")

    release_by_candidate: dict[str, dict[str, Any]] = {}
    evidence_failures: list[str] = []
    for index, row in enumerate(release_rows, 1):
        if not isinstance(row, dict):
            evidence_failures.append(f"release_checks[{index}]: must be an object")
            continue
        if _forbidden_paths(row):
            evidence_failures.append(
                f"release_checks[{index}]: forbidden private/prose fields"
            )
            continue
        candidate_id = _clean_str(row.get("mutation_candidate_id"))
        if candidate_id:
            release_by_candidate[candidate_id] = row

    branch_records = [
        record
        for record in lifecycle["lifecycle_records"]
        if record["candidate_action"] == "private_prompt_branch_after_blockers_clear"
    ]
    records: list[dict[str, Any]] = []
    for record in branch_records:
        candidate_id = record["mutation_candidate_id"]
        evidence = release_by_candidate.get(candidate_id, {})
        blockers: list[str] = []
        blockers.extend(
            f"candidate_blocked_by:{reason}" for reason in record["blocked_by"]
        )
        if not isinstance(evidence.get("prompt_version_id"), int):
            blockers.append("prompt_version_id_missing")
        for key in (
            "prompt_repo_id",
            "prompt_commit_hash",
            "prompt_sha256",
            "verify_release_ref",
            "leak_drift_check_ref",
        ):
            if not _clean_str(evidence.get(key)):
                blockers.append(f"{key}_missing")
        if evidence.get("verify_release_passed") is not True:
            blockers.append("verify_release_not_passed")
        if evidence.get("leak_drift_passed") is not True:
            blockers.append("leak_drift_not_passed")
        if evidence.get("release_ready") is not True:
            blockers.append("release_not_ready")
        if not evidence:
            blockers.append("release_check_missing")
        records.append(
            {
                "mutation_candidate_id": candidate_id,
                "private_prompt_branch": record["private_prompt_branch"],
                "affected_agents": record["affected_agents"],
                "prompt_version_id": evidence.get("prompt_version_id")
                if isinstance(evidence.get("prompt_version_id"), int)
                else None,
                "prompt_repo_id": _clean_str(evidence.get("prompt_repo_id")),
                "prompt_commit_hash": _clean_str(evidence.get("prompt_commit_hash")),
                "prompt_sha256": _clean_str(evidence.get("prompt_sha256")),
                "verify_release_ref": _clean_str(evidence.get("verify_release_ref")),
                "leak_drift_check_ref": _clean_str(evidence.get("leak_drift_check_ref")),
                "release_ready": not blockers,
                "blockers": blockers,
            }
        )

    blocked_reasons = list(lifecycle["blocked_reasons"]) + evidence_failures
    if lifecycle["manifest_status"] != "ready_for_private_branch":
        blocked_reasons.append("lifecycle_manifest_not_ready")
    if not branch_records:
        blocked_reasons.append("prompt_branch_candidate_missing")
    for record in records:
        blocked_reasons.extend(record["blockers"])

    return {
        "schema_version": "rke_prompt_mutation_release_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "blocked_reasons": sorted(set(blocked_reasons)),
        "lifecycle_manifest_status": lifecycle["manifest_status"],
        "branch_candidate_count": len(branch_records),
        "release_record_count": len(records),
        "release_records": records,
        "required_evidence": [
            "prompt_version_id",
            "prompt_repo_id",
            "prompt_commit_hash",
            "prompt_sha256",
            "verify_release_ref",
            "leak_drift_check_ref",
        ],
        "prompt_release_ready": bool(records) and not blocked_reasons,
        "direct_prompt_write_allowed": False,
        "promotion_allowed": False,
    }


@method("rke_benchmark.prompt_mutation_rollback_readiness")
def prompt_mutation_rollback_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Check rollback proof objects for prompt mutations before shadow exit."""
    lifecycle = prompt_mutation_lifecycle_manifest(
        {"candidates": params.get("candidates")}
        if "candidates" in params
        else {}
    )
    supplied = params.get("rollback_evidence")
    if supplied is None:
        evidence_rows: list[Any] = []
    elif isinstance(supplied, list):
        evidence_rows = supplied
    else:
        raise RpcError(INVALID_PARAMS, "'rollback_evidence' must be a list")

    evidence_by_candidate: dict[str, dict[str, Any]] = {}
    evidence_failures: list[str] = []
    for index, row in enumerate(evidence_rows, 1):
        if not isinstance(row, dict):
            evidence_failures.append(f"rollback_evidence[{index}]: must be an object")
            continue
        forbidden_paths = _forbidden_paths(row)
        if forbidden_paths:
            evidence_failures.append(
                f"rollback_evidence[{index}]: forbidden private/prose fields "
                + ", ".join(forbidden_paths[:5])
            )
            continue
        candidate_id = _clean_str(row.get("mutation_candidate_id"))
        if candidate_id:
            evidence_by_candidate[candidate_id] = row

    records: list[dict[str, Any]] = []
    branch_records = [
        record
        for record in lifecycle["lifecycle_records"]
        if record["candidate_action"] == "private_prompt_branch_after_blockers_clear"
    ]
    for record in branch_records:
        candidate_id = record["mutation_candidate_id"]
        evidence = evidence_by_candidate.get(candidate_id, {})
        previous_hashes = sorted(
            {
                _clean_str(pin.get("prompt_sha256"))
                for pin in record["prompt_pins"]
                if _clean_str(pin.get("prompt_sha256"))
            }
        )
        blockers: list[str] = []
        blockers.extend(
            f"candidate_blocked_by:{reason}" for reason in record["blocked_by"]
        )
        if not previous_hashes:
            blockers.append("previous_prompt_hash_missing")
        for key in (
            "rollback_trigger_definition",
            "rollback_command_or_procedure",
            "monitor_output_ref",
            "post_rollback_verification_ref",
        ):
            if not _clean_str(evidence.get(key)):
                blockers.append(f"{key}_missing")
        records.append(
            {
                "mutation_candidate_id": candidate_id,
                "private_prompt_branch": record["private_prompt_branch"],
                "affected_agents": record["affected_agents"],
                "previous_prompt_hashes": previous_hashes,
                "rollback_trigger_definition": _clean_str(
                    evidence.get("rollback_trigger_definition")
                ),
                "rollback_command_or_procedure": _clean_str(
                    evidence.get("rollback_command_or_procedure")
                ),
                "monitor_output_ref": _clean_str(evidence.get("monitor_output_ref")),
                "post_rollback_verification_ref": _clean_str(
                    evidence.get("post_rollback_verification_ref")
                ),
                "rollback_ready": not blockers,
                "blockers": blockers,
            }
        )

    blocked_reasons = list(lifecycle["blocked_reasons"]) + evidence_failures
    if not branch_records:
        blocked_reasons.append("prompt_branch_candidate_missing")
    for record in records:
        blocked_reasons.extend(record["blockers"])

    return {
        "schema_version": "rke_prompt_mutation_rollback_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "blocked_reasons": sorted(set(blocked_reasons)),
        "lifecycle_manifest_status": lifecycle["manifest_status"],
        "branch_candidate_count": len(branch_records),
        "rollback_record_count": len(records),
        "rollback_records": records,
        "required_evidence": [
            "rollback_trigger_definition",
            "previous_prompt_hash",
            "rollback_command_or_procedure",
            "monitor_output_ref",
            "post_rollback_verification_ref",
        ],
        "rollback_gate_ready": bool(records) and not blocked_reasons,
        "promotion_allowed": False,
    }


@method("rke_benchmark.shadow_replay_readiness")
def shadow_replay_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Gate shadow replay on benchmark, footprint, Darwinian, and rollback proof."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    prompt_provenance = all_agent_prompt_provenance_readiness(
        {
            "cohort": params.get("cohort"),
            "release_checks": params.get("all_agent_prompt_release_checks"),
        }
    )
    benchmark = fixed_episode_benchmark_evidence(
        {
            "benchmark_run_id": benchmark_run_id,
            "cohort": params.get("cohort"),
            "paired_output_count": params.get("paired_output_count"),
            "evidence_refs": params.get("benchmark_evidence_refs"),
            "manual_review": params.get("manual_review"),
        }
    )
    darwinian = darwinian_autoresearch_input_manifest(
        {
            "benchmark_run_id": benchmark_run_id,
            "downstream_outcome_metrics": params.get("downstream_outcome_metrics"),
            "prompt_mutation_provenance": params.get("prompt_mutation_provenance"),
        }
    )
    prompt_release = prompt_mutation_release_readiness(
        {
            "candidates": params.get("candidates"),
            "release_checks": params.get("prompt_mutation_release_checks"),
        }
    )
    rollback = prompt_mutation_rollback_readiness(
        {
            "candidates": params.get("candidates"),
            "rollback_evidence": params.get("rollback_evidence"),
        }
    )
    current_data = darwinian["skill_inputs"]["current_data_skill"]
    prior_usage = darwinian["skill_inputs"]["research_prior_usage_skill"]

    blocked_reasons: list[str] = []
    if prompt_provenance["readiness_status"] != "ready":
        blocked_reasons.append("all_agent_prompt_provenance_not_ready")
    if benchmark["evidence_status"] != "ready":
        blocked_reasons.append("benchmark_evidence_not_ready")
    if darwinian["manifest_status"] != "ready":
        blocked_reasons.append("darwinian_autoresearch_input_not_ready")
    if prompt_release["readiness_status"] != "ready":
        blocked_reasons.append("prompt_mutation_release_not_ready")
    if rollback["readiness_status"] != "ready":
        blocked_reasons.append("rollback_readiness_not_ready")
    context_hash_count = int(prior_usage["rke_context_hash_count"] or 0)
    ranking_policy_count = sum(prior_usage["ranking_policy_id_counts"].values())
    priority_bucket_count = sum(prior_usage["priority_bucket_counts"].values())
    if not context_hash_count:
        blocked_reasons.append("runtime_context_hash_missing")
    if ranking_policy_count < context_hash_count:
        blocked_reasons.append("ranking_policy_id_missing")
    if prior_usage["retrieval_rank_count"] < context_hash_count:
        blocked_reasons.append("retrieval_rank_missing")
    if priority_bucket_count < context_hash_count:
        blocked_reasons.append("priority_bucket_missing")
    if prior_usage["truncation_audit_count"] < context_hash_count:
        blocked_reasons.append("truncation_audit_missing")
    if not current_data["current_data_confirmed_count"]:
        blocked_reasons.append("current_data_confirmation_missing")

    return {
        "schema_version": "rke_shadow_replay_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "blocked_reasons": blocked_reasons,
        "prompt_provenance_readiness_status": prompt_provenance["readiness_status"],
        "benchmark_evidence_status": benchmark["evidence_status"],
        "darwinian_manifest_status": darwinian["manifest_status"],
        "prompt_release_readiness_status": prompt_release["readiness_status"],
        "rollback_readiness_status": rollback["readiness_status"],
        "rke_context_hash_count": prior_usage["rke_context_hash_count"],
        "ranking_policy_id_counts": prior_usage["ranking_policy_id_counts"],
        "retrieval_rank_count": prior_usage["retrieval_rank_count"],
        "priority_bucket_counts": prior_usage["priority_bucket_counts"],
        "truncation_audit_count": prior_usage["truncation_audit_count"],
        "current_data_confirmed_count": current_data["current_data_confirmed_count"],
        "shadow_replay_ready": not blocked_reasons,
        "paper_trading_allowed": False,
        "promotion_allowed": False,
    }


@method("rke_benchmark.paper_trading_readiness")
def paper_trading_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Gate paper-trading entry on shadow replay and operator-reviewed controls."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    shadow = shadow_replay_readiness(params)
    plan = params.get("paper_trading_plan")
    if not isinstance(plan, dict):
        plan = {}

    blocked_reasons: list[str] = []
    if shadow["readiness_status"] != "ready":
        blocked_reasons.append("shadow_replay_not_ready")
    for key in (
        "paper_trading_plan_ref",
        "risk_limit_ref",
        "stop_loss_or_rollback_ref",
        "operator_review_timestamp",
    ):
        if not _clean_str(plan.get(key)):
            blocked_reasons.append(f"{key}_missing")
    if _forbidden_paths(plan):
        blocked_reasons.append("private_or_source_prose_ref_detected")

    return {
        "schema_version": "rke_paper_trading_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "blocked_reasons": blocked_reasons,
        "shadow_replay_status": shadow["readiness_status"],
        "paper_trading_plan": {
            "paper_trading_plan_ref": _clean_str(plan.get("paper_trading_plan_ref")),
            "risk_limit_ref": _clean_str(plan.get("risk_limit_ref")),
            "stop_loss_or_rollback_ref": _clean_str(
                plan.get("stop_loss_or_rollback_ref")
            ),
            "operator_review_timestamp": _clean_str(
                plan.get("operator_review_timestamp")
            ),
        },
        "paper_trading_allowed": not blocked_reasons,
        "promotion_allowed": False,
    }


@method("rke_benchmark.promotion_decision_readiness")
def promotion_decision_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Gate operator promotion decision after paper-trading evidence."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    paper = paper_trading_readiness(params)
    evidence = params.get("promotion_evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    blocked_reasons: list[str] = []
    if paper["readiness_status"] != "ready":
        blocked_reasons.append("paper_trading_not_ready")
    for key in (
        "paper_trading_result_ref",
        "monitor_summary_ref",
        "second_review_timestamp",
        "lockbox_decision_ref",
    ):
        if not _clean_str(evidence.get(key)):
            blocked_reasons.append(f"{key}_missing")
    if _clean_str(evidence.get("decision")) != "approved_for_promotion_review":
        blocked_reasons.append("promotion_review_decision_not_approved")
    if _forbidden_paths(evidence):
        blocked_reasons.append("private_or_source_prose_ref_detected")

    return {
        "schema_version": "rke_promotion_decision_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "blocked_reasons": blocked_reasons,
        "paper_trading_status": paper["readiness_status"],
        "promotion_evidence": {
            "paper_trading_result_ref": _clean_str(
                evidence.get("paper_trading_result_ref")
            ),
            "monitor_summary_ref": _clean_str(evidence.get("monitor_summary_ref")),
            "second_review_timestamp": _clean_str(
                evidence.get("second_review_timestamp")
            ),
            "lockbox_decision_ref": _clean_str(evidence.get("lockbox_decision_ref")),
            "decision": _clean_str(evidence.get("decision")),
        },
        "ready_for_operator_promotion_decision": not blocked_reasons,
        "production_allowed": False,
        "promotion_allowed": False,
    }


@method("rke_benchmark.record_delivery_evidence")
def record_delivery_evidence(params: dict[str, Any]) -> dict[str, Any]:
    """Persist no-body delivery evidence refs in the private local store."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    evidence = {key: params[key] for key in _DELIVERY_RECORD_KEYS if key in params}
    if not evidence:
        raise RpcError(
            INVALID_PARAMS, "delivery evidence or context fields are required"
        )
    forbidden_paths = _forbidden_paths(evidence)
    if forbidden_paths:
        return {
            "record_status": "blocked",
            "benchmark_run_id": benchmark_run_id,
            "private_rows_path": _DELIVERY_EVIDENCE_REL_PATH.as_posix(),
            "failures": [
                "forbidden private/prose fields " + ", ".join(forbidden_paths[:5])
            ],
            "recorded_key_count": 0,
            "recorded_context_key_count": 0,
        }
    recorded_key_count = sum(1 for key in _DELIVERY_EVIDENCE_KEYS if key in evidence)
    recorded_context_key_count = sum(
        1 for key in _DELIVERY_CONTEXT_KEYS if key in evidence
    )

    record = {
        "schema_version": "rke_delivery_evidence_v1",
        "benchmark_run_id": benchmark_run_id,
        "evidence": evidence,
    }
    path = _repo_root() / _DELIVERY_EVIDENCE_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "record_status": "recorded",
        "benchmark_run_id": benchmark_run_id,
        "private_rows_path": _DELIVERY_EVIDENCE_REL_PATH.as_posix(),
        "recorded_key_count": recorded_key_count,
        "recorded_context_key_count": recorded_context_key_count,
        "failures": [],
    }


@method("rke_benchmark.delivery_evidence_audit")
def delivery_evidence_audit(params: dict[str, Any]) -> dict[str, Any]:
    """Audit which delivery evidence refs are recorded without returning bodies."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    evidence, failures = _read_delivery_evidence(benchmark_run_id)
    readiness = delivery_readiness({"benchmark_run_id": benchmark_run_id})
    recorded_context_keys = sorted(
        key for key in _DELIVERY_CONTEXT_KEYS if key in evidence
    )
    recorded_keys = sorted(key for key in _DELIVERY_EVIDENCE_KEYS if key in evidence)
    missing_keys = [key for key in _DELIVERY_EVIDENCE_KEYS if key not in evidence]
    if failures:
        evidence_status = "blocked"
    elif not recorded_keys:
        evidence_status = "missing"
    elif missing_keys:
        evidence_status = "partial"
    else:
        evidence_status = "complete"

    return {
        "schema_version": "rke_delivery_evidence_audit_v1",
        "evidence_status": evidence_status,
        "benchmark_run_id": benchmark_run_id,
        "cohort": readiness["cohort"],
        "private_rows_path": _DELIVERY_EVIDENCE_REL_PATH.as_posix(),
        "recorded_key_count": len(recorded_keys),
        "recorded_context_keys": recorded_context_keys,
        "recorded_keys": recorded_keys,
        "recorded_prompt_source_status": evidence.get("prompt_source_status")
        if isinstance(evidence.get("prompt_source_status"), dict)
        else {},
        "missing_keys": missing_keys,
        "failures": failures,
        "delivery_readiness_can_load": bool(recorded_keys),
        "delivery_readiness_status": readiness["readiness_status"],
        "condition_count": readiness["condition_count"],
        "ready_condition_count": readiness["ready_condition_count"],
        "delivery_conditions": readiness["conditions"],
        "delivery_blocked_reasons": readiness["blocked_reasons"],
    }


@method("rke_benchmark.delivery_readiness")
def delivery_readiness(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate E7 delivery readiness without running or promoting anything."""
    benchmark_run_id = _require_str(params, "benchmark_run_id")
    recorded_evidence, evidence_failures = _read_delivery_evidence(benchmark_run_id)
    effective_params = dict(recorded_evidence)
    for key in _DELIVERY_RECORD_KEYS:
        if key in params:
            effective_params[key] = params[key]
    cohort = effective_params.get("cohort")
    if not isinstance(cohort, str) or not cohort.strip():
        cohort = _DEFAULT_COHORT
    else:
        cohort = cohort.strip()
    effective_params["cohort"] = cohort
    prompt_provenance = all_agent_prompt_provenance_readiness(
        {
            "cohort": cohort,
            "release_checks": effective_params.get("all_agent_prompt_release_checks"),
        }
    )
    benchmark = fixed_episode_benchmark_evidence(
        {
            "benchmark_run_id": benchmark_run_id,
            "cohort": cohort,
            "paired_output_count": effective_params.get("paired_output_count"),
            "evidence_refs": effective_params.get("benchmark_evidence_refs"),
            "manual_review": effective_params.get("manual_review"),
        }
    )
    profile = agent_profile_evolution_readiness(
        {
            "benchmark_run_id": benchmark_run_id,
            "profile_evidence": effective_params.get("profile_evidence"),
        }
    )
    darwinian = darwinian_autoresearch_input_manifest(
        {
            "benchmark_run_id": benchmark_run_id,
            "downstream_outcome_metrics": effective_params.get(
                "downstream_outcome_metrics"
            ),
            "prompt_mutation_provenance": effective_params.get(
                "prompt_mutation_provenance"
            ),
        }
    )
    prompt_release = prompt_mutation_release_readiness(
        {
            "candidates": effective_params.get("candidates"),
            "release_checks": effective_params.get("prompt_mutation_release_checks"),
        }
    )
    rollback = prompt_mutation_rollback_readiness(
        {
            "candidates": effective_params.get("candidates"),
            "rollback_evidence": effective_params.get("rollback_evidence"),
        }
    )
    replay_params = {"benchmark_run_id": benchmark_run_id, **effective_params}
    shadow = shadow_replay_readiness(replay_params)
    paper = paper_trading_readiness(replay_params)
    promotion = promotion_decision_readiness(replay_params)

    conditions = [
        _delivery_condition(
            "all_agent_prompt_provenance",
            prompt_provenance["readiness_status"],
            prompt_provenance["blocked_reasons"],
            {"prompt_source_status": prompt_provenance["prompt_source_status"]},
        ),
        _delivery_condition(
            "runtime_ranked_context_consumption",
            shadow["readiness_status"],
            [
                reason
                for reason in shadow["blocked_reasons"]
                if reason
                in {
                    "runtime_context_hash_missing",
                    "ranking_policy_id_missing",
                    "retrieval_rank_missing",
                    "priority_bucket_missing",
                    "truncation_audit_missing",
                    "current_data_confirmation_missing",
                }
            ],
        ),
        _delivery_condition(
            "fixed_episode_benchmark",
            benchmark["evidence_status"],
            benchmark["blocked_reasons"],
            {"prompt_source_status": benchmark["prompt_source_status"]},
        ),
        _delivery_condition(
            "agent_profile_evolution",
            profile["readiness_status"],
            profile["blocked_reasons"],
        ),
        _delivery_condition(
            "darwinian_autoresearch_inputs",
            darwinian["manifest_status"],
            darwinian["blocked_reasons"],
        ),
        _delivery_condition(
            "prompt_mutation_release",
            prompt_release["readiness_status"],
            prompt_release["blocked_reasons"],
        ),
        _delivery_condition(
            "rollback_evidence",
            rollback["readiness_status"],
            rollback["blocked_reasons"],
        ),
        _delivery_condition(
            "shadow_replay",
            shadow["readiness_status"],
            shadow["blocked_reasons"],
        ),
        _delivery_condition(
            "paper_trading_entry",
            paper["readiness_status"],
            paper["blocked_reasons"],
        ),
        _delivery_condition(
            "promotion_decision",
            promotion["readiness_status"],
            promotion["blocked_reasons"],
        ),
    ]
    blocked_reasons = sorted(
        {
            f"{condition['condition_id']}:{reason}"
            for condition in conditions
            for reason in condition["blocked_reasons"]
        }
    )
    blocked_reasons.extend(
        f"delivery_evidence_store:{failure}" for failure in evidence_failures
    )
    return {
        "schema_version": "rke_all_agent_delivery_readiness_v1",
        "readiness_status": "blocked_preflight" if blocked_reasons else "ready",
        "benchmark_run_id": benchmark_run_id,
        "cohort": cohort,
        "condition_count": len(conditions),
        "ready_condition_count": sum(
            1 for condition in conditions if condition["ready"]
        ),
        "blocked_reasons": blocked_reasons,
        "conditions": conditions,
        "recorded_evidence_loaded": bool(recorded_evidence),
        "delivery_ready": not blocked_reasons,
        "production_allowed": False,
        "promotion_allowed": False,
    }


def _delivery_condition(
    condition_id: str,
    status: str,
    blocked_reasons: list[str],
    evidence_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons = list(blocked_reasons)
    if status != "ready" and not reasons:
        reasons.append(f"{condition_id}_not_ready")
    return {
        "condition_id": condition_id,
        "status": status,
        "ready": status == "ready" and not reasons,
        "blocked_reasons": reasons,
        "evidence_summary": evidence_summary or {},
    }


def _read_delivery_evidence(benchmark_run_id: str) -> tuple[dict[str, Any], list[str]]:
    path = _repo_root() / _DELIVERY_EVIDENCE_REL_PATH
    if not path.exists():
        return {}, []
    latest: dict[str, Any] = {}
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
            if row.get("benchmark_run_id") != benchmark_run_id:
                continue
            evidence = row.get("evidence")
            if not isinstance(evidence, dict):
                failures.append(f"line {line_number}: evidence must be object")
                continue
            forbidden_paths = _forbidden_paths(evidence)
            if forbidden_paths:
                failures.append(
                    f"line {line_number}: forbidden private/prose fields "
                    + ", ".join(forbidden_paths[:5])
                )
                continue
            latest.update(
                {
                    key: evidence[key]
                    for key in _DELIVERY_RECORD_KEYS
                    if key in evidence
                }
            )
    return latest, failures


def _affected_agents_from_candidate(item: dict[str, Any]) -> list[str]:
    component = _clean_str(item.get("target_component"))
    if "." in component:
        component = component.rsplit(".", 1)[1]
    if component in _LAYER_BY_AGENT:
        return [component]
    return []


def _slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    return "-".join(part for part in "".join(chars).split("-") if part) or "unknown"


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
        "ranking_policy_id": _clean_str(row.get("ranking_policy_id")),
        "retrieval_rank": _optional_int(row.get("retrieval_rank")),
        "priority_bucket": _clean_str(row.get("priority_bucket")),
        "truncated_item_count": _optional_non_negative_int(
            row.get("truncated_item_count")
        ),
        "rke_prior_usage_quality": _clean_str(row.get("rke_prior_usage_quality"))
        or "not_evaluated",
        "current_data_confirmed": row.get("current_data_confirmed") is True,
        "stale_prior_rejected": row.get("stale_prior_rejected") is True,
        "contradictory_prior_handled": row.get("contradictory_prior_handled") is True,
        "reason_codes": _safe_str_list(row.get("reason_codes")),
        "failure_mode_tags": _safe_str_list(row.get("failure_mode_tags")),
        "tool_refs": _safe_str_list(row.get("tool_refs")),
        "report_claim_refs": _safe_str_list(row.get("report_claim_refs")),
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


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


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
