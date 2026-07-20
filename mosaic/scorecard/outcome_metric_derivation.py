"""Deterministic outcome metrics derived from sealed forecasts and realized-only data."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS


_DIRECTION_SIGN = {"SUPPORTIVE": 1.0, "NEUTRAL": 0.0, "ADVERSE": -1.0}
_EDGE_SIGN = {"POSITIVE": 1.0, "NEGATIVE": -1.0, "MIXED": 0.0}
_EDGE_REALIZED_SIGN = {
    "NO_ACTIVATION": 0.0,
    "POSITIVE": 1.0,
    "NEGATIVE": -1.0,
    "MIXED": 0.0,
}
_ALPHA_CONFIDENCE_SKILL_FINAL_WEIGHT = 0.10
_DECISION_COMPONENTS: dict[str, tuple[tuple[str, float], ...]] = {
    "CRO": (
        ("PRECISION", 0.35),
        ("RECALL", 0.35),
        ("SPECIFICITY", 0.20),
        ("CALIBRATION", 0.10),
    ),
    "ALPHA": (
        ("SELECTED_PICK_UTILITY", 0.70),
        ("INCREMENTAL_OPPORTUNITY_UTILITY", 0.30),
    ),
    "EXECUTION": (
        ("COST_ERROR", 0.40),
        ("FEASIBILITY", 0.30),
        ("TARGET_DELTA", 0.20),
        ("POLICY_COMPLIANCE", 0.10),
    ),
    "CIO": (
        ("RELATIVE_RETURN", 0.50),
        ("DRAWDOWN", 0.25),
        ("TURNOVER_COST", 0.15),
        ("CONSTRAINT_COMPLIANCE", 0.10),
    ),
}


def _record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _rows(value: Any, label: str, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or (not value and not allow_empty)
    ):
        suffix = "an array" if allow_empty else "a non-empty array"
        raise ValueError(f"{label} must be {suffix}")
    return [_record(row, f"{label}[{index}]") for index, row in enumerate(value)]


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    return value.strip()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _probability(value: Any, label: str) -> float:
    result = _number(value, label)
    if not 0 <= result <= 1:
        raise ValueError(f"{label} must be in [0, 1]")
    return result


def _clip(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _unique_by(
    rows: Sequence[Mapping[str, Any]],
    fields: tuple[str, ...],
    label: str,
) -> dict[tuple[str, ...], dict[str, Any]]:
    indexed: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        key = tuple(_text(row.get(field), f"{label}[{index}].{field}") for field in fields)
        if key in indexed:
            raise ValueError(f"{label} identities must be unique")
        indexed[key] = dict(row)
    return indexed


def _member_rows_by_id(
    member_refs: Sequence[Mapping[str, Any]],
    identity_field: str,
    *,
    required_fields: frozenset[str] | None = None,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, member in enumerate(member_refs):
        row = _record(member, f"member_refs[{index}]")
        if required_fields is not None and set(row) != required_fields:
            raise ValueError(
                f"member_refs[{index}] must contain exactly "
                + ", ".join(sorted(required_fields))
            )
        member_id = _text(
            row.get(identity_field), f"member_refs[{index}].{identity_field}"
        )
        if member_id in indexed:
            raise ValueError("opportunity member identities must be unique")
        indexed[member_id] = row
    return indexed


def _require_exact_member_coverage(
    expected: set[str],
    observed: set[str],
    *,
    label: str,
) -> None:
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(f"{label} must exactly equal the frozen opportunity members: " + "; ".join(details))


def _exact_text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    result = [_text(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must contain unique values")
    return result


def _decision_component(
    component_id: str,
    weight: float,
    output_value: float,
    null_value: float,
    *,
    direction: str,
    unit: str,
    zero_rule: str = "NOT_APPLICABLE",
    scale: float = 1.0,
) -> dict[str, Any]:
    if scale <= 0:
        raise ValueError("decision component scale must be positive")
    if direction == "HIGHER_IS_BETTER":
        output_utility = output_value / scale
        null_utility = null_value / scale
    elif direction == "LOWER_IS_BETTER":
        output_utility = -output_value / scale
        null_utility = -null_value / scale
    else:
        raise ValueError("unknown decision component direction")
    return {
        "component_id": component_id,
        "component_weight": weight,
        "unit": unit,
        "direction": direction,
        "unclipped_output_value": output_value,
        "unclipped_null_value": null_value,
        "scale": scale,
        "output_utility": output_utility,
        "null_utility": null_utility,
        "utility_delta": output_utility - null_utility,
        "denominator_zero_rule_id": zero_rule,
    }


def _with_decision_totals(
    family: str,
    components: Sequence[Mapping[str, Any]],
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _DECISION_COMPONENTS[family]
    if len(components) != len(expected):
        raise ValueError(f"{family} component cardinality drift")
    output = 0.0
    null = 0.0
    for component, (component_id, weight) in zip(components, expected, strict=True):
        if component.get("component_id") != component_id:
            raise ValueError(f"{family} component order drift")
        output += weight * _number(component.get("output_utility"), "output_utility")
        null += weight * _number(component.get("null_utility"), "null_utility")
    return {
        "combined_output_utility": output,
        "combined_null_utility": null,
        "combined_utility_delta": output - null,
        "components": [dict(component) for component in components],
        **dict(fields),
    }


def derive_authoritative_outcome_metrics(
    *,
    agent_id: str,
    accepted_payload: Mapping[str, Any],
    opportunity_member_refs: Sequence[Mapping[str, Any]],
    realized_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive every forecast and utility input from immutable public authorities."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    payload = _record(accepted_payload, "accepted output payload")
    realized = _record(realized_metrics, "realized metrics")
    family = str(contract["metric_family"])
    if family == "MACRO_TRANSMISSION":
        return _macro_metrics(agent_id, payload, realized)
    if family == "STANDARD_SECTOR":
        return _sector_metrics(agent_id, payload, opportunity_member_refs, realized)
    if family == "RELATIONSHIP":
        return _relationship_metrics(agent_id, payload, opportunity_member_refs, realized)
    if family == "SUPERINVESTOR":
        return _superinvestor_metrics(agent_id, payload, opportunity_member_refs, realized)
    if family == "CRO":
        return _cro_metrics(agent_id, payload, opportunity_member_refs, realized)
    if family == "ALPHA":
        return _alpha_metrics(agent_id, payload, opportunity_member_refs, realized)
    if family == "EXECUTION":
        return _execution_metrics(agent_id, payload, opportunity_member_refs, realized)
    if family == "CIO":
        return _cio_metrics(agent_id, payload, opportunity_member_refs, realized)
    raise ValueError(f"unsupported metric family: {family}")


def _macro_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("agent_id") != agent_id:
        raise ValueError("accepted Macro payload owner mismatch")
    direction = payload.get("direction")
    if direction not in _DIRECTION_SIGN:
        raise ValueError("accepted Macro direction is invalid")
    strength = _number(payload.get("strength"), "accepted Macro strength")
    if strength not in {0, 1, 2, 3, 4, 5}:
        raise ValueError("accepted Macro strength is invalid")
    if (direction == "NEUTRAL") != (strength == 0):
        raise ValueError("accepted Macro neutral/strength semantics drift")
    return {
        "direction_sign": _DIRECTION_SIGN[str(direction)],
        "strength": strength,
        "confidence": _probability(payload.get("confidence"), "accepted Macro confidence"),
        "role_path_metric": _number(realized.get("role_path_metric"), "role_path_metric"),
        "pit_volatility_scale": _number(
            realized.get("pit_volatility_scale"), "pit_volatility_scale"
        ),
    }


def _sector_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("sector_agent_id") != agent_id:
        raise ValueError("accepted Sector payload owner mismatch")
    selection = _record(payload.get("selection"), "accepted Sector selection")
    preferred = _record(selection.get("preferred_direction"), "preferred_direction")
    least = _record(selection.get("least_preferred_direction"), "least_preferred_direction")
    preferred_id = _text(preferred.get("direction_id"), "preferred direction_id")
    least_id = _text(least.get("direction_id"), "least-preferred direction_id")
    if preferred_id == least_id:
        raise ValueError("accepted Sector directions must differ")
    confidence = _probability(
        payload.get("directional_confidence"), "Sector directional_confidence"
    )
    member_by_direction = _member_rows_by_id(
        member_refs,
        "subindustry_id",
        required_fields=frozenset(
            {
                "subindustry_id",
                "security_shortlist_id",
                "security_shortlist_hash",
                "security_ts_codes",
            }
        ),
    )
    security_tickers_by_direction: dict[str, list[str]] = {}
    for direction_id, member in member_by_direction.items():
        _text(
            member.get("security_shortlist_id"),
            f"Sector member {direction_id} security_shortlist_id",
        )
        _text(
            member.get("security_shortlist_hash"),
            f"Sector member {direction_id} security_shortlist_hash",
        )
        security_tickers_by_direction[direction_id] = _exact_text_list(
            member.get("security_ts_codes"),
            f"Sector member {direction_id} security_ts_codes",
        )
    direction_paths = _rows(realized.get("direction_paths"), "direction_paths")
    direction_by_id = _unique_by(direction_paths, ("direction_id",), "direction_paths")
    if (preferred_id,) not in direction_by_id or (least_id,) not in direction_by_id:
        raise ValueError("realized Sector paths must cover both accepted directions")
    _require_exact_member_coverage(
        set(member_by_direction),
        {key[0] for key in direction_by_id},
        label="realized Sector directions",
    )

    direction_metrics: list[dict[str, Any]] = []
    direction_losses: list[float] = []
    direction_null_losses: list[float] = []
    unit_direction_losses: list[float] = []
    for row in direction_paths:
        direction_id = _text(row.get("direction_id"), "direction_id")
        if direction_id == preferred_id:
            role = "PREFERRED"
            sign = 1.0
            strength = _number(preferred.get("strength"), "preferred strength") / 5.0
        elif direction_id == least_id:
            role = "LEAST_PREFERRED"
            sign = -1.0
            strength = _number(least.get("strength"), "least-preferred strength") / 5.0
        else:
            role = "UNSELECTED"
            sign = 0.0
            strength = 0.0
        actual = _number(row.get("realized_scaled_path"), "realized_scaled_path")
        prediction = sign * strength * confidence
        unit_prediction = sign * strength
        direction_losses.append((prediction - actual) ** 2)
        unit_direction_losses.append((unit_prediction - actual) ** 2)
        direction_null_losses.append(actual**2)
        direction_metrics.append(
            {
                "direction_id": direction_id,
                "realized_return_5d": _number(
                    row.get("realized_return_5d"), "realized_return_5d"
                ),
                "parent_sector_return_5d": _number(
                    row.get("parent_sector_return_5d"), "parent_sector_return_5d"
                ),
                "realized_scaled_path": actual,
                "predicted_tilt": prediction,
                "selected_role": role,
            }
        )

    side_contracts = (
        (
            "PREFERRED",
            preferred_id,
            "preferred_security_status",
            "long_picks",
            "preferred_security_shortlist_id",
            "preferred_security_shortlist_hash",
        ),
        (
            "LEAST_PREFERRED",
            least_id,
            "least_preferred_security_status",
            "short_or_avoid_picks",
            "least_preferred_security_shortlist_id",
            "least_preferred_security_shortlist_hash",
        ),
    )
    security_paths = _rows(
        realized.get("security_paths"), "security_paths", allow_empty=True
    )
    _unique_by(security_paths, ("side", "ts_code"), "security_paths")
    expected_security_keys: set[tuple[str, str]] = set()
    for side, direction_id, _, _, shortlist_id_field, shortlist_hash_field in side_contracts:
        member = member_by_direction.get(direction_id)
        if member is None:
            raise ValueError("accepted Sector direction is outside the frozen opportunity")
        if payload.get(shortlist_id_field) != member["security_shortlist_id"]:
            raise ValueError("accepted Sector shortlist identity drift")
        if payload.get(shortlist_hash_field) != member["security_shortlist_hash"]:
            raise ValueError("accepted Sector shortlist hash drift")
        expected_security_keys.update(
            (side, ticker) for ticker in security_tickers_by_direction[direction_id]
        )
    observed_security_keys = {
        (
            _text(row.get("side"), "security path side"),
            _text(row.get("ts_code"), "security path ts_code"),
        )
        for row in security_paths
    }
    missing_security = sorted(expected_security_keys - observed_security_keys)
    unexpected_security = sorted(observed_security_keys - expected_security_keys)
    if missing_security or unexpected_security:
        details: list[str] = []
        if missing_security:
            details.append(f"missing {missing_security!r}")
        if unexpected_security:
            details.append(f"unexpected {unexpected_security!r}")
        raise ValueError(
            "realized Sector security paths must exactly equal the frozen shortlists: "
            + "; ".join(details)
        )
    security_metrics: list[dict[str, Any]] = []
    security_leg_metrics: list[dict[str, Any]] = []
    security_leg_forecast_losses: list[float] = []
    security_leg_null_losses: list[float] = []
    unit_security_leg_losses: list[float] = []
    for (
        side,
        direction_id,
        status_field,
        picks_field,
        _,
        _,
    ) in side_contracts:
        status = selection.get(status_field)
        picks = _rows(selection.get(picks_field), picks_field, allow_empty=True)
        picks_by_ticker = _unique_by(picks, ("ts_code",), picks_field)
        side_paths = [row for row in security_paths if row.get("side") == side]
        frozen_tickers = set(security_tickers_by_direction[direction_id])
        if status == "NO_QUALIFIED_SECURITY":
            if picks or frozen_tickers:
                raise ValueError(
                    "NO_QUALIFIED_SECURITY requires an empty frozen Sector shortlist"
                )
            raw_status = "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST"
        elif status == "PICKS_PRESENT":
            if not picks or not frozen_tickers:
                raise ValueError(
                    "accepted Sector PICKS_PRESENT requires picks and a non-empty frozen shortlist"
                )
            raw_status = "PICKS_PRESENT"
        else:
            raise ValueError("accepted Sector security status is invalid")
        path_tickers = {_text(row.get("ts_code"), "security path ts_code") for row in side_paths}
        if path_tickers != frozen_tickers:
            raise ValueError("realized Sector side does not match its frozen shortlist")
        if set(key[0] for key in picks_by_ticker) - frozen_tickers:
            raise ValueError("accepted Sector picks are outside the frozen shortlist")
        side_forecast_losses: list[float] = []
        side_null_losses: list[float] = []
        side_unit_losses: list[float] = []
        side_deltas: list[float] = []
        for row in side_paths:
            if row.get("direction_id") != direction_id:
                raise ValueError("Sector security path direction binding drift")
            ticker = _text(row.get("ts_code"), "security path ts_code")
            pick = picks_by_ticker.get((ticker,))
            actual = _number(row.get("realized_scaled_alpha"), "realized_scaled_alpha")
            if pick is None:
                action = "UNSELECTED"
                conviction = 0.0
                unit_prediction = 0.0
            else:
                action = pick.get("position_action")
                if action not in {"LONG", "SHORT", "AVOID"}:
                    raise ValueError("accepted Sector position_action is invalid")
                conviction = _probability(pick.get("conviction"), "Sector conviction")
                unit_prediction = conviction if action == "LONG" else -conviction
            prediction = unit_prediction * confidence
            forecast_loss = (prediction - actual) ** 2
            null_loss = actual**2
            side_forecast_losses.append(forecast_loss)
            side_null_losses.append(null_loss)
            side_unit_losses.append((unit_prediction - actual) ** 2)
            side_deltas.append(null_loss - forecast_loss)
            security_metrics.append(
                {
                    "side": side,
                    "direction_id": direction_id,
                    "ts_code": ticker,
                    "action": action,
                    "conviction": conviction,
                    "net_alpha_5d": _number(row.get("net_alpha_5d"), "net_alpha_5d"),
                    "realized_scaled_alpha": actual,
                    "predicted_position": prediction,
                }
            )
        security_leg_forecast_losses.append(_mean(side_forecast_losses))
        security_leg_null_losses.append(_mean(side_null_losses))
        unit_security_leg_losses.append(_mean(side_unit_losses))
        security_leg_metrics.append(
            {
                "side": side,
                "direction_id": direction_id,
                "security_status": raw_status,
                "shortlist_size": len(frozen_tickers),
                "side_security_utility_delta": _mean(side_deltas),
            }
        )

    direction_forecast = _mean(direction_losses)
    direction_null = _mean(direction_null_losses)
    security_forecast = _mean(security_leg_forecast_losses)
    security_null = _mean(security_leg_null_losses)
    direction_delta = direction_null - direction_forecast
    security_delta = security_null - security_forecast
    combined = 0.5 * direction_delta + 0.5 * security_delta
    unit_direction_delta = direction_null - _mean(unit_direction_losses)
    unit_security_delta = security_null - _mean(unit_security_leg_losses)
    unit_combined = 0.5 * unit_direction_delta + 0.5 * unit_security_delta
    return {
        "output_confidence": confidence,
        "confidence_semantics": "DIRECTIONAL_UTILITY",
        "direction_metrics": direction_metrics,
        "security_metrics": security_metrics,
        "security_leg_metrics": security_leg_metrics,
        "direction_forecast_loss": direction_forecast,
        "direction_null_loss": direction_null,
        "security_forecast_loss": security_forecast,
        "security_null_loss": security_null,
        "direction_utility_delta": direction_delta,
        "security_utility_delta": security_delta,
        "combined_utility_delta": combined,
        "unit_confidence_utility_delta": unit_combined,
        "confidence_calibration_target": int(unit_combined > 0),
    }


def _relationship_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("relationship_agent_id") != agent_id:
        raise ValueError("accepted Relationship payload owner mismatch")
    member_by_id = _member_rows_by_id(
        member_refs,
        "edge_candidate_id",
        required_fields=frozenset({"edge_candidate_id", "materiality_weight"}),
    )
    materiality_by_id: dict[str, float] = {}
    for edge_id, member in member_by_id.items():
        weight = _number(
            member.get("materiality_weight"),
            f"Relationship member {edge_id} materiality_weight",
        )
        if weight <= 0:
            raise ValueError("frozen Relationship materiality weights must be positive")
        materiality_by_id[edge_id] = weight
    edge_paths = _rows(realized.get("edge_paths"), "edge_paths")
    path_by_id = _unique_by(edge_paths, ("edge_candidate_id",), "edge_paths")
    _require_exact_member_coverage(
        set(member_by_id),
        {key[0] for key in path_by_id},
        label="realized Relationship edges",
    )
    predictive_edges = _rows(
        payload.get("predictive_edges"), "predictive_edges", allow_empty=True
    )
    submitted_by_id = _unique_by(
        predictive_edges, ("edge_candidate_id",), "predictive_edges"
    )
    if set(submitted_by_id) - set(path_by_id):
        raise ValueError("accepted Relationship edges are outside realized opportunity paths")
    status = payload.get("predictive_graph_status")
    if status == "EDGES_PRESENT" and not predictive_edges:
        raise ValueError("Relationship EDGES_PRESENT requires accepted predictive edges")
    if status == "NO_QUALIFIED_PREDICTIVE_EDGE" and predictive_edges:
        raise ValueError("empty Relationship graph cannot carry predictive edges")
    if status not in {"EDGES_PRESENT", "NO_QUALIFIED_PREDICTIVE_EDGE"}:
        raise ValueError("accepted Relationship graph status is invalid")

    edge_metrics: list[dict[str, Any]] = []
    for row in edge_paths:
        edge_id = _text(row.get("edge_candidate_id"), "edge_candidate_id")
        submitted = submitted_by_id.get((edge_id,))
        realized_state = row.get("realized_edge_state")
        if realized_state not in _EDGE_REALIZED_SIGN:
            raise ValueError("realized Relationship edge state is invalid")
        actual = _EDGE_REALIZED_SIGN[str(realized_state)]
        lift = _number(row.get("matched_non_edge_lift"), "matched_non_edge_lift")
        if submitted is None:
            submitted_direction = None
            confidence = 0.0
            forecast = 0.0
        else:
            submitted_direction = submitted.get("transmission_direction")
            if submitted_direction not in _EDGE_SIGN:
                raise ValueError("accepted Relationship direction is invalid")
            confidence = _probability(
                submitted.get("calibrated_confidence"),
                "Relationship calibrated_confidence",
            )
            forecast = _EDGE_SIGN[str(submitted_direction)] * confidence
        brier_skill = actual**2 - (forecast - actual) ** 2
        path_utility = forecast * _clip(lift)
        best_utility = abs(_clip(lift))
        missed = best_utility if submitted is None else 0.0
        edge_delta = 0.5 * brier_skill + 0.5 * path_utility - missed
        edge_metrics.append(
            {
                "edge_candidate_id": edge_id,
                "materiality_weight": materiality_by_id[edge_id],
                "realized_edge_state": realized_state,
                "matched_non_edge_lift": lift,
                "candidate_counterfactual_best_utility": best_utility,
                "activation_direction_brier_skill": brier_skill,
                "path_lift_utility_delta": path_utility,
                "missed_edge_regret": missed,
                "edge_utility_delta": edge_delta,
                "submitted": submitted is not None,
                "submitted_direction": submitted_direction,
                "submitted_model_confidence": confidence,
            }
        )
    total_materiality = sum(materiality_by_id.values())
    if status == "EDGES_PRESENT":
        combined = sum(
            row["materiality_weight"] * row["edge_utility_delta"]
            for row in edge_metrics
        ) / total_materiality
        abstention_fields: dict[str, Any] = {
            "weighted_edge_utility_delta": combined,
            "graph_abstention_forecast_probability": None,
            "graph_abstention_warranted_label": None,
            "graph_abstention_forecast_loss": None,
            "graph_abstention_null_loss": None,
            "graph_abstention_best_raw_opportunity_utility": None,
            "graph_abstention_cardinality_adjusted_utility": None,
            "graph_abstention_missed_opportunity_regret": None,
        }
    else:
        best = max(row["candidate_counterfactual_best_utility"] for row in edge_metrics)
        weighted_opportunity = sum(
            row["materiality_weight"]
            * row["candidate_counterfactual_best_utility"]
            for row in edge_metrics
        ) / total_materiality
        adjusted = weighted_opportunity / math.sqrt(len(edge_metrics))
        warranted = int(best <= 0)
        probability = _probability(
            payload.get("predictive_graph_abstention_confidence"),
            "Relationship abstention confidence",
        )
        forecast_loss = (probability - warranted) ** 2
        null_loss = (0.5 - warranted) ** 2
        regret = 0.0 if warranted else adjusted
        combined = null_loss - forecast_loss - regret
        abstention_fields = {
            "weighted_edge_utility_delta": None,
            "graph_abstention_forecast_probability": probability,
            "graph_abstention_warranted_label": warranted,
            "graph_abstention_forecast_loss": forecast_loss,
            "graph_abstention_null_loss": null_loss,
            "graph_abstention_best_raw_opportunity_utility": best,
            "graph_abstention_cardinality_adjusted_utility": adjusted,
            "graph_abstention_missed_opportunity_regret": regret,
        }
    return {
        "predictive_graph_status": status,
        "edge_metrics": edge_metrics,
        **abstention_fields,
        "combined_utility_delta": combined,
    }


def _superinvestor_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("superinvestor_agent_id") != agent_id:
        raise ValueError("accepted Superinvestor payload owner mismatch")
    selection = _record(payload.get("selection"), "Superinvestor selection")
    member_by_ref = _member_rows_by_id(
        member_refs,
        "candidate_ref",
        required_fields=frozenset({"candidate_ref", "ts_code"}),
    )
    ticker_by_ref = {
        candidate_ref: _text(
            member.get("ts_code"),
            f"Superinvestor member {candidate_ref} ts_code",
        )
        for candidate_ref, member in member_by_ref.items()
    }
    if len(set(ticker_by_ref.values())) != len(ticker_by_ref):
        raise ValueError("frozen Superinvestor candidate tickers must be unique")
    paths = _rows(realized.get("candidate_paths"), "candidate_paths")
    paths_by_ref = _unique_by(paths, ("candidate_ref",), "candidate_paths")
    _require_exact_member_coverage(
        set(member_by_ref),
        {key[0] for key in paths_by_ref},
        label="realized Superinvestor candidates",
    )
    for key, path in paths_by_ref.items():
        if _text(path.get("ts_code"), "candidate ts_code") != ticker_by_ref[key[0]]:
            raise ValueError("Superinvestor candidate_ref/ts_code binding drift")
    picks = _rows(selection.get("picks"), "Superinvestor picks", allow_empty=True)
    picks_by_ticker = _unique_by(picks, ("ts_code",), "Superinvestor picks")
    if set(key[0] for key in picks_by_ticker) - set(ticker_by_ref.values()):
        raise ValueError("accepted Superinvestor picks lack realized paths")
    status = selection.get("selection_status")
    if status == "SELECTED" and not picks:
        raise ValueError("selected Superinvestor output requires picks")
    if status == "NO_QUALIFIED_CANDIDATES" and picks:
        raise ValueError("empty Superinvestor output cannot carry picks")
    if status not in {"SELECTED", "NO_QUALIFIED_CANDIDATES"}:
        raise ValueError("accepted Superinvestor status is invalid")
    rows: list[dict[str, Any]] = []
    selected_utilities: list[float] = []
    missed_utilities: list[float] = []
    for path in paths:
        ticker = _text(path.get("ts_code"), "candidate ts_code")
        pick = picks_by_ticker.get((ticker,))
        actual_return = _number(
            path.get("realized_net_excess_return_21d"),
            "realized_net_excess_return_21d",
        )
        scaled = _clip(actual_return)
        if pick is None:
            selected = False
            side = "UNSELECTED"
            conviction = 0.0
            downside = 0.0
            utility = 0.0
            # The actionable null is a long opportunity. A negative unselected
            # return is not an opportunity the Agent should be penalized for missing.
            missed = max(0.0, scaled)
            missed_utilities.append(missed)
        else:
            selected = True
            action = pick.get("position_action")
            if action not in {"LONG", "AVOID"}:
                raise ValueError("accepted Superinvestor position_action is invalid")
            side = action
            conviction = _probability(pick.get("conviction"), "pick conviction")
            signed = scaled if action == "LONG" else -scaled
            downside = max(0.0, -signed)
            utility = conviction * signed - downside
            missed = 0.0
            selected_utilities.append(utility)
        rows.append(
            {
                "candidate_ref": _text(path.get("candidate_ref"), "candidate_ref"),
                "ts_code": ticker,
                "selected": selected,
                "side": side,
                "conviction": conviction,
                "realized_net_excess_return_21d": actual_return,
                "realized_scaled_utility": scaled,
                "downside_path_penalty": downside,
                "pick_utility_delta": utility,
                "missed_opportunity_utility": missed,
            }
        )
    selected_delta = _mean(selected_utilities)
    missed_delta = _mean(missed_utilities)
    base_delta = selected_delta - missed_delta
    confidence = _probability(payload.get("model_confidence"), "model_confidence")
    warranted = int(base_delta > 0) if status == "SELECTED" else int(missed_delta == 0)
    forecast_loss = (confidence - warranted) ** 2
    null_loss = (0.5 - warranted) ** 2
    combined = base_delta + 0.1 * (null_loss - forecast_loss)
    return {
        "selection_disposition": (
            "CANDIDATES" if status == "SELECTED" else "NO_QUALIFIED_CANDIDATES"
        ),
        "output_confidence": confidence,
        "pick_metrics": rows,
        "selected_pick_utility_delta": selected_delta,
        "missed_opportunity_utility": missed_delta,
        "output_confidence_forecast_loss": forecast_loss,
        "output_confidence_null_loss": null_loss,
        "combined_utility_delta": combined,
    }


def _cro_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("agent_id") != agent_id:
        raise ValueError("accepted CRO payload owner mismatch")
    review = _record(payload.get("review"), "accepted CRO review")
    actions = _rows(review.get("candidate_actions"), "CRO candidate_actions")
    actions_by_ref = _unique_by(actions, ("candidate_ref",), "CRO candidate_actions")
    states = _rows(realized.get("candidate_states"), "candidate_states")
    states_by_ref = _unique_by(states, ("candidate_ref",), "candidate_states")
    member_by_id = _member_rows_by_id(
        member_refs,
        "risk_candidate_id",
        required_fields=frozenset(
            {"risk_candidate_id", "ts_code", "proposed_target_weight"}
        ),
    )
    _require_exact_member_coverage(
        set(member_by_id),
        {key[0] for key in states_by_ref},
        label="realized CRO candidates",
    )
    if set(actions_by_ref) != set(states_by_ref):
        raise ValueError("accepted CRO actions and realized candidate states must match exactly")
    candidate_metrics: list[dict[str, Any]] = []
    tp = fp = tn = fn = 0
    brier_losses: list[float] = []
    null_losses: list[float] = []
    for key, action in actions_by_ref.items():
        state = states_by_ref[key]
        member = member_by_id[key[0]]
        if (
            action.get("ts_code") != state.get("ts_code")
            or action.get("ts_code") != member.get("ts_code")
        ):
            raise ValueError("CRO candidate ticker binding drift")
        _probability(
            member.get("proposed_target_weight"), "CRO proposed_target_weight"
        )
        predicted_action = action.get("action")
        if predicted_action not in {
            "VETO",
            "CAP_WEIGHT",
            "REDUCE_WEIGHT",
            "REQUIRE_REVIEW",
            "NO_OBJECTION",
        }:
            raise ValueError("accepted CRO action is invalid")
        predicted_positive = predicted_action != "NO_OBJECTION"
        probability = _probability(
            action.get("predicted_risk_probability"), "predicted_risk_probability"
        )
        actual = int(_number(state.get("realized_risk_state"), "realized_risk_state"))
        if actual not in {0, 1}:
            raise ValueError("realized CRO risk state must be zero or one")
        if predicted_positive and actual:
            tp += 1
        elif predicted_positive:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1
        brier_losses.append((probability - actual) ** 2)
        null_losses.append((0.5 - actual) ** 2)
        candidate_metrics.append(
            {
                "candidate_ref": key[0],
                "ts_code": _text(state.get("ts_code"), "candidate ts_code"),
                "predicted_action": predicted_action,
                "predicted_risk_probability": probability,
                "predicted_positive": predicted_positive,
                "realized_risk_state": actual,
                "realized_risk_evidence_ids": state.get("realized_risk_evidence_ids"),
            }
        )
    precision_zero = tp + fp == 0
    recall_zero = tp + fn == 0
    specificity_zero = tn + fp == 0
    precision = tp / (tp + fp) if not precision_zero else 0.0
    recall = tp / (tp + fn) if not recall_zero else 0.0
    specificity = tn / (tn + fp) if not specificity_zero else 1.0
    forecast_brier = _mean(brier_losses)
    null_brier = _mean(null_losses)
    components = [
        _decision_component(
            "PRECISION",
            0.35,
            precision,
            0.5,
            direction="HIGHER_IS_BETTER",
            unit="RATIO",
            zero_rule=(
                "ZERO_UTILITY_IF_NO_PREDICTED_POSITIVE"
                if precision_zero
                else "NOT_APPLICABLE"
            ),
        ),
        _decision_component(
            "RECALL",
            0.35,
            recall,
            0.5,
            direction="HIGHER_IS_BETTER",
            unit="RATIO",
            zero_rule=("ZERO_UTILITY_IF_NO_ACTUAL_POSITIVE" if recall_zero else "NOT_APPLICABLE"),
        ),
        _decision_component(
            "SPECIFICITY",
            0.20,
            specificity,
            0.5,
            direction="HIGHER_IS_BETTER",
            unit="RATIO",
            zero_rule=("ONE_IF_NO_ACTUAL_NEGATIVE" if specificity_zero else "NOT_APPLICABLE"),
        ),
        _decision_component(
            "CALIBRATION",
            0.10,
            forecast_brier,
            null_brier,
            direction="LOWER_IS_BETTER",
            unit="PROBABILITY_LOSS",
        ),
    ]
    return _with_decision_totals(
        "CRO",
        components,
        {
            "candidate_metrics": candidate_metrics,
            "true_positive_count": tp,
            "false_positive_count": fp,
            "true_negative_count": tn,
            "false_negative_count": fn,
            "precision": precision,
            "recall": recall,
            "specificity": specificity,
            "forecast_brier_loss": forecast_brier,
            "null_brier_loss": null_brier,
            "precision_denominator_zero": precision_zero,
            "recall_denominator_zero": recall_zero,
            "specificity_denominator_zero": specificity_zero,
        },
    )


def _alpha_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("agent_id") != agent_id:
        raise ValueError("accepted Alpha payload owner mismatch")
    selection = _record(payload.get("selection"), "accepted Alpha selection")
    paths = _rows(realized.get("candidate_paths"), "candidate_paths")
    paths_by_ref = _unique_by(paths, ("candidate_ref",), "candidate_paths")
    member_by_id = _member_rows_by_id(
        member_refs,
        "candidate_ref",
        required_fields=frozenset({"candidate_ref", "ts_code"}),
    )
    _require_exact_member_coverage(
        set(member_by_id),
        {key[0] for key in paths_by_ref},
        label="realized Alpha candidates",
    )
    picks = _rows(selection.get("novel_picks"), "Alpha novel_picks", allow_empty=True)
    picks_by_ref = _unique_by(picks, ("candidate_ref",), "Alpha novel_picks")
    if set(picks_by_ref) - set(paths_by_ref):
        raise ValueError("accepted Alpha picks lack realized paths")
    disposition = selection.get("discovery_disposition")
    if disposition == "CANDIDATES" and not picks:
        raise ValueError("Alpha CANDIDATES requires picks")
    if disposition == "NONE_FOUND" and picks:
        raise ValueError("Alpha NONE_FOUND cannot carry picks")
    if disposition not in {"CANDIDATES", "NONE_FOUND"}:
        raise ValueError("accepted Alpha discovery disposition is invalid")
    candidate_metrics: list[dict[str, Any]] = []
    selected_values: list[float] = []
    missed_values: list[float] = []
    for key, path in paths_by_ref.items():
        pick = picks_by_ref.get(key)
        member = member_by_id[key[0]]
        if path.get("ts_code") != member.get("ts_code") or (
            pick is not None and pick.get("ts_code") != member.get("ts_code")
        ):
            raise ValueError("Alpha candidate ticker binding drift")
        actual_return = _number(
            path.get("realized_net_excess_return_5d"),
            "realized_net_excess_return_5d",
        )
        scaled = _clip(actual_return)
        selected = pick is not None
        conviction = (
            _probability(pick.get("conviction"), "Alpha conviction") if pick else 0.0
        )
        missed = (
            (1.0 - conviction) * max(0.0, scaled)
            if selected
            else max(0.0, scaled)
        )
        if selected:
            # Positive opportunities remain conviction-weighted, but selecting a
            # loser is a real action and its downside cannot be erased by sending
            # conviction=0. Residual positive alpha remains missed regret.
            selected_values.append(scaled if scaled < 0 else conviction * scaled)
        missed_values.append(missed)
        candidate_metrics.append(
            {
                "candidate_ref": key[0],
                "ts_code": _text(path.get("ts_code"), "candidate ts_code"),
                "selected": selected,
                "submitted_conviction": conviction,
                "realized_net_excess_return_5d": actual_return,
                "realized_scaled_alpha": scaled,
                "missed_opportunity_utility": missed,
            }
        )
    selected_delta = _mean(selected_values)
    incremental_delta = selected_delta - _mean(missed_values)
    confidence = _probability(payload.get("model_confidence"), "Alpha model_confidence")
    target = (
        int(incremental_delta > 0)
        if disposition == "CANDIDATES"
        else int(all(value == 0.0 for value in missed_values))
    )
    forecast_loss = (confidence - target) ** 2
    null_loss = (0.5 - target) ** 2
    # Confidence calibration is pre-registered as ten percent of final Alpha
    # utility. It is embedded in the 30% incremental component so the frozen
    # two-component schema remains stable and the final contribution is exact:
    # 0.30 * (0.10 / 0.30) * (null_loss - forecast_loss) == 0.10 * skill.
    confidence_skill_component_scale = (
        _ALPHA_CONFIDENCE_SKILL_FINAL_WEIGHT
        / dict(_DECISION_COMPONENTS["ALPHA"])["INCREMENTAL_OPPORTUNITY_UTILITY"]
    )
    effective_null_loss = (
        min(null_loss, forecast_loss)
        if disposition == "CANDIDATES" and incremental_delta <= 0
        else null_loss
    )
    components = [
        _decision_component(
            "SELECTED_PICK_UTILITY",
            0.70,
            selected_delta,
            0.0,
            direction="HIGHER_IS_BETTER",
            unit="RETURN",
        ),
        _decision_component(
            "INCREMENTAL_OPPORTUNITY_UTILITY",
            0.30,
            incremental_delta - confidence_skill_component_scale * forecast_loss,
            -confidence_skill_component_scale * effective_null_loss,
            direction="HIGHER_IS_BETTER",
            unit="RETURN",
        ),
    ]
    return _with_decision_totals(
        "ALPHA",
        components,
        {
            "discovery_disposition": disposition,
            "candidate_metrics": candidate_metrics,
            "selected_pick_utility_delta": selected_delta,
            "incremental_candidate_utility_delta": incremental_delta,
            "output_confidence_forecast_loss": forecast_loss,
            "output_confidence_null_loss": null_loss,
        },
    )


def _execution_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("agent_id") != agent_id:
        raise ValueError("accepted Execution payload owner mismatch")
    assessment = _record(payload.get("assessment"), "accepted Execution assessment")
    accepted_rows = _rows(assessment.get("order_assessments"), "order_assessments")
    accepted_by_ref = _unique_by(
        accepted_rows, ("order_intent_ref",), "order_assessments"
    )
    paths = _rows(realized.get("order_paths"), "order_paths")
    paths_by_ref = _unique_by(paths, ("order_intent_ref",), "order_paths")
    member_by_id = _member_rows_by_id(
        member_refs,
        "order_intent_id",
        required_fields=frozenset(
            {"order_intent_id", "ts_code", "action", "requested_delta_weight"}
        ),
    )
    _require_exact_member_coverage(
        set(member_by_id),
        {key[0] for key in paths_by_ref},
        label="realized Execution orders",
    )
    if set(accepted_by_ref) != set(paths_by_ref):
        raise ValueError("accepted Execution assessments and realized orders must match exactly")
    order_metrics: list[dict[str, Any]] = []
    cost_errors: list[float] = []
    feasibility_values: list[float] = []
    attainments: list[float] = []
    compliance_values: list[float] = []
    for key, accepted in accepted_by_ref.items():
        path = paths_by_ref[key]
        member = member_by_id[key[0]]
        if (
            accepted.get("ts_code") != path.get("ts_code")
            or accepted.get("ts_code") != member.get("ts_code")
        ):
            raise ValueError("Execution order ticker binding drift")
        requested = _number(accepted.get("requested_delta_weight"), "requested_delta_weight")
        frozen_requested = _number(
            member.get("requested_delta_weight"), "frozen requested_delta_weight"
        )
        if not math.isclose(requested, frozen_requested, abs_tol=1e-12):
            raise ValueError("Execution requested delta differs from the frozen order intent")
        expected_action = "BUY" if requested > 0 else member.get("action")
        if expected_action != member.get("action") or member.get("action") not in {
            "BUY",
            "SELL",
            "REDUCE",
        }:
            raise ValueError("Execution action differs from the frozen order intent")
        if requested == 0:
            raise ValueError("Execution requested_delta_weight cannot be zero")
        predicted_feasibility = accepted.get("feasibility")
        realized_feasibility = path.get("realized_feasibility")
        if predicted_feasibility not in {"FEASIBLE", "PARTIAL", "BLOCKED"} or (
            realized_feasibility not in {"FEASIBLE", "PARTIAL", "BLOCKED"}
        ):
            raise ValueError("Execution feasibility class is invalid")
        confidence = _probability(
            accepted.get("feasibility_confidence"), "feasibility_confidence"
        )
        feasibility_values.append(
            confidence if predicted_feasibility == realized_feasibility else -confidence
        )
        predicted_cost = _number(accepted.get("predicted_cost_bps"), "predicted_cost_bps")
        realized_cost = _number(path.get("realized_cost_bps"), "realized_cost_bps")
        cost_scale = _number(path.get("pit_cost_scale_bps"), "pit_cost_scale_bps")
        if cost_scale <= 0:
            raise ValueError("Execution cost scale must be positive")
        cost_error = abs(predicted_cost - realized_cost) / cost_scale
        realized_delta = _number(path.get("realized_delta_weight"), "realized_delta_weight")
        attainment = (
            min(abs(realized_delta) / abs(requested), 1.0)
            if realized_delta == 0 or math.copysign(1, realized_delta) == math.copysign(1, requested)
            else 0.0
        )
        compliance = int(
            _number(path.get("realized_policy_compliance"), "realized_policy_compliance")
        )
        if compliance not in {0, 1}:
            raise ValueError("Execution policy compliance must be zero or one")
        cost_errors.append(cost_error)
        attainments.append(attainment)
        compliance_values.append(float(compliance))
        order_metrics.append(
            {
                "order_intent_ref": key[0],
                "ts_code": _text(path.get("ts_code"), "order ts_code"),
                "requested_delta_weight": requested,
                "predicted_feasibility": predicted_feasibility,
                "predicted_feasibility_confidence": confidence,
                "realized_feasibility": realized_feasibility,
                "predicted_cost_bps": predicted_cost,
                "realized_cost_bps": realized_cost,
                "pit_cost_scale_bps": cost_scale,
                "normalized_absolute_cost_error": cost_error,
                "realized_delta_weight": realized_delta,
                "target_delta_attainment": attainment,
                "realized_policy_compliance": compliance,
                "outcome_evidence_ids": path.get("outcome_evidence_ids"),
            }
        )
    mean_cost = _mean(cost_errors)
    feasibility_delta = _mean(feasibility_values)
    target_delta = _mean(attainments)
    compliance_delta = _mean(compliance_values)
    components = [
        _decision_component(
            "COST_ERROR",
            0.40,
            mean_cost,
            1.0,
            direction="LOWER_IS_BETTER",
            unit="BASIS_POINTS",
        ),
        _decision_component(
            "FEASIBILITY",
            0.30,
            feasibility_delta,
            0.0,
            direction="HIGHER_IS_BETTER",
            unit="RATIO",
        ),
        _decision_component(
            "TARGET_DELTA",
            0.20,
            target_delta,
            0.0,
            direction="HIGHER_IS_BETTER",
            unit="PORTFOLIO_WEIGHT",
        ),
        _decision_component(
            "POLICY_COMPLIANCE",
            0.10,
            compliance_delta,
            0.0,
            direction="HIGHER_IS_BETTER",
            unit="RATIO",
        ),
    ]
    return _with_decision_totals(
        "EXECUTION",
        components,
        {
            "execution_mode": payload.get("execution_mode"),
            "order_metrics": order_metrics,
            "mean_normalized_cost_error": mean_cost,
            "feasibility_classification_utility_delta": feasibility_delta,
            "target_delta_utility_delta": target_delta,
            "policy_compliance_utility_delta": compliance_delta,
        },
    )


def _cio_metrics(
    agent_id: str,
    payload: Mapping[str, Any],
    member_refs: Sequence[Mapping[str, Any]],
    realized: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("agent_id") != agent_id:
        raise ValueError("accepted CIO payload owner mismatch")
    if set(realized) != {
        "position_paths",
        "realized_cash_weight",
        "accepted_portfolio_net_return_5d",
        "baseline_portfolio_net_return_5d",
        "accepted_portfolio_max_drawdown_5d",
        "baseline_portfolio_max_drawdown_5d",
        "accepted_portfolio_turnover_cost",
        "baseline_portfolio_turnover_cost",
        "realized_constraint_compliance",
    }:
        raise ValueError("CIO realized metrics fields mismatch")
    if payload.get("decision_stage") != "FINAL":
        raise ValueError("CIO outcome requires the accepted FINAL decision")
    decision = _record(payload.get("decision"), "accepted CIO decision")
    disposition = decision.get("decision_disposition")
    if disposition not in {"TARGET_PORTFOLIO", "HOLD_CURRENT", "ALL_CASH"}:
        raise ValueError("accepted CIO decision disposition is invalid")
    targets = _rows(decision.get("target_positions"), "target_positions", allow_empty=True)
    targets_by_ticker = _unique_by(targets, ("ts_code",), "target_positions")
    if disposition == "TARGET_PORTFOLIO" and not targets:
        raise ValueError("CIO TARGET_PORTFOLIO requires target positions")
    if disposition == "ALL_CASH" and targets:
        raise ValueError("CIO ALL_CASH cannot carry target positions")
    paths = _rows(realized.get("position_paths"), "position_paths", allow_empty=True)
    if any(
        set(path) != {"ts_code", "realized_weight", "realized_net_return_5d"}
        for path in paths
    ):
        raise ValueError("CIO realized position fields mismatch")
    paths_by_ticker = _unique_by(paths, ("ts_code",), "position_paths")
    contexts = _rows(member_refs, "member_refs")
    if len(contexts) != 1:
        raise ValueError("CIO requires exactly one frozen portfolio context")
    context = contexts[0]
    if set(context) != {
        "controlled_target_set_id",
        "baseline_cash_weight",
        "positions",
    }:
        raise ValueError("CIO frozen portfolio context fields mismatch")
    _text(context.get("controlled_target_set_id"), "controlled_target_set_id")
    frozen_positions = _rows(
        context.get("positions"), "frozen CIO positions", allow_empty=True
    )
    frozen_by_ticker = _unique_by(
        frozen_positions, ("ts_code",), "frozen CIO positions"
    )
    for position in frozen_positions:
        if set(position) != {
            "position_ref",
            "ts_code",
            "baseline_weight",
            "controlled_target_weight",
        }:
            raise ValueError("CIO frozen position fields mismatch")
        _text(position.get("position_ref"), "CIO position_ref")
        _probability(position.get("baseline_weight"), "CIO baseline_weight")
        _probability(
            position.get("controlled_target_weight"),
            "CIO controlled_target_weight",
        )
    _require_exact_member_coverage(
        {key[0] for key in frozen_by_ticker},
        {key[0] for key in paths_by_ticker},
        label="realized CIO positions",
    )
    if set(targets_by_ticker) - set(frozen_by_ticker):
        raise ValueError("accepted CIO targets are outside the frozen portfolio domain")
    portfolio_metrics: list[dict[str, Any]] = []
    for key, path in paths_by_ticker.items():
        target = targets_by_ticker.get(key)
        frozen = frozen_by_ticker[key]
        portfolio_metrics.append(
            {
                "ts_code": key[0],
                "pre_cio_weight": _probability(
                    frozen.get("baseline_weight"), "baseline_weight"
                ),
                "target_weight": (
                    _probability(target.get("target_weight"), "target_weight")
                    if target is not None
                    else 0.0
                ),
                "realized_weight": _probability(
                    path.get("realized_weight"), "realized_weight"
                ),
                "realized_net_return_5d": _number(
                    path.get("realized_net_return_5d"), "realized_net_return_5d"
                ),
            }
        )
    pre_cash = _probability(context.get("baseline_cash_weight"), "baseline_cash_weight")
    target_cash = _probability(decision.get("cash_weight"), "target cash_weight")
    if disposition == "ALL_CASH" and target_cash != 1.0:
        raise ValueError("CIO ALL_CASH target cash weight must equal one")
    realized_cash = _probability(realized.get("realized_cash_weight"), "realized_cash_weight")
    for total, label in (
        (pre_cash + sum(row["pre_cio_weight"] for row in portfolio_metrics), "baseline"),
        (target_cash + sum(row["target_weight"] for row in portfolio_metrics), "target"),
        (realized_cash + sum(row["realized_weight"] for row in portfolio_metrics), "realized"),
    ):
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"CIO {label} portfolio weights must sum to one")
    output_return = _number(
        realized.get("accepted_portfolio_net_return_5d"),
        "accepted_portfolio_net_return_5d",
    )
    null_return = _number(
        realized.get("baseline_portfolio_net_return_5d"),
        "baseline_portfolio_net_return_5d",
    )
    recomputed_null_return = sum(
        row["pre_cio_weight"] * row["realized_net_return_5d"]
        for row in portfolio_metrics
    )
    if not math.isclose(null_return, recomputed_null_return, abs_tol=1e-12):
        raise ValueError(
            "CIO baseline return differs from the frozen baseline weights and returns"
        )
    output_drawdown = _number(
        realized.get("accepted_portfolio_max_drawdown_5d"),
        "accepted_portfolio_max_drawdown_5d",
    )
    null_drawdown = _number(
        realized.get("baseline_portfolio_max_drawdown_5d"),
        "baseline_portfolio_max_drawdown_5d",
    )
    output_turnover = _number(
        realized.get("accepted_portfolio_turnover_cost"),
        "accepted_portfolio_turnover_cost",
    )
    null_turnover = _number(
        realized.get("baseline_portfolio_turnover_cost"),
        "baseline_portfolio_turnover_cost",
    )
    if not math.isclose(null_turnover, 0.0, abs_tol=1e-12):
        raise ValueError("CIO frozen hold-current baseline turnover must equal zero")
    compliance = int(
        _number(
            realized.get("realized_constraint_compliance"),
            "realized_constraint_compliance",
        )
    )
    if compliance not in {0, 1}:
        raise ValueError("CIO constraint compliance must be zero or one")
    components = [
        _decision_component(
            "RELATIVE_RETURN",
            0.50,
            output_return,
            null_return,
            direction="HIGHER_IS_BETTER",
            unit="RETURN",
        ),
        _decision_component(
            "DRAWDOWN",
            0.25,
            output_drawdown,
            null_drawdown,
            direction="HIGHER_IS_BETTER",
            unit="RETURN",
        ),
        _decision_component(
            "TURNOVER_COST",
            0.15,
            output_turnover,
            null_turnover,
            direction="LOWER_IS_BETTER",
            unit="RETURN",
        ),
        _decision_component(
            "CONSTRAINT_COMPLIANCE",
            0.10,
            float(compliance),
            1.0,
            direction="HIGHER_IS_BETTER",
            unit="RATIO",
        ),
    ]
    return _with_decision_totals(
        "CIO",
        components,
        {
            "decision_disposition": disposition,
            "portfolio_metrics": portfolio_metrics,
            "pre_cio_cash_weight": pre_cash,
            "target_cash_weight": target_cash,
            "realized_cash_weight": realized_cash,
            "output_net_return_5d": output_return,
            "null_net_return_5d": null_return,
            "output_max_drawdown_5d": output_drawdown,
            "null_max_drawdown_5d": null_drawdown,
            "output_turnover_cost": output_turnover,
            "null_turnover_cost": null_turnover,
            "realized_constraint_compliance": compliance,
        },
    )


__all__ = [
    "derive_authoritative_outcome_metrics",
]
