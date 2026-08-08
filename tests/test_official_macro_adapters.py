from __future__ import annotations

import base64
import json
from hashlib import sha256
from pathlib import Path

import pytest

from mosaic.dataflows import official_macro_adapters
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.official_macro_adapters import (
    OfficialApiResponse,
    build_ecb_url,
    build_eurostat_url,
    build_fomc_feed_url,
    build_ny_fed_rate_url,
    build_world_bank_url,
    fetch_fomc_feed,
    fetch_ny_fed_rate,
    fetch_official_series,
    parse_ecb_csv,
    parse_ecb_history_csv,
    parse_eurostat_jsonstat,
    parse_fomc_monetary_rss,
    parse_ny_fed_reference_rates,
    parse_world_bank_json,
)


def test_live_fetch_preserves_final_transport_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def timed_out(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        raise TimeoutError("private timeout detail")

    monkeypatch.setattr(official_macro_adapters.urllib.request, "urlopen", timed_out)
    monkeypatch.setattr(official_macro_adapters.time, "sleep", lambda _: None)

    with pytest.raises(
        DataVendorUnavailable, match="official macro API request failed"
    ) as exc_info:
        official_macro_adapters._live_fetch(
            build_eurostat_url("eu27_real_gdp", last_periods=4)
        )

    assert calls == 2
    assert isinstance(exc_info.value.__cause__, TimeoutError)


def test_official_macro_urls_are_closed_and_bounded() -> None:
    eurostat = build_eurostat_url("eu27_real_gdp", last_periods=4)
    assert eurostat.startswith("https://ec.europa.eu/eurostat/api/")
    assert "geo=EU27_2020" in eurostat
    assert "lastTimePeriod=4" in eurostat

    ecb = build_ecb_url("EXR.D.USD.EUR.SP00.A", last_observations=3)
    assert ecb.startswith("https://data-api.ecb.europa.eu/service/data/EXR/")
    assert "includeHistory=false" in ecb
    assert "lastNObservations=3" in ecb
    ecb_history = build_ecb_url(
        "FM.B.U2.EUR.4F.KR.DFR.LEV",
        last_observations=3,
        include_history=True,
    )
    assert "includeHistory=true" in ecb_history
    ecb_window = build_ecb_url(
        "FM.B.U2.EUR.4F.KR.DFR.LEV",
        last_observations=None,
        include_history=True,
        observation_start="2025-01-01",
        observation_end="2026-08-01",
    )
    assert "startPeriod=2025-01-01" in ecb_window
    assert "endPeriod=2026-08-01" in ecb_window
    assert "lastNObservations" not in ecb_window

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


def test_ecb_history_preserves_versions_and_delete_tombstones() -> None:
    payload = (
        b"KEY,TIME_PERIOD,OBS_VALUE,ACTION,VALID_FROM,VALID_TO,OBS_STATUS\n"
        b"FM,2025-01-01,3.0,Replace,2025-01-02T10:00:00+00:00,"
        b"2025-02-02T10:00:00+00:00,A\n"
        b"FM,2025-01-01,,Delete,2025-02-02T10:00:00+00:00,,A\n"
    )

    rows = parse_ecb_history_csv(payload)

    assert rows[0]["OBS_VALUE"] == 3.0
    assert rows[1]["ACTION"] == "Delete"
    assert rows[1]["OBS_VALUE"] is None
    assert rows[1]["VALID_FROM"] == "2025-02-02T10:00:00+00:00"


def test_europe_archive_fetch_retains_provider_vintage_metadata_and_raw_payload() -> None:
    eurostat_document = {
        "class": "dataset",
        "updated": "2026-07-31T11:00:00+0200",
        "id": ["freq", "geo", "time"],
        "size": [1, 1, 1],
        "dimension": {
            "freq": {"category": {"index": {"M": 0}}},
            "geo": {"category": {"index": {"EU27_2020": 0}}},
            "time": {"category": {"index": {"2026-06": 0}}},
        },
        "value": {"0": 2.1},
    }
    ecb_payload = (
        b"KEY,TIME_PERIOD,OBS_VALUE,ACTION,VALID_FROM,VALID_TO,OBS_STATUS\n"
        b"FM,2026-06-11,2.0,Replace,2026-06-11T12:00:00+00:00,,A\n"
    )

    def fetch(url: str) -> OfficialApiResponse:
        body = (
            json.dumps(eurostat_document).encode()
            if "eurostat" in url
            else ecb_payload
        )
        return OfficialApiResponse(
            url=url,
            content_type="application/json" if "eurostat" in url else "text/csv",
            body=body,
            retrieved_at="2026-08-01T06:00:00+00:00",
        )

    eurostat = fetch_official_series(
        provider="EUROSTAT",
        series_key="eu27_hicp",
        as_of="2026-08-01T15:00:00+08:00",
        fetch=fetch,
        include_raw_payload=True,
    )
    ecb = fetch_official_series(
        provider="ECB",
        series_key="FM.B.U2.EUR.4F.KR.DFR.LEV",
        as_of="2026-08-01T15:00:00+08:00",
        fetch=fetch,
        include_history=True,
        include_raw_payload=True,
    )

    assert eurostat["dataset_updated"] == "2026-07-31T11:00:00+02:00"
    assert base64.b64decode(eurostat["raw_payload_b64"]) == json.dumps(
        eurostat_document
    ).encode()
    assert ecb["pit_status"] == "AUTHORITATIVE_VINTAGE_HISTORY"
    assert ecb["rows"][0]["VALID_FROM"] == "2026-06-11T12:00:00+00:00"
    assert base64.b64decode(ecb["raw_payload_b64"]) == ecb_payload


def test_ecb_authoritative_history_can_be_captured_after_historical_cutoff() -> None:
    payload = (
        b"KEY,TIME_PERIOD,OBS_VALUE,ACTION,VALID_FROM,VALID_TO,OBS_STATUS\n"
        b"FM,2026-06-11,2.0,Replace,2026-06-11T12:00:00+00:00,,A\n"
    )

    def fetch(url: str) -> OfficialApiResponse:
        return OfficialApiResponse(
            url=url,
            content_type="text/csv",
            body=payload,
            retrieved_at="2026-08-09T06:00:00+00:00",
        )

    history = fetch_official_series(
        provider="ECB",
        series_key="FM.B.U2.EUR.4F.KR.DFR.LEV",
        as_of="2026-08-08T15:00:00+08:00",
        fetch=fetch,
        include_history=True,
        observation_start="2025-01-01",
        observation_end="2026-08-08",
    )
    assert history["pit_status"] == "AUTHORITATIVE_VINTAGE_HISTORY"
    with pytest.raises(DataVendorUnavailable, match="historical as_of"):
        fetch_official_series(
            provider="ECB",
            series_key="FM.B.U2.EUR.4F.KR.DFR.LEV",
            as_of="2026-08-08T15:00:00+08:00",
            fetch=fetch,
        )


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


def test_us_official_urls_are_closed_and_exact() -> None:
    assert build_fomc_feed_url() == (
        "https://www.federalreserve.gov/feeds/press_monetary.xml"
    )
    sofr = build_ny_fed_rate_url(
        "SOFR", start_date="2026-07-01", end_date="2026-07-03"
    )
    assert sofr.startswith("https://markets.newyorkfed.org/api/rates/secured/sofr/")
    assert "startDate=2026-07-01" in sofr
    assert "endDate=2026-07-03" in sofr
    assert "type=rate" in sofr
    effr = build_ny_fed_rate_url(
        "EFFR", start_date="2026-07-01", end_date="2026-07-03"
    )
    assert "/api/rates/unsecured/effr/" in effr
    with pytest.raises(DataVendorUnavailable, match="unsupported NY Fed rate"):
        build_ny_fed_rate_url(
            "OBFR", start_date="2026-07-01", end_date="2026-07-03"
        )


def test_fomc_rss_parser_accepts_only_official_statement_metadata() -> None:
    payload = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Federal Reserve issues FOMC statement</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260701a.htm</link>
    <guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260701a.htm</guid>
    <category>Monetary Policy</category>
    <pubDate>Wed, 01 Jul 2026 18:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Federal Reserve announces unrelated notice</title>
    <link>https://www.federalreserve.gov/newsevents/pressreleases/other.htm</link>
    <guid>https://www.federalreserve.gov/newsevents/pressreleases/other.htm</guid>
    <category>Other</category>
    <pubDate>Wed, 01 Jul 2026 17:00:00 GMT</pubDate>
  </item>
</channel></rss>"""
    rows = parse_fomc_monetary_rss(payload)
    assert rows == [
        {
            "event_id": (
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20260701a.htm"
            ),
            "title": "Federal Reserve issues FOMC statement",
            "url": (
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20260701a.htm"
            ),
            "category": "Monetary Policy",
            "published_at": "2026-07-01T18:00:00+00:00",
        }
    ]
    with pytest.raises(DataVendorUnavailable, match="official Federal Reserve"):
        parse_fomc_monetary_rss(
            payload.replace(b"www.federalreserve.gov", b"example.com")
        )


def test_ny_fed_parser_enforces_rate_type_and_date_window() -> None:
    payload = json.dumps(
        {
            "refRates": [
                {
                    "effectiveDate": "2026-07-01",
                    "type": "SOFR",
                    "percentRate": 4.33,
                    "revisionIndicator": "",
                }
            ]
        }
    ).encode()
    assert parse_ny_fed_reference_rates(
        payload,
        expected_rate="SOFR",
        start_date="2026-07-01",
        end_date="2026-07-03",
    ) == [
        {
            "effective_date": "2026-07-01",
            "rate_type": "SOFR",
            "percent_rate": 4.33,
            "revision_indicator": "",
        }
    ]
    wrong_type = payload.replace(b'"SOFR"', b'"EFFR"')
    with pytest.raises(DataVendorUnavailable, match="rate type mismatch"):
        parse_ny_fed_reference_rates(
            wrong_type,
            expected_rate="SOFR",
            start_date="2026-07-01",
            end_date="2026-07-03",
        )


def test_us_official_fetches_reuse_live_transport_provenance_and_cutoff() -> None:
    rss = b"""<rss version="2.0"><channel><item>
<title>Federal Reserve issues FOMC statement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260701a.htm</link>
<guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260701a.htm</guid>
<category>Monetary Policy</category>
<pubDate>Wed, 01 Jul 2026 06:00:00 GMT</pubDate>
</item></channel></rss>"""
    rates = json.dumps(
        {
            "refRates": [
                {
                    "effectiveDate": "2026-07-01",
                    "type": "EFFR",
                    "percentRate": 4.4,
                    "revisionIndicator": "",
                }
            ]
        }
    ).encode()

    def fetch(url: str) -> OfficialApiResponse:
        return OfficialApiResponse(
            url=url,
            content_type="application/xml" if "federalreserve" in url else "application/json",
            body=rss if "federalreserve" in url else rates,
            retrieved_at="2026-07-01T07:00:00+00:00",
        )

    fomc = fetch_fomc_feed(
        as_of="2026-07-01T15:00:00+08:00", fetch=fetch
    )
    effr = fetch_ny_fed_rate(
        rate_type="EFFR",
        start_date="2026-07-01",
        end_date="2026-07-01",
        as_of="2026-07-01T15:00:00+08:00",
        fetch=fetch,
    )
    assert fomc["provider"] == "FEDERAL_RESERVE"
    assert fomc["source"] == "official.fomc_statement"
    assert effr["provider"] == "NY_FED"
    assert effr["source"] == "official.nyfed_effr"
    assert fomc["payload_hash"].startswith("sha256:")
    assert effr["row_count"] == 1
    assert "raw_payload_b64" not in fomc
    assert "raw_payload_b64" not in effr
    private_fomc = fetch_fomc_feed(
        as_of="2026-07-01T15:00:00+08:00",
        fetch=fetch,
        include_raw_payload=True,
    )
    private_effr = fetch_ny_fed_rate(
        rate_type="EFFR",
        start_date="2026-07-01",
        end_date="2026-07-01",
        as_of="2026-07-01T15:00:00+08:00",
        fetch=fetch,
        include_raw_payload=True,
    )
    assert base64.b64decode(private_fomc["raw_payload_b64"]) == rss
    assert base64.b64decode(private_effr["raw_payload_b64"]) == rates
    with pytest.raises(DataVendorUnavailable, match="historical as_of"):
        fetch_fomc_feed(
            as_of="2026-07-01T06:59:59+00:00", fetch=fetch
        )
