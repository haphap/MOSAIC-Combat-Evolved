"""Private PIT sector snapshots exposed through zero-choice role tools.

The model cannot choose a sector, direction universe, ticker universe, or data
source.  Those are frozen by the runtime and validated here before any payload
crosses the bridge.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .cross_runtime_json import canonical_hash as _canonical_hash
from .exceptions import DataVendorUnavailable
from .role_events import (
    ROLE_EVENT_COVERAGE_VERSION,
    ROLE_EVENT_CURRENCIES,
    ROLE_EVENT_SNAPSHOT_VERSION,
    build_role_event_snapshot,
)

SECTOR_SNAPSHOT_SCHEMA_VERSION = "sector_research_snapshot_v4"
RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION = "relationship_research_snapshot_v2"
SECTOR_DIRECTION_CONTRACT_VERSION = "sector_direction_registry_v4"
SECTOR_MEMBERSHIP_MAX_STALENESS_DAYS = 10
SECTOR_MARKET_METRIC_MAX_STALENESS_DAYS = 10
SECTOR_FUNDAMENTAL_METRIC_MAX_STALENESS_DAYS = 150
SECTOR_ETF_SELECTION_MAX_STALENESS_DAYS = 31
SECTOR_SOURCE_RECEIPT_SCHEMA_VERSION = "sector_registered_source_receipt_v1"
SECTOR_REQUIRED_SOURCE_ENDPOINTS = frozenset(
    {
        "index_member_all",
        "daily",
        "adj_factor",
        "daily_basic",
        "income",
        "cashflow",
        "moneyflow",
    }
)
SECTOR_ETF_SOURCE_ENDPOINTS = frozenset(
    {"fund_basic", "fund_daily", "fund_adj", "fund_share", "fund_nav"}
)
SECTOR_UNIVERSE_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "prompt_checks"
    / "sector_universe_manifest_v1.json"
)
TUSHARE_ENDPOINT_PREFLIGHT_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "data_sources"
    / "tushare_endpoint_preflight_v2.json"
)


def _load_sector_universe_manifest(
    path: Path = SECTOR_UNIVERSE_MANIFEST_PATH,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"cannot load Sector universe manifest {path}: {exc}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "sector_universe_manifest_v1"
    ):
        raise RuntimeError("Sector universe manifest schema_version mismatch")
    content = {key: value for key, value in payload.items() if key != "manifest_hash"}
    if payload.get("manifest_hash") != _canonical_hash(content):
        raise RuntimeError("Sector universe manifest_hash mismatch")
    if payload.get("sector_count") != 9 or payload.get("direction_count") != 47:
        raise RuntimeError("Sector universe manifest roster count mismatch")
    metrics = payload.get("direction_metric_registry")
    if not isinstance(metrics, list) or len(metrics) != 26:
        raise RuntimeError("Sector metric registry must contain exactly 26 rows")
    if payload.get("direction_metric_registry_hash") != _canonical_hash(metrics):
        raise RuntimeError("Sector metric registry hash mismatch")
    metric_ids: set[str] = set()
    for metric in metrics:
        if not isinstance(metric, dict):
            raise RuntimeError("Sector metric contract must be an object")
        content = {
            key: value for key, value in metric.items() if key != "metric_contract_hash"
        }
        if metric.get("metric_contract_hash") != _canonical_hash(content):
            raise RuntimeError("Sector metric contract hash mismatch")
        metric_id = metric.get("metric_id")
        if not isinstance(metric_id, str) or not metric_id or metric_id in metric_ids:
            raise RuntimeError("Sector metric IDs must be non-empty and unique")
        metric_ids.add(metric_id)
    contracts = (
        ("direction_comparison_contract", "comparison_contract_hash"),
        ("direction_conflict_resolver_contract", "resolver_contract_hash"),
        ("security_scoring_contract", "scoring_contract_hash"),
        ("flow_coverage_contract", "contract_hash"),
    )
    for contract_name, hash_field in contracts:
        contract = payload.get(contract_name)
        if not isinstance(contract, dict):
            raise RuntimeError(f"Sector {contract_name} is missing")
        contract_body = {
            key: value for key, value in contract.items() if key != hash_field
        }
        if contract.get(hash_field) != _canonical_hash(contract_body):
            raise RuntimeError(f"Sector {contract_name} hash mismatch")
    scoring_contract = payload["security_scoring_contract"]
    scoring_compatibility = {
        "scoring_contract_id": "sector_security_scoring_v2",
        "scoring_contract_version": "sector_security_scoring_v2",
        "candidate_source": "PIT_DIRECTION_ELIGIBLE_SECURITY_SCORE_ROWS",
        "scoring_features": [
            "ADJUSTED_RETURN_20D",
            "REALIZED_VOLATILITY_20D",
            "MEDIAN_AMOUNT_20D_CNY",
            "NET_MONEYFLOW_20D_CNY",
        ],
        "required_source_endpoints": ["daily", "adj_factor", "moneyflow"],
        "required_observation_count": 20,
        "required_adjusted_close_observation_count": 21,
        "minimum_coverage_ratio": 1,
        "adjusted_return_formula": (
            "LATEST_ADJUSTED_CLOSE_DIV_LAG_20_ADJUSTED_CLOSE_MINUS_ONE"
        ),
        "realized_volatility_formula": (
            "SAMPLE_STDDEV_OF_20_ADJUSTED_SIMPLE_RETURNS_ANNUALIZED_SQRT_252"
        ),
        "median_amount_formula": "MEDIAN_LATEST_20_DAILY_AMOUNT_TIMES_1000_CNY",
        "net_moneyflow_formula": "SUM_LATEST_20_NET_MF_AMOUNT_TIMES_10000_CNY",
        "availability_rule": (
            "ALL_20_RETURN_INTERVALS_HAVE_DAILY_ADJ_FACTOR_AND_MONEYFLOW"
        ),
        "shortlist_order": "MEDIAN_AMOUNT_20D_CNY_DESC_THEN_TS_CODE_ASC",
        "shortlist_maximum_size_per_direction": 50,
        "model_pick_domain": "EXACT_FROZEN_SCORING_SHORTLIST",
    }
    if any(
        scoring_contract.get(key) != expected
        for key, expected in scoring_compatibility.items()
    ):
        raise RuntimeError("Sector security scoring contract semantics mismatch")
    plans = payload.get("membership_query_plans")
    if not isinstance(plans, list) or len(plans) != 9:
        raise RuntimeError("Sector membership query plan roster mismatch")
    plan_by_id: dict[str, dict[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            raise RuntimeError("Sector membership query plan must be an object")
        plan_content = {
            key: value for key, value in plan.items() if key != "query_plan_hash"
        }
        if plan.get("query_plan_hash") != _canonical_hash(plan_content):
            raise RuntimeError("Sector membership query plan hash mismatch")
        branches = plan.get("branches")
        if not isinstance(branches, list) or not branches:
            raise RuntimeError("Sector membership query plan branches are missing")
        branch_keys = {
            (
                branch.get("parameter"),
                branch.get("classification_code"),
                branch.get("is_new"),
            )
            for branch in branches
            if isinstance(branch, dict)
        }
        code_keys = {(parameter, code) for parameter, code, _is_new in branch_keys}
        if any(
            (parameter, code, "Y") not in branch_keys
            or (parameter, code, "N") not in branch_keys
            for parameter, code in code_keys
        ):
            raise RuntimeError(
                "Sector membership plans require paired is_new Y/N branches"
            )
        plan_id = plan.get("query_plan_id")
        if not isinstance(plan_id, str) or plan_id in plan_by_id:
            raise RuntimeError("Sector membership query_plan_id must be unique")
        plan_by_id[plan_id] = plan
    directions = payload.get("direction_contracts")
    if not isinstance(directions, list) or len(directions) != 47:
        raise RuntimeError("Sector direction contract roster mismatch")
    seen_directions: set[tuple[str, str]] = set()
    directions_by_role: dict[str, list[dict[str, Any]]] = {}
    for direction in directions:
        if not isinstance(direction, dict):
            raise RuntimeError("Sector direction contract must be an object")
        content = {
            key: value
            for key, value in direction.items()
            if key != "direction_contract_hash"
        }
        if direction.get("direction_contract_hash") != _canonical_hash(content):
            raise RuntimeError("Sector direction contract hash mismatch")
        key = (direction.get("sector_agent_id"), direction.get("direction_id"))
        if (
            not all(isinstance(value, str) and value for value in key)
            or key in seen_directions
        ):
            raise RuntimeError("Sector direction IDs must be non-empty and role-unique")
        seen_directions.add(key)
        directions_by_role.setdefault(key[0], []).append(direction)
        plan_id = direction.get("membership_query_plan_id")
        plan = plan_by_id.get(plan_id)
        if not plan or direction.get("membership_query_plan_hash") != plan.get(
            "query_plan_hash"
        ):
            raise RuntimeError("Sector direction membership plan binding mismatch")
        if (
            direction.get("direction_contract_version")
            != SECTOR_DIRECTION_CONTRACT_VERSION
        ):
            raise RuntimeError("Sector direction contract version mismatch")
    if set(directions_by_role) != set(payload.get("overlap_precedence", ())):
        raise RuntimeError("Sector direction roles do not match overlap precedence")
    for agent_id, role_directions in directions_by_role.items():
        if len(role_directions) < 3:
            raise RuntimeError(
                f"{agent_id} requires at least three registered directions"
            )
        plan = plan_by_id.get(f"sector-membership:{agent_id}")
        if plan is None:
            raise RuntimeError(f"{agent_id} membership query plan is missing")
        branch_codes = {
            branch["classification_code"]
            for branch in plan["branches"]
            if branch.get("is_new") == "Y"
        }
        partition_codes: set[str] = set()
        for direction in role_directions:
            included = direction.get("included_classification_codes")
            excluded = direction.get("excluded_classification_codes")
            if (
                not isinstance(included, list)
                or not included
                or not isinstance(excluded, list)
            ):
                raise RuntimeError(
                    "Sector direction partition definition is incomplete"
                )
            if partition_codes.intersection(included):
                raise RuntimeError(f"{agent_id} direction partitions overlap")
            partition_codes.update(included)
        if partition_codes != branch_codes:
            raise RuntimeError(
                f"{agent_id} directions do not fully partition the parent universe"
            )
    return payload


SECTOR_UNIVERSE_MANIFEST = _load_sector_universe_manifest()
SECTOR_DIRECTION_IDS: dict[str, tuple[str, ...]] = {
    agent_id: tuple(
        direction["direction_id"]
        for direction in SECTOR_UNIVERSE_MANIFEST["direction_contracts"]
        if direction["sector_agent_id"] == agent_id
    )
    for agent_id in SECTOR_UNIVERSE_MANIFEST["overlap_precedence"]
}


def sector_snapshot_root() -> Path:
    explicit = os.getenv("MOSAIC_SECTOR_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "sector_snapshots"


def _read(role: str, as_of_date: str, root: Path) -> Any:
    candidates = (
        root / as_of_date / f"{role}.json",
        root / f"{role}.{as_of_date}.json",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise DataVendorUnavailable(
            f"no private PIT sector snapshot for {role} on {as_of_date} under {root}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            f"cannot read sector snapshot {path}: {exc}"
        ) from exc


_SECTOR_SNAPSHOT_FIELDS = {
    "schema_version",
    "sector_universe_manifest_hash",
    "sector_agent_id",
    "as_of_date",
    "direction_contract_version",
    "direction_metric_registry_version",
    "direction_metric_registry_hash",
    "membership_query_plan_id",
    "membership_query_plan_version",
    "membership_query_plan_hash",
    "membership_pit_status",
    "membership_observed_at",
    "direction_ids",
    "direction_cards",
    "eligible_security_universe",
    "eligible_count",
    "membership_hash",
    "security_scoring_contract_version",
    "security_scoring_contract_hash",
    "security_scoring_rows",
    "security_scoring_rows_hash",
    "evidence_catalog",
    "snapshot_hash",
}
_OPTIONAL_SECTOR_SNAPSHOT_FIELDS = {"fixture_class"}
_ROLE_EVENT_SNAPSHOT_FIELDS = {
    "role_event_snapshot_id",
    "schema_version",
    "consumer_agent",
    "as_of",
    "contract_version",
    "coverage",
    "projections",
    "role_event_snapshot_hash",
}
_ROLE_EVENT_REF_FIELDS = {
    "role_event_snapshot_id",
    "role_event_snapshot_hash",
}
_SECURITY_FIELDS = {
    "ts_code",
    "direction_id",
    "l1_code",
    "l2_code",
    "l3_code",
    "in_date",
    "out_date",
    "released_at",
    "vintage_at",
    "pit_status",
    "evidence_ids",
    "membership_row_hash",
}
_SECURITY_SCORING_FIELDS = {
    "ts_code",
    "direction_id",
    "availability_status",
    "unavailability_reason",
    "observation_date",
    "released_at",
    "vintage_at",
    "pit_status",
    "adjusted_return_20d",
    "realized_volatility_20d",
    "median_amount_20d_cny",
    "net_moneyflow_20d_cny",
    "observation_count",
    "required_observation_count",
    "coverage_ratio",
    "evidence_ids",
    "security_scoring_row_hash",
}
_SECURITY_SCORING_UNAVAILABLE_REASONS = {
    "INSUFFICIENT_PIT_OBSERVATIONS",
    "MISSING_ADJUSTMENT_FACTOR",
    "MISSING_MONEYFLOW",
}
_EVIDENCE_FIELDS = {
    "evidence_id",
    "evidence_kind",
    "source_id",
    "source_endpoint",
    "observation_date",
    "released_at",
    "vintage_at",
    "pit_status",
    "content_hash",
    "evidence_record_hash",
}
_ETF_FAMILY_FIELDS = {
    "etf_family_id",
    "direction_id",
    "etf_ts_codes",
    "selection_date",
    "released_at",
    "vintage_at",
    "pit_status",
    "evidence_ids",
    "etf_family_hash",
}
_CARD_FIELDS = {
    "direction_id",
    "direction_contract_hash",
    "membership_query_plan_id",
    "membership_query_plan_hash",
    "eligible_count",
    "membership_hash",
    "readiness_status",
    "etf_family",
    "metrics",
    "evidence_ids",
    "direction_card_hash",
}
_METRIC_OBSERVATION_FIELDS = {
    "direction_id",
    "availability_status",
    "observation_date",
    "released_at",
    "vintage_at",
    "pit_status",
    "value",
    "observation_count",
    "eligible_count",
    "observed_count",
    "coverage_ratio",
    "etf_family_id",
    "etf_family_hash",
    "evidence_ids",
    "metric_observation_hash",
}
_SOURCE_BATCH_FIELDS = {
    "source_batch_id",
    "source_id",
    "endpoint",
    "schema_contract_version",
    "request",
    "captured_at",
    "released_at",
    "vintage_at",
    "pit_status",
    "pagination_complete",
    "truncated",
    "query_count",
    "completed_query_count",
    "coverage_ratio",
    "rows",
    "rows_hash",
    "source_batch_hash",
}
_SOURCE_BATCH_RECEIPT_FIELDS = _SOURCE_BATCH_FIELDS - {"rows"}
_SOURCE_RECEIPT_FIELDS = {
    "schema_version",
    "sector_agent_id",
    "as_of_date",
    "sector_snapshot_hash",
    "required_endpoints",
    "source_batches",
    "source_bundle_hash",
}


def _require_exact_fields(
    value: dict[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DataVendorUnavailable(
            f"{label} fields mismatch missing={missing} extra={extra}"
        )


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise DataVendorUnavailable(f"{label} must be a canonical sha256 hash")
    return value


def _parse_temporal(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DataVendorUnavailable(f"{label} must be an ISO date or timestamp")
    normalized = value.strip()
    try:
        if len(normalized) == 8 and normalized.isdigit():
            parsed = datetime.strptime(normalized, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        elif len(normalized) == 10:
            parsed = datetime.combine(
                date.fromisoformat(normalized), datetime.min.time(), timezone.utc
            )
        else:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"{label} is not a valid ISO date/timestamp"
        ) from exc
    return parsed


def _require_pit_temporals(
    value: dict[str, Any],
    as_of: date,
    label: str,
    observation_field: str = "observation_date",
) -> None:
    observation = _parse_temporal(
        value.get(observation_field), f"{label}.{observation_field}"
    )
    released = _parse_temporal(value.get("released_at"), f"{label}.released_at")
    vintage = _parse_temporal(value.get("vintage_at"), f"{label}.vintage_at")
    as_of_end = datetime.combine(as_of, datetime.max.time(), timezone.utc)
    if observation > released or released > vintage or vintage > as_of_end:
        raise DataVendorUnavailable(
            f"{label} violates observation <= release <= vintage <= as_of"
        )
    if value.get("pit_status") != "PIT_VERIFIED":
        raise DataVendorUnavailable(f"{label}.pit_status must be PIT_VERIFIED")


def _require_fresh_date(
    value: Any, as_of: date, max_staleness_days: int, label: str
) -> None:
    observed = _parse_temporal(value, label).date()
    age_days = (as_of - observed).days
    if age_days < 0 or age_days > max_staleness_days:
        raise DataVendorUnavailable(
            f"{label} is stale: age_days={age_days} max={max_staleness_days}"
        )


def _require_hash_binding(value: dict[str, Any], hash_field: str, label: str) -> None:
    supplied = _require_sha256(value.get(hash_field), f"{label}.{hash_field}")
    body = {key: item for key, item in value.items() if key != hash_field}
    if supplied != _canonical_hash(body):
        raise DataVendorUnavailable(f"{label}.{hash_field} mismatch")


def _require_id_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise DataVendorUnavailable(
            f"{label} must be a {'possibly empty ' if allow_empty else ''}array"
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise DataVendorUnavailable(f"{label} values must be non-empty strings")
    if len(set(value)) != len(value) or value != sorted(value):
        raise DataVendorUnavailable(f"{label} must be unique and canonically ordered")
    return value


def _manifest_bindings(role: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    plan = next(
        (
            row
            for row in SECTOR_UNIVERSE_MANIFEST["membership_query_plans"]
            if row["sector_agent_id"] == role
        ),
        None,
    )
    if plan is None:
        raise DataVendorUnavailable(f"{role} membership plan is not registered")
    directions = {
        row["direction_id"]: row
        for row in SECTOR_UNIVERSE_MANIFEST["direction_contracts"]
        if row["sector_agent_id"] == role
    }
    return plan, directions


def _direction_for_security(
    security: dict[str, Any], direction_contracts: dict[str, dict[str, Any]]
) -> str:
    classification_values = {
        value
        for field in ("l1_code", "l2_code", "l3_code")
        if isinstance((value := security.get(field)), str) and value
    }
    matches = []
    for direction_id, contract in direction_contracts.items():
        included = set(contract["included_classification_codes"])
        excluded = set(contract["excluded_classification_codes"])
        if classification_values.intersection(
            included
        ) and not classification_values.intersection(excluded):
            matches.append(direction_id)
    if len(matches) != 1:
        raise DataVendorUnavailable(
            "sector security does not map to exactly one direction partition"
        )
    return matches[0]


def _validate_evidence_catalog(
    value: Any, as_of: date
) -> tuple[list[dict[str, Any]], set[str]]:
    if not isinstance(value, list) or not value:
        raise DataVendorUnavailable("sector evidence_catalog must be non-empty")
    ids: set[str] = set()
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise DataVendorUnavailable("sector evidence rows must be objects")
        _require_exact_fields(row, _EVIDENCE_FIELDS, f"evidence_catalog[{index}]")
        evidence_id = row.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in ids:
            raise DataVendorUnavailable(
                "sector evidence ids must be non-empty and unique"
            )
        ids.add(evidence_id)
        for field in ("evidence_kind", "source_id", "source_endpoint"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise DataVendorUnavailable(
                    f"evidence_catalog[{index}].{field} is required"
                )
        _require_sha256(
            row.get("content_hash"), f"evidence_catalog[{index}].content_hash"
        )
        _require_hash_binding(row, "evidence_record_hash", f"evidence_catalog[{index}]")
        _require_pit_temporals(row, as_of, f"evidence_catalog[{index}]")
    if [row["evidence_id"] for row in value] != sorted(ids):
        raise DataVendorUnavailable(
            "sector evidence_catalog must be canonically ordered"
        )
    return value, ids


def validate_sector_snapshot(
    payload: Any, role: str, as_of_date: str
) -> dict[str, Any]:
    if role not in SECTOR_DIRECTION_IDS:
        raise DataVendorUnavailable(f"unknown standard sector role {role!r}")
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("sector snapshot must be an object")
    expected_fields = set(_SECTOR_SNAPSHOT_FIELDS)
    if "fixture_class" in payload:
        expected_fields.update(_OPTIONAL_SECTOR_SNAPSHOT_FIELDS)
        if payload.get("fixture_class") != "SYNTHETIC_NON_PRODUCTION":
            raise DataVendorUnavailable("sector fixture_class is invalid")
    _require_exact_fields(payload, expected_fields, "sector snapshot")
    if payload.get("schema_version") != SECTOR_SNAPSHOT_SCHEMA_VERSION:
        raise DataVendorUnavailable("sector snapshot schema_version mismatch")
    if (
        payload.get("sector_agent_id") != role
        or payload.get("as_of_date") != as_of_date
    ):
        raise DataVendorUnavailable("sector snapshot role/as_of mismatch")
    try:
        as_of = date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise DataVendorUnavailable("sector snapshot as_of_date is invalid") from exc
    if payload.get("direction_contract_version") != SECTOR_DIRECTION_CONTRACT_VERSION:
        raise DataVendorUnavailable("sector direction contract version mismatch")
    if (
        payload.get("sector_universe_manifest_hash")
        != SECTOR_UNIVERSE_MANIFEST["manifest_hash"]
    ):
        raise DataVendorUnavailable("sector universe manifest hash mismatch")
    if (
        payload.get("direction_metric_registry_version")
        != SECTOR_UNIVERSE_MANIFEST["direction_metric_registry_version"]
        or payload.get("direction_metric_registry_hash")
        != SECTOR_UNIVERSE_MANIFEST["direction_metric_registry_hash"]
    ):
        raise DataVendorUnavailable("sector metric registry binding mismatch")
    plan, direction_contracts = _manifest_bindings(role)
    plan_bindings = {
        "membership_query_plan_id": "query_plan_id",
        "membership_query_plan_version": "query_plan_version",
        "membership_query_plan_hash": "query_plan_hash",
    }
    for snapshot_field, manifest_field in plan_bindings.items():
        if payload.get(snapshot_field) != plan.get(manifest_field):
            raise DataVendorUnavailable(f"sector {snapshot_field} binding mismatch")
    if payload.get("membership_pit_status") != "PIT_VERIFIED":
        raise DataVendorUnavailable("sector membership_pit_status must be PIT_VERIFIED")
    _require_fresh_date(
        payload.get("membership_observed_at"),
        as_of,
        SECTOR_MEMBERSHIP_MAX_STALENESS_DAYS,
        "membership_observed_at",
    )
    expected_directions = SECTOR_DIRECTION_IDS[role]
    if (
        len(expected_directions) < 3
        or tuple(payload.get("direction_ids", ())) != expected_directions
    ):
        raise DataVendorUnavailable(f"{role} direction registry mismatch")

    evidence_catalog, evidence_catalog_ids = _validate_evidence_catalog(
        payload.get("evidence_catalog"), as_of
    )
    referenced_evidence: set[str] = set()
    universe = payload.get("eligible_security_universe")
    if not isinstance(universe, list) or not universe:
        raise DataVendorUnavailable(
            "eligible_security_universe must be a non-empty array"
        )
    if payload.get("eligible_count") != len(universe):
        raise DataVendorUnavailable(
            "sector eligible_count does not match membership rows"
        )
    seen_tickers: set[str] = set()
    members_by_direction: dict[str, list[dict[str, Any]]] = {
        direction_id: [] for direction_id in expected_directions
    }
    for index, security in enumerate(universe):
        if not isinstance(security, dict):
            raise DataVendorUnavailable("sector security rows must be objects")
        _require_exact_fields(
            security, _SECURITY_FIELDS, f"eligible_security_universe[{index}]"
        )
        _require_hash_binding(
            security, "membership_row_hash", f"eligible_security_universe[{index}]"
        )
        ts_code = security.get("ts_code")
        if (
            not isinstance(ts_code, str)
            or len(ts_code) != 9
            or ts_code[6:] not in {".SH", ".SZ", ".BJ"}
            or not ts_code[:6].isdigit()
        ):
            raise DataVendorUnavailable("sector security ts_code is invalid")
        if ts_code in seen_tickers:
            raise DataVendorUnavailable(f"duplicate sector security {ts_code}")
        seen_tickers.add(ts_code)
        for level_field, prefix in (
            ("l1_code", "801"),
            ("l2_code", "801"),
            ("l3_code", "850"),
        ):
            value = security.get(level_field)
            if value is not None and (
                not isinstance(value, str)
                or len(value) != 9
                or not value.startswith(prefix)
                or not value[3:6].isdigit()
                or not value.endswith(".SI")
            ):
                raise DataVendorUnavailable(f"sector security {level_field} is invalid")
        expected_direction = _direction_for_security(security, direction_contracts)
        if security.get("direction_id") != expected_direction:
            raise DataVendorUnavailable("sector security direction identity mismatch")
        in_date = _parse_temporal(
            security.get("in_date"), f"security[{ts_code}].in_date"
        )
        if in_date.date() > as_of:
            raise DataVendorUnavailable("future sector member entered the PIT universe")
        out_date_value = security.get("out_date")
        if (
            out_date_value is not None
            and _parse_temporal(out_date_value, f"security[{ts_code}].out_date").date()
            <= as_of
        ):
            raise DataVendorUnavailable(
                "departed sector member entered the PIT universe"
            )
        _require_pit_temporals(
            {**security, "observation_date": security["in_date"]},
            as_of,
            f"security[{ts_code}]",
        )
        refs = _require_id_list(
            security.get("evidence_ids"), f"security[{ts_code}].evidence_ids"
        )
        referenced_evidence.update(refs)
        members_by_direction[expected_direction].append(security)
    if universe != sorted(
        universe, key=lambda row: (row["direction_id"], row["ts_code"])
    ):
        raise DataVendorUnavailable(
            "eligible_security_universe must be canonically ordered"
        )
    if any(not rows for rows in members_by_direction.values()):
        raise DataVendorUnavailable(
            "every registered direction requires at least one eligible member"
        )
    if payload.get("membership_hash") != _canonical_hash(universe):
        raise DataVendorUnavailable("sector membership_hash mismatch")

    scoring_contract = SECTOR_UNIVERSE_MANIFEST["security_scoring_contract"]
    if (
        payload.get("security_scoring_contract_version")
        != scoring_contract["scoring_contract_version"]
        or payload.get("security_scoring_contract_hash")
        != scoring_contract["scoring_contract_hash"]
    ):
        raise DataVendorUnavailable("sector security scoring contract binding mismatch")
    scoring_rows = payload.get("security_scoring_rows")
    if not isinstance(scoring_rows, list) or not scoring_rows:
        raise DataVendorUnavailable("security_scoring_rows must be a non-empty array")
    if payload.get("security_scoring_rows_hash") != _canonical_hash(scoring_rows):
        raise DataVendorUnavailable("sector security_scoring_rows_hash mismatch")
    required_observations = scoring_contract["required_observation_count"]
    expected_security_keys = {
        (member["direction_id"], member["ts_code"]) for member in universe
    }
    observed_security_keys: set[tuple[str, str]] = set()
    evidence_endpoint_by_id = {
        evidence["evidence_id"]: evidence["source_endpoint"]
        for evidence in evidence_catalog
    }
    for index, row in enumerate(scoring_rows):
        if not isinstance(row, dict):
            raise DataVendorUnavailable("sector security scoring rows must be objects")
        label = f"security_scoring_rows[{index}]"
        _require_exact_fields(row, _SECURITY_SCORING_FIELDS, label)
        _require_hash_binding(row, "security_scoring_row_hash", label)
        key = (row.get("direction_id"), row.get("ts_code"))
        if key not in expected_security_keys or key in observed_security_keys:
            raise DataVendorUnavailable(
                "sector security scoring rows must map one-to-one to eligible members"
            )
        observed_security_keys.add(key)
        _require_pit_temporals(row, as_of, label)
        _require_fresh_date(
            row["vintage_at"],
            as_of,
            SECTOR_MARKET_METRIC_MAX_STALENESS_DAYS,
            f"{label}.vintage_at",
        )
        observation_count = row.get("observation_count")
        required_count = row.get("required_observation_count")
        coverage_ratio = row.get("coverage_ratio")
        if (
            isinstance(observation_count, bool)
            or not isinstance(observation_count, int)
            or observation_count < 0
            or observation_count > required_observations
            or required_count != required_observations
            or isinstance(coverage_ratio, bool)
            or not isinstance(coverage_ratio, (int, float))
            or not math.isfinite(float(coverage_ratio))
            or not math.isclose(
                float(coverage_ratio),
                observation_count / required_observations,
                abs_tol=1e-12,
            )
        ):
            raise DataVendorUnavailable(
                "sector security scoring observation coverage is invalid"
            )
        refs = _require_id_list(row.get("evidence_ids"), f"{label}.evidence_ids")
        referenced_evidence.update(refs)
        metrics = (
            row.get("adjusted_return_20d"),
            row.get("realized_volatility_20d"),
            row.get("median_amount_20d_cny"),
            row.get("net_moneyflow_20d_cny"),
        )
        availability = row.get("availability_status")
        reason = row.get("unavailability_reason")
        if availability == "AVAILABLE":
            if reason is not None or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in metrics
            ):
                raise DataVendorUnavailable(
                    "available security scoring row lacks finite metrics"
                )
            if (
                float(row["realized_volatility_20d"]) < 0
                or float(row["median_amount_20d_cny"]) < 0
                or observation_count != required_count
                or not math.isclose(float(coverage_ratio), 1.0, abs_tol=1e-12)
            ):
                raise DataVendorUnavailable(
                    "available security scoring row fails readiness"
                )
            if "fixture_class" not in payload:
                endpoint_closure = {evidence_endpoint_by_id.get(ref) for ref in refs}
                required_endpoints = set(scoring_contract["required_source_endpoints"])
                if not required_endpoints.issubset(endpoint_closure):
                    raise DataVendorUnavailable(
                        "available security scoring row lacks registered endpoint evidence"
                    )
        elif availability == "UNAVAILABLE":
            if reason not in _SECURITY_SCORING_UNAVAILABLE_REASONS or any(
                value is not None for value in metrics
            ):
                raise DataVendorUnavailable(
                    "unavailable security scoring row violates null metric semantics"
                )
            if (
                reason == "INSUFFICIENT_PIT_OBSERVATIONS"
                and observation_count >= required_count
            ):
                raise DataVendorUnavailable(
                    "insufficient-observation scoring row has a complete observation count"
                )
        else:
            raise DataVendorUnavailable(
                "security scoring availability_status is invalid"
            )
    if observed_security_keys != expected_security_keys:
        raise DataVendorUnavailable(
            "sector security scoring rows must map one-to-one to eligible members"
        )
    if scoring_rows != sorted(
        scoring_rows, key=lambda row: (row["direction_id"], row["ts_code"])
    ):
        raise DataVendorUnavailable("security_scoring_rows must be canonically ordered")

    cards = payload.get("direction_cards")
    if not isinstance(cards, list) or [
        card.get("direction_id") if isinstance(card, dict) else None for card in cards
    ] != list(expected_directions):
        raise DataVendorUnavailable(
            "sector snapshot requires one ordered card per direction"
        )
    expected_metrics = SECTOR_UNIVERSE_MANIFEST["direction_metric_registry"]
    for card_index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise DataVendorUnavailable("sector direction cards must be objects")
        _require_exact_fields(card, _CARD_FIELDS, f"direction_cards[{card_index}]")
        _require_hash_binding(
            card, "direction_card_hash", f"direction_cards[{card_index}]"
        )
        direction_id = card["direction_id"]
        contract = direction_contracts[direction_id]
        if (
            card.get("direction_contract_hash") != contract["direction_contract_hash"]
            or card.get("membership_query_plan_id") != plan["query_plan_id"]
            or card.get("membership_query_plan_hash") != plan["query_plan_hash"]
        ):
            raise DataVendorUnavailable(
                "sector direction card contract binding mismatch"
            )
        direction_members = members_by_direction[direction_id]
        if card.get("eligible_count") != len(direction_members):
            raise DataVendorUnavailable("sector direction eligible_count mismatch")
        if card.get("membership_hash") != _canonical_hash(direction_members):
            raise DataVendorUnavailable("sector direction membership_hash mismatch")
        if card.get("readiness_status") != "READY":
            raise DataVendorUnavailable(
                "sector directions must be READY before model analysis"
            )
        etf_family = card.get("etf_family")
        if not isinstance(etf_family, dict):
            raise DataVendorUnavailable("sector etf_family must be an object")
        _require_exact_fields(
            etf_family, _ETF_FAMILY_FIELDS, f"direction_cards[{card_index}].etf_family"
        )
        _require_hash_binding(
            etf_family, "etf_family_hash", f"direction_cards[{card_index}].etf_family"
        )
        expected_family_id = f"sector-etf:{role}:{direction_id}"
        if (
            etf_family.get("direction_id") != direction_id
            or etf_family.get("etf_family_id") != expected_family_id
        ):
            raise DataVendorUnavailable("sector ETF family direction identity mismatch")
        etf_codes = _require_id_list(
            etf_family.get("etf_ts_codes"),
            f"direction_cards[{card_index}].etf_family.etf_ts_codes",
            allow_empty=True,
        )
        if any(
            len(code) != 9 or not code[:6].isdigit() or code[6:] not in {".SH", ".SZ"}
            for code in etf_codes
        ):
            raise DataVendorUnavailable(
                "sector ETF family contains an invalid ETF code"
            )
        _require_pit_temporals(
            {**etf_family, "observation_date": etf_family["selection_date"]},
            as_of,
            f"direction_cards[{card_index}].etf_family",
        )
        _require_fresh_date(
            etf_family["selection_date"],
            as_of,
            SECTOR_ETF_SELECTION_MAX_STALENESS_DAYS,
            f"direction_cards[{card_index}].etf_family.selection_date",
        )
        family_refs = _require_id_list(
            etf_family.get("evidence_ids"),
            f"direction_cards[{card_index}].etf_family.evidence_ids",
        )
        referenced_evidence.update(family_refs)

        metrics = card.get("metrics")
        if not isinstance(metrics, list) or [
            metric.get("metric_id") if isinstance(metric, dict) else None
            for metric in metrics
        ] != [metric["metric_id"] for metric in expected_metrics]:
            raise DataVendorUnavailable(
                "sector card metrics must exactly match the metric registry"
            )
        card_refs: set[str] = set(family_refs)
        card_refs.update(
            evidence_id
            for member in direction_members
            for evidence_id in member["evidence_ids"]
        )
        for metric_index, (metric_row, metric_contract) in enumerate(
            zip(metrics, expected_metrics, strict=True)
        ):
            if not isinstance(metric_row, dict):
                raise DataVendorUnavailable("sector metric rows must be objects")
            expected_fields = set(metric_contract) | _METRIC_OBSERVATION_FIELDS
            _require_exact_fields(
                metric_row,
                expected_fields,
                f"direction_cards[{card_index}].metrics[{metric_index}]",
            )
            _require_hash_binding(
                metric_row,
                "metric_observation_hash",
                f"direction_cards[{card_index}].metrics[{metric_index}]",
            )
            if any(
                metric_row.get(key) != value for key, value in metric_contract.items()
            ):
                raise DataVendorUnavailable("sector metric contract semantics mismatch")
            if metric_row.get("direction_id") != direction_id:
                raise DataVendorUnavailable("sector metric direction identity mismatch")
            _require_pit_temporals(
                metric_row,
                as_of,
                f"direction_cards[{card_index}].metrics[{metric_index}]",
            )
            metric_max_age = (
                SECTOR_FUNDAMENTAL_METRIC_MAX_STALENESS_DAYS
                if metric_contract["metric_family"] == "FUNDAMENTALS"
                else SECTOR_MARKET_METRIC_MAX_STALENESS_DAYS
            )
            _require_fresh_date(
                metric_row["vintage_at"],
                as_of,
                metric_max_age,
                f"direction_cards[{card_index}].metrics[{metric_index}].vintage_at",
            )
            availability = metric_row.get("availability_status")
            if availability not in {"AVAILABLE", "UNAVAILABLE"}:
                raise DataVendorUnavailable(
                    "sector metric availability_status is invalid"
                )
            is_etf = metric_contract["metric_family"] == "ETF_CONFIRMATION"
            if is_etf:
                if (
                    metric_row.get("etf_family_id") != expected_family_id
                    or metric_row.get("etf_family_hash")
                    != etf_family["etf_family_hash"]
                    or metric_row.get("eligible_count") != len(etf_codes)
                ):
                    raise DataVendorUnavailable(
                        "sector ETF metric family binding mismatch"
                    )
            elif (
                metric_row.get("etf_family_id") is not None
                or metric_row.get("etf_family_hash") is not None
                or metric_row.get("eligible_count") != len(direction_members)
            ):
                raise DataVendorUnavailable(
                    "sector constituent metric membership binding mismatch"
                )
            observation_count = metric_row.get("observation_count")
            observed_count = metric_row.get("observed_count")
            eligible_count = metric_row.get("eligible_count")
            coverage_ratio = metric_row.get("coverage_ratio")
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (observation_count, observed_count, eligible_count)
            ):
                raise DataVendorUnavailable(
                    "sector metric counts must be non-negative integers"
                )
            if observed_count > eligible_count:
                raise DataVendorUnavailable(
                    "sector metric observed_count exceeds eligible_count"
                )
            if isinstance(coverage_ratio, bool) or not isinstance(
                coverage_ratio, (int, float)
            ):
                raise DataVendorUnavailable(
                    "sector metric coverage_ratio must be numeric"
                )
            expected_coverage = (
                observed_count / eligible_count if eligible_count else 0.0
            )
            if not math.isfinite(float(coverage_ratio)) or not math.isclose(
                float(coverage_ratio), expected_coverage, abs_tol=1e-9
            ):
                raise DataVendorUnavailable(
                    "sector metric coverage_ratio is inconsistent"
                )
            value = metric_row.get("value")
            if availability == "AVAILABLE":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or observation_count < metric_contract["minimum_observations"]
                    or coverage_ratio < metric_contract["minimum_coverage_ratio"]
                    or eligible_count == 0
                ):
                    raise DataVendorUnavailable(
                        "available sector metric fails value/coverage readiness"
                    )
            elif (
                metric_contract["required_for_direction_readiness"]
                or value is not None
                or observation_count != 0
                or observed_count != 0
                or coverage_ratio != 0
            ):
                raise DataVendorUnavailable(
                    "unavailable sector metric violates readiness semantics"
                )
            metric_refs = _require_id_list(
                metric_row.get("evidence_ids"),
                f"direction_cards[{card_index}].metrics[{metric_index}].evidence_ids",
            )
            card_refs.update(metric_refs)
            referenced_evidence.update(metric_refs)
        declared_card_refs = _require_id_list(
            card.get("evidence_ids"), f"direction_cards[{card_index}].evidence_ids"
        )
        if declared_card_refs != sorted(card_refs):
            raise DataVendorUnavailable(
                "sector direction card evidence closure mismatch"
            )
        referenced_evidence.update(declared_card_refs)

    unknown_evidence = referenced_evidence - evidence_catalog_ids
    orphan_evidence = evidence_catalog_ids - referenced_evidence
    if unknown_evidence or orphan_evidence:
        raise DataVendorUnavailable(
            f"sector evidence closure mismatch unknown={sorted(unknown_evidence)} orphan={sorted(orphan_evidence)}"
        )
    _require_hash_binding(payload, "snapshot_hash", "sector snapshot")
    return {key: payload[key] for key in payload}


def _registered_tushare_endpoint_contracts() -> dict[str, dict[str, Any]]:
    try:
        artifact = json.loads(
            TUSHARE_ENDPOINT_PREFLIGHT_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            f"cannot read Tushare endpoint registry: {exc}"
        ) from exc
    if not isinstance(artifact, dict) or artifact.get("schema_version") != (
        "tushare_endpoint_preflight_v2"
    ):
        raise DataVendorUnavailable("Tushare endpoint registry version mismatch")
    artifact_body = {
        key: value for key, value in artifact.items() if key != "artifact_hash"
    }
    if artifact.get("artifact_hash") != _canonical_hash(artifact_body):
        raise DataVendorUnavailable("Tushare endpoint registry hash mismatch")
    required = SECTOR_REQUIRED_SOURCE_ENDPOINTS | SECTOR_ETF_SOURCE_ENDPOINTS
    contracts = {
        str(row["endpoint"]): row
        for row in artifact.get("checks", [])
        if isinstance(row, dict) and row.get("endpoint") in required
    }
    if set(contracts) != required:
        raise DataVendorUnavailable("registered sector endpoint closure is incomplete")
    return contracts


def _validate_source_batch(
    value: Any,
    *,
    as_of: date,
    endpoint_contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DataVendorUnavailable("sector source batches must be objects")
    _require_exact_fields(value, _SOURCE_BATCH_FIELDS, "sector source batch")
    endpoint = value.get("endpoint")
    contract = endpoint_contracts.get(endpoint)
    if contract is None or value.get("source_id") != f"tushare.{endpoint}":
        raise DataVendorUnavailable("sector source batch route is not registered")
    if value.get("schema_contract_version") != contract.get("schema_contract_version"):
        raise DataVendorUnavailable("sector source batch schema contract mismatch")
    if not isinstance(value.get("request"), dict):
        raise DataVendorUnavailable("sector source batch request must be an object")
    if any(
        key.casefold() in {"token", "api_key", "authorization"}
        for key in value["request"]
    ):
        raise DataVendorUnavailable("sector source batch request contains credentials")
    released = _parse_temporal(value.get("released_at"), "source batch released_at")
    vintage = _parse_temporal(value.get("vintage_at"), "source batch vintage_at")
    captured = _parse_temporal(value.get("captured_at"), "source batch captured_at")
    as_of_end = datetime.combine(as_of, datetime.max.time(), timezone.utc)
    if not released <= vintage <= captured <= as_of_end:
        raise DataVendorUnavailable(
            "sector source batch violates release <= vintage <= capture <= as_of"
        )
    if value.get("pit_status") != "PIT_VERIFIED":
        raise DataVendorUnavailable("sector source batch must be PIT_VERIFIED")
    if (
        value.get("pagination_complete") is not True
        or value.get("truncated") is not False
    ):
        raise DataVendorUnavailable("sector source batch pagination is incomplete")
    query_count = value.get("query_count")
    completed_count = value.get("completed_query_count")
    coverage_ratio = value.get("coverage_ratio")
    if (
        isinstance(query_count, bool)
        or not isinstance(query_count, int)
        or query_count < 1
        or isinstance(completed_count, bool)
        or not isinstance(completed_count, int)
        or completed_count < 0
        or completed_count > query_count
        or isinstance(coverage_ratio, bool)
        or not isinstance(coverage_ratio, (int, float))
        or not math.isfinite(float(coverage_ratio))
        or not math.isclose(
            float(coverage_ratio), completed_count / query_count, abs_tol=1e-12
        )
        or float(coverage_ratio) < 0.9
    ):
        raise DataVendorUnavailable("sector source batch coverage is below 90%")
    rows = value.get("rows")
    expected_columns = set(contract.get("expected_columns", ()))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise DataVendorUnavailable("sector source batch rows must be objects")
    for row in rows:
        if not expected_columns.issubset(row):
            raise DataVendorUnavailable(
                f"sector source batch {endpoint} row schema is incomplete"
            )
        for field in (
            "trade_date",
            "ann_date",
            "f_ann_date",
            "nav_date",
            "end_date",
        ):
            temporal = row.get(field)
            if (
                temporal not in (None, "")
                and _parse_temporal(temporal, f"source batch {endpoint}.{field}").date()
                > as_of
            ):
                raise DataVendorUnavailable(
                    f"sector source batch {endpoint} contains future {field}"
                )
    request_end = value["request"].get("end_date")
    if (
        request_end not in (None, "")
        and _parse_temporal(request_end, "source batch request.end_date").date() > as_of
    ):
        raise DataVendorUnavailable("sector source batch request crosses as_of")
    if value.get("rows_hash") != _canonical_hash(rows):
        raise DataVendorUnavailable("sector source batch rows_hash mismatch")
    batch_body = {
        key: item
        for key, item in value.items()
        if key not in {"source_batch_id", "source_batch_hash", "rows"}
    }
    expected_batch_hash = _canonical_hash(batch_body)
    if value.get("source_batch_hash") != expected_batch_hash:
        raise DataVendorUnavailable("sector source batch hash mismatch")
    expected_batch_id = "sector-source-batch:" + expected_batch_hash.removeprefix(
        "sha256:"
    )
    if value.get("source_batch_id") != expected_batch_id:
        raise DataVendorUnavailable("sector source batch ID mismatch")
    return {key: value[key] for key in value}


def _required_sector_endpoints(snapshot: Mapping[str, Any]) -> frozenset[str]:
    etf_required = any(
        bool(card["etf_family"]["etf_ts_codes"])
        or any(
            metric["metric_family"] == "ETF_CONFIRMATION"
            and metric["availability_status"] == "AVAILABLE"
            for metric in card["metrics"]
        )
        for card in snapshot["direction_cards"]
    )
    return SECTOR_REQUIRED_SOURCE_ENDPOINTS | (
        SECTOR_ETF_SOURCE_ENDPOINTS if etf_required else frozenset()
    )


def _validate_membership_batches(
    *,
    role: str,
    as_of: date,
    snapshot: Mapping[str, Any],
    batches: list[dict[str, Any]],
) -> None:
    def membership_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        in_value = row.get("in_date")
        out_value = row.get("out_date")
        return (
            row.get("l1_code"),
            row.get("l2_code"),
            row.get("l3_code"),
            row.get("ts_code"),
            _parse_temporal(in_value, "sector membership key.in_date")
            .date()
            .isoformat(),
            (
                _parse_temporal(out_value, "sector membership key.out_date")
                .date()
                .isoformat()
                if out_value not in (None, "")
                else None
            ),
        )

    plan, direction_contracts = _manifest_bindings(role)
    membership_batches = [
        batch for batch in batches if batch["endpoint"] == "index_member_all"
    ]
    required_branches = {
        (
            branch["parameter"],
            branch["classification_code"],
            branch["is_new"],
        )
        for branch in plan["branches"]
    }
    observed_branches: set[tuple[str, str, str]] = set()
    reconstructed: dict[tuple[Any, ...], dict[str, Any]] = {}
    for batch in membership_batches:
        request = batch["request"]
        if (
            set(request)
            != {
                "query_plan_hash",
                "parameter",
                "classification_code",
                "is_new",
            }
            or request.get("query_plan_hash") != plan["query_plan_hash"]
        ):
            raise DataVendorUnavailable(
                "sector membership source batch request is not plan-bound"
            )
        branch = (
            request["parameter"],
            request["classification_code"],
            request["is_new"],
        )
        if branch not in required_branches or branch in observed_branches:
            raise DataVendorUnavailable(
                "sector membership source batch has an unknown or duplicate branch"
            )
        observed_branches.add(branch)
        for row in batch["rows"]:
            if (
                row.get(request["parameter"]) != request["classification_code"]
                or row.get("is_new") != request["is_new"]
            ):
                raise DataVendorUnavailable(
                    "sector membership row is outside its registered branch"
                )
            in_date = _parse_temporal(
                row.get("in_date"), "sector membership row.in_date"
            ).date()
            out_value = row.get("out_date")
            out_date = (
                _parse_temporal(out_value, "sector membership row.out_date").date()
                if out_value not in (None, "")
                else None
            )
            if in_date > as_of or (out_date is not None and out_date <= as_of):
                continue
            key = membership_key(row)
            reconstructed[key] = row
    if observed_branches != required_branches:
        raise DataVendorUnavailable("sector membership source branches are incomplete")

    expected_keys = {
        membership_key(row) for row in snapshot["eligible_security_universe"]
    }
    if set(reconstructed) != expected_keys:
        raise DataVendorUnavailable(
            "sector snapshot membership does not equal the registered PIT branches"
        )
    for row in reconstructed.values():
        _direction_for_security(row, direction_contracts)


def _finite_source_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validate_security_scoring_batches(
    *, snapshot: Mapping[str, Any], batches: list[dict[str, Any]], as_of: date
) -> None:
    scoring_batches = {
        endpoint: [batch for batch in batches if batch["endpoint"] == endpoint]
        for endpoint in ("daily", "adj_factor", "moneyflow")
    }
    indexed: dict[str, dict[tuple[str, date], dict[str, Any]]] = {}
    for endpoint, endpoint_batches in scoring_batches.items():
        rows_by_key: dict[tuple[str, date], dict[str, Any]] = {}
        for batch in endpoint_batches:
            for row in batch["rows"]:
                ts_code = row.get("ts_code")
                trade_date = _parse_temporal(
                    row.get("trade_date"), f"sector {endpoint} scoring row.trade_date"
                ).date()
                key = (ts_code, trade_date)
                if not isinstance(ts_code, str) or key in rows_by_key:
                    raise DataVendorUnavailable(
                        f"sector {endpoint} scoring rows contain a duplicate or invalid key"
                    )
                rows_by_key[key] = row
        indexed[endpoint] = rows_by_key

    released_at = max(
        _parse_temporal(batch["released_at"], "sector scoring batch.released_at")
        for endpoint_batches in scoring_batches.values()
        for batch in endpoint_batches
    )
    vintage_at = max(
        _parse_temporal(batch["vintage_at"], "sector scoring batch.vintage_at")
        for endpoint_batches in scoring_batches.values()
        for batch in endpoint_batches
    )
    scoring_by_ticker = {
        row["ts_code"]: row for row in snapshot["security_scoring_rows"]
    }
    for member in snapshot["eligible_security_universe"]:
        ts_code = member["ts_code"]
        submitted = scoring_by_ticker[ts_code]
        daily_rows = sorted(
            (
                (trade_date, row)
                for (row_ts_code, trade_date), row in indexed["daily"].items()
                if row_ts_code == ts_code and trade_date <= as_of
            ),
            key=lambda item: item[0],
        )
        latest = daily_rows[-21:]
        latest_dates = [trade_date for trade_date, _row in latest]
        interval_dates = latest_dates[1:]
        adj_by_date = {
            trade_date: row
            for (row_ts_code, trade_date), row in indexed["adj_factor"].items()
            if row_ts_code == ts_code and trade_date <= as_of
        }
        flow_by_date = {
            trade_date: row
            for (row_ts_code, trade_date), row in indexed["moneyflow"].items()
            if row_ts_code == ts_code and trade_date <= as_of
        }
        daily_by_date = dict(latest)

        complete_intervals = 0
        if len(latest) >= 2:
            for prior_date, current_date in zip(
                latest_dates[:-1], interval_dates, strict=True
            ):
                prior_daily = daily_by_date[prior_date]
                current_daily = daily_by_date[current_date]
                prior_adj = adj_by_date.get(prior_date)
                current_adj = adj_by_date.get(current_date)
                flow = flow_by_date.get(current_date)
                complete = (
                    _finite_source_number(prior_daily.get("close")) is not None
                    and _finite_source_number(current_daily.get("close")) is not None
                    and _finite_source_number(current_daily.get("amount")) is not None
                    and prior_adj is not None
                    and _finite_source_number(prior_adj.get("adj_factor")) is not None
                    and current_adj is not None
                    and _finite_source_number(current_adj.get("adj_factor")) is not None
                    and flow is not None
                    and _finite_source_number(flow.get("net_mf_amount")) is not None
                )
                complete_intervals += int(complete)
        observation_count = min(20, complete_intervals)
        expected_common = {
            "observation_count": observation_count,
            "required_observation_count": 20,
            "coverage_ratio": observation_count / 20,
        }

        invalid_daily = len(latest) != 21 or any(
            _finite_source_number(row.get("close")) is None
            or _finite_source_number(row.get("amount")) is None
            for _trade_date, row in latest
        )
        missing_adj = len(latest) == 21 and any(
            trade_date not in adj_by_date
            or _finite_source_number(adj_by_date[trade_date].get("adj_factor")) is None
            for trade_date in latest_dates
        )
        missing_flow = len(interval_dates) == 20 and any(
            trade_date not in flow_by_date
            or _finite_source_number(flow_by_date[trade_date].get("net_mf_amount"))
            is None
            for trade_date in interval_dates
        )
        if invalid_daily:
            expected_status = "UNAVAILABLE"
            expected_reason = "INSUFFICIENT_PIT_OBSERVATIONS"
            expected_metrics = (None, None, None, None)
        elif missing_adj:
            expected_status = "UNAVAILABLE"
            expected_reason = "MISSING_ADJUSTMENT_FACTOR"
            expected_metrics = (None, None, None, None)
        elif missing_flow:
            expected_status = "UNAVAILABLE"
            expected_reason = "MISSING_MONEYFLOW"
            expected_metrics = (None, None, None, None)
        else:
            adjusted_closes = [
                float(daily_by_date[trade_date]["close"])
                * float(adj_by_date[trade_date]["adj_factor"])
                for trade_date in latest_dates
            ]
            if any(value <= 0 for value in adjusted_closes):
                raise DataVendorUnavailable(
                    "sector adjusted closes must be positive for security scoring"
                )
            returns = [
                current / prior - 1
                for prior, current in zip(
                    adjusted_closes[:-1], adjusted_closes[1:], strict=True
                )
            ]
            daily_amounts = [
                float(daily_by_date[trade_date]["amount"])
                for trade_date in interval_dates
            ]
            if any(value < 0 for value in daily_amounts):
                raise DataVendorUnavailable(
                    "sector daily amount must be non-negative for security scoring"
                )
            expected_status = "AVAILABLE"
            expected_reason = None
            expected_metrics = (
                adjusted_closes[-1] / adjusted_closes[0] - 1,
                statistics.stdev(returns) * math.sqrt(252),
                statistics.median(daily_amounts) * 1_000,
                sum(
                    float(flow_by_date[trade_date]["net_mf_amount"])
                    for trade_date in interval_dates
                )
                * 10_000,
            )
        if (
            submitted.get("availability_status") != expected_status
            or submitted.get("unavailability_reason") != expected_reason
            or any(
                not math.isclose(
                    float(submitted[key]), float(expected), rel_tol=1e-9, abs_tol=1e-9
                )
                for key, expected in expected_common.items()
            )
        ):
            raise DataVendorUnavailable(
                f"sector security scoring row does not match registered PIT batches: {ts_code}"
            )
        submitted_metrics = (
            submitted.get("adjusted_return_20d"),
            submitted.get("realized_volatility_20d"),
            submitted.get("median_amount_20d_cny"),
            submitted.get("net_moneyflow_20d_cny"),
        )
        if any(
            (actual is not None or expected is not None)
            and (
                actual is None
                or expected is None
                or not math.isclose(
                    float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9
                )
            )
            for actual, expected in zip(
                submitted_metrics, expected_metrics, strict=True
            )
        ):
            raise DataVendorUnavailable(
                f"sector security scoring metrics do not match registered PIT batches: {ts_code}"
            )
        expected_observation_date = latest_dates[-1] if latest_dates else as_of
        if (
            _parse_temporal(
                submitted["observation_date"], "security scoring observation_date"
            ).date()
            != expected_observation_date
            or _parse_temporal(submitted["released_at"], "security scoring released_at")
            != released_at
            or _parse_temporal(submitted["vintage_at"], "security scoring vintage_at")
            != vintage_at
        ):
            raise DataVendorUnavailable(
                f"sector security scoring temporals do not match registered PIT batches: {ts_code}"
            )


def _build_sector_source_receipt(
    *,
    role: str,
    as_of_date: str,
    snapshot: Mapping[str, Any],
    source_batches: list[dict[str, Any]],
) -> dict[str, Any]:
    as_of = date.fromisoformat(as_of_date)
    contracts = _registered_tushare_endpoint_contracts()
    batches = [
        _validate_source_batch(batch, as_of=as_of, endpoint_contracts=contracts)
        for batch in source_batches
    ]
    batch_ids = [batch["source_batch_id"] for batch in batches]
    if len(batch_ids) != len(set(batch_ids)):
        raise DataVendorUnavailable("sector source batch IDs must be unique")
    required_endpoints = _required_sector_endpoints(snapshot)
    observed_endpoints = {batch["endpoint"] for batch in batches}
    missing = sorted(required_endpoints - observed_endpoints)
    if missing:
        raise DataVendorUnavailable(
            "sector registered source endpoints are incomplete: " + ", ".join(missing)
        )
    _validate_membership_batches(
        role=role, as_of=as_of, snapshot=snapshot, batches=batches
    )
    _validate_security_scoring_batches(snapshot=snapshot, batches=batches, as_of=as_of)
    batch_keys = {
        (batch["source_id"], batch["endpoint"], batch["source_batch_hash"])
        for batch in batches
    }
    for evidence in snapshot["evidence_catalog"]:
        key = (
            evidence["source_id"],
            evidence["source_endpoint"],
            evidence["content_hash"],
        )
        if key not in batch_keys:
            raise DataVendorUnavailable(
                f"sector evidence is not bound to a registered source batch: {evidence['evidence_id']}"
            )
    metadata = [
        {key: batch[key] for key in sorted(_SOURCE_BATCH_RECEIPT_FIELDS)}
        for batch in sorted(batches, key=lambda row: row["source_batch_id"])
    ]
    body = {
        "schema_version": SECTOR_SOURCE_RECEIPT_SCHEMA_VERSION,
        "sector_agent_id": role,
        "as_of_date": as_of_date,
        "sector_snapshot_hash": snapshot["snapshot_hash"],
        "required_endpoints": sorted(required_endpoints),
        "source_batches": metadata,
    }
    return {**body, "source_bundle_hash": _canonical_hash(body)}


def _validate_sector_source_receipt(
    receipt: Any,
    *,
    snapshot: Mapping[str, Any],
    role: str,
    as_of_date: str,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise DataVendorUnavailable("sector source receipt must be an object")
    _require_exact_fields(receipt, _SOURCE_RECEIPT_FIELDS, "sector source receipt")
    if (
        receipt.get("schema_version") != SECTOR_SOURCE_RECEIPT_SCHEMA_VERSION
        or receipt.get("sector_agent_id") != role
        or receipt.get("as_of_date") != as_of_date
        or receipt.get("sector_snapshot_hash") != snapshot.get("snapshot_hash")
        or receipt.get("required_endpoints")
        != sorted(_required_sector_endpoints(snapshot))
    ):
        raise DataVendorUnavailable("sector source receipt identity mismatch")
    batches = receipt.get("source_batches")
    if not isinstance(batches, list) or not batches:
        raise DataVendorUnavailable("sector source receipt batches are required")
    ids: list[str] = []
    contracts = _registered_tushare_endpoint_contracts()
    as_of = date.fromisoformat(as_of_date)
    observed_endpoints: set[str] = set()
    for batch in batches:
        if not isinstance(batch, dict):
            raise DataVendorUnavailable("sector source receipt batches must be objects")
        _require_exact_fields(
            batch, _SOURCE_BATCH_RECEIPT_FIELDS, "sector source receipt batch"
        )
        _require_sha256(batch.get("source_batch_hash"), "sector source batch hash")
        _require_sha256(batch.get("rows_hash"), "sector source rows hash")
        endpoint = str(batch.get("endpoint"))
        contract = contracts.get(endpoint)
        if (
            contract is None
            or batch.get("source_id") != f"tushare.{endpoint}"
            or batch.get("schema_contract_version")
            != contract.get("schema_contract_version")
        ):
            raise DataVendorUnavailable("sector source receipt route mismatch")
        for field in ("released_at", "vintage_at", "captured_at"):
            if (
                _parse_temporal(batch.get(field), f"source receipt {field}").date()
                > as_of
            ):
                raise DataVendorUnavailable("sector source receipt contains lookahead")
        if (
            batch.get("pit_status") != "PIT_VERIFIED"
            or batch.get("pagination_complete") is not True
            or batch.get("truncated") is not False
            or batch.get("coverage_ratio", 0) < 0.9
        ):
            raise DataVendorUnavailable("sector source receipt is not ready")
        batch_body = {
            key: value
            for key, value in batch.items()
            if key not in {"source_batch_id", "source_batch_hash"}
        }
        expected_hash = _canonical_hash(batch_body)
        expected_id = "sector-source-batch:" + expected_hash.removeprefix("sha256:")
        if (
            batch.get("source_batch_hash") != expected_hash
            or batch.get("source_batch_id") != expected_id
        ):
            raise DataVendorUnavailable("sector source receipt batch hash mismatch")
        ids.append(expected_id)
        observed_endpoints.add(endpoint)
    if ids != sorted(set(ids)):
        raise DataVendorUnavailable("sector source receipt batches are not canonical")
    if not set(receipt["required_endpoints"]).issubset(observed_endpoints):
        raise DataVendorUnavailable(
            "sector source receipt endpoint coverage is incomplete"
        )
    receipt_body = {
        key: value for key, value in receipt.items() if key != "source_bundle_hash"
    }
    if receipt.get("source_bundle_hash") != _canonical_hash(receipt_body):
        raise DataVendorUnavailable("sector source receipt hash mismatch")
    return {key: receipt[key] for key in receipt}


def _sector_source_receipt_path(role: str, as_of_date: str, root: Path) -> Path:
    return root / as_of_date / f"{role}.sources.json"


def _load_and_validate_sector_source_receipt(
    *,
    snapshot: Mapping[str, Any],
    role: str,
    as_of_date: str,
    root: Path,
) -> dict[str, Any]:
    path = _sector_source_receipt_path(role, as_of_date, root)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            f"sector registered source receipt is unavailable: {path}"
        ) from exc
    return _validate_sector_source_receipt(
        receipt, snapshot=snapshot, role=role, as_of_date=as_of_date
    )


def write_registered_sector_snapshot(
    *,
    role: str,
    as_of_date: str,
    snapshot: Mapping[str, Any],
    source_batches: list[dict[str, Any]],
    root: Path | None = None,
) -> dict[str, Any]:
    """Publish a validated PIT snapshot from caller-supplied collector rows.

    This function never fetches a source and never falls back.  The snapshot is
    published only after every registered membership route, endpoint, timestamp,
    coverage ratio, source hash and evidence binding has been verified.
    """
    if not isinstance(snapshot, dict) or "fixture_class" in snapshot:
        raise DataVendorUnavailable(
            "registered sector builder accepts production archived inputs only"
        )
    canonical = validate_sector_snapshot(snapshot, role, as_of_date)
    receipt = _build_sector_source_receipt(
        role=role,
        as_of_date=as_of_date,
        snapshot=canonical,
        source_batches=source_batches,
    )
    destination_root = root or sector_snapshot_root()
    destination = destination_root / as_of_date / f"{role}.json"
    receipt_path = _sector_source_receipt_path(role, as_of_date, destination_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    for path, expected in ((destination, canonical), (receipt_path, receipt)):
        if not path.exists():
            continue
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                f"existing frozen sector artifact is unreadable: {path}"
            ) from exc
        if existing != expected:
            raise DataVendorUnavailable(
                f"refusing to replace a different frozen sector artifact: {path}"
            )
    receipt_tmp = receipt_path.with_suffix(".json.tmp")
    snapshot_tmp = destination.with_suffix(".json.tmp")
    receipt_tmp.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    snapshot_tmp.write_text(
        json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    os.replace(receipt_tmp, receipt_path)
    os.replace(snapshot_tmp, destination)
    return canonical


def load_sector_snapshot(
    role: str, as_of_date: str, root: Path | None = None
) -> dict[str, Any]:
    source_root = root or sector_snapshot_root()
    snapshot = validate_sector_snapshot(
        _read(role, as_of_date, source_root), role, as_of_date
    )
    synthetic_source_bypass = (
        os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") == "structured_smoke"
        and snapshot.get("fixture_class") == "SYNTHETIC_NON_PRODUCTION"
    )
    if not synthetic_source_bypass:
        _load_and_validate_sector_source_receipt(
            snapshot=snapshot,
            role=role,
            as_of_date=as_of_date,
            root=source_root,
        )
    base_runtime_fields = set(snapshot)
    if role in ROLE_EVENT_CURRENCIES:
        role_events = build_role_event_snapshot(role, as_of_date)
        if not isinstance(role_events, dict):
            raise DataVendorUnavailable("sector role-event snapshot must be an object")
        _require_exact_fields(
            role_events, _ROLE_EVENT_SNAPSHOT_FIELDS, "sector role-event snapshot"
        )
        if (
            role_events.get("consumer_agent") != role
            or not str(role_events.get("as_of", "")).startswith(as_of_date)
            or role_events.get("schema_version") != ROLE_EVENT_SNAPSHOT_VERSION
            or role_events.get("contract_version") != ROLE_EVENT_COVERAGE_VERSION
        ):
            raise DataVendorUnavailable("sector role-event identity mismatch")
        _require_hash_binding(
            role_events, "role_event_snapshot_hash", "sector role-event snapshot"
        )
        role_event_without_id = {
            key: value
            for key, value in role_events.items()
            if key not in {"role_event_snapshot_id", "role_event_snapshot_hash"}
        }
        expected_role_event_id = "role-event-snapshot:" + _canonical_hash(
            role_event_without_id
        ).removeprefix("sha256:")
        if role_events.get("role_event_snapshot_id") != expected_role_event_id:
            raise DataVendorUnavailable("sector role-event snapshot ID mismatch")
        coverage = role_events.get("coverage")
        if not isinstance(coverage, dict) or not isinstance(
            role_events.get("projections"), list
        ):
            raise DataVendorUnavailable("sector role-event payload shape mismatch")
        if coverage.get("coverage_completeness") != "COMPLETE":
            raise DataVendorUnavailable(
                "sector role-event required routes are incomplete"
            )
        snapshot = {
            **{key: value for key, value in snapshot.items() if key != "snapshot_hash"},
            "event_coverage": coverage,
            "role_event_snapshot_ref": {
                "role_event_snapshot_id": role_events["role_event_snapshot_id"],
                "role_event_snapshot_hash": role_events["role_event_snapshot_hash"],
            },
        }
        snapshot["snapshot_hash"] = _canonical_hash(snapshot)
        _require_exact_fields(
            snapshot,
            base_runtime_fields | {"event_coverage", "role_event_snapshot_ref"},
            "sector runtime snapshot",
        )
        role_event_ref = snapshot["role_event_snapshot_ref"]
        if not isinstance(role_event_ref, dict):
            raise DataVendorUnavailable("sector role-event reference must be an object")
        _require_exact_fields(
            role_event_ref, _ROLE_EVENT_REF_FIELDS, "sector role-event reference"
        )
        _require_sha256(
            role_event_ref["role_event_snapshot_hash"],
            "sector role-event reference hash",
        )
        _require_hash_binding(snapshot, "snapshot_hash", "sector runtime snapshot")
    return snapshot


def render_sector_snapshot(role: str, as_of_date: str) -> str:
    return json.dumps(
        load_sector_snapshot(role, as_of_date),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_relationship_snapshot(
    as_of_date: str, run_id: str = "standalone_relationship_snapshot"
) -> str:
    payload = _read("relationship_mapper", as_of_date, sector_snapshot_root())
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("relationship snapshot must be an object")
    if payload.get("schema_version") != RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION:
        raise DataVendorUnavailable("relationship snapshot schema_version mismatch")
    if payload.get("as_of_date") != as_of_date:
        raise DataVendorUnavailable("relationship snapshot as_of mismatch")
    if not isinstance(run_id, str) or not run_id.strip():
        raise DataVendorUnavailable("relationship snapshot run_id is required")
    required = (
        "frozen_security_domain_hash",
        "relationships",
        "prediction_opportunity_set",
        "evidence_catalog",
    )
    if any(not payload.get(field) for field in required):
        raise DataVendorUnavailable("relationship snapshot missing required data")
    opportunity = payload["prediction_opportunity_set"]
    if not isinstance(opportunity, dict):
        raise DataVendorUnavailable(
            "relationship prediction opportunity set must be an object"
        )
    opportunities = opportunity.get("ordered_opportunities")
    if not isinstance(opportunities, list) or not opportunities:
        raise DataVendorUnavailable(
            "relationship prediction opportunity set must be non-empty"
        )
    candidate_ids: list[str] = []
    for row in opportunities:
        if not isinstance(row, dict):
            raise DataVendorUnavailable(
                "relationship prediction opportunity must be an object"
            )
        required_row = (
            "edge_candidate_id",
            "source_entity",
            "target_entity",
            "edge_type",
            "materiality_weight",
            "matched_non_edge_set_id",
            "matched_non_edge_set_hash",
        )
        if any(row.get(field) in (None, "") for field in required_row):
            raise DataVendorUnavailable(
                "relationship prediction opportunity is incomplete"
            )
        weight = row["materiality_weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise DataVendorUnavailable(
                "relationship materiality weight must be numeric"
            )
        if not math.isfinite(float(weight)) or float(weight) <= 0:
            raise DataVendorUnavailable(
                "relationship materiality weight must be finite and positive"
            )
        matched_hash = row["matched_non_edge_set_hash"]
        if not isinstance(matched_hash, str) or not matched_hash.startswith("sha256:"):
            raise DataVendorUnavailable("relationship matched non-edge hash is invalid")
        candidate_ids.append(str(row["edge_candidate_id"]))
    if len(set(candidate_ids)) != len(candidate_ids) or candidate_ids != sorted(
        candidate_ids
    ):
        raise DataVendorUnavailable(
            "relationship opportunity ids must be unique and canonically ordered"
        )
    relationship_by_id = {
        row.get("edge_candidate_id"): row
        for row in payload["relationships"]
        if isinstance(row, dict) and isinstance(row.get("edge_candidate_id"), str)
    }
    for row in opportunities:
        source = relationship_by_id.get(row["edge_candidate_id"])
        if source is None or any(
            source.get(field) != row[field]
            for field in ("source_entity", "target_entity", "edge_type")
        ):
            raise DataVendorUnavailable(
                "relationship opportunity does not match the frozen relationship domain"
            )
    opportunity_body = {
        "run_id": run_id,
        "as_of": as_of_date,
        "candidate_generation_contract_version": opportunity.get(
            "candidate_generation_contract_version"
        ),
        "scoring_contract_version": opportunity.get("scoring_contract_version"),
        "ordered_opportunities": opportunities,
    }
    if not all(
        isinstance(opportunity_body[field], str) and opportunity_body[field]
        for field in (
            "candidate_generation_contract_version",
            "scoring_contract_version",
        )
    ):
        raise DataVendorUnavailable(
            "relationship opportunity contract versions are required"
        )
    opportunity_hash = _canonical_hash(opportunity_body)
    frozen_opportunity = {
        "opportunity_set_id": f"relationship-opportunity:{opportunity_hash.removeprefix('sha256:')}",
        "opportunity_set_hash": opportunity_hash,
        **opportunity_body,
    }
    canonical = {
        key: payload[key]
        for key in (
            "schema_version",
            "as_of_date",
            "frozen_security_domain_hash",
            "relationships",
            "evidence_catalog",
        )
    }
    canonical["prediction_opportunity_set"] = frozen_opportunity
    canonical["snapshot_hash"] = _canonical_hash(canonical)
    return json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


__all__ = [
    "RELATIONSHIP_SNAPSHOT_SCHEMA_VERSION",
    "SECTOR_DIRECTION_CONTRACT_VERSION",
    "SECTOR_DIRECTION_IDS",
    "SECTOR_REQUIRED_SOURCE_ENDPOINTS",
    "SECTOR_SNAPSHOT_SCHEMA_VERSION",
    "SECTOR_SOURCE_RECEIPT_SCHEMA_VERSION",
    "load_sector_snapshot",
    "render_relationship_snapshot",
    "render_sector_snapshot",
    "sector_snapshot_root",
    "validate_sector_snapshot",
    "write_registered_sector_snapshot",
]
