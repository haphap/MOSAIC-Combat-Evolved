from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.official_macro_adapters import (
    OfficialApiResponse,
    build_ecb_url,
    build_eurostat_url,
    build_world_bank_url,
    fetch_official_series,
    parse_ecb_csv,
    parse_eurostat_jsonstat,
    parse_world_bank_json,
)


def test_official_macro_urls_are_closed_and_bounded() -> None:
    eurostat = build_eurostat_url("eu27_real_gdp", last_periods=4)
    assert eurostat.startswith("https://ec.europa.eu/eurostat/api/")
    assert "geo=EU27_2020" in eurostat
    assert "lastTimePeriod=4" in eurostat

    ecb = build_ecb_url("EXR.D.USD.EUR.SP00.A", last_observations=3)
    assert ecb.startswith("https://data-api.ecb.europa.eu/service/data/EXR/")
    assert "includeHistory=false" in ecb
    assert "lastNObservations=3" in ecb

    world_bank = build_world_bank_url("eu_gdp_growth_context", most_recent=5)
    assert world_bank.startswith("https://api.worldbank.org/v2/country/EUU/")
    assert "source=2" in world_bank
    with pytest.raises(DataVendorUnavailable, match="unregistered"):
        build_eurostat_url("invented_series")


def test_official_macro_response_parsers_reject_empty_or_malformed_payloads() -> None:
    eurostat = {
        "class": "dataset",
        "id": ["freq", "geo", "time"],
        "size": [1, 1, 2],
        "dimension": {
            "freq": {"category": {"index": {"Q": 0}}},
            "geo": {"category": {"index": {"EU27_2020": 0}}},
            "time": {"category": {"index": {"2025-Q1": 0, "2025-Q2": 1}}},
        },
        "value": {"0": 100.5, "1": 101.25},
    }
    assert parse_eurostat_jsonstat(json.dumps(eurostat).encode()) == [
        {"freq": "Q", "geo": "EU27_2020", "time": "2025-Q1", "value": 100.5},
        {"freq": "Q", "geo": "EU27_2020", "time": "2025-Q2", "value": 101.25},
    ]

    ecb = (
        b"KEY,TIME_PERIOD,OBS_VALUE,ACTION,VALID_FROM\n"
        b"EXR,2026-07-16,1.17,Replace,2026-07-17\n"
        b"EXR,2015-07-27,,Delete,2015-07-27\n"
    )
    assert parse_ecb_csv(ecb)[0]["OBS_VALUE"] == 1.17

    world_bank = [
        {"page": 1, "pages": 1, "lastupdated": "2026-07-17"},
        [
            {"date": "2025", "value": 1.2},
            {"date": "2024", "value": None},
        ],
    ]
    assert parse_world_bank_json(json.dumps(world_bank).encode()) == [
        {"date": "2025", "value": 1.2}
    ]
    with pytest.raises(DataVendorUnavailable):
        parse_eurostat_jsonstat(b"{}")
    with pytest.raises(DataVendorUnavailable):
        parse_ecb_csv(b"TIME_PERIOD,OBS_VALUE\n")
    with pytest.raises(DataVendorUnavailable):
        parse_world_bank_json(b"[]")


def test_live_official_response_cannot_backfill_a_historical_as_of() -> None:
    payload = json.dumps(
        [
            {"page": 1, "pages": 1, "lastupdated": "2026-07-17"},
            [{"date": "2025", "value": 1.2}],
        ]
    ).encode()

    def fetch(_: str) -> OfficialApiResponse:
        return OfficialApiResponse(
            url=(
                "https://api.worldbank.org/v2/country/EUU/indicator/"
                "NY.GDP.MKTP.KD.ZG"
            ),
            content_type="application/json",
            body=payload,
            retrieved_at="2026-07-17T12:00:00+00:00",
        )

    with pytest.raises(DataVendorUnavailable, match="historical as_of"):
        fetch_official_series(
            provider="WORLD_BANK",
            series_key="eu_gdp_growth_context",
            as_of="2026-07-16T23:59:59+00:00",
            fetch=fetch,
        )
    current = fetch_official_series(
        provider="WORLD_BANK",
        series_key="eu_gdp_growth_context",
        as_of="2026-07-18T00:00:00+00:00",
        fetch=fetch,
    )
    assert current["usage_mode"] == "CONTEXT_ONLY"
    assert current["pit_status"] == "CURRENT_RESPONSE_REQUIRES_RELEASE_VINTAGE_JOIN"
    assert current["row_count"] == 1


def test_committed_official_preflight_is_metadata_only_and_hash_bound() -> None:
    path = Path("registry/data_sources/official_macro_source_preflight_v1.json")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = artifact.pop("preflight_hash")
    canonical = json.dumps(
        artifact,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert expected_hash == f"sha256:{sha256(canonical).hexdigest()}"
    assert artifact["raw_provider_rows_committed"] is False
    assert artifact["summary"]["production_snapshot_ready"] is False
    assert all("rows" not in check for check in artifact["checks"])
