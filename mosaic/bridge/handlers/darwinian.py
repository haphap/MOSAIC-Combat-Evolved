"""``darwinian.*`` JSON-RPC handlers.

Production v2 uses ``prepare_variant`` and ``publish_v2_updates``.  The old
``compute/get_weights`` surface remains read-only compatible for legacy replay;
it is never an implicit fallback for a production v2 runtime binding.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


def _store():
    # §14 R-T4: use the cached singleton.
    from mosaic.scorecard import get_store

    return get_store()


def _config():
    try:
        from mosaic.dataflows.config import get_config

        return get_config()
    except Exception:  # noqa: BLE001
        from mosaic.default_config import DEFAULT_CONFIG

        return DEFAULT_CONFIG


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


def _require_dict(params: dict, key: str) -> dict[str, Any]:
    value = params.get(key)
    if not isinstance(value, dict):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an object")
    return value


# ---------------------------------------------------------------------------
# darwinian.compute
# ---------------------------------------------------------------------------


@method("darwinian.prepare_variant")
def darwinian_prepare_variant(params: dict[str, Any]) -> dict[str, Any]:
    binding = params.get("binding")
    if not isinstance(binding, dict):
        raise RpcError(INVALID_PARAMS, "'binding' must be an object")
    as_of = _require_str(params, "as_of")
    try:
        return _store().prepare_darwinian_v2_production_variant(
            binding=binding,
            as_of=as_of,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.prepare_outcome_schedule")
def darwinian_prepare_outcome_schedule(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store().prepare_outcome_schedule_plan(
            production_variant_roster_revision_id=_require_str(
                params, "production_variant_roster_revision_id"
            ),
            graph_run_id=_require_str(params, "graph_run_id"),
            as_of=_require_str(params, "as_of"),
            prepared_at=_require_str(params, "prepared_at"),
            trading_calendar_snapshot=_require_dict(
                params, "trading_calendar_snapshot"
            ),
            verified_event_candidates=_require_dict(
                params, "verified_event_candidates"
            ),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.prepare_daily_cycle_outcomes")
def darwinian_prepare_daily_cycle_outcomes(params: dict[str, Any]) -> dict[str, Any]:
    """Freeze the real-run calendar, event denominator and scheduled opportunities."""
    revision_id = _require_str(params, "production_variant_roster_revision_id")
    graph_run_id = _require_str(params, "graph_run_id")
    as_of = _require_str(params, "as_of")
    prepared_at = _require_str(params, "prepared_at")
    try:
        from mosaic.dataflows.calendar import verified_trading_calendar_snapshot
        from mosaic.dataflows.outcome_runtime_inputs import (
            load_evaluation_opportunity_projection,
            load_verified_event_coverage,
        )

        as_of_date = date.fromisoformat(as_of[:10])
        calendar = verified_trading_calendar_snapshot(
            "2010-01-04",
            (as_of_date + timedelta(days=60)).isoformat(),
            as_of=as_of,
        )
        event_coverage = load_verified_event_coverage(as_of)
        store = _store()
        plan = store.prepare_outcome_schedule_plan(
            production_variant_roster_revision_id=revision_id,
            graph_run_id=graph_run_id,
            as_of=as_of,
            prepared_at=prepared_at,
            trading_calendar_snapshot=calendar,
            verified_event_candidates=event_coverage,
        )
        decisions: list[dict[str, Any]] = []
        stage_skips: dict[str, dict[str, Any]] = {}
        blockers: list[dict[str, str]] = []
        for slot in plan["slots"]:
            if slot["run_slot_kind"] != "OUTCOME_SCHEDULED":
                continue
            agent_id = str(slot["agent_id"])
            projection = load_evaluation_opportunity_projection(as_of, agent_id)
            if projection["projection_status"] == "AVAILABLE":
                decision = store.freeze_scheduled_outcome_opportunity(
                    outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
                    agent_id=agent_id,
                    qualification_predicate_version=projection[
                        "qualification_predicate_version"
                    ],
                    member_refs=projection["member_refs"],
                    source_evidence_by_required_source_id=projection[
                        "source_evidence_by_required_source_id"
                    ],
                    projection_snapshot_hash=projection["snapshot_hash"],
                )
                if not projection["member_refs"]:
                    decision = store.create_no_evaluation_object_stage_skip(
                        outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
                        agent_id=agent_id,
                        recorded_at=prepared_at,
                    )
                    stage_skips[agent_id] = decision["stage_skip"]
            else:
                decision = store.record_scheduled_outcome_opportunity_failure(
                    outcome_schedule_plan_id=plan["outcome_schedule_plan_id"],
                    agent_id=agent_id,
                    qualification_predicate_version=projection[
                        "qualification_predicate_version"
                    ],
                    source_evidence_by_required_source_id=projection[
                        "source_evidence_by_required_source_id"
                    ],
                    error_codes=projection["error_codes"],
                    attempted_at=prepared_at,
                )
                blockers.append(
                    {
                        "agent_id": agent_id,
                        "reason": "OPPORTUNITY_SET_UNAVAILABLE",
                    }
                )
            decisions.append({"agent_id": agent_id, **decision})
        return {
            "outcome_schedule_plan": plan,
            "scheduled_opportunity_decisions": decisions,
            "stage_skips": stage_skips,
            "run_blockers": blockers,
            "trading_calendar_snapshot_hash": calendar["snapshot_hash"],
            "event_candidate_input_hash": plan["event_candidate_input_hash"],
        }
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.freeze_outcome_opportunity")
def darwinian_freeze_outcome_opportunity(params: dict[str, Any]) -> dict[str, Any]:
    member_refs = params.get("member_refs")
    if not isinstance(member_refs, list) or any(
        not isinstance(item, dict) for item in member_refs
    ):
        raise RpcError(INVALID_PARAMS, "'member_refs' must be an array of objects")
    try:
        return _store().freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=_require_str(
                params, "outcome_schedule_plan_id"
            ),
            agent_id=_require_str(params, "agent_id"),
            qualification_predicate_version=_require_str(
                params, "qualification_predicate_version"
            ),
            member_refs=member_refs,
            source_evidence_by_required_source_id=_require_dict(
                params, "source_evidence_by_required_source_id"
            ),
            projection_snapshot_hash=_require_str(params, "projection_snapshot_hash"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.record_outcome_opportunity_failure")
def darwinian_record_outcome_opportunity_failure(
    params: dict[str, Any],
) -> dict[str, Any]:
    error_codes = params.get("error_codes")
    if not isinstance(error_codes, list) or any(
        not isinstance(item, str) for item in error_codes
    ):
        raise RpcError(INVALID_PARAMS, "'error_codes' must be an array of strings")
    try:
        return _store().record_scheduled_outcome_opportunity_failure(
            outcome_schedule_plan_id=_require_str(
                params, "outcome_schedule_plan_id"
            ),
            agent_id=_require_str(params, "agent_id"),
            qualification_predicate_version=_require_str(
                params, "qualification_predicate_version"
            ),
            source_evidence_by_required_source_id=_require_dict(
                params, "source_evidence_by_required_source_id"
            ),
            error_codes=error_codes,
            attempted_at=_require_str(params, "attempted_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.refresh_v2_windows")
def darwinian_refresh_v2_windows(params: dict[str, Any]) -> dict[str, Any]:
    revision_id = _require_str(params, "production_variant_roster_revision_id")
    cutoff_at = _require_str(params, "cutoff_at")
    trading_dates = params.get("trading_dates")
    if not isinstance(trading_dates, list):
        raise RpcError(INVALID_PARAMS, "'trading_dates' must be an array")
    try:
        rows = _store().refresh_darwinian_v2_evaluation_windows(
            production_variant_roster_revision_id=revision_id,
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        return {"evaluation_windows": rows}
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.publish_v2_updates")
def darwinian_publish_v2_updates(params: dict[str, Any]) -> dict[str, Any]:
    revision_id = _require_str(params, "production_variant_roster_revision_id")
    cutoff_at = _require_str(params, "cutoff_at")
    trading_dates = params.get("trading_dates")
    if not isinstance(trading_dates, list):
        raise RpcError(INVALID_PARAMS, "'trading_dates' must be an array")
    try:
        rows = _store().publish_darwinian_v2_weight_updates(
            production_variant_roster_revision_id=revision_id,
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        return {"published_batches": rows}
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_register_track")
def darwinian_knot_register_track(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store().register_knot_research_track(
            production_variant_roster_revision_id=_require_str(
                params, "production_variant_roster_revision_id"
            ),
            target_evaluation_track_key_hash=_require_str(
                params, "target_evaluation_track_key_hash"
            ),
            mutation_manifest=_require_dict(params, "mutation_manifest"),
            created_at=_require_str(params, "created_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_nominate")
def darwinian_knot_nominate(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store().publish_knot_nomination_audit(
            production_variant_roster_revision_id=_require_str(
                params, "production_variant_roster_revision_id"
            ),
            research_slot_id=_require_str(params, "research_slot_id"),
            track_states=_require_dict(params, "track_states"),
            active_candidate_counts_by_layer=_require_dict(
                params, "active_candidate_counts_by_layer"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_freeze_pair")
def darwinian_knot_freeze_pair(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store().freeze_knot_pair_input(
            knot_research_track_id=_require_str(params, "knot_research_track_id"),
            research_slot_id=_require_str(params, "research_slot_id"),
            evaluation_opportunity_set_id=_require_str(
                params, "evaluation_opportunity_set_id"
            ),
            root_snapshot_binding=_require_dict(params, "root_snapshot_binding"),
            champion_capability=_require_dict(params, "champion_capability"),
            candidate_capability=_require_dict(params, "candidate_capability"),
            frozen_at=_require_str(params, "frozen_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_score")
def darwinian_knot_append_score(params: dict[str, Any]) -> dict[str, Any]:
    cost_audit = params.get("sector_inference_cost_audit")
    if cost_audit is not None and not isinstance(cost_audit, dict):
        raise RpcError(
            INVALID_PARAMS, "'sector_inference_cost_audit' must be an object or null"
        )
    try:
        return _store().append_knot_research_score_record(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            pair_side=_require_str(params, "pair_side"),
            score_disposition=_require_str(params, "score_disposition"),
            recorded_at=_require_str(params, "recorded_at"),
            outcome_label_id=params.get("outcome_label_id"),
            operational_opportunity_audit_id=params.get(
                "operational_opportunity_audit_id"
            ),
            sector_inference_cost_audit=cost_audit,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_control_dependency")
def darwinian_knot_append_control_dependency(
    params: dict[str, Any],
) -> dict[str, Any]:
    evidence_ids = params.get("evidence_ids")
    if not isinstance(evidence_ids, list) or any(
        not isinstance(item, str) or not item for item in evidence_ids
    ):
        raise RpcError(INVALID_PARAMS, "'evidence_ids' must be a non-empty string array")
    output = params.get("output")
    if output is not None and not isinstance(output, dict):
        raise RpcError(INVALID_PARAMS, "'output' must be an object or null")
    run_id = params.get("run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise RpcError(INVALID_PARAMS, "'run_id' must be a non-empty string or null")
    failure_reason = params.get("failure_reason")
    if failure_reason is not None and (
        not isinstance(failure_reason, str) or not failure_reason
    ):
        raise RpcError(
            INVALID_PARAMS, "'failure_reason' must be a non-empty string or null"
        )
    try:
        return _store().append_knot_control_dependency_result(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            control_side=_require_str(params, "control_side"),
            agent_id=_require_str(params, "agent_id"),
            graph_run_id=_require_str(params, "graph_run_id"),
            run_id=run_id,
            result_disposition=_require_str(params, "result_disposition"),
            frozen_object_set_id=_require_str(params, "frozen_object_set_id"),
            frozen_object_set_hash=_require_str(params, "frozen_object_set_hash"),
            evidence_ids=evidence_ids,
            recorded_at=_require_str(params, "recorded_at"),
            output=output,
            failure_reason=failure_reason,
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_finalize_pair")
def darwinian_knot_finalize_pair(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store().finalize_knot_pair(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            pair_disposition=_require_str(params, "pair_disposition"),
            recorded_at=_require_str(params, "recorded_at"),
            exclusion_or_failure_reason=params.get("exclusion_or_failure_reason"),
            dependency_blocked_audit_id=params.get("dependency_blocked_audit_id"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_cio_dependency_blocked")
def darwinian_knot_append_cio_dependency_blocked(
    params: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _store().append_knot_cio_dependency_blocked_audit(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            control_side=_require_str(params, "control_side"),
            blocked_dependency_operational_audit_id=_require_str(
                params, "blocked_dependency_operational_audit_id"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_promotion")
def darwinian_knot_publish_promotion(params: dict[str, Any]) -> dict[str, Any]:
    hard_gate_failures = params.get("hard_gate_failures")
    if not isinstance(hard_gate_failures, list) or any(
        not isinstance(item, str) or not item for item in hard_gate_failures
    ):
        raise RpcError(INVALID_PARAMS, "'hard_gate_failures' must be a string array")
    try:
        return _store().publish_knot_promotion_revision(
            knot_research_track_id=_require_str(params, "knot_research_track_id"),
            champion_operational_reliability=params.get(
                "champion_operational_reliability"
            ),
            candidate_operational_reliability=params.get(
                "candidate_operational_reliability"
            ),
            benjamini_hochberg_q=params.get("benjamini_hochberg_q"),
            maximum_holdout_regime_degradation=params.get(
                "maximum_holdout_regime_degradation"
            ),
            hard_gate_failures=hard_gate_failures,
            recorded_at=_require_str(params, "recorded_at"),
            effective_from_research_slot_id=params.get(
                "effective_from_research_slot_id"
            ),
            new_execution_behavior_release_id=params.get(
                "new_execution_behavior_release_id"
            ),
            new_production_variant_roster_revision_id=params.get(
                "new_production_variant_roster_revision_id"
            ),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_promotion_batch")
def darwinian_knot_publish_promotion_batch(params: dict[str, Any]) -> dict[str, Any]:
    targets = params.get("targets")
    if not isinstance(targets, list) or not targets or any(
        not isinstance(target, dict) for target in targets
    ):
        raise RpcError(INVALID_PARAMS, "'targets' must be a non-empty object array")
    try:
        return _store().publish_knot_promotion_batch(
            targets=targets,
            effective_from_research_slot_id=_require_str(
                params, "effective_from_research_slot_id"
            ),
            new_execution_behavior_release_id=_require_str(
                params, "new_execution_behavior_release_id"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_rollback")
def darwinian_knot_publish_rollback(params: dict[str, Any]) -> dict[str, Any]:
    hard_gate_failures = params.get("hard_gate_failures")
    if not isinstance(hard_gate_failures, list) or any(
        not isinstance(item, str) or not item for item in hard_gate_failures
    ):
        raise RpcError(INVALID_PARAMS, "'hard_gate_failures' must be a string array")
    try:
        return _store().publish_knot_rollback_revision(
            knot_research_track_id=_require_str(params, "knot_research_track_id"),
            champion_operational_reliability=params.get(
                "champion_operational_reliability"
            ),
            candidate_operational_reliability=params.get(
                "candidate_operational_reliability"
            ),
            hard_gate_failures=hard_gate_failures,
            effective_from_research_slot_id=_require_str(
                params, "effective_from_research_slot_id"
            ),
            new_execution_behavior_release_id=_require_str(
                params, "new_execution_behavior_release_id"
            ),
            new_production_variant_roster_revision_id=_require_str(
                params, "new_production_variant_roster_revision_id"
            ),
            cooldown_until_research_slot_id=_require_str(
                params, "cooldown_until_research_slot_id"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.compute")
def darwinian_compute(params: dict[str, Any]) -> dict[str, Any]:
    """Compute and persist Darwinian weights for every agent in the cohort.

    Params:
        cohort: str
        today:  str (YYYY-MM-DD)

    Returns:
        {"written": <int>, "agents_uniform_fallback": <int>}
    """
    cohort = _require_str(params, "cohort")
    today = _require_str(params, "today")

    try:
        from mosaic.scorecard import compute_weights
    except ImportError as exc:
        raise RpcError(INTERNAL_ERROR, f"scorecard package not importable: {exc}") from exc

    try:
        return compute_weights(_store(), cohort=cohort, today=today, config=_config())
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# darwinian.get_weights
# ---------------------------------------------------------------------------


@method("darwinian.get_weights")
def darwinian_get_weights(params: dict[str, Any]) -> dict[str, Any]:
    """Read the latest (or specified date's) Darwinian weight table.

    Params:
        cohort: str
        date:   str (YYYY-MM-DD, optional) — when omitted returns latest
                                              row per (cohort, agent).

    Returns:
        {"weights": {<agent>: {"weight": float,
                                "sharpe_30": float | None,
                                "sharpe_90": float | None,
                                "quartile": int | None}}}

    When the table is empty (e.g. before darwinian.compute has ever run),
    returns ``{"weights": {}}`` — caller treats that as the uniform=1.0
    Phase 2 stub fallback (Plan §11.3 design decision #7).
    """
    cohort = _require_str(params, "cohort")
    date: Optional[str] = params.get("date") or None
    if date is not None and not isinstance(date, str):
        raise RpcError(INVALID_PARAMS, "'date' must be a string when provided")

    try:
        weights = _store().get_darwinian_weights(cohort=cohort, date=date)
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return {"weights": weights}
