from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_source_adapters import (
    GeopoliticalParsedPage,
    GeopoliticalParsedPublication,
    GeopoliticalTransportResponse,
    ingest_geopolitical_route,
    probe_geopolitical_source_transport,
    registered_geopolitical_source_ids,
)
from mosaic.dataflows.geopolitical_events import (
    GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    GeopoliticalEventStore,
)
from scripts.probe_geopolitical_sources import canonical_hash


def _response(url: str, content_type: str, body: bytes) -> GeopoliticalTransportResponse:
    return GeopoliticalTransportResponse(
        request_url=url,
        final_url=url,
        content_type=content_type,
        body=body,
        retrieved_at="2026-07-17T12:00:00+00:00",
    )


def test_geopolitical_transport_registry_is_closed() -> None:
    source_ids = registered_geopolitical_source_ids()
    assert len(source_ids) == 15
    assert "gdelt_event_gkg" in source_ids
    with pytest.raises(DataVendorUnavailable, match="unregistered"):
        probe_geopolitical_source_transport("invented", fetch=lambda *_: None)  # type: ignore[arg-type,return-value]


def test_geopolitical_transport_returns_metadata_without_source_content() -> None:
    gdelt_body = (
        b"100 a http://data.gdeltproject.org/gdeltv2/a.export.CSV.zip\n"
        b"100 b http://data.gdeltproject.org/gdeltv2/b.mentions.CSV.zip\n"
        b"100 c http://data.gdeltproject.org/gdeltv2/c.gkg.csv.zip\n"
    )

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        return _response(url, "text/plain", gdelt_body)

    result = probe_geopolitical_source_transport("gdelt_event_gkg", fetch=fetch)
    assert result["transport_status"] == "ACTIVE"
    assert result["broad_schema_signal"] == "GDELT_LAST_UPDATE_LIST"
    assert result["raw_source_content_committed"] is False
    assert "body" not in result


def test_geopolitical_transport_broad_shapes_fail_closed() -> None:
    def bad_html(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        return _response(url, "text/plain", b"access denied")

    with pytest.raises(DataVendorUnavailable, match="HTML document"):
        probe_geopolitical_source_transport("ofac_recent_actions", fetch=bad_html)

    def reliefweb(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        assert "limit=1" in url
        return _response(url, "application/json", json.dumps({"data": []}).encode())

    result = probe_geopolitical_source_transport("ocha_reliefweb", fetch=reliefweb)
    assert result["broad_schema_signal"] == "JSON_OBJECT"


def test_geopolitical_preflight_hash_and_required_failures_are_fail_closed() -> None:
    path = Path(
        "registry/data_sources/geopolitical_source_transport_preflight_v1.json"
    )
    if not path.exists():
        pytest.skip("live metadata preflight has not been generated")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    supplied = artifact.pop("preflight_hash")
    assert supplied == canonical_hash(artifact)
    assert supplied == (
        "sha256:"
        + sha256(
            json.dumps(
                artifact,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    required = [row for row in artifact["checks"] if row["required"]]
    assert artifact["summary"]["required_root_transport_ready"] is all(
        row["transport_status"] == "ACTIVE" for row in required
    )
    assert artifact["summary"]["production_event_coverage_ready"] is False


def _official_sanction_route() -> dict:
    return next(
        row
        for row in GEOPOLITICAL_INITIAL_SOURCE_MANIFEST["coverage_routes"]
        if row["event_type"] == "SANCTION"
        and row["subject_type"] == "GLOBAL"
        and "ofac_recent_actions" in row["required_source_ids"]
    )


def _publication(*, published_at: str = "2026-07-17T11:00:00Z"):
    return GeopoliticalParsedPublication(
        source_record_id="ofac-2026-001",
        event_type="SANCTION",
        lifecycle_status="ANNOUNCED",
        actors=("US", "RU"),
        affected_regions=("EU",),
        affected_channels=("trade", "financial_conditions"),
        published_at=published_at,
        effective_at=None,
        causal_dedupe_key="ofac-sanction-program-2026-001",
        normalized_content_hash="sha256:" + "1" * 64,
        content_hash="sha256:" + "2" * 64,
    )


def test_route_ingestion_proves_pagination_and_appends_deduplicated_ledger(
    tmp_path: Path,
) -> None:
    route = _official_sanction_route()
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    second_url = "https://ofac.treasury.gov/recent-actions?page=2"

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        retrieved_at = (
            "2026-07-17T12:03:00Z" if url == second_url else "2026-07-17T12:02:00Z"
        )
        return GeopoliticalTransportResponse(
            request_url=url,
            final_url=url,
            content_type="text/html",
            body=b"<!doctype html><html><body>private source page</body></html>",
            retrieved_at=retrieved_at,
        )

    def parse_page(response: GeopoliticalTransportResponse, _: object):
        if response.request_url == second_url:
            return GeopoliticalParsedPage(
                publications=(_publication(),),
                next_url=None,
                terminal_marker_observed=True,
            )
        return GeopoliticalParsedPage(
            publications=(_publication(),),
            next_url=second_url,
            terminal_marker_observed=False,
        )

    result = ingest_geopolitical_route(
        route["coverage_route_id"],
        "ofac_recent_actions",
        parse_page=parse_page,
        fetch=fetch,
        store=store,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        poll_started_at="2026-07-17T12:00:00Z",
        nonproduction_parser_override=True,
    )

    assert result["page_count"] == 2
    assert result["parsed_row_count"] == 2
    assert result["deduplicated_event_revision_count"] == 1
    assert result["pagination_complete"] is True
    assert result["production_eligible"] is False
    assert "private source page" not in json.dumps(result)
    cutoff = datetime.fromisoformat("2026-07-17T13:00:00+00:00")
    polls = store.polls_as_of(cutoff)
    events = store.events_as_of(cutoff)
    assert len(polls) == 1
    assert polls[0]["pagination_complete"] is True
    assert polls[0]["ingestion_mode"] == "NON_PRODUCTION_CALLBACK"
    assert len(events) == 1
    assert events[0]["verification_status"] == "OFFICIAL_CONFIRMED"
    assert events[0]["published_at"] == "2026-07-17T11:00:00Z"


def test_route_ingestion_rejects_future_publication_and_records_failed_poll(
    tmp_path: Path,
) -> None:
    route = _official_sanction_route()
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        return GeopoliticalTransportResponse(
            request_url=url,
            final_url=url,
            content_type="text/html",
            body=b"<!doctype html><html></html>",
            retrieved_at="2026-07-17T12:02:00Z",
        )

    def parse_page(*_: object):
        return GeopoliticalParsedPage(
            publications=(_publication(published_at="2026-07-17T12:03:00Z"),),
            next_url=None,
            terminal_marker_observed=True,
        )

    with pytest.raises(DataVendorUnavailable, match="later than retrieval"):
        ingest_geopolitical_route(
            route["coverage_route_id"],
            "ofac_recent_actions",
            parse_page=parse_page,
            fetch=fetch,
            store=store,
            manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
            poll_started_at="2026-07-17T12:00:00Z",
            nonproduction_parser_override=True,
        )
    cutoff = datetime.fromisoformat("2026-07-17T13:00:00+00:00")
    assert store.events_as_of(cutoff) == []
    polls = store.polls_as_of(cutoff)
    assert len(polls) == 1
    assert polls[0]["parse_result"] == "FAILED"
    assert polls[0]["pagination_complete"] is False
    assert polls[0]["ingestion_mode"] == "NON_PRODUCTION_CALLBACK"


def test_caller_parser_cannot_enter_production_ingestion(tmp_path: Path) -> None:
    route = _official_sanction_route()

    with pytest.raises(DataVendorUnavailable, match="non-production only"):
        ingest_geopolitical_route(
            route["coverage_route_id"],
            "ofac_recent_actions",
            parse_page=lambda *_: GeopoliticalParsedPage((), None, True),
            fetch=lambda *_: _response(
                "https://ofac.treasury.gov/recent-actions",
                "text/html",
                b"<!doctype html><html></html>",
            ),
            store=GeopoliticalEventStore(tmp_path / "events.sqlite3"),
            manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        )

    with pytest.raises(DataVendorUnavailable, match="not implemented"):
        ingest_geopolitical_route(
            route["coverage_route_id"],
            "ofac_recent_actions",
            store=GeopoliticalEventStore(tmp_path / "events.sqlite3"),
            manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        )
