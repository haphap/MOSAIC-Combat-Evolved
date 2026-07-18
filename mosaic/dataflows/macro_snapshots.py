"""Point-in-time, role-scoped inputs for Layer-1 macro agents.

The committed code defines contracts and validates private local snapshots. Raw
Tushare news, licensed prose, and historical vintages stay under the operator's
cache directory and never enter the repository.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .exceptions import DataVendorUnavailable
from .geopolitical_events import ALL_SOURCE_IDS, build_geopolitical_role_snapshot
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
_OBSERVATION_SOURCE_ROOTS = {"tushare", "official", "eurostat", "ecb", "world_bank"}
_A_SHARE_TIMEZONE = ZoneInfo("Asia/Shanghai")

# Role boundaries are enforced at the snapshot boundary, not left to prompt
# compliance. Prefixes describe canonical private-cache series families; the
# exact set covers vendor identifiers that cannot carry a descriptive prefix.
ROLE_SERIES_PREFIXES: dict[str, tuple[str, ...]] = {
    "china": ("cn_", "china_"),
    "us_economy": ("us_",),
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
}

DIRECT_MACRO_ROLES = {"institutional_flow"}
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


def _as_of_end(as_of_date: str) -> datetime:
    try:
        parsed = date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"as_of_date must be YYYY-MM-DD, got {as_of_date!r}"
        ) from exc
    local_end = datetime.combine(parsed, time.max, tzinfo=_A_SHARE_TIMEZONE)
    return local_end.astimezone(timezone.utc)


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
    required = (
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
    )
    missing = [field for field in required if field not in row]
    if missing:
        raise DataVendorUnavailable(
            f"macro observation missing fields: {', '.join(missing)}"
        )
    released_at = _parse_datetime(row["released_at"], "released_at")
    vintage_at = _parse_datetime(row["vintage_at"], "vintage_at")
    if released_at > cutoff or vintage_at > cutoff:
        raise DataVendorUnavailable(
            f"future macro observation rejected for {row.get('series_id')}: "
            f"released_at/vintage_at exceeds as_of"
        )
    if row.get("pit_status") != _PIT_STATUS:
        raise DataVendorUnavailable(
            f"macro observation {row.get('series_id')} is not point-in-time available"
        )
    if not isinstance(row.get("evidence_id"), str) or not row["evidence_id"].strip():
        raise DataVendorUnavailable("macro observation evidence_id must be non-empty")
    source = str(row.get("source") or "")
    if source in _EVENT_SOURCES:
        raise DataVendorUnavailable(
            "news and policy documents must use the event library"
        )
    source_root = source.split(".", 1)[0]
    if source != "ALFRED" and source_root not in _OBSERVATION_SOURCE_ROOTS:
        raise DataVendorUnavailable(f"unapproved macro observation source: {source!r}")
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
    elif not _series_allowed_for_role(role, row.get("series_id")):
        raise DataVendorUnavailable(
            f"series {row.get('series_id')!r} is outside the {role} snapshot contract"
        )
    return {field: row[field] for field in required}


def validate_role_snapshot(payload: Any, role: str, as_of_date: str) -> dict[str, Any]:
    if role not in ROLE_SNAPSHOT_NAMES:
        raise DataVendorUnavailable(f"unknown macro snapshot role {role!r}")
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("macro role snapshot must be a JSON object")
    if payload.get("schema_version") != MACRO_SNAPSHOT_SCHEMA_VERSION:
        raise DataVendorUnavailable("macro role snapshot schema_version mismatch")
    if payload.get("role") != role or payload.get("as_of_date") != as_of_date:
        raise DataVendorUnavailable("macro role snapshot role/as_of mismatch")
    cutoff = _as_of_end(as_of_date)
    observations = [
        _validate_observation(role, row, cutoff)
        for row in payload.get("observations", [])
    ]
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
    evidence_ids = [row["evidence_id"] for row in observations]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise DataVendorUnavailable(
            f"{role} snapshot contains duplicate evidence_id values"
        )
    component_contract = ROLE_COMPONENT_PREFIXES.get(role)
    component_data_quality: dict[str, float] | None = None
    direct_data_quality: float | None = None
    if component_contract is not None:
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
            "primary": "tushare",
            "us_revision_source": "ALFRED/official fixed map",
            "implicit_fallback": False,
        },
    }
    if component_data_quality is not None:
        canonical["component_data_quality"] = component_data_quality
    if direct_data_quality is not None:
        canonical["direct_data_quality"] = direct_data_quality
    canonical["snapshot_hash"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
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
        snapshot["snapshot_hash"] = hashlib.sha256(
            json.dumps(without_hash, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    return snapshot


def render_role_snapshot(role: str, as_of_date: str) -> str:
    return json.dumps(
        load_role_snapshot(role, as_of_date),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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
    "ROLE_SNAPSHOT_NAMES",
    "ROLE_EXACT_SERIES_IDS",
    "ROLE_SERIES_PREFIXES",
    "load_role_snapshot",
    "mark_legacy_macro_output",
    "render_role_snapshot",
    "snapshot_cache_root",
    "validate_role_snapshot",
]
