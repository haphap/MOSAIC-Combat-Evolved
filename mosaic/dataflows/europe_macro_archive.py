"""Trusted Europe macro capture using existing ECB, Eurostat, and Tushare adapters."""

from __future__ import annotations

import base64
import calendar
import hashlib
import json
import math
import os
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
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
from .exceptions import DataVendorUnavailable
from .macro_snapshots import (
    MACRO_SNAPSHOT_SCHEMA_VERSION,
    validate_role_snapshot,
)
from .macro_source_contracts import (
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_REAL_ECONOMY_SERIES_MAP,
)
from .official_macro_adapters import fetch_official_series
from .runtime_paths import agent_cache_root, isolated_agent_runtime_path
from .tushare import _query_pro
from .tushare_catalog import assert_endpoint_capture_preflight_allowed


CAPTURE_SCHEMA_VERSION = "europe_macro_capture_group_v2"
COMPILER_VERSION = "europe_macro_compiler_v2"
ARCHIVE_LOCK_TIMEOUT_SECONDS = 60 * 60
HISTORICAL_REPLAY_TIME_POLICY_VERSION = "europe_macro_historical_replay_time_v1"
LOGICAL_ROUTES = (
    "ecb.eu_real_economy",
    "ecb.euro_macro",
    "market.euro_fx",
)


def _requested_routes(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return LOGICAL_ROUTES
    requested = tuple(value)
    if (
        not requested
        or len(set(requested)) != len(requested)
        or any(route_id not in LOGICAL_ROUTES for route_id in requested)
    ):
        raise ValueError("requested Europe macro routes are invalid")
    return tuple(route_id for route_id in LOGICAL_ROUTES if route_id in requested)
ECB_SERIES_IDS = tuple(
    sorted(
        source
        for sources in EURO_AREA_FINANCIAL_SERIES_MAP.values()
        for source in sources
        if not source.startswith(("official.", "tushare."))
    )
)
REAL_ECONOMY_ECB_SERIES_IDS = tuple(sorted(EU_REAL_ECONOMY_SERIES_MAP))
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DECISION_CUTOFF = time(15, 0)
_SOURCE_SCHEMA_HASH = canonical_hash(
    {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "routes": list(LOGICAL_ROUTES),
        "financial_ecb_series_ids": list(ECB_SERIES_IDS),
        "real_economy_ecb_series_ids": list(REAL_ECONOMY_ECB_SERIES_IDS),
        "fx_instrument": "EURUSD.FXCM",
    }
)
_REAL_ECONOMY_ECB_OUTPUT = {
    series_id: (contract["output_id"], "provider_unit")
    for series_id, contract in EU_REAL_ECONOMY_SERIES_MAP.items()
}
_ECB_OUTPUT = {
    "BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A": (
        "euro_area_bank_credit_loans",
        "provider_unit",
    ),
    "EST.B.EU000A2X2A25.WT": ("ecb_estr", "percent"),
    "EXR.D.USD.EUR.SP00.A": ("eur_usd_ecb", "USD per EUR"),
    "FM.B.U2.EUR.4F.KR.DFR.LEV": ("ecb_dfr", "percent"),
    "FM.B.U2.EUR.4F.KR.MRR_FR.LEV": ("ecb_mrr", "percent"),
    "MIR.M.U2.B.A2A.A.R.A.2240.EUR.N": (
        "euro_area_bank_credit_mir",
        "percent",
    ),
    "RDF.D.D0.Z0Z.4F.EC.DFTLB.PR": (
        "eu_large_bank_simultaneous_default_probability",
        "probability",
    ),
    "RDF.D.D0.Z0Z.4F.EC.DFTSV.PR": (
        "eu_sovereign_simultaneous_default_probability",
        "probability",
    ),
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y": (
        "euro_area_curve_10y",
        "percent",
    ),
    "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y": (
        "euro_area_curve_2y",
        "percent",
    ),
}
if set(_ECB_OUTPUT) != set(ECB_SERIES_IDS):  # pragma: no cover - import invariant
    raise RuntimeError("Europe ECB output map drifts from the source contract")
if set(_REAL_ECONOMY_ECB_OUTPUT) != set(REAL_ECONOMY_ECB_SERIES_IDS):  # pragma: no cover
    raise RuntimeError("Europe real-economy output map drifts from the source contract")


class EuropeMacroSchemaError(DataVendorUnavailable):
    """A provider response cannot satisfy the frozen Europe macro contract."""


class EuropeMacroCaptureAfterCutoff(DataVendorUnavailable):
    """A live Europe route completed after the A-share decision cutoff."""


class EuropeMacroCaptureBeforeWindow(DataVendorUnavailable):
    """Europe materialization was requested before its as-of date."""


@dataclass(frozen=True)
class EuropeMacroArchiveResult:
    source_receipts: tuple[SourceCaptureReceipt, ...]
    coverage_receipt: RouteCoverageReceipt
    cache_hit: bool
    group: dict[str, Any] | None


@dataclass(frozen=True)
class EuropeMacroBuildResult:
    snapshots: dict[str, dict[str, Any]]
    build_receipts: tuple[SnapshotBuildReceipt, ...]


def europe_macro_archive_path() -> Path:
    isolated = isolated_agent_runtime_path("agent_data/europe_macro.sqlite3")
    if isolated is not None:
        return isolated
    explicit = os.getenv("MOSAIC_EUROPE_MACRO_ARCHIVE_DB")
    if explicit:
        return Path(explicit).expanduser()
    return agent_cache_root() / "agent_data" / "europe_macro.sqlite3"


def europe_macro_snapshot_root() -> Path:
    isolated = isolated_agent_runtime_path("agent_data/europe_macro_snapshots")
    if isolated is not None:
        return isolated
    explicit = os.getenv("MOSAIC_EUROPE_MACRO_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return agent_cache_root() / "agent_data" / "europe_macro_snapshots"


def _capture_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EuropeMacroSchemaError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise EuropeMacroSchemaError(f"{field} must include timezone")
    return parsed


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, allow_nan=False)
    )


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _is_transport_failure(exc: BaseException) -> bool:
    seen: set[int] = set()
    pending = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(
            current,
            (
                TimeoutError,
                ConnectionError,
                requests.Timeout,
                requests.ConnectionError,
            ),
        ):
            return True
        for nested in (current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _private_official_fetch(**kwargs: Any) -> dict[str, Any]:
    return fetch_official_series(**kwargs)


def _private_tushare_fetch(*, endpoint: str, **params: str) -> Any:
    assert_endpoint_capture_preflight_allowed(endpoint)
    return _query_pro(endpoint, **params)


class EuropeMacroArchiveStore:
    """Append-only compressed Europe macro capture groups."""

    def __init__(self, path: Path | None = None, *, create: bool = True) -> None:
        self.path = path or europe_macro_archive_path()
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
                CREATE TABLE IF NOT EXISTS europe_macro_capture_groups (
                    capture_key TEXT PRIMARY KEY,
                    group_hash TEXT NOT NULL UNIQUE,
                    as_of_date TEXT NOT NULL,
                    cutoff_at TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload_zlib BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS europe_macro_capture_as_of
                  ON europe_macro_capture_groups(as_of_date, captured_at);
                CREATE TRIGGER IF NOT EXISTS europe_macro_capture_groups_no_update
                  BEFORE UPDATE ON europe_macro_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS europe_macro_capture_groups_no_delete
                  BEFORE DELETE ON europe_macro_capture_groups
                  BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(zlib.decompress(row["payload_zlib"]).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Europe macro archive payload is unreadable") from exc
        if canonical_hash(payload) != row["group_hash"]:
            raise ValueError("Europe macro archive group hash mismatch")
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
                    "SELECT * FROM europe_macro_capture_groups WHERE capture_key = ?",
                    (capture_key,),
                ).fetchone()
                if existing is not None:
                    payload = self._decode(existing)
                    conn.execute("COMMIT")
                    return payload, True
                payload = builder()
                conn.execute(
                    "INSERT INTO europe_macro_capture_groups "
                    "(capture_key, group_hash, as_of_date, cutoff_at, captured_at, "
                    "payload_zlib) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        capture_key,
                        canonical_hash(payload),
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
                "SELECT * FROM europe_macro_capture_groups WHERE capture_key = ?",
                (capture_key,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(
                    f"no Europe macro capture group for {capture_key}"
                )
            return self._decode(row)

    def row_count(self) -> int:
        with self._connect(read_only=True) as conn:
            return int(
                conn.execute(
                    "SELECT count(*) FROM europe_macro_capture_groups"
                ).fetchone()[0]
            )


def _period_bounds(value: Any) -> tuple[date, date]:
    text = str(value or "").strip()
    try:
        if len(text) == 10:
            parsed = date.fromisoformat(text)
            return parsed, parsed
        if len(text) == 7 and text[4:6] == "-Q" and text[-1] in "1234":
            year = int(text[:4])
            quarter = int(text[-1])
            first_month = 1 + (quarter - 1) * 3
            last_month = first_month + 2
            return (
                date(year, first_month, 1),
                date(year, last_month, calendar.monthrange(year, last_month)[1]),
            )
        if len(text) == 7 and text[4] == "-":
            year, month = (int(item) for item in text.split("-"))
            return (
                date(year, month, 1),
                date(year, month, calendar.monthrange(year, month)[1]),
            )
        if len(text) == 4:
            year = int(text)
            return date(year, 1, 1), date(year, 12, 31)
    except (TypeError, ValueError) as exc:
        raise EuropeMacroSchemaError(f"unsupported observation period: {text!r}") from exc
    raise EuropeMacroSchemaError(f"unsupported observation period: {text!r}")


def _decode_raw(payload: Mapping[str, Any], expected_provider: str) -> bytes:
    try:
        raw = base64.b64decode(str(payload["raw_payload_b64"]), validate=True)
    except (KeyError, ValueError) as exc:
        raise EuropeMacroSchemaError(
            f"{expected_provider} capture is missing private raw payload"
        ) from exc
    if _sha256_bytes(raw) != payload.get("payload_hash"):
        raise EuropeMacroSchemaError(f"{expected_provider} payload hash mismatch")
    return raw


def _validate_result_common(
    payload: Mapping[str, Any],
    *,
    provider: str,
    series_key: str,
    cutoff: datetime,
    retrieval_cutoff: datetime | None = None,
    completed: datetime | None = None,
) -> dict[str, Any]:
    value = _json_copy(payload)
    if value.get("provider") != provider or value.get("series_key") != series_key:
        raise EuropeMacroSchemaError(f"{provider} series identity mismatch")
    rows = value.get("rows")
    if (
        not isinstance(rows, list)
        or not rows
        or value.get("row_count") != len(rows)
    ):
        raise EuropeMacroSchemaError(f"{provider} row-count contract mismatch")
    _decode_raw(value, provider)
    retrieved = _timestamp(value.get("retrieved_at"), f"{provider}.retrieved_at")
    if completed is not None and retrieved > completed:
        raise EuropeMacroSchemaError(f"{provider} retrieval exceeds capture time")
    if provider != "ECB" and retrieved > (retrieval_cutoff or cutoff):
        raise EuropeMacroSchemaError(f"{provider} retrieval exceeds cutoff")
    return value


def select_ecb_vintage_rows(
    rows: Sequence[Mapping[str, Any]], *, cutoff_at: str
) -> list[dict[str, Any]]:
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for raw in rows:
        row = _json_copy(raw)
        period = str(row.get("TIME_PERIOD") or "").strip()
        action = str(row.get("ACTION") or "").strip().casefold()
        if not period or action not in {"insert", "replace", "delete"}:
            raise EuropeMacroSchemaError("ECB history row identity/action mismatch")
        valid_from_text = str(row.get("VALID_FROM") or "").strip()
        valid_from = _timestamp(
            row.get("VALID_TO")
            if action == "delete" and not valid_from_text
            else valid_from_text,
            "ECB.VALID_TO" if action == "delete" and not valid_from_text else "ECB.VALID_FROM",
        )
        if valid_from > cutoff:
            continue
        previous = latest.get(period)
        if previous is None or valid_from > previous[0]:
            latest[period] = (valid_from, row)
        elif valid_from == previous[0] and row != previous[1]:
            raise EuropeMacroSchemaError(
                "ECB history has conflicting actions at one validity timestamp"
            )
    selected = [
        row
        for _, row in latest.values()
        if str(row.get("ACTION") or "").casefold() != "delete"
    ]
    for row in selected:
        value = row.get("OBS_VALUE")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EuropeMacroSchemaError("ECB selected observation is not numeric")
        if not math.isfinite(float(value)):
            raise EuropeMacroSchemaError("ECB selected observation is not finite")
    selected.sort(key=lambda row: str(row["TIME_PERIOD"]))
    return selected


def _validate_ecb_payload(
    payload: Mapping[str, Any],
    *,
    series_id: str,
    cutoff: datetime,
    observation_start: date,
    observation_end: date,
) -> dict[str, Any]:
    value = _validate_result_common(
        payload,
        provider="ECB",
        series_key=series_id,
        cutoff=cutoff,
    )
    if value.get("source") != f"ecb.{series_id}" or value.get("pit_status") != (
        "AUTHORITATIVE_VINTAGE_HISTORY"
    ):
        raise EuropeMacroSchemaError("ECB history provenance contract mismatch")
    selected = select_ecb_vintage_rows(value["rows"], cutoff_at=cutoff.isoformat())
    selected = [
        row
        for row in selected
        if observation_start <= _period_bounds(row["TIME_PERIOD"])[1] <= observation_end
    ]
    if not selected:
        raise EuropeMacroSchemaError(
            f"ECB history has no usable cutoff row for {series_id}"
        )
    value["selected_rows"] = selected
    return value


def _response_rows(payload: Any) -> list[dict[str, Any]]:
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict(orient="records")
    if not isinstance(payload, list):
        raise EuropeMacroSchemaError("Tushare fx_daily response must be row-oriented")
    if not all(isinstance(row, Mapping) for row in payload):
        raise EuropeMacroSchemaError("Tushare fx_daily row must be an object")
    return [_json_copy(row) for row in payload]


def _tushare_date(value: Any) -> date:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise EuropeMacroSchemaError("Tushare fx_daily trade_date is invalid") from exc


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise EuropeMacroSchemaError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EuropeMacroSchemaError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise EuropeMacroSchemaError(f"{field} must be finite")
    return number


def _validate_fx_payload(
    payload: Any,
    *,
    observation_start: date,
    observation_end: date,
) -> dict[str, Any]:
    rows = _response_rows(payload)
    usable = []
    for row in rows:
        observed = _tushare_date(row.get("trade_date"))
        if str(row.get("ts_code") or "") != "EURUSD.FXCM":
            raise EuropeMacroSchemaError("Tushare Europe FX instrument mismatch")
        bid = _finite_number(row.get("bid_close"), "fx_daily.bid_close")
        ask = _finite_number(row.get("ask_close"), "fx_daily.ask_close")
        if ask < bid:
            raise EuropeMacroSchemaError("Tushare Europe FX ask is below bid")
        if observation_start <= observed <= observation_end:
            usable.append({**row, "bid_close": bid, "ask_close": ask})
    if not usable:
        raise EuropeMacroSchemaError("Tushare EURUSD has no usable rows")
    usable.sort(key=lambda row: str(row["trade_date"]))
    return {
        "endpoint": "fx_daily",
        "params": {
            "ts_code": "EURUSD.FXCM",
            "start_date": observation_start.strftime("%Y%m%d"),
            "end_date": observation_end.strftime("%Y%m%d"),
        },
        "payload_hash": canonical_hash({"rows": usable}),
        "rows": usable,
    }


def _build_group(
    *,
    capture_key: str,
    as_of_date: str,
    cutoff_at: str,
    observation_start: str,
    requested_route_ids: tuple[str, ...],
    historical_replay: bool,
    fetch_official: Callable[..., dict[str, Any]],
    fetch_tushare: Callable[..., Any],
) -> dict[str, Any]:
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    started = _capture_now()
    if started.tzinfo is None:
        raise EuropeMacroSchemaError("trusted capture clock must include timezone")
    capture_date = started.astimezone(_SHANGHAI).date()
    as_of = date.fromisoformat(as_of_date)
    if capture_date < as_of or (historical_replay and capture_date <= as_of):
        raise EuropeMacroCaptureBeforeWindow(
            "Europe macro capture cannot start before the as-of date"
        )
    start_date = date.fromisoformat(observation_start)
    end_date = date.fromisoformat(as_of_date)
    selection_cutoff = started if historical_replay else cutoff
    requested = frozenset(requested_route_ids)
    financial_only_context = requested == {
        "ecb.euro_macro",
        "market.euro_fx",
    }
    financial_ecb = []
    if "ecb.euro_macro" in requested:
        for series_id in ECB_SERIES_IDS:
            financial_ecb.append(
                _validate_ecb_payload(
                    fetch_official(
                        provider="ECB",
                        series_key=series_id,
                        as_of=cutoff_at,
                        include_history=True,
                        include_raw_payload=True,
                        observation_start=observation_start,
                        observation_end=as_of_date,
                    ),
                    series_id=series_id,
                    cutoff=selection_cutoff,
                    observation_start=start_date,
                    observation_end=end_date,
                )
            )
    real_economy_ecb = []
    if "ecb.eu_real_economy" in requested or financial_only_context:
        for series_id in REAL_ECONOMY_ECB_SERIES_IDS:
            real_economy_ecb.append(
                _validate_ecb_payload(
                    fetch_official(
                        provider="ECB",
                        series_key=series_id,
                        as_of=cutoff_at,
                        include_history=True,
                        include_raw_payload=True,
                        observation_start=observation_start,
                        observation_end=as_of_date,
                    ),
                    series_id=series_id,
                    cutoff=selection_cutoff,
                    observation_start=start_date,
                    observation_end=end_date,
                )
            )

    historical_miss = started > cutoff
    capture_allowed = not historical_miss or historical_replay
    fx: dict[str, Any] | None = None
    if capture_allowed and "market.euro_fx" in requested:
        fx = _validate_fx_payload(
            fetch_tushare(
                endpoint="fx_daily",
                ts_code="EURUSD.FXCM",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            ),
            observation_start=start_date,
            observation_end=end_date,
        )
    completed = _capture_now()
    if completed.tzinfo is None:
        raise EuropeMacroSchemaError("trusted capture clock must include timezone")
    live_requested = requested.difference(
        {"ecb.eu_real_economy", "ecb.euro_macro"}
    )
    if (
        live_requested
        and not historical_replay
        and not historical_miss
        and completed > cutoff
    ):
        raise EuropeMacroCaptureAfterCutoff(
            "live Europe macro capture completed after cutoff"
        )
    for payload in financial_ecb + real_economy_ecb:
        if _timestamp(payload["retrieved_at"], "retrieved_at") > completed:
            raise EuropeMacroSchemaError("official retrieval exceeds capture time")
    route_states = {
        route_id: (
            "SUCCESS"
            if route_id in {"ecb.eu_real_economy", "ecb.euro_macro"}
            or capture_allowed
            else "CAPTURE_REJECTED"
        )
        for route_id in requested_route_ids
    }
    group = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "capture_key": capture_key,
        "as_of_date": as_of_date,
        "cutoff_at": completed.isoformat() if historical_replay else cutoff_at,
        "captured_at": completed.isoformat(),
        "observation_start": observation_start,
        "observation_end": as_of_date,
        "ecb": {"series": financial_ecb, "series_ids": list(ECB_SERIES_IDS)},
        "ecb_real_economy": {
            "series": real_economy_ecb,
            "series_ids": list(REAL_ECONOMY_ECB_SERIES_IDS),
        },
        "market_fx": fx,
        "route_states": route_states,
    }
    if historical_replay:
        group.update(
            {
                "historical_replay": True,
                "historical_replay_time_policy_version": (
                    HISTORICAL_REPLAY_TIME_POLICY_VERSION
                ),
                "requested_cutoff_at": cutoff_at,
            }
        )
    if requested_route_ids != LOGICAL_ROUTES:
        group["requested_route_ids"] = list(requested_route_ids)
    return group


def _capture_id(capture_key: str, route_id: str) -> str:
    return f"europe-macro:{capture_key.removeprefix('sha256:')}:{route_id}"


def _receipt_common(group: Mapping[str, Any], route_id: str) -> dict[str, Any]:
    return {
        "schema_version": "source_capture_receipt_v1",
        "identity": {
            "source_family": {
                "ecb.eu_real_economy": "ecb",
                "ecb.euro_macro": "ecb",
                "market.euro_fx": "market",
            }[route_id],
            "route_id": route_id,
            "request_hash": canonical_hash(
                {
                    "route_id": route_id,
                    "as_of_date": group["as_of_date"],
                    "cutoff_at": group["cutoff_at"],
                    "requested_cutoff_at": group.get("requested_cutoff_at"),
                    "historical_replay_time_policy_version": group.get(
                        "historical_replay_time_policy_version"
                    ),
                    "observation_start": group["observation_start"],
                    "observation_end": group["observation_end"],
                    "financial_ecb_series_ids": group["ecb"]["series_ids"],
                    "real_economy_ecb_series_ids": group["ecb_real_economy"][
                        "series_ids"
                    ],
                    "fx_instrument": "EURUSD.FXCM",
                }
            ),
            "capture_id": _capture_id(str(group["capture_key"]), route_id),
        },
        "pit": {
            "as_of_cutoff": group["cutoff_at"],
            "eligible": True,
            "blocker_codes": [],
        },
        "provenance": {
            "parent_capture_hash": None,
            "previous_revision_hash": None,
            "revision_reason": None,
        },
    }


def _receipt_coverage(
    *,
    group: Mapping[str, Any],
    periods: Sequence[str],
    dimensions: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    bounds = [_period_bounds(period) for period in periods]
    return {
        "requested_start": group["observation_start"],
        "requested_end": group["observation_end"],
        "observed_start": min(start for start, _ in bounds).isoformat(),
        "observed_end": max(end for _, end in bounds).isoformat(),
        "dimensions": {
            key: sorted(set(str(item) for item in values))
            for key, values in sorted(dimensions.items())
        },
    }


def _ecb_receipt(
    group: Mapping[str, Any], *, route_id: str, group_key: str
) -> SourceCaptureReceipt:
    payload = _receipt_common(group, route_id)
    series = list(group[group_key]["series"])
    context_in_financial_route = (
        route_id == "ecb.euro_macro"
        and set(group.get("requested_route_ids", LOGICAL_ROUTES))
        == {"ecb.euro_macro", "market.euro_fx"}
    )
    if context_in_financial_route:
        series.extend(group["ecb_real_economy"]["series"])
    selected = [row for item in series for row in item["selected_rows"]]
    series_ids = list(group[group_key]["series_ids"])
    if context_in_financial_route:
        series_ids.extend(group["ecb_real_economy"]["series_ids"])
    knowledge_at = max(
        _timestamp(row["VALID_FROM"], "ECB.VALID_FROM") for row in selected
    ).isoformat()
    payload.update(
        {
            "transport": {
                "redacted_url": "https://data-api.ecb.europa.eu/service/data/<flow>/<key>",
                "method": "GET",
                "query_keys": [
                    "detail",
                    "endPeriod",
                    "format",
                    "includeHistory",
                    "startPeriod",
                ],
                "pagination_policy": "ONE_BOUNDED_QUERY_PER_REGISTERED_SERIES",
                "page_count": len(series),
            },
            "authority": {
                "provider": "ECB",
                "permission_tier": "public",
                "api_version": "data-api-v1",
                "parser_version": "official_macro_adapters_v1-history",
            },
            "time": {
                "released_at": knowledge_at,
                "vintage_at": knowledge_at,
                "captured_at": group["captured_at"],
                "knowledge_available_at": knowledge_at,
            },
            "content": {
                "raw_content_hash": canonical_hash(
                    {item["series_key"]: item["payload_hash"] for item in series}
                ),
                "normalized_row_count": len(selected),
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": _receipt_coverage(
                group=group,
                periods=[str(row["TIME_PERIOD"]) for row in selected],
                dimensions={"series_id": series_ids},
            ),
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
        }
    )
    payload["pit"].update(
        {
            "pit_mode": "AUTHORITATIVE_VINTAGE_REPLAY",
            "vintage_query": {
                "includeHistory": "true",
                "startPeriod": group["observation_start"],
                "endPeriod": group["observation_end"],
                "version_selector": "max(VALID_FROM)<=as_of_cutoff;Delete=tombstone",
            },
        }
    )
    return SourceCaptureReceipt.seal(payload)


def _market_receipt(group: Mapping[str, Any]) -> SourceCaptureReceipt:
    route_id = "market.euro_fx"
    payload = _receipt_common(group, route_id)
    fx = group["market_fx"]
    periods = [
        _tushare_date(row["trade_date"]).isoformat() for row in fx["rows"]
    ]
    payload.update(
        {
            "transport": {
                "redacted_url": "https://api.tushare.pro/fx_daily",
                "method": "POST",
                "query_keys": ["end_date", "start_date", "ts_code"],
                "pagination_policy": "SINGLE_BOUNDED_QUERY",
                "page_count": 1,
            },
            "authority": {
                "provider": "tushare",
                "permission_tier": "configured-runtime",
                "api_version": "pro-v1",
                "parser_version": "europe_macro_compiler_v1",
            },
            "time": {
                "released_at": group["captured_at"],
                "vintage_at": group["captured_at"],
                "captured_at": group["captured_at"],
                "knowledge_available_at": group["captured_at"],
            },
            "content": {
                "raw_content_hash": fx["payload_hash"],
                "normalized_row_count": len(fx["rows"]),
                "schema_hash": _SOURCE_SCHEMA_HASH,
            },
            "coverage": _receipt_coverage(
                group=group,
                periods=periods,
                dimensions={"instrument_id": ["EURUSD.FXCM"]},
            ),
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
        }
    )
    payload["pit"].update({"pit_mode": "OBSERVED_LIVE", "vintage_query": None})
    return SourceCaptureReceipt.seal(payload)


def _source_receipts(group: Mapping[str, Any]) -> tuple[SourceCaptureReceipt, ...]:
    requested = tuple(group.get("requested_route_ids", LOGICAL_ROUTES))
    receipt_builders: dict[str, Callable[[], SourceCaptureReceipt]] = {
        "ecb.eu_real_economy": lambda: _ecb_receipt(
            group,
            route_id="ecb.eu_real_economy",
            group_key="ecb_real_economy",
        ),
        "ecb.euro_macro": lambda: _ecb_receipt(
            group, route_id="ecb.euro_macro", group_key="ecb"
        ),
        "market.euro_fx": lambda: _market_receipt(group),
    }
    receipts = [
        receipt_builders[route_id]()
        for route_id in requested
        if group["route_states"][route_id] == "SUCCESS"
    ]
    return tuple(
        sorted(receipts, key=lambda item: item.as_dict()["identity"]["route_id"])
    )


def _coverage_receipt(
    *,
    as_of_date: str,
    cutoff_at: str,
    source_receipts: tuple[SourceCaptureReceipt, ...],
    route_states: Mapping[str, str],
    required_route_ids: tuple[str, ...],
    blocker_codes: tuple[str, ...],
) -> RouteCoverageReceipt:
    hashes = {
        receipt.as_dict()["identity"]["route_id"]: receipt.receipt_hash
        for receipt in source_receipts
    }
    route_results = [
        {
            "route_id": route_id,
            "capture_receipt_hash": hashes.get(route_id),
            "status": route_states[route_id],
        }
        for route_id in required_route_ids
    ]
    complete = all(row["status"] in {"SUCCESS", "TRUE_EMPTY"} for row in route_results)
    coverage_id = "europe-macro-coverage:" + canonical_hash(
        {
            "as_of_date": as_of_date,
            "cutoff_at": cutoff_at,
            "route_results": route_results,
            "blocker_codes": list(blocker_codes),
        }
    ).removeprefix("sha256:")
    return RouteCoverageReceipt.seal(
        {
            "schema_version": "route_coverage_receipt_v1",
            "coverage_id": coverage_id,
            "window": {
                "start": f"{as_of_date}T00:00:00+08:00",
                "end": cutoff_at,
                "timezone": "Asia/Shanghai",
            },
            "required_route_ids": list(required_route_ids),
            "route_results": route_results,
            "coverage_complete": complete,
            "blocker_codes": list(blocker_codes),
        }
    )


def _failed_result(
    *,
    as_of_date: str,
    cutoff_at: str,
    ledger: AgentDataMaterializationLedger,
    status: str,
    blocker: str,
    required_route_ids: tuple[str, ...],
) -> EuropeMacroArchiveResult:
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        cutoff_at=cutoff_at,
        source_receipts=(),
        route_states={route_id: status for route_id in required_route_ids},
        required_route_ids=required_route_ids,
        blocker_codes=(blocker,),
    )
    ledger.append_route_coverage(coverage)
    return EuropeMacroArchiveResult((), coverage, False, None)


def archive_europe_macro_sources(
    *,
    as_of_date: str,
    cutoff_at: str,
    observation_start: str,
    requested_route_ids: Sequence[str] | None = None,
    historical_replay: bool = False,
    store: EuropeMacroArchiveStore,
    ledger: AgentDataMaterializationLedger,
    fetch_official: Callable[..., dict[str, Any]] = _private_official_fetch,
    fetch_tushare: Callable[..., Any] = _private_tushare_fetch,
) -> EuropeMacroArchiveResult:
    as_of = date.fromisoformat(as_of_date)
    start = date.fromisoformat(observation_start)
    cutoff = _timestamp(cutoff_at, "cutoff_at")
    cutoff_local = cutoff.astimezone(_SHANGHAI)
    if start > as_of:
        raise ValueError("observation_start cannot exceed as_of_date")
    if cutoff_local.date() != as_of or cutoff_local.time() != _DECISION_CUTOFF:
        raise ValueError("Europe macro cutoff must be 15:00 Asia/Shanghai on as-of")
    if not isinstance(historical_replay, bool):
        raise ValueError("historical_replay must be a boolean")
    normalized_cutoff = cutoff.isoformat()
    required_routes = _requested_routes(requested_route_ids)
    capture_identity = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "cutoff_at": normalized_cutoff,
        "observation_start": observation_start,
        "observation_end": as_of_date,
        "financial_ecb_series_ids": list(ECB_SERIES_IDS),
        "real_economy_ecb_series_ids": list(REAL_ECONOMY_ECB_SERIES_IDS),
        "fx_instrument": "EURUSD.FXCM",
        **(
            {
                "historical_replay": True,
                "historical_replay_time_policy_version": (
                    HISTORICAL_REPLAY_TIME_POLICY_VERSION
                ),
            }
            if historical_replay
            else {}
        ),
    }
    if required_routes != LOGICAL_ROUTES:
        capture_identity["requested_route_ids"] = list(required_routes)
    capture_key = canonical_hash(capture_identity)
    try:
        group, cache_hit = store.get_or_capture(
            capture_key,
            lambda: _build_group(
                capture_key=capture_key,
                as_of_date=as_of_date,
                cutoff_at=normalized_cutoff,
                observation_start=observation_start,
                requested_route_ids=required_routes,
                historical_replay=historical_replay,
                fetch_official=fetch_official,
                fetch_tushare=fetch_tushare,
            ),
        )
        sources = _source_receipts(group)
        blockers = (
            ("CAPTURE_AFTER_AS_OF_CUTOFF",)
            if group["route_states"].get("market.euro_fx")
            not in {None, "SUCCESS"}
            else ()
        )
        coverage = _coverage_receipt(
            as_of_date=as_of_date,
            cutoff_at=str(group["cutoff_at"]),
            source_receipts=sources,
            route_states=group["route_states"],
            required_route_ids=required_routes,
            blocker_codes=blockers,
        )
        ledger.append_capture_group(sources, coverage)
        return EuropeMacroArchiveResult(sources, coverage, cache_hit, group)
    except PermissionError:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="PERMISSION_DENIED",
            blocker="PERMISSION_DENIED",
            required_route_ids=required_routes,
        )
    except (TimeoutError, ConnectionError):
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="TRANSPORT_FAILED",
            blocker="TRANSPORT_FAILED",
            required_route_ids=required_routes,
        )
    except EuropeMacroCaptureAfterCutoff:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="CAPTURE_AFTER_AS_OF_CUTOFF",
            required_route_ids=required_routes,
        )
    except EuropeMacroCaptureBeforeWindow:
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="CAPTURE_REJECTED",
            blocker="CAPTURE_BEFORE_AS_OF_WINDOW",
            required_route_ids=required_routes,
        )
    except DataVendorUnavailable as exc:
        if _is_transport_failure(exc):
            return _failed_result(
                as_of_date=as_of_date,
                cutoff_at=normalized_cutoff,
                ledger=ledger,
                status="TRANSPORT_FAILED",
                blocker="TRANSPORT_FAILED",
                required_route_ids=required_routes,
            )
        return _failed_result(
            as_of_date=as_of_date,
            cutoff_at=normalized_cutoff,
            ledger=ledger,
            status="SCHEMA_DRIFT",
            blocker="SCHEMA_DRIFT",
            required_route_ids=required_routes,
        )


def _latest_row(
    rows: Sequence[Mapping[str, Any]], *, period_field: str, as_of: date
) -> tuple[dict[str, Any], date, date]:
    candidates = []
    for raw in rows:
        row = _json_copy(raw)
        start, end = _period_bounds(row.get(period_field))
        if end <= as_of:
            candidates.append((end, start, row))
    if not candidates:
        raise DataVendorUnavailable("frozen Europe source has no row on or before as-of")
    end, start, row = max(candidates, key=lambda item: item[0])
    return row, start, end


def _ecb_observations(
    group: Mapping[str, Any],
    receipt: SourceCaptureReceipt,
    *,
    group_key: str,
    output_map: Mapping[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    observations = []
    as_of = date.fromisoformat(str(group["as_of_date"]))
    for item in group[group_key]["series"]:
        row, start, end = _latest_row(
            item["selected_rows"], period_field="TIME_PERIOD", as_of=as_of
        )
        series_id = str(item["series_key"])
        output_id, default_unit = output_map[series_id]
        observations.append(
            {
                "series_id": output_id,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "released_at": row["VALID_FROM"],
                "vintage_at": row["VALID_FROM"],
                "actual": float(row["OBS_VALUE"]),
                "previous": None,
                "expected": None,
                "unit": str(row.get("UNIT") or default_unit),
                "source": f"ecb.{series_id}",
                "pit_status": "AVAILABLE_AS_OF",
                "evidence_id": (
                    f"{receipt.receipt_hash}:{series_id}:{row['TIME_PERIOD']}:"
                    f"{str(item['payload_hash']).removeprefix('sha256:')}"
                ),
            }
        )
    return sorted(observations, key=lambda row: row["series_id"])


def _fx_observation(
    group: Mapping[str, Any], receipt: SourceCaptureReceipt
) -> dict[str, Any]:
    as_of = date.fromisoformat(str(group["as_of_date"]))
    candidates = [
        row
        for row in group["market_fx"]["rows"]
        if _tushare_date(row["trade_date"]) <= as_of
    ]
    if not candidates:
        raise DataVendorUnavailable("no frozen EURUSD market row on or before as-of")
    row = max(candidates, key=lambda item: str(item["trade_date"]))
    observed = _tushare_date(row["trade_date"])
    midpoint = (float(row["bid_close"]) + float(row["ask_close"])) / 2
    availability = (
        group["requested_cutoff_at"]
        if group.get("historical_replay") is True
        else group["captured_at"]
    )
    return {
        "series_id": "eur_usd_market",
        "period_start": observed.isoformat(),
        "period_end": observed.isoformat(),
        "released_at": availability,
        "vintage_at": availability,
        "actual": midpoint,
        "previous": None,
        "expected": None,
        "unit": "USD per EUR",
        "source": "tushare.fx_daily.EUR_USD",
        "pit_status": "AVAILABLE_AS_OF",
        "evidence_id": (
            f"{receipt.receipt_hash}:EURUSD:{observed.isoformat()}:"
            f"{str(group['market_fx']['payload_hash']).removeprefix('sha256:')}"
        ),
    }


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
    ledger: AgentDataMaterializationLedger,
    *,
    as_of_date: str,
    lookup_as_of_date: str | None = None,
) -> str:
    route_id = "tushare.eco_cal.eur"
    status = ledger.source_status(
        as_of=lookup_as_of_date or as_of_date, route_id=route_id
    )
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
                f"existing Europe macro snapshot is unreadable: {destination}"
            ) from exc
        if existing != dict(snapshot):
            raise DataVendorUnavailable(
                f"refusing to replace a different Europe macro snapshot: {destination}"
            )
        return
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, destination)


def compile_europe_macro_snapshots(
    *,
    capture_key: str,
    store: EuropeMacroArchiveStore,
    ledger: AgentDataMaterializationLedger,
    output_root: Path | None = None,
    requested_roles: Sequence[str] | None = None,
    exact_calendar_evidence_hash: str | None = None,
) -> EuropeMacroBuildResult:
    group = store.load_group(capture_key)
    if group.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise DataVendorUnavailable("Europe macro archive schema drift")
    if requested_roles is None:
        selected_roles = ("eu_economy", "euro_area_financial_conditions")
    else:
        if isinstance(requested_roles, (str, bytes)):
            raise ValueError("requested_roles must be a sequence")
        requested = tuple(requested_roles)
        if (
            not requested
            or len(requested) != len(set(requested))
            or any(
                role not in {"eu_economy", "euro_area_financial_conditions"}
                for role in requested
            )
        ):
            raise ValueError("requested_roles must be a non-empty Europe macro role subset")
        selected_roles = tuple(
            role
            for role in ("eu_economy", "euro_area_financial_conditions")
            if role in requested
        )
    selected_role_set = set(selected_roles)
    requested_archive_routes = tuple(
        group.get("requested_route_ids", LOGICAL_ROUTES)
    )
    required_archive_routes = (
        ("ecb.eu_real_economy", "ecb.euro_macro")
        if selected_role_set == {"eu_economy"}
        else ("ecb.euro_macro", "market.euro_fx")
        if selected_role_set == {"euro_area_financial_conditions"}
        else LOGICAL_ROUTES
    )
    if requested_archive_routes != required_archive_routes:
        raise DataVendorUnavailable(
            "Europe macro capture route scope does not match roles"
        )
    if any(
        group["route_states"].get(route) != "SUCCESS"
        for route in required_archive_routes
    ):
        raise DataVendorUnavailable(
            "Europe macro capture does not cover every required route"
        )
    sources = _source_receipts(group)
    source_by_route = {
        receipt.as_dict()["identity"]["route_id"]: receipt for receipt in sources
    }
    if set(source_by_route) != set(required_archive_routes):
        raise DataVendorUnavailable("Europe macro source route closure mismatch")
    for route_id, receipt in source_by_route.items():
        registered = ledger.source_capture_receipt(receipt_hash=receipt.receipt_hash)
        if (
            registered is None
            or registered.receipt_hash != receipt.receipt_hash
            or registered.as_dict() != receipt.as_dict()
        ):
            raise DataVendorUnavailable(f"Europe macro source receipt drift: {route_id}")
        payload = registered.as_dict()
        if (
            payload.get("identity", {}).get("route_id") != route_id
            or payload.get("pit", {}).get("eligible") is not True
            or payload.get("pit", {}).get("as_of_cutoff") != group["cutoff_at"]
            or payload.get("coverage", {}).get("requested_end")
            != group["as_of_date"]
        ):
            raise DataVendorUnavailable(f"Europe macro source receipt drift: {route_id}")
    context_receipt = (
        source_by_route["ecb.eu_real_economy"]
        if "ecb.eu_real_economy" in source_by_route
        else source_by_route["ecb.euro_macro"]
    )
    economy_observations = _ecb_observations(
        group,
        context_receipt,
        group_key="ecb_real_economy",
        output_map=_REAL_ECONOMY_ECB_OUTPUT,
    )
    raw_snapshots: dict[str, dict[str, Any]] = {}
    if "eu_economy" in selected_role_set:
        raw_snapshots["eu_economy"] = {
            "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
            "role": "eu_economy",
            "as_of_date": group["as_of_date"],
            "observations": economy_observations,
            "events": [],
        }
    if "euro_area_financial_conditions" in selected_role_set:
        financial_observations = _ecb_observations(
            group,
            source_by_route["ecb.euro_macro"],
            group_key="ecb",
            output_map=_ECB_OUTPUT,
        )
        financial_observations.append(
            _fx_observation(group, source_by_route["market.euro_fx"])
        )
        raw_snapshots["euro_area_financial_conditions"] = {
            "schema_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
            "role": "euro_area_financial_conditions",
            "as_of_date": group["as_of_date"],
            "observations": financial_observations,
            "context_observations": economy_observations,
            "events": [],
        }
    knowledge_cutoff = (
        _timestamp(group["cutoff_at"], "cutoff_at")
        if group.get("historical_replay") is True
        else None
    )
    snapshots = {
        role: validate_role_snapshot(
            raw,
            role,
            group["as_of_date"],
            knowledge_cutoff=knowledge_cutoff,
        )
        for role, raw in raw_snapshots.items()
    }
    if selected_role_set == {"eu_economy"} and exact_calendar_evidence_hash is None:
        raise DataVendorUnavailable("EU economy requires exact calendar evidence")
    calendar_hash = (
        str(exact_calendar_evidence_hash)
        if exact_calendar_evidence_hash is not None
        else _calendar_hash(
            ledger,
            as_of_date=group["as_of_date"],
            lookup_as_of_date=(
                _timestamp(group["captured_at"], "captured_at").date().isoformat()
                if group.get("historical_replay") is True
                else None
            ),
        )
    )
    build_specs: list[tuple[str, str, list[str]]] = []
    if "eu_economy" in selected_role_set:
        build_specs.append(
            (
                "eu_economy",
                "get_eu_macro_snapshot",
                [
                    source_by_route["ecb.eu_real_economy"].receipt_hash,
                    source_by_route["ecb.euro_macro"].receipt_hash,
                    calendar_hash,
                ],
            )
        )
    if "euro_area_financial_conditions" in selected_role_set:
        build_specs.append(
            (
                "euro_area_financial_conditions",
                "get_euro_area_financial_conditions_snapshot",
                [
                    source_by_route["ecb.euro_macro"].receipt_hash,
                    source_by_route["market.euro_fx"].receipt_hash,
                    calendar_hash,
                ],
            )
        )
    now = _capture_now().isoformat()
    build_receipts = []
    for role, tool_id, source_hashes in build_specs:
        required_routes = _required_routes(role, tool_id)
        build_id = "europe-macro-build:" + canonical_hash(
            {
                "role": role,
                "as_of_date": group["as_of_date"],
                "source_receipt_hashes": sorted(source_hashes),
                "snapshot_hash": snapshots[role]["snapshot_hash"],
            }
        ).removeprefix("sha256:")
        build_receipts.append(
            SnapshotBuildReceipt.seal(
                {
                    "schema_version": "snapshot_build_receipt_v1",
                    "build_id": build_id,
                    "agent_id": role,
                    "stage": role,
                    "tool_id": tool_id,
                    "as_of": group["as_of_date"],
                    "as_of_cutoff": group["cutoff_at"],
                    "source_receipt_hashes": sorted(set(source_hashes)),
                    "compiler_version": COMPILER_VERSION,
                    "output_contract_version": MACRO_SNAPSHOT_SCHEMA_VERSION,
                    "output_path": (
                        f"europe_macro_snapshots/{group['as_of_date']}/{role}.json"
                    ),
                    "output_hash": snapshots[role]["snapshot_hash"],
                    "pit_mode": "MIXED_AUTHORITY",
                    "earliest_trustworthy_date": group["as_of_date"],
                    "required_route_ids": required_routes,
                    "missing_route_ids": [],
                    "terminal_state": "READY",
                    "blocker_codes": [],
                    "build_started_at": now,
                    "build_finished_at": now,
                }
            )
        )
    destination_root = output_root or europe_macro_snapshot_root()
    for role, raw in raw_snapshots.items():
        _write_snapshot(destination_root, role, group["as_of_date"], raw)
    persisted_receipts = tuple(
        ledger.append_or_reuse_snapshot_build(receipt) for receipt in build_receipts
    )
    return EuropeMacroBuildResult(snapshots, persisted_receipts)


__all__ = [
    "ARCHIVE_LOCK_TIMEOUT_SECONDS",
    "CAPTURE_SCHEMA_VERSION",
    "COMPILER_VERSION",
    "ECB_SERIES_IDS",
    "REAL_ECONOMY_ECB_SERIES_IDS",
    "EuropeMacroArchiveResult",
    "EuropeMacroArchiveStore",
    "EuropeMacroBuildResult",
    "LOGICAL_ROUTES",
    "archive_europe_macro_sources",
    "compile_europe_macro_snapshots",
    "europe_macro_archive_path",
    "europe_macro_snapshot_root",
    "select_ecb_vintage_rows",
]
