from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from mosaic.dataflows import agent_cycle_authority as cycle_authority
from mosaic.dataflows.agent_materialization import (
    AgentCycleEvent,
    AgentCyclePublication,
    AgentDataMaterializationLedger,
    RouteEligibilityReceipt,
    RuntimeRouteNotRequiredReceipt,
    SourceCaptureReceipt,
    load_agent_data_route_manifest,
)
from mosaic.dataflows.route_eligibility import (
    ROUTE_ELIGIBILITY_CHECKERS,
    earliest_agent_source_ready_date,
    evaluate_agent_cycle_preflight,
    evaluate_agent_source_admission,
    evaluate_route_eligibility,
    evaluate_runtime_stage_admission,
)
from mosaic.dataflows.source_archive import ECO_CAL_LOGICAL_ROUTES
from mosaic.scorecard.canonical_json import canonical_hash


HASH = "sha256:" + "1" * 64
TARGET = "2026-07-01"
EVALUATED_AT = "2026-07-01T08:00:00+00:00"


def _write_mof_chinabond_license_receipt(path: Path) -> str:
    payload = {
        "schema_version": "source_license_decision_receipt_v1",
        "receipt_id": "license:mof-chinabond:2026-08-11",
        "route_id": "composite.cn_rates",
        "source_id": "official.mof_chinabond_government_yield_curve",
        "decision": "APPROVED_FOR_PRODUCTION_USE",
        "authorization_scope": "production_analysis",
        "reviewer": "named-compliance-reviewer",
        "decided_at": "2026-06-30T09:00:00+08:00",
    }
    payload["receipt_hash"] = canonical_hash(payload)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload["receipt_hash"]


def _route(route_id: str) -> dict:
    return next(
        row
        for row in load_agent_data_route_manifest()["routes"]
        if row["route_id"] == route_id
    )


def _source_receipt(
    route_id: str,
    *,
    target: str = TARGET,
    requested_start: str | None = None,
    requested_end: str | None = None,
    observed_start: str | None = None,
    observed_end: str | None = None,
    observed_at: str | None = None,
    authority_provider: str | None = None,
    dimensions: dict[str, list[str]] | None = None,
) -> SourceCaptureReceipt:
    route = _route(route_id)
    spec = ROUTE_ELIGIBILITY_CHECKERS[route["contract_version"]]
    policy = spec.receipt_policy
    authoritative = route["pit_strategy"] in {
        "AUTHORITATIVE_VINTAGE_REPLAY",
        "DERIVED_FROM_PIT_ARCHIVE",
    }
    start = observed_start or target
    end = observed_end or target
    request_start = requested_start or start
    request_end = requested_end or end
    captured_at = observed_at or f"{target}T06:00:00+00:00"
    capture_time_id = captured_at.replace("+", "p")
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": route["source_family"],
                "route_id": route_id,
                "request_hash": HASH,
                "capture_id": (
                    f"capture:{route_id}:{target}:{start}:{end}:{capture_time_id}"
                ),
            },
            "transport": {
                "redacted_url": "local-test://route-eligibility",
                "method": "FILE",
                "query_keys": ["target_date"],
                "pagination_policy": policy.pagination_policy,
                "page_count": 1,
            },
            "authority": {
                "provider": authority_provider or policy.authority_provider,
                "permission_tier": policy.permission_tier,
                "api_version": policy.api_version,
                "parser_version": "route_eligibility_fixture_v1",
            },
            "time": {
                "released_at": f"{target}T05:00:00+00:00",
                "vintage_at": f"{target}T05:30:00+00:00",
                "captured_at": captured_at,
                "knowledge_available_at": (
                    f"{target}T05:30:00+00:00"
                    if authoritative
                    else captured_at
                ),
            },
            "pit": {
                "pit_mode": (
                    "AUTHORITATIVE_VINTAGE_REPLAY"
                    if authoritative
                    else "OBSERVED_LIVE"
                ),
                "as_of_cutoff": f"{target}T23:00:00+00:00",
                "eligible": True,
                "blocker_codes": [],
                "vintage_query": (
                    {"target_date": target} if authoritative else None
                ),
            },
            "content": {
                "raw_content_hash": HASH,
                "normalized_row_count": 1,
                "schema_hash": HASH,
            },
            "coverage": {
                "requested_start": request_start,
                "requested_end": request_end,
                "observed_start": start,
                "observed_end": end,
                "dimensions": (
                    dimensions
                    if dimensions is not None
                    else {
                        key: list(values) if values else ["fixture"]
                        for key, values in policy.required_dimensions
                    }
                ),
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
            "provenance": {
                "parent_capture_hash": (
                    HASH if policy.require_parent_capture else None
                ),
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def test_checker_registry_is_exactly_bound_to_all_route_contract_versions():
    manifest = load_agent_data_route_manifest()
    expected = {route["contract_version"] for route in manifest["routes"]}
    assert len(expected) == 29
    assert set(ROUTE_ELIGIBILITY_CHECKERS) == expected
    assert {
        spec.route_id for spec in ROUTE_ELIGIBILITY_CHECKERS.values()
    } == {route["route_id"] for route in manifest["routes"]}
    assert all(spec.receipt_policy.authority_provider for spec in ROUTE_ELIGIBILITY_CHECKERS.values())
    assert all(spec.receipt_policy.api_version for spec in ROUTE_ELIGIBILITY_CHECKERS.values())
    assert all(spec.receipt_policy.pagination_policy for spec in ROUTE_ELIGIBILITY_CHECKERS.values())


def test_checker_registry_uses_replayable_europe_contract_versions_only():
    assert "ecb_euro_macro_v2" in ROUTE_ELIGIBILITY_CHECKERS
    assert "ecb_eu_real_economy_history_v1" in ROUTE_ELIGIBILITY_CHECKERS
    assert "ecb_euro_macro_v1" not in ROUTE_ELIGIBILITY_CHECKERS
    assert "eurostat_forward_archive_v1" not in ROUTE_ELIGIBILITY_CHECKERS


def test_all_contract_checkers_accept_their_exact_receipt_profile(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    routes = load_agent_data_route_manifest()["routes"]
    for route in routes:
        ledger.append_source_capture(_source_receipt(route["route_id"]))

    results = {
        route["route_id"]: evaluate_route_eligibility(
            ledger=ledger,
            route_id=route["route_id"],
            target_date=TARGET,
            evaluated_at=EVALUATED_AT,
        ).as_dict()
        for route in routes
    }

    assert len(results) == 29
    assert {route_id for route_id, result in results.items() if result["status"] == "READY"} == set(results)


def test_contract_checker_skips_newer_wrong_authority_and_selects_valid_revision(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    valid = _source_receipt("alfred.us_macro", observed_at=f"{TARGET}T06:00:00+00:00")
    wrong = _source_receipt(
        "alfred.us_macro",
        observed_at=f"{TARGET}T07:00:00+00:00",
        authority_provider="tushare",
    )
    ledger.append_source_capture(valid)
    ledger.append_source_capture(wrong)

    ready = evaluate_route_eligibility(
        ledger=ledger,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()
    assert ready["status"] == "READY"
    assert ready["selected_receipt_refs"] == [valid.receipt_hash]

    wrong_only = AgentDataMaterializationLedger(tmp_path / "wrong.sqlite3")
    wrong_only.append_source_capture(wrong)
    blocked = evaluate_route_eligibility(
        ledger=wrong_only,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()
    assert blocked["status"] == "BLOCKED"
    assert blocked["blockers"] == ["SCHEMA_DRIFT"]
    assert blocked["selected_receipt_refs"] == [wrong.receipt_hash]


def test_contract_checker_rejects_missing_route_continuity_dimensions(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    receipt = _source_receipt("tushare.commodities", dimensions={})
    ledger.append_source_capture(receipt)

    blocked = evaluate_route_eligibility(
        ledger=ledger,
        route_id="tushare.commodities",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert blocked["status"] == "BLOCKED"
    assert blocked["blockers"] == ["REVISION_GAP"]


@pytest.mark.parametrize(
    "route_id",
    ("tushare.sector_fundamentals", "tushare.sector_market"),
)
def test_sector_checker_accepts_exact_membership_without_parent_capture(
    tmp_path: Path, route_id: str
):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    receipt = _source_receipt(route_id)
    assert receipt.as_dict()["provenance"]["parent_capture_hash"] is None
    ledger.append_source_capture(receipt)

    result = evaluate_route_eligibility(
        ledger=ledger,
        route_id=route_id,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert result["status"] == "READY"
    assert result["blockers"] == []
    assert result["selected_receipt_refs"] == [receipt.receipt_hash]


@pytest.mark.parametrize(
    "route_id",
    ("tushare.sector_fundamentals", "tushare.sector_market"),
)
def test_sector_checker_rejects_non_exact_membership_without_parent_capture(
    tmp_path: Path, route_id: str
):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    receipt = _source_receipt(
        route_id,
        dimensions={"logical_route": ["tushare.unregistered_sector_route"]},
    )
    assert receipt.as_dict()["provenance"]["parent_capture_hash"] is None
    ledger.append_source_capture(receipt)

    result = evaluate_route_eligibility(
        ledger=ledger,
        route_id=route_id,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert result["status"] == "BLOCKED"
    assert result["blockers"] == ["REVISION_GAP"]
    assert result["selected_receipt_refs"] == [receipt.receipt_hash]


def test_euro_calendar_checker_accepts_registered_logical_currency_set(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    receipt = _source_receipt(
        "tushare.eco_cal.eur",
        dimensions={
            "country": ["fixture"],
            "currency": sorted(ECO_CAL_LOGICAL_ROUTES["tushare.eco_cal.eur"]),
        },
    )
    ledger.append_source_capture(receipt)

    result = evaluate_route_eligibility(
        ledger=ledger,
        route_id="tushare.eco_cal.eur",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert result["status"] == "READY"
    assert result["blockers"] == []


def test_earliest_ready_date_intersects_all_source_and_historical_runtime_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    routes = load_agent_data_route_manifest()["routes"]
    required = [
        route["route_id"]
        for route in routes
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
    ] + [
        "runtime.account_positions_policy",
        "runtime.market_liquidity",
    ]
    assert len(required) == 27
    for route_id in required:
        ledger.append_source_capture(
            _source_receipt(
                route_id,
                observed_start="2026-06-29",
                observed_end="2026-07-03",
            )
        )

    calendar_calls: list[tuple[str, str, str]] = []

    def fake_calendar(start_date: str, end_date: str, *, as_of: str) -> dict:
        calendar_calls.append((start_date, end_date, as_of))
        return {
            "schema_version": "verified_trading_calendar_snapshot_v1",
            "snapshot_hash": HASH,
            "trading_dates": ["2026-06-30", "2026-07-01", "2026-07-02"],
        }

    monkeypatch.setattr(
        "mosaic.dataflows.route_eligibility.verified_trading_calendar_snapshot",
        fake_calendar,
    )

    result = earliest_agent_source_ready_date(
        ledger=ledger,
        evaluated_at="2026-07-04T08:00:00+00:00",
    )

    assert result["status"] == "READY"
    assert result["earliest_ready_date"] == "2026-06-30"
    assert result["source_route_count"] == 25
    assert result["runtime_precheck_route_ids"] == [
        "runtime.account_positions_policy",
        "runtime.market_liquidity",
    ]
    assert result["pending_runtime_route_ids"] == [
        "runtime.accepted_outputs",
        "runtime.candidate_scope",
    ]
    assert result["eligible_intervals"] == [
        {"start": "2026-06-29", "end": "2026-07-03"}
    ]
    assert result["calendar_snapshot_hash"] == HASH
    assert calendar_calls == [
        ("2026-06-29", "2026-07-04", "2026-07-04T08:00:00+00:00")
    ]


def test_earliest_ready_date_blocks_before_calendar_when_runtime_archive_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    for route in load_agent_data_route_manifest()["routes"]:
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY":
            ledger.append_source_capture(
                _source_receipt(
                    route["route_id"],
                    observed_start="2026-06-29",
                    observed_end="2026-07-03",
                )
            )
    ledger.append_source_capture(
        _source_receipt(
            "runtime.account_positions_policy",
            observed_start="2026-06-29",
            observed_end="2026-07-03",
        )
    )

    def unexpected_calendar(*_args, **_kwargs):
        raise AssertionError("calendar must not run without runtime archive closure")

    monkeypatch.setattr(
        "mosaic.dataflows.route_eligibility.verified_trading_calendar_snapshot",
        unexpected_calendar,
    )

    result = earliest_agent_source_ready_date(
        ledger=ledger,
        evaluated_at="2026-07-04T08:00:00+00:00",
    )

    assert result["status"] == "BLOCKED"
    assert result["earliest_ready_date"] is None
    assert result["route_blockers"] == {
        "runtime.market_liquidity": ["MISSING_ARCHIVE"]
    }
    assert result["calendar_snapshot_hash"] is None


def test_route_eligibility_requires_exact_covering_receipt_and_is_append_only(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    missing = evaluate_route_eligibility(
        ledger=ledger,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    )
    assert missing.as_dict()["status"] == "BLOCKED"
    assert missing.as_dict()["blockers"] == ["MISSING_ARCHIVE"]

    outside = _source_receipt(
        "alfred.us_macro",
        target="2026-07-02",
        observed_start="2026-07-02",
        observed_end="2026-07-02",
    )
    ledger.append_source_capture(outside)
    blocked = evaluate_route_eligibility(
        ledger=ledger,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    )
    assert blocked.as_dict()["status"] == "BLOCKED"
    assert blocked.as_dict()["blockers"] == ["OUTSIDE_COVERAGE"]

    source = _source_receipt("alfred.us_macro")
    ledger.append_source_capture(source)
    ready = evaluate_route_eligibility(
        ledger=ledger,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    )
    payload = ready.as_dict()
    assert payload["status"] == "READY"
    assert payload["eligible_intervals"] == [{"start": TARGET, "end": TARGET}]
    assert payload["selected_receipt_refs"] == [source.receipt_hash]
    assert ledger.append_route_eligibility(ready) == ready.receipt_hash
    assert (
        ledger.route_eligibility_receipt(receipt_hash=ready.receipt_hash).as_dict()
        == payload
    )

    with sqlite3.connect(ledger.path) as conn, pytest.raises(
        sqlite3.IntegrityError, match="append_only"
    ):
        conn.execute(
            "UPDATE route_eligibility_receipts SET status = 'BLOCKED' "
            "WHERE receipt_hash = ?",
            (ready.receipt_hash,),
        )


def test_authoritative_vintage_uses_requested_as_of_coverage_without_extending_live_data(
    tmp_path: Path,
) -> None:
    vintage_ledger = AgentDataMaterializationLedger(tmp_path / "vintage.sqlite3")
    vintage = _source_receipt(
        "alfred.us_macro",
        requested_start="2026-06-01",
        requested_end=TARGET,
        observed_start="2026-06-01",
        observed_end="2026-06-30",
    )
    vintage_ledger.append_source_capture(vintage)

    vintage_result = evaluate_route_eligibility(
        ledger=vintage_ledger,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert vintage_result["status"] == "READY"
    assert vintage_result["eligible_intervals"] == [
        {"start": "2026-06-01", "end": TARGET}
    ]

    live_ledger = AgentDataMaterializationLedger(tmp_path / "live.sqlite3")
    live = _source_receipt(
        "tushare.cn_macro",
        requested_start="2026-06-01",
        requested_end=TARGET,
        observed_start="2026-06-01",
        observed_end="2026-06-30",
    )
    live_ledger.append_source_capture(live)

    live_result = evaluate_route_eligibility(
        ledger=live_ledger,
        route_id="tushare.cn_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert live_result["status"] == "BLOCKED"
    assert live_result["blockers"] == ["OUTSIDE_COVERAGE"]


@pytest.mark.parametrize(
    ("route_id", "stale_observed_end"),
    (
        ("tushare.fx_daily", "2026-06-26"),
        ("market.us_conditions", "2026-06-26"),
        ("market.euro_fx", "2026-06-26"),
    ),
)
def test_market_session_routes_cover_decision_date_only_within_registered_lag(
    tmp_path: Path, route_id: str, stale_observed_end: str
) -> None:
    ready_ledger = AgentDataMaterializationLedger(
        tmp_path / f"{route_id}-ready.sqlite3"
    )
    ready_source = _source_receipt(
        route_id,
        requested_start="2026-06-01",
        requested_end=TARGET,
        observed_start="2026-06-01",
        observed_end="2026-06-30",
    )
    ready_ledger.append_source_capture(ready_source)

    ready = evaluate_route_eligibility(
        ledger=ready_ledger,
        route_id=route_id,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert ready["status"] == "READY"
    assert ready["eligible_intervals"] == [
        {"start": "2026-06-01", "end": TARGET}
    ]

    stale_ledger = AgentDataMaterializationLedger(
        tmp_path / f"{route_id}-stale.sqlite3"
    )
    stale_source = _source_receipt(
        route_id,
        requested_start="2026-06-01",
        requested_end=TARGET,
        observed_start="2026-06-01",
        observed_end=stale_observed_end,
    )
    stale_ledger.append_source_capture(stale_source)

    stale = evaluate_route_eligibility(
        ledger=stale_ledger,
        route_id=route_id,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert stale["status"] == "BLOCKED"
    assert stale["blockers"] == ["OUTSIDE_COVERAGE"]


def test_official_policy_feed_covers_decision_through_requested_end(
    tmp_path: Path,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "official-policy.sqlite3")
    source = _source_receipt(
        "official.us_policy",
        requested_start="2026-03-18",
        requested_end=TARGET,
        observed_start="2026-03-18",
        observed_end="2026-06-17",
    )
    ledger.append_source_capture(source)

    result = evaluate_route_eligibility(
        ledger=ledger,
        route_id="official.us_policy",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert result["status"] == "READY"
    assert result["eligible_intervals"] == [
        {"start": "2026-03-18", "end": TARGET}
    ]


def test_official_policy_empty_replay_does_not_claim_historical_coverage(
    tmp_path: Path,
) -> None:
    payload = _source_receipt(
        "official.us_policy",
        requested_start=TARGET,
        requested_end=TARGET,
    ).as_dict()
    payload["content"]["normalized_row_count"] = 0
    payload["coverage"]["observed_start"] = None
    payload["coverage"]["observed_end"] = None
    payload["completeness"]["empty_result_semantics"] = "TRUE_EMPTY"
    source = SourceCaptureReceipt.seal(payload)
    ledger = AgentDataMaterializationLedger(tmp_path / "official-policy-empty.sqlite3")
    ledger.append_source_capture(source)

    result = evaluate_route_eligibility(
        ledger=ledger,
        route_id="official.us_policy",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    assert result["status"] == "BLOCKED"
    assert result["blockers"] == ["OUTSIDE_COVERAGE"]


def test_receipt_rejects_manifest_or_checker_drift(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    source = _source_receipt("alfred.us_macro")
    ledger.append_source_capture(source)
    receipt = evaluate_route_eligibility(
        ledger=ledger,
        route_id="alfred.us_macro",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()

    drifted = dict(receipt)
    drifted["contract_version"] = "unregistered_contract_v1"
    with pytest.raises(ValueError, match="route manifest"):
        RouteEligibilityReceipt.seal(drifted)

    drifted = dict(receipt)
    drifted["checker_version"] = "unregistered_checker_v1"
    with pytest.raises(ValueError, match="checker version"):
        RouteEligibilityReceipt.seal(drifted)


def test_checker_ignores_a_newer_revision_not_known_at_evaluation_time(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    older = _source_receipt(
        "tushare.a_share_breadth",
        observed_at=f"{TARGET}T06:00:00+00:00",
    )
    future = _source_receipt(
        "tushare.a_share_breadth",
        observed_at=f"{TARGET}T09:00:00+00:00",
    )
    ledger.append_source_capture(older)
    ledger.append_source_capture(future)

    receipt = evaluate_route_eligibility(
        ledger=ledger,
        route_id="tushare.a_share_breadth",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    )
    assert receipt.as_dict()["selected_receipt_refs"] == [older.receipt_hash]


def test_curve_license_receipt_is_required_only_for_production_enforce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = AgentDataMaterializationLedger(tmp_path / "curve-license.sqlite3")
    source = _source_receipt("composite.cn_rates")
    ledger.append_source_capture(source)

    shadow = evaluate_route_eligibility(
        ledger=ledger,
        route_id="composite.cn_rates",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    ).as_dict()
    assert shadow["status"] == "READY"

    blocked = evaluate_route_eligibility(
        ledger=ledger,
        route_id="composite.cn_rates",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
        require_production_license=True,
    ).as_dict()
    assert blocked["status"] == "BLOCKED"
    assert blocked["blockers"] == ["LICENSE_REVIEW_REQUIRED"]
    assert blocked["selected_receipt_refs"] == [source.receipt_hash]

    receipt_path = tmp_path / "mof-chinabond-license.json"
    receipt_hash = _write_mof_chinabond_license_receipt(receipt_path)
    monkeypatch.setenv(
        "MOSAIC_MOF_CHINABOND_LICENSE_RECEIPT_PATH", str(receipt_path)
    )
    ready = evaluate_route_eligibility(
        ledger=ledger,
        route_id="composite.cn_rates",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
        require_production_license=True,
    ).as_dict()
    assert ready["status"] == "READY"
    assert ready["license_receipt_ref"] == receipt_hash


def test_cycle_preflight_is_all_or_none_for_exact_28_stage_route_union(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    manifest = load_agent_data_route_manifest()
    missing_route = "composite.cn_rates"
    for route in manifest["routes"]:
        if route["route_id"] != missing_route:
            ledger.append_source_capture(_source_receipt(route["route_id"]))

    blocked = evaluate_agent_cycle_preflight(
        ledger=ledger,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["route_count"] == 29
    assert blocked["stage_count"] == 28
    assert blocked["blocked_routes"] == [
        {"route_id": missing_route, "blockers": ["MISSING_ARCHIVE"]}
    ]
    assert blocked["would_materialize"] is False
    assert any(
        missing_route in stage["required_route_ids"]
        and stage["status"] == "BLOCKED"
        for stage in blocked["stages"]
    )

    ledger.append_source_capture(_source_receipt(missing_route))
    ready = evaluate_agent_cycle_preflight(
        ledger=ledger,
        target_date=TARGET,
        evaluated_at="2026-07-01T08:01:00+00:00",
    )
    assert ready["status"] == "READY"
    assert ready["blocked_routes"] == []
    assert ready["would_materialize"] is True
    assert all(stage["status"] == "READY" for stage in ready["stages"])


def test_source_admission_allows_25_ready_routes_to_start_before_runtime_exists(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    manifest = load_agent_data_route_manifest()
    source_routes = [
        route
        for route in manifest["routes"]
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
    ]
    runtime_route_ids = sorted(
        route["route_id"]
        for route in manifest["routes"]
        if route["pit_strategy"] == "LOCAL_RUNTIME_AUTHORITY"
    )
    assert len(source_routes) == 25
    assert len(runtime_route_ids) == 4
    for route in source_routes:
        ledger.append_source_capture(_source_receipt(route["route_id"]))

    admission = evaluate_agent_source_admission(
        ledger=ledger,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
        cycle_run_id="cycle-source-admission-1",
    )

    assert admission["schema_version"] == "agent_source_admission_v1"
    assert admission["status"] == "SOURCE_READY_PENDING_RUNTIME"
    assert admission["would_materialize"] is True
    assert admission["route_count"] == 25
    assert admission["runtime_route_count"] == 4
    assert admission["pending_runtime_route_ids"] == runtime_route_ids
    assert set(admission["eligibility_receipt_hashes"]) == {
        route["route_id"] for route in source_routes
    }
    assert {
        ledger.route_eligibility_receipt(receipt_hash=receipt_hash)
        .as_dict()["cycle_run_id"]
        for receipt_hash in admission["eligibility_receipt_hashes"].values()
    } == {"cycle-source-admission-1"}
    assert admission["stage_count"] == 28
    assert admission["blocked_routes"] == []
    assert any(
        stage["status"] == "SOURCE_READY_PENDING_RUNTIME"
        and stage["pending_runtime_route_ids"]
        for stage in admission["stages"]
    )
    assert all(
        not set(stage["eligibility_receipt_hashes"]) & set(runtime_route_ids)
        for stage in admission["stages"]
    )


def test_production_source_admission_blocks_only_curve_without_license_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_MOF_CHINABOND_LICENSE_RECEIPT_PATH", raising=False)
    ledger = AgentDataMaterializationLedger(tmp_path / "production-license.sqlite3")
    manifest = load_agent_data_route_manifest()
    source_routes = [
        route
        for route in manifest["routes"]
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
    ]
    for route in source_routes:
        ledger.append_source_capture(_source_receipt(route["route_id"]))

    admission = evaluate_agent_source_admission(
        ledger=ledger,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
        require_production_license=True,
    )

    assert admission["status"] == "BLOCKED"
    assert admission["blocked_routes"] == [
        {
            "route_id": "composite.cn_rates",
            "blockers": ["LICENSE_REVIEW_REQUIRED"],
        }
    ]


def test_source_admission_blocks_when_one_of_26_source_routes_is_missing(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    manifest = load_agent_data_route_manifest()
    missing_route = "composite.cn_rates"
    for route in manifest["routes"]:
        if (
            route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
            and route["route_id"] != missing_route
        ):
            ledger.append_source_capture(_source_receipt(route["route_id"]))

    admission = evaluate_agent_source_admission(
        ledger=ledger,
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
    )

    assert admission["status"] == "BLOCKED"
    assert admission["would_materialize"] is False
    assert admission["blocked_routes"] == [
        {"route_id": missing_route, "blockers": ["MISSING_ARCHIVE"]}
    ]


def test_runtime_stage_admission_uses_only_current_build_source_receipts(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    old_accepted = _source_receipt(
        "runtime.accepted_outputs",
        observed_at=f"{TARGET}T06:00:00+00:00",
    )
    current_accepted = _source_receipt(
        "runtime.accepted_outputs",
        observed_at=f"{TARGET}T07:00:00+00:00",
    )
    current_scope = _source_receipt(
        "runtime.candidate_scope",
        observed_at=f"{TARGET}T07:00:00+00:00",
    )
    for receipt in (old_accepted, current_accepted, current_scope):
        ledger.append_source_capture(receipt)

    result = evaluate_runtime_stage_admission(
        ledger=ledger,
        agent_id="ackman",
        stage="ackman",
        target_date=TARGET,
        evaluated_at=EVALUATED_AT,
        cycle_run_id="cycle-runtime-1",
        source_receipt_hashes=[
            current_accepted.receipt_hash,
            current_scope.receipt_hash,
        ],
    )

    assert set(result) == {
        "runtime.accepted_outputs",
        "runtime.candidate_scope",
    }
    selected = {
        route_id: ledger.route_eligibility_receipt(receipt_hash=receipt_hash)
        .as_dict()
        for route_id, receipt_hash in result.items()
    }
    assert selected["runtime.accepted_outputs"]["selected_receipt_refs"] == [
        current_accepted.receipt_hash
    ]
    assert {payload["cycle_run_id"] for payload in selected.values()} == {
        "cycle-runtime-1"
    }


def test_runtime_stage_admission_rejects_missing_exact_current_build_route(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    accepted = _source_receipt("runtime.accepted_outputs")
    ledger.append_source_capture(accepted)

    with pytest.raises(ValueError, match="runtime.candidate_scope"):
        evaluate_runtime_stage_admission(
            ledger=ledger,
            agent_id="ackman",
            stage="ackman",
            target_date=TARGET,
            evaluated_at=EVALUATED_AT,
            cycle_run_id="cycle-runtime-2",
            source_receipt_hashes=[accepted.receipt_hash],
        )


def _cycle_authority_hashes() -> dict[str, str]:
    manifest = load_agent_data_route_manifest()
    return {
        "route_manifest_hash": manifest["manifest_hash"],
        "agent_tool_contract_manifest_hash": manifest[
            "agent_tool_contract_manifest_hash"
        ],
        "execution_behavior_release_hash": HASH,
        "knot_coverage_manifest_v2_hash": HASH,
    }


def _cycle_eligibility_refs(
    ledger: AgentDataMaterializationLedger,
    *,
    run_id: str,
    target_date: str = TARGET,
) -> tuple[dict[str, str], dict[str, str]]:
    manifest = load_agent_data_route_manifest()
    for route in manifest["routes"]:
        ledger.append_source_capture(
            _source_receipt(route["route_id"], target=target_date)
        )
    source = evaluate_agent_source_admission(
        ledger=ledger,
        target_date=target_date,
        evaluated_at=f"{target_date}T08:00:00+00:00",
        cycle_run_id=run_id,
    )["eligibility_receipt_hashes"]
    runtime = {}
    for route in manifest["routes"]:
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY":
            continue
        receipt = evaluate_route_eligibility(
            ledger=ledger,
            route_id=route["route_id"],
            target_date=target_date,
            evaluated_at=f"{target_date}T08:00:00+00:00",
            cycle_run_id=run_id,
        )
        ledger.append_route_eligibility(receipt)
        runtime[route["route_id"]] = receipt.receipt_hash
    return source, runtime


def _cycle_event_payload(
    *,
    run_id: str,
    state: str,
    source_refs: dict[str, str],
    runtime_refs: dict[str, str] | None = None,
    target_date: str = TARGET,
) -> dict:
    manifest = load_agent_data_route_manifest()
    stage_keys = sorted(
        {(binding["agent_id"], binding["stage"]) for binding in manifest["bindings"]}
    )
    assert len(stage_keys) == 28
    terminal = state == "COMMITTED"
    return {
        "schema_version": "agent_cycle_event_v1",
        "event_id": f"cycle-event:{run_id}:{state.lower()}",
        "run_id": run_id,
        "target_date": target_date,
        "cohort": "cohort_default",
        "mode": "enforce",
        "cycle_kind": "PRODUCTION",
        "state": state,
        "authority_hashes": _cycle_authority_hashes(),
        "source_eligibility_receipt_hashes": source_refs,
        "runtime_route_closure_refs": runtime_refs if terminal else {},
        "stage_outcomes": (
            [
                {
                    "agent_id": agent_id,
                    "stage": stage,
                    "outcome_kind": "ACCEPTED_OUTPUT",
                    "ref_hash": HASH,
                }
                for agent_id, stage in stage_keys
            ]
            if terminal
            else []
        ),
        "accepted_output_closure_hash": HASH if terminal else None,
        "final_decision_hash": HASH if terminal else None,
        "lease": {
            "opened_at": f"{target_date}T08:00:00+00:00",
            "expires_at": f"{target_date}T09:00:00+00:00",
        },
        "terminal_reason": None,
        "event_at": (
            f"{target_date}T08:30:00+00:00"
            if terminal
            else f"{target_date}T08:00:00+00:00"
        ),
    }


def _runtime_route_consumers(route_id: str) -> list[tuple[str, str]]:
    manifest = load_agent_data_route_manifest()
    return sorted(
        {
            (binding["agent_id"], binding["stage"])
            for binding in manifest["bindings"]
            if route_id in binding["required_route_ids"]
        }
    )


def test_replay_cycle_event_requires_shadow_mode():
    manifest = load_agent_data_route_manifest()
    source_refs = {
        route["route_id"]: HASH
        for route in manifest["routes"]
        if route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
    }
    replay = {
        **_cycle_event_payload(
            run_id="historical-replay-1",
            state="OPEN",
            source_refs=source_refs,
        ),
        "cycle_kind": "REPLAY",
    }

    with pytest.raises(ValueError, match="REPLAY cycle requires shadow mode"):
        AgentCycleEvent.seal(replay)

    accepted = AgentCycleEvent.seal({**replay, "mode": "shadow"})
    assert accepted.as_dict()["cycle_kind"] == "REPLAY"
    assert accepted.as_dict()["mode"] == "shadow"


def _not_required_receipt(
    *,
    route_id: str,
    run_id: str,
    skip_hash: str = HASH,
) -> RuntimeRouteNotRequiredReceipt:
    route = _route(route_id)
    return RuntimeRouteNotRequiredReceipt.seal(
        {
            "schema_version": "runtime_route_not_required_v1",
            "receipt_id": f"runtime-not-required:{run_id}:{route_id}",
            "route_id": route_id,
            "contract_version": route["contract_version"],
            "target_date": TARGET,
            "run_id": run_id,
            "unexecuted_stages": [
                {
                    "agent_id": agent_id,
                    "stage": stage,
                    "skip_receipt_hash": skip_hash,
                }
                for agent_id, stage in _runtime_route_consumers(route_id)
            ],
            "upstream_authority_hashes": _cycle_authority_hashes(),
            "evaluated_at": f"{TARGET}T08:25:00+00:00",
        }
    )


def test_cycle_commit_atomically_publishes_and_enforces_production_cas(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    run_id = "cycle-production-1"
    source_refs, runtime_refs = _cycle_eligibility_refs(ledger, run_id=run_id)
    opened = AgentCycleEvent.seal(
        _cycle_event_payload(run_id=run_id, state="OPEN", source_refs=source_refs)
    )
    ledger.append_cycle_open(opened)
    committed = AgentCycleEvent.seal(
        _cycle_event_payload(
            run_id=run_id,
            state="COMMITTED",
            source_refs=source_refs,
            runtime_refs=runtime_refs,
        )
    )
    publication = AgentCyclePublication.seal(
        {
            "schema_version": "agent_cycle_publication_v1",
            "publication_id": f"cycle-publication:{run_id}",
            "run_id": run_id,
            "target_date": TARGET,
            "cohort": "cohort_default",
            "cycle_kind": "PRODUCTION",
            "committed_event_hash": committed.receipt_hash,
            "final_decision_hash": HASH,
            "published_at": f"{TARGET}T08:30:00+00:00",
        }
    )

    event_hash, publication_hash = ledger.commit_cycle(committed, publication)
    assert event_hash == committed.receipt_hash
    assert publication_hash == publication.receipt_hash
    assert (
        ledger.committed_cycle_publication(run_id=run_id).as_dict()
        == publication.as_dict()
    )

    second_run = "cycle-production-2"
    second_source, second_runtime = _cycle_eligibility_refs(
        ledger, run_id=second_run
    )
    second_open = AgentCycleEvent.seal(
        _cycle_event_payload(
            run_id=second_run,
            state="OPEN",
            source_refs=second_source,
        )
    )
    assert second_runtime
    with pytest.raises(ValueError, match="already COMMITTED"):
        ledger.append_cycle_open(second_open)
    assert ledger.committed_cycle_publication(run_id=second_run) is None
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM agent_cycle_events WHERE run_id = ?",
            (second_run,),
        ).fetchone()[0] == 0


def test_cycle_abort_is_terminal_and_non_committed_is_not_publishable(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    run_id = "cycle-abort-1"
    source_refs, runtime_refs = _cycle_eligibility_refs(ledger, run_id=run_id)
    opened_payload = _cycle_event_payload(
        run_id=run_id,
        state="OPEN",
        source_refs=source_refs,
    )
    ledger.append_cycle_open(AgentCycleEvent.seal(opened_payload))
    aborted = AgentCycleEvent.seal(
        {
            **opened_payload,
            "event_id": f"cycle-event:{run_id}:aborted",
            "state": "ABORTED",
            "terminal_reason": "STAGE_FAILURE",
            "event_at": f"{TARGET}T08:20:00+00:00",
        }
    )
    ledger.append_cycle_abort(aborted)
    assert ledger.committed_cycle_publication(run_id=run_id) is None

    committed = AgentCycleEvent.seal(
        _cycle_event_payload(
            run_id=run_id,
            state="COMMITTED",
            source_refs=source_refs,
            runtime_refs=runtime_refs,
        )
    )
    publication = AgentCyclePublication.seal(
        {
            "schema_version": "agent_cycle_publication_v1",
            "publication_id": f"cycle-publication:{run_id}",
            "run_id": run_id,
            "target_date": TARGET,
            "cohort": "cohort_default",
            "cycle_kind": "PRODUCTION",
            "committed_event_hash": committed.receipt_hash,
            "final_decision_hash": HASH,
            "published_at": f"{TARGET}T08:30:00+00:00",
        }
    )
    with pytest.raises(ValueError, match="active OPEN"):
        ledger.commit_cycle(committed, publication)


def test_cycle_abort_preserves_partial_stage_skip_without_runtime_not_required(
    tmp_path: Path,
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    run_id = "cycle-skip-then-abort"
    source_refs, _ = _cycle_eligibility_refs(ledger, run_id=run_id)
    opened_payload = _cycle_event_payload(
        run_id=run_id,
        state="OPEN",
        source_refs=source_refs,
    )
    ledger.append_cycle_open(AgentCycleEvent.seal(opened_payload))
    first_stage = min(
        {
            (binding["agent_id"], binding["stage"])
            for binding in load_agent_data_route_manifest()["bindings"]
        }
    )
    aborted = AgentCycleEvent.seal(
        {
            **opened_payload,
            "event_id": f"cycle-event:{run_id}:aborted",
            "state": "ABORTED",
            "stage_outcomes": [
                {
                    "agent_id": first_stage[0],
                    "stage": first_stage[1],
                    "outcome_kind": "STAGE_SKIP",
                    "ref_hash": HASH,
                }
            ],
            "terminal_reason": "LATER_STAGE_FAILURE",
            "event_at": f"{TARGET}T08:20:00+00:00",
        }
    )

    ledger.append_cycle_abort(aborted)

    with sqlite3.connect(ledger.path) as conn:
        persisted = json.loads(
            conn.execute(
                "SELECT receipt_json FROM agent_cycle_events "
                "WHERE run_id = ? AND state = 'ABORTED'",
                (run_id,),
            ).fetchone()[0]
        )
        assert persisted["stage_outcomes"] == aborted.as_dict()["stage_outcomes"]
        assert conn.execute(
            "SELECT count(*) FROM runtime_route_not_required_receipts"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM agent_cycle_publications"
        ).fetchone()[0] == 0


def test_expired_open_is_atomically_aborted_before_new_open(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    old_run = "cycle-stale-old"
    old_source, _ = _cycle_eligibility_refs(ledger, run_id=old_run)
    ledger.append_cycle_open(
        AgentCycleEvent.seal(
            _cycle_event_payload(
                run_id=old_run,
                state="OPEN",
                source_refs=old_source,
            )
        )
    )
    new_run = "cycle-stale-new"
    new_source, _ = _cycle_eligibility_refs(ledger, run_id=new_run)
    new_payload = _cycle_event_payload(
        run_id=new_run,
        state="OPEN",
        source_refs=new_source,
    )
    new_payload["event_at"] = f"{TARGET}T10:00:00+00:00"
    new_payload["lease"] = {
        "opened_at": f"{TARGET}T10:00:00+00:00",
        "expires_at": f"{TARGET}T11:00:00+00:00",
    }

    ledger.append_cycle_open(AgentCycleEvent.seal(new_payload))

    assert ledger.open_cycle_event(run_id=old_run) is None
    assert ledger.open_cycle_event(run_id=new_run) is not None
    with sqlite3.connect(ledger.path) as conn:
        stale_json = conn.execute(
            "SELECT receipt_json FROM agent_cycle_events "
            "WHERE run_id = ? AND state = 'ABORTED'",
            (old_run,),
        ).fetchone()[0]
        assert json.loads(stale_json)["terminal_reason"] == "STALE_OPEN"


def test_concurrent_open_has_exactly_one_active_winner(tmp_path: Path):
    path = tmp_path / "materialization.sqlite3"
    ledger = AgentDataMaterializationLedger(path)
    events = []
    for run_id in ("cycle-open-race-1", "cycle-open-race-2"):
        source_refs, _ = _cycle_eligibility_refs(ledger, run_id=run_id)
        events.append(
            AgentCycleEvent.seal(
                _cycle_event_payload(
                    run_id=run_id,
                    state="OPEN",
                    source_refs=source_refs,
                )
            )
        )
    barrier = Barrier(2)

    def attempt(event: AgentCycleEvent) -> tuple[str, str]:
        contender = AgentDataMaterializationLedger(path, create=False)
        barrier.wait()
        try:
            contender.append_cycle_open(event)
        except ValueError as exc:
            return "error", str(exc)
        return "ok", event.as_dict()["run_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, events))

    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("error") == 1
    assert any("active OPEN lease" in detail for status, detail in results if status == "error")
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM agent_cycle_events WHERE state = 'OPEN'"
        ).fetchone()[0] == 1


def test_concurrent_commit_retry_publishes_exactly_once(tmp_path: Path):
    path = tmp_path / "materialization.sqlite3"
    ledger = AgentDataMaterializationLedger(path)
    run_id = "cycle-commit-race"
    source_refs, runtime_refs = _cycle_eligibility_refs(ledger, run_id=run_id)
    ledger.append_cycle_open(
        AgentCycleEvent.seal(
            _cycle_event_payload(
                run_id=run_id,
                state="OPEN",
                source_refs=source_refs,
            )
        )
    )
    committed = AgentCycleEvent.seal(
        _cycle_event_payload(
            run_id=run_id,
            state="COMMITTED",
            source_refs=source_refs,
            runtime_refs=runtime_refs,
        )
    )
    publication = AgentCyclePublication.seal(
        {
            "schema_version": "agent_cycle_publication_v1",
            "publication_id": f"cycle-publication:{run_id}",
            "run_id": run_id,
            "target_date": TARGET,
            "cohort": "cohort_default",
            "cycle_kind": "PRODUCTION",
            "committed_event_hash": committed.receipt_hash,
            "final_decision_hash": HASH,
            "published_at": f"{TARGET}T08:30:00+00:00",
        }
    )
    barrier = Barrier(2)

    def attempt() -> tuple[str, str]:
        contender = AgentDataMaterializationLedger(path, create=False)
        barrier.wait()
        try:
            _, publication_hash = contender.commit_cycle(committed, publication)
        except ValueError as exc:
            return "error", str(exc)
        return "ok", publication_hash

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result() for future in futures]

    assert [status for status, _ in results].count("ok") == 1
    assert [status for status, _ in results].count("error") == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT count(*) FROM agent_cycle_events WHERE state = 'COMMITTED'"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM agent_cycle_publications").fetchone()[0] == 1


def test_cycle_commit_accepts_not_required_for_all_skipped_consumers(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    run_id = "cycle-not-required"
    route_id = "runtime.candidate_scope"
    source_refs, runtime_refs = _cycle_eligibility_refs(ledger, run_id=run_id)
    ledger.append_cycle_open(
        AgentCycleEvent.seal(
            _cycle_event_payload(
                run_id=run_id,
                state="OPEN",
                source_refs=source_refs,
            )
        )
    )
    not_required = _not_required_receipt(route_id=route_id, run_id=run_id)
    ledger.append_runtime_route_not_required(not_required)
    runtime_refs[route_id] = not_required.receipt_hash
    committed_payload = _cycle_event_payload(
        run_id=run_id,
        state="COMMITTED",
        source_refs=source_refs,
        runtime_refs=runtime_refs,
    )
    consumers = set(_runtime_route_consumers(route_id))
    for outcome in committed_payload["stage_outcomes"]:
        if (outcome["agent_id"], outcome["stage"]) in consumers:
            outcome["outcome_kind"] = "STAGE_SKIP"
    committed = AgentCycleEvent.seal(committed_payload)
    publication = AgentCyclePublication.seal(
        {
            "schema_version": "agent_cycle_publication_v1",
            "publication_id": f"cycle-publication:{run_id}",
            "run_id": run_id,
            "target_date": TARGET,
            "cohort": "cohort_default",
            "cycle_kind": "PRODUCTION",
            "committed_event_hash": committed.receipt_hash,
            "final_decision_hash": HASH,
            "published_at": f"{TARGET}T08:30:00+00:00",
        }
    )

    _, publication_hash = ledger.commit_cycle(committed, publication)

    assert publication_hash == publication.receipt_hash


def test_cycle_commit_rejects_not_required_when_a_consumer_executed(tmp_path: Path):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    run_id = "cycle-not-required-invalid"
    route_id = "runtime.candidate_scope"
    source_refs, runtime_refs = _cycle_eligibility_refs(ledger, run_id=run_id)
    ledger.append_cycle_open(
        AgentCycleEvent.seal(
            _cycle_event_payload(
                run_id=run_id,
                state="OPEN",
                source_refs=source_refs,
            )
        )
    )
    not_required = _not_required_receipt(route_id=route_id, run_id=run_id)
    ledger.append_runtime_route_not_required(not_required)
    runtime_refs[route_id] = not_required.receipt_hash
    committed = AgentCycleEvent.seal(
        _cycle_event_payload(
            run_id=run_id,
            state="COMMITTED",
            source_refs=source_refs,
            runtime_refs=runtime_refs,
        )
    )
    publication = AgentCyclePublication.seal(
        {
            "schema_version": "agent_cycle_publication_v1",
            "publication_id": f"cycle-publication:{run_id}",
            "run_id": run_id,
            "target_date": TARGET,
            "cohort": "cohort_default",
            "cycle_kind": "PRODUCTION",
            "committed_event_hash": committed.receipt_hash,
            "final_decision_hash": HASH,
            "published_at": f"{TARGET}T08:30:00+00:00",
        }
    )

    with pytest.raises(ValueError, match="not-required"):
        ledger.commit_cycle(committed, publication)


def test_high_level_commit_seals_not_required_for_skipped_route(
    tmp_path: Path, monkeypatch
):
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    run_id = "cycle-high-level-not-required"
    route_id = "runtime.candidate_scope"
    manifest = load_agent_data_route_manifest()
    for route in manifest["routes"]:
        ledger.append_source_capture(_source_receipt(route["route_id"]))
    cycle_authority.open_agent_cycle(
        ledger=ledger,
        target_date=TARGET,
        run_id=run_id,
        cohort="cohort_default",
        mode="enforce",
        cycle_kind="PRODUCTION",
        execution_behavior_release_hash=HASH,
        knot_coverage_manifest_v2_hash=HASH,
        opened_at=EVALUATED_AT,
    )
    for route in manifest["routes"]:
        if (
            route["pit_strategy"] != "LOCAL_RUNTIME_AUTHORITY"
            or route["route_id"] == route_id
        ):
            continue
        receipt = evaluate_route_eligibility(
            ledger=ledger,
            route_id=route["route_id"],
            target_date=TARGET,
            evaluated_at=f"{TARGET}T08:20:00+00:00",
            cycle_run_id=run_id,
        )
        ledger.append_route_eligibility(receipt)
    skipped_consumers = set(_runtime_route_consumers(route_id))
    stage_keys = sorted(
        {(binding["agent_id"], binding["stage"]) for binding in manifest["bindings"]}
    )
    stage_outcomes = [
        {
            "agent_id": agent_id,
            "stage": stage,
            "outcome_kind": (
                "STAGE_SKIP"
                if (agent_id, stage) in skipped_consumers
                else "ACCEPTED_OUTPUT"
            ),
            "ref_hash": HASH,
        }
        for agent_id, stage in stage_keys
    ]
    monkeypatch.setattr(
        cycle_authority,
        "accepted_cycle_stage_outcome_refs",
        lambda _state: stage_outcomes,
    )
    state = {
        "trace_id": run_id,
        "as_of_date": TARGET,
        "active_cohort": "cohort_default",
        "decision_disposition": "HOLD",
        "final_target_state": None,
        "portfolio_actions": [],
        "day_outcome_status": "accepted",
    }

    committed = cycle_authority.commit_agent_cycle(
        ledger=ledger,
        state=state,
        committed_at=f"{TARGET}T08:30:00+00:00",
    )

    assert committed["status"] == "COMMITTED"
    with sqlite3.connect(ledger.path) as conn:
        row = conn.execute(
            "SELECT receipt_json FROM runtime_route_not_required_receipts"
        ).fetchone()
    assert json.loads(row[0])["route_id"] == route_id
