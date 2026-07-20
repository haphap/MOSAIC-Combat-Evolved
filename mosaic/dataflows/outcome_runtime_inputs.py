"""Private-cache inputs for outcome scheduling, freezing, and maturation."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker

from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import (
    OPPORTUNITY_GENERATION_FAILURE_CODES,
    OUTCOME_CONTRACTS,
    OUTCOME_METRIC_SCHEMAS_HASH,
    OUTCOME_PROJECTION_SCHEMA_HASH,
    OUTCOME_PROJECTION_SCHEMA_PATH,
    OUTCOME_REALIZED_METRIC_SCHEMAS_HASH,
    OUTCOME_REALIZED_METRIC_SCHEMAS,
    OUTCOME_REGISTRY_HASH,
)


EVENT_COVERAGE_SCHEMA_VERSION = "verified_event_coverage_snapshot_v2"
OPPORTUNITY_PROJECTION_SCHEMA_VERSION = "evaluation_opportunity_projection_v2"
OUTCOME_PROJECTION_SCHEMA_VERSION = "realized_outcome_projection_v2"
_OPPORTUNITY_PROJECTION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "evaluation_opportunity_projection_v2.schema.json"
)
_EMPTY_OPPORTUNITY_ALLOWED = {
    "druckenmiller",
    "munger",
    "burry",
    "ackman",
    "cro",
    "alpha_discovery",
    "autonomous_execution",
}
_READINESS_ONLY_PROJECTION_AGENTS = frozenset(
    {
        "druckenmiller",
        "munger",
        "burry",
        "ackman",
        "alpha_discovery",
        "cro",
        "autonomous_execution",
        "cio",
    }
)
_MEMBER_FIELD_BY_EVALUATION_OBJECT_TYPE = {
    "SECTOR_TILT_PICKS": "subindustry_id",
    "SUPERINVESTOR_PICKS": "candidate_ref",
    "RELATIONSHIP_EDGES": "edge_candidate_id",
    "CRO_FROZEN_RISK_ACTIONS": "risk_candidate_id",
    "ALPHA_FROZEN_NOVEL_PICKS": "candidate_ref",
    "EXECUTION_FROZEN_ORDER_INTENT": "order_intent_id",
    "CIO_FROZEN_FINAL_PORTFOLIO": "controlled_target_set_id",
}
_MEMBER_FIELDS_BY_EVALUATION_OBJECT_TYPE = {
    "SECTOR_TILT_PICKS": frozenset(
        {
            "subindustry_id",
            "security_shortlist_id",
            "security_shortlist_hash",
            "security_ts_codes",
        }
    ),
    "SUPERINVESTOR_PICKS": frozenset({"candidate_ref", "ts_code"}),
    "RELATIONSHIP_EDGES": frozenset(
        {"edge_candidate_id", "materiality_weight"}
    ),
    "CRO_FROZEN_RISK_ACTIONS": frozenset(
        {"risk_candidate_id", "ts_code", "proposed_target_weight"}
    ),
    "ALPHA_FROZEN_NOVEL_PICKS": frozenset({"candidate_ref", "ts_code"}),
    "EXECUTION_FROZEN_ORDER_INTENT": frozenset(
        {"order_intent_id", "ts_code", "action", "requested_delta_weight"}
    ),
    "CIO_FROZEN_FINAL_PORTFOLIO": frozenset(
        {"controlled_target_set_id", "baseline_cash_weight", "positions"}
    ),
}
_OPPORTUNITY_PROJECTION_FIELDS = {
    "schema_version",
    "snapshot_hash",
    "agent_id",
    "as_of",
    "generated_at",
    "pit_status",
    "projection_status",
    "qualification_predicate_version",
    "member_refs",
    "source_evidence_by_required_source_id",
    "error_codes",
}
_OUTCOME_PROJECTION_FIELDS = {
    "schema_version",
    "snapshot_hash",
    "scheduled_sample_id",
    "outcome_schedule_slot_id",
    "outcome_schedule_slot_hash",
    "evaluation_opportunity_set_id",
    "evaluation_opportunity_set_hash",
    "accepted_output_id",
    "accepted_output_hash",
    "track_key_hash",
    "agent_id",
    "metric_family",
    "metric_schema_id",
    "realized_metric_schema_id",
    "outcome_registry_hash",
    "metric_schemas_hash",
    "realized_metric_schemas_hash",
    "outcome_projection_schema_hash",
    "source_authority_registry_hash",
    "source_authority_registry_schema_hash",
    "source_receipt_schema_hash",
    "source_batch_schema_hash",
    "opportunity_as_of",
    "outcome_due_at",
    "generated_at",
    "pit_status",
    "source_batch_id",
    "source_batch_hash",
}
_FORBIDDEN_REALIZED_KEY_FRAGMENTS = (
    "agent_output",
    "confidence",
    "forecast",
    "model_output",
    "predicted",
    "prediction",
    "predictive",
    "score",
    "utility",
)


def outcome_runtime_cache_root() -> Path:
    explicit = os.getenv("MOSAIC_OUTCOME_RUNTIME_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "outcome_runtime"


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _read_hashed(path: Path, schema_version: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required outcome runtime input is unavailable: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read outcome runtime input {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise ValueError(f"outcome runtime input schema mismatch: {path}")
    supplied = payload.get("snapshot_hash")
    without_hash = {key: value for key, value in payload.items() if key != "snapshot_hash"}
    if supplied != canonical_hash(without_hash):
        raise ValueError(f"outcome runtime input hash mismatch: {path}")
    return payload


def expected_qualification_predicate_version(agent_id: str) -> str:
    """Return the registry-owned denominator predicate for one Agent."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    return str(contract["opportunity_set_contract_version"])


def _member_field(agent_id: str) -> str:
    contract = OUTCOME_CONTRACTS[agent_id]
    if contract["evaluation_object_type"] == "MACRO_TRANSMISSION":
        return (
            "event_id"
            if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
            else "path_snapshot_id"
        )
    field = _MEMBER_FIELD_BY_EVALUATION_OBJECT_TYPE.get(
        str(contract["evaluation_object_type"])
    )
    if field is None:
        raise ValueError(f"{agent_id} has no registered opportunity member domain")
    return field


def validate_evaluation_opportunity_members(
    agent_id: str,
    qualification_predicate_version: Any,
    member_refs: Any,
) -> list[dict[str, Any]]:
    """Validate the denominator against the Agent's frozen evaluation domain."""
    if agent_id not in OUTCOME_CONTRACTS:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    expected_predicate = expected_qualification_predicate_version(agent_id)
    if qualification_predicate_version != expected_predicate:
        raise ValueError(
            f"{agent_id} qualification predicate must be {expected_predicate!r}"
        )
    if not isinstance(member_refs, list):
        raise ValueError("opportunity member_refs must be an array")
    if not member_refs and agent_id not in _EMPTY_OPPORTUNITY_ALLOWED:
        raise ValueError(f"{agent_id} cannot use an empty opportunity denominator")
    member_field = _member_field(agent_id)
    object_type = str(OUTCOME_CONTRACTS[agent_id]["evaluation_object_type"])
    member_fields = _MEMBER_FIELDS_BY_EVALUATION_OBJECT_TYPE.get(
        object_type,
        frozenset({member_field}),
    )
    normalized: list[dict[str, Any]] = []
    member_identities: set[str] = set()
    for index, member in enumerate(member_refs):
        if not isinstance(member, dict) or set(member) != member_fields:
            raise ValueError(
                f"{agent_id} member_refs[{index}] must contain exactly "
                + ", ".join(repr(field) for field in sorted(member_fields))
            )
        value = member.get(member_field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{agent_id} member_refs[{index}].{member_field} must be non-empty"
            )
        member_identity = value.strip()
        if member_identity in member_identities:
            raise ValueError(
                f"opportunity member {member_field} identities must be unique"
            )
        member_identities.add(member_identity)
        normalized_member: dict[str, Any] = {member_field: member_identity}
        if object_type == "SECTOR_TILT_PICKS":
            for field in ("security_shortlist_id", "security_shortlist_hash"):
                field_value = member.get(field)
                if not isinstance(field_value, str) or not field_value.strip():
                    raise ValueError(
                        f"{agent_id} member_refs[{index}].{field} must be non-empty"
                    )
                normalized_member[field] = field_value.strip()
            shortlist_hash = normalized_member["security_shortlist_hash"]
            if not (
                len(shortlist_hash) == 71
                and shortlist_hash.startswith("sha256:")
                and all(character in "0123456789abcdef" for character in shortlist_hash[7:])
            ):
                raise ValueError(
                    f"{agent_id} member_refs[{index}].security_shortlist_hash "
                    "must be lowercase sha256"
                )
            ts_codes = member.get("security_ts_codes")
            if not isinstance(ts_codes, list):
                raise ValueError(
                    f"{agent_id} member_refs[{index}].security_ts_codes must be an array"
                )
            normalized_ts_codes: list[str] = []
            for ts_index, ts_code in enumerate(ts_codes):
                if not isinstance(ts_code, str) or not ts_code.strip():
                    raise ValueError(
                        f"{agent_id} member_refs[{index}].security_ts_codes[{ts_index}] "
                        "must be non-empty"
                    )
                normalized_ts_codes.append(ts_code.strip())
            if len(normalized_ts_codes) != len(set(normalized_ts_codes)):
                raise ValueError("Sector security_ts_codes must be unique per shortlist")
            normalized_member["security_ts_codes"] = normalized_ts_codes
        elif object_type == "RELATIONSHIP_EDGES":
            weight = member.get("materiality_weight")
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(float(weight))
                or float(weight) <= 0
            ):
                raise ValueError(
                    f"{agent_id} member_refs[{index}].materiality_weight "
                    "must be finite and positive"
                )
            normalized_member["materiality_weight"] = float(weight)
        elif object_type == "SUPERINVESTOR_PICKS":
            ts_code = member.get("ts_code")
            if not isinstance(ts_code, str) or not ts_code.strip():
                raise ValueError(
                    f"{agent_id} member_refs[{index}].ts_code must be non-empty"
                )
            normalized_member["ts_code"] = ts_code.strip()
        elif object_type in {
            "CRO_FROZEN_RISK_ACTIONS",
            "ALPHA_FROZEN_NOVEL_PICKS",
        }:
            ts_code = _canonical_a_share_code(
                member.get("ts_code"),
                f"{agent_id} member_refs[{index}].ts_code",
            )
            normalized_member["ts_code"] = ts_code
            if object_type == "CRO_FROZEN_RISK_ACTIONS":
                normalized_member["proposed_target_weight"] = _member_weight(
                    member.get("proposed_target_weight"),
                    f"{agent_id} member_refs[{index}].proposed_target_weight",
                )
        elif object_type == "EXECUTION_FROZEN_ORDER_INTENT":
            normalized_member["ts_code"] = _canonical_a_share_code(
                member.get("ts_code"),
                f"{agent_id} member_refs[{index}].ts_code",
            )
            action = member.get("action")
            if action not in {"BUY", "SELL", "REDUCE"}:
                raise ValueError(
                    f"{agent_id} member_refs[{index}].action is invalid"
                )
            delta = _finite_number(
                member.get("requested_delta_weight"),
                f"{agent_id} member_refs[{index}].requested_delta_weight",
            )
            if not -1 <= delta <= 1 or math.isclose(delta, 0.0, abs_tol=1e-12):
                raise ValueError("Execution requested_delta_weight must be in [-1,1] and non-zero")
            if (action == "BUY") != (delta > 0):
                raise ValueError("Execution action/requested_delta_weight mismatch")
            normalized_member["action"] = action
            normalized_member["requested_delta_weight"] = delta
        elif object_type == "CIO_FROZEN_FINAL_PORTFOLIO":
            normalized_member.update(
                _normalize_cio_portfolio_context(member, agent_id=agent_id, index=index)
            )
        normalized.append(normalized_member)
    return normalized


def _finite_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _member_weight(value: Any, label: str) -> float:
    weight = _finite_number(value, label)
    if not 0 <= weight <= 1:
        raise ValueError(f"{label} must be in [0,1]")
    return weight


def _canonical_a_share_code(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    normalized = value.strip().upper()
    if not (
        len(normalized) == 9
        and normalized[:6].isdigit()
        and normalized[6:] in {".SH", ".SZ", ".BJ"}
    ):
        raise ValueError(f"{label} must be a canonical A-share code")
    return normalized


def _normalize_cio_portfolio_context(
    member: Mapping[str, Any],
    *,
    agent_id: str,
    index: int,
) -> dict[str, Any]:
    baseline_cash = _member_weight(
        member.get("baseline_cash_weight"),
        f"{agent_id} member_refs[{index}].baseline_cash_weight",
    )
    raw_positions = member.get("positions")
    if not isinstance(raw_positions, list):
        raise ValueError(f"{agent_id} member_refs[{index}].positions must be an array")
    positions: list[dict[str, Any]] = []
    position_refs: set[str] = set()
    ts_codes: set[str] = set()
    for position_index, raw_position in enumerate(raw_positions):
        if not isinstance(raw_position, Mapping) or set(raw_position) != {
            "position_ref",
            "ts_code",
            "baseline_weight",
            "controlled_target_weight",
        }:
            raise ValueError("CIO frozen positions must contain the exact portfolio fields")
        position_ref = raw_position.get("position_ref")
        if not isinstance(position_ref, str) or not position_ref.strip():
            raise ValueError("CIO frozen position_ref must be non-empty")
        ts_code = _canonical_a_share_code(
            raw_position.get("ts_code"),
            f"{agent_id} member_refs[{index}].positions[{position_index}].ts_code",
        )
        if position_ref in position_refs or ts_code in ts_codes:
            raise ValueError("CIO frozen position refs and tickers must be unique")
        position_refs.add(position_ref)
        ts_codes.add(ts_code)
        positions.append(
            {
                "position_ref": position_ref.strip(),
                "ts_code": ts_code,
                "baseline_weight": _member_weight(
                    raw_position.get("baseline_weight"),
                    "CIO frozen baseline_weight",
                ),
                "controlled_target_weight": _member_weight(
                    raw_position.get("controlled_target_weight"),
                    "CIO frozen controlled_target_weight",
                ),
            }
        )
    if positions != sorted(positions, key=lambda row: row["ts_code"]):
        raise ValueError("CIO frozen positions must be sorted by ts_code")
    if not math.isclose(
        baseline_cash + sum(row["baseline_weight"] for row in positions),
        1.0,
        abs_tol=1e-9,
    ):
        raise ValueError("CIO frozen baseline weights must sum to one")
    if sum(row["controlled_target_weight"] for row in positions) > 1 + 1e-9:
        raise ValueError("CIO frozen controlled target weights exceed one")
    return {
        "baseline_cash_weight": baseline_cash,
        "positions": positions,
    }


def _source_evidence(
    agent_id: str,
    source_evidence: Any,
    *,
    label: str,
) -> list[str]:
    required_sources = set(OUTCOME_CONTRACTS[agent_id]["required_source_ids"])
    if not isinstance(source_evidence, dict) or set(source_evidence) != required_sources:
        raise ValueError(f"{label} does not cover the exact required_source_ids")
    flattened: list[str] = []
    for source_id in sorted(required_sources):
        values = source_evidence[source_id]
        if not isinstance(values, list) or not values or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError(f"{label} source {source_id} lacks evidence")
        flattened.extend(value.strip() for value in values)
    if len(flattened) != len(set(flattened)):
        raise ValueError(f"{label} evidence IDs must be globally unique")
    return sorted(flattened)


def _forbidden_realized_key_path(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                return f"{path}.<non-string-key>"
            normalized = key.casefold()
            if any(fragment in normalized for fragment in _FORBIDDEN_REALIZED_KEY_FRAGMENTS):
                return f"{path}.{key}"
            nested = _forbidden_realized_key_path(child, f"{path}.{key}")
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for index, child in enumerate(value):
            nested = _forbidden_realized_key_path(child, f"{path}[{index}]")
            if nested is not None:
                return nested
    return None


def validate_realized_outcome_metrics(
    agent_id: str,
    realized_metrics: Any,
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    """Validate realized-only inputs against the Agent's registry-owned schema."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    if not isinstance(realized_metrics, Mapping):
        raise ValueError("realized outcome metrics must be an object")
    normalized_metrics = dict(realized_metrics)
    forbidden_path = _forbidden_realized_key_path(normalized_metrics)
    if forbidden_path is not None:
        raise ValueError(
            "realized outcome metrics contain a forecast, prediction, utility, "
            f"confidence, or score at {forbidden_path}"
        )
    if allow_empty and not normalized_metrics:
        return {}
    schema_id = str(contract["realized_metric_schema_id"])
    schema = OUTCOME_REALIZED_METRIC_SCHEMAS.get(schema_id)
    if schema is None:
        raise ValueError(f"unknown realized outcome metric schema: {schema_id}")
    errors = sorted(
        Draft7Validator(dict(schema)).iter_errors(normalized_metrics),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        error_path = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(
            f"realized outcome metrics schema violation at {error_path}: {first.message}"
        )
    return normalized_metrics


def validate_raw_metrics_realization_consistency(
    agent_id: str,
    realized_metrics: Mapping[str, Any],
    raw_metrics: Mapping[str, Any],
) -> None:
    """Reject score inputs whose realized fields drift from observed outcomes."""
    contract = OUTCOME_CONTRACTS.get(agent_id)
    if contract is None:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    realized = validate_realized_outcome_metrics(agent_id, dict(realized_metrics))
    family = str(contract["metric_family"])
    raw = dict(raw_metrics)
    if family == "MACRO_TRANSMISSION":
        expected = {
            "role_path_metric": raw["role_path_metric"],
            "pit_volatility_scale": raw["pit_volatility_scale"],
        }
    elif family == "STANDARD_SECTOR":
        expected = {
            "direction_paths": [
                {
                    field: row[field]
                    for field in (
                        "direction_id",
                        "realized_return_5d",
                        "parent_sector_return_5d",
                        "realized_scaled_path",
                    )
                }
                for row in raw["direction_metrics"]
            ],
            "security_paths": [
                {
                    field: row[field]
                    for field in (
                        "side",
                        "direction_id",
                        "ts_code",
                        "net_alpha_5d",
                        "realized_scaled_alpha",
                    )
                }
                for row in raw["security_metrics"]
            ],
        }
    elif family == "RELATIONSHIP":
        expected = {
            "edge_paths": [
                {
                    field: row[field]
                    for field in (
                        "edge_candidate_id",
                        "realized_edge_state",
                        "matched_non_edge_lift",
                    )
                }
                for row in raw["edge_metrics"]
            ]
        }
    elif family == "SUPERINVESTOR":
        expected = {
            "candidate_paths": [
                {
                    field: row[field]
                    for field in (
                        "candidate_ref",
                        "ts_code",
                        "realized_net_excess_return_21d",
                    )
                }
                for row in raw["pick_metrics"]
            ]
        }
    elif family == "CRO":
        expected = {
            "candidate_states": [
                {
                    field: row[field]
                    for field in (
                        "candidate_ref",
                        "ts_code",
                        "realized_risk_state",
                        "realized_risk_evidence_ids",
                    )
                }
                for row in raw["candidate_metrics"]
            ]
        }
    elif family == "ALPHA":
        expected = {
            "candidate_paths": [
                {
                    field: row[field]
                    for field in (
                        "candidate_ref",
                        "ts_code",
                        "realized_net_excess_return_5d",
                    )
                }
                for row in raw["candidate_metrics"]
            ]
        }
    elif family == "EXECUTION":
        expected = {
            "order_paths": [
                {
                    field: row[field]
                    for field in (
                        "order_intent_ref",
                        "ts_code",
                        "realized_feasibility",
                        "realized_cost_bps",
                        "pit_cost_scale_bps",
                        "realized_delta_weight",
                        "realized_policy_compliance",
                        "outcome_evidence_ids",
                    )
                }
                for row in raw["order_metrics"]
            ]
        }
    elif family == "CIO":
        expected = {
            "position_paths": [
                {
                    field: row[field]
                    for field in (
                        "ts_code",
                        "realized_weight",
                        "realized_net_return_5d",
                    )
                }
                for row in raw["portfolio_metrics"]
            ],
            "realized_cash_weight": raw["realized_cash_weight"],
            "accepted_portfolio_net_return_5d": raw["output_net_return_5d"],
            "baseline_portfolio_net_return_5d": raw["null_net_return_5d"],
            "accepted_portfolio_max_drawdown_5d": raw[
                "output_max_drawdown_5d"
            ],
            "baseline_portfolio_max_drawdown_5d": raw["null_max_drawdown_5d"],
            "accepted_portfolio_turnover_cost": raw["output_turnover_cost"],
            "baseline_portfolio_turnover_cost": raw["null_turnover_cost"],
            "realized_constraint_compliance": raw[
                "realized_constraint_compliance"
            ],
        }
    else:  # pragma: no cover - manifest validation closes this branch
        raise ValueError(f"unsupported outcome metric family: {family}")
    if realized != expected:
        raise ValueError(
            f"{agent_id} raw outcome metrics do not match the realized-only projection"
        )


def load_verified_event_coverage(
    as_of: str,
    *,
    root: Path | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Load a complete event-trigger coverage denominator; absence is not no-event."""
    runtime_root = root or outcome_runtime_cache_root()
    as_of_timestamp = _timestamp(as_of, "as_of")
    payload = _read_hashed(
        runtime_root / as_of_timestamp.date().isoformat() / "event_coverage.json",
        EVENT_COVERAGE_SCHEMA_VERSION,
    )
    if (
        payload.get("as_of") != as_of
        or payload.get("pit_status") != "VERIFIED"
        or _timestamp(payload.get("generated_at"), "event coverage generated_at")
        > as_of_timestamp
    ):
        raise ValueError("event coverage snapshot is not PIT-aligned to the run")
    event_agents = {
        agent_id
        for agent_id, contract in OUTCOME_CONTRACTS.items()
        if contract["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
    }
    coverage = payload.get("event_coverage")
    if not isinstance(coverage, dict) or set(coverage) != event_agents:
        raise ValueError("event coverage must contain the exact event-triggered Agent roster")
    return coverage


def load_evaluation_opportunity_projection(
    as_of: str,
    agent_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load one deterministic pre-run opportunity projection for a scheduled Agent."""
    if agent_id not in OUTCOME_CONTRACTS:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    runtime_root = root or outcome_runtime_cache_root()
    as_of_timestamp = _timestamp(as_of, "as_of")
    payload = _read_hashed(
        runtime_root
        / as_of_timestamp.date().isoformat()
        / "opportunities"
        / f"{agent_id}.json",
        OPPORTUNITY_PROJECTION_SCHEMA_VERSION,
    )
    if set(payload) != _OPPORTUNITY_PROJECTION_FIELDS:
        raise ValueError("evaluation opportunity projection fields drift")
    if (
        payload.get("agent_id") != agent_id
        or payload.get("as_of") != as_of
        or payload.get("pit_status") != "VERIFIED"
        or _timestamp(payload.get("generated_at"), "opportunity generated_at")
        > as_of_timestamp
    ):
        raise ValueError("evaluation opportunity projection is not PIT-aligned")
    predicate = payload.get("qualification_predicate_version")
    source_evidence = payload.get("source_evidence_by_required_source_id")
    _source_evidence(agent_id, source_evidence, label="opportunity")
    status = payload.get("projection_status")
    if status == "AVAILABLE":
        if agent_id in _READINESS_ONLY_PROJECTION_AGENTS:
            if payload.get("member_refs") != []:
                raise ValueError(
                    "deferred runtime pre-run projection may provide readiness "
                    "evidence only"
                )
            if predicate != expected_qualification_predicate_version(agent_id):
                raise ValueError(
                    f"{agent_id} qualification predicate must be "
                    f"{expected_qualification_predicate_version(agent_id)!r}"
                )
        else:
            validate_evaluation_opportunity_members(
                agent_id,
                predicate,
                payload.get("member_refs"),
            )
        if payload.get("error_codes") != []:
            raise ValueError("AVAILABLE opportunity projection cannot carry error codes")
    elif status == "GENERATION_FAILURE":
        if predicate != expected_qualification_predicate_version(agent_id):
            raise ValueError("failed opportunity projection predicate version drift")
        if payload.get("member_refs") != []:
            raise ValueError("failed opportunity projection cannot carry members")
        errors = payload.get("error_codes")
        if (
            not isinstance(errors, list)
            or not errors
            or any(
                error not in OPPORTUNITY_GENERATION_FAILURE_CODES
                for error in errors
            )
        ):
            raise ValueError("failed opportunity projection has invalid error codes")
    else:
        raise ValueError("unknown evaluation opportunity projection status")
    projection_schema = json.loads(
        _OPPORTUNITY_PROJECTION_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    schema_errors = sorted(
        Draft202012Validator(
            projection_schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        first = schema_errors[0]
        path = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(
            f"evaluation opportunity projection schema violation at {path}: "
            f"{first.message}"
        )
    return payload


def load_realized_outcome_projection(
    *,
    scheduled_sample_id: str,
    outcome_schedule_slot_id: str,
    outcome_schedule_slot_hash: str,
    evaluation_opportunity_set_id: str,
    evaluation_opportunity_set_hash: str,
    accepted_output_id: str,
    accepted_output_hash: str,
    track_key_hash: str,
    agent_id: str,
    opportunity_as_of: str,
    outcome_due_at: str,
    cutoff_at: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load one hash-bound, role-owned deterministic outcome projection."""
    if agent_id not in OUTCOME_CONTRACTS:
        raise ValueError(f"unknown outcome Agent {agent_id!r}")
    if (
        not isinstance(scheduled_sample_id, str)
        or not scheduled_sample_id
        or "/" in scheduled_sample_id
        or "\\" in scheduled_sample_id
        or scheduled_sample_id in {".", ".."}
    ):
        raise ValueError("scheduled_sample_id is not a safe cache key")
    due = _timestamp(outcome_due_at, "outcome_due_at")
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    runtime_root = root or outcome_runtime_cache_root()
    payload = _read_hashed(
        runtime_root
        / due.date().isoformat()
        / "realized_outcomes"
        / f"{scheduled_sample_id}.json",
        OUTCOME_PROJECTION_SCHEMA_VERSION,
    )
    projection_schema = json.loads(
        OUTCOME_PROJECTION_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    schema_errors = sorted(
        Draft202012Validator(
            projection_schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        first = schema_errors[0]
        path = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(
            f"realized outcome projection schema violation at {path}: {first.message}"
        )
    if set(payload) != _OUTCOME_PROJECTION_FIELDS:
        raise ValueError("realized outcome projection fields drift")
    expected = {
        "scheduled_sample_id": scheduled_sample_id,
        "outcome_schedule_slot_id": outcome_schedule_slot_id,
        "outcome_schedule_slot_hash": outcome_schedule_slot_hash,
        "evaluation_opportunity_set_id": evaluation_opportunity_set_id,
        "evaluation_opportunity_set_hash": evaluation_opportunity_set_hash,
        "accepted_output_id": accepted_output_id,
        "accepted_output_hash": accepted_output_hash,
        "track_key_hash": track_key_hash,
        "agent_id": agent_id,
        "opportunity_as_of": opportunity_as_of,
        "outcome_due_at": outcome_due_at,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"realized outcome projection {field} drift")
    contract = OUTCOME_CONTRACTS[agent_id]
    for field, value in (
        ("metric_family", contract["metric_family"]),
        ("metric_schema_id", contract["metric_schema_id"]),
        ("realized_metric_schema_id", contract["realized_metric_schema_id"]),
        ("outcome_registry_hash", OUTCOME_REGISTRY_HASH),
        ("metric_schemas_hash", OUTCOME_METRIC_SCHEMAS_HASH),
        ("realized_metric_schemas_hash", OUTCOME_REALIZED_METRIC_SCHEMAS_HASH),
        ("outcome_projection_schema_hash", OUTCOME_PROJECTION_SCHEMA_HASH),
        ("pit_status", "VERIFIED"),
    ):
        if payload.get(field) != value:
            raise ValueError(f"realized outcome projection {field} drift")

    generated = _timestamp(payload.get("generated_at"), "outcome generated_at")
    if not due <= generated <= cutoff:
        raise ValueError(
            "realized outcome projection must satisfy due_at <= generated_at "
            "<= cutoff_at"
        )
    if not isinstance(payload.get("source_batch_id"), str) or not payload[
        "source_batch_id"
    ]:
        raise ValueError("realized outcome projection source_batch_id is required")
    return payload


__all__ = [
    "EVENT_COVERAGE_SCHEMA_VERSION",
    "OPPORTUNITY_PROJECTION_SCHEMA_VERSION",
    "OUTCOME_PROJECTION_SCHEMA_VERSION",
    "expected_qualification_predicate_version",
    "load_evaluation_opportunity_projection",
    "load_realized_outcome_projection",
    "load_verified_event_coverage",
    "outcome_runtime_cache_root",
    "validate_raw_metrics_realization_consistency",
    "validate_realized_outcome_metrics",
    "validate_evaluation_opportunity_members",
]
