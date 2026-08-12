from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import mosaic.dataflows.sector_archive as sector_archive
import pytest
from mosaic.dataflows.agent_materialization import AgentDataMaterializationLedger
from mosaic.dataflows.a_share_archive import ASharePaginationError, AShareSchemaError
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.sector_archive import (
    LOGICAL_ROUTES,
    SectorArchiveStore,
    _build_capture_group,
    archive_sector_relationship,
    compile_sector_relationship_core_snapshots,
)
from mosaic.dataflows.tushare_catalog import PREFLIGHT_ENDPOINT_CHECKS


AS_OF = "2026-08-06"
CUTOFF = "2026-08-06T23:59:00+08:00"


def _sealed_group(
    capture_key: str,
    agent_ids: tuple[str, ...] = sector_archive.STANDARD_SECTOR_AGENT_IDS,
) -> dict[str, Any]:
    group = {
        "schema_version": "sector_relationship_capture_group_v2",
        "capture_key": capture_key,
        "as_of_date": AS_OF,
        "cutoff_at": CUTOFF,
        "captured_at": "2026-08-06T17:00:00+08:00",
        "sessions": ["20260806"],
        "batches": [
            {"endpoint": endpoint, "rows": [{"fixture_endpoint": endpoint}]}
            for endpoint in (
                "trade_cal",
                "stock_basic",
                "daily",
                "adj_factor",
                "suspend_d",
                "daily_basic",
            )
        ],
        "page_count": 7,
        "normalized_row_count": 11,
        "requested_route_ids": list(sector_archive.LOGICAL_ROUTES),
        "capture_scope": {
            "sector_agent_ids": list(agent_ids),
            "security_codes": [],
            "etf_codes": [],
        },
    }
    group["capture_scope_hash"] = sector_archive.canonical_hash(
        group["capture_scope"]
    )
    return group


def test_sector_archive_atomically_publishes_two_routes_and_replays_cache(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    calls = {"builder": 0}

    def build(*_args, capture_key: str, **_kwargs):
        calls["builder"] += 1
        group = _sealed_group(capture_key)
        group["capture_scope"]["sector_agent_ids"] = ["semiconductor"]
        group["capture_scope_hash"] = sector_archive.canonical_hash(
            group["capture_scope"]
        )
        return group

    monkeypatch.setattr(sector_archive, "_build_capture_group", build)
    monkeypatch.setattr(
        sector_archive,
        "compile_sector_archive_group",
        lambda _group: {"semiconductor": {"snapshot_hash": f"sha256:{'c' * 64}"}},
    )
    first = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )
    second = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )

    assert calls["builder"] == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert {row.as_dict()["identity"]["route_id"] for row in first.source_receipts} == set(
        LOGICAL_ROUTES
    )
    assert {
        row.as_dict()["transport"]["pagination_policy"]
        for row in first.source_receipts
    } == {"ENDPOINT_SPECIFIC_COMPLETENESS_V1"}
    assert first.coverage_receipt.as_dict()["coverage_complete"] is True
    assert store.row_count() == 1
    counts = ledger.row_counts()
    assert counts["source_capture_receipts"] == 2
    assert counts["route_coverage_receipts"] == 1


def test_archive_scope_binds_exact_object_capture_key_and_receipt(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")

    def build(
        *_args,
        capture_key: str,
        requested_route_ids,
        requested_agent_ids,
        **_kwargs,
    ):
        security_code = {
            "semiconductor": "000001.SZ",
            "technology": "000002.SZ",
        }[requested_agent_ids[0]]
        group = _sealed_group(capture_key)
        group["requested_route_ids"] = list(requested_route_ids)
        group["capture_scope"] = {
            "sector_agent_ids": list(requested_agent_ids),
            "security_codes": [security_code],
            "etf_codes": [],
        }
        group["capture_scope_hash"] = sector_archive.canonical_hash(
            group["capture_scope"]
        )
        return group

    monkeypatch.setattr(sector_archive, "_build_capture_group", build)
    monkeypatch.setattr(
        sector_archive,
        "compile_sector_archive_group",
        lambda group: {
            group["capture_scope"]["sector_agent_ids"][0]: {
                "snapshot_hash": f"sha256:{'c' * 64}"
            }
        },
    )
    monkeypatch.setattr(
        sector_archive,
        "write_registered_sector_snapshot",
        lambda **kwargs: kwargs["snapshot"],
    )

    results = [
        archive_sector_relationship(
            lambda *_args, **_kwargs: None,
            as_of_date=AS_OF,
            cutoff_at=CUTOFF,
            requested_route_ids=(
                "tushare.sector_fundamentals",
                "tushare.sector_market",
            ),
            requested_agent_ids=(agent_id,),
            store=store,
            ledger=ledger,
        )
        for agent_id in ("semiconductor", "technology")
    ]

    assert store.row_count() == 2
    assert all("base_group_hash" not in result.group for result in results)
    assert results[0].group["capture_key"] != results[1].group["capture_key"]
    assert (
        results[0].source_receipts[0].as_dict()["identity"]["request_hash"]
        != results[1].source_receipts[0].as_dict()["identity"]["request_hash"]
    )
    published = [
        compile_sector_relationship_core_snapshots(result, ledger=ledger)
        for result in results
    ]
    assert [list(result.snapshots) for result in published] == [
        ["semiconductor"],
        ["technology"],
    ]


def test_sector_archive_historical_replay_seals_real_completion_cutoff(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    completion = "2026-08-10T23:30:00+08:00"

    def build(
        *_args,
        capture_key: str,
        historical_replay: bool,
        requested_agent_ids,
        **_kwargs,
    ):
        assert historical_replay is True
        group = _sealed_group(capture_key, tuple(requested_agent_ids))
        group["captured_at"] = completion
        group["cutoff_at"] = completion
        group["historical_replay"] = True
        group["historical_replay_time_policy_version"] = (
            sector_archive.HISTORICAL_REPLAY_TIME_POLICY_VERSION
        )
        return group

    monkeypatch.setattr(sector_archive, "_build_capture_group", build)
    monkeypatch.setattr(
        sector_archive,
        "compile_sector_archive_group",
        lambda _group: {"semiconductor": {"snapshot_hash": f"sha256:{'c' * 64}"}},
    )

    result = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        historical_replay=True,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )

    assert result.coverage_receipt.as_dict()["window"]["end"] == completion
    assert {
        receipt.as_dict()["pit"]["as_of_cutoff"]
        for receipt in result.source_receipts
    } == {completion}


def test_sector_archive_default_reader_ignores_newer_partial_group(tmp_path) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    full_key = f"sha256:{'a' * 64}"
    partial_key = f"sha256:{'b' * 64}"
    full_group = _sealed_group(full_key)
    full_group["captured_at"] = "2026-08-06T16:00:00+08:00"
    partial_group = _sealed_group(partial_key)
    partial_group["captured_at"] = "2026-08-06T17:00:00+08:00"
    partial_group["requested_route_ids"] = ["tushare.sector_fundamentals"]
    store.get_or_capture(full_key, lambda: full_group)
    store.get_or_capture(partial_key, lambda: partial_group)

    assert store.load_group(AS_OF)["capture_key"] == full_key
    assert store.load_group(
        AS_OF, required_route_ids=("tushare.sector_fundamentals",)
    )["capture_key"] == partial_key


def test_store_selects_role_scoped_group_by_route_and_security(tmp_path) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")

    def scoped_group(
        capture_key: str, *, agent_id: str, security_code: str, captured_at: str
    ) -> dict[str, Any]:
        group = _sealed_group(capture_key)
        group["captured_at"] = captured_at
        group["requested_route_ids"] = [
            "tushare.sector_fundamentals",
            "tushare.sector_market",
        ]
        group["capture_scope"] = {
            "sector_agent_ids": [agent_id],
            "security_codes": [security_code],
            "etf_codes": [],
        }
        group["capture_scope_hash"] = sector_archive.canonical_hash(
            group["capture_scope"]
        )
        return group

    semiconductor, _ = store.get_or_capture(
        "semiconductor",
        lambda: scoped_group(
            "semiconductor",
            agent_id="semiconductor",
            security_code="000001.SZ",
            captured_at="2026-08-06T16:00:00+08:00",
        ),
    )
    technology, _ = store.get_or_capture(
        "technology",
        lambda: scoped_group(
            "technology",
            agent_id="technology",
            security_code="000002.SZ",
            captured_at="2026-08-06T16:01:00+08:00",
        ),
    )
    legacy_group = _sealed_group("legacy")
    legacy_group.pop("capture_scope")
    legacy_group.pop("capture_scope_hash")
    legacy_group["captured_at"] = "2026-08-06T16:02:00+08:00"
    legacy_group["requested_route_ids"] = [
        "tushare.sector_fundamentals",
        "tushare.sector_market",
    ]
    legacy, _ = store.get_or_capture("legacy", lambda: legacy_group)
    assert "capture_scope" not in legacy

    with pytest.raises(FileNotFoundError):
        store.load_group(AS_OF)
    assert store.load_group(
        AS_OF,
        required_route_ids=("tushare.sector_market",),
        required_security_code="000001.SZ",
    ) == semiconductor
    assert store.load_group(
        AS_OF,
        required_route_ids=("tushare.sector_fundamentals",),
        required_security_code="000002.SZ",
    ) == technology
    with pytest.raises(FileNotFoundError):
        store.load_group(
            AS_OF,
            required_route_ids=("tushare.sector_market",),
            required_security_code="000003.SZ",
        )


def test_sector_core_snapshots_publish_exact_builds_and_replay(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    snapshots = {
        "semiconductor": {
            "snapshot_hash": sector_archive.canonical_hash(
                {"role": "semiconductor"}
            )
        }
    }
    writes: list[tuple[str, str]] = []

    monkeypatch.setattr(
        sector_archive,
        "_build_capture_group",
        lambda *_args, capture_key, requested_agent_ids, **_kwargs: _sealed_group(
            capture_key, tuple(requested_agent_ids)
        ),
    )
    monkeypatch.setattr(
        sector_archive, "compile_sector_archive_group", lambda _group: snapshots
    )

    def write_sector(**kwargs):
        writes.append(("sector", kwargs["role"]))
        return kwargs["snapshot"]

    monkeypatch.setattr(
        sector_archive, "write_registered_sector_snapshot", write_sector
    )
    archived = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )
    first = compile_sector_relationship_core_snapshots(
        archived,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )
    replay = compile_sector_relationship_core_snapshots(
        archived,
        ledger=ledger,
        output_root=tmp_path / "snapshots",
    )

    assert set(first.snapshots) == {"semiconductor"}
    assert len(first.build_receipts) == 1
    assert [row.receipt_hash for row in replay.build_receipts] == [
        row.receipt_hash for row in first.build_receipts
    ]
    assert writes == [("sector", "semiconductor"), ("sector", "semiconductor")]
    route_hashes = {
        receipt.as_dict()["identity"]["route_id"]: receipt.receipt_hash
        for receipt in archived.source_receipts
    }
    semiconductor = ledger.ready_snapshot_build_receipts(
        agent_id="semiconductor",
        stage="semiconductor",
        tool_id="get_sector_research_snapshot",
        as_of=AS_OF,
    )[0].as_dict()
    assert semiconductor["source_receipt_hashes"] == sorted(
        [
            route_hashes["tushare.sector_fundamentals"],
            route_hashes["tushare.sector_market"],
        ]
    )
    assert ledger.row_counts()["snapshot_build_receipts"] == 1


def test_sector_archive_same_key_concurrency_runs_one_builder(tmp_path) -> None:
    assert sector_archive._LOCK_TIMEOUT_SECONDS == 9 * 60 * 60
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    capture_key = f"sha256:{'a' * 64}"

    def build() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return _sealed_group(capture_key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.get_or_capture, capture_key, build)
        assert entered.wait(timeout=5)
        second = pool.submit(store.get_or_capture, capture_key, build)
        assert not second.done()
        release.set()
        first_group, first_hit = first.result(timeout=5)
        second_group, second_hit = second.result(timeout=5)

    assert calls == 1
    assert first_group == second_group
    assert {first_hit, second_hit} == {False, True}
    assert store.row_count() == 1


def test_sector_archive_transport_failure_publishes_no_source(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")

    def fail(*_args, **_kwargs):
        raise ConnectionError("private vendor detail")

    monkeypatch.setattr(sector_archive, "_build_capture_group", fail)
    result = archive_sector_relationship(
        lambda *_args, **_kwargs: None,
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )

    assert result.source_receipts == ()
    assert result.coverage_receipt.as_dict()["coverage_complete"] is False
    assert result.coverage_receipt.as_dict()["blocker_codes"] == ["TRANSPORT_FAILED"]
    assert store.row_count() == 0
    counts = ledger.row_counts()
    assert counts["source_capture_receipts"] == 0
    assert counts["route_coverage_receipts"] == 1
    assert counts["snapshot_build_receipts"] == 0


def test_compiler_failure_preserves_raw_capture_for_zero_transport_replay(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    calls = {"builder": 0}

    def build(*_args, capture_key: str, requested_agent_ids, **_kwargs):
        calls["builder"] += 1
        return _sealed_group(capture_key, tuple(requested_agent_ids))

    monkeypatch.setattr(sector_archive, "_build_capture_group", build)
    monkeypatch.setattr(
        sector_archive,
        "compile_sector_archive_group",
        lambda _group: (_ for _ in ()).throw(
            DataVendorUnavailable("redacted deterministic compiler failure")
        ),
    )
    first = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )

    assert first.source_receipts == ()
    assert first.coverage_receipt.as_dict()["blocker_codes"] == [
        "INCOMPLETE_COVERAGE"
    ]
    assert store.row_count() == 1
    assert calls["builder"] == 1

    monkeypatch.setattr(
        sector_archive,
        "compile_sector_archive_group",
        lambda _group: {"semiconductor": {"snapshot_hash": f"sha256:{'c' * 64}"}},
    )
    second = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )

    assert second.cache_hit is True
    assert len(second.source_receipts) == 2
    assert calls["builder"] == 1
    assert store.row_count() == 1


def test_sector_archive_preserves_sanitized_endpoint_failure_code(
    tmp_path, monkeypatch
) -> None:
    store = SectorArchiveStore(tmp_path / "sector.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "ledger.sqlite3")
    reason_code = "TUSHARE_TOP10_HOLDERS_UNAVAILABLE"

    monkeypatch.setattr(
        sector_archive,
        "_build_capture_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DataVendorUnavailable(
                "vendor text and request parameters must stay private",
                reason_code=reason_code,
            )
        ),
    )
    result = archive_sector_relationship(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport")),
        as_of_date=AS_OF,
        cutoff_at=CUTOFF,
        requested_agent_ids=("semiconductor",),
        store=store,
        ledger=ledger,
    )

    payload = result.coverage_receipt.as_dict()
    assert payload["blocker_codes"] == [reason_code]
    assert "vendor text" not in str(payload)
    assert store.row_count() == 0


def test_sector_archive_rejects_preclose_and_next_day_cutoffs(tmp_path) -> None:
    for index, cutoff in enumerate(
        ("2026-08-06T15:00:00+08:00", "2026-08-07T00:00:00+08:00")
    ):
        result = archive_sector_relationship(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("transport must not run")
            ),
            as_of_date=AS_OF,
            cutoff_at=cutoff,
            requested_agent_ids=("semiconductor",),
            store=SectorArchiveStore(tmp_path / f"sector-{index}.sqlite3"),
            ledger=AgentDataMaterializationLedger(
                tmp_path / f"ledger-{index}.sqlite3"
            ),
        )

        assert result.source_receipts == ()
        assert result.coverage_receipt.as_dict()["blocker_codes"] == [
            "MARKET_SESSION_INCOMPLETE"
        ]


def test_incremental_pagination_retries_empty_and_rejects_hidden_rows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sector_archive.wall_time, "sleep", lambda _seconds: None)
    calls = 0

    def transient_fetch(endpoint: str, **params: Any):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        return [_endpoint_row(endpoint, params)]

    rows, page_count, duplicates = sector_archive._paginate_incremental(
        transient_fetch,
        "income",
        {"ts_code": "000001.SZ", "end_date": "20260806"},
        confirm_terminal=False,
    )
    assert len(rows) == 1
    assert page_count == 2
    assert duplicates == 0

    def hidden_fetch(endpoint: str, **params: Any):
        return [_endpoint_row(endpoint, params)]

    try:
        sector_archive._paginate_incremental(
            hidden_fetch,
            "moneyflow",
            {"trade_date": "20260806"},
            confirm_terminal=True,
        )
    except ASharePaginationError:
        pass
    else:
        raise AssertionError("hidden rows after a short page must fail closed")


def test_incremental_pagination_redacts_vendor_failure_by_endpoint() -> None:
    def failed_fetch(_endpoint: str, **_params: Any):
        raise DataVendorUnavailable("vendor text and request parameters must stay private")

    try:
        sector_archive._paginate_incremental(
            failed_fetch,
            "top10_holders",
            {"ts_code": "000001.SZ", "end_date": "20260806"},
            confirm_terminal=False,
        )
    except DataVendorUnavailable as exc:
        assert exc.reason_code == "TUSHARE_TOP10_HOLDERS_UNAVAILABLE"
        assert str(exc) == "Tushare endpoint 'top10_holders' unavailable"
    else:
        raise AssertionError("vendor failure must remain fail closed")


def test_sealed_batch_records_the_pagination_proof_actually_used() -> None:
    def fetch(endpoint: str, **params: Any):
        if int(params.get("offset", 0)):
            return []
        return [_endpoint_row(endpoint, params)]

    terminal, _duplicates, _pages = sector_archive._seal_batch(
        endpoint="moneyflow",
        requests=({"trade_date": "20260806"},),
        request_contract={"end_date": AS_OF},
        fetch=fetch,
        captured_at="2026-08-06T17:00:00+08:00",
        require_each_nonempty=True,
        confirm_terminal=True,
    )
    capped, _duplicates, _pages = sector_archive._seal_batch(
        endpoint="income",
        requests=({"ts_code": "000001.SZ", "end_date": "20260806"},),
        request_contract={"end_date": AS_OF},
        fetch=fetch,
        captured_at="2026-08-06T17:00:00+08:00",
        require_each_nonempty=False,
        confirm_terminal=False,
    )

    assert terminal["pagination_policy"] == "OFFSET_WITH_TERMINAL_CONFIRMATION"
    assert capped["pagination_policy"] == "OFFSET_UNTIL_SHORT_PAGE_OFFICIAL_CAP"


def test_moneyflow_must_match_exact_daily_ticker_and_session() -> None:
    daily = {
        "endpoint": "daily",
        "rows": [{"trade_date": "20260806", "ts_code": "000001.SZ"}],
    }
    moneyflow = {
        "endpoint": "moneyflow",
        "rows": [{"trade_date": "20260806", "ts_code": "000002.SZ"}],
    }

    try:
        sector_archive._validate_moneyflow_exact_closure(
            daily_batch=daily,
            moneyflow_batch=moneyflow,
            tickers=("000001.SZ",),
            sessions=("20260806",),
        )
    except AShareSchemaError:
        pass
    else:
        raise AssertionError("moneyflow outside exact daily authority must fail closed")


def test_incremental_pagination_rejects_schema_drift() -> None:
    try:
        sector_archive._paginate_incremental(
            lambda *_args, **_kwargs: [{"ts_code": "000001.SZ"}],
            "moneyflow",
            {"trade_date": "20260806"},
            confirm_terminal=False,
        )
    except AShareSchemaError:
        pass
    else:
        raise AssertionError("missing frozen columns must fail closed")


def test_fund_nav_allows_optional_total_netasset_column_to_be_absent() -> None:
    def fetch(endpoint: str, **params: Any):
        if int(params.get("offset", 0)):
            return []
        row = _endpoint_row(endpoint, params)
        row.pop("total_netasset")
        return [row]

    rows, _, _ = sector_archive._paginate_incremental(
        fetch,
        "fund_nav",
        {
            "ts_code": "159865.SZ",
            "start_date": "20230713",
            "end_date": "20260717",
        },
        confirm_terminal=True,
    )

    assert rows[0]["ts_code"] == "159865.SZ"
    assert "total_netasset" not in rows[0]


def test_sealed_batch_rejects_rows_outside_request() -> None:
    def fetch(endpoint: str, **params: Any):
        row = _endpoint_row(endpoint, params)
        row["ts_code"] = "000002.SZ"
        return [row]

    try:
        sector_archive._seal_batch(
            endpoint="income",
            requests=({"ts_code": "000001.SZ", "end_date": "20260806"},),
            request_contract={"end_date": AS_OF},
            fetch=fetch,
            captured_at="2026-08-06T17:00:00+08:00",
            require_each_nonempty=False,
            confirm_terminal=False,
        )
    except AShareSchemaError:
        pass
    else:
        raise AssertionError("rows outside a requested security must fail closed")


def _endpoint_row(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    row = {
        field: 1.0
        for field in PREFLIGHT_ENDPOINT_CHECKS[endpoint]["expected_columns"]
    }
    if "ts_code" in row:
        row["ts_code"] = params.get(
            "ts_code", "510001.SH" if endpoint.startswith("fund_") else "000001.SZ"
        )
    for field in ("trade_date", "ann_date", "f_ann_date", "end_date"):
        if field in row:
            row[field] = params.get("trade_date", "20260806")
    if endpoint == "trade_cal":
        row.update({"cal_date": "20260806", "is_open": 1, "exchange": "SSE"})
    elif endpoint == "index_member_all":
        row.update(
            {
                "l1_code": "801010.SI",
                "l2_code": "801011.SI",
                "l3_code": "850111.SI",
                "in_date": "20200101",
                "out_date": "",
                "is_new": "Y",
            }
        )
    elif endpoint == "fund_basic":
        row.update(
            {
                "ts_code": "510001.SH",
                "market": "E",
                "status": "L",
                "list_date": "20200101",
                "delist_date": None,
            }
        )
    elif endpoint == "top10_holders":
        row.update({"holder_name": "institution-a", "hold_ratio": 2.5})
    return row


def test_membership_batches_runs_vendor_fetches_on_caller_thread() -> None:
    caller_id = threading.get_ident()
    calls: list[tuple[int, str, dict[str, Any]]] = []

    def fetch(endpoint: str, **params: Any) -> list[dict[str, Any]]:
        calls.append((threading.get_ident(), endpoint, dict(params)))
        row = _endpoint_row(endpoint, params)
        row.update(
            {
                "l2_code": params["l2_code"],
                "l3_code": "850812.SI",
                "is_new": params["is_new"],
            }
        )
        return [row, dict(row)] if params["is_new"] == "Y" else [row]

    batches, duplicates, pages = sector_archive._membership_batches(
        fetch,
        "2026-08-06T15:01:00+08:00",
        requested_agent_ids=("semiconductor",),
    )

    assert {thread_id for thread_id, _endpoint, _params in calls} == {caller_id}
    assert len(calls) == 2
    assert len(batches) == 2
    assert [params for _thread_id, _endpoint, params in calls] == [
        {"l2_code": "801081.SI", "is_new": "Y"},
        {"l2_code": "801081.SI", "is_new": "N"},
    ]
    assert all(
        "offset" not in params and "limit" not in params
        for _, _, params in calls
    )
    assert duplicates == 1
    assert pages == 2
    assert {
        batch["request"]["classification_code"] for batch in batches
    } == {"801081.SI"}
    assert {batch["request"]["parameter"] for batch in batches} == {"l2_code"}
    assert all(
        batch["request"]["covered_l3_codes"]
        == [
            "850812.SI",
            "850813.SI",
            "850814.SI",
            "850815.SI",
            "850816.SI",
            "850817.SI",
            "850818.SI",
        ]
        for batch in batches
    )

    def capped_fetch(endpoint: str, **params: Any) -> list[dict[str, Any]]:
        row = _endpoint_row(endpoint, params)
        row.update(
            {
                "l2_code": params["l2_code"],
                "l3_code": "850812.SI",
                "is_new": params["is_new"],
            }
        )
        return [{**row, "ts_code": f"{index:06d}.SZ"} for index in range(2000)]

    with pytest.raises(ASharePaginationError, match="official cap"):
        sector_archive._membership_batches(
            capped_fetch,
            "2026-08-06T15:01:00+08:00",
            requested_agent_ids=("semiconductor",),
        )




def test_capture_group_executes_registered_incremental_routes(
    monkeypatch,
) -> None:
    plan = {
        "sector_agent_id": "semiconductor",
        "query_plan_hash": f"sha256:{'b' * 64}",
        "branches": [
            {
                "endpoint": "index_member_all",
                "parameter": "l3_code",
                "classification_code": "850111.SI",
                "is_new": "Y",
            }
        ],
    }
    monkeypatch.setitem(
        sector_archive.SECTOR_UNIVERSE_MANIFEST,
        "membership_query_plans",
        [plan],
    )
    monkeypatch.setattr(
        sector_archive,
        "_authoritative_etf_codes",
        lambda role, direction_id, _as_of: (
            ["510001.SH"]
            if role == "semiconductor" and direction_id == "chip_design"
            else []
        ),
    )
    moments = iter(
        (
            sector_archive._timestamp("2026-08-06T15:01:00+08:00", "test"),
            sector_archive._timestamp("2026-08-06T15:02:00+08:00", "test"),
        )
    )
    monkeypatch.setattr(sector_archive, "_capture_now", lambda: next(moments))
    calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(endpoint: str, **params: Any):
        calls.append((endpoint, dict(params)))
        if int(params.get("offset", 0)):
            return []
        if endpoint == "stock_basic" and params["ts_code"] == "002257.SZ":
            return []
        if endpoint == "trade_cal":
            start = sector_archive.date.fromisoformat(
                f"{params['start_date'][:4]}-{params['start_date'][4:6]}-"
                f"{params['start_date'][6:]}"
            )
            end = sector_archive.date.fromisoformat(
                f"{params['end_date'][:4]}-{params['end_date'][4:6]}-"
                f"{params['end_date'][6:]}"
            )
            return [
                {
                    **_endpoint_row(endpoint, params),
                    "cal_date": day.strftime("%Y%m%d"),
                    "is_open": 1,
                }
                for day in (
                    start + sector_archive.timedelta(days=offset)
                    for offset in range((end - start).days + 1)
                )
            ]
        row = _endpoint_row(endpoint, params)
        if endpoint == "index_member_all":
            return [row, {**row, "ts_code": "002257.SZ"}]
        return [row]

    group = _build_capture_group(
        fetch,
        as_of_date=sector_archive.date.fromisoformat(AS_OF),
        cutoff_at=CUTOFF,
        capture_key=f"sha256:{'d' * 64}",
        requested_agent_ids=("semiconductor",),
    )

    assert {batch["endpoint"] for batch in group["batches"]} == {
        "stock_basic",
        "trade_cal",
        "daily",
        "adj_factor",
        "suspend_d",
        "daily_basic",
        "index_member_all",
        "moneyflow",
        "income",
        "balancesheet",
        "cashflow",
        "fund_basic",
        "fund_daily",
        "fund_adj",
        "fund_share",
        "fund_nav",
        "fund_portfolio",
    }
    assert group["page_count"] == len(calls)
    assert "compiled_snapshot_hashes" not in group
    stock_basic = next(
        batch for batch in group["batches"] if batch["endpoint"] == "stock_basic"
    )
    assert stock_basic["request"]["ts_codes"] == ["000001.SZ", "002257.SZ"]
    assert {row["ts_code"] for row in stock_basic["rows"]} == {"000001.SZ"}
    assert stock_basic["query_count"] == stock_basic["completed_query_count"] == 2
    assert [
        params for endpoint, params in calls if endpoint == "stock_basic"
    ] == [{"ts_code": "000001.SZ"}, {"ts_code": "002257.SZ"}]
    assert all(
        params.get("ts_code") != "002257.SZ"
        for endpoint, params in calls
        if endpoint not in {"index_member_all", "stock_basic"}
    )
    assert group["capture_scope"]["security_codes"] == ["000001.SZ"]
    assert all(
        batch.get("coverage_ratio") == 1.0
        for batch in group["batches"]
        if batch["endpoint"] not in {"stock_basic", "trade_cal", "daily"}
    )
    policies = {
        batch["endpoint"]: batch["pagination_policy"]
        for batch in group["batches"]
        if "pagination_policy" in batch
    }
    assert policies == {
        "cashflow": "OFFSET_UNTIL_SHORT_PAGE_OFFICIAL_CAP",
        "balancesheet": "OFFSET_UNTIL_SHORT_PAGE_OFFICIAL_CAP",
        "fund_basic": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "fund_daily": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "fund_adj": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "fund_share": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "fund_nav": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "fund_portfolio": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "income": "OFFSET_UNTIL_SHORT_PAGE_OFFICIAL_CAP",
        "index_member_all": "OFFSET_WITH_TERMINAL_CONFIRMATION",
        "moneyflow": "OFFSET_WITH_TERMINAL_CONFIRMATION",
    }


def test_sector_market_capture_queries_role_tickers_and_etfs_exactly(
    monkeypatch,
) -> None:
    plan = {
        "sector_agent_id": "semiconductor",
        "query_plan_hash": f"sha256:{'b' * 64}",
        "branches": [
            {
                "endpoint": "index_member_all",
                "parameter": "l3_code",
                "classification_code": "850111.SI",
                "is_new": "Y",
            }
        ],
    }
    monkeypatch.setitem(
        sector_archive.SECTOR_UNIVERSE_MANIFEST,
        "membership_query_plans",
        [plan],
    )
    monkeypatch.setattr(
        sector_archive,
        "_authoritative_etf_codes",
        lambda role, _direction_id, _as_of: (
            ["510001.SH"] if role == "semiconductor" else ["510999.SH"]
        ),
    )
    moments = iter(
        (
            sector_archive._timestamp("2026-08-06T15:01:00+08:00", "test"),
            sector_archive._timestamp("2026-08-06T15:02:00+08:00", "test"),
        )
    )
    monkeypatch.setattr(sector_archive, "_capture_now", lambda: next(moments))
    calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(endpoint: str, **params: Any):
        calls.append((endpoint, dict(params)))
        if int(params.get("offset", 0)):
            return []
        if endpoint == "trade_cal":
            current = sector_archive.datetime.strptime(
                str(params["start_date"]), "%Y%m%d"
            ).date()
            end = sector_archive.datetime.strptime(
                str(params["end_date"]), "%Y%m%d"
            ).date()
            rows = []
            while current <= end:
                cal_date = current.strftime("%Y%m%d")
                rows.append(
                    {
                        "exchange": "SSE",
                        "cal_date": cal_date,
                        "is_open": 1,
                        "pretrade_date": cal_date,
                    }
                )
                current += sector_archive.timedelta(days=1)
            return rows
        return [_endpoint_row(endpoint, params)]

    group = _build_capture_group(
        fetch,
        as_of_date=sector_archive.date.fromisoformat(AS_OF),
        cutoff_at=CUTOFF,
        capture_key=f"sha256:{'d' * 64}",
        requested_route_ids=("tushare.sector_market",),
        requested_agent_ids=("semiconductor",),
    )

    moneyflow_calls = [params for endpoint, params in calls if endpoint == "moneyflow"]
    fund_calls = [
        params
        for endpoint, params in calls
        if endpoint
        in {
            "fund_basic",
            "fund_daily",
            "fund_adj",
            "fund_share",
            "fund_nav",
            "fund_portfolio",
        }
    ]
    assert {params["ts_code"] for params in moneyflow_calls} == {"000001.SZ"}
    assert all("trade_date" not in params for params in moneyflow_calls)
    assert {params["ts_code"] for params in fund_calls} == {"510001.SH"}
    assert "510999.SH" not in str(calls)
    assert group["capture_scope"]["etf_codes"] == ["510001.SH"]
