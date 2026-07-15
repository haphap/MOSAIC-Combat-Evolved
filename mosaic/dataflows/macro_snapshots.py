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

MACRO_SNAPSHOT_SCHEMA_VERSION = "macro_role_snapshot_v1"

ROLE_SNAPSHOT_NAMES: dict[str, str] = {
    "china": "get_china_macro_snapshot",
    "us_economy": "get_us_macro_snapshot",
    "central_bank": "get_central_bank_snapshot",
    "yield_curve": "get_rates_credit_snapshot",
    "dollar": "get_fx_conditions_snapshot",
    "commodities": "get_commodity_conditions_snapshot",
    "geopolitical": "get_geopolitical_events_snapshot",
    "volatility": "get_volatility_snapshot",
    "institutional_flow": "get_market_positioning_snapshot",
}

# Pre-registered ALFRED/official mappings. A series missing from this table is
# rejected; it is never silently replaced with a current FRED observation.
ALFRED_SERIES_MAP: dict[str, dict[str, str]] = {
    "us_real_gdp": {"series_id": "GDPC1", "source": "ALFRED"},
    "us_nonfarm_payrolls": {"series_id": "PAYEMS", "source": "ALFRED"},
    "us_unemployment_rate": {"series_id": "UNRATE", "source": "ALFRED"},
    "us_cpi": {"series_id": "CPIAUCSL", "source": "ALFRED"},
    "us_core_cpi": {"series_id": "CPILFESL", "source": "ALFRED"},
    "us_pce": {"series_id": "PCEPI", "source": "ALFRED"},
    "us_core_pce": {"series_id": "PCEPILFE", "source": "ALFRED"},
    "us_retail_sales": {"series_id": "RSAFS", "source": "ALFRED"},
}

_NEWS_SOURCES = {"tushare.major_news", "official_policy_document"}
_NEWS_ROLES = {"china", "geopolitical"}
_PIT_STATUS = "AVAILABLE_AS_OF"
_OBSERVATION_SOURCE_ROOTS = {"tushare", "official"}
_A_SHARE_TIMEZONE = ZoneInfo("Asia/Shanghai")

# Role boundaries are enforced at the snapshot boundary, not left to prompt
# compliance. Prefixes describe canonical private-cache series families; the
# exact set covers vendor identifiers that cannot carry a descriptive prefix.
ROLE_SERIES_PREFIXES: dict[str, tuple[str, ...]] = {
    "china": ("cn_", "china_"),
    "us_economy": ("us_",),
    "central_bank": (
        "pboc_",
        "cn_policy_",
        "domestic_liquidity_",
        "cn_growth_summary",
        "cn_price_summary",
        "cn_credit_summary",
    ),
    "yield_curve": (
        "cn_curve_",
        "us_curve_",
        "cn_real_yield_",
        "us_real_yield_",
        "money_market_",
        "credit_condition_",
        "rates_credit_",
    ),
    "dollar": ("broad_dollar_", "rmb_", "cny_", "fx_"),
    "commodities": (
        "commodity_",
        "energy_",
        "oil_",
        "industrial_metal_",
        "copper_",
        "gold_",
        "inventory_",
        "term_structure_",
    ),
    "geopolitical": (
        "geopolitical_",
        "sanction_",
        "trade_restriction_",
        "supply_chain_risk_",
        "event_severity_",
    ),
    "volatility": (
        "vix_",
        "us_implied_vol_",
        "china_realized_vol_",
        "realized_vol_",
        "cross_market_stress_",
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
    "yield_curve": frozenset({"DGS1", "DGS2", "DGS5", "DGS10", "DGS30"}),
    "dollar": frozenset({"DTWEXBGS", "USDCNH", "USDCNY"}),
    "volatility": frozenset({"VIXCLS"}),
}


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(f"macro snapshot {field} must be a non-empty ISO timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DataVendorUnavailable(f"macro snapshot {field} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise DataVendorUnavailable(f"macro snapshot {field} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _as_of_end(as_of_date: str) -> datetime:
    try:
        parsed = date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise DataVendorUnavailable(f"as_of_date must be YYYY-MM-DD, got {as_of_date!r}") from exc
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
        raise DataVendorUnavailable(f"macro observation missing fields: {', '.join(missing)}")
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
    if source in _NEWS_SOURCES:
        raise DataVendorUnavailable("news and policy documents must use the event library")
    source_root = source.split(".", 1)[0]
    if source != "ALFRED" and source_root not in _OBSERVATION_SOURCE_ROOTS:
        raise DataVendorUnavailable(f"unapproved macro observation source: {source!r}")
    if source == "ALFRED" and role != "us_economy":
        raise DataVendorUnavailable(f"ALFRED revision series is not permitted for role {role}")
    if role == "us_economy" and source == "ALFRED":
        allowed = {mapping["series_id"] for mapping in ALFRED_SERIES_MAP.values()}
        if row.get("series_id") not in allowed:
            raise DataVendorUnavailable(
                f"unregistered ALFRED series rejected: {row.get('series_id')!r}"
            )
    elif not _series_allowed_for_role(role, row.get("series_id")):
        raise DataVendorUnavailable(
            f"series {row.get('series_id')!r} is outside the {role} snapshot contract"
        )
    return {field: row[field] for field in required}


def _validate_event(role: str, row: Any, cutoff: datetime) -> dict[str, Any]:
    if role not in _NEWS_ROLES:
        raise DataVendorUnavailable(f"event evidence is not permitted for role {role}")
    if not isinstance(row, dict):
        raise DataVendorUnavailable("macro snapshot events must be objects")
    required = ("event_id", "published_at", "source", "content_hash", "title", "evidence_id")
    missing = [field for field in required if field not in row]
    if missing:
        raise DataVendorUnavailable(f"macro event missing fields: {', '.join(missing)}")
    if _parse_datetime(row["published_at"], "published_at") > cutoff:
        raise DataVendorUnavailable(f"future macro event rejected: {row.get('event_id')}")
    if row.get("source") not in _NEWS_SOURCES:
        raise DataVendorUnavailable(f"unapproved event source: {row.get('source')!r}")
    if not isinstance(row.get("content_hash"), str) or not row["content_hash"].strip():
        raise DataVendorUnavailable("macro event content_hash must be non-empty")
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
        _validate_observation(role, row, cutoff) for row in payload.get("observations", [])
    ]
    events = [_validate_event(role, row, cutoff) for row in payload.get("events", [])]
    if not observations and not events:
        raise DataVendorUnavailable(f"{role} snapshot has no accepted evidence")
    evidence_ids = [row["evidence_id"] for row in [*observations, *events]]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise DataVendorUnavailable(f"{role} snapshot contains duplicate evidence_id values")
    content_hashes = [row["content_hash"] for row in events]
    if len(content_hashes) != len(set(content_hashes)):
        raise DataVendorUnavailable(f"{role} snapshot contains duplicate event content hashes")
    canonical = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": role,
        "as_of_date": as_of_date,
        "observations": observations,
        "events": events,
        "source_policy": {
            "primary": "tushare",
            "us_revision_source": "ALFRED/official fixed map",
            "implicit_fallback": False,
        },
    }
    canonical["snapshot_hash"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return canonical


def load_role_snapshot(role: str, as_of_date: str, root: Path | None = None) -> dict[str, Any]:
    cache_root = root or snapshot_cache_root()
    path = next((item for item in _snapshot_candidates(role, as_of_date, cache_root) if item.is_file()), None)
    if path is None:
        raise DataVendorUnavailable(
            f"no private PIT snapshot for {role} on {as_of_date} under {cache_root}; "
            "implicit vendor fallback is disabled"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(f"cannot read macro snapshot {path}: {exc}") from exc
    return validate_role_snapshot(payload, role, as_of_date)


def render_role_snapshot(role: str, as_of_date: str) -> str:
    return json.dumps(
        load_role_snapshot(role, as_of_date),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def mark_legacy_macro_output(payload: dict[str, Any]) -> dict[str, Any]:
    agent = payload.get("agent")
    if agent not in {"emerging_markets", "news_sentiment"}:
        raise ValueError(f"not a legacy macro output: {agent!r}")
    return {**payload, "legacy_status": "legacy_unverified"}


__all__ = [
    "ALFRED_SERIES_MAP",
    "MACRO_SNAPSHOT_SCHEMA_VERSION",
    "ROLE_SNAPSHOT_NAMES",
    "ROLE_EXACT_SERIES_IDS",
    "ROLE_SERIES_PREFIXES",
    "load_role_snapshot",
    "mark_legacy_macro_output",
    "render_role_snapshot",
    "snapshot_cache_root",
    "validate_role_snapshot",
]
