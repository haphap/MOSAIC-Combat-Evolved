"""Trusted China, commodity, institutional, and reference-rate archives."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests

from mosaic.scorecard.canonical_json import canonical_hash

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
    fetch_mof_chinabond_government_yield_curve,
)
from .runtime_paths import agent_cache_root, isolated_agent_runtime_path
from .tushare import _query_pro
from .tushare_catalog import assert_endpoint_capture_preflight_allowed


CAPTURE_SCHEMA_VERSION = "china_agent_data_capture_group_v2"
COMPILER_VERSION = "china_agent_data_compiler_v2"
HISTORICAL_REPLAY_TIME_POLICY_VERSION = "china_historical_replay_time_v1"
ARCHIVE_LOCK_TIMEOUT_SECONDS = 60 * 60
CHINA_ROUTE_GROUP = "official.cn_macro+tushare.cn_macro"
COMMODITY_ROUTE_GROUP = "tushare.commodities"
INSTITUTIONAL_ROUTE_GROUP = "tushare.institutional_flow"
CURVE_ROUTE_GROUP = "composite.cn_rates"
ROUTE_GROUPS: dict[str, tuple[str, ...]] = {
    CHINA_ROUTE_GROUP: ("official.cn_macro", "tushare.cn_macro"),
    COMMODITY_ROUTE_GROUP: ("tushare.commodities",),
    INSTITUTIONAL_ROUTE_GROUP: ("tushare.institutional_flow",),
    CURVE_ROUTE_GROUP: ("composite.cn_rates",),
}
LOGICAL_ROUTES = tuple(
    sorted(route_id for route_ids in ROUTE_GROUPS.values() for route_id in route_ids)
)
INSTITUTIONAL_ETF_UNIVERSE = (
    "159915.SZ",
    "510050.SH",
    "510300.SH",
    "510500.SH",
    "588000.SH",
)
INSTITUTIONAL_INDUSTRY_UNIVERSE = ("881121.TI", "881155.TI")
INSTITUTIONAL_CROWDING_UNIVERSE = ("000001.SZ", "600000.SH")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DECISION_CUTOFF = time(15, 0)
_TUSHARE_HARD_CAPS = {
    "daily_basic": 6_000,
    "fut_basic": 10_000,
    "fut_wsr": 1_000,
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
_CHINA_OFFICIAL_DOCUMENTS = frozenset(
    {
        "nbs_industrial_activity",
        "nbs_fixed_asset_investment",
        "nbs_retail_sales",
        "nbs_employment_release",
        "nbs_cpi_release",
        "nbs_ppi_release",
        "pboc_financial_statistics",
        "customs_monthly_trade",
        "mof_fiscal_release",
    }
)
_TUSHARE_MACRO_FIELDS = {
    "cn_gdp": ("quarter", "gdp_yoy", "cn_gdp_yoy", "percent_yoy"),
    "cn_pmi": ("month", "pmi010000", "cn_pmi_headline", "index"),
    "cn_cpi": ("month", "nt_yoy", "cn_cpi_yoy", "percent_yoy"),
    "cn_ppi": ("month", "ppi_yoy", "cn_ppi_yoy", "percent_yoy"),
}
_TUSHARE_MACRO_REQUEST_FIELDS = {
    "cn_gdp": "quarter,gdp_yoy",
    "cn_pmi": "month,pmi010000",
    "cn_cpi": "month,nt_yoy",
    "cn_ppi": "month,ppi_yoy",
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
        "institutional_industry_universe": list(INSTITUTIONAL_INDUSTRY_UNIVERSE),
        "institutional_crowding_universe": list(INSTITUTIONAL_CROWDING_UNIVERSE),
        "tushare_hard_caps": _TUSHARE_HARD_CAPS,
        "commodity_inventory_pagination": "EXACT_SYMBOL_SINGLE_REQUEST",
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
    isolated = isolated_agent_runtime_path("agent_data/china_agent_data.sqlite3")
    if isolated is not None:
        return isolated
    explicit = os.getenv("MOSAIC_CHINA_AGENT_ARCHIVE_DB")
    if explicit:
        return Path(explicit).expanduser()
    return agent_cache_root() / "agent_data" / "china_agent_data.sqlite3"


def china_agent_snapshot_root() -> Path:
    isolated = isolated_agent_runtime_path("agent_data/china_agent_snapshots")
    if isolated is not None:
        return isolated
    explicit = os.getenv("MOSAIC_CHINA_AGENT_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return agent_cache_root() / "agent_data" / "china_agent_snapshots"


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


def _private_official_fetch(
    *,
    cutoff_at: str,
    historical_replay: bool = False,
    document_types: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    return fetch_official_china_release_set(
        cutoff_at=cutoff_at,
        retrieved_at=_capture_now().isoformat(),
        historical_replay=historical_replay,
        document_types=tuple(
            sorted(
                _REQUIRED_OFFICIAL_DOCUMENTS
                if document_types is None
                else document_types
            )
        ),
    )


def _seal_group(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = _json_copy(payload)
    body.pop("group_hash", None)
    body["group_hash"] = canonical_hash(body)
    return body


def _capture_time_fields(
    *,
    completed: datetime,
    as_of_date: str,
    cutoff_at: str,
    historical_replay: bool,
    label: str,
) -> dict[str, Any]:
    if completed.tzinfo is None:
        raise ChinaAgentDataSchemaError("trusted capture clock must include timezone")
    if historical_replay:
        if date.fromisoformat(as_of_date) >= completed.astimezone(_SHANGHAI).date():
            raise ChinaAgentDataSchemaError(
                f"{label} historical replay date is not complete"
            )
        completed_at = completed.isoformat()
        return {
            "cutoff_at": completed_at,
            "captured_at": completed_at,
            "historical_replay": True,
            "historical_replay_time_policy_version": (
                HISTORICAL_REPLAY_TIME_POLICY_VERSION
            ),
        }
    if completed > _timestamp(cutoff_at, "cutoff_at"):
        raise ChinaAgentDataSchemaError(f"{label} capture exceeded PIT cutoff")
    return {"cutoff_at": cutoff_at, "captured_at": completed.isoformat()}


def _validate_replay_group(
    group: Mapping[str, Any], *, historical_replay: bool
) -> None:
    if historical_replay:
        if (
            group.get("historical_replay") is not True
            or group.get("historical_replay_time_policy_version")
            != HISTORICAL_REPLAY_TIME_POLICY_VERSION
            or group.get("cutoff_at") != group.get("captured_at")
        ):
            raise ChinaAgentDataSchemaError(
                "China historical replay authority is invalid"
            )
        captured = _timestamp(group.get("captured_at"), "captured_at")
        if date.fromisoformat(str(group["as_of_date"])) >= captured.astimezone(
            _SHANGHAI
        ).date():
            raise ChinaAgentDataSchemaError(
                "China historical replay capture must follow the as-of date"
            )
        return
    if (
        "historical_replay" in group
        or "historical_replay_time_policy_version" in group
    ):
        raise ChinaAgentDataSchemaError(
            "live China capture cannot use historical replay authority"
        )


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

    def load_route_group(self, as_of_date: str, route_group: str) -> dict[str, Any]:
        if route_group not in ROUTE_GROUPS:
            raise ValueError(f"unknown China agent route group: {route_group}")
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                "SELECT * FROM china_agent_capture_groups "
                "WHERE as_of_date = ? AND route_group = ? "
                "ORDER BY captured_at DESC",
                (as_of_date, route_group),
            ).fetchall()
            for row in rows:
                group = self._decode(row)
                if tuple(sorted(group.get("route_ids", ()))) == tuple(
                    sorted(ROUTE_GROUPS[route_group])
                ):
                    return group
            raise FileNotFoundError(
                f"no complete China agent capture group for {route_group} at {as_of_date}"
            )

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


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return next_month - timedelta(days=1)


def _latest_complete_macro_period(endpoint: str, as_of: date) -> str:
    if endpoint in {"cn_cpi", "cn_pmi", "cn_ppi"}:
        month = as_of.month
        year = as_of.year
        if as_of < _last_day_of_month(year, month):
            month -= 1
            if month == 0:
                year -= 1
                month = 12
        return f"{year:04d}{month:02d}"
    if endpoint == "cn_gdp":
        quarter = (as_of.month - 1) // 3 + 1
        quarter_end = _last_day_of_month(as_of.year, quarter * 3)
        if as_of < quarter_end:
            quarter -= 1
            if quarter == 0:
                return f"{as_of.year - 1}Q4"
        return f"{as_of.year}Q{quarter}"
    raise ChinaAgentDataSchemaError(f"unsupported China macro endpoint: {endpoint!r}")


def _china_macro_request(endpoint: str, as_of: date) -> dict[str, str]:
    fields = _TUSHARE_MACRO_REQUEST_FIELDS[endpoint]
    period = _latest_complete_macro_period(endpoint, as_of)
    return {
        ("q" if endpoint == "cn_gdp" else "m"): period,
        "fields": fields,
    }


def _validate_official_documents(
    value: Any,
    *,
    cutoff: datetime,
    historical_replay_captured_at: datetime | None = None,
    required_document_types: frozenset[str] = _REQUIRED_OFFICIAL_DOCUMENTS,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ChinaAgentDataSchemaError("official China catalog returned no documents")
    documents = [_json_copy(row) for row in value]
    document_types = [str(row.get("document_type") or "") for row in documents]
    if len(document_types) != len(set(document_types)):
        raise ChinaAgentDataSchemaError("official China document types are duplicated")
    missing = sorted(required_document_types - set(document_types))
    if missing:
        raise ChinaAgentDataSchemaError(
            "official China catalog lacks required documents: " + ", ".join(missing)
        )
    unexpected = sorted(set(document_types) - required_document_types)
    if unexpected:
        raise ChinaAgentDataSchemaError(
            "official China catalog returned out-of-scope documents: "
            + ", ".join(unexpected)
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
        if (
            published > cutoff
            or published > retrieved
            or (
                historical_replay_captured_at is None
                and retrieved > cutoff
            )
            or (
                historical_replay_captured_at is not None
                and retrieved > historical_replay_captured_at
            )
        ):
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
    expected_period = _latest_complete_macro_period(endpoint, as_of)
    candidates = []
    for raw in rows:
        if not isinstance(raw, dict) or period_field not in raw or value_field not in raw:
            raise ChinaAgentDataSchemaError(f"Tushare {endpoint} schema drift")
        start, end = _period_bounds(raw[period_field])
        if str(raw[period_field]).upper() != expected_period:
            continue
        if raw[value_field] is None:
            continue
        candidates.append((end, start, _finite(raw[value_field], value_field)))
    if len(candidates) != 1:
        raise ChinaAgentDataSchemaError(
            f"Tushare {endpoint} did not return exactly one requested period"
        )
    end, start, actual = candidates[0]
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
    historical_replay: bool,
    requested_route_ids: tuple[str, ...],
    official_document_types: tuple[str, ...] | None,
    fetch_official: Callable[..., list[dict[str, Any]]],
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    requested = frozenset(requested_route_ids)
    required_official_documents = frozenset(
        _REQUIRED_OFFICIAL_DOCUMENTS
        if official_document_types is None
        else official_document_types
    )
    official_request = {
        "cutoff_at": cutoff_at,
        **({"historical_replay": True} if historical_replay else {}),
        **(
            {"document_types": tuple(sorted(required_official_documents))}
            if official_document_types is not None
            else {}
        ),
    }
    official_rows = (
        fetch_official(**official_request)
        if "official.cn_macro" in requested
        else []
    )
    captured = _capture_now()
    _capture_time_fields(
        completed=captured,
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        historical_replay=historical_replay,
        label="China macro",
    )
    official = (
        _validate_official_documents(
            official_rows,
            cutoff=cutoff,
            historical_replay_captured_at=(captured if historical_replay else None),
            required_document_types=required_official_documents,
        )
        if "official.cn_macro" in requested
        else []
    )
    macro_requests = {
        endpoint: _china_macro_request(endpoint, date.fromisoformat(as_of_date))
        for endpoint in _TUSHARE_MACRO_FIELDS
    }
    observations = (
        [
            _latest_macro_observation(
                endpoint,
                fetch_tushare(endpoint=endpoint, **macro_requests[endpoint]),
                as_of=date.fromisoformat(as_of_date),
                captured_at=captured.isoformat(),
            )
            for endpoint in _TUSHARE_MACRO_FIELDS
        ]
        if "tushare.cn_macro" in requested
        else []
    )
    completed = _capture_now()
    timing = _capture_time_fields(
        completed=completed,
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        historical_replay=historical_replay,
        label="China macro",
    )
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": CHINA_ROUTE_GROUP,
            "route_ids": list(requested_route_ids),
            "as_of_date": as_of_date,
            **timing,
            "official_documents": official,
            "tushare_macro_requests": macro_requests,
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
    historical_replay: bool,
    market_session_date: str,
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    session = _date(market_session_date, "market_session_date")
    session_param = session.strftime("%Y%m%d")
    metadata: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    commodity_requests = {
        "fut_basic": [],
        "fut_daily": [],
        "fut_wsr": [],
    }
    transport_call_count = 0
    for family_id in _REQUIRED_COMMODITY_FAMILIES:
        contract = COMMODITY_FAMILY_CONTRACTS[family_id]
        basic_params = {
            "exchange": contract["exchange"],
            "fut_type": "1",
            "fut_code": contract["product_code"],
        }
        basic_rows = fetch_tushare(endpoint="fut_basic", **basic_params)
        transport_call_count += 1
        commodity_requests["fut_basic"].append(dict(basic_params))
        if not isinstance(basic_rows, list):
            raise ChinaAgentDataSchemaError("fut_basic response must be rows")
        if len(basic_rows) >= _TUSHARE_HARD_CAPS["fut_basic"]:
            raise ChinaAgentDataSchemaError(
                "fut_basic reached its hard cap without terminal proof"
            )
        eligible = []
        for raw in basic_rows:
            row = _json_copy(raw)
            if _family_for_contract(row) != family_id:
                raise ChinaAgentDataSchemaError(
                    "fut_basic returned an unrelated product"
                )
            code = str(row.get("ts_code") or "")
            if not code:
                raise ChinaAgentDataSchemaError("fut_basic lacks contract identity")
            listed = _date(row.get("list_date"), "fut_basic.list_date")
            delisted = _date(row.get("delist_date"), "fut_basic.delist_date")
            if (
                listed <= session <= delisted
                and (delisted - session).days
                >= COMMODITY_FAMILY_CONTRACTS[family_id]["roll_rule"][
                    "minimum_days_to_delist"
                ]
            ):
                eligible.append(row)
        eligible.sort(key=lambda row: (row["delist_date"], row["ts_code"]))
        selected = eligible[:2]
        if len(selected) != 2 or len({row["ts_code"] for row in selected}) != 2:
            raise ChinaAgentDataSchemaError(
                f"commodity {family_id} lacks exactly two roll-eligible contracts"
            )
        metadata.extend(selected)
        for row in selected:
            code = str(row["ts_code"])
            daily_params = {
                "ts_code": code,
                "start_date": session_param,
                "end_date": session_param,
            }
            commodity_requests["fut_daily"].append(dict(daily_params))
            daily_rows = fetch_tushare(endpoint="fut_daily", **daily_params)
            transport_call_count += 1
            if not isinstance(daily_rows, list):
                raise ChinaAgentDataSchemaError("fut_daily response must be rows")
            if any(str(row.get("ts_code") or "") != code for row in daily_rows):
                raise ChinaAgentDataSchemaError("fut_daily returned an unrelated contract")
            daily.extend(_json_copy(daily_rows))
        inventory_params = {
            "trade_date": market_session_date,
            "symbol": contract["product_code"],
        }
        commodity_requests["fut_wsr"].append(dict(inventory_params))
        inventory_rows = fetch_tushare(endpoint="fut_wsr", **inventory_params)
        transport_call_count += 1
        if not isinstance(inventory_rows, list):
            raise ChinaAgentDataSchemaError("fut_wsr response must be rows")
        if len(inventory_rows) >= _TUSHARE_HARD_CAPS["fut_wsr"]:
            raise ChinaAgentDataSchemaError(
                "fut_wsr reached its hard cap without terminal proof"
            )
        if any(
            str(row.get("symbol") or "").upper() != contract["product_code"]
            for row in inventory_rows
        ):
            raise ChinaAgentDataSchemaError("fut_wsr returned an unrelated product")
        inventory.extend(_json_copy(inventory_rows))
    if not isinstance(inventory, list) or not inventory:
        raise ChinaAgentDataSchemaError("fut_wsr returned no inventory")
    completed = _capture_now()
    timing = _capture_time_fields(
        completed=completed,
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        historical_replay=historical_replay,
        label="commodity",
    )
    condition_input = _normalise_commodity_input(
        as_of_date=as_of_date,
        market_session_date=market_session_date,
        metadata_rows=metadata,
        daily_rows=daily,
        inventory_rows=inventory,
        captured_at=cutoff_at if historical_replay else completed.isoformat(),
    )
    validate_commodity_conditions_input(condition_input, as_of_date=as_of_date)
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": COMMODITY_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[COMMODITY_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            **timing,
            "market_session_date": _date(market_session_date, "market_session_date").isoformat(),
            "condition_input": condition_input,
            "raw_row_counts": {
                "fut_basic": len(metadata),
                "fut_daily": len(daily),
                "fut_wsr": len(inventory),
            },
            "raw_duplicate_counts": {"fut_wsr": 0},
            "commodity_requests": commodity_requests,
            "transport_call_count": transport_call_count,
        }
    )


def _build_institutional_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    historical_replay: bool,
    market_session_date: str,
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    session = _date(market_session_date, "market_session_date")
    session_param = session.strftime("%Y%m%d")
    request_sets = {
        "moneyflow": [
            {"ts_code": ts_code, "trade_date": session_param}
            for ts_code in INSTITUTIONAL_CROWDING_UNIVERSE
        ],
        "moneyflow_ind_ths": [
            {"ts_code": ts_code, "trade_date": session_param}
            for ts_code in INSTITUTIONAL_INDUSTRY_UNIVERSE
        ],
        "fund_share": [
            {"ts_code": ts_code, "start_date": session_param, "end_date": session_param}
            for ts_code in INSTITUTIONAL_ETF_UNIVERSE
        ],
        "daily_basic": [
            {"ts_code": ts_code, "trade_date": session_param}
            for ts_code in INSTITUTIONAL_CROWDING_UNIVERSE
        ],
    }
    market_flow_rows: list[dict[str, Any]] = []
    for request in request_sets["moneyflow"]:
        rows = fetch_tushare(endpoint="moneyflow", **request)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ChinaAgentDataSchemaError("moneyflow exact request is not unique")
        row = rows[0]
        if (
            not isinstance(row, dict)
            or str(row.get("ts_code") or "") != request["ts_code"]
            or _date(row.get("trade_date"), "moneyflow.trade_date") != session
        ):
            raise ChinaAgentDataSchemaError("moneyflow identity/session drift")
        market_flow_rows.append(
            {
                "ts_code": request["ts_code"],
                "net_mf_amount": _finite(
                    row.get("net_mf_amount"), "moneyflow.net_mf_amount"
                ),
            }
        )
    industries: list[dict[str, Any]] = []
    for request in request_sets["moneyflow_ind_ths"]:
        rows = fetch_tushare(endpoint="moneyflow_ind_ths", **request)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ChinaAgentDataSchemaError(
                "moneyflow_ind_ths exact request is not unique"
            )
        row = rows[0]
        if (
            not isinstance(row, dict)
            or str(row.get("ts_code") or "") != request["ts_code"]
            or _date(row.get("trade_date"), "moneyflow_ind_ths.trade_date")
            != session
        ):
            raise ChinaAgentDataSchemaError("moneyflow_ind_ths identity/session drift")
        industries.append(row)
    fund_rows: list[dict[str, Any]] = []
    for request in request_sets["fund_share"]:
        rows = fetch_tushare(endpoint="fund_share", **request)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ChinaAgentDataSchemaError("fund_share exact request is not unique")
        row = rows[0]
        if (
            not isinstance(row, dict)
            or str(row.get("ts_code") or "") != request["ts_code"]
            or _date(row.get("trade_date"), "fund_share.trade_date") != session
        ):
            raise ChinaAgentDataSchemaError("fund_share identity/session drift")
        fund_rows.append(row)
    crowding: list[dict[str, Any]] = []
    for request in request_sets["daily_basic"]:
        rows = fetch_tushare(endpoint="daily_basic", **request)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ChinaAgentDataSchemaError("daily_basic exact request is not unique")
        row = rows[0]
        if (
            not isinstance(row, dict)
            or str(row.get("ts_code") or "") != request["ts_code"]
            or _date(row.get("trade_date"), "daily_basic.trade_date") != session
        ):
            raise ChinaAgentDataSchemaError("daily_basic identity/session drift")
        crowding.append(row)
    industry_rows = []
    for row in industries:
        trade_date = _date(row.get("trade_date"), "moneyflow_ind_ths.trade_date")
        if str(row.get("ts_code") or "") not in INSTITUTIONAL_INDUSTRY_UNIVERSE:
            raise ChinaAgentDataSchemaError("moneyflow_ind_ths identity drift")
        industry = str(row.get("industry") or row.get("name") or "").strip()
        if not industry:
            raise ChinaAgentDataSchemaError("moneyflow_ind_ths lacks industry identity")
        amount_field = "net_amount" if "net_amount" in row else "net_amount_rate"
        if trade_date != session:
            raise ChinaAgentDataSchemaError("moneyflow_ind_ths session/schema drift")
        industry_rows.append(
            {
                "ts_code": str(row["ts_code"]),
                "industry": industry,
                "net_amount": _finite(row.get(amount_field), amount_field),
            }
        )
    if len(industry_rows) != len(INSTITUTIONAL_INDUSTRY_UNIVERSE) or len(
        {row["ts_code"] for row in industry_rows}
    ) != len(INSTITUTIONAL_INDUSTRY_UNIVERSE):
        raise ChinaAgentDataSchemaError(
            "moneyflow_ind_ths fixed universe is incomplete"
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
        if code not in INSTITUTIONAL_CROWDING_UNIVERSE:
            raise ChinaAgentDataSchemaError("daily_basic identity drift")
        if _date(row.get("trade_date"), "daily_basic.trade_date") != session:
            raise ChinaAgentDataSchemaError("daily_basic session/schema drift")
        if row.get("turnover_rate") is None or row.get("volume_ratio") is None:
            raise ChinaAgentDataSchemaError("daily_basic fixed universe is incomplete")
        crowding_rows.append(
            {
                "ts_code": code,
                "turnover_rate": _finite(row.get("turnover_rate"), "turnover_rate"),
                "volume_ratio": _finite(row.get("volume_ratio"), "volume_ratio"),
            }
        )
    if (
        len(crowding_rows) != len(INSTITUTIONAL_CROWDING_UNIVERSE)
        or len({row["ts_code"] for row in crowding_rows})
        != len(INSTITUTIONAL_CROWDING_UNIVERSE)
    ):
        raise ChinaAgentDataSchemaError(
            "daily_basic fixed universe is incomplete"
        )
    completed = _capture_now()
    timing = _capture_time_fields(
        completed=completed,
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        historical_replay=historical_replay,
        label="institutional",
    )
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": INSTITUTIONAL_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[INSTITUTIONAL_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            **timing,
            "market_session_date": session.isoformat(),
            "market_flow_rows": sorted(
                market_flow_rows, key=lambda row: row["ts_code"]
            ),
            "industry_rows": sorted(industry_rows, key=lambda row: row["ts_code"]),
            "fund_share_rows": [fund_by_code[code] for code in INSTITUTIONAL_ETF_UNIVERSE],
            "crowding_rows": sorted(crowding_rows, key=lambda row: row["ts_code"]),
            "institutional_requests": request_sets,
        }
    )


def _build_curve_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    historical_replay: bool,
    market_session_date: str,
    fetch_official_curve: Callable[..., dict[str, Any]],
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    session = _date(market_session_date, "market_session_date")
    curve_start = session - timedelta(days=365)
    curve_payload = fetch_official_curve(
        start_date=curve_start.isoformat(),
        end_date=session.isoformat(),
    )
    if (
        not isinstance(curve_payload, dict)
        or curve_payload.get("provider") != "MOF_CHINABOND"
        or curve_payload.get("yield_type") != "MATURITY"
        or curve_payload.get("release_time") != "17:30:00+08:00"
        or not isinstance(curve_payload.get("request_windows"), list)
        or not isinstance(curve_payload.get("response_hashes"), list)
    ):
        raise ChinaAgentDataSchemaError(
            "official government curve lineage is incomplete"
        )
    curve = curve_payload.get("rows")
    if not isinstance(curve, list) or not curve:
        raise ChinaAgentDataSchemaError("China curve endpoints returned no rows")
    required_tenors = {1, 2, 3, 5, 7, 10, 30}
    tenors_by_date: dict[date, dict[int, float]] = {}
    curve_rows: list[dict[str, Any]] = []
    seen_curve_keys: set[tuple[str, int]] = set()
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    for row in curve:
        if not isinstance(row, dict):
            raise ChinaAgentDataSchemaError("official government curve row is invalid")
        trade_date = _date(row.get("trade_date"), "government_curve.trade_date")
        if trade_date < curve_start or trade_date > session:
            raise ChinaAgentDataSchemaError(
                "official government curve row is outside the requested window"
            )
        if str(row.get("curve_type")) != "0":
            raise ChinaAgentDataSchemaError(
                "official government curve is not a maturity Treasury curve"
            )
        term = int(_finite(row.get("curve_term"), "government_curve.curve_term"))
        if term not in required_tenors:
            continue
        key = (trade_date.isoformat(), term)
        if key in seen_curve_keys:
            raise ChinaAgentDataSchemaError(
                "official government curve has duplicate date/tenor rows"
            )
        seen_curve_keys.add(key)
        value = _finite(row.get("yield"), "government_curve.yield")
        released_at = _timestamp(
            str(row.get("released_at")), "government_curve.released_at"
        )
        expected_release = datetime.combine(
            trade_date,
            time(17, 30),
            tzinfo=_SHANGHAI,
        )
        if released_at != expected_release:
            raise ChinaAgentDataSchemaError(
                "official government curve violates the 17:30 publication contract"
            )
        if released_at > cutoff:
            continue
        curve_rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "released_at": released_at.isoformat(),
                "curve_type": "0",
                "curve_term": term,
                "yield": value,
            }
        )
        tenors_by_date.setdefault(trade_date, {})[term] = value
    if not tenors_by_date or any(
        set(tenors) != required_tenors for tenors in tenors_by_date.values()
    ):
        raise ChinaAgentDataSchemaError(
            "official government curve lacks seven exact tenors before the cutoff"
        )
    selected_session = max(tenors_by_date)
    latest_tenors = tenors_by_date[selected_session]
    selected_session_param = selected_session.strftime("%Y%m%d")
    shibor = fetch_tushare(
        endpoint="shibor",
        start_date=selected_session_param,
        end_date=selected_session_param,
    )
    if not isinstance(shibor, list) or not shibor:
        raise ChinaAgentDataSchemaError("China curve endpoints returned no rows")
    shibor_row = shibor[0]
    shibor_date = _date(
        shibor_row.get("date") or shibor_row.get("trade_date"), "shibor.date"
    )
    if shibor_date != selected_session:
        raise ChinaAgentDataSchemaError("Shibor row does not match curve session")
    completed = _capture_now()
    timing = _capture_time_fields(
        completed=completed,
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        historical_replay=historical_replay,
        label="China curve",
    )
    return _seal_group(
        {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_key": capture_key,
            "route_group": CURVE_ROUTE_GROUP,
            "route_ids": list(ROUTE_GROUPS[CURVE_ROUTE_GROUP]),
            "as_of_date": as_of_date,
            **timing,
            "market_session_date": selected_session.isoformat(),
            "requested_market_session_date": session.isoformat(),
            "shibor": {
                "overnight": _finite(shibor_row.get("on"), "shibor.on"),
                "three_month": _finite(shibor_row.get("3m"), "shibor.3m"),
            },
            "curve_history_start": curve_start.isoformat(),
            "government_curve_rows": sorted(
                curve_rows,
                key=lambda row: (row["trade_date"], row["curve_term"]),
            ),
            "government_curve": {
                "2y": latest_tenors[2],
                "10y": latest_tenors[10],
            },
            "government_curve_source": {
                "schema_version": curve_payload.get("schema_version"),
                "provider": curve_payload["provider"],
                "source_url": curve_payload.get("source_url"),
                "yield_type": curve_payload["yield_type"],
                "release_time": curve_payload["release_time"],
                "request_windows": curve_payload["request_windows"],
                "response_hashes": curve_payload["response_hashes"],
                "session_released_at": datetime.combine(
                    selected_session,
                    time(17, 30),
                    tzinfo=_SHANGHAI,
                ).isoformat(),
            },
        }
    )


def _capture_key(
    route_group: str,
    *,
    as_of_date: str,
    cutoff_at: str,
    historical_replay: bool,
    market_session_date: str,
    requested_route_ids: tuple[str, ...],
    official_document_types: tuple[str, ...] | None = None,
) -> str:
    identity = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "route_group": route_group,
        "route_ids": list(requested_route_ids),
        "as_of_date": as_of_date,
        "market_session_date": market_session_date,
        "commodity_families": list(_REQUIRED_COMMODITY_FAMILIES)
        if route_group == COMMODITY_ROUTE_GROUP
        else None,
        "commodity_request_contract": (
            {
                "fut_basic": [
                    {
                        "exchange": COMMODITY_FAMILY_CONTRACTS[family]["exchange"],
                        "fut_type": "1",
                        "fut_code": COMMODITY_FAMILY_CONTRACTS[family][
                            "product_code"
                        ],
                    }
                    for family in _REQUIRED_COMMODITY_FAMILIES
                ],
                "fut_daily": {
                    "fields": ["ts_code", "start_date", "end_date"],
                    "window": market_session_date,
                },
                "fut_wsr": {
                    "fields": ["trade_date", "symbol"],
                    "trade_date": market_session_date,
                    "pagination": "NONE",
                },
            }
            if route_group == COMMODITY_ROUTE_GROUP
            else None
        ),
        "institutional_etf_universe": list(INSTITUTIONAL_ETF_UNIVERSE)
        if route_group == INSTITUTIONAL_ROUTE_GROUP
        else None,
        "institutional_industry_universe": list(INSTITUTIONAL_INDUSTRY_UNIVERSE)
        if route_group == INSTITUTIONAL_ROUTE_GROUP
        else None,
        "institutional_crowding_universe": list(INSTITUTIONAL_CROWDING_UNIVERSE)
        if route_group == INSTITUTIONAL_ROUTE_GROUP
        else None,
        "institutional_request_contract": (
            {
                "moneyflow": ["ts_code", "trade_date"],
                "moneyflow_ind_ths": ["ts_code", "trade_date"],
                "fund_share": ["ts_code", "start_date", "end_date"],
                "daily_basic": ["ts_code", "trade_date"],
                "pagination": "NONE",
            }
            if route_group == INSTITUTIONAL_ROUTE_GROUP
            else None
        ),
        **(
            {
                "historical_replay": True,
                "historical_replay_time_policy_version": (
                    HISTORICAL_REPLAY_TIME_POLICY_VERSION
                ),
            }
            if historical_replay
            else {"cutoff_at": cutoff_at}
        ),
    }
    if route_group == CHINA_ROUTE_GROUP:
        identity["tushare_macro_request_contract"] = {
            endpoint: _china_macro_request(endpoint, date.fromisoformat(as_of_date))
            for endpoint in _TUSHARE_MACRO_FIELDS
        }
        if official_document_types is not None:
            identity["official_document_types"] = list(official_document_types)
    return canonical_hash(identity)


def _source_receipt(
    group: Mapping[str, Any], route_id: str
) -> SourceCaptureReceipt:
    captured_at = str(group["captured_at"])
    route_group = str(group["route_group"])
    coverage_start = group.get("market_session_date", group["as_of_date"])
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
        macro_requests = group.get("tushare_macro_requests", {})
        dimensions = {
            "endpoint": sorted(_TUSHARE_MACRO_FIELDS),
            "request_params": [
                endpoint
                + ":"
                + "&".join(
                    f"{key}={macro_requests[endpoint][key]}"
                    for key in sorted(macro_requests[endpoint])
                )
                for endpoint in sorted(macro_requests)
            ],
        }
        provider = "tushare"
        query_keys = sorted(
            {
                key
                for request in macro_requests.values()
                for key in request
            }
        )
        page_count = len(_TUSHARE_MACRO_FIELDS)
        parser_version = COMPILER_VERSION
    elif route_id == COMMODITY_ROUTE_GROUP:
        counts = group["raw_row_counts"]
        row_count = sum(int(value) for value in counts.values())
        released_at = captured_at
        raw_hash = canonical_hash(group["condition_input"])
        requests = group["commodity_requests"]
        request_dimensions = {
            endpoint: sorted(
                {
                    endpoint
                    + ":"
                    + "&".join(f"{key}={request[key]}" for key in sorted(request))
                    for request in requests[endpoint]
                }
            )
            for endpoint in requests
        }
        dimensions = {
            "family_id": sorted(_REQUIRED_COMMODITY_FAMILIES),
            **request_dimensions,
        }
        provider = "tushare"
        query_keys = sorted(
            {
                key
                for request_set in requests.values()
                for request in request_set
                for key in request
            }
        )
        page_count = int(group["transport_call_count"])
        duplicate_count = int(group["raw_duplicate_counts"]["fut_wsr"])
        pagination_policy = "EXACT_REQUEST_SET_NO_PAGINATION"
        parser_version = COMPILER_VERSION
    elif route_id == INSTITUTIONAL_ROUTE_GROUP:
        row_count = (
            len(group["market_flow_rows"])
            + len(group["industry_rows"])
            + len(group["fund_share_rows"])
            + len(group["crowding_rows"])
        )
        released_at = (
            f"{group['market_session_date']}T15:00:00+08:00"
            if group.get("historical_replay") is True
            else captured_at
        )
        raw_hash = canonical_hash(
            {
                "market_flow_rows": group["market_flow_rows"],
                "industry_rows": group["industry_rows"],
                "fund_share_rows": group["fund_share_rows"],
                "crowding_rows": group["crowding_rows"],
                "institutional_requests": group["institutional_requests"],
            }
        )
        requests = group["institutional_requests"]
        request_strings = sorted(
            {
                endpoint
                + ":"
                + "&".join(f"{key}={request[key]}" for key in sorted(request))
                for endpoint, request_set in requests.items()
                for request in request_set
            }
        )
        dimensions = {
            "endpoint": sorted(requests),
            "request": request_strings,
            "industry": list(INSTITUTIONAL_INDUSTRY_UNIVERSE),
            "crowding": list(INSTITUTIONAL_CROWDING_UNIVERSE),
            "etf": list(INSTITUTIONAL_ETF_UNIVERSE),
        }
        provider = "tushare"
        query_keys = ["end_date", "start_date", "trade_date", "ts_code"]
        page_count = sum(len(request_set) for request_set in requests.values())
        duplicate_count = 0
        pagination_policy = "EXACT_REQUEST_SET_NO_PAGINATION"
        parser_version = COMPILER_VERSION
    elif route_id == CURVE_ROUTE_GROUP:
        row_count = 2 + len(group["government_curve_rows"])
        curve_source = group["government_curve_source"]
        released_at = curve_source["session_released_at"]
        raw_hash = canonical_hash(
            {
                "shibor": group["shibor"],
                "curve": group["government_curve_rows"],
                "curve_source": curve_source,
            }
        )
        dimensions = {
            "component": ["mof_chinabond_maturity_curve", "tushare_shibor"],
            "tenor": ["10y", "1y", "2y", "30y", "3m", "3y", "5y", "7y", "overnight"],
        }
        provider = "composite"
        query_keys = ["end_date", "start_date", "trade_date"]
        page_count = 1 + len(curve_source["request_windows"])
        coverage_start = group["curve_history_start"]
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
                        **(
                            {
                                "requested_market_session_date": group[
                                    "requested_market_session_date"
                                ]
                            }
                            if route_id == CURVE_ROUTE_GROUP
                            else {}
                        ),
                        **(
                            {"macro_request_contract": group["tushare_macro_requests"]}
                            if route_id == "tushare.cn_macro"
                            else {}
                        ),
                        **(
                            {
                                "official_document_types": sorted(
                                    str(row["document_type"])
                                    for row in group["official_documents"]
                                )
                            }
                            if route_id == "official.cn_macro"
                            else {}
                        ),
                        **(
                            {"commodity_requests": group["commodity_requests"]}
                            if route_id == COMMODITY_ROUTE_GROUP
                            else {}
                        ),
                        **(
                            {
                                "institutional_requests": group[
                                    "institutional_requests"
                                ]
                            }
                            if route_id == INSTITUTIONAL_ROUTE_GROUP
                            else {}
                        ),
                    }
                ),
                "capture_id": capture_id,
            },
            "transport": {
                "redacted_url": (
                    "https://official.cn/<allowlisted-catalog>/<document>"
                    if route_id == "official.cn_macro"
                    else (
                        "https://yield.chinabond.com.cn/<historyQuery>+"
                        "https://api.tushare.pro/<shibor>"
                        if route_id == CURVE_ROUTE_GROUP
                        else "https://api.tushare.pro/<registered-endpoint>"
                    )
                ),
                "method": "GET" if route_id == "official.cn_macro" else "POST",
                "query_keys": sorted(query_keys),
                "pagination_policy": pagination_policy,
                "page_count": page_count,
            },
            "authority": {
                "provider": provider,
                "permission_tier": (
                    "public"
                    if route_id == "official.cn_macro"
                    else (
                        "public/configured-runtime"
                        if route_id == CURVE_ROUTE_GROUP
                        else "configured-runtime"
                    )
                ),
                "api_version": (
                    "public-web-v1"
                    if route_id == "official.cn_macro"
                    else (
                        "mof-chinabond-history-v1/tushare-pro-v1"
                        if route_id == CURVE_ROUTE_GROUP
                        else "pro-v1"
                    )
                ),
                "parser_version": parser_version,
            },
            "time": {
                "released_at": released_at,
                "vintage_at": released_at,
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
                "requested_start": coverage_start,
                "requested_end": group["as_of_date"],
                "observed_start": coverage_start,
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


def china_archive_source_receipt(
    group: Mapping[str, Any], route_id: str
) -> SourceCaptureReceipt:
    """Rebuild and validate one logical receipt from a sealed China group."""

    if route_id not in group.get("route_ids", ()):
        raise ValueError(f"China archive group does not contain route {route_id}")
    return _source_receipt(group, route_id)


def _coverage_receipt(
    *,
    route_group: str,
    required_route_ids: tuple[str, ...],
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
        for route_id in required_route_ids
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
            "required_route_ids": list(required_route_ids),
            "route_results": route_results,
            "coverage_complete": complete,
            "blocker_codes": blockers,
        }
    )


def _failed_route(
    *,
    route_group: str,
    required_route_ids: tuple[str, ...],
    as_of_date: str,
    cutoff_at: str,
    ledger: AgentDataMaterializationLedger,
    status: str,
    blocker: str,
) -> ChinaRouteArchiveResult:
    coverage = _coverage_receipt(
        route_group=route_group,
        required_route_ids=required_route_ids,
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
    required_route_ids: tuple[str, ...],
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    historical_replay: bool,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    builder: Callable[[], dict[str, Any]],
) -> ChinaRouteArchiveResult:
    try:
        group, cache_hit = store.get_or_capture(capture_key, builder)
        _validate_replay_group(group, historical_replay=historical_replay)
        sources = _source_receipts(group)
        coverage = _coverage_receipt(
            route_group=route_group,
            required_route_ids=required_route_ids,
            as_of_date=as_of_date,
            cutoff_at=str(group["cutoff_at"]),
            source_receipts=sources,
            status="SUCCESS",
            blocker_codes=(),
        )
        ledger.append_capture_group(sources, coverage)
        return ChinaRouteArchiveResult(sources, coverage, cache_hit, group)
    except PermissionError:
        return _failed_route(
            route_group=route_group,
            required_route_ids=required_route_ids,
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
            required_route_ids=required_route_ids,
            as_of_date=as_of_date,
            cutoff_at=cutoff_at,
            ledger=ledger,
            status=status,
            blocker=blocker,
        )
    except (TimeoutError, ConnectionError):
        return _failed_route(
            route_group=route_group,
            required_route_ids=required_route_ids,
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
    requested_route_ids: Sequence[str] | None = None,
    official_document_types: Sequence[str] | None = None,
    historical_replay: bool = False,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    fetch_official: Callable[..., list[dict[str, Any]]] = _private_official_fetch,
    fetch_official_curve: Callable[..., dict[str, Any]] = (
        fetch_mof_chinabond_government_yield_curve
    ),
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
    if not isinstance(historical_replay, bool):
        raise ValueError("historical_replay must be a boolean")
    explicit_official_document_types = None
    if official_document_types is not None:
        if isinstance(official_document_types, (str, bytes)):
            raise ValueError("official_document_types must be a sequence")
        explicit_official_document_types = tuple(official_document_types)
        if (
            not explicit_official_document_types
            or explicit_official_document_types
            != tuple(sorted(set(explicit_official_document_types)))
            or not set(explicit_official_document_types)
            <= set(_REQUIRED_OFFICIAL_DOCUMENTS)
        ):
            raise ValueError(
                "official_document_types must be a sorted registered document subset"
            )
    normalized_cutoff = cutoff.isoformat()
    if requested_route_ids is None:
        required_routes = LOGICAL_ROUTES
    else:
        if isinstance(requested_route_ids, (str, bytes)):
            raise ValueError("requested_route_ids must be a sequence of route IDs")
        required_routes = tuple(requested_route_ids)
        if (
            not required_routes
            or required_routes != tuple(sorted(set(required_routes)))
            or not set(required_routes) <= set(LOGICAL_ROUTES)
        ):
            raise ValueError(
                "requested_route_ids must be a non-empty sorted unique China route subset"
            )
    required_set = frozenset(required_routes)
    selected_groups = tuple(
        route_group
        for route_group, route_ids in ROUTE_GROUPS.items()
        if required_set.intersection(route_ids)
    )
    group_routes = {
        route_group: tuple(
            route_id
            for route_id in ROUTE_GROUPS[route_group]
            if route_id in required_set
        )
        for route_group in selected_groups
    }
    now = _capture_now()
    if now.tzinfo is None:
        raise ChinaAgentDataSchemaError("trusted capture clock must include timezone")
    local_now_date = now.astimezone(_SHANGHAI).date()
    if historical_replay and local_now_date <= as_of:
        blocker = "CAPTURE_BEFORE_AS_OF_WINDOW"
    elif local_now_date < as_of:
        blocker = "CAPTURE_BEFORE_AS_OF_WINDOW"
    elif not historical_replay and now > cutoff:
        blocker = "CAPTURE_AFTER_AS_OF_CUTOFF"
    else:
        blocker = None
    if blocker:
        return ChinaAgentArchiveResult(
            {
                route_group: _failed_route(
                    route_group=route_group,
                    required_route_ids=group_routes[route_group],
                    as_of_date=as_of_date,
                    cutoff_at=normalized_cutoff,
                    ledger=ledger,
                    status="CAPTURE_REJECTED",
                    blocker=blocker,
                )
                for route_group in selected_groups
            }
        )
    keys = {
        route_group: _capture_key(
            route_group,
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            historical_replay=historical_replay,
            market_session_date=session.isoformat(),
            requested_route_ids=group_routes[route_group],
            official_document_types=(
                explicit_official_document_types
                if route_group == CHINA_ROUTE_GROUP
                else None
            ),
        )
        for route_group in selected_groups
    }
    builders: dict[str, Callable[[], dict[str, Any]]] = {
        CHINA_ROUTE_GROUP: lambda: _build_china_group(
            capture_key=keys[CHINA_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            historical_replay=historical_replay,
            requested_route_ids=group_routes[CHINA_ROUTE_GROUP],
            official_document_types=explicit_official_document_types,
            fetch_official=fetch_official,
            fetch_tushare=fetch_tushare,
        ),
        COMMODITY_ROUTE_GROUP: lambda: _build_commodity_group(
            capture_key=keys[COMMODITY_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            historical_replay=historical_replay,
            market_session_date=session.strftime("%Y%m%d"),
            fetch_tushare=fetch_tushare,
        ),
        INSTITUTIONAL_ROUTE_GROUP: lambda: _build_institutional_group(
            capture_key=keys[INSTITUTIONAL_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            historical_replay=historical_replay,
            market_session_date=session.strftime("%Y%m%d"),
            fetch_tushare=fetch_tushare,
        ),
        CURVE_ROUTE_GROUP: lambda: _build_curve_group(
            capture_key=keys[CURVE_ROUTE_GROUP],
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            historical_replay=historical_replay,
            market_session_date=session.strftime("%Y%m%d"),
            fetch_official_curve=fetch_official_curve,
            fetch_tushare=fetch_tushare,
        ),
    }
    builders = {
        route_group: builder
        for route_group, builder in builders.items()
        if route_group in selected_groups
    }
    return ChinaAgentArchiveResult(
        {
            route_group: _archive_route(
                route_group=route_group,
                required_route_ids=group_routes[route_group],
                capture_key=keys[route_group],
                as_of_date=as_of_date,
                cutoff_at=normalized_cutoff,
                historical_replay=historical_replay,
                store=store,
                ledger=ledger,
                builder=builders[route_group],
            )
            for route_group in selected_groups
        }
    )


def _load_ready_group(
    *,
    route_group: str,
    archive: ChinaAgentArchiveResult,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    expected_route_ids: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, SourceCaptureReceipt]]:
    result = archive.routes.get(route_group)
    if result is None:
        raise DataVendorUnavailable(f"required China route group is missing: {route_group}")
    if result.group is None:
        raise DataVendorUnavailable(f"required China route group is blocked: {route_group}")
    group = store.load_group(str(result.group["capture_key"]))
    expected_routes = set(
        ROUTE_GROUPS[route_group]
        if expected_route_ids is None
        else expected_route_ids
    )
    if (
        group.get("schema_version") != CAPTURE_SCHEMA_VERSION
        or group.get("route_group") != route_group
        or set(group.get("route_ids", ())) != expected_routes
    ):
        raise DataVendorUnavailable("China agent archive schema/route drift")
    receipts = {
        receipt.as_dict()["identity"]["route_id"]: receipt
        for receipt in _source_receipts(group)
    }
    for route_id, receipt in receipts.items():
        registered = ledger.source_capture_receipt(
            receipt_hash=receipt.receipt_hash
        )
        if registered is None:
            raise DataVendorUnavailable(f"China agent source receipt drift: {route_id}")
        if (
            registered.receipt_hash != receipt.receipt_hash
            or registered.as_dict() != receipt.as_dict()
        ):
            raise DataVendorUnavailable(f"China agent source receipt drift: {route_id}")
        payload = registered.as_dict()
        if (
            payload.get("identity", {}).get("route_id") != route_id
            or payload.get("pit", {}).get("eligible") is not True
            or payload.get("coverage", {}).get("requested_end")
            != group["as_of_date"]
            or payload.get("coverage", {}).get("observed_end")
            != group["as_of_date"]
        ):
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


def _official_china_context_observations(
    group: Mapping[str, Any], receipt: SourceCaptureReceipt
) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "series_id": _CHINA_SERIES_PROJECTION.get(
                str(row["series_id"]), str(row["series_id"])
            ),
        }
        for row in _official_observations(group, receipt)
        if row["source"] in _CHINA_OFFICIAL_BRANCHES
    ]


def _china_observations(
    group: Mapping[str, Any], receipts: Mapping[str, SourceCaptureReceipt]
) -> list[dict[str, Any]]:
    rows = _official_china_context_observations(
        group, receipts["official.cn_macro"]
    )
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
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        if group.get("historical_replay") is True:
            near_contract = next(
                contract
                for contract in family["contracts"]
                if contract["ts_code"] == term["near_contract"]
            )
            released_at = near_contract["price_released_at"]
            vintage_at = near_contract["price_vintage_at"]
        else:
            released_at = group["captured_at"]
            vintage_at = group["captured_at"]
        observations.append(
            {
                "series_id": prefixes[family_id],
                "period_start": group["market_session_date"],
                "period_end": group["market_session_date"],
                "released_at": released_at,
                "vintage_at": vintage_at,
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
    raw = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": "commodities",
        "as_of_date": group["as_of_date"],
        "observations": observations,
        "events": [],
        "commodity_conditions": group["condition_input"],
    }
    return raw, validate_role_snapshot(
        raw,
        "commodities",
        group["as_of_date"],
    )


def _institutional_snapshot(
    group: Mapping[str, Any], receipt: SourceCaptureReceipt
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = group["market_session_date"]
    availability = (
        f"{session}T15:00:00+08:00"
        if group.get("historical_replay") is True
        else group["captured_at"]
    )
    industry_amounts = [float(row["net_amount"]) for row in group["industry_rows"]]
    fund_shares = [float(row["fd_share"]) for row in group["fund_share_rows"]]
    turnovers = [float(row["turnover_rate"]) for row in group["crowding_rows"]]
    observations = [
        {
            "series_id": "market_flow_registered_universe_net_amount",
            "period_start": session,
            "period_end": session,
            "released_at": availability,
            "vintage_at": availability,
            "actual": sum(
                float(row["net_mf_amount"]) for row in group["market_flow_rows"]
            ),
            "previous": None,
            "expected": None,
            "unit": "10k_cny",
            "source": "tushare.moneyflow",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"{receipt.receipt_hash}:market-flow:{session}",
        },
        {
            "series_id": "sector_rotation_registered_universe_net_amount",
            "period_start": session,
            "period_end": session,
            "released_at": availability,
            "vintage_at": availability,
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
            "released_at": availability,
            "vintage_at": availability,
            "actual": sum(fund_shares),
            "previous": None,
            "expected": None,
            "unit": "10k_shares",
            "source": "tushare.fund_share",
            "pit_status": "AVAILABLE_AS_OF",
            "evidence_id": f"{receipt.receipt_hash}:etf-share:{session}",
        },
        {
            "series_id": "crowding_registered_universe_turnover_median",
            "period_start": session,
            "period_end": session,
            "released_at": availability,
            "vintage_at": availability,
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
            "eligible_count": len(INSTITUTIONAL_CROWDING_UNIVERSE),
            "observed_count": len(group["market_flow_rows"]),
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
    raw = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": "institutional_flow",
        "as_of_date": group["as_of_date"],
        "observations": observations,
        "events": [],
        "component_coverage": component_coverage,
    }
    return raw, validate_role_snapshot(
        raw,
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
    knowledge_cutoff: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
                "source": "official.mof_chinabond_government_2y",
                "unit": "percent",
            },
            {
                "series_id": "cn_curve_10y",
                "actual": curve_group["government_curve"]["10y"],
                "source": "official.mof_chinabond_government_10y",
                "unit": "percent",
            },
        ]
    )
    for index, row in enumerate(selected):
        if "period_start" not in row:
            availability = (
                curve_group["government_curve_source"]["session_released_at"]
                if str(row["series_id"]).startswith("cn_curve_")
                else curve_group["captured_at"]
            )
            row.update(
                {
                    "period_start": session,
                    "period_end": session,
                    "released_at": availability,
                    "vintage_at": availability,
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
    raw = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": "central_bank",
        "as_of_date": china_group["as_of_date"],
        "observations": selected,
        "context_observations": deterministic_context,
        "events": [],
    }
    return raw, validate_role_snapshot(
        raw,
        "central_bank",
        china_group["as_of_date"],
        knowledge_cutoff=knowledge_cutoff,
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


_CHINA_COMPILED_ROLES = (
    "china",
    "commodities",
    "institutional_flow",
    "central_bank",
)


def _normalise_requested_roles(
    requested_roles: Sequence[str] | None,
) -> tuple[str, ...] | None:
    if requested_roles is None:
        return None
    if isinstance(requested_roles, (str, bytes)):
        raise ValueError("requested_roles must be a sequence")
    roles = tuple(requested_roles)
    if (
        not roles
        or any(not isinstance(role, str) for role in roles)
        or len(roles) != len(set(roles))
        or any(role not in _CHINA_COMPILED_ROLES for role in roles)
    ):
        raise ValueError("requested_roles must be a non-empty unique China role subset")
    return roles


def _build_china_snapshot(
    group: Mapping[str, Any], receipts: Mapping[str, SourceCaptureReceipt]
) -> tuple[dict[str, Any], dict[str, Any]]:
    china_observations = _china_observations(group, receipts)
    if group.get("historical_replay") is True:
        cutoff = _timestamp(
            f"{group['as_of_date']}T15:00:00+08:00", "historical_replay_cutoff"
        )
        for row in china_observations:
            released = min(_timestamp(row["released_at"], "released_at"), cutoff)
            vintage = max(
                released,
                min(_timestamp(row["vintage_at"], "vintage_at"), cutoff),
            )
            row["released_at"] = released.isoformat()
            row["vintage_at"] = vintage.isoformat()
    china_raw = {
        "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
        "role": "china",
        "as_of_date": group["as_of_date"],
        "observations": china_observations,
        "events": [],
    }
    return china_raw, validate_role_snapshot(
        china_raw,
        "china",
        group["as_of_date"],
    )


def compile_china_agent_snapshot(
    *,
    archive: ChinaAgentArchiveResult,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    output_root: Path | None = None,
    exact_calendar_evidence_hash: str | None = None,
) -> ChinaAgentBuildResult:
    """Compile only the China snapshot from its three bound source routes."""
    china_group, china_receipts = _load_ready_group(
        route_group=CHINA_ROUTE_GROUP,
        archive=archive,
        store=store,
        ledger=ledger,
    )
    expected_routes = {"official.cn_macro", "tushare.cn_macro"}
    if (
        set(china_group.get("route_ids", ())) != expected_routes
        or set(china_receipts) != expected_routes
    ):
        raise DataVendorUnavailable(
            "China snapshot source receipts do not close the required routes"
        )
    china_raw, china_snapshot = _build_china_snapshot(china_group, china_receipts)
    as_of_date = str(china_group["as_of_date"])
    calendar_cny = exact_calendar_evidence_hash or _calendar_hash(
        ledger, as_of_date=as_of_date, route_id="tushare.eco_cal.cny"
    )
    receipt = _build_receipt(
        role="china",
        tool_id="get_china_macro_snapshot",
        as_of_date=as_of_date,
        cutoff_at=china_group["cutoff_at"],
        source_hashes=[
            china_receipts["official.cn_macro"].receipt_hash,
            china_receipts["tushare.cn_macro"].receipt_hash,
            calendar_cny,
        ],
        snapshot=china_snapshot,
    )
    _write_snapshot(output_root or china_agent_snapshot_root(), "china", as_of_date, china_raw)
    persisted = (ledger.append_or_reuse_snapshot_build(receipt),)
    return ChinaAgentBuildResult({"china": china_snapshot}, persisted)


def compile_china_agent_snapshots(
    *,
    archive: ChinaAgentArchiveResult,
    store: ChinaAgentDataArchiveStore,
    ledger: AgentDataMaterializationLedger,
    output_root: Path | None = None,
    requested_roles: Sequence[str] | None = None,
    exact_calendar_evidence_hash: str | None = None,
    exact_calendar_evidence_hashes: Sequence[str] | None = None,
) -> ChinaAgentBuildResult:
    selected_roles = _normalise_requested_roles(requested_roles)
    selected_role_set = set(_CHINA_COMPILED_ROLES if selected_roles is None else selected_roles)
    if selected_role_set == {"central_bank"}:
        china_group, china_receipts = _load_ready_group(
            route_group=CHINA_ROUTE_GROUP,
            archive=archive,
            store=store,
            ledger=ledger,
            expected_route_ids=("official.cn_macro",),
        )
        curve_group, curve_receipts = _load_ready_group(
            route_group=CURVE_ROUTE_GROUP,
            archive=archive,
            store=store,
            ledger=ledger,
        )
        china_context = _official_china_context_observations(
            china_group, china_receipts["official.cn_macro"]
        )
        knowledge_cutoff = None
        if china_group.get("historical_replay") is True:
            knowledge_cutoff = max(
                _timestamp(china_group["cutoff_at"], "cutoff_at"),
                _timestamp(curve_group["cutoff_at"], "cutoff_at"),
            )
        central_bank_raw, central_bank_snapshot = _central_bank_snapshot(
            china_group=china_group,
            china_receipts=china_receipts,
            curve_group=curve_group,
            curve_receipt=curve_receipts[CURVE_ROUTE_GROUP],
            china_context=china_context,
            knowledge_cutoff=knowledge_cutoff,
        )
        as_of_date = str(china_group["as_of_date"])
        calendar_cny = exact_calendar_evidence_hash or _calendar_hash(
            ledger, as_of_date=as_of_date, route_id="tushare.eco_cal.cny"
        )
        receipt = _build_receipt(
            role="central_bank",
            tool_id="get_central_bank_snapshot",
            as_of_date=as_of_date,
            cutoff_at=china_group["cutoff_at"],
            source_hashes=[
                china_receipts["official.cn_macro"].receipt_hash,
                curve_receipts[CURVE_ROUTE_GROUP].receipt_hash,
                calendar_cny,
            ],
            snapshot=central_bank_snapshot,
        )
        destination_root = output_root or china_agent_snapshot_root()
        _write_snapshot(destination_root, "central_bank", as_of_date, central_bank_raw)
        persisted = (ledger.append_or_reuse_snapshot_build(receipt),)
        return ChinaAgentBuildResult({"central_bank": central_bank_snapshot}, persisted)
    if selected_role_set == {"commodities"}:
        commodity_group, commodity_receipts = _load_ready_group(
            route_group=COMMODITY_ROUTE_GROUP,
            archive=archive,
            store=store,
            ledger=ledger,
        )
        if exact_calendar_evidence_hashes is None or isinstance(
            exact_calendar_evidence_hashes, (str, bytes)
        ):
            raise DataVendorUnavailable(
                "commodity compiler requires three exact calendar receipts"
            )
        calendar_hashes = tuple(exact_calendar_evidence_hashes)
        if (
            len(calendar_hashes) != 3
            or len(set(calendar_hashes)) != 3
            or any(not isinstance(value, str) or not value for value in calendar_hashes)
        ):
            raise DataVendorUnavailable(
                "commodity compiler requires three unique calendar receipts"
            )
        commodity_raw, commodity_snapshot = _commodity_snapshot(
            commodity_group,
            commodity_receipts[COMMODITY_ROUTE_GROUP],
        )
        as_of_date = str(commodity_group["as_of_date"])
        receipt = _build_receipt(
            role="commodities",
            tool_id="get_commodity_conditions_snapshot",
            as_of_date=as_of_date,
            cutoff_at=commodity_group["cutoff_at"],
            source_hashes=[
                commodity_receipts[COMMODITY_ROUTE_GROUP].receipt_hash,
                *calendar_hashes,
            ],
            snapshot=commodity_snapshot,
        )
        destination_root = output_root or china_agent_snapshot_root()
        _write_snapshot(destination_root, "commodities", as_of_date, commodity_raw)
        persisted = (ledger.append_or_reuse_snapshot_build(receipt),)
        return ChinaAgentBuildResult({"commodities": commodity_snapshot}, persisted)
    if selected_role_set == {"institutional_flow"}:
        institutional_group, institutional_receipts = _load_ready_group(
            route_group=INSTITUTIONAL_ROUTE_GROUP,
            archive=archive,
            store=store,
            ledger=ledger,
        )
        institutional_raw, institutional_snapshot = _institutional_snapshot(
            institutional_group,
            institutional_receipts[INSTITUTIONAL_ROUTE_GROUP],
        )
        as_of_date = str(institutional_group["as_of_date"])
        receipt = _build_receipt(
            role="institutional_flow",
            tool_id="get_market_positioning_snapshot",
            as_of_date=as_of_date,
            cutoff_at=institutional_group["cutoff_at"],
            source_hashes=[
                institutional_receipts[INSTITUTIONAL_ROUTE_GROUP].receipt_hash
            ],
            snapshot=institutional_snapshot,
        )
        destination_root = output_root or china_agent_snapshot_root()
        _write_snapshot(
            destination_root,
            "institutional_flow",
            as_of_date,
            institutional_raw,
        )
        persisted = (ledger.append_or_reuse_snapshot_build(receipt),)
        return ChinaAgentBuildResult(
            {"institutional_flow": institutional_snapshot}, persisted
        )
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
    china_raw, china_snapshot = _build_china_snapshot(china_group, china_receipts)
    china_observations = china_raw["observations"]
    commodity_raw, commodity_snapshot = _commodity_snapshot(
        commodity_group, commodity_receipts[COMMODITY_ROUTE_GROUP]
    )
    institutional_raw, institutional_snapshot = _institutional_snapshot(
        institutional_group,
        institutional_receipts[INSTITUTIONAL_ROUTE_GROUP],
    )
    raw_snapshots = {
        "china": china_raw,
        "commodities": commodity_raw,
        "institutional_flow": institutional_raw,
    }
    snapshots = {
        "china": china_snapshot,
        "commodities": commodity_snapshot,
        "institutional_flow": institutional_snapshot,
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
        central_bank_raw, central_bank_snapshot = _central_bank_snapshot(
            china_group=china_group,
            china_receipts=china_receipts,
            curve_group=curve_group,
            curve_receipt=curve_receipts[CURVE_ROUTE_GROUP],
            china_context=china_observations,
        )
        raw_snapshots["central_bank"] = central_bank_raw
        snapshots["central_bank"] = central_bank_snapshot
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
    selected_raw_snapshots = {
        role: raw for role, raw in raw_snapshots.items() if role in selected_role_set
    }
    selected_snapshots = {
        role: snapshot
        for role, snapshot in snapshots.items()
        if role in selected_role_set
    }
    selected_build_receipts = tuple(
        receipt
        for receipt in build_receipts
        if receipt.as_dict()["agent_id"] in selected_role_set
    )
    destination_root = output_root or china_agent_snapshot_root()
    for role, raw in selected_raw_snapshots.items():
        _write_snapshot(destination_root, role, as_of_date, raw)
    persisted = tuple(
        ledger.append_or_reuse_snapshot_build(receipt)
        for receipt in selected_build_receipts
    )
    return ChinaAgentBuildResult(selected_snapshots, persisted)


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
    "china_archive_source_receipt",
    "china_agent_snapshot_root",
    "compile_china_agent_snapshot",
    "compile_china_agent_snapshots",
]
