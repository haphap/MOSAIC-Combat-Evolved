"""``darwinian.*`` JSON-RPC handlers.

Production v2 uses ``prepare_variant`` and ``publish_v2_updates``.  The old
``compute/get_weights`` surface remains available only for explicit
legacy-unverified audit/replay; it is never an implicit fallback for a
production v2 runtime binding.
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


def _capability_store():
    from mosaic.bridge.tool_capabilities import get_capability_store

    return get_capability_store()


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


def _optional_str(params: dict, key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RpcError(
            INVALID_PARAMS, f"'{key}' must be a non-empty string or null"
        )
    return value.strip()


def _reject_unknown_params(params: dict, allowed: set[str]) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise RpcError(
            INVALID_PARAMS,
            f"unsupported parameter(s): {', '.join(unknown)}",
        )


def _require_dict(params: dict, key: str) -> dict[str, Any]:
    value = params.get(key)
    if not isinstance(value, dict):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an object")
    return value


def _require_choice(params: dict, key: str, allowed: set[str]) -> str:
    value = _require_str(params, key)
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise RpcError(INVALID_PARAMS, f"'{key}' must be one of: {choices}")
    return value


def _require_nonempty_str_list(params: dict, key: str) -> list[str]:
    value = params.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string array")
    return [item.strip() for item in value]


def _require_positive_int(params: dict, key: str) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a positive integer")
    return value


def _optional_positive_int(params: dict, key: str) -> int | None:
    if params.get(key) is None:
        return None
    return _require_positive_int(params, key)


def _require_legacy_audit_only(params: dict[str, Any], allowed: set[str]) -> None:
    _reject_unknown_params(params, allowed | {"audit_only"})
    if params.get("audit_only") is not True:
        raise RpcError(
            INVALID_PARAMS,
            "legacy Darwinian v1 is legacy_unverified/audit_only; production mutation "
            "must use the frozen Darwinian v2 refresh/publish path",
        )


# ---------------------------------------------------------------------------
# darwinian.compute
# ---------------------------------------------------------------------------


@method("darwinian.prepare_variant")
def darwinian_prepare_variant(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(params, {"binding", "as_of"})
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
    del params
    raise RpcError(
        INVALID_PARAMS,
        "outcome schedule inputs are server-owned; use "
        "darwinian.prepare_daily_cycle_outcomes",
    )


@method("darwinian.prepare_daily_cycle_outcomes")
def darwinian_prepare_daily_cycle_outcomes(params: dict[str, Any]) -> dict[str, Any]:
    """Freeze the real-run calendar, event denominator and scheduled opportunities."""
    _reject_unknown_params(
        params,
        {
            "production_variant_roster_revision_id",
            "graph_run_id",
            "as_of",
            "prepared_at",
        },
    )
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
    del params
    raise RpcError(
        INVALID_PARAMS,
        "outcome opportunity projections are server-owned; use "
        "darwinian.prepare_daily_cycle_outcomes",
    )


@method("darwinian.record_outcome_opportunity_failure")
def darwinian_record_outcome_opportunity_failure(
    params: dict[str, Any],
) -> dict[str, Any]:
    del params
    raise RpcError(
        INVALID_PARAMS,
        "outcome opportunity failure evidence is server-owned; use "
        "darwinian.prepare_daily_cycle_outcomes",
    )


def _verified_darwinian_trading_dates(cutoff_at: str) -> list[str]:
    from mosaic.dataflows.calendar import verified_trading_calendar_snapshot

    cutoff_date = date.fromisoformat(cutoff_at[:10]).isoformat()
    snapshot = verified_trading_calendar_snapshot(
        "2010-01-04",
        cutoff_date,
        as_of=cutoff_at,
    )
    dates = snapshot.get("trading_dates")
    if not isinstance(dates, list) or any(
        not isinstance(item, str) for item in dates
    ):
        raise RuntimeError("verified trading calendar snapshot is invalid")
    return dates


@method("darwinian.refresh_v2_windows")
def darwinian_refresh_v2_windows(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {"production_variant_roster_revision_id", "cutoff_at"},
    )
    revision_id = _require_str(params, "production_variant_roster_revision_id")
    cutoff_at = _require_str(params, "cutoff_at")
    try:
        rows = _store().refresh_darwinian_v2_evaluation_windows(
            production_variant_roster_revision_id=revision_id,
            cutoff_at=cutoff_at,
            trading_dates=_verified_darwinian_trading_dates(cutoff_at),
        )
        return {"evaluation_windows": rows}
    except (ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.publish_v2_updates")
def darwinian_publish_v2_updates(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {"production_variant_roster_revision_id", "cutoff_at"},
    )
    revision_id = _require_str(params, "production_variant_roster_revision_id")
    cutoff_at = _require_str(params, "cutoff_at")
    try:
        rows = _store().publish_darwinian_v2_weight_updates(
            production_variant_roster_revision_id=revision_id,
            cutoff_at=cutoff_at,
            trading_dates=_verified_darwinian_trading_dates(cutoff_at),
        )
        return {"published_batches": rows}
    except (ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_register_track")
def darwinian_knot_register_track(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_nomination_audit_id",
            "production_variant_roster_revision_id",
            "target_evaluation_track_key_hash",
            "mutation_definition",
            "created_at",
        },
    )
    try:
        return _store().register_knot_research_track(
            knot_nomination_audit_id=_require_str(
                params, "knot_nomination_audit_id"
            ),
            production_variant_roster_revision_id=_require_str(
                params, "production_variant_roster_revision_id"
            ),
            target_evaluation_track_key_hash=_require_str(
                params, "target_evaluation_track_key_hash"
            ),
            mutation_definition=_require_dict(params, "mutation_definition"),
            created_at=_require_str(params, "created_at"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_nominate")
def darwinian_knot_nominate(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "production_variant_roster_revision_id",
            "research_slot_id",
            "research_slot_sequence",
            "recorded_at",
        },
    )
    try:
        return _store().publish_knot_nomination_audit(
            production_variant_roster_revision_id=_require_str(
                params, "production_variant_roster_revision_id"
            ),
            research_slot_id=_require_str(params, "research_slot_id"),
            research_slot_sequence=_require_positive_int(
                params, "research_slot_sequence"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_schedule")
def darwinian_knot_publish_schedule(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {"knot_research_track_id", "pair_phase", "slots", "published_at"},
    )
    slots = params.get("slots")
    if not isinstance(slots, list) or not slots:
        raise RpcError(INVALID_PARAMS, "'slots' must be a non-empty object array")
    normalized_slots: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            raise RpcError(INVALID_PARAMS, "each schedule slot must be an object")
        _reject_unknown_params(
            slot,
            {"research_slot_id", "research_slot_sequence", "scheduled_sample_id"},
        )
        normalized_slots.append(
            {
                "research_slot_id": _require_str(slot, "research_slot_id"),
                "research_slot_sequence": _require_positive_int(
                    slot, "research_slot_sequence"
                ),
                "scheduled_sample_id": _require_str(
                    slot, "scheduled_sample_id"
                ),
            }
        )
    try:
        return _store().publish_knot_research_schedule(
            knot_research_track_id=_require_str(
                params, "knot_research_track_id"
            ),
            pair_phase=_require_choice(
                params,
                "pair_phase",
                {"RESEARCH", "POST_PROMOTION_SHADOW"},
            ),
            slots=normalized_slots,
            published_at=_require_str(params, "published_at"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_preregister_pair_assignment")
def darwinian_knot_preregister_pair_assignment(
    params: dict[str, Any],
) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_research_track_id",
            "research_slot_id",
            "scheduled_sample_id",
            "pair_phase",
            "regime_source_snapshot",
        },
    )
    try:
        knot_research_track_id = _require_str(
            params, "knot_research_track_id"
        )
        research_slot_id = _require_str(params, "research_slot_id")
        scheduled_sample_id = _require_str(params, "scheduled_sample_id")
        sample_context = _store().resolve_scheduled_sample_context(
            scheduled_sample_id=scheduled_sample_id
        )
        expected_as_of = _require_str(sample_context, "as_of")[:10]
        capability_store = _capability_store()
        regime_receipt = capability_store.classify_and_reserve_knot_regime(
            knot_research_track_id=knot_research_track_id,
            research_slot_id=research_slot_id,
            scheduled_sample_id=scheduled_sample_id,
            expected_as_of=expected_as_of,
            source_snapshot=_require_dict(params, "regime_source_snapshot"),
        )
        return _store().preregister_knot_pair_assignment(
            knot_research_track_id=knot_research_track_id,
            research_slot_id=research_slot_id,
            scheduled_sample_id=scheduled_sample_id,
            pair_phase=_require_choice(
                params,
                "pair_phase",
                {"RESEARCH", "POST_PROMOTION_SHADOW"},
            ),
            regime_classification_receipt=regime_receipt,
            receipt_verifier=(
                capability_store.verify_knot_regime_classification_receipt
            ),
            assigned_at=regime_receipt["classified_at"],
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_freeze_pair")
def darwinian_knot_freeze_pair(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_research_track_id",
            "knot_pair_assignment_id",
            "research_slot_id",
            "evaluation_opportunity_set_id",
            "champion_capability_envelope",
            "candidate_capability_envelope",
        },
    )
    try:
        pair_binding = {
            "knot_research_track_id": _require_str(
                params, "knot_research_track_id"
            ),
            "knot_pair_assignment_id": _require_str(
                params, "knot_pair_assignment_id"
            ),
            "research_slot_id": _require_str(params, "research_slot_id"),
            "evaluation_opportunity_set_id": _require_str(
                params, "evaluation_opportunity_set_id"
            ),
        }
        capability_store = _capability_store()
        pair_root_receipt = capability_store.verify_and_reserve_knot_pair_root(
            pair_binding=pair_binding,
            champion_envelope=_require_dict(
                params, "champion_capability_envelope"
            ),
            candidate_envelope=_require_dict(
                params, "candidate_capability_envelope"
            ),
        )
        result = _store().freeze_knot_pair_input(
            **pair_binding,
            pair_root_receipt=pair_root_receipt,
            receipt_verifier=capability_store.verify_knot_pair_root_receipt,
        )
        if "sector_inference_budget_contract" not in result:
            raise ValueError(
                "private KNOT freeze result lacks Sector inference budget binding"
            )
        sector_budget = result["sector_inference_budget_contract"]
        if sector_budget is not None and not isinstance(sector_budget, dict):
            raise ValueError("private Sector inference budget contract must be an object")
        capability_store.bind_knot_private_pair(
            pair_root_reservation_id=pair_root_receipt[
                "pair_root_reservation_id"
            ],
            knot_pair_id=_require_str(result, "knot_pair_id"),
            knot_pair_input_hash=_require_str(result, "knot_pair_input_hash"),
            sector_inference_budget_contract=sector_budget,
        )
        budget_ref = (
            {
                "budget_contract_id": _require_str(
                    sector_budget, "budget_contract_id"
                ),
                "budget_contract_version": _require_str(
                    sector_budget, "budget_contract_version"
                ),
                "budget_contract_hash": _require_str(
                    sector_budget, "budget_contract_hash"
                ),
            }
            if sector_budget is not None
            else None
        )
        return {
            **{
                key: value
                for key, value in result.items()
                if key != "sector_inference_budget_contract"
            },
            "sector_inference_budget_contract_ref": budget_ref,
        }
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_score")
def darwinian_knot_append_score(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_pair_id",
            "pair_side",
            "score_disposition",
            "recorded_at",
            "outcome_label_id",
            "operational_opportunity_audit_id",
            "sector_inference_cost_audit_id",
        },
    )
    disposition = _require_choice(
        params, "score_disposition", {"SCORE", "AGENT_FAILURE"}
    )
    outcome_label_id = _optional_str(params, "outcome_label_id")
    operational_audit_id = _optional_str(
        params, "operational_opportunity_audit_id"
    )
    if disposition == "SCORE":
        if outcome_label_id is None:
            raise RpcError(
                INVALID_PARAMS,
                "SCORE requires 'outcome_label_id'",
            )
        if operational_audit_id is not None:
            raise RpcError(
                INVALID_PARAMS,
                "SCORE cannot carry 'operational_opportunity_audit_id'",
            )
    elif outcome_label_id is not None:
        raise RpcError(
            INVALID_PARAMS,
            "AGENT_FAILURE cannot carry 'outcome_label_id'",
        )
    try:
        return _store().append_knot_research_score_record(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            pair_side=_require_choice(
                params, "pair_side", {"CHAMPION", "CANDIDATE"}
            ),
            score_disposition=disposition,
            recorded_at=_require_str(params, "recorded_at"),
            outcome_label_id=outcome_label_id,
            operational_opportunity_audit_id=operational_audit_id,
            sector_inference_cost_audit_id=_optional_str(
                params,
                "sector_inference_cost_audit_id"
            ),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_pair_side_result")
def darwinian_knot_append_pair_side_result(
    params: dict[str, Any],
) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_pair_id",
            "pair_side",
            "result_disposition",
            "recorded_at",
            "accepted_output_record",
            "verified_claim_graph",
            "schema_json",
            "failure_reason",
            "cio_failure_phase",
            "output_phase",
        },
    )
    try:
        knot_pair_id = _require_str(params, "knot_pair_id")
        pair_side = _require_choice(
            params, "pair_side", {"CHAMPION", "CANDIDATE"}
        )
        disposition = _require_choice(
            params, "result_disposition", {"ACCEPTED", "AGENT_FAILURE"}
        )
        capability_store = _capability_store()
        capability = capability_store.resolve_knot_pair_side_capability(
            knot_pair_id=knot_pair_id,
            pair_side=pair_side,
        )
        is_cio = capability.get("agent_id") == "cio"
        if is_cio and capability.get("stage") != "cio_final":
            raise RpcError(
                INVALID_PARAMS,
                "two-phase CIO KNOT execution requires its cio_final orchestration capability",
            )
        validated_output: dict[str, Any] | None = None
        failure_reason = _optional_str(params, "failure_reason")
        cio_failure_phase = _optional_str(params, "cio_failure_phase")
        output_phase = _optional_str(params, "output_phase")
        private_cio_output_phase: str | None = None
        strict_receipt_verifier = None
        accepted_fields = (
            "accepted_output_record",
            "verified_claim_graph",
            "schema_json",
        )
        if disposition == "ACCEPTED":
            if failure_reason is not None:
                raise RpcError(
                    INVALID_PARAMS,
                    "accepted KNOT side cannot carry 'failure_reason'",
                )
            if cio_failure_phase is not None:
                raise RpcError(
                    INVALID_PARAMS,
                    "accepted KNOT side cannot carry 'cio_failure_phase'",
                )
            if is_cio:
                if output_phase not in {"CIO_PROPOSAL", "CIO_FINAL"}:
                    raise RpcError(
                        INVALID_PARAMS,
                        "accepted CIO KNOT side requires output_phase "
                        "CIO_PROPOSAL or CIO_FINAL",
                    )
                private_cio_output_phase = output_phase.removeprefix("CIO_")
            elif output_phase is not None:
                raise RpcError(
                    INVALID_PARAMS,
                    "output_phase is restricted to accepted CIO KNOT sides",
                )
            accepted_output_record = _require_dict(
                params, "accepted_output_record"
            )
            verified_claim_graph = _require_dict(
                params, "verified_claim_graph"
            )
            schema_json = _require_dict(params, "schema_json")
            schema_binding = _store().resolve_knot_strict_schema_binding(
                knot_pair_id=knot_pair_id,
                pair_side=pair_side,
                cio_output_phase=private_cio_output_phase,
            )
            if is_cio and schema_binding.get("accepted_output_kind") != output_phase:
                raise RpcError(
                    INVALID_PARAMS,
                    "CIO output phase differs from its private schema binding",
                )
            strict_receipt = (
                capability_store.mint_knot_strict_output_validation_receipt(
                    knot_pair_id=knot_pair_id,
                    pair_side=pair_side,
                    accepted_output_kind=_require_str(
                        schema_binding, "accepted_output_kind"
                    ),
                    accepted_output_record=accepted_output_record,
                    verified_claim_graph=verified_claim_graph,
                    schema_binding=schema_binding,
                    schema_json=schema_json,
                )
            )
            validated_output = {
                "accepted_output_record": accepted_output_record,
                "verified_claim_graph": verified_claim_graph,
                "strict_validation_receipt": strict_receipt,
            }
            strict_receipt_verifier = (
                capability_store.verify_knot_strict_output_validation_receipt
            )
        else:
            if any(params.get(field) is not None for field in accepted_fields):
                raise RpcError(
                    INVALID_PARAMS,
                    "failed KNOT side cannot carry accepted output fields",
                )
            if failure_reason is None:
                raise RpcError(
                    INVALID_PARAMS,
                    "failed KNOT side requires 'failure_reason'",
                )
            if output_phase is not None:
                raise RpcError(
                    INVALID_PARAMS,
                    "failed KNOT side cannot carry 'output_phase'",
                )
            if cio_failure_phase is not None and cio_failure_phase not in {
                "PROPOSAL",
                "FINAL",
            }:
                raise RpcError(
                    INVALID_PARAMS,
                    "'cio_failure_phase' must be PROPOSAL, FINAL, or null",
                )
            if cio_failure_phase is not None and not is_cio:
                raise RpcError(
                    INVALID_PARAMS,
                    "cio_failure_phase is restricted to CIO KNOT sides",
                )
        append_kwargs = {
            "knot_pair_id": knot_pair_id,
            "pair_side": pair_side,
            "graph_run_id": capability["graph_run_id"],
            "run_id": capability["run_id"],
            "result_disposition": disposition,
            "recorded_at": _require_str(params, "recorded_at"),
            "validated_output": validated_output,
            "failure_reason": failure_reason,
            "strict_receipt_verifier": strict_receipt_verifier,
            "cio_failure_phase": cio_failure_phase,
            "cio_output_phase": private_cio_output_phase,
        }
        if disposition == "ACCEPTED" and output_phase == "CIO_PROPOSAL":
            return _store().append_knot_cio_proposal_execution_result(
                **append_kwargs
            )
        return _store().append_knot_pair_side_execution_result(
            **append_kwargs
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_sector_cost_audit")
def darwinian_knot_append_sector_cost_audit(
    params: dict[str, Any],
) -> dict[str, Any]:
    _reject_unknown_params(params, {"knot_pair_id", "pair_side"})
    try:
        knot_pair_id = _require_str(params, "knot_pair_id")
        pair_side = _require_choice(
            params, "pair_side", {"CHAMPION", "CANDIDATE"}
        )
        binding = _store().resolve_knot_sector_usage_binding(
            knot_pair_id=knot_pair_id,
            pair_side=pair_side,
        )
        capability_store = _capability_store()
        usage_receipt = capability_store.mint_knot_sector_inference_usage_receipt(
            binding=binding
        )
        return _store().append_knot_sector_inference_cost_audit(
            knot_pair_id=knot_pair_id,
            pair_side=pair_side,
            usage_receipt=usage_receipt,
            receipt_verifier=(
                capability_store.verify_knot_sector_inference_usage_receipt
            ),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_control_dependency")
def darwinian_knot_append_control_dependency(
    params: dict[str, Any],
) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_pair_id",
            "control_side",
            "agent_id",
            "graph_run_id",
            "run_id",
            "result_disposition",
            "frozen_object_set_id",
            "frozen_object_set_hash",
            "evidence_ids",
            "recorded_at",
            "output",
            "schema_json",
            "failure_reason",
        },
    )
    evidence_ids = _require_nonempty_str_list(params, "evidence_ids")
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
        knot_pair_id = _require_str(params, "knot_pair_id")
        control_side = _require_choice(
            params, "control_side", {"SHARED", "CHAMPION", "CANDIDATE"}
        )
        agent_id = _require_choice(
            params,
            "agent_id",
            {"alpha_discovery", "cro", "autonomous_execution"},
        )
        disposition = _require_choice(
            params,
            "result_disposition",
            {
                "ACCEPTED",
                "NO_EVALUATION_OBJECT",
                "AGENT_FAILURE",
                "EXOGENOUS_EXCLUSION",
            },
        )
        recorded_at = _require_str(params, "recorded_at")
        validated_output = None
        strict_receipt_verifier = None
        if disposition == "ACCEPTED":
            if output is None:
                raise RpcError(
                    INVALID_PARAMS,
                    "accepted KNOT control dependency requires 'output'",
                )
            if run_id is None:
                raise RpcError(
                    INVALID_PARAMS,
                    "accepted KNOT control dependency requires 'run_id'",
                )
            if failure_reason is not None:
                raise RpcError(
                    INVALID_PARAMS,
                    "accepted KNOT control dependency cannot carry 'failure_reason'",
                )
            schema_json = _require_dict(params, "schema_json")
            binding = _store().resolve_knot_control_strict_schema_binding(
                knot_pair_id=knot_pair_id,
                control_side=control_side,
                agent_id=agent_id,
            )
            strict_receipt = (
                _capability_store().mint_knot_control_strict_output_validation_receipt(
                    binding=binding,
                    run_id=run_id,
                    frozen_object_set_id=_require_str(
                        params, "frozen_object_set_id"
                    ),
                    frozen_object_set_hash=_require_str(
                        params, "frozen_object_set_hash"
                    ),
                    accepted_output_record=output,
                    schema_json=schema_json,
                    validated_at=recorded_at,
                )
            )
            validated_output = {
                "accepted_output_record": output,
                "strict_validation_receipt": strict_receipt,
            }
            strict_receipt_verifier = (
                _capability_store().verify_knot_control_strict_output_validation_receipt
            )
        elif output is not None or params.get("schema_json") is not None:
            raise RpcError(
                INVALID_PARAMS,
                "non-accepted KNOT control dependency cannot carry output/schema",
            )
        return _store().append_knot_control_dependency_result(
            knot_pair_id=knot_pair_id,
            control_side=control_side,
            agent_id=agent_id,
            graph_run_id=_require_str(params, "graph_run_id"),
            run_id=run_id,
            result_disposition=disposition,
            frozen_object_set_id=_require_str(params, "frozen_object_set_id"),
            frozen_object_set_hash=_require_str(params, "frozen_object_set_hash"),
            evidence_ids=evidence_ids,
            recorded_at=recorded_at,
            validated_output=validated_output,
            strict_receipt_verifier=strict_receipt_verifier,
            failure_reason=failure_reason,
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_finalize_pair")
def darwinian_knot_finalize_pair(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_pair_id",
            "pair_disposition",
            "recorded_at",
            "exclusion_or_failure_reason",
            "dependency_blocked_audit_id",
            "exclusion_audit_id",
        },
    )
    try:
        return _store().finalize_knot_pair(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            pair_disposition=_require_choice(
                params,
                "pair_disposition",
                {
                    "ACCOUNTABLE",
                    "EXOGENOUS_EXCLUSION",
                    "DEPENDENCY_BLOCKED",
                    "CONTRACT_FAILURE",
                },
            ),
            recorded_at=_require_str(params, "recorded_at"),
            exclusion_or_failure_reason=_optional_str(
                params, "exclusion_or_failure_reason"
            ),
            dependency_blocked_audit_id=_optional_str(
                params, "dependency_blocked_audit_id"
            ),
            exclusion_audit_id=_optional_str(params, "exclusion_audit_id"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_append_cio_dependency_blocked")
def darwinian_knot_append_cio_dependency_blocked(
    params: dict[str, Any],
) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_pair_id",
            "control_side",
            "blocked_dependency_operational_audit_id",
            "recorded_at",
        },
    )
    try:
        return _store().append_knot_cio_dependency_blocked_audit(
            knot_pair_id=_require_str(params, "knot_pair_id"),
            control_side=_require_choice(
                params, "control_side", {"SHARED", "CHAMPION", "CANDIDATE"}
            ),
            blocked_dependency_operational_audit_id=_require_str(
                params, "blocked_dependency_operational_audit_id"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_promotion")
def darwinian_knot_publish_promotion(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_research_track_id",
            "recorded_at",
            "effective_from_research_slot_id",
            "effective_from_research_slot_sequence",
            "new_execution_behavior_release_id",
            "new_production_variant_roster_revision_id",
        },
    )
    try:
        return _store().publish_knot_promotion_revision(
            knot_research_track_id=_require_str(params, "knot_research_track_id"),
            recorded_at=_require_str(params, "recorded_at"),
            effective_from_research_slot_id=_optional_str(
                params,
                "effective_from_research_slot_id"
            ),
            effective_from_research_slot_sequence=_optional_positive_int(
                params,
                "effective_from_research_slot_sequence",
            ),
            new_execution_behavior_release_id=_optional_str(
                params,
                "new_execution_behavior_release_id"
            ),
            new_production_variant_roster_revision_id=_optional_str(
                params,
                "new_production_variant_roster_revision_id"
            ),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_promotion_batch")
def darwinian_knot_publish_promotion_batch(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "targets",
            "effective_from_research_slot_id",
            "effective_from_research_slot_sequence",
            "new_execution_behavior_release_id",
            "recorded_at",
        },
    )
    targets = params.get("targets")
    if not isinstance(targets, list) or not targets or any(
        not isinstance(target, dict) for target in targets
    ):
        raise RpcError(INVALID_PARAMS, "'targets' must be a non-empty object array")
    normalized_targets: list[dict[str, str]] = []
    for target in targets:
        _reject_unknown_params(
            target,
            {
                "knot_research_track_id",
                "new_production_variant_roster_revision_id",
            },
        )
        normalized_targets.append(
            {
                "knot_research_track_id": _require_str(
                    target, "knot_research_track_id"
                ),
                "new_production_variant_roster_revision_id": _require_str(
                    target, "new_production_variant_roster_revision_id"
                ),
            }
        )
    try:
        return _store().publish_knot_promotion_batch(
            targets=normalized_targets,
            effective_from_research_slot_id=_require_str(
                params, "effective_from_research_slot_id"
            ),
            effective_from_research_slot_sequence=_require_positive_int(
                params, "effective_from_research_slot_sequence"
            ),
            new_execution_behavior_release_id=_require_str(
                params, "new_execution_behavior_release_id"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.knot_publish_rollback")
def darwinian_knot_publish_rollback(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {
            "knot_research_track_id",
            "effective_from_research_slot_id",
            "effective_from_research_slot_sequence",
            "new_execution_behavior_release_id",
            "new_production_variant_roster_revision_id",
            "cooldown_until_research_slot_id",
            "cooldown_until_research_slot_sequence",
            "recorded_at",
        },
    )
    try:
        return _store().publish_knot_rollback_revision(
            knot_research_track_id=_require_str(params, "knot_research_track_id"),
            effective_from_research_slot_id=_require_str(
                params, "effective_from_research_slot_id"
            ),
            effective_from_research_slot_sequence=_require_positive_int(
                params, "effective_from_research_slot_sequence"
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
            cooldown_until_research_slot_sequence=_require_positive_int(
                params, "cooldown_until_research_slot_sequence"
            ),
            recorded_at=_require_str(params, "recorded_at"),
        )
    except RpcError:
        raise
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.compute")
def darwinian_compute(params: dict[str, Any]) -> dict[str, Any]:
    """Compute legacy-unverified v1 weights for explicit audit/replay only.

    Params:
        cohort: str
        today:  str (YYYY-MM-DD)

    Returns:
        {"written": <int>, "agents_uniform_fallback": <int>}
    """
    _require_legacy_audit_only(params, {"cohort", "today"})
    cohort = _require_str(params, "cohort")
    today = _require_str(params, "today")

    try:
        from mosaic.scorecard import compute_weights
    except ImportError as exc:
        raise RpcError(INTERNAL_ERROR, f"scorecard package not importable: {exc}") from exc

    try:
        result = compute_weights(_store(), cohort=cohort, today=today, config=_config())
        return {"status": "legacy_unverified", "audit_only": True, **result}
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# darwinian.get_weights
# ---------------------------------------------------------------------------


@method("darwinian.get_weights")
def darwinian_get_weights(params: dict[str, Any]) -> dict[str, Any]:
    """Read the legacy-unverified v1 table for explicit audit/replay only.

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
    returns ``{"weights": {}}`` for audit/replay.  Production callers must use
    a frozen Darwinian-v2 production-variant binding and cannot treat this
    legacy table as a fallback.
    """
    _require_legacy_audit_only(params, {"cohort", "date"})
    cohort = _require_str(params, "cohort")
    date: Optional[str] = params.get("date") or None
    if date is not None and not isinstance(date, str):
        raise RpcError(INVALID_PARAMS, "'date' must be a string when provided")

    try:
        weights = _store().get_darwinian_weights(cohort=cohort, date=date)
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc

    return {"status": "legacy_unverified", "audit_only": True, "weights": weights}
