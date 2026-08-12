"""Trusted source capture orchestration for Agent data materialization.

The source archive owns transport execution and sealed evidence.  It never exposes
raw vendor rows to model-visible tools; the economic-calendar adapter keeps those
rows in the existing private append-only SQLite store.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    RouteCoverageReceipt,
    SourceCaptureReceipt,
)
from mosaic.dataflows.cross_runtime_json import canonical_hash
from mosaic.dataflows.economic_calendar import (
    ECO_CAL_CAPTURE_CONTRACT_VERSION,
    ECO_CAL_EXPECTED_COLUMNS,
    ECO_CAL_REGISTERED_CURRENCIES,
    ECO_CAL_REGISTERED_ROUTES,
    EconomicCalendarStore,
    collect_eco_calendar,
)
from mosaic.dataflows.role_events import (
    ROLE_EVENT_CURRENCIES,
    build_role_event_snapshot,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DECISION_CUTOFF = time(15, 0)
_ECO_CAL_SCHEMA_HASH = canonical_hash(
    {
        "capture_contract_version": ECO_CAL_CAPTURE_CONTRACT_VERSION,
        "columns": list(ECO_CAL_EXPECTED_COLUMNS),
    }
)

ECO_CAL_LOGICAL_ROUTES: dict[str, tuple[str, ...]] = {
    "tushare.eco_cal.cny": ("CNY",),
    "tushare.eco_cal.eur": (
        "EUR",
        "BGN",
        "CZK",
        "DKK",
        "HUF",
        "PLN",
        "RON",
        "SEK",
    ),
    "tushare.eco_cal.usd": ("USD",),
}


@dataclass(frozen=True)
class _LeafAudit:
    query_date: str
    country: str
    currency: str
    row_hashes: tuple[str, ...]


@dataclass(frozen=True)
class SourceArchiveResult:
    batch: dict[str, Any] | None
    source_receipts: tuple[SourceCaptureReceipt, ...]
    coverage_receipt: RouteCoverageReceipt
    role_event_snapshot: dict[str, Any] | None


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _rows_for_audit(value: Any) -> list[dict[str, Any]] | None:
    if hasattr(value, "to_dict"):
        records = value.to_dict(orient="records")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        records = list(value)
    else:
        return None
    if not all(isinstance(row, Mapping) for row in records):
        return None
    return [dict(row) for row in records]


def _cutoff(as_of_date: str) -> datetime:
    return datetime.combine(
        date.fromisoformat(as_of_date),
        _DECISION_CUTOFF,
        tzinfo=_SHANGHAI,
    )


def _logical_route_for_currency(currency: str) -> str:
    return next(
        route_id
        for route_id, currencies in ECO_CAL_LOGICAL_ROUTES.items()
        if currency in currencies
    )


def _requested_routes(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return tuple(sorted(ECO_CAL_LOGICAL_ROUTES))
    if isinstance(value, (str, bytes)):
        raise ValueError("requested_route_ids must be a sequence of route IDs")
    route_ids = tuple(value)
    if (
        not route_ids
        or route_ids != tuple(sorted(set(route_ids)))
        or not set(route_ids) <= set(ECO_CAL_LOGICAL_ROUTES)
    ):
        raise ValueError(
            "requested_route_ids must be a non-empty sorted unique calendar route subset"
        )
    return route_ids


def _currencies_for_routes(route_ids: Sequence[str]) -> tuple[str, ...]:
    selected = {
        currency
        for route_id in route_ids
        for currency in ECO_CAL_LOGICAL_ROUTES[route_id]
    }
    return tuple(
        currency
        for currency in ECO_CAL_REGISTERED_CURRENCIES
        if currency in selected
    )


def _coverage_receipt(
    *,
    as_of_date: str,
    requested_route_ids: Sequence[str],
    route_results: Sequence[Mapping[str, Any]],
    blocker_codes: Sequence[str],
) -> RouteCoverageReceipt:
    window_start = datetime.combine(
        date.fromisoformat(as_of_date), time.min, tzinfo=_SHANGHAI
    ).isoformat()
    window_end = _cutoff(as_of_date).isoformat()
    results = sorted(
        (dict(result) for result in route_results),
        key=lambda result: str(result["route_id"]),
    )
    blockers = sorted(set(blocker_codes))
    identity = {
        "as_of_date": as_of_date,
        "route_results": results,
        "blocker_codes": blockers,
    }
    return RouteCoverageReceipt.seal(
        {
            "schema_version": "route_coverage_receipt_v1",
            "coverage_id": (
                "eco-cal-coverage:"
                + canonical_hash(identity).removeprefix("sha256:")
            ),
            "window": {
                "start": window_start,
                "end": window_end,
                "timezone": "Asia/Shanghai",
            },
            "required_route_ids": list(requested_route_ids),
            "route_results": results,
            "coverage_complete": not blockers,
            "blocker_codes": blockers,
        }
    )


def _failed_result(
    *,
    as_of_date: str,
    requested_route_ids: Sequence[str],
    ledger: AgentDataMaterializationLedger,
    route_statuses: Mapping[str, str],
    blockers: Sequence[str],
    batch: dict[str, Any] | None = None,
) -> SourceArchiveResult:
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        requested_route_ids=requested_route_ids,
        route_results=[
            {
                "route_id": route_id,
                "capture_receipt_hash": None,
                "status": route_statuses[route_id],
            }
            for route_id in requested_route_ids
        ],
        blocker_codes=blockers,
    )
    ledger.append_route_coverage(coverage)
    return SourceArchiveResult(
        batch=batch,
        source_receipts=(),
        coverage_receipt=coverage,
        role_event_snapshot=None,
    )


def _uniform_failure(
    *,
    as_of_date: str,
    requested_route_ids: Sequence[str],
    ledger: AgentDataMaterializationLedger,
    route_status: str,
    blocker: str,
) -> SourceArchiveResult:
    return _failed_result(
        as_of_date=as_of_date,
        requested_route_ids=requested_route_ids,
        ledger=ledger,
        route_statuses={
            route_id: route_status for route_id in requested_route_ids
        },
        blockers=[blocker],
    )


def _rejected_batch_result(
    *,
    as_of_date: str,
    requested_route_ids: Sequence[str],
    ledger: AgentDataMaterializationLedger,
    batch: dict[str, Any],
) -> SourceArchiveResult:
    failure = str(batch.get("failure_reason") or "")
    statuses = {
        route_id: "CAPTURE_REJECTED" for route_id in requested_route_ids
    }
    if failure.startswith("TRUNCATED_LEAF:"):
        currency = failure.split(":", 3)[2]
        statuses[_logical_route_for_currency(currency)] = "TRUNCATED"
        blockers = ["TRUNCATED"]
    elif failure.startswith("ROUTE_BINDING_MISMATCH:"):
        currency = failure.split(":", 3)[2]
        statuses[_logical_route_for_currency(currency)] = "SCHEMA_DRIFT"
        blockers = ["SCHEMA_DRIFT"]
    else:
        blockers = ["CAPTURE_REJECTED"]
    return _failed_result(
        as_of_date=as_of_date,
        requested_route_ids=requested_route_ids,
        ledger=ledger,
        route_statuses=statuses,
        blockers=blockers,
        batch=batch,
    )


def _source_receipt(
    *,
    route_id: str,
    currencies: Sequence[str],
    audits: Sequence[_LeafAudit],
    as_of_date: str,
    captured_at: str,
    as_of_cutoff: str,
    batch_id: str,
) -> SourceCaptureReceipt:
    selected = sorted(
        (audit for audit in audits if audit.currency in currencies),
        key=lambda audit: (audit.query_date, audit.currency, audit.country),
    )
    raw_hashes = [row_hash for audit in selected for row_hash in audit.row_hashes]
    unique_hashes = sorted(set(raw_hashes))
    request = {
        "endpoint": "eco_cal",
        "leaves": [
            {
                "date": audit.query_date,
                "country": audit.country,
                "currency": audit.currency,
            }
            for audit in selected
        ],
    }
    content_identity = {
        "retrieval_batch_id": batch_id,
        "leaves": [
            {
                "date": audit.query_date,
                "country": audit.country,
                "currency": audit.currency,
                "row_hashes": list(audit.row_hashes),
            }
            for audit in selected
        ],
    }
    normalized_count = len(unique_hashes)
    empty_semantics = "TRUE_EMPTY" if normalized_count == 0 else "NON_EMPTY"
    identity_hash = canonical_hash(
        {"route_id": route_id, "batch_id": batch_id, "request": request}
    ).removeprefix("sha256:")
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": "tushare",
                "route_id": route_id,
                "request_hash": canonical_hash(request),
                "capture_id": f"eco-cal-capture:{identity_hash}",
            },
            "transport": {
                "redacted_url": "https://api.tushare.pro/eco_cal",
                "method": "POST",
                "query_keys": ["country", "date"],
                "pagination_policy": "SINGLE_PAGE_EXACT_DATE",
                "page_count": len(selected),
            },
            "authority": {
                "provider": "tushare",
                "permission_tier": "token_preflight_verified",
                "api_version": "pro-v1",
                "parser_version": ECO_CAL_CAPTURE_CONTRACT_VERSION,
            },
            "time": {
                # eco_cal has no single route-level release/vintage timestamp.
                # The live capture is the conservative first trusted availability;
                # row-level occurrence/release fields remain in the private store.
                "released_at": captured_at,
                "vintage_at": captured_at,
                "captured_at": captured_at,
                "knowledge_available_at": captured_at,
            },
            "pit": {
                "pit_mode": "OBSERVED_LIVE",
                "as_of_cutoff": as_of_cutoff,
                "eligible": True,
                "blocker_codes": [],
                "vintage_query": None,
            },
            "content": {
                "raw_content_hash": canonical_hash(content_identity),
                "normalized_row_count": normalized_count,
                "schema_hash": _ECO_CAL_SCHEMA_HASH,
            },
            "coverage": {
                "requested_start": as_of_date,
                "requested_end": as_of_date,
                "observed_start": as_of_date if normalized_count else None,
                "observed_end": as_of_date if normalized_count else None,
                "dimensions": {
                    "country": sorted(audit.country for audit in selected),
                    "currency": sorted(currencies),
                },
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": len(raw_hashes) - normalized_count,
                "empty_result_semantics": empty_semantics,
            },
            "provenance": {
                "parent_capture_hash": None,
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def _reuse_existing_archive(
    *,
    as_of_date: str,
    as_of_cutoff: datetime,
    requested_route_ids: Sequence[str],
    currencies: Sequence[str],
    store: EconomicCalendarStore,
    ledger: AgentDataMaterializationLedger,
    consumer_agent: str | None,
) -> SourceArchiveResult | None:
    receipts_by_route: dict[str, dict[str, SourceCaptureReceipt]] = {}
    for route_id in requested_route_ids:
        candidates: dict[str, SourceCaptureReceipt] = {}
        for receipt in ledger.source_capture_receipts_for_route(route_id=route_id):
            payload = receipt.as_dict()
            captured_at = str(payload["time"]["captured_at"])
            if (
                payload["coverage"]["requested_start"] != as_of_date
                or payload["coverage"]["requested_end"] != as_of_date
                or payload["pit"]["eligible"] is not True
                or _timestamp(captured_at, "captured_at") > as_of_cutoff
                or _timestamp(
                    str(payload["pit"]["as_of_cutoff"]), "receipt.as_of_cutoff"
                )
                > as_of_cutoff
            ):
                continue
            candidates[captured_at] = receipt
        if not candidates:
            return None
        receipts_by_route[route_id] = candidates

    common_capture_times = set.intersection(
        *(set(candidates) for candidates in receipts_by_route.values())
    )
    if not common_capture_times:
        return None
    captured_at = max(
        common_capture_times,
        key=lambda value: _timestamp(value, "captured_at"),
    )
    store_coverage = store.coverage_as_of(
        as_of=captured_at,
        occurrence_date=as_of_date,
        currencies=currencies,
    )
    if store_coverage["query_complete"] is not True:
        return None

    receipts = tuple(
        receipts_by_route[route_id][captured_at]
        for route_id in sorted(receipts_by_route)
    )
    route_results = [
        {
            "route_id": receipt.as_dict()["identity"]["route_id"],
            "capture_receipt_hash": receipt.receipt_hash,
            "status": (
                "TRUE_EMPTY"
                if receipt.as_dict()["content"]["normalized_row_count"] == 0
                else "SUCCESS"
            ),
        }
        for receipt in receipts
    ]
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        requested_route_ids=requested_route_ids,
        route_results=route_results,
        blocker_codes=[],
    )
    ledger.append_capture_group(receipts, coverage)
    snapshot = (
        build_role_event_snapshot(consumer_agent, as_of_date, store=store)
        if consumer_agent is not None
        else None
    )
    return SourceArchiveResult(
        batch=None,
        source_receipts=receipts,
        coverage_receipt=coverage,
        role_event_snapshot=snapshot,
    )


def archive_eco_calendar(
    fetch: Callable[..., Any],
    *,
    as_of_date: str,
    captured_at: str,
    store: EconomicCalendarStore,
    ledger: AgentDataMaterializationLedger,
    as_of_cutoff: str | None = None,
    requested_route_ids: Sequence[str] | None = None,
    consumer_agent: str | None = None,
) -> SourceArchiveResult:
    """Capture the requested eco_cal leaves and seal matching route receipts.

    Known transport failures are classified precisely. Any other adapter/vendor
    exception is sealed as CAPTURE_REJECTED so a failed attempt always leaves an
    auditable, fail-closed coverage receipt without exposing exception text.
    """
    captured = _timestamp(captured_at, "captured_at")
    cutoff = (
        _timestamp(as_of_cutoff, "as_of_cutoff")
        if as_of_cutoff is not None
        else _cutoff(as_of_date)
    )
    route_ids = _requested_routes(requested_route_ids)
    currencies = _currencies_for_routes(route_ids)
    if consumer_agent is not None and consumer_agent not in ROLE_EVENT_CURRENCIES:
        raise ValueError(f"role-event access is denied for {consumer_agent}")
    if consumer_agent is not None:
        consumer_routes = {
            _logical_route_for_currency(currency)
            for currency in ROLE_EVENT_CURRENCIES[consumer_agent]
        }
        if not consumer_routes <= set(route_ids):
            raise ValueError(
                "requested calendar routes do not cover the role-event consumer"
            )
        route_ids = tuple(sorted(consumer_routes))
        currencies = tuple(
            currency
            for currency in ECO_CAL_REGISTERED_CURRENCIES
            if currency in ROLE_EVENT_CURRENCIES[consumer_agent]
        )
    historical_replay = cutoff.astimezone(_SHANGHAI).date() > date.fromisoformat(
        as_of_date
    )
    if captured > cutoff or historical_replay:
        replay = _reuse_existing_archive(
            as_of_date=as_of_date,
            as_of_cutoff=cutoff,
            requested_route_ids=route_ids,
            currencies=currencies,
            store=store,
            ledger=ledger,
            consumer_agent=consumer_agent,
        )
        if replay is not None:
            return replay
        if captured > cutoff:
            return _uniform_failure(
                as_of_date=as_of_date,
                requested_route_ids=route_ids,
                ledger=ledger,
                route_status="PIT_INELIGIBLE",
                blocker="CAPTURE_AFTER_AS_OF_CUTOFF",
            )

    audits: list[_LeafAudit] = []
    currency_by_country = {
        country: currency for currency, country in ECO_CAL_REGISTERED_ROUTES
    }

    def audited_fetch(**request: str) -> Any:
        value = fetch(**request)
        rows = _rows_for_audit(value)
        if rows is not None:
            audits.append(
                _LeafAudit(
                    query_date=request["date"],
                    country=request["country"],
                    currency=currency_by_country[request["country"]],
                    row_hashes=tuple(canonical_hash(row) for row in rows),
                )
            )
        return value

    try:
        batch = collect_eco_calendar(
            audited_fetch,
            start_date=as_of_date,
            end_date=as_of_date,
            retrieved_at=captured.isoformat(),
            store=store,
            currencies=currencies,
        )
    except TimeoutError:
        return _uniform_failure(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            route_status="TRANSPORT_FAILED",
            blocker="TRANSPORT_TIMEOUT",
        )
    except PermissionError:
        return _uniform_failure(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            route_status="PERMISSION_DENIED",
            blocker="PERMISSION_DENIED",
        )
    except ConnectionError:
        return _uniform_failure(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            route_status="TRANSPORT_FAILED",
            blocker="TRANSPORT_FAILED",
        )
    except ValueError as exc:
        if str(exc).startswith("DENY_UNKNOWN_ENDPOINT:"):
            return _uniform_failure(
                as_of_date=as_of_date,
                requested_route_ids=route_ids,
                ledger=ledger,
                route_status="CAPTURE_REJECTED",
                blocker="CAPTURE_REJECTED",
            )
        return _uniform_failure(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            route_status="SCHEMA_DRIFT",
            blocker="SCHEMA_DRIFT",
        )
    except Exception:  # noqa: BLE001 - trust boundary must seal vendor failures
        return _uniform_failure(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            route_status="CAPTURE_REJECTED",
            blocker="CAPTURE_REJECTED",
        )

    if batch["status"] != "COMPLETE":
        return _rejected_batch_result(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            batch=batch,
        )
    if len(audits) != len(currencies):
        return _uniform_failure(
            as_of_date=as_of_date,
            requested_route_ids=route_ids,
            ledger=ledger,
            route_status="SCHEMA_DRIFT",
            blocker="LEAF_AUDIT_INCOMPLETE",
        )

    receipts = tuple(
        _source_receipt(
            route_id=route_id,
            currencies=tuple(
                currency
                for currency in ECO_CAL_LOGICAL_ROUTES[route_id]
                if currency in currencies
            ),
            audits=audits,
            as_of_date=as_of_date,
            captured_at=captured.isoformat(),
            as_of_cutoff=cutoff.isoformat(),
            batch_id=str(batch["retrieval_batch_id"]),
        )
        for route_id in route_ids
    )
    results = [
        {
            "route_id": receipt.as_dict()["identity"]["route_id"],
            "capture_receipt_hash": receipt.receipt_hash,
            "status": (
                "TRUE_EMPTY"
                if receipt.as_dict()["content"]["normalized_row_count"] == 0
                else "SUCCESS"
            ),
        }
        for receipt in receipts
    ]
    coverage = _coverage_receipt(
        as_of_date=as_of_date,
        requested_route_ids=route_ids,
        route_results=results,
        blocker_codes=[],
    )
    ledger.append_capture_group(receipts, coverage)
    snapshot = (
        build_role_event_snapshot(consumer_agent, as_of_date, store=store)
        if consumer_agent is not None
        else None
    )
    return SourceArchiveResult(
        batch=batch,
        source_receipts=receipts,
        coverage_receipt=coverage,
        role_event_snapshot=snapshot,
    )


__all__ = [
    "ECO_CAL_LOGICAL_ROUTES",
    "SourceArchiveResult",
    "archive_eco_calendar",
]
