"""Point-in-time, role-scoped inputs for Layer-1 macro agents.

The committed code defines contracts and validates private local snapshots. Raw
Tushare news, licensed prose, and historical vintages stay under the operator's
cache directory and never enter the repository.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .exceptions import DataVendorUnavailable
from .geopolitical_events import ALL_SOURCE_IDS, build_geopolitical_role_snapshot
from .macro_source_contracts import (
    MACRO_OBSERVATION_SOURCE_COMPONENTS,
    assert_macro_role_sources_ready,
)
from .role_events import build_role_event_snapshot

MACRO_SNAPSHOT_SCHEMA_VERSION = "macro_role_snapshot_v2"

ROLE_SNAPSHOT_NAMES: dict[str, str] = {
    "china": "get_china_macro_snapshot",
    "us_economy": "get_us_macro_snapshot",
    "eu_economy": "get_eu_macro_snapshot",
    "central_bank": "get_central_bank_snapshot",
    "us_financial_conditions": "get_us_financial_conditions_snapshot",
    "euro_area_financial_conditions": "get_euro_area_financial_conditions_snapshot",
    "commodities": "get_commodity_conditions_snapshot",
    "geopolitical": "get_geopolitical_events_snapshot",
    "institutional_flow": "get_market_positioning_snapshot",
}

# Pre-registered ALFRED/official mappings. A series missing from this table is
# rejected; it is never silently replaced with a current FRED observation.
ALFRED_SERIES_MAP: dict[str, dict[str, str]] = {
    "us_real_gdp": {"series_id": "GDPC1", "source": "ALFRED"},
    "us_industrial_production": {"series_id": "INDPRO", "source": "ALFRED"},
    "us_nonfarm_payrolls": {"series_id": "PAYEMS", "source": "ALFRED"},
    "us_unemployment_rate": {"series_id": "UNRATE", "source": "ALFRED"},
    "us_cpi": {"series_id": "CPIAUCSL", "source": "ALFRED"},
    "us_core_cpi": {"series_id": "CPILFESL", "source": "ALFRED"},
    "us_pce": {"series_id": "PCEPI", "source": "ALFRED"},
    "us_core_pce": {"series_id": "PCEPILFE", "source": "ALFRED"},
    "us_retail_sales": {"series_id": "RSAFS", "source": "ALFRED"},
    "us_trade_balance": {"series_id": "BOPGSTB", "source": "ALFRED"},
    "us_real_yield_5y": {
        "series_id": "DFII5",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
    "us_real_yield_10y": {
        "series_id": "DFII10",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
    "us_real_yield_30y": {
        "series_id": "DFII30",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
    "us_baa_treasury_spread": {
        "series_id": "BAA10Y",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
    "us_financial_conditions_index": {
        "series_id": "NFCI",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
    "us_vix": {
        "series_id": "VIXCLS",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
    "us_broad_dollar": {
        "series_id": "DTWEXBGS",
        "source": "ALFRED",
        "role": "us_financial_conditions",
    },
}

ALFRED_SERIES_ROLE_MAP: dict[str, str] = {
    mapping["series_id"]: mapping.get("role", "us_economy")
    for mapping in ALFRED_SERIES_MAP.values()
}

_EVENT_SOURCES = ALL_SOURCE_IDS
_PIT_STATUS = "AVAILABLE_AS_OF"
_A_SHARE_TIMEZONE = ZoneInfo("Asia/Shanghai")
_A_SHARE_DECISION_CUTOFF = time(15, 0)
_OBSERVATION_FIELDS = frozenset(
    {
        "series_id",
        "period_start",
        "period_end",
        "released_at",
        "vintage_at",
        "actual",
        "previous",
        "expected",
        "unit",
        "source",
        "pit_status",
        "evidence_id",
    }
)

# Role boundaries are enforced at the snapshot boundary, not left to prompt
# compliance. Prefixes describe canonical private-cache series families; the
# exact set covers vendor identifiers that cannot carry a descriptive prefix.
ROLE_SERIES_PREFIXES: dict[str, tuple[str, ...]] = {
    "china": (
        "cn_gdp",
        "cn_industrial",
        "cn_pmi",
        "china_growth",
        "cn_cpi",
        "cn_ppi",
        "china_price",
        "cn_credit",
        "cn_tsfin",
        "cn_money",
        "china_credit",
        "cn_export",
        "cn_import",
        "cn_trade",
        "china_trade",
        "cn_fiscal",
        "china_fiscal",
    ),
    "us_economy": (
        "us_gdp",
        "us_industrial",
        "us_pmi",
        "gdpc1",
        "indpro",
        "us_cpi",
        "us_pce",
        "cpiaucsl",
        "cpilfesl",
        "pcepi",
        "pcepilfe",
        "us_payroll",
        "us_unemployment",
        "payems",
        "unrate",
        "us_retail",
        "us_trade",
        "rsafs",
        "bopgstb",
    ),
    "eu_economy": ("eu_", "eurostat_", "world_bank_eu_"),
    "central_bank": (
        "pboc_",
        "cn_policy_",
        "domestic_liquidity_",
        "cn_growth_summary",
        "cn_price_summary",
        "cn_credit_summary",
        "cn_curve_",
        "money_market_",
        "credit_condition_",
    ),
    "us_financial_conditions": (
        "us_curve_",
        "us_real_yield_",
        "fed_",
        "us_money_market_",
        "us_credit_",
        "us_financial_stress_",
        "broad_dollar_",
        "rmb_",
        "cny_",
        "fx_",
    ),
    "euro_area_financial_conditions": (
        "ecb_",
        "euro_area_curve_",
        "euro_area_bank_credit_",
        "eur_",
        "euro_area_financial_stress_",
    ),
    "commodities": (
        "commodity_",
        "energy_",
        "oil_",
        "industrial_metal_",
        "copper_",
        "gold_",
        "inventory_",
        "term_structure_",
        "agriculture_",
        "food_",
    ),
    "institutional_flow": (
        "market_flow_",
        "sector_rotation_",
        "etf_share_",
        "crowding_",
        "institutional_flow_",
        "lhb_",
    ),
}

ROLE_EXACT_SERIES_IDS: dict[str, frozenset[str]] = {
    "us_financial_conditions": frozenset(
        {
            "DGS1",
            "DGS2",
            "DGS5",
            "DGS10",
            "DGS30",
            "DFII5",
            "DFII10",
            "DFII30",
            "BAA10Y",
            "NFCI",
            "DTWEXBGS",
            "USDCNH",
            "USDCNY",
            "VIXCLS",
        }
    ),
}

ROLE_COMPONENT_PREFIXES: dict[str, dict[str, tuple[str, ...]]] = {
    "china": {
        "growth_production": ("cn_gdp", "cn_industrial", "cn_pmi", "china_growth"),
        "prices": ("cn_cpi", "cn_ppi", "china_price"),
        "credit": ("cn_credit", "cn_tsfin", "cn_money", "china_credit"),
        "external_demand_trade": ("cn_export", "cn_import", "cn_trade", "china_trade"),
        "fiscal": ("cn_fiscal", "china_fiscal"),
    },
    "us_economy": {
        "growth_production": (
            "us_gdp",
            "us_industrial",
            "us_pmi",
            "gdpc1",
            "indpro",
        ),
        "prices": ("us_cpi", "us_pce", "cpiaucsl", "cpilfesl", "pcepi", "pcepilfe"),
        "employment": ("us_payroll", "us_unemployment", "payems", "unrate"),
        "demand_trade": ("us_retail", "us_trade", "rsafs", "bopgstb"),
    },
    "eu_economy": {
        "growth_production": (
            "eu_gdp",
            "eu_industrial",
            "eurostat_gdp",
            "eurostat_industrial",
        ),
        "prices": ("eu_hicp", "eurostat_hicp", "eu_price"),
        "employment": ("eu_employment", "eu_unemployment", "eurostat_employment"),
        "demand_trade": ("eu_retail", "eu_trade", "eurostat_retail", "eurostat_trade"),
    },
    "central_bank": {
        "pboc_policy_bias": ("pboc_", "cn_policy_"),
        "liquidity_money_market": ("domestic_liquidity_", "money_market_"),
        "china_curve": ("cn_curve_",),
        "credit_conditions": ("credit_condition_", "cn_credit_summary"),
    },
    "us_financial_conditions": {
        "fed_liquidity": ("fed_", "us_money_market_"),
        "us_curve": ("us_curve_", "dgs", "dfii"),
        "credit_financial_stress": (
            "us_credit_",
            "us_financial_stress_",
            "baa10y",
            "nfci",
            "vixcls",
        ),
        "usd_rmb": (
            "broad_dollar_",
            "rmb_",
            "cny_",
            "fx_",
            "dtwexbgs",
            "usdcnh",
            "usdcny",
        ),
    },
    "euro_area_financial_conditions": {
        "ecb_liquidity": ("ecb_",),
        "euro_area_curve": ("euro_area_curve_",),
        "bank_credit": ("euro_area_bank_credit_",),
        "eur_financial_stress": ("eur_", "euro_area_financial_stress_"),
    },
    "commodities": {
        "energy": ("energy_", "oil_", "commodity_energy"),
        "industrial_metals": ("industrial_metal_", "copper_", "commodity_metal"),
        "gold": ("gold_", "commodity_gold"),
        "agriculture_food": ("agriculture_", "food_", "commodity_agriculture"),
    },
    "institutional_flow": {
        "market_wide_flow": ("market_flow_", "institutional_flow_market_"),
        "sector_rotation": ("sector_rotation_",),
        "etf_share": ("etf_share_",),
        "crowding": ("crowding_",),
    },
}

DIRECT_MACRO_ROLES = {"institutional_flow"}
INSTITUTIONAL_FLOW_MIN_COMPONENT_COVERAGE = 0.9
FINANCIAL_CONTEXT_SOURCE_ROLES: dict[str, str] = {
    "us_financial_conditions": "us_economy",
    "euro_area_financial_conditions": "eu_economy",
}
MACRO_EVENT_ROLES = frozenset(
    {
        "china",
        "us_economy",
        "eu_economy",
        "central_bank",
        "us_financial_conditions",
        "euro_area_financial_conditions",
        "commodities",
        "geopolitical",
    }
)


def _component_for_observation(role: str, row: dict[str, Any]) -> str | None:
    if str(row.get("source", "")).split(".", 1)[0] == "world_bank":
        return None
    series_id = str(row["series_id"]).casefold()
    matches = [
        component
        for component, prefixes in ROLE_COMPONENT_PREFIXES.get(role, {}).items()
        if series_id.startswith(prefixes)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(
            f"macro snapshot {field} must be a non-empty ISO timestamp"
        )
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"macro snapshot {field} is not ISO-8601: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise DataVendorUnavailable(
            f"macro snapshot {field} must include a timezone offset"
        )
    return parsed.astimezone(timezone.utc)


def _as_of_cutoff(as_of_date: str) -> datetime:
    try:
        parsed = date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"as_of_date must be YYYY-MM-DD, got {as_of_date!r}"
        ) from exc
    local_cutoff = datetime.combine(
        parsed, _A_SHARE_DECISION_CUTOFF, tzinfo=_A_SHARE_TIMEZONE
    )
    return local_cutoff.astimezone(timezone.utc)


def _series_allowed_for_role(role: str, series_id: Any) -> bool:
    if not isinstance(series_id, str) or not series_id.strip():
        return False
    normalized = series_id.strip()
    if normalized.upper() in ROLE_EXACT_SERIES_IDS.get(role, frozenset()):
        return True
    return normalized.casefold().startswith(ROLE_SERIES_PREFIXES.get(role, ()))


def snapshot_cache_root() -> Path:
    explicit = os.getenv("MOSAIC_MACRO_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "macro_snapshots"


def _snapshot_candidates(role: str, as_of_date: str, root: Path) -> tuple[Path, ...]:
    return (
        root / as_of_date / f"{role}.json",
        root / f"{role}.{as_of_date}.json",
    )


def _validate_observation(role: str, row: Any, cutoff: datetime) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise DataVendorUnavailable("macro snapshot observations must be objects")
    if set(row) != _OBSERVATION_FIELDS:
        missing = sorted(_OBSERVATION_FIELDS - set(row))
        extra = sorted(set(row) - _OBSERVATION_FIELDS)
        raise DataVendorUnavailable(
            f"macro observation fields mismatch missing={missing} extra={extra}"
        )
    try:
        period_start = date.fromisoformat(row["period_start"])
        period_end = date.fromisoformat(row["period_end"])
    except (TypeError, ValueError) as exc:
        raise DataVendorUnavailable(
            "macro observation periods must be ISO dates"
        ) from exc
    if period_start > period_end or period_end > cutoff.date():
        raise DataVendorUnavailable(
            "macro observation period must satisfy start <= end <= as_of"
        )
    released_at = _parse_datetime(row["released_at"], "released_at")
    vintage_at = _parse_datetime(row["vintage_at"], "vintage_at")
    if released_at > cutoff or vintage_at > cutoff:
        raise DataVendorUnavailable(
            f"future macro observation rejected for {row.get('series_id')}: "
            f"released_at/vintage_at exceeds as_of"
        )
    if released_at > vintage_at:
        raise DataVendorUnavailable(
            "macro observation must satisfy released_at <= vintage_at"
        )
    if row.get("pit_status") != _PIT_STATUS:
        raise DataVendorUnavailable(
            f"macro observation {row.get('series_id')} is not point-in-time available"
        )
    if (
        not isinstance(row.get("evidence_id"), str)
        or not row["evidence_id"].strip()
        or len(row["evidence_id"]) > 256
    ):
        raise DataVendorUnavailable("macro observation evidence_id must be non-empty")
    for field, nullable in (("actual", False), ("previous", True), ("expected", True)):
        value = row[field]
        if value is None and nullable:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise DataVendorUnavailable(
                f"macro observation {field} must be a finite number"
            )
    if (
        not isinstance(row.get("unit"), str)
        or not row["unit"].strip()
        or len(row["unit"]) > 64
    ):
        raise DataVendorUnavailable("macro observation unit must be non-empty")
    source = str(row.get("source") or "").strip()
    if source in _EVENT_SOURCES:
        raise DataVendorUnavailable(
            "news and policy documents must use the event library"
        )
    if source == "ALFRED":
        series_id = str(row.get("series_id") or "")
        owner = ALFRED_SERIES_ROLE_MAP.get(series_id)
        if owner is None:
            raise DataVendorUnavailable(
                f"unregistered ALFRED series rejected: {series_id!r}"
            )
        if owner != role:
            raise DataVendorUnavailable(
                f"ALFRED series {series_id} belongs to {owner}, not {role}"
            )
        allowed_components = frozenset(ROLE_COMPONENT_PREFIXES.get(role, {}))
    else:
        registered_sources = MACRO_OBSERVATION_SOURCE_COMPONENTS.get(role, {})
        allowed_components = registered_sources.get(source)
        if allowed_components is None:
            raise DataVendorUnavailable(
                f"unregistered macro observation source identity: {source!r}"
            )
    component = _component_for_observation(role, row)
    if source != "ALFRED" and not _series_allowed_for_role(role, row.get("series_id")):
        raise DataVendorUnavailable(
            f"series {row.get('series_id')!r} is outside the {role} snapshot contract"
        )
    if component is not None and component not in allowed_components:
        raise DataVendorUnavailable(
            f"source {source!r} is not registered for {role}/{component}"
        )
    if component is None and source.split(".", 1)[0] != "world_bank":
        raise DataVendorUnavailable(
            f"series {row.get('series_id')!r} does not map to one {role} component"
        )
    return {field: row[field] for field in sorted(_OBSERVATION_FIELDS)}


def _validate_institutional_flow_coverage(
    payload: dict[str, Any], observations: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, float | int]], float]:
    component_contract = ROLE_COMPONENT_PREFIXES["institutional_flow"]
    routed_components = {
        component
        for row in observations
        if (component := _component_for_observation("institutional_flow", row))
        is not None
    }
    missing_components = sorted(set(component_contract) - routed_components)
    if missing_components:
        raise DataVendorUnavailable(
            "institutional_flow snapshot missing required components: "
            + ", ".join(missing_components)
        )
    raw = payload.get("component_coverage")
    if not isinstance(raw, dict) or set(raw) != set(component_contract):
        raise DataVendorUnavailable(
            "institutional_flow component_coverage must match the four required components"
        )
    validated: dict[str, dict[str, float | int]] = {}
    for component in component_contract:
        row = raw[component]
        if not isinstance(row, dict) or set(row) != {
            "eligible_count",
            "observed_count",
            "coverage_ratio",
        }:
            raise DataVendorUnavailable(
                f"institutional_flow {component} coverage contract mismatch"
            )
        eligible = row["eligible_count"]
        observed = row["observed_count"]
        ratio = row["coverage_ratio"]
        if (
            isinstance(eligible, bool)
            or not isinstance(eligible, int)
            or eligible < 1
            or isinstance(observed, bool)
            or not isinstance(observed, int)
            or observed < 0
            or observed > eligible
            or isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or abs(float(ratio) - observed / eligible) > 1e-12
        ):
            raise DataVendorUnavailable(
                f"institutional_flow {component} coverage values are inconsistent"
            )
        if float(ratio) < INSTITUTIONAL_FLOW_MIN_COMPONENT_COVERAGE:
            raise DataVendorUnavailable(
                f"institutional_flow {component} coverage below readiness threshold"
            )
        validated[component] = {
            "eligible_count": eligible,
            "observed_count": observed,
            "coverage_ratio": float(ratio),
        }
    quality = sum(
        float(row["coverage_ratio"]) for row in validated.values()
    ) / len(validated)
    return validated, quality


def _build_real_economy_context_projection(
    *,
    financial_role: str,
    context_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    source_role = FINANCIAL_CONTEXT_SOURCE_ROLES[financial_role]
    component_contract = ROLE_COMPONENT_PREFIXES[source_role]
    rows_by_component: dict[str, list[dict[str, Any]]] = {
        component: [] for component in component_contract
    }
    for row in context_observations:
        component = _component_for_observation(source_role, row)
        if component is None:
            raise DataVendorUnavailable(
                f"{financial_role} context observation has no {source_role} component"
            )
        rows_by_component[component].append(row)
    missing = sorted(
        component for component, rows in rows_by_component.items() if not rows
    )
    if missing:
        raise DataVendorUnavailable(
            f"{financial_role} context-only projection missing components: "
            + ", ".join(missing)
        )

    def balance(rows: list[dict[str, Any]], comparator: str) -> int:
        result = 0
        for row in rows:
            reference = row[comparator]
            if reference is None:
                continue
            result += (row["actual"] > reference) - (row["actual"] < reference)
        return result

    summaries = {
        component: {
            "component": component,
            "source_role": source_role,
            "usage_mode": "CONTEXT_ONLY",
            "contributes_to_required_components": False,
            "observation_count": len(rows),
            "latest_period_end": max(str(row["period_end"]) for row in rows),
            "actual_vs_expected_balance": balance(rows, "expected"),
            "actual_vs_previous_balance": balance(rows, "previous"),
            "evidence_ids": sorted(str(row["evidence_id"]) for row in rows),
        }
        for component, rows in sorted(rows_by_component.items())
    }
    body = {
        "schema_version": "macro_real_economy_context_projection_v1",
        "usage_mode": "CONTEXT_ONLY",
        "source_role": source_role,
        "contributes_to_required_components": False,
        "component_summaries": summaries,
    }
    return {
        **body,
        "projection_hash": "sha256:"
        + hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def validate_role_snapshot(payload: Any, role: str, as_of_date: str) -> dict[str, Any]:
    if role not in ROLE_SNAPSHOT_NAMES:
        raise DataVendorUnavailable(f"unknown macro snapshot role {role!r}")
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("macro role snapshot must be a JSON object")
    allowed_top_level = {
        "schema_version",
        "role",
        "as_of_date",
        "observations",
        "events",
        "fixture_class",
    }
    if role == "institutional_flow":
        allowed_top_level.add("component_coverage")
    if role in FINANCIAL_CONTEXT_SOURCE_ROLES:
        allowed_top_level.add("context_observations")
    required_top_level = allowed_top_level - {"fixture_class"}
    if not required_top_level.issubset(payload) or not set(payload).issubset(
        allowed_top_level
    ):
        raise DataVendorUnavailable(
            "macro role snapshot top-level fields mismatch"
        )
    if "fixture_class" in payload and payload["fixture_class"] != "SYNTHETIC_NON_PRODUCTION":
        raise DataVendorUnavailable("macro fixture_class is invalid")
    if payload.get("schema_version") != MACRO_SNAPSHOT_SCHEMA_VERSION:
        raise DataVendorUnavailable("macro role snapshot schema_version mismatch")
    if payload.get("role") != role or payload.get("as_of_date") != as_of_date:
        raise DataVendorUnavailable("macro role snapshot role/as_of mismatch")
    cutoff = _as_of_cutoff(as_of_date)
    observations = [
        _validate_observation(role, row, cutoff)
        for row in payload.get("observations", [])
    ]
    context_projection: dict[str, Any] | None = None
    context_observations: list[dict[str, Any]] = []
    if role in FINANCIAL_CONTEXT_SOURCE_ROLES:
        raw_context = payload.get("context_observations")
        if not isinstance(raw_context, list) or not raw_context:
            raise DataVendorUnavailable(
                f"{role} requires a non-empty deterministic context-only projection"
            )
        context_role = FINANCIAL_CONTEXT_SOURCE_ROLES[role]
        context_observations = [
            _validate_observation(context_role, row, cutoff) for row in raw_context
        ]
        context_projection = _build_real_economy_context_projection(
            financial_role=role,
            context_observations=context_observations,
        )
    events = payload.get("events", [])
    if events:
        raise DataVendorUnavailable(
            "macro role snapshots cannot embed event prose; use the bound event registry projection"
        )
    if role == "geopolitical":
        raise DataVendorUnavailable(
            "geopolitical must use GeopoliticalEventsSnapshot, not a generic macro snapshot"
        )
    if not observations:
        raise DataVendorUnavailable(f"{role} snapshot has no accepted evidence")
    evidence_ids = [row["evidence_id"] for row in observations + context_observations]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise DataVendorUnavailable(
            f"{role} snapshot contains duplicate evidence_id values"
        )
    component_contract = ROLE_COMPONENT_PREFIXES.get(role)
    component_data_quality: dict[str, float] | None = None
    direct_data_quality: float | None = None
    institutional_flow_coverage: dict[str, dict[str, float | int]] | None = None
    if role == "institutional_flow":
        institutional_flow_coverage, direct_data_quality = (
            _validate_institutional_flow_coverage(payload, observations)
        )
    elif component_contract is not None:
        routed_components = {
            component
            for row in observations
            if (component := _component_for_observation(role, row)) is not None
        }
        missing_components = sorted(set(component_contract) - routed_components)
        if missing_components:
            raise DataVendorUnavailable(
                f"{role} snapshot missing required components: {', '.join(missing_components)}"
            )
        component_data_quality = {component: 1.0 for component in component_contract}
    elif role in DIRECT_MACRO_ROLES:
        direct_data_quality = 1.0
    canonical = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": role,
        "as_of_date": as_of_date,
        "observations": observations,
        "events": [],
        "source_policy": {
            "registered_sources": sorted({row["source"] for row in observations}),
            "us_revision_source": "ALFRED/official fixed map",
            "implicit_fallback": False,
        },
    }
    if component_data_quality is not None:
        canonical["component_data_quality"] = component_data_quality
    if direct_data_quality is not None:
        canonical["direct_data_quality"] = direct_data_quality
    if institutional_flow_coverage is not None:
        canonical["component_coverage"] = institutional_flow_coverage
    if context_projection is not None:
        canonical["context_only_projection"] = context_projection
    canonical["snapshot_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return canonical


def load_role_snapshot(
    role: str, as_of_date: str, root: Path | None = None
) -> dict[str, Any]:
    if role == "geopolitical":
        snapshot = build_geopolitical_role_snapshot(as_of_date)
        role_events = build_role_event_snapshot(role, as_of_date)
        if role_events["coverage"]["coverage_completeness"] != "COMPLETE":
            raise DataVendorUnavailable(
                "geopolitical economic-calendar coverage is incomplete"
            )
        snapshot["role_event_snapshot"] = role_events
        without_hash = {
            key: value for key, value in snapshot.items() if key != "snapshot_hash"
        }
        snapshot["snapshot_hash"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(without_hash, ensure_ascii=False, sort_keys=True).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        return snapshot
    cache_root = root or snapshot_cache_root()
    path = next(
        (
            item
            for item in _snapshot_candidates(role, as_of_date, cache_root)
            if item.is_file()
        ),
        None,
    )
    if path is None:
        raise DataVendorUnavailable(
            f"no private PIT snapshot for {role} on {as_of_date} under {cache_root}; "
            "implicit vendor fallback is disabled"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            f"cannot read macro snapshot {path}: {exc}"
        ) from exc
    synthetic_source_gap_bypass = (
        os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") == "structured_smoke"
        and payload.get("fixture_class") == "SYNTHETIC_NON_PRODUCTION"
    )
    if not synthetic_source_gap_bypass:
        try:
            assert_macro_role_sources_ready(role)
            if role in FINANCIAL_CONTEXT_SOURCE_ROLES:
                assert_macro_role_sources_ready(
                    FINANCIAL_CONTEXT_SOURCE_ROLES[role]
                )
        except RuntimeError as exc:
            raise DataVendorUnavailable(str(exc)) from exc
    snapshot = validate_role_snapshot(payload, role, as_of_date)
    if role in MACRO_EVENT_ROLES:
        role_events = build_role_event_snapshot(role, as_of_date)
        if role_events["coverage"]["coverage_completeness"] != "COMPLETE":
            raise DataVendorUnavailable(
                f"{role} economic-calendar coverage is incomplete"
            )
        snapshot["role_event_snapshot"] = role_events
        without_hash = {
            key: value for key, value in snapshot.items() if key != "snapshot_hash"
        }
        snapshot["snapshot_hash"] = "sha256:" + hashlib.sha256(
            json.dumps(
                without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    return snapshot


def render_role_snapshot(role: str, as_of_date: str) -> str:
    return json.dumps(
        load_role_snapshot(role, as_of_date),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def write_registered_role_snapshot(
    *,
    role: str,
    as_of_date: str,
    observations: list[dict[str, Any]],
    context_observations: list[dict[str, Any]] | None = None,
    component_coverage: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate and atomically persist a production PIT role snapshot.

    This builder accepts only already archived release/vintage observations
    carrying exact registered source identities.  It never calls a live source,
    substitutes an adjacent endpoint, or fabricates release metadata.
    """
    if role in {"geopolitical", "market_breadth"}:
        raise DataVendorUnavailable(
            f"{role} has a dedicated deterministic snapshot builder"
        )
    try:
        assert_macro_role_sources_ready(role)
        if role in FINANCIAL_CONTEXT_SOURCE_ROLES:
            assert_macro_role_sources_ready(FINANCIAL_CONTEXT_SOURCE_ROLES[role])
    except RuntimeError as exc:
        raise DataVendorUnavailable(str(exc)) from exc
    raw: dict[str, Any] = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": role,
        "as_of_date": as_of_date,
        "observations": observations,
        "events": [],
    }
    if component_coverage is not None:
        raw["component_coverage"] = component_coverage
    if role in FINANCIAL_CONTEXT_SOURCE_ROLES:
        if context_observations is None:
            raise DataVendorUnavailable(
                f"{role} requires deterministic real-economy context observations"
            )
        raw["context_observations"] = context_observations
    canonical = validate_role_snapshot(raw, role, as_of_date)
    destination_root = root or snapshot_cache_root()
    destination = destination_root / as_of_date / f"{role}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                f"existing macro snapshot is unreadable: {destination}"
            ) from exc
        if existing != raw:
            raise DataVendorUnavailable(
                f"refusing to replace a different frozen macro snapshot: {destination}"
            )
        return canonical
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, destination)
    return canonical


def mark_legacy_macro_output(payload: dict[str, Any]) -> dict[str, Any]:
    agent = payload.get("agent")
    if agent not in {
        "dollar",
        "yield_curve",
        "volatility",
        "emerging_markets",
        "news_sentiment",
    }:
        raise ValueError(f"not a legacy macro output: {agent!r}")
    return {**payload, "legacy_status": "legacy_unverified"}


__all__ = [
    "ALFRED_SERIES_MAP",
    "ALFRED_SERIES_ROLE_MAP",
    "MACRO_SNAPSHOT_SCHEMA_VERSION",
    "MACRO_EVENT_ROLES",
    "FINANCIAL_CONTEXT_SOURCE_ROLES",
    "ROLE_SNAPSHOT_NAMES",
    "ROLE_EXACT_SERIES_IDS",
    "ROLE_SERIES_PREFIXES",
    "load_role_snapshot",
    "mark_legacy_macro_output",
    "render_role_snapshot",
    "snapshot_cache_root",
    "validate_role_snapshot",
    "write_registered_role_snapshot",
]
