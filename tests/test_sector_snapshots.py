from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.sector_snapshots import (
    _canonical_hash,
    _load_sector_universe_manifest,
    load_sector_snapshot,
    validate_sector_snapshot,
)
from mosaic.dataflows.sector_snapshots import (
    SECTOR_REQUIRED_SOURCE_ENDPOINTS,
    SECTOR_UNIVERSE_MANIFEST,
    TUSHARE_ENDPOINT_PREFLIGHT_PATH,
    write_registered_sector_snapshot,
)
from scripts.build_structured_smoke_fixtures import _build_sector_snapshots


AS_OF = "2026-07-17"
ROLE = "semiconductor"


@pytest.fixture
def snapshot(tmp_path: Path) -> dict[str, Any]:
    _build_sector_snapshots(tmp_path, date.fromisoformat(AS_OF))
    return json.loads(
        (tmp_path / "sector_snapshots" / AS_OF / f"{ROLE}.json").read_text(
            encoding="utf-8"
        )
    )


def _rehash_metric(
    snapshot: dict[str, Any], card_index: int, metric_index: int
) -> None:
    metric = snapshot["direction_cards"][card_index]["metrics"][metric_index]
    metric["metric_observation_hash"] = _canonical_hash(
        {
            key: value
            for key, value in metric.items()
            if key != "metric_observation_hash"
        }
    )
    _rehash_card_and_snapshot(snapshot, card_index)


def _rehash_card_and_snapshot(snapshot: dict[str, Any], card_index: int) -> None:
    card = snapshot["direction_cards"][card_index]
    card["direction_card_hash"] = _canonical_hash(
        {key: value for key, value in card.items() if key != "direction_card_hash"}
    )
    _rehash_snapshot(snapshot)


def _rehash_snapshot(snapshot: dict[str, Any]) -> None:
    snapshot["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )


def _rehash_security_scoring_rows(snapshot: dict[str, Any]) -> None:
    for row in snapshot["security_scoring_rows"]:
        row["security_scoring_row_hash"] = _canonical_hash(
            {
                key: value
                for key, value in row.items()
                if key != "security_scoring_row_hash"
            }
        )
    snapshot["security_scoring_rows_hash"] = _canonical_hash(
        snapshot["security_scoring_rows"]
    )
    _rehash_snapshot(snapshot)


def test_sector_hash_matches_json_stringify_integral_number_semantics() -> None:
    assert _canonical_hash(
        {"coverage_ratio": 1.0, "amounts": [0.0, 1_000.0]}
    ) == _canonical_hash(
        {"coverage_ratio": 1, "amounts": [0, 1_000]}
    )

    with pytest.raises(ValueError, match="non-finite"):
        _canonical_hash({"invalid": float("inf")})

    assert _canonical_hash({"tiny_return": 1e-7}) == (
        "sha256:82bce345d5bc24f25c040adab90dbfb1430cabe22c6932c8de244e0ccf7947e8"
    )


def test_sector_snapshot_accepts_strict_pit_fixture(snapshot: dict[str, Any]) -> None:
    accepted = validate_sector_snapshot(snapshot, ROLE, AS_OF)
    assert accepted["schema_version"] == "sector_research_snapshot_v4"
    assert len(accepted["direction_ids"]) >= 3
    assert accepted["eligible_count"] == len(accepted["eligible_security_universe"])


def test_sector_manifest_rejects_rehashed_nested_contract_drift(tmp_path: Path) -> None:
    manifest = copy.deepcopy(SECTOR_UNIVERSE_MANIFEST)
    manifest["flow_coverage_contract"]["aggregation"] = "UNREGISTERED_AGGREGATION"
    manifest["manifest_hash"] = _canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    path = tmp_path / "sector-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="flow_coverage_contract hash mismatch"):
        _load_sector_universe_manifest(path)

    scoring_drift = copy.deepcopy(SECTOR_UNIVERSE_MANIFEST)
    scoring = scoring_drift["security_scoring_contract"]
    scoring["required_observation_count"] = 19
    scoring["scoring_contract_hash"] = _canonical_hash(
        {key: value for key, value in scoring.items() if key != "scoring_contract_hash"}
    )
    scoring_drift["manifest_hash"] = _canonical_hash(
        {key: value for key, value in scoring_drift.items() if key != "manifest_hash"}
    )
    path.write_text(json.dumps(scoring_drift), encoding="utf-8")

    with pytest.raises(
        RuntimeError, match="security scoring contract semantics mismatch"
    ):
        _load_sector_universe_manifest(path)

    metric_drift = copy.deepcopy(SECTOR_UNIVERSE_MANIFEST)
    metric_drift["direction_metric_registry"][0]["minimum_observations"] = 7
    metric_drift["direction_metric_registry_hash"] = _canonical_hash(
        metric_drift["direction_metric_registry"]
    )
    metric_drift["manifest_hash"] = _canonical_hash(
        {key: value for key, value in metric_drift.items() if key != "manifest_hash"}
    )
    path.write_text(json.dumps(metric_drift), encoding="utf-8")

    with pytest.raises(RuntimeError, match="metric contract hash mismatch"):
        _load_sector_universe_manifest(path)


def test_sector_snapshot_rejects_future_metric_vintage(
    snapshot: dict[str, Any],
) -> None:
    metric = snapshot["direction_cards"][0]["metrics"][0]
    metric["released_at"] = "2026-07-18"
    metric["vintage_at"] = "2026-07-18"
    _rehash_metric(snapshot, 0, 0)

    with pytest.raises(DataVendorUnavailable, match="as_of"):
        validate_sector_snapshot(snapshot, ROLE, AS_OF)


def test_sector_snapshot_rejects_missing_or_duplicate_members(
    snapshot: dict[str, Any],
) -> None:
    missing = copy.deepcopy(snapshot)
    missing["eligible_security_universe"] = missing["eligible_security_universe"][1:]
    missing["eligible_count"] = len(missing["eligible_security_universe"])
    missing["membership_hash"] = _canonical_hash(missing["eligible_security_universe"])
    _rehash_snapshot(missing)
    with pytest.raises(DataVendorUnavailable, match="every registered direction"):
        validate_sector_snapshot(missing, ROLE, AS_OF)

    duplicate = copy.deepcopy(snapshot)
    duplicate["eligible_security_universe"].append(
        copy.deepcopy(duplicate["eligible_security_universe"][0])
    )
    duplicate["eligible_security_universe"].sort(
        key=lambda row: (row["direction_id"], row["ts_code"])
    )
    duplicate["eligible_count"] = len(duplicate["eligible_security_universe"])
    duplicate["membership_hash"] = _canonical_hash(
        duplicate["eligible_security_universe"]
    )
    _rehash_snapshot(duplicate)
    with pytest.raises(DataVendorUnavailable, match="duplicate sector security"):
        validate_sector_snapshot(duplicate, ROLE, AS_OF)


def test_sector_snapshot_rejects_wrong_etf_direction_binding(
    snapshot: dict[str, Any],
) -> None:
    metric_index = next(
        index
        for index, metric in enumerate(snapshot["direction_cards"][0]["metrics"])
        if metric["metric_family"] == "ETF_CONFIRMATION"
    )
    metric = snapshot["direction_cards"][0]["metrics"][metric_index]
    metric["etf_family_id"] = "sector-etf:semiconductor:wrong-direction"
    _rehash_metric(snapshot, 0, metric_index)

    with pytest.raises(DataVendorUnavailable, match="ETF metric family binding"):
        validate_sector_snapshot(snapshot, ROLE, AS_OF)


def test_sector_snapshot_rejects_evidence_closure_and_record_hash(
    snapshot: dict[str, Any],
) -> None:
    missing_evidence = copy.deepcopy(snapshot)
    missing_evidence["evidence_catalog"] = missing_evidence["evidence_catalog"][1:]
    _rehash_snapshot(missing_evidence)
    with pytest.raises(DataVendorUnavailable, match="evidence closure"):
        validate_sector_snapshot(missing_evidence, ROLE, AS_OF)

    bad_hash = copy.deepcopy(snapshot)
    bad_hash["evidence_catalog"][0]["content_hash"] = f"sha256:{'f' * 64}"
    _rehash_snapshot(bad_hash)
    with pytest.raises(DataVendorUnavailable, match="evidence_record_hash mismatch"):
        validate_sector_snapshot(bad_hash, ROLE, AS_OF)


def test_sector_snapshot_rejects_required_metric_below_coverage(
    snapshot: dict[str, Any],
) -> None:
    metric = snapshot["direction_cards"][0]["metrics"][0]
    assert metric["required_for_direction_readiness"] is True
    metric["observed_count"] = 0
    metric["coverage_ratio"] = 0.0
    _rehash_metric(snapshot, 0, 0)

    with pytest.raises(DataVendorUnavailable, match="value/coverage readiness"):
        validate_sector_snapshot(snapshot, ROLE, AS_OF)


def test_sector_snapshot_rejects_bad_membership_hash_and_one_direction(
    snapshot: dict[str, Any],
) -> None:
    bad_hash = copy.deepcopy(snapshot)
    bad_hash["membership_hash"] = f"sha256:{'0' * 64}"
    _rehash_snapshot(bad_hash)
    with pytest.raises(DataVendorUnavailable, match="membership_hash mismatch"):
        validate_sector_snapshot(bad_hash, ROLE, AS_OF)

    one_direction = copy.deepcopy(snapshot)
    one_direction["direction_ids"] = one_direction["direction_ids"][:1]
    _rehash_snapshot(one_direction)
    with pytest.raises(DataVendorUnavailable, match="direction registry mismatch"):
        validate_sector_snapshot(one_direction, ROLE, AS_OF)


def test_sector_snapshot_rejects_stale_membership_and_market_metric(
    snapshot: dict[str, Any],
) -> None:
    stale_membership = copy.deepcopy(snapshot)
    stale_membership["membership_observed_at"] = "2026-07-01"
    _rehash_snapshot(stale_membership)
    with pytest.raises(DataVendorUnavailable, match="membership_observed_at is stale"):
        validate_sector_snapshot(stale_membership, ROLE, AS_OF)

    stale_metric = copy.deepcopy(snapshot)
    card_index = 0
    metric_index = next(
        index
        for index, metric in enumerate(
            stale_metric["direction_cards"][card_index]["metrics"]
        )
        if metric["metric_family"] == "BASKET_PRICE_TREND"
    )
    metric = stale_metric["direction_cards"][card_index]["metrics"][metric_index]
    metric["observation_date"] = "2026-07-01"
    metric["released_at"] = "2026-07-01"
    metric["vintage_at"] = "2026-07-01"
    _rehash_metric(stale_metric, card_index, metric_index)
    with pytest.raises(DataVendorUnavailable, match="vintage_at is stale"):
        validate_sector_snapshot(stale_metric, ROLE, AS_OF)


def test_sector_snapshot_rejects_security_scoring_lookahead_and_hash_tamper(
    snapshot: dict[str, Any],
) -> None:
    lookahead = copy.deepcopy(snapshot)
    row = lookahead["security_scoring_rows"][0]
    row["observation_date"] = "2026-07-18"
    row["released_at"] = "2026-07-18"
    row["vintage_at"] = "2026-07-18"
    _rehash_security_scoring_rows(lookahead)
    with pytest.raises(DataVendorUnavailable, match="as_of"):
        validate_sector_snapshot(lookahead, ROLE, AS_OF)

    tampered = copy.deepcopy(snapshot)
    tampered["security_scoring_rows"][0]["median_amount_20d_cny"] += 1
    tampered["security_scoring_rows_hash"] = _canonical_hash(
        tampered["security_scoring_rows"]
    )
    _rehash_snapshot(tampered)
    with pytest.raises(
        DataVendorUnavailable, match="security_scoring_row_hash mismatch"
    ):
        validate_sector_snapshot(tampered, ROLE, AS_OF)


def test_sector_snapshot_requires_one_scoring_row_per_eligible_security(
    snapshot: dict[str, Any],
) -> None:
    missing = copy.deepcopy(snapshot)
    missing["security_scoring_rows"] = missing["security_scoring_rows"][1:]
    missing["security_scoring_rows_hash"] = _canonical_hash(
        missing["security_scoring_rows"]
    )
    _rehash_snapshot(missing)
    with pytest.raises(DataVendorUnavailable, match="one-to-one"):
        validate_sector_snapshot(missing, ROLE, AS_OF)

    duplicate = copy.deepcopy(snapshot)
    duplicate["security_scoring_rows"].append(
        copy.deepcopy(duplicate["security_scoring_rows"][0])
    )
    duplicate["security_scoring_rows"].sort(
        key=lambda row: (row["direction_id"], row["ts_code"])
    )
    duplicate["security_scoring_rows_hash"] = _canonical_hash(
        duplicate["security_scoring_rows"]
    )
    _rehash_snapshot(duplicate)
    with pytest.raises(DataVendorUnavailable, match="one-to-one"):
        validate_sector_snapshot(duplicate, ROLE, AS_OF)


def test_sector_snapshot_allows_only_explicit_data_unavailability(
    snapshot: dict[str, Any],
) -> None:
    unavailable = copy.deepcopy(snapshot)
    row = unavailable["security_scoring_rows"][0]
    row.update(
        {
            "availability_status": "UNAVAILABLE",
            "unavailability_reason": "INSUFFICIENT_PIT_OBSERVATIONS",
            "adjusted_return_20d": None,
            "realized_volatility_20d": None,
            "median_amount_20d_cny": None,
            "net_moneyflow_20d_cny": None,
            "observation_count": 10,
            "coverage_ratio": 0.5,
        }
    )
    _rehash_security_scoring_rows(unavailable)
    assert (
        validate_sector_snapshot(unavailable, ROLE, AS_OF)["security_scoring_rows"][0][
            "availability_status"
        ]
        == "UNAVAILABLE"
    )

    invalid = copy.deepcopy(unavailable)
    invalid["security_scoring_rows"][0]["unavailability_reason"] = None
    _rehash_security_scoring_rows(invalid)
    with pytest.raises(DataVendorUnavailable, match="null metric semantics"):
        validate_sector_snapshot(invalid, ROLE, AS_OF)

    incomplete_available = copy.deepcopy(snapshot)
    incomplete_available["security_scoring_rows"][0]["observation_count"] = 18
    incomplete_available["security_scoring_rows"][0]["coverage_ratio"] = 0.9
    _rehash_security_scoring_rows(incomplete_available)
    with pytest.raises(DataVendorUnavailable, match="fails readiness"):
        validate_sector_snapshot(incomplete_available, ROLE, AS_OF)


def _role_event_snapshot() -> dict[str, Any]:
    without_id = {
        "schema_version": "role_event_snapshot_v2",
        "consumer_agent": ROLE,
        "as_of": f"{AS_OF}T15:00:00+08:00",
        "contract_version": "role_event_coverage_v2",
        "coverage": {
            "coverage_completeness": "COMPLETE",
            "query_complete": True,
        },
        "projections": [],
    }
    snapshot_id = "role-event-snapshot:" + _canonical_hash(without_id).removeprefix(
        "sha256:"
    )
    with_id = {"role_event_snapshot_id": snapshot_id, **without_id}
    return {**with_id, "role_event_snapshot_hash": _canonical_hash(with_id)}


def test_loaded_sector_snapshot_has_one_validated_immutable_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_sector_snapshots(tmp_path, date.fromisoformat(AS_OF))
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")
    source_path = tmp_path / "sector_snapshots" / AS_OF / f"{ROLE}.json"
    source_before = source_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        "mosaic.dataflows.sector_snapshots.build_role_event_snapshot",
        lambda *_: _role_event_snapshot(),
    )

    loaded = load_sector_snapshot(ROLE, AS_OF, root=tmp_path / "sector_snapshots")

    assert set(loaded) == {
        *snapshot_field_names(),
        "event_coverage",
        "role_event_snapshot_ref",
    }
    assert loaded["snapshot_hash"] == _canonical_hash(
        {key: value for key, value in loaded.items() if key != "snapshot_hash"}
    )
    assert source_path.read_text(encoding="utf-8") == source_before


def snapshot_field_names() -> set[str]:
    return {
        "schema_version",
        "fixture_class",
        "sector_universe_manifest_hash",
        "sector_agent_id",
        "as_of_date",
        "direction_contract_version",
        "direction_metric_registry_version",
        "direction_metric_registry_hash",
        "membership_query_plan_id",
        "membership_query_plan_version",
        "membership_query_plan_hash",
        "membership_pit_status",
        "membership_observed_at",
        "direction_ids",
        "direction_cards",
        "eligible_security_universe",
        "eligible_count",
        "membership_hash",
        "security_scoring_contract_version",
        "security_scoring_contract_hash",
        "security_scoring_rows",
        "security_scoring_rows_hash",
        "evidence_catalog",
        "snapshot_hash",
    }


def test_sector_snapshot_rejects_unvalidated_runtime_fields(
    snapshot: dict[str, Any],
) -> None:
    snapshot["event_coverage"] = {"coverage_completeness": "COMPLETE"}
    _rehash_snapshot(snapshot)
    with pytest.raises(DataVendorUnavailable, match="fields mismatch"):
        validate_sector_snapshot(snapshot, ROLE, AS_OF)


def _rehash_source_batch(batch: dict[str, Any]) -> None:
    batch["rows_hash"] = _canonical_hash(batch["rows"])
    body = {
        key: value
        for key, value in batch.items()
        if key not in {"source_batch_id", "source_batch_hash", "rows"}
    }
    batch["source_batch_hash"] = _canonical_hash(body)
    batch["source_batch_id"] = "sector-source-batch:" + batch[
        "source_batch_hash"
    ].removeprefix("sha256:")


def _collector_row(
    endpoint: str, columns: list[str], ts_code: str, trade_date: str = AS_OF
) -> dict[str, Any]:
    row: dict[str, Any] = {column: 1.0 for column in columns}
    for field in columns:
        if field == "ts_code":
            row[field] = ts_code
        elif field in {"trade_date", "ann_date", "f_ann_date", "nav_date", "end_date"}:
            row[field] = trade_date
        elif field in {"report_type", "comp_type", "end_type", "update_flag"}:
            row[field] = "1"
    return row


def _registered_source_inputs(
    source_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snapshot = copy.deepcopy(source_snapshot)
    snapshot.pop("fixture_class")
    preflight = json.loads(TUSHARE_ENDPOINT_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    contracts = {
        row["endpoint"]: row
        for row in preflight["checks"]
        if row["endpoint"] in SECTOR_REQUIRED_SOURCE_ENDPOINTS
    }
    plan = next(
        row
        for row in SECTOR_UNIVERSE_MANIFEST["membership_query_plans"]
        if row["sector_agent_id"] == ROLE
    )
    members_by_code: dict[str, list[dict[str, Any]]] = {}
    for member in snapshot["eligible_security_universe"]:
        code = next(
            member[field]
            for field in ("l1_code", "l2_code", "l3_code")
            if member[field] is not None
        )
        members_by_code.setdefault(code, []).append(member)

    batches: list[dict[str, Any]] = []
    for branch in plan["branches"]:
        rows = []
        if branch["is_new"] == "Y":
            for member in members_by_code.get(branch["classification_code"], []):
                rows.append(
                    {
                        "l1_code": member["l1_code"],
                        "l1_name": "",
                        "l2_code": member["l2_code"],
                        "l2_name": "",
                        "l3_code": member["l3_code"],
                        "l3_name": "",
                        "ts_code": member["ts_code"],
                        "name": "synthetic registered row",
                        "in_date": member["in_date"],
                        "out_date": member["out_date"],
                        "is_new": "Y",
                    }
                )
        batch = {
            "source_batch_id": "pending",
            "source_id": "tushare.index_member_all",
            "endpoint": "index_member_all",
            "schema_contract_version": contracts["index_member_all"][
                "schema_contract_version"
            ],
            "request": {
                "query_plan_hash": plan["query_plan_hash"],
                "parameter": branch["parameter"],
                "classification_code": branch["classification_code"],
                "is_new": branch["is_new"],
            },
            "captured_at": f"{AS_OF}T12:00:00Z",
            "released_at": f"{AS_OF}T10:00:00Z",
            "vintage_at": f"{AS_OF}T11:00:00Z",
            "pit_status": "PIT_VERIFIED",
            "pagination_complete": True,
            "truncated": False,
            "query_count": 1,
            "completed_query_count": 1,
            "coverage_ratio": 1.0,
            "rows": rows,
            "rows_hash": "pending",
            "source_batch_hash": "pending",
        }
        _rehash_source_batch(batch)
        batches.append(batch)

    ts_codes = [row["ts_code"] for row in snapshot["eligible_security_universe"]]
    for endpoint in sorted(SECTOR_REQUIRED_SOURCE_ENDPOINTS - {"index_member_all"}):
        contract = contracts[endpoint]
        trade_dates = (
            [
                (date.fromisoformat(AS_OF) - timedelta(days=offset)).isoformat()
                for offset in range(20, -1, -1)
            ]
            if endpoint in {"daily", "adj_factor", "moneyflow"}
            else [AS_OF]
        )
        batch = {
            "source_batch_id": "pending",
            "source_id": f"tushare.{endpoint}",
            "endpoint": endpoint,
            "schema_contract_version": contract["schema_contract_version"],
            "request": {"end_date": AS_OF},
            "captured_at": f"{AS_OF}T12:00:00Z",
            "released_at": f"{AS_OF}T10:00:00Z",
            "vintage_at": f"{AS_OF}T11:00:00Z",
            "pit_status": "PIT_VERIFIED",
            "pagination_complete": True,
            "truncated": False,
            "query_count": 1,
            "completed_query_count": 1,
            "coverage_ratio": 1.0,
            "rows": [
                _collector_row(
                    endpoint, contract["expected_columns"], ts_code, trade_date
                )
                for ts_code in ts_codes
                for trade_date in trade_dates
            ],
            "rows_hash": "pending",
            "source_batch_hash": "pending",
        }
        _rehash_source_batch(batch)
        batches.append(batch)

    representative_batches = {batch["endpoint"]: batch for batch in batches}
    for evidence, endpoint in zip(
        snapshot["evidence_catalog"],
        sorted(SECTOR_REQUIRED_SOURCE_ENDPOINTS),
    ):
        batch = representative_batches[endpoint]
        evidence["evidence_kind"] = "REGISTERED_COLLECTOR_BATCH"
        evidence["source_id"] = batch["source_id"]
        evidence["source_endpoint"] = endpoint
        evidence["content_hash"] = batch["source_batch_hash"]
        evidence["evidence_record_hash"] = _canonical_hash(
            {
                key: value
                for key, value in evidence.items()
                if key != "evidence_record_hash"
            }
        )
    scoring_evidence_ids = []
    for endpoint in ("adj_factor", "daily", "moneyflow"):
        batch = representative_batches[endpoint]
        evidence_id = f"registered:sector-security:{ROLE}:{endpoint}:{AS_OF}"
        evidence = {
            "evidence_id": evidence_id,
            "evidence_kind": "REGISTERED_SECURITY_SCORING_BATCH",
            "source_id": batch["source_id"],
            "source_endpoint": endpoint,
            "observation_date": AS_OF,
            "released_at": f"{AS_OF}T10:00:00Z",
            "vintage_at": f"{AS_OF}T11:00:00Z",
            "pit_status": "PIT_VERIFIED",
            "content_hash": batch["source_batch_hash"],
        }
        evidence["evidence_record_hash"] = _canonical_hash(evidence)
        snapshot["evidence_catalog"].append(evidence)
        scoring_evidence_ids.append(evidence_id)
    snapshot["evidence_catalog"].sort(key=lambda row: row["evidence_id"])
    for row in snapshot["security_scoring_rows"]:
        row["evidence_ids"] = sorted(scoring_evidence_ids)
        row.update(
            {
                "observation_date": AS_OF,
                "released_at": f"{AS_OF}T10:00:00Z",
                "vintage_at": f"{AS_OF}T11:00:00Z",
                "adjusted_return_20d": 0.0,
                "realized_volatility_20d": 0.0,
                "median_amount_20d_cny": 1_000.0,
                "net_moneyflow_20d_cny": 200_000.0,
                "observation_count": 20,
                "required_observation_count": 20,
                "coverage_ratio": 1.0,
                "availability_status": "AVAILABLE",
                "unavailability_reason": None,
            }
        )
    _rehash_security_scoring_rows(snapshot)
    return snapshot, batches


def test_registered_sector_builder_is_route_complete_and_atomic(
    snapshot: dict[str, Any], tmp_path: Path
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    root = tmp_path / "production-sector"
    written = write_registered_sector_snapshot(
        role=ROLE,
        as_of_date=AS_OF,
        snapshot=production,
        source_batches=batches,
        root=root,
    )
    assert written == production
    snapshot_path = root / AS_OF / f"{ROLE}.json"
    receipt_path = root / AS_OF / f"{ROLE}.sources.json"
    before = snapshot_path.read_bytes()
    assert receipt_path.is_file()

    changed = copy.deepcopy(production)
    changed["membership_observed_at"] = AS_OF
    _rehash_snapshot(changed)
    with pytest.raises(DataVendorUnavailable, match="refusing to replace"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=changed,
            source_batches=batches,
            root=root,
        )
    assert snapshot_path.read_bytes() == before


def test_registered_sector_builder_rejects_omission_route_and_lookahead(
    snapshot: dict[str, Any], tmp_path: Path
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    missing = [batch for batch in batches if batch["endpoint"] != "moneyflow"]
    with pytest.raises(DataVendorUnavailable, match="incomplete: moneyflow"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=missing,
            root=tmp_path / "missing",
        )

    wrong_route = copy.deepcopy(batches)
    wrong_route[0]["source_id"] = "tushare.daily"
    _rehash_source_batch(wrong_route[0])
    with pytest.raises(DataVendorUnavailable, match="route is not registered"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=wrong_route,
            root=tmp_path / "wrong-route",
        )

    lookahead = copy.deepcopy(batches)
    daily = next(batch for batch in lookahead if batch["endpoint"] == "daily")
    daily["rows"][0]["trade_date"] = "2026-07-18"
    _rehash_source_batch(daily)
    with pytest.raises(DataVendorUnavailable, match="future trade_date"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=lookahead,
            root=tmp_path / "lookahead",
        )


def test_registered_sector_builder_recomputes_security_scores(
    snapshot: dict[str, Any], tmp_path: Path
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    production["security_scoring_rows"][0]["adjusted_return_20d"] = 0.25
    _rehash_security_scoring_rows(production)

    with pytest.raises(
        DataVendorUnavailable, match="metrics do not match registered PIT batches"
    ):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "fabricated-score",
        )
