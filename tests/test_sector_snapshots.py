from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

import mosaic.dataflows.sector_snapshots as sector_snapshots_module
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.sector_snapshots import (
    _build_sector_etf_direction_authority,
    _canonical_hash,
    _derive_relationship_source_truth,
    _load_sector_universe_manifest,
    _registered_sector_metric_observations,
    load_sector_snapshot,
    render_relationship_snapshot,
    validate_relationship_snapshot,
    validate_sector_snapshot,
)
from mosaic.dataflows.sector_snapshots import (
    RELATIONSHIP_REQUIRED_SOURCE_ENDPOINTS,
    RELATIONSHIP_SOURCE_EXTRACTOR_CONTRACT_VERSION,
    SECTOR_ETF_SOURCE_ENDPOINTS,
    SECTOR_REQUIRED_SOURCE_ENDPOINTS,
    SECTOR_UNIVERSE_MANIFEST,
    TUSHARE_ENDPOINT_PREFLIGHT_PATH,
    write_registered_relationship_snapshot,
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


def _rehash_relationship_snapshot(snapshot: dict[str, Any]) -> None:
    snapshot["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    )


def _relationship_snapshot(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    _build_sector_snapshots(tmp_path, date.fromisoformat(AS_OF))
    source_path = tmp_path / "sector_snapshots" / AS_OF / "relationship_mapper.json"
    return source_path, json.loads(source_path.read_text(encoding="utf-8"))


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
    ) == _canonical_hash({"coverage_ratio": 1, "amounts": [0, 1_000]})

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


def test_structured_smoke_sector_fixture_has_a_decisive_order(
    snapshot: dict[str, Any],
) -> None:
    values_by_metric = {
        metric_id: [
            next(
                metric["value"]
                for metric in card["metrics"]
                if metric["metric_id"] == metric_id
            )
            for card in snapshot["direction_cards"]
        ]
        for metric_id in (
            "REVENUE_GROWTH_TTM_YOY",
            "EARNINGS_YIELD_TTM",
            "RELATIVE_TOTAL_RETURN_20D",
            "REALIZED_VOLATILITY_60D",
            "CURRENT_DRAWDOWN_252D",
        )
    }
    assert values_by_metric["REVENUE_GROWTH_TTM_YOY"] == sorted(
        values_by_metric["REVENUE_GROWTH_TTM_YOY"]
    )
    assert values_by_metric["EARNINGS_YIELD_TTM"] == sorted(
        values_by_metric["EARNINGS_YIELD_TTM"]
    )
    assert values_by_metric["RELATIVE_TOTAL_RETURN_20D"] == sorted(
        values_by_metric["RELATIVE_TOTAL_RETURN_20D"]
    )
    assert values_by_metric["REALIZED_VOLATILITY_60D"] == sorted(
        values_by_metric["REALIZED_VOLATILITY_60D"], reverse=True
    )
    assert values_by_metric["CURRENT_DRAWDOWN_252D"] == sorted(
        values_by_metric["CURRENT_DRAWDOWN_252D"]
    )
    for values in values_by_metric.values():
        assert len(set(values)) == len(values)


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


def test_relationship_snapshot_rejects_duplicate_factual_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path, payload = _relationship_snapshot(tmp_path)
    snapshot_root = tmp_path / "sector_snapshots"
    duplicate = copy.deepcopy(payload["relationships"][0])
    duplicate["edge_candidate_id"] = "structured-smoke-edge-duplicate"
    duplicate["relationship_row_hash"] = _canonical_hash(
        {
            key: value
            for key, value in duplicate.items()
            if key != "relationship_row_hash"
        }
    )
    payload["relationships"].append(duplicate)
    payload["relationships"].sort(key=lambda row: row["edge_candidate_id"])
    _rehash_relationship_snapshot(payload)
    source_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MOSAIC_SECTOR_SNAPSHOT_DIR", str(snapshot_root))
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")

    with pytest.raises(
        DataVendorUnavailable,
        match="frozen factual relationship tuples must be unique",
    ):
        render_relationship_snapshot(AS_OF, "graph-duplicate-factual")


def test_relationship_snapshot_binds_full_hashes_and_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    snapshot_root = tmp_path / "sector_snapshots"
    monkeypatch.setenv("MOSAIC_SECTOR_SNAPSHOT_DIR", str(snapshot_root))
    monkeypatch.setenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke")

    validated = validate_relationship_snapshot(payload, AS_OF)
    rendered = json.loads(render_relationship_snapshot(AS_OF, "graph-1"))

    assert validated["evidence_catalog_hash"] == _canonical_hash(
        validated["evidence_catalog"]
    )
    assert validated["frozen_holder_domain_hash"] == _canonical_hash(
        ["synthetic-holder"]
    )
    assert validated["frozen_security_domain_hash"] == _canonical_hash(
        ["000001.SZ", "000002.SZ"]
    )
    assert rendered["prediction_opportunity_set"]["run_id"] == "graph-1"
    assert rendered["snapshot_hash"] == _canonical_hash(
        {key: value for key, value in rendered.items() if key != "snapshot_hash"}
    )


def test_relationship_snapshot_rejects_duplicate_candidate_id_and_oversized_domains(
    tmp_path: Path,
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    duplicate = copy.deepcopy(payload)
    duplicate_row = copy.deepcopy(duplicate["relationships"][0])
    duplicate_row.update(
        {
            "source_entity": "financials",
            "target_entity": "000003.SZ",
            "edge_type": "COMMON_OWNERSHIP",
        }
    )
    duplicate_row["relationship_row_hash"] = _canonical_hash(
        {
            key: value
            for key, value in duplicate_row.items()
            if key != "relationship_row_hash"
        }
    )
    duplicate["relationships"].append(duplicate_row)
    _rehash_relationship_snapshot(duplicate)
    with pytest.raises(
        DataVendorUnavailable, match="edge_candidate_id values must be unique"
    ):
        validate_relationship_snapshot(duplicate, AS_OF)

    duplicate_opportunity = copy.deepcopy(payload)
    duplicate_opportunity["prediction_opportunity_set"]["ordered_opportunities"].append(
        copy.deepcopy(payload["prediction_opportunity_set"]["ordered_opportunities"][0])
    )
    with pytest.raises(DataVendorUnavailable, match="opportunity ids must be unique"):
        validate_relationship_snapshot(duplicate_opportunity, AS_OF)

    oversized = copy.deepcopy(payload)
    oversized["relationships"] = [
        copy.deepcopy(payload["relationships"][0]) for _ in range(33)
    ]
    with pytest.raises(DataVendorUnavailable, match="between 1 and 32 rows"):
        validate_relationship_snapshot(oversized, AS_OF)

    oversized_opportunities = copy.deepcopy(payload)
    oversized_opportunities["prediction_opportunity_set"]["ordered_opportunities"] = [
        copy.deepcopy(payload["prediction_opportunity_set"]["ordered_opportunities"][0])
        for _ in range(33)
    ]
    with pytest.raises(DataVendorUnavailable, match="between 1 and 32 rows"):
        validate_relationship_snapshot(oversized_opportunities, AS_OF)

    overlong = copy.deepcopy(payload)
    overlong["relationships"][0]["source_entity"] = "x" * 129
    with pytest.raises(DataVendorUnavailable, match="no longer than 128"):
        validate_relationship_snapshot(overlong, AS_OF)


def test_relationship_snapshot_rejects_future_or_tampered_evidence(
    tmp_path: Path,
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    future_row = copy.deepcopy(payload)
    relationship = future_row["relationships"][0]
    relationship["observation_date"] = "2026-07-18"
    relationship["released_at"] = "2026-07-18"
    relationship["vintage_at"] = "2026-07-18"
    relationship["relationship_row_hash"] = _canonical_hash(
        {
            key: value
            for key, value in relationship.items()
            if key != "relationship_row_hash"
        }
    )
    _rehash_relationship_snapshot(future_row)
    with pytest.raises(DataVendorUnavailable, match="as_of"):
        validate_relationship_snapshot(future_row, AS_OF)

    future = copy.deepcopy(payload)
    evidence = future["evidence_catalog"][0]
    evidence["observation_date"] = "2026-07-18"
    evidence["released_at"] = "2026-07-18"
    evidence["vintage_at"] = "2026-07-18"
    evidence["evidence_record_hash"] = _canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_record_hash"}
    )
    future["evidence_catalog_hash"] = _canonical_hash(future["evidence_catalog"])
    _rehash_relationship_snapshot(future)
    with pytest.raises(DataVendorUnavailable, match="as_of"):
        validate_relationship_snapshot(future, AS_OF)

    tampered_evidence_hash = copy.deepcopy(payload)
    tampered_evidence_hash["evidence_catalog_hash"] = f"sha256:{'f' * 64}"
    _rehash_relationship_snapshot(tampered_evidence_hash)
    with pytest.raises(DataVendorUnavailable, match="evidence_catalog_hash mismatch"):
        validate_relationship_snapshot(tampered_evidence_hash, AS_OF)

    tampered_snapshot = copy.deepcopy(payload)
    tampered_snapshot["prediction_opportunity_set"]["scoring_contract_version"] = (
        "relationship_graph_validation_tampered"
    )
    with pytest.raises(DataVendorUnavailable, match="snapshot_hash mismatch"):
        validate_relationship_snapshot(tampered_snapshot, AS_OF)


def test_relationship_snapshot_rejects_same_day_post_close_vintages(
    tmp_path: Path,
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    late_evidence = copy.deepcopy(payload)
    evidence = late_evidence["evidence_catalog"][0]
    evidence["released_at"] = f"{AS_OF}T07:00:01Z"
    evidence["vintage_at"] = f"{AS_OF}T07:00:01Z"
    evidence["evidence_record_hash"] = _canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_record_hash"}
    )
    late_evidence["evidence_catalog_hash"] = _canonical_hash(
        late_evidence["evidence_catalog"]
    )
    _rehash_relationship_snapshot(late_evidence)
    with pytest.raises(DataVendorUnavailable, match="15:00"):
        validate_relationship_snapshot(late_evidence, AS_OF)

    late_fact = copy.deepcopy(payload)
    relationship = late_fact["relationships"][0]
    relationship["released_at"] = f"{AS_OF}T07:00:01Z"
    relationship["vintage_at"] = f"{AS_OF}T07:00:01Z"
    relationship["relationship_row_hash"] = _canonical_hash(
        {
            key: value
            for key, value in relationship.items()
            if key != "relationship_row_hash"
        }
    )
    _rehash_relationship_snapshot(late_fact)
    with pytest.raises(DataVendorUnavailable, match="15:00"):
        validate_relationship_snapshot(late_fact, AS_OF)


def test_relationship_snapshot_requires_timezone_qualified_timestamps_and_includes_cutoff(
    tmp_path: Path,
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    timezone_less = copy.deepcopy(payload)
    evidence = timezone_less["evidence_catalog"][0]
    evidence["released_at"] = f"{AS_OF}T06:59:59"
    evidence["vintage_at"] = f"{AS_OF}T06:59:59"
    evidence["evidence_record_hash"] = _canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_record_hash"}
    )
    timezone_less["evidence_catalog_hash"] = _canonical_hash(
        timezone_less["evidence_catalog"]
    )
    _rehash_relationship_snapshot(timezone_less)
    with pytest.raises(DataVendorUnavailable, match="timezone-qualified"):
        validate_relationship_snapshot(timezone_less, AS_OF)

    for boundary in (f"{AS_OF}T07:00:00Z", f"{AS_OF}T15:00:00+08:00"):
        at_cutoff = copy.deepcopy(payload)
        evidence = at_cutoff["evidence_catalog"][0]
        evidence["released_at"] = boundary
        evidence["vintage_at"] = boundary
        evidence["evidence_record_hash"] = _canonical_hash(
            {
                key: value
                for key, value in evidence.items()
                if key != "evidence_record_hash"
            }
        )
        at_cutoff["evidence_catalog_hash"] = _canonical_hash(
            at_cutoff["evidence_catalog"]
        )
        _rehash_relationship_snapshot(at_cutoff)
        validate_relationship_snapshot(at_cutoff, AS_OF)


def test_relationship_snapshot_rejects_entity_identity_type_label_spoofing(
    tmp_path: Path,
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    holder_target = copy.deepcopy(payload)
    holder_target["relationships"][0]["target_entity"] = "holder-b"
    holder_target["prediction_opportunity_set"]["ordered_opportunities"][0][
        "target_entity"
    ] = "holder-b"
    with pytest.raises(DataVendorUnavailable, match="canonical A-share security"):
        validate_relationship_snapshot(holder_target, AS_OF)

    security_source = copy.deepcopy(payload)
    security_source["relationships"][0]["source_entity"] = "000005.SH"
    security_source["prediction_opportunity_set"]["ordered_opportunities"][0][
        "source_entity"
    ] = "000005.SH"
    with pytest.raises(DataVendorUnavailable, match="holder, not a security"):
        validate_relationship_snapshot(security_source, AS_OF)


def test_relationship_snapshot_binds_matched_non_edge_members_exactly(
    tmp_path: Path,
) -> None:
    _source_path, payload = _relationship_snapshot(tmp_path)
    opportunity = payload["prediction_opportunity_set"]["ordered_opportunities"][0]
    opportunity["matched_non_edges"][0]["target_entity"] = "000003.SZ"
    _rehash_relationship_snapshot(payload)

    with pytest.raises(
        DataVendorUnavailable, match="matched_non_edge_set_hash mismatch"
    ):
        validate_relationship_snapshot(payload, AS_OF)


def test_relationship_snapshot_requires_registered_source_receipt_outside_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_path, _payload = _relationship_snapshot(tmp_path)
    monkeypatch.setenv("MOSAIC_SECTOR_SNAPSHOT_DIR", str(tmp_path / "sector_snapshots"))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)

    with pytest.raises(
        DataVendorUnavailable, match="registered source receipt is unavailable"
    ):
        render_relationship_snapshot(AS_OF, "graph-production-source-gate")


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
        elif field in {
            "trade_date",
            "ann_date",
            "f_ann_date",
            "nav_date",
            "end_date",
            "cal_date",
        }:
            row[field] = trade_date
        elif field in {"report_type", "comp_type", "end_type", "update_flag"}:
            row[field] = "1"
    return row


def _registered_relationship_source_inputs(
    source_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snapshot = copy.deepcopy(source_snapshot)
    snapshot.pop("fixture_class")
    preflight = json.loads(TUSHARE_ENDPOINT_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    contracts = {
        row["endpoint"]: row
        for row in preflight["checks"]
        if row["endpoint"] in RELATIONSHIP_REQUIRED_SOURCE_ENDPOINTS
    }
    batches: list[dict[str, Any]] = []
    for endpoint in sorted(RELATIONSHIP_REQUIRED_SOURCE_ENDPOINTS):
        contract = contracts[endpoint]
        rows = [_collector_row(endpoint, contract["expected_columns"], "000001.SZ")]
        if endpoint == "index_member_all":
            rows.append(
                _collector_row(endpoint, contract["expected_columns"], "000002.SZ")
            )
            for row in rows:
                row.update(
                    {
                        "l1_code": "sector-energy",
                        "l1_name": "Energy",
                        "l2_code": "",
                        "l2_name": "",
                        "l3_code": "",
                        "l3_name": "",
                        "in_date": "20200101",
                        "out_date": "",
                        "is_new": "Y",
                    }
                )
        batch = {
            "source_batch_id": "pending",
            "source_id": f"tushare.{endpoint}",
            "endpoint": endpoint,
            "schema_contract_version": contract["schema_contract_version"],
            "request": {"end_date": AS_OF},
            "captured_at": f"{AS_OF}T06:30:00Z",
            "released_at": f"{AS_OF}T05:00:00Z",
            "vintage_at": f"{AS_OF}T06:00:00Z",
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
        if endpoint == "top10_holders":
            batch["rows"][0]["holder_name"] = "institution-a"
            batch["rows"][0]["hold_ratio"] = 2.5
        _rehash_source_batch(batch)
        batches.append(batch)
    evidence_batch = next(
        batch for batch in batches if batch["endpoint"] == "top10_holders"
    )
    evidence = snapshot["evidence_catalog"][0]
    evidence.update(
        {
            "evidence_kind": "REGISTERED_RELATIONSHIP_BATCH",
            "source_id": evidence_batch["source_id"],
            "source_endpoint": evidence_batch["endpoint"],
            "observation_date": AS_OF,
            "released_at": f"{AS_OF}T05:00:00Z",
            "vintage_at": f"{AS_OF}T06:00:00Z",
            "content_hash": evidence_batch["source_batch_hash"],
        }
    )
    evidence["evidence_record_hash"] = _canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_record_hash"}
    )
    relationships, opportunities, _derivations, _frozen = (
        _derive_relationship_source_truth(snapshot=snapshot, batches=batches)
    )
    snapshot["relationships"] = relationships
    snapshot["frozen_holder_domain_hash"] = _canonical_hash(
        sorted(
            {row["source_entity"] for row in relationships}
            | {
                matched["source_entity"]
                for opportunity in opportunities
                for matched in opportunity["matched_non_edges"]
            }
        )
    )
    snapshot["frozen_security_domain_hash"] = _canonical_hash(
        sorted(
            {row["target_entity"] for row in relationships}
            | {
                matched["target_entity"]
                for opportunity in opportunities
                for matched in opportunity["matched_non_edges"]
            }
        )
    )
    snapshot["prediction_opportunity_set"] = {
        "candidate_generation_contract_version": RELATIONSHIP_SOURCE_EXTRACTOR_CONTRACT_VERSION,
        "scoring_contract_version": "relationship_graph_validation_20d_v1",
        "ordered_opportunities": opportunities,
    }
    snapshot["evidence_catalog_hash"] = _canonical_hash(snapshot["evidence_catalog"])
    _rehash_relationship_snapshot(snapshot)
    return snapshot, batches


def test_registered_relationship_builder_binds_source_receipt_and_rejects_lookahead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    destination_root = tmp_path / "registered-relationship"

    written = write_registered_relationship_snapshot(
        as_of_date=AS_OF,
        snapshot=production,
        source_batches=batches,
        root=destination_root,
    )
    monkeypatch.setenv("MOSAIC_SECTOR_SNAPSHOT_DIR", str(destination_root))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    rendered = json.loads(render_relationship_snapshot(AS_OF, "graph-registered"))
    assert written == production
    assert rendered["prediction_opportunity_set"]["run_id"] == "graph-registered"

    receipt_path = destination_root / AS_OF / "relationship_mapper.sources.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert set(receipt["required_endpoints"]) == {
        "index_member_all",
        "top10_holders",
    }
    assert receipt["extractor_contract_version"] == (
        RELATIONSHIP_SOURCE_EXTRACTOR_CONTRACT_VERSION
    )
    assert receipt["normalizer_contract_version"] == (
        "relationship_source_normalizer_v1"
    )
    top10_frozen = next(
        row
        for row in receipt["frozen_source_batches"]
        if row["endpoint"] == "top10_holders"
    )
    assert receipt["relationship_derivations"] == [
        {
            "edge_candidate_id": production["relationships"][0]["edge_candidate_id"],
            "source_row_locator": {
                "source_batch_id": top10_frozen["source_batch_id"],
                "endpoint": "top10_holders",
                "row_index": 0,
            },
            "source_row_content_hash": _canonical_hash(top10_frozen["rows"][0]),
        }
    ]
    receipt["source_batches"][0]["captured_at"] = "2026-07-18T00:00:00Z"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(DataVendorUnavailable, match="lookahead"):
        render_relationship_snapshot(AS_OF, "graph-lookahead")


@pytest.mark.parametrize("late_field", ("vintage_at", "captured_at"))
def test_registered_relationship_rejects_post_close_source_batch(
    tmp_path: Path,
    late_field: str,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    batch = batches[0]
    batch[late_field] = f"{AS_OF}T07:00:01Z"
    if late_field == "vintage_at":
        batch["captured_at"] = f"{AS_OF}T07:00:01Z"
    _rehash_source_batch(batch)
    with pytest.raises(DataVendorUnavailable, match="15:00"):
        write_registered_relationship_snapshot(
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / late_field,
        )


def test_registered_relationship_rejects_timezone_less_source_batch(
    tmp_path: Path,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    batch = batches[0]
    batch["vintage_at"] = f"{AS_OF}T06:00:00"
    _rehash_source_batch(batch)
    with pytest.raises(DataVendorUnavailable, match="timezone-qualified"):
        write_registered_relationship_snapshot(
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "timezone-less",
        )


def test_registered_relationship_requires_only_consumed_source_routes(
    tmp_path: Path,
) -> None:
    assert RELATIONSHIP_REQUIRED_SOURCE_ENDPOINTS == {
        "index_member_all",
        "top10_holders",
    }
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    with pytest.raises(DataVendorUnavailable, match="endpoints are incomplete"):
        write_registered_relationship_snapshot(
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=[
                batch for batch in batches if batch["endpoint"] == "top10_holders"
            ],
            root=tmp_path / "missing-membership",
        )


@pytest.mark.parametrize("endpoint", ("index_member_all", "top10_holders"))
def test_registered_relationship_source_targets_must_be_canonical_securities(
    tmp_path: Path,
    endpoint: str,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    batch = next(row for row in batches if row["endpoint"] == endpoint)
    batch["rows"][0]["ts_code"] = "holder-b"
    _rehash_source_batch(batch)
    if endpoint == "top10_holders":
        production["evidence_catalog"][0]["content_hash"] = batch["source_batch_hash"]
    with pytest.raises(DataVendorUnavailable, match="canonical A-share security"):
        _derive_relationship_source_truth(snapshot=production, batches=batches)


def test_registered_relationship_source_holder_must_not_be_a_security(
    tmp_path: Path,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    batch = next(row for row in batches if row["endpoint"] == "top10_holders")
    batch["rows"][0]["holder_name"] = "000005.SH"
    _rehash_source_batch(batch)
    production["evidence_catalog"][0]["content_hash"] = batch["source_batch_hash"]
    with pytest.raises(DataVendorUnavailable, match="holder, not a security"):
        _derive_relationship_source_truth(snapshot=production, batches=batches)


def test_registered_relationship_uses_edge_announcement_timestamp(
    tmp_path: Path,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    holder_batch = next(
        batch for batch in batches if batch["endpoint"] == "top10_holders"
    )
    holder_batch["rows"][0]["ann_date"] = f"{AS_OF}T05:30:00Z"
    _rehash_source_batch(holder_batch)
    evidence = production["evidence_catalog"][0]
    evidence["content_hash"] = holder_batch["source_batch_hash"]
    evidence["evidence_record_hash"] = _canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_record_hash"}
    )
    production["evidence_catalog_hash"] = _canonical_hash(
        production["evidence_catalog"]
    )
    _rehash_relationship_snapshot(production)
    with pytest.raises(DataVendorUnavailable, match="end_date <= ann_date"):
        write_registered_relationship_snapshot(
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "late-edge-publication",
        )


def test_registered_relationship_matched_target_must_be_pit_eligible_same_sector(
    tmp_path: Path,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    membership_batch = next(
        batch for batch in batches if batch["endpoint"] == "index_member_all"
    )
    alternative = next(
        row for row in membership_batch["rows"] if row["ts_code"] == "000002.SZ"
    )
    alternative["out_date"] = AS_OF.replace("-", "")
    _rehash_source_batch(membership_batch)
    with pytest.raises(DataVendorUnavailable, match="matched non-edge"):
        write_registered_relationship_snapshot(
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "ineligible-control",
        )


@pytest.mark.parametrize(
    "mutation",
    ("factual_tuple", "activation_trigger", "materiality", "matched_non_edge"),
)
def test_registered_relationship_rejects_rehashed_derived_fact_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _source_path, source_snapshot = _relationship_snapshot(tmp_path)
    production, batches = _registered_relationship_source_inputs(source_snapshot)
    destination_root = tmp_path / f"registered-relationship-{mutation}"
    write_registered_relationship_snapshot(
        as_of_date=AS_OF,
        snapshot=production,
        source_batches=batches,
        root=destination_root,
    )
    snapshot_path = destination_root / AS_OF / "relationship_mapper.json"
    receipt_path = destination_root / AS_OF / "relationship_mapper.sources.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    relationship = snapshot["relationships"][0]
    opportunity = snapshot["prediction_opportunity_set"]["ordered_opportunities"][0]
    if mutation == "factual_tuple":
        relationship["source_entity"] = "mutated-holder"
        opportunity["source_entity"] = "mutated-holder"
        for matched in opportunity["matched_non_edges"]:
            matched["source_entity"] = "mutated-holder"
    elif mutation == "activation_trigger":
        relationship["activation_trigger"] = "REHASHED_BUT_UNSOURCED_TRIGGER"
    elif mutation == "materiality":
        opportunity["materiality_weight"] = 99.0
        opportunity["materiality_bucket"] = "HIGH"
        for matched in opportunity["matched_non_edges"]:
            matched["materiality_bucket"] = "HIGH"
    else:
        opportunity["matched_non_edges"][0]["target_entity"] = "000003.SZ"
    opportunity["matched_non_edge_set_hash"] = _canonical_hash(
        opportunity["matched_non_edges"]
    )
    snapshot["frozen_holder_domain_hash"] = _canonical_hash(
        sorted(
            {row["source_entity"] for row in snapshot["relationships"]}
            | {
                matched["source_entity"]
                for row in snapshot["prediction_opportunity_set"][
                    "ordered_opportunities"
                ]
                for matched in row["matched_non_edges"]
            }
        )
    )
    snapshot["frozen_security_domain_hash"] = _canonical_hash(
        sorted(
            {row["target_entity"] for row in snapshot["relationships"]}
            | {
                matched["target_entity"]
                for row in snapshot["prediction_opportunity_set"][
                    "ordered_opportunities"
                ]
                for matched in row["matched_non_edges"]
            }
        )
    )
    relationship["relationship_row_hash"] = _canonical_hash(
        {
            key: value
            for key, value in relationship.items()
            if key != "relationship_row_hash"
        }
    )
    _rehash_relationship_snapshot(snapshot)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["relationship_snapshot_hash"] = snapshot["snapshot_hash"]
    receipt["source_bundle_hash"] = _canonical_hash(
        {key: value for key, value in receipt.items() if key != "source_bundle_hash"}
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setenv("MOSAIC_SECTOR_SNAPSHOT_DIR", str(destination_root))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)

    with pytest.raises(DataVendorUnavailable, match="deterministic frozen source rows"):
        render_relationship_snapshot(AS_OF, f"graph-{mutation}")


def _registered_source_inputs(
    source_snapshot: dict[str, Any],
    *,
    with_etf: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snapshot = copy.deepcopy(source_snapshot)
    snapshot.pop("fixture_class")
    authority = sector_snapshots_module.SECTOR_ETF_DIRECTION_AUTHORITY
    authority_codes = {
        (row["sector_agent_id"], row["direction_id"]): row["etf_ts_codes"]
        for row in authority["direction_families"]
    }
    mapped_etf_codes = sorted(
        code for codes in authority_codes.values() for code in codes
    )
    if with_etf and not mapped_etf_codes:
        raise AssertionError("with_etf requires a test ETF direction authority")
    for card in snapshot["direction_cards"]:
        family = card["etf_family"]
        family.update(
            {
                "etf_ts_codes": authority_codes[(ROLE, card["direction_id"])],
                "selection_date": AS_OF,
                "released_at": f"{AS_OF}T05:00:00Z",
                "vintage_at": f"{AS_OF}T06:00:00Z",
                "direction_authority_version": authority["authority_version"],
                "direction_authority_hash": authority["authority_hash"],
                "direction_authority_effective_from": authority["effective_from"],
                "direction_authority_effective_to": authority["effective_to"],
            }
        )
        family["etf_family_hash"] = _canonical_hash(
            {key: value for key, value in family.items() if key != "etf_family_hash"}
        )
    preflight = json.loads(TUSHARE_ENDPOINT_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    required_endpoints = SECTOR_REQUIRED_SOURCE_ENDPOINTS | (
        SECTOR_ETF_SOURCE_ENDPOINTS if with_etf else frozenset()
    )
    contracts = {
        row["endpoint"]: row
        for row in preflight["checks"]
        if row["endpoint"] in required_endpoints
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
            "captured_at": f"{AS_OF}T07:00:00Z",
            "released_at": f"{AS_OF}T05:00:00Z",
            "vintage_at": f"{AS_OF}T06:00:00Z",
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
    statement_dates = [
        "2024-03-31",
        "2024-06-30",
        "2024-09-30",
        "2024-12-31",
        "2025-03-31",
        "2025-06-30",
        "2025-09-30",
        "2025-12-31",
        "2026-03-31",
        "2026-06-30",
    ]
    for endpoint in sorted(required_endpoints - {"index_member_all"}):
        contract = contracts[endpoint]
        if endpoint in {
            "daily",
            "adj_factor",
            "moneyflow",
            "fund_daily",
            "fund_adj",
            "fund_nav",
            "fund_share",
        }:
            trade_dates = [
                (date.fromisoformat(AS_OF) - timedelta(days=offset)).isoformat()
                for offset in range(252, -1, -1)
            ]
        elif endpoint in {"income", "cashflow"}:
            trade_dates = statement_dates
        elif endpoint == "trade_cal":
            trade_dates = [
                (date.fromisoformat(AS_OF) - timedelta(days=offset)).isoformat()
                for offset in range(252, -1, -1)
            ]
        else:
            trade_dates = [AS_OF]
        if endpoint == "trade_cal":
            rows = [
                {
                    "exchange": "SSE",
                    "cal_date": trade_date,
                    "is_open": 1,
                    "pretrade_date": (
                        date.fromisoformat(trade_date) - timedelta(days=1)
                    ).isoformat(),
                }
                for trade_date in trade_dates
            ]
        else:
            endpoint_codes = (
                sorted(set(mapped_etf_codes) | {"510001.SH"})
                if endpoint == "fund_basic"
                else mapped_etf_codes
                if endpoint.startswith("fund_")
                else ts_codes
            )
            rows = [
                _collector_row(
                    endpoint, contract["expected_columns"], ts_code, trade_date
                )
                for ts_code in endpoint_codes
                for trade_date in trade_dates
            ]
        if endpoint == "fund_basic":
            for row in rows:
                row.update(
                    {
                        "list_date": "2020-01-01",
                        "delist_date": None,
                        "market": "E",
                        "status": "L",
                    }
                )
        batch = {
            "source_batch_id": "pending",
            "source_id": f"tushare.{endpoint}",
            "endpoint": endpoint,
            "schema_contract_version": contract["schema_contract_version"],
            "request": (
                {"market": "E"}
                if endpoint == "fund_basic"
                else {
                    "exchange": "SSE",
                    "start_date": trade_dates[0],
                    "end_date": AS_OF,
                }
                if endpoint == "trade_cal"
                else {"end_date": AS_OF}
            ),
            "captured_at": f"{AS_OF}T07:00:00Z",
            "released_at": f"{AS_OF}T05:00:00Z",
            "vintage_at": f"{AS_OF}T06:00:00Z",
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

    representative_batches = {batch["endpoint"]: batch for batch in batches}
    membership_batches = [
        batch for batch in batches if batch["endpoint"] == "index_member_all"
    ]
    for evidence in snapshot["evidence_catalog"]:
        direction_id = evidence["evidence_id"].rsplit(":", 1)[-1]
        member_codes = {
            row["ts_code"]
            for row in snapshot["eligible_security_universe"]
            if row["direction_id"] == direction_id
        }
        batch = next(
            batch
            for batch in membership_batches
            if any(row["ts_code"] in member_codes for row in batch["rows"])
        )
        evidence["evidence_kind"] = "REGISTERED_COLLECTOR_BATCH"
        evidence["source_id"] = batch["source_id"]
        evidence["source_endpoint"] = "index_member_all"
        evidence["content_hash"] = batch["source_batch_hash"]
        evidence["evidence_record_hash"] = _canonical_hash(
            {
                key: value
                for key, value in evidence.items()
                if key != "evidence_record_hash"
            }
        )
    endpoint_evidence_ids: dict[str, str] = {}
    for endpoint in sorted(required_endpoints - {"index_member_all"}):
        batch = representative_batches[endpoint]
        evidence_id = f"registered:sector-source:{ROLE}:{endpoint}:{AS_OF}"
        evidence = {
            "evidence_id": evidence_id,
            "evidence_kind": "REGISTERED_METRIC_SOURCE_BATCH",
            "source_id": batch["source_id"],
            "source_endpoint": endpoint,
            "observation_date": AS_OF,
            "released_at": f"{AS_OF}T05:00:00Z",
            "vintage_at": f"{AS_OF}T06:00:00Z",
            "pit_status": "PIT_VERIFIED",
            "content_hash": batch["source_batch_hash"],
        }
        evidence["evidence_record_hash"] = _canonical_hash(evidence)
        snapshot["evidence_catalog"].append(evidence)
        endpoint_evidence_ids[endpoint] = evidence_id
    snapshot["evidence_catalog"].sort(key=lambda row: row["evidence_id"])
    for card in snapshot["direction_cards"]:
        family = card["etf_family"]
        family["evidence_ids"] = [endpoint_evidence_ids["fund_basic"]]
        family["etf_family_hash"] = _canonical_hash(
            {key: value for key, value in family.items() if key != "etf_family_hash"}
        )
    scoring_evidence_ids = sorted(
        endpoint_evidence_ids[endpoint]
        for endpoint in ("adj_factor", "daily", "moneyflow")
    )
    for row in snapshot["security_scoring_rows"]:
        row["evidence_ids"] = scoring_evidence_ids
        row.update(
            {
                "observation_date": AS_OF,
                "released_at": f"{AS_OF}T05:00:00Z",
                "vintage_at": f"{AS_OF}T06:00:00Z",
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
    authoritative_metrics = _registered_sector_metric_observations(
        snapshot=snapshot,
        batches=batches,
        as_of=date.fromisoformat(AS_OF),
    )
    members_by_direction = {
        direction_id: [
            row
            for row in snapshot["eligible_security_universe"]
            if row["direction_id"] == direction_id
        ]
        for direction_id in snapshot["direction_ids"]
    }
    for card in snapshot["direction_cards"]:
        card_refs = set(card["etf_family"]["evidence_ids"])
        card_refs.update(
            evidence_id
            for member in members_by_direction[card["direction_id"]]
            for evidence_id in member["evidence_ids"]
        )
        for metric in card["metrics"]:
            metric.update(
                authoritative_metrics[(card["direction_id"], metric["metric_id"])]
            )
            metric["metric_observation_hash"] = _canonical_hash(
                {
                    key: value
                    for key, value in metric.items()
                    if key != "metric_observation_hash"
                }
            )
            card_refs.update(metric["evidence_ids"])
        card["evidence_ids"] = sorted(card_refs)
        card["direction_card_hash"] = _canonical_hash(
            {key: value for key, value in card.items() if key != "direction_card_hash"}
        )
    _rehash_snapshot(snapshot)
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

    missing_empty_etf_proof = [
        batch for batch in batches if batch["endpoint"] != "fund_basic"
    ]
    with pytest.raises(DataVendorUnavailable, match="incomplete: fund_basic"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=missing_empty_etf_proof,
            root=tmp_path / "missing-empty-etf-proof",
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


@pytest.mark.parametrize(
    "metric_id",
    [
        contract["metric_id"]
        for contract in SECTOR_UNIVERSE_MANIFEST["direction_metric_registry"]
    ],
)
def test_registered_sector_builder_rejects_rehashed_metric_mutation_for_every_contract(
    snapshot: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metric_id: str,
) -> None:
    authority = _build_sector_etf_direction_authority(
        {(ROLE, snapshot["direction_ids"][0]): ("510001.SH",)}
    )
    monkeypatch.setattr(
        sector_snapshots_module, "SECTOR_ETF_DIRECTION_AUTHORITY", authority
    )
    production, batches = _registered_source_inputs(snapshot, with_etf=True)
    metric_index = next(
        index
        for index, metric in enumerate(production["direction_cards"][0]["metrics"])
        if metric["metric_id"] == metric_id
    )
    metric = production["direction_cards"][0]["metrics"][metric_index]
    assert metric["availability_status"] == "AVAILABLE"
    metric["value"] = float(metric["value"]) + 0.125
    _rehash_metric(production, 0, metric_index)

    with pytest.raises(
        DataVendorUnavailable,
        match="sector metric does not match registered PIT source rows",
    ):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / metric_id.lower(),
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("observation_count", 9),
        ("observation_date", "2026-06-29"),
        ("released_at", "2026-07-17T05:30:00Z"),
        ("vintage_at", "2026-07-17T06:30:00Z"),
    ],
)
def test_registered_sector_builder_rejects_rehashed_metric_projection_drift(
    snapshot: dict[str, Any],
    tmp_path: Path,
    field: str,
    replacement: Any,
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    metric = production["direction_cards"][0]["metrics"][0]
    metric[field] = replacement
    _rehash_metric(production, 0, 0)

    with pytest.raises(
        DataVendorUnavailable,
        match="sector metric does not match registered PIT source rows",
    ):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / field,
        )


def test_registered_sector_builder_rejects_rehashed_metric_evidence_drift(
    snapshot: dict[str, Any], tmp_path: Path
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    metric = production["direction_cards"][0]["metrics"][0]
    wrong_evidence_id = next(
        row["evidence_id"]
        for row in production["evidence_catalog"]
        if row["source_endpoint"] == "daily"
    )
    metric["evidence_ids"] = [wrong_evidence_id]
    _rehash_metric(production, 0, 0)

    with pytest.raises(
        DataVendorUnavailable,
        match="sector metric does not match registered PIT source rows",
    ):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "metric-evidence",
        )


def _rebind_changed_source_batch(
    snapshot: dict[str, Any], batch: dict[str, Any]
) -> None:
    _rehash_source_batch(batch)
    evidence = next(
        row
        for row in snapshot["evidence_catalog"]
        if row["source_endpoint"] == batch["endpoint"]
        and row["evidence_kind"] == "REGISTERED_METRIC_SOURCE_BATCH"
    )
    evidence["content_hash"] = batch["source_batch_hash"]
    evidence["evidence_record_hash"] = _canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_record_hash"}
    )
    _rehash_snapshot(snapshot)


@pytest.mark.parametrize("late_field", ("vintage_at", "captured_at"))
def test_registered_sector_builder_rejects_post_close_source_batch(
    snapshot: dict[str, Any], tmp_path: Path, late_field: str
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    batch = next(row for row in batches if row["endpoint"] == "daily")
    batch[late_field] = f"{AS_OF}T07:00:01Z"
    if late_field == "vintage_at":
        batch["captured_at"] = f"{AS_OF}T07:00:01Z"
    _rehash_source_batch(batch)

    with pytest.raises(DataVendorUnavailable, match="15:00"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / late_field,
        )


def test_sector_snapshot_rejects_post_close_metric_vintage(
    snapshot: dict[str, Any],
) -> None:
    metric = snapshot["direction_cards"][0]["metrics"][0]
    metric["released_at"] = f"{AS_OF}T07:00:01Z"
    metric["vintage_at"] = f"{AS_OF}T07:00:01Z"
    _rehash_metric(snapshot, 0, 0)

    with pytest.raises(DataVendorUnavailable, match="15:00"):
        validate_sector_snapshot(snapshot, ROLE, AS_OF)


def test_sector_etf_direction_authority_rejects_hidden_and_cross_direction_family(
    snapshot: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _build_sector_etf_direction_authority(
        {(ROLE, snapshot["direction_ids"][0]): ("510001.SH",)}
    )
    monkeypatch.setattr(
        sector_snapshots_module, "SECTOR_ETF_DIRECTION_AUTHORITY", authority
    )
    production, batches = _registered_source_inputs(snapshot, with_etf=True)

    hidden = copy.deepcopy(production)
    hidden_family = hidden["direction_cards"][0]["etf_family"]
    hidden_family["etf_ts_codes"] = []
    hidden_family["etf_family_hash"] = _canonical_hash(
        {key: value for key, value in hidden_family.items() if key != "etf_family_hash"}
    )
    _rehash_card_and_snapshot(hidden, 0)
    with pytest.raises(DataVendorUnavailable, match="fixed PIT direction authority"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=hidden,
            source_batches=batches,
            root=tmp_path / "hidden-etf",
        )

    crossed = copy.deepcopy(production)
    crossed_family = crossed["direction_cards"][1]["etf_family"]
    crossed_family["etf_ts_codes"] = ["510001.SH"]
    crossed_family["etf_family_hash"] = _canonical_hash(
        {
            key: value
            for key, value in crossed_family.items()
            if key != "etf_family_hash"
        }
    )
    _rehash_card_and_snapshot(crossed, 1)
    with pytest.raises(DataVendorUnavailable, match="fixed PIT direction authority"):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=crossed,
            source_batches=batches,
            root=tmp_path / "crossed-etf",
        )


def test_registered_sector_metrics_use_common_grid_across_suspension(
    snapshot: dict[str, Any], tmp_path: Path
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    ts_code = production["eligible_security_universe"][0]["ts_code"]
    daily = next(row for row in batches if row["endpoint"] == "daily")
    grid = sorted(
        date.fromisoformat(row["trade_date"])
        for row in daily["rows"]
        if row["ts_code"] == ts_code
    )
    missing_session = grid[-61].isoformat()
    daily["rows"] = [
        row
        for row in daily["rows"]
        if not (row["ts_code"] == ts_code and row["trade_date"] == missing_session)
    ]
    _rebind_changed_source_batch(production, daily)

    projected = _registered_sector_metric_observations(
        snapshot=production,
        batches=batches,
        as_of=date.fromisoformat(AS_OF),
    )
    direction_id = production["direction_ids"][0]
    assert (
        projected[(direction_id, "RELATIVE_TOTAL_RETURN_60D")]["availability_status"]
        == "UNAVAILABLE"
    )
    with pytest.raises(
        DataVendorUnavailable, match="does not match registered PIT source rows"
    ):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "suspended-common-grid",
        )


def test_registered_sector_fundamentals_require_consecutive_quarters(
    snapshot: dict[str, Any], tmp_path: Path
) -> None:
    production, batches = _registered_source_inputs(snapshot)
    ts_code = production["eligible_security_universe"][0]["ts_code"]
    income = next(row for row in batches if row["endpoint"] == "income")
    income["rows"] = [
        row
        for row in income["rows"]
        if not (row["ts_code"] == ts_code and row["end_date"] == "2025-12-31")
    ]
    _rebind_changed_source_batch(production, income)

    projected = _registered_sector_metric_observations(
        snapshot=production,
        batches=batches,
        as_of=date.fromisoformat(AS_OF),
    )
    direction_id = production["direction_ids"][0]
    assert (
        projected[(direction_id, "REVENUE_GROWTH_TTM_YOY")]["availability_status"]
        == "UNAVAILABLE"
    )
    with pytest.raises(
        DataVendorUnavailable, match="does not match registered PIT source rows"
    ):
        write_registered_sector_snapshot(
            role=ROLE,
            as_of_date=AS_OF,
            snapshot=production,
            source_batches=batches,
            root=tmp_path / "missing-quarter",
        )
