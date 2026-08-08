"""Trusted China, commodity, and institutional source archives.

The module materializes four independent append-only route groups.  A known
permission blocker on the China government curve therefore cannot invalidate
otherwise complete China, commodity, or institutional captures.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests

from mosaic.scorecard.canonical_json import canonical_hash

from .a_share_archive import ASharePaginationError, AShareSchemaError
from .agent_materialization import (
    AgentDataMaterializationLedger,
    RouteCoverageReceipt,
    SnapshotBuildReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
)
from .commodity_conditions import (
    COMMODITY_CONDITION_INPUT_SCHEMA_VERSION,
    validate_commodity_conditions_input,
)
from .exceptions import DataVendorUnavailable
from .macro_snapshots import (
    CONTEXT_REQUIRED_COMPONENTS,
    MACRO_SNAPSHOT_SCHEMA_VERSION,
    ROLE_COMPONENT_PREFIXES,
    validate_role_snapshot,
)
from .macro_source_contracts import (
    CHINA_MACRO_SERIES_MAP,
    COMMODITY_CONTRACT_MAP,
    COMMODITY_FAMILY_CONTRACTS,
)
from .official_china_adapters import (
    OFFICIAL_CHINA_DOCUMENT_SPECS,
    fetch_official_china_release_set,
)
from .sector_archive import _paginate_incremental as _paginate_tushare_incremental
from .tushare import _query_pro
from .tushare_catalog import assert_endpoint_capture_preflight_allowed


CAPTURE_SCHEMA_VERSION = "china_agent_data_capture_group_v1"
COMPILER_VERSION = "china_agent_data_compiler_v1"
ARCHIVE_LOCK_TIMEOUT_SECONDS = 60 * 60
CHINA_ROUTE_GROUP = "official.cn_macro+tushare.cn_macro"
COMMODITY_ROUTE_GROUP = "tushare.commodities"
INSTITUTIONAL_ROUTE_GROUP = "tushare.institutional_flow"
CURVE_ROUTE_GROUP = "tushare.shibor_yield_curve"
ROUTE_GROUPS: dict[str, tuple[str, ...]] = {
    CHINA_ROUTE_GROUP: ("official.cn_macro", "tushare.cn_macro"),
    COMMODITY_ROUTE_GROUP: ("tushare.commodities",),
    INSTITUTIONAL_ROUTE_GROUP: ("tushare.institutional_flow",),
    CURVE_ROUTE_GROUP: ("tushare.shibor_yield_curve",),
}
INSTITUTIONAL_ETF_UNIVERSE = (
    "159915.SZ",
    "510050.SH",
    "510300.SH",
    "510500.SH",
    "588000.SH",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DECISION_CUTOFF = time(15, 0)
_TUSHARE_HARD_CAPS = {
    "daily_basic": 6_000,
    "fut_basic": 10_000,
    "moneyflow_hsgt": 300,
    "moneyflow_ind_ths": 5_000,
}
_REQUIRED_COMMODITY_FAMILIES = tuple(
    family
    for component in COMMODITY_CONTRACT_MAP.values()
    for family in component["required_families"]
)
_REQUIRED_OFFICIAL_DOCUMENTS = frozenset(
    {
        "nbs_industrial_activity",
        "nbs_fixed_asset_investment",
        "nbs_retail_sales",
        "nbs_employment_release",
        "nbs_cpi_release",
        "nbs_ppi_release",
        "pboc_financial_statistics",
        "pboc_omo_document",
        "pboc_lpr_document",
        "pboc_mpc_meeting",
        "pboc_monetary_policy_report",
        "customs_monthly_trade",
        "mof_fiscal_release",
    }
)
_TUSHARE_MACRO_FIELDS = {
    "cn_gdp": ("quarter", "gdp_yoy", "cn_gdp_yoy", "percent_yoy"),
    "cn_pmi": ("MONTH", "PMI010000", "cn_pmi_headline", "index"),
    "cn_cpi": ("month", "nt_yoy", "cn_cpi_yoy", "percent_yoy"),
    "cn_ppi": ("month", "ppi_yoy", "cn_ppi_yoy", "percent_yoy"),
}
_CHINA_SERIES_PROJECTION = {
    "cn_fixed_asset_investment_yoy": "china_growth_fixed_asset_investment_yoy",
    "cn_retail_sales_yoy": "china_growth_retail_sales_yoy",
    "cn_urban_unemployment_rate": "china_growth_urban_unemployment_rate",
    "cn_rmb_loan_flow": "china_credit_rmb_loan_flow",
    "cn_m2_yoy": "cn_money_m2_yoy",
}
_CHINA_OFFICIAL_BRANCHES = frozenset(
    branch
    for contract in CHINA_MACRO_SERIES_MAP.values()
    for branch in contract["required_branches"]
    if branch.startswith("official.")
)
_SOURCE_SCHEMA_HASH = canonical_hash(
    {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "route_groups": {key: list(value) for key, value in ROUTE_GROUPS.items()},
        "macro_endpoints": sorted(_TUSHARE_MACRO_FIELDS),
        "commodity_families": list(_REQUIRED_COMMODITY_FAMILIES),
        "institutional_etf_universe": list(INSTITUTIONAL_ETF_UNIVERSE),
        "tushare_hard_caps": _TUSHARE_HARD_CAPS,
        "commodity_inventory_pagination": "OFFSET_WITH_TERMINAL_CONFIRMATION",
    }
)


class ChinaAgentDataSchemaError(DataVendorUnavailable):
    """A provider response cannot satisfy the frozen route contract."""


@dataclass(frozen=True)
class ChinaRouteArchiveResult:
    source_receipts: tuple[SourceCaptureReceipt, ...]
    coverage_receipt: RouteCoverageReceipt
    cache_hit: bool
    group: dict[str, Any] | None


@dataclass(frozen=True)
class ChinaAgentArchiveResult:
    routes: dict[str, ChinaRouteArchiveResult]


@dataclass(frozen=True)
class ChinaAgentBuildResult:
    snapshots: dict[str, dict[str, Any]]
    build_receipts: tuple[SnapshotBuildReceipt, ...]


def china_agent_archive_path() -> Path:
    explicit = os.getenv("MOSAIC_CHINA_AGENT_ARCHIVE_DB")
    if explicit:
        return Path(explicit).expanduser()
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache_root / "agent_data" / "china_agent_data.sqlite3"


def china_agent_snapshot_root() -> Path:
    explicit = os.getenv("MOSAIC_CHINA_AGENT_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache_root / "agent_data" / "china_agent_snapshots"


def _capture_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ChinaAgentDataSchemaError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ChinaAgentDataSchemaError(f"{field} must include timezone")
    return parsed


def _date(value: Any, field: str) -> date:
    text = str(value or "").strip()
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ChinaAgentDataSchemaError(f"{field} must be a date") from exc


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ChinaAgentDataSchemaError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ChinaAgentDataSchemaError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ChinaAgentDataSchemaError(f"{field} must be finite")
    return number


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _is_transport_failure(exc: BaseException) -> bool:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(
            current,
            (TimeoutError, ConnectionError, requests.Timeout, requests.ConnectionError),
        ):
            return True
        for nested in (current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _private_tushare_fetch(*, endpoint: str, **params: str) -> Any:
    assert_endpoint_capture_preflight_allowed(endpoint)
    value = _query_pro(endpoint, **params)
    if hasattr(value, "to_dict"):
        if all(hasattr(value, method) for method in ("astype", "notna", "where")):
            value = value.astype(object).where(value.notna(), None)
        return value.to_dict(orient="records")
    return value


def _private_official_fetch(*, cutoff_at: str) -> list[dict[str, Any]]:
    return fetch_official_china_release_set(
        cutoff_at=cutoff_at,
        retrieved_at=_capture_now().isoformat(),
        document_types=tuple(sorted(_REQUIRED_OFFICIAL_DOCUMENTS)),
    )


def _seal_group(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = _json_copy(payload)
    body.pop("group_hash", None)
    body["group_hash"] = canonical_hash(body)
    return body


class ChinaAgentDataArchiveStore:
    """Append-only compressed independent route groups."""

    def __init__(self, path: Path | None = None, *, create: bool = True) -> None:
        self.path = path or china_agent_archive_path()
        self._available = self.path.exists()
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialise()
            self._available = True

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if not self._available:
            raise FileNotFoundError(self.path)
        if read_only:
            conn = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                timeout=30,
                isolation_level=None,
                uri=True,
            )
            conn.execute("PRAGMA query_only = ON")
        else:
            conn = sqlite3.connect(
                self.path,
                timeout=ARCHIVE_LOCK_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            conn.execute(
                f"PRAGMA busy_timeout = {ARCHIVE_LOCK_TIMEOUT_SECONDS * 1000}"
            )
            conn.execute("PRAGMA journal_mode = DELETE")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        self._available = True
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS china_agent_capture_groups (
                    capture_key TEXT PRIMARY KEY,
                    route_group TEXT NOT NULL,
                    group_hash TEXT NOT NULL UNIQUE,
                    as_of_date TEXT NOT NULL,
                    cutoff_at TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS china_agent_capture_as_of
                  ON china_agent_capture_groups(as_of_date, route_group, captured_at);
                CREATE TRIGGER IF NOT EXISTS china_agent_capture_groups_no_update
                  BEFORE UPDATE ON china_agent_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS china_agent_capture_groups_no_delete
                  BEFORE DELETE ON china_agent_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(zlib.decompress(row["payload_zlib"]).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("China agent archive payload is unreadable") from exc
        body = {key: value for key, value in payload.items() if key != "group_hash"}
        if (
            payload.get("group_hash") != row["group_hash"]
            or canonical_hash(body) != row["group_hash"]
        ):
            raise ValueError("China agent archive group hash mismatch")
        return payload

    def get_or_capture(
        self,
        capture_key: str,
        builder: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT * FROM china_agent_capture_groups WHERE capture_key = ?",
                    (capture_key,),
                ).fetchone()
                if existing is not None:
                    payload = self._decode(existing)
                    conn.execute("COMMIT")
                    return payload, True
                payload = builder()
                body = {key: value for key, value in payload.items() if key != "group_hash"}
                if payload.get("group_hash") != canonical_hash(body):
                    raise ValueError("builder returned an unsealed China agent group")
                conn.execute(
                    "INSERT INTO china_agent_capture_groups "
                    "(capture_key, route_group, group_hash, as_of_date, cutoff_at, "
                    "captured_at, payload_zlib) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        capture_key,
                        payload["route_group"],
                        payload["group_hash"],
                        payload["as_of_date"],
                        payload["cutoff_at"],
                        payload["captured_at"],
                        zlib.compress(_canonical_bytes(payload), level=9),
                    ),
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return payload, False

    def load_group(self, capture_key: str) -> dict[str, Any]:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM china_agent_capture_groups WHERE capture_key = ?",
                (capture_key,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"no China agent capture group for {capture_key}")
            return self._decode(row)

    def row_count(self) -> int:
        with self._connect(read_only=True) as conn:
            return int(
                conn.execute("SELECT count(*) FROM china_agent_capture_groups").fetchone()[0]
            )


def _period_bounds(value: Any) -> tuple[str, str]:
    text = str(value or "").strip().upper()
    if len(text) == 6 and text.isdigit():
        year, month = int(text[:4]), int(text[4:])
        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1).fromordinal(
                date(year, month + 1, 1).toordinal() - 1
            )
        return start.isoformat(), end.isoformat()
    if len(text) == 6 and text[4] == "Q" and text[5] in "1234":
        year, quarter = int(text[:4]), int(text[5])
        first_month = 1 + (quarter - 1) * 3
        start = date(year, first_month, 1)
        next_month = first_month + 3
        next_start = date(year + (next_month > 12), ((next_month - 1) % 12) + 1, 1)
        return start.isoformat(), date.fromordinal(next_start.toordinal() - 1).isoformat()
    raise ChinaAgentDataSchemaError(f"unsupported China macro period: {value!r}")


def _validate_official_documents(
    value: Any, *, cutoff: datetime
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ChinaAgentDataSchemaError("official China catalog returned no documents")
    documents = [_json_copy(row) for row in value]
    document_types = [str(row.get("document_type") or "") for row in documents]
    if len(document_types) != len(set(document_types)):
        raise ChinaAgentDataSchemaError("official China document types are duplicated")
    missing = sorted(_REQUIRED_OFFICIAL_DOCUMENTS - set(document_types))
    if missing:
        raise ChinaAgentDataSchemaError(
            "official China catalog lacks required documents: " + ", ".join(missing)
        )
    for row in documents:
        document_type = str(row.get("document_type") or "")
        if document_type not in OFFICIAL_CHINA_DOCUMENT_SPECS:
            raise ChinaAgentDataSchemaError("official China document type is unregistered")
        if row.get("branches_covered") != list(
            OFFICIAL_CHINA_DOCUMENT_SPECS[document_type]["branches"]
        ):
            raise ChinaAgentDataSchemaError(
                "official China document branch contract drift"
            )
        published = _timestamp(row.get("published_at"), "official.published_at")
        retrieved = _timestamp(row.get("retrieved_at"), "official.retrieved_at")
        if published > cutoff or retrieved > cutoff or published > retrieved:
            raise ChinaAgentDataSchemaError("official China document exceeds PIT cutoff")
        observations = row.get("observations")
        if not isinstance(observations, list):
            raise ChinaAgentDataSchemaError("official China observations must be a list")
        for observation in observations:
            if not isinstance(observation, dict) or not {
                "series_id",
                "source",
                "actual",
                "unit",
                "period_start",
                "period_end",
            } <= set(observation):
                raise ChinaAgentDataSchemaError("official China observation schema drift")
            _finite(observation["actual"], "official.actual")
            if date.fromisoformat(observation["period_end"]) > cutoff.date():
                raise ChinaAgentDataSchemaError("official China period exceeds PIT cutoff")
        if not str(row.get("content_hash") or "").startswith("sha256:"):
            raise ChinaAgentDataSchemaError("official China content hash is missing")
    return documents


def _latest_macro_observation(
    endpoint: str, rows: Any, *, as_of: date, captured_at: str
) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise ChinaAgentDataSchemaError(f"Tushare {endpoint} returned no rows")
    period_field, value_field, series_id, unit = _TUSHARE_MACRO_FIELDS[endpoint]
    candidates = []
    for raw in rows:
        if not isinstance(raw, dict) or period_field not in raw or value_field not in raw:
            raise ChinaAgentDataSchemaError(f"Tushare {endpoint} schema drift")
        start, end = _period_bounds(raw[period_field])
        if date.fromisoformat(end) <= as_of:
            if raw[value_field] is None:
                continue
            candidates.append((end, start, _finite(raw[value_field], value_field)))
    if not candidates:
        raise ChinaAgentDataSchemaError(f"Tushare {endpoint} has no PIT-eligible row")
    end, start, actual = max(candidates, key=lambda row: row[0])
    return {
        "series_id": series_id,
        "period_start": start,
        "period_end": end,
        "released_at": captured_at,
        "vintage_at": captured_at,
        "actual": actual,
        "previous": None,
        "expected": None,
        "unit": unit,
        "source": f"tushare.{endpoint}",
        "pit_status": "AVAILABLE_AS_OF",
        "evidence_key": f"{endpoint}:{end}",
    }


def _build_china_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    fetch_official: Callable[..., list[dict[str, Any]]],
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    official = _validate_official_documents(
        fetch_official(cutoff_at=cutoff_at), cutoff=cutoff
    )
    captured = _capture_now()
    if captured.tzinfo is None or captured > cutoff:
        raise ChinaAgentDataSchemaError("China macro capture exceeded PIT cutoff")
    observations = [
        _latest_macro_observation(
            endpoint,
            fetch_tushare(endpoint=endpoint),
            as_of=date.fromisoformat(as_of_date),
            captured_at=captured.isoformat(),
        )
        for endpoint in _TUSHARE_MACRO_FIELDS
    ]
    completed = _capture_now()
    if completed.tzinfo is None or completed > cutoff:
        raise ChinaAgentDataSchemaError("China macro capture exceeded PIT cutoff")
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": CHINA_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[CHINA_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "captured_at": completed.isoformat(),
            "official_documents": official,
            "tushare_observations": observations,
        }
    )


def _family_for_contract(row: Mapping[str, Any]) -> str | None:
    for family_id in _REQUIRED_COMMODITY_FAMILIES:
        contract = COMMODITY_FAMILY_CONTRACTS[family_id]
        if (
            str(row.get("exchange") or "") == contract["exchange"]
            and str(row.get("fut_code") or "").upper() == contract["product_code"]
            and str(row.get("ts_code") or "").endswith(
                "." + contract["ts_code_suffix"]
            )
        ):
            return family_id
    return None


def _normalise_commodity_input(
    *,
    as_of_date: str,
    market_session_date: str,
    metadata_rows: Sequence[Mapping[str, Any]],
    daily_rows: Sequence[Mapping[str, Any]],
    inventory_rows: Sequence[Mapping[str, Any]],
    captured_at: str,
) -> dict[str, Any]:
    session = _date(market_session_date, "market_session_date")
    daily_by_code: dict[str, dict[str, Any]] = {}
    for raw in daily_rows:
        row = _json_copy(raw)
        if _date(row.get("trade_date"), "fut_daily.trade_date") != session:
            raise ChinaAgentDataSchemaError("fut_daily returned a different session")
        code = str(row.get("ts_code") or "")
        if not code or code in daily_by_code:
            raise ChinaAgentDataSchemaError("fut_daily contract identity drift")
        daily_by_code[code] = row
    inventory_by_product: dict[str, list[dict[str, Any]]] = {}
    for raw in inventory_rows:
        row = _json_copy(raw)
        if _date(row.get("trade_date"), "fut_wsr.trade_date") != session:
            raise ChinaAgentDataSchemaError("fut_wsr returned a different session")
        product = str(row.get("symbol") or "").upper()
        if not product:
            raise ChinaAgentDataSchemaError("fut_wsr lacks product identity")
        inventory_by_product.setdefault(product, []).append(row)
    families = []
    for family_id in _REQUIRED_COMMODITY_FAMILIES:
        source = COMMODITY_FAMILY_CONTRACTS[family_id]
        contracts = []
        for raw in metadata_rows:
            if _family_for_contract(raw) != family_id:
                continue
            code = str(raw.get("ts_code") or "")
            daily = daily_by_code.get(code)
            if daily is None:
                continue
            settle = _finite(daily.get("settle"), "fut_daily.settle")
            volume = _finite(daily.get("vol"), "fut_daily.vol")
            open_interest = _finite(daily.get("oi"), "fut_daily.oi")
            if settle <= 0 or volume <= 0 or open_interest <= 0:
                continue
            delivery = str(raw.get("d_month") or "")
            if len(delivery) != 6 or not delivery.isdigit():
                raise ChinaAgentDataSchemaError("fut_basic delivery month schema drift")
            contracts.append(
                {
                    "ts_code": code,
                    "symbol": str(raw.get("symbol") or ""),
                    "exchange": source["exchange"],
                    "name": str(raw.get("name") or family_id),
                    "fut_code": source["product_code"],
                    "multiplier": _finite(raw.get("per_unit"), "fut_basic.per_unit"),
                    "trade_unit": str(raw.get("trade_unit") or "contract"),
                    "quote_unit": "cny_per_unit",
                    "list_date": _date(raw.get("list_date"), "fut_basic.list_date").isoformat(),
                    "delist_date": _date(raw.get("delist_date"), "fut_basic.delist_date").isoformat(),
                    "delivery_month": f"{delivery[:4]}-{delivery[4:]}",
                    "last_delivery_date": _date(raw.get("last_ddate"), "fut_basic.last_ddate").isoformat(),
                    "trade_date": session.isoformat(),
                    "settle": settle,
                    "volume": volume,
                    "open_interest": open_interest,
                    "metadata_released_at": captured_at,
                    "metadata_vintage_at": captured_at,
                    "price_released_at": captured_at,
                    "price_vintage_at": captured_at,
                    "metadata_source": source["contract_metadata_source"],
                    "price_source": source["daily_settlement_source"],
                    "pit_status": "AVAILABLE_AS_OF",
                    "metadata_evidence_id": f"metadata:{family_id}:{code}:{captured_at}",
                    "price_evidence_id": f"settlement:{family_id}:{code}:{session.isoformat()}:{captured_at}",
                }
            )
        if len(contracts) < 2:
            raise ChinaAgentDataSchemaError(
                f"commodity {family_id} lacks two dated contracts with settlements"
            )
        inventory = [
            row
            for row in inventory_by_product.get(source["product_code"], [])
            if row.get("vol") is not None
            and (row.get("pre_vol") is not None or row.get("vol_chg") is not None)
        ]
        if not inventory:
            raise ChinaAgentDataSchemaError(f"commodity {family_id} lacks inventory")
        actual = 0.0
        previous = 0.0
        for row in inventory:
            current = _finite(row.get("vol"), "fut_wsr.vol")
            prior = (
                _finite(row.get("pre_vol"), "fut_wsr.pre_vol")
                if row.get("pre_vol") is not None
                else current - _finite(row.get("vol_chg"), "fut_wsr.vol_chg")
            )
            if current < 0 or prior < 0:
                raise ChinaAgentDataSchemaError(
                    "fut_wsr inventory values must be non-negative"
                )
            actual += current
            previous += prior
        families.append(
            {
                "family_id": family_id,
                "component": source["component"],
                "contracts": contracts,
                "inventory": {
                    "series_id": f"inventory_{family_id.replace('@', '_')}",
                    "family_id": family_id,
                    "observation_date": session.isoformat(),
                    "released_at": captured_at,
                    "vintage_at": captured_at,
                    "actual": actual,
                    "previous": previous,
                    "unit": str(inventory[0].get("unit") or "provider_unit"),
                    "source": source["inventory_source"],
                    "pit_status": "AVAILABLE_AS_OF",
                    "evidence_id": f"inventory:{family_id}:{session.isoformat()}:{captured_at}",
                },
            }
        )
    return {
        "schema_version": COMMODITY_CONDITION_INPUT_SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "market_session_date": session.isoformat(),
        "families": families,
    }


def _build_commodity_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    market_session_date: str,
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    metadata: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    transport_call_count = 0
    for exchange in ("INE", "SHFE", "DCE"):
        basic_rows = fetch_tushare(endpoint="fut_basic", exchange=exchange, fut_type="1")
        daily_rows = fetch_tushare(
            endpoint="fut_daily", exchange=exchange, trade_date=market_session_date
        )
        transport_call_count += 2
        if not isinstance(basic_rows, list) or not isinstance(daily_rows, list):
            raise ChinaAgentDataSchemaError("commodity endpoint response must be rows")
        if len(basic_rows) >= _TUSHARE_HARD_CAPS["fut_basic"]:
            raise ChinaAgentDataSchemaError(
                "fut_basic reached its hard cap without terminal proof"
            )
        metadata.extend(_json_copy(basic_rows))
        daily.extend(_json_copy(daily_rows))
    try:
        inventory, inventory_call_count, inventory_duplicate_count = (
            _paginate_tushare_incremental(
                lambda endpoint, **params: fetch_tushare(
                    endpoint=endpoint, **params
                ),
                "fut_wsr",
                {"trade_date": market_session_date},
                confirm_terminal=True,
            )
        )
    except (ASharePaginationError, AShareSchemaError) as exc:
        raise ChinaAgentDataSchemaError(
            "fut_wsr pagination/schema closure failed"
        ) from exc
    transport_call_count += inventory_call_count
    if not isinstance(inventory, list) or not inventory:
        raise ChinaAgentDataSchemaError("fut_wsr returned no inventory")
    completed = _capture_now()
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    if completed.tzinfo is None or completed > cutoff:
        raise ChinaAgentDataSchemaError("commodity capture exceeded PIT cutoff")
    condition_input = _normalise_commodity_input(
        as_of_date=as_of_date,
        market_session_date=market_session_date,
        metadata_rows=metadata,
        daily_rows=daily,
        inventory_rows=inventory,
        captured_at=completed.isoformat(),
    )
    validate_commodity_conditions_input(condition_input, as_of_date=as_of_date)
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": COMMODITY_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[COMMODITY_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "captured_at": completed.isoformat(),
            "market_session_date": _date(market_session_date, "market_session_date").isoformat(),
            "condition_input": condition_input,
            "raw_row_counts": {
                "fut_basic": len(metadata),
                "fut_daily": len(daily),
                "fut_wsr": len(inventory),
            },
            "raw_duplicate_counts": {"fut_wsr": inventory_duplicate_count},
            "transport_call_count": transport_call_count,
        }
    )


def _build_institutional_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    market_session_date: str,
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    session = _date(market_session_date, "market_session_date")
    session_param = session.strftime("%Y%m%d")
    northbound = fetch_tushare(
        endpoint="moneyflow_hsgt", trade_date=session_param
    )
    industries = fetch_tushare(
        endpoint="moneyflow_ind_ths", trade_date=session_param
    )
    fund_rows = [
        row
        for ts_code in INSTITUTIONAL_ETF_UNIVERSE
        for row in fetch_tushare(
            endpoint="fund_share",
            ts_code=ts_code,
            start_date=session_param,
            end_date=session_param,
        )
    ]
    crowding = fetch_tushare(endpoint="daily_basic", trade_date=session_param)
    for endpoint, rows in (
        ("moneyflow_hsgt", northbound),
        ("moneyflow_ind_ths", industries),
        ("fund_share", fund_rows),
        ("daily_basic", crowding),
    ):
        if not isinstance(rows, list) or not rows:
            raise ChinaAgentDataSchemaError(f"{endpoint} returned no rows")
        hard_cap = _TUSHARE_HARD_CAPS.get(endpoint)
        if hard_cap is not None and len(rows) >= hard_cap:
            raise ChinaAgentDataSchemaError(
                f"{endpoint} reached its hard cap without terminal proof"
            )
        for row in rows:
            if not isinstance(row, dict) or _date(
                row.get("trade_date"), f"{endpoint}.trade_date"
            ) != session:
                raise ChinaAgentDataSchemaError(f"{endpoint} session/schema drift")
    if len(northbound) != 1:
        raise ChinaAgentDataSchemaError("moneyflow_hsgt exact-day query is not unique")
    north_money = _finite(northbound[0].get("north_money"), "north_money")
    industry_rows = []
    for row in industries:
        industry = str(row.get("industry") or row.get("name") or "").strip()
        if not industry:
            raise ChinaAgentDataSchemaError("moneyflow_ind_ths lacks industry identity")
        amount_field = "net_amount" if "net_amount" in row else "net_amount_rate"
        industry_rows.append(
            {"industry": industry, "net_amount": _finite(row.get(amount_field), amount_field)}
        )
    fund_by_code: dict[str, dict[str, Any]] = {}
    for row in fund_rows:
        code = str(row.get("ts_code") or "")
        if code not in INSTITUTIONAL_ETF_UNIVERSE or code in fund_by_code:
            raise ChinaAgentDataSchemaError("fund_share ETF identity drift")
        fund_by_code[code] = {
            "ts_code": code,
            "fd_share": _finite(row.get("fd_share"), "fund_share.fd_share"),
        }
    missing_etfs = sorted(set(INSTITUTIONAL_ETF_UNIVERSE) - set(fund_by_code))
    if missing_etfs:
        raise ChinaAgentDataSchemaError(
            "fund_share lacks registered ETFs: " + ", ".join(missing_etfs)
        )
    crowding_rows = []
    for row in crowding:
        code = str(row.get("ts_code") or "")
        if not code:
            raise ChinaAgentDataSchemaError("daily_basic lacks security identity")
        if row.get("turnover_rate") is None or row.get("volume_ratio") is None:
            continue
        crowding_rows.append(
            {
                "ts_code": code,
                "turnover_rate": _finite(row.get("turnover_rate"), "turnover_rate"),
                "volume_ratio": _finite(row.get("volume_ratio"), "volume_ratio"),
            }
        )
    if not crowding_rows:
        raise ChinaAgentDataSchemaError(
            "daily_basic has no complete crowding metric rows"
        )
    completed = _capture_now()
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    if completed.tzinfo is None or completed > cutoff:
        raise ChinaAgentDataSchemaError("institutional capture exceeded PIT cutoff")
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": INSTITUTIONAL_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[INSTITUTIONAL_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "captured_at": completed.isoformat(),
            "market_session_date": session.isoformat(),
            "northbound": {"north_money": north_money, "row_count": 1},
            "industry_rows": sorted(industry_rows, key=lambda row: row["industry"]),
            "fund_share_rows": [fund_by_code[code] for code in INSTITUTIONAL_ETF_UNIVERSE],
            "crowding_rows": sorted(crowding_rows, key=lambda row: row["ts_code"]),
        }
    )


def _build_curve_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    market_session_date: str,
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    session = _date(market_session_date, "market_session_date")
    session_param = session.strftime("%Y%m%d")
    # Query the recorded permission blocker first so a disabled yc_cb endpoint
    # cannot cause a partial Shibor transport on every retry.
    curve = fetch_tushare(endpoint="yc_cb", trade_date=session_param)
    shibor = fetch_tushare(
        endpoint="shibor", start_date=session_param, end_date=session_param
    )
    if not isinstance(curve, list) or not curve or not isinstance(shibor, list) or not shibor:
        raise ChinaAgentDataSchemaError("China curve endpoints returned no rows")
    shibor_row = shibor[0]
    shibor_date = _date(
        shibor_row.get("date") or shibor_row.get("trade_date"), "shibor.date"
    )
    if shibor_date != session:
        raise ChinaAgentDataSchemaError("Shibor row does not match market session")
    tenors: dict[int, float] = {}
    for row in curve:
        if _date(row.get("trade_date"), "yc_cb.trade_date") != session:
            raise ChinaAgentDataSchemaError("yc_cb row does not match market session")
        if str(row.get("curve_type")) != "0":
            continue
        term = int(_finite(row.get("curve_term"), "yc_cb.curve_term"))
        if term in {2, 10}:
            tenors[term] = _finite(row.get("yield"), "yc_cb.yield")
    if set(tenors) != {2, 10}:
        raise ChinaAgentDataSchemaError("yc_cb lacks exact 2Y/10Y government tenors")
    completed = _capture_now()
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    if completed.tzinfo is None or completed > cutoff:
        raise ChinaAgentDataSchemaError("China curve capture exceeded PIT cutoff")
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": CURVE_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[CURVE_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "captured_at": completed.isoformat(),
            "market_session_date": session.isoformat(),
            "shibor": {
                "overnight": _finite(shibor_row.get("on"), "shibor.on"),
                "three_month": _finite(shibor_row.get("3m"), "shibor.3m"),
            },
            "government_curve": {"2y": tenors[2], "10y": tenors[10]},
        }
    )


def _capture_key(
    route_group: str,
    *,
    as_of_date: str,
    cutoff_at: str,
    market_session_date: str,
) -> str:
    return canonical_hash(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "route_group": route_group,
            "route_ids": list(ROUTE_GROUPS[route_group]),
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "market_session_date": market_session_date,
            "commodity_families": list(_REQUIRED_COMMODITY_FAMILIES)
            if route_group == COMMODITY_ROUTE_GROUP
            else None,
            "institutional_etf_universe": list(INSTITUTIONAL_ETF_UNIVERSE)
            if route_group == INSTITUTIONAL_ROUTE_GROUP
            else None,
        }
    )


def _source_receipt(
    group: Mapping[str, Any], route_id: str
) -> SourceCaptureReceipt:
    captured_at = str(group["captured_at"])
    route_group = str(group["route_group"])
    duplicate_count = 0
    pagination_policy = "REGISTERED_BOUNDED_REQUEST_SET"
    if route_id == "official.cn_macro":
        documents = group["official_documents"]
        row_count = sum(len(row["observations"]) for row in documents)
        released_at = max(str(row["published_at"]) for row in documents)
        raw_hash = canonical_hash(
            {row["document_id"]: row["content_hash"] for row in documents}
        )
        dimensions = {
            "document_type": sorted(str(row["document_type"]) for row in documents)
        }
        provider = "official_cn"
        query_keys = ["catalog", "document_url"]
        page_count = len(documents)
        parser_version = "official_china_adapters_v1"
    elif route_id == "tushare.cn_macro":
        rows = group["tushare_observations"]
        row_count = len(rows)
        released_at = captured_at
        raw_hash = canonical_hash(rows)
        dimensions = {"endpoint": sorted(_TUSHARE_MACRO_FIELDS)}
        provider = "tushare"
        query_keys = []
        page_count = len(_TUSHARE_MACRO_FIELDS)
        parser_version = COMPILER_VERSION
    elif route_id == COMMODITY_ROUTE_GROUP:
        counts = group["raw_row_counts"]
        row_count = sum(int(value) for value in counts.values())
        released_at = captured_at
        raw_hash = canonical_hash(group["condition_input"])
        dimensions = {"family_id": sorted(_REQUIRED_COMMODITY_FAMILIES)}
        provider = "tushare"
        query_keys = ["exchange", "fut_type", "limit", "offset", "trade_date"]
        page_count = int(group["transport_call_count"])
        duplicate_count = int(group["raw_duplicate_counts"]["fut_wsr"])
        pagination_policy = (
            "REGISTERED_REQUEST_SET_WITH_OFFSET_TERMINAL_CONFIRMATION"
        )
        parser_version = COMPILER_VERSION
    elif route_id == INSTITUTIONAL_ROUTE_GROUP:
        row_count = (
            1
            + len(group["industry_rows"])
            + len(group["fund_share_rows"])
            + len(group["crowding_rows"])
        )
        released_at = captured_at
        raw_hash = canonical_hash(
            {
                "northbound": group["northbound"],
                "industry_rows": group["industry_rows"],
                "fund_share_rows": group["fund_share_rows"],
                "crowding_rows": group["crowding_rows"],
            }
        )
        dimensions = {
            "endpoint": [
                "daily_basic",
                "fund_share",
                "moneyflow_hsgt",
                "moneyflow_ind_ths",
            ],
            "etf": list(INSTITUTIONAL_ETF_UNIVERSE),
        }
        provider = "tushare"
        query_keys = ["end_date", "start_date", "trade_date", "ts_code"]
        page_count = 3 + len(INSTITUTIONAL_ETF_UNIVERSE)
        parser_version = COMPILER_VERSION
    elif route_id == CURVE_ROUTE_GROUP:
        row_count = 4
        released_at = captured_at
        raw_hash = canonical_hash(
            {"shibor": group["shibor"], "curve": group["government_curve"]}
        )
        dimensions = {"tenor": ["10y", "2y", "3m", "overnight"]}
        provider = "tushare"
        query_keys = ["end_date", "start_date", "trade_date"]
        page_count = 2
        parser_version = COMPILER_VERSION
    else:  # pragma: no cover - closed route invariant
        raise AssertionError(route_id)
    capture_id = (
        "china-agent:"
        + str(group["capture_key"]).removeprefix("sha256:")
        + ":"
        + route_id
    )
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": provider,
                "route_id": route_id,
                "request_hash": canonical_hash(
                    {
                        "route_group": route_group,
                        "route_id": route_id,
                        "as_of_date": group["as_of_date"],
                        "cutoff_at": group["cutoff_at"],
                        "market_session_date": group.get("market_session_date"),
                    }
                ),
                "capture_id": capture_id,
            },
            "transport": {
                "redacted_url": (
                    "https://official.cn/<allowlisted-catalog>/<document>"
                    if route_id == "official.cn_macro"
                    else "https://api.tushare.pro/<registered-endpoint>"
                ),
                "method": "GET" if route_id == "official.cn_macro" else "POST",
                "query_keys": sorted(query_keys),
                "pagination_policy": pagination_policy,
                "page_count": page_count,
            },
            "authority": {
                "provider": provider,
                "permission_tier": "public" if route_id == "official.cn_macro" else "configured-runtime",
                "api_version": "public-web-v1" if route_id == "official.cn_macro" else "pro-v1",
                "parser_version": parser_version,
            },
            "time": {
                "released_at": released_at,
                "vintage_at": captured_at,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "pit": {
                # The shared receipt schema names first-seen forward archives
                # OBSERVED_LIVE; the route manifest retains the stricter
                # FORWARD_ARCHIVE strategy and historical misses are rejected
                # before transport.
                "pit_mode": "OBSERVED_LIVE",
                "as_of_cutoff": group["cutoff_at"],
                "eligible": True,
                "blocker_codes": [],
                "vintage_query": None,
            },
            "content": {
                "raw_content_hash": raw_hash,
                "normalized_row_count": row_count,
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": group.get("market_session_date", group["as_of_date"]),
                "requested_end": group["as_of_date"],
                "observed_start": group.get("market_session_date", group["as_of_date"]),
                "observed_end": group["as_of_date"],
                "dimensions": dimensions,
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": duplicate_count,
                "empty_result_semantics": "NON_EMPTY",
            },
            "provenance": {
                "parent_capture_hash": None,
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def _source_receipts(group: Mapping[str, Any]) -> tuple[SourceCaptureReceipt, ...]:
    return tuple(
        _source_receipt(group, route_id)
        for route_id in sorted(group["route_ids"])
    )


def _coverage_receipt(
    *,
    route_group: str,
    as_of_date: str,
    cutoff_at: str,
    source_receipts: Sequence[SourceCaptureReceipt],
    status: str,
    blocker_codes: Sequence[str],
) -> RouteCoverageReceipt:
    by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt.receipt_hash
        for receipt in source_receipts
    }
    route_results = [
        {
            "route_id": route_id,
            "capture_receipt_hash": by_route.get(route_id),
            "status": "SUCCESS" if route_id in by_route else status,
        }
        for route_id in sorted(ROUTE_GROUPS[route_group])
    ]
    complete = all(row["status"] == "SUCCESS" for row in route_results)
    blockers = [] if complete else sorted(set(str(code) for code in blocker_codes))
    return RouteCoverageReceipt.seal(
        {
            "schema_version": "route_coverage_receipt_v1",
            "coverage_id": "china-agent-coverage:"
            + canonical_hash(
                {
                    "route_group": route_group,
                    "as_of_date": as_of_date,
                    "cutoff_at": cutoff_at,
                    "route_results": route_results,
                    "blocker_codes": blockers,
                }
            ).removeprefix("sha256:"),
            "window": {
                "start": f"{as_of_date}T00:00:00+08:00",
                "end": cutoff_at,
                "timezone": "Asia/Shanghai",
            },
            "required_route_ids": sorted(ROUTE_GROUPS[route_group]),
            "route_results": route_results,
            "coverage_complete": complete,
            "blocker_codes": blockers,
        }
    )


def _failed_route(
    *,
    route_group: str,
    as_of_date: str,
    cutoff_at: str,
    ledger: AgentDataMaterializationLedger,
    status: str,
    blocker: str,
) -> ChinaRouteArchiveResult:
    coverage = _coverage_receipt(
        route_group=route_group,
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        source_receipts=(),
        status=status,
        blocker_codes=(blocker,),
    )
    ledger.append_route_coverage(coverage)
    return ChinaRouteArchiveResult((), coverage, False, None)


def _archive_route(
    *,
    route_group: str,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    builder: Callable[[], dict[str, Any]],
) -> ChinaRouteArchiveResult:
    try:
        group, cache_hit = store.get_or_capture(capture_key, builder)
        sources = _source_receipts(group)
        coverage = _coverage_receipt(
            route_group=route_group,
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            source_receipts=sources,
            status="SUCCESS",
            blocker_codes=(),
        )
        ledger.append_capture_group(sources, coverage)
        return ChinaRouteArchiveResult(sources, coverage, cache_hit, group)
    except PermissionError:
        return _failed_route(
            route_group=route_group,
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="PERMISSION_DENIED",
            blocker="PERMISSION_DENIED",
        )
    except DataVendorUnavailable as exc:
        if _is_transport_failure(exc):
            status, blocker = "TRANSPORT_FAILED", "TRANSPORT_FAILED"
        else:
            status, blocker = "SCHEMA_DRIFT", "SCHEMA_DRIFT"
        return _failed_route(
            route_group=route_group,
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status=status,
            blocker=blocker,
        )
    except (TimeoutError, ConnectionError):
        return _failed_route(
            route_group=route_group,
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status="TRANSPORT_FAILED",
            blocker="TRANSPORT_FAILED",
        )


def archive_china_agent_sources(
    *,
    as_of_date: str,
    cutoff_at: str,
    market_session_date: str,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    fetch_official: Callable[..., list[dict[str, Any]]] = _private_official_fetch,
    fetch_tushare: Callable[..., Any] = _private_tushare_fetch,
) -> ChinaAgentArchiveResult:
    as_of = date.fromisoformat(as_of_date)
    session = _date(market_session_date, "market_session_date")
    if session > as_of:
        raise ValueError("market_session_date cannot exceed as_of_date")
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    local_cutoff = cutoff.astimezone(_SHANGHAI)
    if local_cutoff.date() != as_of or local_cutoff.time() != _DECISION_CUTOFF:
        raise ValueError("China agent cutoff must be 15:00 Asia/Shanghai on as-of")
    normalized_cutoff = cutoff.isoformat()
    now = _capture_now()
    if now.tzinfo is None:
        raise ChinaAgentDataSchemaError("trusted capture clock must include timezone")
    if now.astimezone(_SHANGHAI).date() < as_of:
        blocker = "CAPTURE_BEFORE_AS_OF_WINDOW"
    elif now > cutoff:
        blocker = "CAPTURE_AFTER_AS_OF_CUTOFF"
    else:
        blocker = None
    if blocker:
        return ChinaAgentArchiveResult(
            {
                route_group: _failed_route(
                    route_group=route_group,
                    as_of_date=as_of_date,
                    cutoff_at=normalized_cutoff,
                    ledger=ledger,
                    status="CAPTURE_REJECTED",
                    blocker=blocker,
                )
                for route_group in ROUTE_GROUPS
            }
        )
    keys = {
        route_group: _capture_key(
            route_group,
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            market_session_date=session.isoformat(),
        )
        for route_group in ROUTE_GROUPS
    }
    builders: dict[str, Callable[[], dict[str, Any]]] = {
        CHINA_ROUTE_GROUP: lambda: _build_china_group(
            capture_key=keys[CHINA_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            fetch_official=fetch_official,
            fetch_tushare=fetch_tushare,
        ),
        COMMODITY_ROUTE_GROUP: lambda: _build_commodity_group(
            capture_key=keys[COMMODITY_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            market_session_date=session.strftime("%Y%m%d"),
            fetch_tushare=fetch_tushare,
        ),
        INSTITUTIONAL_ROUTE_GROUP: lambda: _build_institutional_group(
            capture_key=keys[INSTITUTIONAL_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            market_session_date=session.strftime("%Y%m%d"),
            fetch_tushare=fetch_tushare,
        ),
        CURVE_ROUTE_GROUP: lambda: _build_curve_group(
            capture_key=keys[CURVE_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            market_session_date=session.strftime("%Y%m%d"),
            fetch_tushare=fetch_tushare,
        ),
    }
    return ChinaAgentArchiveResult(
        {
            route_group: _archive_route(
                route_group=route_group,
                capture_key=keys[route_group],
                as_of_date=as_of_date,
                cutoff_at=normalized_cutoff,
                store=store,
                ledger=ledger,
                builder=builders[route_group],
            )
            for route_group in ROUTE_GROUPS
        }
    )


def _load_ready_group(
    *,
    route_group: str,
    archive: ChinaAgentArchiveResult,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
) -> tuple[dict[str, Any], dict[str, SourceCaptureReceipt]]:
    result = archive.routes[route_group]
    if result.group is None:
        raise DataVendorUnavailable(f"required China route group is blocked: {route_group}")
    group = store.load_group(str(result.group["capture_key"]))
    if (
        group.get("schema_version") != CAPTURE_SCHEMA_VERSION
        or group.get("route_group") != route_group
    ):
        raise DataVendorUnavailable("China agent archive schema/route drift")
    receipts = {
        receipt.as_dict()["identity"]["route_id"]: receipt
        for receipt in _source_receipts(group)
    }
    for route_id, receipt in receipts.items():
        status = ledger.source_status(as_of=group["as_of_date"], route_id=route_id)
        if status["capture_receipt_hash"] != receipt.receipt_hash:
            raise DataVendorUnavailable(f"China agent source receipt drift: {route_id}")
    return group, receipts


def _official_observations(
    group: Mapping[str, Any], receipt: SourceCaptureReceipt
) -> list[dict[str, Any]]:
    observations = []
    for document in group["official_documents"]:
        for raw in document["observations"]:
            observations.append(
                {
                    "series_id": str(raw["series_id"]),
                    "period_start": str(raw["period_start"]),
                    "period_end": str(raw["period_end"]),
                    "released_at": str(document["published_at"]),
                    "vintage_at": str(group["captured_at"]),
                    "actual": _finite(raw["actual"], "official.actual"),
                    "previous": None,
                    "expected": None,
                    "unit": str(raw["unit"]),
                    "source": str(raw["source"]),
                    "pit_status": "AVAILABLE_AS_OF",
                    "evidence_id": (
                        f"{receipt.receipt_hash}:{document['revision_id']}:"
                        f"{raw['series_id']}"
                    ),
                }
            )
    return observations


def _china_observations(
    group: Mapping[str, Any], receipts: Mapping[str, SourceCaptureReceipt]
) -> list[dict[str, Any]]:
    rows = [
        {
            **row,
            "series_id": _CHINA_SERIES_PROJECTION.get(
                str(row["series_id"]), str(row["series_id"])
            ),
        }
        for row in _official_observations(group, receipts["official.cn_macro"])
        if row["source"] in _CHINA_OFFICIAL_BRANCHES
    ]
    tushare_receipt = receipts["tushare.cn_macro"]
    rows.extend(
        {
            **{key: value for key, value in raw.items() if key != "evidence_key"},
            "evidence_id": f"{tushare_receipt.receipt_hash}:{raw['evidence_key']}",
        }
        for raw in group["tushare_observations"]
    )
    return sorted(rows, key=lambda row: (row["series_id"], row["evidence_id"]))


def _commodity_snapshot(
    group: Mapping[str, Any], receipt: SourceCaptureReceipt
) -> dict[str, Any]:
    conditions = validate_commodity_conditions_input(
        group["condition_input"], as_of_date=group["as_of_date"]
    )
    prefixes = {
        "SC@INE": "energy_crude_curve",
        "CU@SHFE": "industrial_metal_copper_curve",
        "AU@SHFE": "gold_curve",
        "C@DCE": "agriculture_corn_curve",
        "M@DCE": "food_soymeal_curve",
    }
    observations = []
    for family_id in _REQUIRED_COMMODITY_FAMILIES:
        family = conditions["families"][family_id]
        term = family["term_structure"]
        observations.append(
            {
                "series_id": prefixes[family_id],
                "period_start": group["market_session_date"],
                "period_end": group["market_session_date"],
                "released_at": group["captured_at"],
                "vintage_at": group["captured_at"],
                "actual": float(term["near_settle"]),
                "previous": None,
                "expected": None,
                "unit": "cny_per_unit",
                "source": COMMODITY_FAMILY_CONTRACTS[family_id][
                    "daily_settlement_source"
                ],
                "pit_status": "AVAILABLE_AS_OF",
                "evidence_id": (
                    f"{receipt.receipt_hash}:{family_id}:"
                    f"{term['near_contract']}:{group['market_session_date']}"
                ),
            }
        )
    return validate_role_snapshot(
        {
            "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
            "role": "commodities",
            "as_of_date": group["as_of_date"],
            "observations": observations,
            "events": [],
            "commodity_conditions": group["condition_input"],
        },
        "commodities",
        group["as_of_date"],
    )


def _institutional_snapshot(
    group: Mapping[str, Any], receipt: SourceCaptureReceipt
) -> dict[str, Any]:
    session = group["market_session_date"]
    industry_amounts = [float(row["net_amount"]) for row in group["industry_rows"]]
    fund_shares = [float(row["fd_share"]) for row in group["fund_share_rows"]]
    turnovers = [float(row["turnover_rate"]) for row in group["crowding_rows"]]
    observations = [
        {
            "series_id": "market_flow_northbound",
            "period_start": session,
            "period_end": session,
            "released_at": group["captured_at"],
            "vintage_at": group["captured_at"],
            "actual": float(group["northbound"]["north_money"]),
            "previous": None,
            "expected": None,
            "unit": "100m_cny",
            "source": "tushare.moneyflow_hsgt",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"{receipt.receipt_hash}:northbound:{session}",
        },
        {
            "series_id": "sector_rotation_net_amount",
            "period_start": session,
            "period_end": session,
            "released_at": group["captured_at"],
            "vintage_at": group["captured_at"],
            "actual": sum(industry_amounts),
            "previous": None,
            "expected": None,
            "unit": "provider_unit",
            "source": "tushare.moneyflow_ind_ths",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"{receipt.receipt_hash}:sector:{session}",
        },
        {
            "series_id": "etf_share_registered_universe",
            "period_start": session,
            "period_end": session,
            "released_at": group["captured_at"],
            "vintage_at": group["captured_at"],
            "actual": sum(fund_shares),
            "previous": None,
            "expected": None,
            "unit": "10k_shares",
            "source": "tushare.fund_share",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"{receipt.receipt_hash}:etf-share:{session}",
        },
        {
            "series_id": "crowding_turnover_median",
            "period_start": session,
            "period_end": session,
            "released_at": group["captured_at"],
            "vintage_at": group["captured_at"],
            "actual": statistics.median(turnovers),
            "previous": None,
            "expected": None,
            "unit": "percent",
            "source": "tushare.daily_basic",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"{receipt.receipt_hash}:crowding:{session}",
        },
    ]
    component_coverage = {
        "market_wide_flow": {
            "eligible_count": 1,
            "observed_count": 1,
            "coverage_ratio": 1.0,
        },
        "sector_rotation": {
            "eligible_count": len(group["industry_rows"]),
            "observed_count": len(group["industry_rows"]),
            "coverage_ratio": 1.0,
        },
        "etf_share": {
            "eligible_count": len(INSTITUTIONAL_ETF_UNIVERSE),
            "observed_count": len(group["fund_share_rows"]),
            "coverage_ratio": len(group["fund_share_rows"])
            / len(INSTITUTIONAL_ETF_UNIVERSE),
        },
        "crowding": {
            "eligible_count": len(group["crowding_rows"]),
            "observed_count": len(group["crowding_rows"]),
            "coverage_ratio": 1.0,
        },
    }
    return validate_role_snapshot(
        {
            "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
            "role": "institutional_flow",
            "as_of_date": group["as_of_date"],
            "observations": observations,
            "events": [],
            "component_coverage": component_coverage,
        },
        "institutional_flow",
        group["as_of_date"],
    )


def _central_bank_snapshot(
    *,
    china_group: Mapping[str, Any],
    china_receipts: Mapping[str, SourceCaptureReceipt],
    curve_group: Mapping[str, Any],
    curve_receipt: SourceCaptureReceipt,
    china_context: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    official = _official_observations(
        china_group, china_receipts["official.cn_macro"]
    )
    selected = [
        row
        for row in official
        if row["source"] in {"official.pboc_omo_catalog", "official.pboc_lpr_catalog"}
    ]
    credit = next(
        row for row in official if row["source"] == "official.pboc_tsfin_flow_stock"
    )
    selected.append(
        {
            **credit,
            "series_id": "cn_credit_summary_tsfin",
            "evidence_id": credit["evidence_id"] + ":central",
        }
    )
    session = curve_group["market_session_date"]
    selected.extend(
        [
            {
                "series_id": "domestic_liquidity_shibor_overnight",
                "actual": curve_group["shibor"]["overnight"],
                "source": "tushare.shibor_overnight",
                "unit": "percent",
            },
            {
                "series_id": "money_market_shibor_3m",
                "actual": curve_group["shibor"]["three_month"],
                "source": "tushare.shibor_3m",
                "unit": "percent",
            },
            {
                "series_id": "cn_curve_2y",
                "actual": curve_group["government_curve"]["2y"],
                "source": "tushare.yc_cb_cn_government_2y",
                "unit": "percent",
            },
            {
                "series_id": "cn_curve_10y",
                "actual": curve_group["government_curve"]["10y"],
                "source": "tushare.yc_cb_cn_government_10y",
                "unit": "percent",
            },
        ]
    )
    for index, row in enumerate(selected):
        if "period_start" not in row:
            row.update(
                {
                    "period_start": session,
                    "period_end": session,
                    "released_at": curve_group["captured_at"],
                    "vintage_at": curve_group["captured_at"],
                    "previous": None,
                    "expected": None,
                    "pit_status": "AVAILABLE_AS_OF",
                    "evidence_id": f"{curve_receipt.receipt_hash}:curve:{index}:{session}",
                }
            )
    context_prefixes = tuple(
        prefix.casefold()
        for component in CONTEXT_REQUIRED_COMPONENTS["central_bank"]
        for prefix in ROLE_COMPONENT_PREFIXES["china"][component]
    )
    deterministic_context = [
        row
        for row in china_context
        if str(row["series_id"]).casefold().startswith(context_prefixes)
    ]
    return validate_role_snapshot(
        {
            "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
            "role": "central_bank",
            "as_of_date": china_group["as_of_date"],
            "observations": selected,
            "context_observations": deterministic_context,
            "events": [],
        },
        "central_bank",
        china_group["as_of_date"],
    )


def _required_routes(agent_id: str, tool_id: str) -> list[str]:
    matches = [
        binding["required_route_ids"]
        for binding in load_agent_data_route_manifest()["bindings"]
        if binding["agent_id"] == agent_id
        and binding["stage"] == agent_id
        and binding["tool_id"] == tool_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"missing exact route binding for {agent_id}/{tool_id}")
    return list(matches[0])


def _calendar_hash(
    ledger: AgentDataMaterializationLedger, *, as_of_date: str, route_id: str
) -> str:
    status = ledger.source_status(as_of=as_of_date, route_id=route_id)
    if status["status"] != "READY" or not status["capture_receipt_hash"]:
        raise DataVendorUnavailable(f"required calendar route is blocked: {route_id}")
    return str(status["capture_receipt_hash"])


def _write_snapshot(
    root: Path, role: str, as_of_date: str, snapshot: Mapping[str, Any]
) -> None:
    destination = root / as_of_date / f"{role}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_bytes(snapshot)
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataVendorUnavailable(
                f"existing China agent snapshot is unreadable: {destination}"
            ) from exc
        if existing != dict(snapshot):
            raise DataVendorUnavailable(
                f"refusing to replace a different China agent snapshot: {destination}"
            )
        return
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, destination)


def _build_receipt(
    *,
    role: str,
    tool_id: str,
    as_of_date: str,
    cutoff_at: str,
    source_hashes: Sequence[str],
    snapshot: Mapping[str, Any] | None,
    missing_routes: Sequence[str] = (),
    blockers: Sequence[str] = (),
) -> SnapshotBuildReceipt:
    required_routes = _required_routes(role, tool_id)
    missing = sorted(set(missing_routes))
    blocker_codes = sorted(set(blockers))
    now = _capture_now().isoformat()
    output_hash = None if snapshot is None else str(snapshot["snapshot_hash"])
    return SnapshotBuildReceipt.seal(
        {
            "schema_version": "snapshot_build_receipt_v1",
            "build_id": "china-agent-build:"
            + canonical_hash(
                {
                    "role": role,
                    "as_of_date": as_of_date,
                    "source_receipt_hashes": sorted(set(source_hashes)),
                    "output_hash": output_hash,
                    "missing_route_ids": missing,
                    "blocker_codes": blocker_codes,
                }
            ).removeprefix("sha256:"),
            "agent_id": role,
            "stage": role,
            "tool_id": tool_id,
            "as_of": as_of_date,
            "as_of_cutoff": cutoff_at,
            "source_receipt_hashes": sorted(set(source_hashes)),
            "compiler_version": COMPILER_VERSION,
            "output_contract_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
            "output_path": f"china_agent_snapshots/{as_of_date}/{role}.json",
            "output_hash": output_hash,
            "pit_mode": "MIXED_AUTHORITY",
            "earliest_trustworthy_date": as_of_date if snapshot is not None else None,
            "required_route_ids": required_routes,
            "missing_route_ids": missing,
            "terminal_state": "READY" if snapshot is not None else "BLOCKED",
            "blocker_codes": blocker_codes,
            "build_started_at": now,
            "build_finished_at": now,
        }
    )


def compile_china_agent_snapshots(
    *,
    archive: ChinaAgentArchiveResult,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    output_root: Path | None = None,
) -> ChinaAgentBuildResult:
    china_group, china_receipts = _load_ready_group(
        route_group=CHINA_ROUTE_GROUP,
        archive=archive,
        store=store,
        ledger=ledger,
    )
    commodity_group, commodity_receipts = _load_ready_group(
        route_group=COMMODITY_ROUTE_GROUP,
        archive=archive,
        store=store,
        ledger=ledger,
    )
    institutional_group, institutional_receipts = _load_ready_group(
        route_group=INSTITUTIONAL_ROUTE_GROUP,
        archive=archive,
        store=store,
        ledger=ledger,
    )
    china_observations = _china_observations(china_group, china_receipts)
    snapshots = {
        "china": validate_role_snapshot(
            {
                "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
                "role": "china",
                "as_of_date": china_group["as_of_date"],
                "observations": china_observations,
                "events": [],
            },
            "china",
            china_group["as_of_date"],
        ),
        "commodities": _commodity_snapshot(
            commodity_group, commodity_receipts[COMMODITY_ROUTE_GROUP]
        ),
        "institutional_flow": _institutional_snapshot(
            institutional_group,
            institutional_receipts[INSTITUTIONAL_ROUTE_GROUP],
        ),
    }
    as_of_date = str(china_group["as_of_date"])
    calendar_cny = _calendar_hash(
        ledger, as_of_date=as_of_date, route_id="tushare.eco_cal.cny"
    )
    calendar_eur = _calendar_hash(
        ledger, as_of_date=as_of_date, route_id="tushare.eco_cal.eur"
    )
    calendar_usd = _calendar_hash(
        ledger, as_of_date=as_of_date, route_id="tushare.eco_cal.usd"
    )
    build_receipts = [
        _build_receipt(
            role="china",
            tool_id="get_china_macro_snapshot",
            as_of_date=as_of_date,
            cutoff_at=china_group["cutoff_at"],
            source_hashes=[
                china_receipts["official.cn_macro"].receipt_hash,
                china_receipts["tushare.cn_macro"].receipt_hash,
                calendar_cny,
            ],
            snapshot=snapshots["china"],
        ),
        _build_receipt(
            role="commodities",
            tool_id="get_commodity_conditions_snapshot",
            as_of_date=as_of_date,
            cutoff_at=china_group["cutoff_at"],
            source_hashes=[
                commodity_receipts[COMMODITY_ROUTE_GROUP].receipt_hash,
                calendar_cny,
                calendar_eur,
                calendar_usd,
            ],
            snapshot=snapshots["commodities"],
        ),
        _build_receipt(
            role="institutional_flow",
            tool_id="get_market_positioning_snapshot",
            as_of_date=as_of_date,
            cutoff_at=china_group["cutoff_at"],
            source_hashes=[
                institutional_receipts[INSTITUTIONAL_ROUTE_GROUP].receipt_hash
            ],
            snapshot=snapshots["institutional_flow"],
        ),
    ]
    curve_result = archive.routes[CURVE_ROUTE_GROUP]
    if curve_result.group is None:
        curve_coverage = curve_result.coverage_receipt.as_dict()
        blocker_codes = curve_coverage["blocker_codes"] or ["MISSING_SOURCE_ROUTE"]
        build_receipts.append(
            _build_receipt(
                role="central_bank",
                tool_id="get_central_bank_snapshot",
                as_of_date=as_of_date,
                cutoff_at=china_group["cutoff_at"],
                source_hashes=[
                    china_receipts["official.cn_macro"].receipt_hash,
                    calendar_cny,
                ],
                snapshot=None,
                missing_routes=[CURVE_ROUTE_GROUP],
                blockers=blocker_codes,
            )
        )
    else:
        curve_group, curve_receipts = _load_ready_group(
            route_group=CURVE_ROUTE_GROUP,
            archive=archive,
            store=store,
            ledger=ledger,
        )
        snapshots["central_bank"] = _central_bank_snapshot(
            china_group=china_group,
            china_receipts=china_receipts,
            curve_group=curve_group,
            curve_receipt=curve_receipts[CURVE_ROUTE_GROUP],
            china_context=china_observations,
        )
        build_receipts.append(
            _build_receipt(
                role="central_bank",
                tool_id="get_central_bank_snapshot",
                as_of_date=as_of_date,
                cutoff_at=china_group["cutoff_at"],
                source_hashes=[
                    china_receipts["official.cn_macro"].receipt_hash,
                    curve_receipts[CURVE_ROUTE_GROUP].receipt_hash,
                    calendar_cny,
                ],
                snapshot=snapshots["central_bank"],
            )
        )
    destination_root = output_root or china_agent_snapshot_root()
    for role, snapshot in snapshots.items():
        _write_snapshot(destination_root, role, as_of_date, snapshot)
    persisted = tuple(
        ledger.append_or_reuse_snapshot_build(receipt)
        for receipt in build_receipts
    )
    return ChinaAgentBuildResult(snapshots, persisted)


__all__ = [
    "ARCHIVE_LOCK_TIMEOUT_SECONDS",
    "CAPTURE_SCHEMA_VERSION",
    "CHINA_ROUTE_GROUP",
    "COMPILER_VERSION",
    "COMMODITY_ROUTE_GROUP",
    "CURVE_ROUTE_GROUP",
    "INSTITUTIONAL_ETF_UNIVERSE",
    "INSTITUTIONAL_ROUTE_GROUP",
    "ChinaAgentArchiveResult",
    "ChinaAgentBuildResult",
    "ChinaAgentDataArchiveStore",
    "ChinaAgentDataSchemaError",
    "ChinaRouteArchiveResult",
    "archive_china_agent_sources",
    "china_agent_archive_path",
    "china_agent_snapshot_root",
    "compile_china_agent_snapshots",
]
