"""``darwinian.*`` JSON-RPC handlers.

Production v2 uses ``prepare_variant`` and ``publish_v2_updates``.  The old
``compute/get_weights`` surface remains available only for explicit
legacy-unverified audit/replay; it is never an implicit fallback for a
production v2 runtime binding.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

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


_DEFERRED_DECISION_OPPORTUNITY_AGENTS = {
    "alpha_discovery",
    "cro",
    "autonomous_execution",
    "cio",
}
_DEFERRED_SUPERINVESTOR_OPPORTUNITY_AGENTS = {
    "druckenmiller",
    "munger",
    "burry",
    "ackman",
}
_LIVE_L1_L2_OPPORTUNITY_AGENTS = {
    "china",
    "us_economy",
    "eu_economy",
    "central_bank",
    "us_financial_conditions",
    "euro_area_financial_conditions",
    "commodities",
    "geopolitical",
    "market_breadth",
    "institutional_flow",
    "semiconductor",
    "technology",
    "energy",
    "biotech",
    "consumer",
    "industrials",
    "real_estate_construction",
    "financials",
    "agriculture",
    "relationship_mapper",
}
_DEFERRED_RUNTIME_OPPORTUNITY_AGENTS = (
    _DEFERRED_DECISION_OPPORTUNITY_AGENTS
    | _DEFERRED_SUPERINVESTOR_OPPORTUNITY_AGENTS
    | _LIVE_L1_L2_OPPORTUNITY_AGENTS
)


def _server_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_stage_authority_failure(
    *,
    store: Any,
    outcome_schedule_plan_id: str,
    agent_id: str,
    projection: Mapping[str, Any],
    attempted_at: str,
    error_code: str,
    blocker_reason: str,
) -> dict[str, Any]:
    decision = store.record_scheduled_outcome_opportunity_failure(
        outcome_schedule_plan_id=outcome_schedule_plan_id,
        agent_id=agent_id,
        qualification_predicate_version=projection[
            "qualification_predicate_version"
        ],
        source_evidence_by_required_source_id=projection[
            "source_evidence_by_required_source_id"
        ],
        error_codes=[error_code],
        attempted_at=attempted_at,
    )
    return {
        **decision,
        "run_allowed": False,
        "blocker_reason": blocker_reason,
    }


def _decision_stage_frozen_object(
    agent_id: str,
    value: Mapping[str, Any],
    *,
    runtime_authority: Mapping[str, Any] | None = None,
) -> tuple[str, str, list[dict[str, Any]], dict[str, str]]:
    """Verify one runtime-frozen Decision denominator before any model call."""
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    expected_fields = {
        "schema_version",
        "agent_id",
        "object_kind",
        "frozen_object_set_id",
        "frozen_object_set_hash",
        "object_payload",
        "member_refs",
    }
    if set(value) != expected_fields:
        raise ValueError("Decision frozen object fields mismatch")
    if value.get("schema_version") != "decision_stage_frozen_object_set_v1":
        raise ValueError("Decision frozen object schema mismatch")
    if value.get("agent_id") != agent_id:
        raise ValueError("Decision frozen object owner mismatch")
    frozen_hash = value.get("frozen_object_set_hash")
    payload = value.get("object_payload")
    members = value.get("member_refs")
    if not isinstance(payload, Mapping) or not isinstance(members, list):
        raise ValueError("Decision frozen object payload or members are invalid")
    if frozen_hash != canonical_hash(payload):
        raise ValueError("Decision frozen object hash mismatch")
    if not (
        isinstance(frozen_hash, str)
        and len(frozen_hash) == 71
        and frozen_hash.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in frozen_hash[7:])
    ):
        raise ValueError("Decision frozen object hash is invalid")
    namespace_by_agent = {
        "alpha_discovery": "alpha-novel-candidate-universe",
        "cro": "cro-candidate-universe",
        "autonomous_execution": "order-intent-set",
        "cio": "cio-frozen-portfolio",
    }
    expected_id = f"{namespace_by_agent[agent_id]}:{str(frozen_hash)[7:]}"
    if value.get("frozen_object_set_id") != expected_id:
        raise ValueError("Decision frozen object ID mismatch")
    object_kind_by_agent = {
        "alpha_discovery": "ALPHA_NOVEL_CANDIDATE_UNIVERSE",
        "cro": "CRO_CANDIDATE_UNIVERSE",
        "autonomous_execution": "EXECUTION_ORDER_INTENT_SET",
        "cio": "CIO_FROZEN_PORTFOLIO_CONTEXT",
    }
    if value.get("object_kind") != object_kind_by_agent[agent_id]:
        raise ValueError("Decision frozen object kind mismatch")

    from mosaic.dataflows.outcome_runtime_inputs import (
        expected_qualification_predicate_version,
        validate_evaluation_opportunity_members,
    )

    normalized_members = validate_evaluation_opportunity_members(
        agent_id,
        expected_qualification_predicate_version(agent_id),
        members,
    )
    if normalized_members != members:
        raise ValueError("Decision frozen object member domain mismatch")
    expected_payload, expected_members = _expected_decision_frozen_object(
        agent_id,
        runtime_authority,
    )
    if dict(payload) != expected_payload or normalized_members != expected_members:
        raise ValueError(
            f"{agent_id} frozen object differs from the server-owned runtime authority"
        )
    return (
        str(value["frozen_object_set_id"]),
        str(frozen_hash),
        normalized_members,
        _decision_runtime_authority_binding(agent_id, runtime_authority),
    )


def _expected_decision_frozen_object(
    agent_id: str,
    authority: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    if authority is None:
        raise ValueError(f"{agent_id} runtime candidate authority is unavailable")
    expected_agent = {
        "alpha_discovery": ("alpha_discovery", "alpha_discovery"),
        "cro": ("cro", "cro"),
        "autonomous_execution": (
            "autonomous_execution",
            "autonomous_execution",
        ),
        "cio": ("cio", "cio_final"),
    }[agent_id]
    if (
        authority.get("agent_id") != expected_agent[0]
        or authority.get("stage") != expected_agent[1]
    ):
        raise ValueError(f"{agent_id} runtime authority Agent/stage mismatch")
    candidates = authority.get("candidate_universe")
    refs = authority.get("upstream_accepted_output_refs")
    if not isinstance(candidates, list) or not all(
        isinstance(row, Mapping) for row in candidates
    ):
        raise ValueError(f"{agent_id} runtime candidate universe is invalid")
    if not isinstance(refs, list) or not all(isinstance(row, Mapping) for row in refs):
        raise ValueError(f"{agent_id} runtime upstream accepted refs are invalid")
    if authority.get("candidate_universe_hash") != canonical_hash(
        {
            "candidate_status": authority.get("candidate_status"),
            "candidate_universe": candidates,
        }
    ):
        raise ValueError(f"{agent_id} runtime candidate universe hash mismatch")
    common = {
        "snapshot_id": authority.get("snapshot_id"),
        "snapshot_hash": authority.get("snapshot_hash"),
        "candidate_scope_hash": authority.get("candidate_scope_hash"),
        "candidate_universe_id": authority.get("candidate_universe_id"),
        "candidate_universe_hash": authority.get("candidate_universe_hash"),
        "upstream_accepted_output_refs": refs,
    }
    _decision_runtime_authority_binding(agent_id, authority)
    if agent_id == "alpha_discovery":
        members = sorted(
            [
                {
                    "candidate_ref": row.get("candidate_ref"),
                    "ts_code": row.get("ts_code"),
                }
                for row in candidates
            ],
            key=lambda row: str(row["candidate_ref"]),
        )
        return (
            {
                "schema_version": "alpha_frozen_novel_candidate_universe_v2",
                **common,
                "candidates": members,
            },
            members,
        )
    tool_id = _decision_authority_tool_id(agent_id)
    common = {"source_tool_id": tool_id, **common}
    if agent_id == "cro":
        candidates_view = sorted(
            [
                {
                    "candidate_ref": row.get("candidate_ref"),
                    "ts_code": row.get("ts_code"),
                    "proposed_target_weight": row.get(
                        "proposed_target_weight"
                    ),
                }
                for row in candidates
            ],
            key=lambda row: str(row["candidate_ref"]),
        )
        members = [
            {
                "risk_candidate_id": row["candidate_ref"],
                "ts_code": row["ts_code"],
                "proposed_target_weight": row["proposed_target_weight"],
            }
            for row in candidates_view
        ]
        return (
            {
                "schema_version": "cro_frozen_candidate_universe_v2",
                **common,
                "candidates": candidates_view,
            },
            members,
        )
    if agent_id == "autonomous_execution":
        intents: list[dict[str, Any]] = []
        for row in candidates:
            delta = row.get("requested_delta_weight")
            target = row.get("target_weight")
            if (
                isinstance(delta, bool)
                or not isinstance(delta, (int, float))
                or isinstance(target, bool)
                or not isinstance(target, (int, float))
            ):
                raise ValueError("Execution runtime authority weights are invalid")
            if abs(float(delta)) <= 1e-9:
                continue
            intents.append(
                {
                    "order_intent_ref": row.get("order_intent_ref"),
                    "ts_code": row.get("ts_code"),
                    "action": (
                        "BUY"
                        if float(delta) > 0
                        else "SELL"
                        if float(target) <= 1e-9
                        else "REDUCE"
                    ),
                    "requested_delta_weight": float(delta),
                }
            )
        intents.sort(key=lambda row: str(row["order_intent_ref"]))
        members = [
            {
                "order_intent_id": row["order_intent_ref"],
                "ts_code": row["ts_code"],
                "action": row["action"],
                "requested_delta_weight": row["requested_delta_weight"],
            }
            for row in intents
        ]
        return (
            {
                "schema_version": "execution_frozen_order_intent_set_v2",
                **common,
                "intents": intents,
            },
            members,
        )
    positions = sorted(
        [
            {
                "position_ref": row.get("proposal_position_ref"),
                "ts_code": row.get("ts_code"),
                "baseline_weight": row.get("current_weight"),
                "controlled_target_weight": row.get("proposed_target_weight"),
            }
            for row in candidates
        ],
        key=lambda row: str(row["ts_code"]),
    )
    if any(
        isinstance(row["baseline_weight"], bool)
        or not isinstance(row["baseline_weight"], (int, float))
        for row in positions
    ):
        raise ValueError("CIO runtime baseline weights are invalid")
    baseline_cash = 1.0 - sum(float(row["baseline_weight"]) for row in positions)
    if not -1e-9 <= baseline_cash <= 1 + 1e-9:
        raise ValueError("CIO runtime baseline weights are invalid")
    context = {
        "controlled_target_set_id": authority.get("candidate_universe_id"),
        "baseline_cash_weight": max(0.0, baseline_cash),
        "positions": positions,
    }
    return (
        {
            "schema_version": "decision.frozen_portfolio_context.v2",
            **common,
            "portfolio_context": context,
        },
        [context],
    )


def _decision_authority_tool_id(agent_id: str) -> str:
    return {
        "alpha_discovery": "get_alpha_candidate_snapshot",
        "cro": "get_cro_risk_snapshot",
        "autonomous_execution": "get_execution_snapshot",
        "cio": "get_cio_decision_snapshot",
    }[agent_id]


def _decision_runtime_authority_binding(
    agent_id: str,
    authority: Mapping[str, Any] | None,
) -> dict[str, str]:
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    if authority is None:
        raise ValueError(f"{agent_id} runtime candidate authority is unavailable")
    binding: dict[str, Any] = {
        "source_tool_id": _decision_authority_tool_id(agent_id),
        "source_snapshot_hash": authority.get("snapshot_hash"),
        "candidate_scope_hash": authority.get("candidate_scope_hash"),
        "candidate_universe_hash": authority.get("candidate_universe_hash"),
        "upstream_accepted_output_refs_hash": canonical_hash(
            authority.get("upstream_accepted_output_refs")
        ),
    }
    for field in (
        "source_snapshot_hash",
        "candidate_scope_hash",
        "candidate_universe_hash",
        "upstream_accepted_output_refs_hash",
    ):
        value = binding[field]
        if not (
            isinstance(value, str)
            and len(value) == 71
            and value.startswith("sha256:")
            and all(character in "0123456789abcdef" for character in value[7:])
        ):
            raise ValueError(f"{agent_id} runtime authority {field} is invalid")
    return {key: str(value) for key, value in binding.items()}


def _assert_server_owned_decision_control_sources(
    store: Any,
    *,
    agent_id: str,
    runtime_authority: Mapping[str, Any],
    graph_run_id: str,
) -> None:
    """Resolve stage-skip controls from Scorecard, never from request data."""
    role_context = runtime_authority.get("role_context")
    if not isinstance(role_context, Mapping):
        raise ValueError("Decision runtime authority role context is invalid")
    required_sources = {
        "alpha_discovery": (),
        "cro": (),
        "autonomous_execution": (
            ("cro_control_source", "cro", "CRO_RISK_REVIEW"),
        ),
        "cio": (
            ("cro_control_source", "cro", "CRO_RISK_REVIEW"),
            (
                "execution_control_source",
                "autonomous_execution",
                "EXECUTION_ASSESSMENT",
            ),
        ),
    }.get(agent_id)
    if required_sources is None:
        raise ValueError("Decision runtime authority Agent is invalid")
    expected_fields = {
        "source_status",
        "agent_id",
        "accepted_output_kind",
        "accepted_output_id",
        "accepted_output_hash",
        "stage_skip_id",
        "stage_skip_hash",
    }
    for field, owner, accepted_kind in required_sources:
        source = role_context.get(field)
        if not isinstance(source, Mapping):
            raise ValueError(f"{owner} runtime control source is missing")
        if (
            set(source) != expected_fields
            or source.get("agent_id") != owner
            or source.get("accepted_output_kind") != accepted_kind
        ):
            raise ValueError(f"{owner} runtime control source identity mismatch")
        persisted = store.resolve_no_evaluation_object_stage_skip(
            graph_run_id=graph_run_id,
            agent_id=owner,
        )
        if source.get("source_status") == "NO_EVALUATION_OBJECT":
            if persisted is None:
                raise ValueError(
                    f"{owner} runtime control stage skip is not persisted"
                )
            expected = {
                "source_status": "NO_EVALUATION_OBJECT",
                "agent_id": owner,
                "accepted_output_kind": accepted_kind,
                "accepted_output_id": None,
                "accepted_output_hash": None,
                "stage_skip_id": persisted["stage_skip_id"],
                "stage_skip_hash": persisted["stage_skip_hash"],
            }
            if dict(source) != expected:
                raise ValueError(
                    f"{owner} runtime control stage-skip binding mismatch"
                )
        elif source.get("source_status") == "ACCEPTED_OUTPUT":
            if persisted is not None:
                raise ValueError(
                    f"{owner} runtime accepted control source masks a persisted stage skip"
                )
            accepted_id = source.get("accepted_output_id")
            accepted_hash = source.get("accepted_output_hash")
            if (
                not isinstance(accepted_id, str)
                or not accepted_id
                or not isinstance(accepted_hash, str)
                or len(accepted_hash) != 71
                or not accepted_hash.startswith("sha256:")
                or any(
                    character not in "0123456789abcdef"
                    for character in accepted_hash[7:]
                )
                or source.get("stage_skip_id") is not None
                or source.get("stage_skip_hash") is not None
            ):
                raise ValueError(
                    f"{owner} runtime accepted control source binding mismatch"
                )
        else:
            raise ValueError(f"{owner} runtime control source status is invalid")


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
    """Freeze only the run plan; every opportunity is a live-stage decision."""
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
        from mosaic.dataflows.outcome_runtime_inputs import load_verified_event_coverage

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
        return {
            "outcome_schedule_plan": plan,
            "scheduled_opportunity_decisions": [],
            "stage_skips": {},
            "run_blockers": [],
            "trading_calendar_snapshot_hash": calendar["snapshot_hash"],
            "event_candidate_input_hash": plan["event_candidate_input_hash"],
            "deferred_opportunity_agent_ids": sorted(
                _DEFERRED_RUNTIME_OPPORTUNITY_AGENTS
            ),
        }
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.freeze_outcome_opportunity")
def darwinian_freeze_outcome_opportunity(params: dict[str, Any]) -> dict[str, Any]:
    """Freeze one exact L1/L2 source domain immediately before its Agent runs."""
    if set(params) & {
        "member_refs",
        "source_evidence_by_required_source_id",
        "runtime_authority_binding",
    }:
        raise RpcError(
            INVALID_PARAMS,
            "live opportunity denominator and source authority are server-owned",
        )
    _reject_unknown_params(
        params,
        {
            "outcome_schedule_plan_id",
            "scheduled_sample_id",
            "agent_id",
        },
    )
    plan_id = _require_str(params, "outcome_schedule_plan_id")
    scheduled_sample_id = _require_str(params, "scheduled_sample_id")
    agent_id = _require_choice(
        params,
        "agent_id",
        _LIVE_L1_L2_OPPORTUNITY_AGENTS,
    )
    try:
        from mosaic.dataflows.exceptions import DataVendorUnavailable
        from mosaic.dataflows.outcome_runtime_inputs import (
            load_evaluation_opportunity_projection,
        )
        from mosaic.scorecard.darwinian_v2 import canonical_hash
        from mosaic.scorecard.opportunity_authority import (
            assert_authoritative_member_match,
            materialize_pre_run_authority,
        )

        store = _store()
        context = store.resolve_scheduled_sample_context(
            scheduled_sample_id=scheduled_sample_id
        )
        for field, expected in (
            ("agent_id", agent_id),
            ("outcome_schedule_plan_id", plan_id),
        ):
            if context.get(field) != expected:
                raise ValueError(f"live opportunity schedule {field} mismatch")
        projection = load_evaluation_opportunity_projection(
            str(context["as_of"]), agent_id
        )
        attempted_at = _server_now()
        if projection["projection_status"] != "AVAILABLE":
            decision = store.record_scheduled_outcome_opportunity_failure(
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                qualification_predicate_version=projection[
                    "qualification_predicate_version"
                ],
                source_evidence_by_required_source_id=projection[
                    "source_evidence_by_required_source_id"
                ],
                error_codes=projection["error_codes"],
                attempted_at=attempted_at,
            )
            return {
                **decision,
                "run_allowed": False,
                "blocker_reason": "OPPORTUNITY_SET_UNAVAILABLE",
            }
        try:
            authority = materialize_pre_run_authority(
                agent_id=agent_id,
                as_of=str(context["as_of"]),
                graph_run_id=str(context["graph_run_id"]),
                schedule_slot=context,
            )
        except DataVendorUnavailable:
            return _record_stage_authority_failure(
                store=store,
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                projection=projection,
                attempted_at=attempted_at,
                error_code="REQUIRED_DATA_UNAVAILABLE",
                blocker_reason="SOURCE_AUTHORITY_UNAVAILABLE",
            )
        try:
            assert_authoritative_member_match(
                agent_id=agent_id,
                projected_members=projection["member_refs"],
                authoritative_members=authority["member_refs"],
            )
        except ValueError:
            return _record_stage_authority_failure(
                store=store,
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                projection=projection,
                attempted_at=attempted_at,
                error_code="CONTRACT_MISMATCH",
                blocker_reason="SOURCE_AUTHORITY_MISMATCH",
            )
        runtime_authority = authority["runtime_authority_binding"]
        generator_hash = canonical_hash(
            {
                "projection_snapshot_hash": projection["snapshot_hash"],
                "source_domain_hash": runtime_authority["domain_hash"],
            }
        )
        decision = store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan_id,
            agent_id=agent_id,
            qualification_predicate_version=projection[
                "qualification_predicate_version"
            ],
            member_refs=authority["member_refs"],
            source_evidence_by_required_source_id=projection[
                "source_evidence_by_required_source_id"
            ],
            projection_snapshot_hash=generator_hash,
            runtime_authority_binding=runtime_authority,
        )
        return {
            **decision,
            "runtime_authority_binding": runtime_authority,
        }
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.freeze_stage_outcome_opportunity")
def darwinian_freeze_stage_outcome_opportunity(
    params: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the exact Decision-stage universe immediately before its Agent call."""
    _reject_unknown_params(
        params,
        {
            "outcome_schedule_plan_id",
            "scheduled_sample_id",
            "agent_id",
            "recorded_at",
            "frozen_object",
        },
    )
    plan_id = _require_str(params, "outcome_schedule_plan_id")
    scheduled_sample_id = _require_str(params, "scheduled_sample_id")
    agent_id = _require_choice(
        params,
        "agent_id",
        _DEFERRED_DECISION_OPPORTUNITY_AGENTS,
    )
    recorded_at = _require_str(params, "recorded_at")
    try:
        from mosaic.dataflows.outcome_runtime_inputs import (
            load_evaluation_opportunity_projection,
        )
        from mosaic.dataflows.exceptions import DataVendorUnavailable
        from mosaic.scorecard.darwinian_v2 import canonical_hash

        store = _store()
        context = store.resolve_scheduled_sample_context(
            scheduled_sample_id=scheduled_sample_id
        )
        for field, expected in (
            ("agent_id", agent_id),
            ("outcome_schedule_plan_id", plan_id),
        ):
            if context.get(field) != expected:
                raise ValueError(f"Decision stage schedule {field} mismatch")
        projection = load_evaluation_opportunity_projection(
            str(context["as_of"]), agent_id
        )
        if projection["projection_status"] != "AVAILABLE":
            decision = store.record_scheduled_outcome_opportunity_failure(
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                qualification_predicate_version=projection[
                    "qualification_predicate_version"
                ],
                source_evidence_by_required_source_id=projection[
                    "source_evidence_by_required_source_id"
                ],
                error_codes=projection["error_codes"],
                attempted_at=recorded_at,
            )
            return {
                **decision,
                "run_allowed": False,
                "blocker_reason": "OPPORTUNITY_SET_UNAVAILABLE",
            }
        if projection.get("member_refs") != []:
            raise ValueError(
                "Decision pre-run projection may provide readiness evidence only"
            )
        supplied = params.get("frozen_object")
        if supplied is None:
            raise ValueError(f"{agent_id} requires a runtime frozen object")
        if not isinstance(supplied, Mapping):
            raise ValueError("frozen_object must be an object")
        from mosaic.bridge.tool_capabilities import materialize_tool_payload

        object_payload = supplied.get("object_payload")
        if not isinstance(object_payload, Mapping):
            raise ValueError("Decision frozen object payload is invalid")
        authority_stage = "cio_final" if agent_id == "cio" else agent_id
        try:
            rendered = materialize_tool_payload(
                _decision_authority_tool_id(agent_id),
                agent_id=agent_id,
                stage=authority_stage,
                as_of=str(context["as_of"])[:10],
                graph_run_id=str(context["graph_run_id"]),
                accepted_output_refs=object_payload.get(
                    "upstream_accepted_output_refs"
                ),
            )
            if not isinstance(rendered, str):
                raise ValueError(
                    "Decision runtime authority must be rendered as JSON text"
                )
            runtime_authority = json.loads(rendered)
            if not isinstance(runtime_authority, Mapping):
                raise ValueError("Decision runtime authority must be an object")
            _assert_server_owned_decision_control_sources(
                store,
                agent_id=agent_id,
                runtime_authority=runtime_authority,
                graph_run_id=str(context["graph_run_id"]),
            )
        except DataVendorUnavailable:
            return _record_stage_authority_failure(
                store=store,
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                projection=projection,
                attempted_at=recorded_at,
                error_code="REQUIRED_DATA_UNAVAILABLE",
                blocker_reason="SOURCE_AUTHORITY_UNAVAILABLE",
            )
        except ValueError:
            return _record_stage_authority_failure(
                store=store,
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                projection=projection,
                attempted_at=recorded_at,
                error_code="CONTRACT_MISMATCH",
                blocker_reason="SOURCE_AUTHORITY_MISMATCH",
            )
        frozen_id, frozen_hash, members, authority_binding = (
            _decision_stage_frozen_object(
                agent_id,
                supplied,
                runtime_authority=runtime_authority,
            )
        )
        generator_hash = canonical_hash(
            {
                "projection_snapshot_hash": projection["snapshot_hash"],
                "frozen_object_set_hash": frozen_hash,
                "runtime_authority_binding": authority_binding,
            }
        )
        decision = store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan_id,
            agent_id=agent_id,
            qualification_predicate_version=projection[
                "qualification_predicate_version"
            ],
            member_refs=members,
            source_evidence_by_required_source_id=projection[
                "source_evidence_by_required_source_id"
            ],
            projection_snapshot_hash=generator_hash,
            frozen_object_set_id=frozen_id,
            frozen_object_set_hash=frozen_hash,
            runtime_authority_binding=authority_binding,
        )
        if not members:
            skipped = store.create_no_evaluation_object_stage_skip(
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                recorded_at=recorded_at,
            )
            return {
                **decision,
                **skipped,
                "runtime_authority_binding": authority_binding,
                "frozen_object": dict(supplied),
            }
        return {
            **decision,
            "runtime_authority_binding": authority_binding,
            "frozen_object": dict(supplied),
        }
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.freeze_superinvestor_outcome_opportunity")
def darwinian_freeze_superinvestor_outcome_opportunity(
    params: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the exact L2-derived candidate set before one L3 model call."""
    _reject_unknown_params(
        params,
        {
            "outcome_schedule_plan_id",
            "scheduled_sample_id",
            "agent_id",
            "recorded_at",
            "accepted_output_refs",
        },
    )
    plan_id = _require_str(params, "outcome_schedule_plan_id")
    scheduled_sample_id = _require_str(params, "scheduled_sample_id")
    agent_id = _require_choice(
        params,
        "agent_id",
        _DEFERRED_SUPERINVESTOR_OPPORTUNITY_AGENTS,
    )
    recorded_at = _require_str(params, "recorded_at")
    accepted_output_refs = params.get("accepted_output_refs")
    if not isinstance(accepted_output_refs, list) or not accepted_output_refs:
        raise RpcError(
            INVALID_PARAMS,
            "'accepted_output_refs' must be a non-empty array",
        )
    try:
        from mosaic.dataflows.outcome_runtime_inputs import (
            load_evaluation_opportunity_projection,
        )
        from mosaic.dataflows.exceptions import DataVendorUnavailable
        from mosaic.scorecard.darwinian_v2 import canonical_hash
        from mosaic.scorecard.opportunity_authority import (
            materialize_superinvestor_authority,
        )

        store = _store()
        context = store.resolve_scheduled_sample_context(
            scheduled_sample_id=scheduled_sample_id
        )
        for field, expected in (
            ("agent_id", agent_id),
            ("outcome_schedule_plan_id", plan_id),
            ("prepared_at", recorded_at),
        ):
            if context.get(field) != expected:
                raise ValueError(f"Superinvestor stage schedule {field} mismatch")
        projection = load_evaluation_opportunity_projection(
            str(context["as_of"]), agent_id
        )
        if projection["projection_status"] != "AVAILABLE":
            decision = store.record_scheduled_outcome_opportunity_failure(
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                qualification_predicate_version=projection[
                    "qualification_predicate_version"
                ],
                source_evidence_by_required_source_id=projection[
                    "source_evidence_by_required_source_id"
                ],
                error_codes=projection["error_codes"],
                attempted_at=recorded_at,
            )
            return {
                **decision,
                "run_allowed": False,
                "blocker_reason": "OPPORTUNITY_SET_UNAVAILABLE",
            }
        if projection.get("member_refs") != []:
            raise ValueError(
                "Superinvestor pre-run projection may provide readiness evidence only"
            )
        try:
            authority = materialize_superinvestor_authority(
                agent_id=agent_id,
                as_of=str(context["as_of"]),
                graph_run_id=str(context["graph_run_id"]),
                accepted_output_refs=accepted_output_refs,
            )
            if not isinstance(authority, Mapping):
                raise ValueError(
                    "Superinvestor runtime authority must be an object"
                )
        except DataVendorUnavailable:
            return _record_stage_authority_failure(
                store=store,
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                projection=projection,
                attempted_at=recorded_at,
                error_code="REQUIRED_DATA_UNAVAILABLE",
                blocker_reason="SOURCE_AUTHORITY_UNAVAILABLE",
            )
        except ValueError:
            return _record_stage_authority_failure(
                store=store,
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                projection=projection,
                attempted_at=recorded_at,
                error_code="CONTRACT_MISMATCH",
                blocker_reason="SOURCE_AUTHORITY_MISMATCH",
            )
        generator_hash = canonical_hash(
            {
                "projection_snapshot_hash": projection["snapshot_hash"],
                "source_authority_hash": authority["authority_hash"],
            }
        )
        decision = store.freeze_scheduled_outcome_opportunity(
            outcome_schedule_plan_id=plan_id,
            agent_id=agent_id,
            qualification_predicate_version=projection[
                "qualification_predicate_version"
            ],
            member_refs=authority["member_refs"],
            source_evidence_by_required_source_id=projection[
                "source_evidence_by_required_source_id"
            ],
            projection_snapshot_hash=generator_hash,
            frozen_object_set_id=authority["candidate_universe_id"],
            frozen_object_set_hash=authority["candidate_universe_hash"],
        )
        pins = {
            "runtime_candidate_scope_hash": authority[
                "candidate_scope_hash"
            ],
            "runtime_candidate_universe_hash": authority[
                "candidate_universe_hash"
            ],
            "runtime_source_snapshot_hash": authority[
                "source_snapshot_hash"
            ],
        }
        if not authority["member_refs"]:
            skipped = store.create_no_evaluation_object_stage_skip(
                outcome_schedule_plan_id=plan_id,
                agent_id=agent_id,
                recorded_at=recorded_at,
            )
            return {**decision, **skipped, **pins}
        return {**decision, **pins}
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


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


def _run_v2_outcome_update(
    *,
    production_variant_roster_revision_id: str,
    cutoff_at: str,
    operation: str,
) -> dict[str, Any]:
    """Mature due outcomes before refreshing or publishing Darwinian state."""
    from mosaic.scorecard.darwinian_updates import (
        materialize_due_outcomes,
        publish_usage_weight_updates,
        refresh_evaluation_windows,
    )

    trading_dates = _verified_darwinian_trading_dates(cutoff_at)
    store = _store()
    with store._connect() as conn:
        maturation = materialize_due_outcomes(
            conn,
            production_variant_roster_revision_id=(
                production_variant_roster_revision_id
            ),
            cutoff_at=cutoff_at,
            trading_dates=trading_dates,
        )
        if operation == "MATERIALIZE":
            return {"outcome_maturation": maturation}
        if operation == "REFRESH":
            rows = refresh_evaluation_windows(
                conn,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                cutoff_at=cutoff_at,
                trading_dates=trading_dates,
            )
            return {
                "outcome_maturation": maturation,
                "evaluation_windows": rows,
            }
        if operation == "PUBLISH":
            if maturation["unresolved_count"]:
                return {
                    "outcome_maturation": maturation,
                    "published_batches": [],
                    "publication_status": "BLOCKED_UNRESOLVED_DUE_OUTCOMES",
                }
            rows = publish_usage_weight_updates(
                conn,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                cutoff_at=cutoff_at,
                trading_dates=trading_dates,
            )
            return {
                "outcome_maturation": maturation,
                "published_batches": rows,
                "publication_status": "PUBLISHED",
            }
    raise ValueError(f"unsupported Darwinian outcome update operation: {operation}")


@method("darwinian.materialize_due_outcomes")
def darwinian_materialize_due_outcomes(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {"production_variant_roster_revision_id", "cutoff_at"},
    )
    try:
        return _run_v2_outcome_update(
            production_variant_roster_revision_id=_require_str(
                params, "production_variant_roster_revision_id"
            ),
            cutoff_at=_require_str(params, "cutoff_at"),
            operation="MATERIALIZE",
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc


@method("darwinian.refresh_v2_windows")
def darwinian_refresh_v2_windows(params: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_params(
        params,
        {"production_variant_roster_revision_id", "cutoff_at"},
    )
    revision_id = _require_str(params, "production_variant_roster_revision_id")
    cutoff_at = _require_str(params, "cutoff_at")
    try:
        return _run_v2_outcome_update(
            production_variant_roster_revision_id=revision_id,
            cutoff_at=cutoff_at,
            operation="REFRESH",
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
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
        return _run_v2_outcome_update(
            production_variant_roster_revision_id=revision_id,
            cutoff_at=cutoff_at,
            operation="PUBLISH",
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
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
