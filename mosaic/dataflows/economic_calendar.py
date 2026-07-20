"""Append-only, local-capture pipeline for the Tushare ``eco_cal`` endpoint.

Raw rows are private runtime data.  The public repository contains only this
normalizer, its schema contract, and permission/schema preflight metadata.
Models never call ``eco_cal`` directly; consumers read role projections built
from this immutable cache.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from mosaic.dataflows.cross_runtime_json import canonical_hash, canonical_json
from mosaic.dataflows.tushare_catalog import assert_endpoint_runtime_enabled

ECO_CAL_SCHEMA_VERSION = "economic_calendar_event_v2"
ECO_CAL_CAPTURE_CONTRACT_VERSION = "eco_cal_local_capture_pit_v2"
ECO_CAL_EXPECTED_COLUMNS = (
    "date",
    "time",
    "currency",
    "country",
    "event",
    "value",
    "pre_value",
    "fore_value",
)
ECO_CAL_REGISTERED_CURRENCIES = (
    "CNY",
    "USD",
    "EUR",
    "BGN",
    "CZK",
    "DKK",
    "HUF",
    "PLN",
    "RON",
    "SEK",
)
ECO_CAL_REGISTERED_ROUTES = (
    ("CNY", "中国"),
    ("USD", "美国"),
    ("EUR", "欧元区"),
    ("BGN", "保加利亚"),
    ("CZK", "捷克"),
    ("DKK", "丹麦"),
    ("HUF", "匈牙利"),
    ("PLN", "波兰"),
    ("RON", "罗马尼亚"),
    ("SEK", "瑞典"),
)
ECO_CAL_EVENT_FAMILIES = (
    "balance",
    "central_banks",
    "credit",
    "economic_activity",
    "employment",
    "inflation",
)
ECO_CAL_EVENT_FAMILY_CLASSIFIER_VERSION = "eco_cal_event_family_classifier_v1"
_EVENT_FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "central_banks",
        (
            "央行",
            "货币政策",
            "利率决议",
            "公开市场操作",
            "fomc",
            "federal reserve",
            "fed ",
            "ecb",
            "pboc",
            "central bank",
            "policy rate",
            "rate decision",
        ),
    ),
    (
        "employment",
        (
            "就业",
            "失业",
            "非农",
            "职位空缺",
            "初请失业金",
            "employment",
            "unemployment",
            "nonfarm",
            "payroll",
            "jobless",
            "job openings",
        ),
    ),
    (
        "inflation",
        (
            "通胀",
            "消费者价格",
            "生产者价格",
            "居民消费价格",
            "cpi",
            "ppi",
            "pce",
            "inflation",
            "consumer price",
            "producer price",
        ),
    ),
    (
        "credit",
        (
            "信贷",
            "贷款",
            "社会融资",
            "货币供应",
            "m0",
            "m1",
            "m2",
            "credit",
            "loan",
            "money supply",
            "aggregate financing",
        ),
    ),
    (
        "balance",
        (
            "贸易帐",
            "贸易差额",
            "经常帐",
            "进出口",
            "出口",
            "进口",
            "外汇储备",
            "trade balance",
            "current account",
            "export",
            "import",
            "foreign exchange reserve",
        ),
    ),
)
_NUMBER_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([%KMBT]?)\s*$", re.I)
_REFERENCE_PERIOD_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})\s*年\s*(?P<month>1[0-2]|0?[1-9])\s*月"),
    re.compile(r"(?P<year>20\d{2})[-/](?P<month>1[0-2]|0[1-9])"),
    re.compile(r"(?P<year>20\d{2})\s*[Qq](?P<quarter>[1-4])"),
)


def _canonical_json(value: Any) -> str:
    return canonical_json(value)


def _hash(value: Any) -> str:
    return canonical_hash(value)


def _id(namespace: str, value: Any) -> str:
    return f"{namespace}:{_hash(value).removeprefix('sha256:')}"


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _raw_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_number(value: Any) -> tuple[float | None, str, str | None]:
    text = _raw_text(value)
    if text is None or text in {"--", "-", "N/A", "n/a"}:
        return None, "EMPTY", None
    normalized = text.replace(",", "")
    match = _NUMBER_RE.fullmatch(normalized)
    if match is None:
        return None, "FAILED", None
    number = float(match.group(1))
    suffix = match.group(2).upper()
    multipliers = {"": 1.0, "%": 1.0, "K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0, "T": 1_000_000_000_000.0}
    return number * multipliers[suffix], "PARSED", "percent" if suffix == "%" else None


def _normalize_event(value: Any) -> str:
    text = _raw_text(value)
    if text is None:
        raise ValueError("eco_cal event must be non-empty")
    return re.sub(r"\s+", " ", text).strip().casefold()


def classify_eco_cal_event_family(normalized_event: str) -> str:
    """Classify event prose locally; Tushare ``country`` is never a family field."""
    event = _normalize_event(normalized_event)
    for family, keywords in _EVENT_FAMILY_KEYWORDS:
        if any(keyword in event for keyword in keywords):
            return family
    return "economic_activity"


def _reference_period(event: str) -> str | None:
    for pattern in _REFERENCE_PERIOD_PATTERNS:
        match = pattern.search(event)
        if match is None:
            continue
        year = match.group("year")
        month = match.groupdict().get("month")
        quarter = match.groupdict().get("quarter")
        return f"{year}-{int(month):02d}" if month else f"{year}-Q{quarter}"
    return None


def _release_stage(event: str) -> str:
    if any(token in event for token in ("终值", "final")):
        return "FINAL"
    if any(token in event for token in ("修正", "revised", "revision")):
        return "REVISION"
    if any(token in event for token in ("初值", "preliminary", "flash")):
        return "PRELIMINARY"
    return "UNSPECIFIED"


def _date_text(value: Any) -> str:
    text = _raw_text(value)
    if text is None:
        raise ValueError("eco_cal date must be non-empty")
    normalized = text.replace("-", "")
    parsed = datetime.strptime(normalized, "%Y%m%d").date()
    return parsed.isoformat()


def _rows(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        columns = tuple(str(column) for column in value.columns)
        if columns != ECO_CAL_EXPECTED_COLUMNS:
            raise ValueError(f"eco_cal schema drift: {columns!r}")
        return [dict(row) for row in value.to_dict(orient="records")]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("eco_cal fetch result must be a DataFrame or row sequence")
    result = [dict(row) for row in value if isinstance(row, Mapping)]
    if len(result) != len(value):
        raise ValueError("eco_cal row sequence contains non-object rows")
    if any(tuple(row) != ECO_CAL_EXPECTED_COLUMNS for row in result):
        raise ValueError("eco_cal schema drift")
    return result


def economic_calendar_cache_path() -> Path:
    explicit = os.getenv("MOSAIC_ECO_CAL_CACHE_PATH")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "economic_calendar" / "eco_cal.sqlite3"


class EconomicCalendarStore:
    """Private append-only ledger for retrievals, raw rows and event revisions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or economic_calendar_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS retrieval_batches (
                    retrieval_batch_id TEXT PRIMARY KEY,
                    retrieved_at TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    query_count INTEGER NOT NULL,
                    raw_row_count INTEGER NOT NULL,
                    deduplicated_row_count INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('COMPLETE', 'REJECTED')),
                    failure_reason TEXT,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raw_rows (
                    raw_row_hash TEXT PRIMARY KEY,
                    first_retrieval_batch_id TEXT NOT NULL REFERENCES retrieval_batches(retrieval_batch_id),
                    row_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_revisions (
                    event_revision_id TEXT PRIMARY KEY,
                    calendar_event_id TEXT NOT NULL,
                    supersedes_revision_id TEXT,
                    valid_from TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS event_revision_content
                  ON event_revisions(calendar_event_id, event_revision_id);
                CREATE TABLE IF NOT EXISTS retrieval_observations (
                    retrieval_batch_id TEXT NOT NULL REFERENCES retrieval_batches(retrieval_batch_id),
                    event_revision_id TEXT NOT NULL REFERENCES event_revisions(event_revision_id),
                    retrieved_at TEXT NOT NULL,
                    PRIMARY KEY(retrieval_batch_id, event_revision_id)
                );
                CREATE TRIGGER IF NOT EXISTS retrieval_batches_no_update
                  BEFORE UPDATE ON retrieval_batches BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS retrieval_batches_no_delete
                  BEFORE DELETE ON retrieval_batches BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS raw_rows_no_update
                  BEFORE UPDATE ON raw_rows BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS raw_rows_no_delete
                  BEFORE DELETE ON raw_rows BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS event_revisions_no_update
                  BEFORE UPDATE ON event_revisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS event_revisions_no_delete
                  BEFORE DELETE ON event_revisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS retrieval_observations_no_update
                  BEFORE UPDATE ON retrieval_observations BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                CREATE TRIGGER IF NOT EXISTS retrieval_observations_no_delete
                  BEFORE DELETE ON retrieval_observations BEGIN SELECT RAISE(ABORT, 'append_only'); END;
                """
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def append_batch(
        self,
        *,
        retrieved_at: str,
        requests: Sequence[Mapping[str, str]],
        rows: Sequence[Mapping[str, Any]],
        status: str = "COMPLETE",
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        retrieved = _timestamp(retrieved_at, "retrieved_at").isoformat()
        if status not in {"COMPLETE", "REJECTED"}:
            raise ValueError("eco_cal batch status is invalid")
        request_rows = [dict(sorted(request.items())) for request in requests]
        raw = [dict(row) for row in rows]
        raw_hashes = [_hash(row) for row in raw]
        deduplicated = {
            raw_hash: row for raw_hash, row in zip(raw_hashes, raw, strict=True)
        }
        identity = {
            "retrieved_at": retrieved,
            "requests": request_rows,
            "raw_row_hashes": sorted(deduplicated),
            "status": status,
            "failure_reason": failure_reason,
        }
        batch_id = _id("eco-cal-retrieval-batch", identity)
        batch = {
            "retrieval_batch_id": batch_id,
            "schema_version": "eco_cal_retrieval_batch_v2",
            **identity,
            "query_count": len(request_rows),
            "raw_row_count": len(raw),
            "deduplicated_row_count": len(deduplicated),
        }
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT record_json FROM retrieval_batches WHERE retrieval_batch_id = ?",
                    (batch_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != _canonical_json(batch):
                        raise ValueError("immutable eco_cal batch collision")
                    revision_ids = [
                        row[0]
                        for row in conn.execute(
                            "SELECT event_revision_id FROM retrieval_observations "
                            "WHERE retrieval_batch_id = ? ORDER BY event_revision_id",
                            (batch_id,),
                        ).fetchall()
                    ]
                    conn.execute("ROLLBACK")
                    return {**json.loads(existing[0]), "event_revision_ids": revision_ids}
                conn.execute(
                    "INSERT INTO retrieval_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        batch_id,
                        retrieved,
                        _canonical_json(request_rows),
                        len(request_rows),
                        len(raw),
                        len(deduplicated),
                        status,
                        failure_reason,
                        _canonical_json(batch),
                    ),
                )
                for raw_hash, row in sorted(deduplicated.items()):
                    conn.execute(
                        "INSERT OR IGNORE INTO raw_rows VALUES (?, ?, ?)",
                        (raw_hash, batch_id, _canonical_json(row)),
                    )
                records = self._append_revisions(
                    conn,
                    batch_id=batch_id,
                    retrieved_at=retrieved,
                    rows=deduplicated,
                ) if status == "COMPLETE" else []
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {**batch, "event_revision_ids": [row["event_revision_id"] for row in records]}

    def _append_revisions(
        self,
        conn: sqlite3.Connection,
        *,
        batch_id: str,
        retrieved_at: str,
        rows: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, ...], list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
        for raw_hash, row in rows.items():
            normalized_event = _normalize_event(row.get("event"))
            event_family = classify_eco_cal_event_family(normalized_event)
            key = (
                _raw_text(row.get("country")) or "UNKNOWN",
                (_raw_text(row.get("currency")) or "UNKNOWN").upper(),
                normalized_event,
                _date_text(row.get("date")),
                _release_stage(normalized_event),
            )
            grouped[key].append((raw_hash, row))
        result: list[dict[str, Any]] = []
        for key, members in sorted(grouped.items()):
            country, currency, normalized_event, raw_date, release_stage = key
            reference_period = _reference_period(normalized_event)
            occurrence_key = (
                f"REFERENCE_PERIOD:{reference_period}"
                if reference_period
                else f"OCCURRENCE_DATE:{raw_date}"
            )
            event_identity = {
                "country": country,
                "currency": currency,
                "normalized_event": normalized_event,
                "event_family": event_family,
                "reference_period": reference_period,
                "release_stage": release_stage,
                "occurrence_key": occurrence_key,
            }
            calendar_event_id = _id("economic-calendar-event", event_identity)
            parsed_fields: dict[str, tuple[float | None, str, str | None]] = {}
            conflict_fields: list[str] = []
            raw_values: dict[str, list[str | None]] = {}
            unit: str | None = None
            for source_field, target_field in (
                ("value", "ACTUAL"),
                ("pre_value", "PREVIOUS"),
                ("fore_value", "FORECAST"),
            ):
                values = sorted({_raw_text(row.get(source_field)) for _, row in members}, key=lambda item: item or "")
                raw_values[source_field] = values
                if len(values) > 1:
                    conflict_fields.append(target_field)
                    parsed_fields[source_field] = (None, "FAILED", None)
                    continue
                parsed_fields[source_field] = _parse_number(values[0])
                unit = unit or parsed_fields[source_field][2]
            actual, actual_status, _ = parsed_fields["value"]
            previous, previous_status, _ = parsed_fields["pre_value"]
            forecast, forecast_status, _ = parsed_fields["fore_value"]
            conflict_status = "CONFLICT" if conflict_fields else "CLEAR"
            event_phase = "RELEASED" if actual_status == "PARSED" else "SCHEDULED"
            raw_row_hashes = sorted(raw_hash for raw_hash, _ in members)
            content = {
                **event_identity,
                "raw_date": raw_date,
                "raw_time": _raw_text(members[0][1].get("time")),
                "occurrence_anchor_date": raw_date,
                "scheduled_at": None,
                "released_at": retrieved_at if event_phase == "RELEASED" else None,
                "timezone": None,
                "time_status": "UNVERIFIED",
                "raw_actual": raw_values["value"][0] if len(raw_values["value"]) == 1 else None,
                "raw_previous": raw_values["pre_value"][0] if len(raw_values["pre_value"]) == 1 else None,
                "raw_forecast": raw_values["fore_value"][0] if len(raw_values["fore_value"]) == 1 else None,
                "actual": actual,
                "previous": previous,
                "forecast": forecast,
                "unit": unit,
                "actual_parse_status": actual_status,
                "previous_parse_status": previous_status,
                "forecast_parse_status": forecast_status,
                "event_phase": event_phase,
                "conflict_status": conflict_status,
                "conflict_fields": conflict_fields,
                "conflict_resolution_evidence_ids": [],
                "reconciliation_status": "CONFLICT" if conflict_fields else "UNVERIFIED",
                "retrieved_at": retrieved_at,
                "valid_from": retrieved_at,
                "valid_to": None,
                "raw_row_hashes": raw_row_hashes,
                "source_evidence_id": _id("tushare-eco-cal-evidence", raw_row_hashes),
                "event_family_classifier_version": (
                    ECO_CAL_EVENT_FAMILY_CLASSIFIER_VERSION
                ),
            }
            latest = conn.execute(
                "SELECT event_revision_id, record_json FROM event_revisions "
                "WHERE calendar_event_id = ? ORDER BY valid_from DESC, rowid DESC LIMIT 1",
                (calendar_event_id,),
            ).fetchone()
            comparable = {key: value for key, value in content.items() if key not in {"retrieved_at", "valid_from"}}
            if latest is not None:
                prior = json.loads(latest["record_json"])
                prior_comparable = {
                    key: value
                    for key, value in prior.items()
                    if key not in {
                        "calendar_event_id",
                        "event_revision_id",
                        "supersedes_revision_id",
                        "retrieval_batch_id",
                        "retrieved_at",
                        "valid_from",
                        "evidence_bundle_id",
                    }
                }
                if prior_comparable == comparable:
                    conn.execute(
                        "INSERT OR IGNORE INTO retrieval_observations VALUES (?, ?, ?)",
                        (batch_id, latest["event_revision_id"], retrieved_at),
                    )
                    result.append(prior)
                    continue
                content["event_phase"] = "REVISED"
                comparable = {
                    key: value
                    for key, value in content.items()
                    if key not in {"retrieved_at", "valid_from"}
                }
            revision_identity = {
                "calendar_event_id": calendar_event_id,
                "content": comparable,
                "raw_row_hashes": raw_row_hashes,
            }
            revision_id = _id("economic-calendar-event-revision", revision_identity)
            evidence_bundle_id = _id(
                "economic-calendar-evidence-bundle",
                {"calendar_event_id": calendar_event_id, "event_revision_id": revision_id},
            )
            record = {
                "calendar_event_id": calendar_event_id,
                "event_revision_id": revision_id,
                "supersedes_revision_id": latest["event_revision_id"] if latest else None,
                "retrieval_batch_id": batch_id,
                **content,
                "evidence_bundle_id": evidence_bundle_id,
            }
            conn.execute(
                "INSERT OR IGNORE INTO event_revisions VALUES (?, ?, ?, ?, ?)",
                (
                    revision_id,
                    calendar_event_id,
                    record["supersedes_revision_id"],
                    retrieved_at,
                    _canonical_json(record),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO retrieval_observations VALUES (?, ?, ?)",
                (batch_id, revision_id, retrieved_at),
            )
            result.append(record)
        return result

    def events_as_of(self, as_of: str) -> list[dict[str, Any]]:
        cutoff = _timestamp(as_of, "as_of").isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT record_json FROM event_revisions AS event
                WHERE valid_from <= ?
                  AND rowid = (
                    SELECT inner_event.rowid FROM event_revisions AS inner_event
                    WHERE inner_event.calendar_event_id = event.calendar_event_id
                      AND inner_event.valid_from <= ?
                    ORDER BY inner_event.valid_from DESC, inner_event.rowid DESC LIMIT 1
                  )
                ORDER BY calendar_event_id
                """,
                (cutoff, cutoff),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def coverage_as_of(
        self,
        *,
        as_of: str,
        occurrence_date: str,
        currencies: Sequence[str],
    ) -> dict[str, Any]:
        cutoff = _timestamp(as_of, "as_of").isoformat()
        query_date = date.fromisoformat(occurrence_date).strftime("%Y%m%d")
        required = tuple(
            sorted(dict.fromkeys(currency.upper() for currency in currencies))
        )
        if not required or any(currency not in ECO_CAL_REGISTERED_CURRENCIES for currency in required):
            raise ValueError("eco_cal coverage currencies are outside the registered scope")
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT record_json FROM retrieval_batches "
                "WHERE retrieved_at <= ? ORDER BY retrieved_at DESC, rowid DESC",
                (cutoff,),
            ).fetchall()
        batches = [json.loads(row[0]) for row in rows]
        country_by_currency = dict(ECO_CAL_REGISTERED_ROUTES)
        required_route_ids = [
            f"eco_cal:{query_date}:{currency}:{country_by_currency[currency]}"
            for currency in required
        ]
        healthy: list[str] = []
        evidence_ids: list[str] = []
        for currency, route_id in zip(required, required_route_ids, strict=True):
            country = country_by_currency[currency]
            selected_batch: dict[str, Any] | None = None
            selected_request: dict[str, Any] | None = None
            for batch in batches:
                requests = batch.get("requests")
                if not isinstance(requests, list):
                    continue
                matching = [
                    request
                    for request in requests
                    if isinstance(request, dict)
                    and request.get("date") == query_date
                    and request.get("country") == country
                    and request.get("expected_currency") == currency
                    and "event" not in request
                ]
                if matching:
                    selected_batch = batch
                    selected_request = matching[0]
                    break
            if selected_batch is None or selected_request is None:
                evidence_ids.append(
                    _id(
                        "eco-cal-missing-coverage",
                        {"as_of": cutoff, "date": query_date, "currency": currency},
                    )
                )
                continue
            evidence_ids.append(selected_batch["retrieval_batch_id"])
            if (
                selected_batch.get("status") == "COMPLETE"
                and selected_request.get("leaf_status") == "COMPLETE"
            ):
                healthy.append(route_id)
        unhealthy = sorted(set(required_route_ids) - set(healthy))
        return {
            "query_complete": not unhealthy,
            "required_route_ids": required_route_ids,
            "healthy_route_ids": sorted(healthy),
            "unhealthy_route_ids": unhealthy,
            "coverage_evidence_ids": sorted(set(evidence_ids)),
        }


def _collect_eco_calendar_unchecked(
    fetch: Callable[..., Any],
    *,
    start_date: str,
    end_date: str,
    retrieved_at: str,
    store: EconomicCalendarStore | None = None,
    currencies: Sequence[str] = ECO_CAL_REGISTERED_CURRENCIES,
) -> dict[str, Any]:
    """Shared collector for runtime and the permission preflight."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("eco_cal end_date precedes start_date")
    normalized_currencies = tuple(dict.fromkeys(currency.upper() for currency in currencies))
    if not normalized_currencies or any(
        currency not in ECO_CAL_REGISTERED_CURRENCIES for currency in normalized_currencies
    ):
        raise ValueError("eco_cal currencies must be a non-empty registered subset")
    requests: list[dict[str, str]] = []
    collected: list[dict[str, Any]] = []
    current = start
    while current <= end:
        query_date = current.strftime("%Y%m%d")
        country_by_currency = dict(ECO_CAL_REGISTERED_ROUTES)
        for currency in normalized_currencies:
            country = country_by_currency[currency]
            request = {
                "date": query_date,
                "country": country,
            }
            leaf = _rows(fetch(**request))
            if len(leaf) >= 100:
                requests.append(
                    {
                        **request,
                        "expected_currency": currency,
                        "row_count": str(len(leaf)),
                        "leaf_status": "TRUNCATED",
                    }
                )
                target = store or EconomicCalendarStore()
                return target.append_batch(
                    retrieved_at=retrieved_at,
                    requests=requests,
                    rows=collected,
                    status="REJECTED",
                    failure_reason=f"TRUNCATED_LEAF:{query_date}:{currency}:{country}",
                )
            if any(
                (_raw_text(row.get("country")) or "") != country
                or (_raw_text(row.get("currency")) or "").upper() != currency
                for row in leaf
            ):
                requests.append(
                    {
                        **request,
                        "expected_currency": currency,
                        "row_count": str(len(leaf)),
                        "leaf_status": "ROUTE_BINDING_MISMATCH",
                    }
                )
                target = store or EconomicCalendarStore()
                return target.append_batch(
                    retrieved_at=retrieved_at,
                    requests=requests,
                    rows=collected,
                    status="REJECTED",
                    failure_reason=f"ROUTE_BINDING_MISMATCH:{query_date}:{currency}:{country}",
                )
            requests.append(
                {
                    **request,
                    "expected_currency": currency,
                    "row_count": str(len(leaf)),
                    "leaf_status": "COMPLETE",
                }
            )
            collected.extend(leaf)
        current += timedelta(days=1)
    target = store or EconomicCalendarStore()
    return target.append_batch(
        retrieved_at=retrieved_at,
        requests=requests,
        rows=collected,
    )


def collect_eco_calendar(
    fetch: Callable[..., Any],
    *,
    start_date: str,
    end_date: str,
    retrieved_at: str,
    store: EconomicCalendarStore | None = None,
    currencies: Sequence[str] = ECO_CAL_REGISTERED_CURRENCIES,
) -> dict[str, Any]:
    """Collect date/currency leaves after the committed preflight authorizes runtime use."""
    registration = assert_endpoint_runtime_enabled("eco_cal")
    if registration.schema_contract_version != ECO_CAL_CAPTURE_CONTRACT_VERSION:
        raise ValueError("eco_cal runtime schema contract is not active")
    return _collect_eco_calendar_unchecked(
        fetch,
        start_date=start_date,
        end_date=end_date,
        retrieved_at=retrieved_at,
        store=store,
        currencies=currencies,
    )


def preflight_eco_calendar_coverage(
    fetch: Callable[..., Any],
    *,
    start_date: str,
    end_date: str,
    retrieved_at: str,
    store: EconomicCalendarStore,
    currencies: Sequence[str] = ECO_CAL_REGISTERED_CURRENCIES,
) -> dict[str, Any]:
    """Exercise the exact runtime query topology before an endpoint is activated."""
    return _collect_eco_calendar_unchecked(
        fetch,
        start_date=start_date,
        end_date=end_date,
        retrieved_at=retrieved_at,
        store=store,
        currencies=currencies,
    )


__all__ = [
    "ECO_CAL_CAPTURE_CONTRACT_VERSION",
    "ECO_CAL_EXPECTED_COLUMNS",
    "ECO_CAL_EVENT_FAMILIES",
    "ECO_CAL_EVENT_FAMILY_CLASSIFIER_VERSION",
    "ECO_CAL_REGISTERED_CURRENCIES",
    "ECO_CAL_REGISTERED_ROUTES",
    "ECO_CAL_SCHEMA_VERSION",
    "EconomicCalendarStore",
    "classify_eco_cal_event_family",
    "collect_eco_calendar",
    "economic_calendar_cache_path",
    "preflight_eco_calendar_coverage",
]
