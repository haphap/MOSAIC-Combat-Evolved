from __future__ import annotations

import copy
import gzip
import json
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mosaic.dataflows.agent_materialization import (
    AgentDataMaterializationLedger,
    SourceCaptureReceipt,
)
from mosaic.dataflows.cross_runtime_json import canonical_hash
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_archive import materialize_geopolitical_snapshot
from mosaic.dataflows.geopolitical_events import (
    GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    REQUIRED_SOURCE_IDS,
    GeopoliticalEventStore,
    build_continuous_preflight_receipt,
    build_geopolitical_events_snapshot,
    build_geopolitical_source_license_decision,
    promote_geopolitical_manifest,
    validate_continuous_preflight_receipt,
    validate_geopolitical_manifest,
)
from mosaic.dataflows import geopolitical_source_adapters as adapters
from mosaic.dataflows.geopolitical_source_adapters import (
    BUILTIN_SOURCE_PARSER_CONTRACTS,
    GeopoliticalTransportResponse,
    capture_geopolitical_source,
    capture_required_geopolitical_sources,
    parse_registered_geopolitical_page,
)


_EVENT_TITLES = {
    "cn_mfa_releases": "中方决定对有关实体采取制裁措施",
    "cn_mofcom_export_control": "关于加强两用物项出口管制的公告",
    "un_sc_sanctions": "Security Council sanctions concerning Russia",
    "ofac_recent_actions": "United States imposes sanctions on Russia",
    "bis_federal_register": "United States updates export controls on China",
    "ustr_actions": "United States tariff restrictions concerning China",
    "eu_council_sanctions": "European Union sanctions concerning Russia",
    "eurlex_official_journal": "European Union sanctions concerning Russia",
    "marad_msci": "Shipping disruption in the Red Sea",
    "ukmto_advisories": "Shipping disruption in the Red Sea",
    "gdelt_event_gkg": "Armed conflict escalates in Ukraine",
    "un_conflict_releases": "Armed conflict escalates in Ukraine",
    "us_state_releases": "Diplomatic escalation between United States and China",
    "eeas_releases": "Diplomatic de-escalation between EU and Russia",
}

_FALLBACK_HTML_MARKERS = {
    "us_state_releases": "collection-result",
}

_RSS_SOURCE_IDS = {
    "eu_council_sanctions",
    "marad_msci",
    "un_conflict_releases",
}


def _adapter(source_id: str) -> dict:
    return next(
        row
        for row in GEOPOLITICAL_INITIAL_SOURCE_MANIFEST["adapter_contracts"]
        if row["source_id"] == source_id
    )


def _source_fixture(
    source_id: str,
    *,
    title: str | None = None,
    published_at: datetime | None = None,
) -> tuple[str, bytes]:
    title = title or _EVENT_TITLES[source_id]
    published = published_at or datetime(
        2026, 7, 17, 12, 0, tzinfo=timezone.utc
    )
    published = published.astimezone(timezone.utc)
    iso_timestamp = published.isoformat()
    iso_date = published.date().isoformat()
    dmy_date = published.strftime("%d.%m.%Y")
    month_date = published.strftime("%B %d, %Y")
    rss_date = published.strftime("%a, %d %b %Y %H:%M:%S +0000")
    if source_id == "un_sc_sanctions":
        return (
            "application/xml",
            (
                f"<CONSOLIDATED_LIST dateGenerated='{iso_timestamp}'>"
                "<INDIVIDUALS><INDIVIDUAL /></INDIVIDUALS>"
                "<ENTITIES><ENTITY /></ENTITIES>"
                "</CONSOLIDATED_LIST>"
            ).encode(),
        )
    if source_id in _RSS_SOURCE_IDS:
        return (
            "application/rss+xml",
            (
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<rss version='2.0'><channel><title>Official updates</title>"
                "<lastBuildDate>Fri, 17 Jul 2026 12:30:00 GMT</lastBuildDate>"
                "<item><guid>official-2026-001</guid>"
                f"<title>{title}</title>"
                "<link>https://example.invalid/official-2026-001</link>"
                f"<pubDate>{rss_date}</pubDate>"
                "</item></channel></rss>"
            ).encode(),
        )
    if source_id == "gdelt_event_gkg":
        return (
            "application/json",
            (
                '{"version":"https://jsonfeed.org/version/1.1","items":['
                '{"id":"gdelt-2026-001","url":"https://www.gdeltproject.org/'
                'event/gdelt-2026-001","title":"'
                + title
                + '"}]}'
            ).encode(),
        )
    if source_id == "ukmto_advisories":
        incidents = (
            []
            if title == "Routine administrative notice"
            else [
                {
                    "sitecoreId": "official-2026-001",
                    "incidentNumber": 1,
                    "incidentIssuer": "UKMTO",
                    "incidentTypeName": title,
                    "incidentTypeLevel": 2,
                    "utcDateOfIncident": iso_timestamp,
                    "place": "Red Sea",
                    "region": "Middle East",
                }
            ]
        )
        return (
            "application/json",
            json.dumps(incidents).encode(),
        )
    if source_id == "bis_federal_register":
        body = {
            "props": {
                "pageProps": {
                    "frns": [
                        {
                            "frnTitle": title,
                            "frnCitation": "91 FR 1",
                            "frnDocumentType": "Notice",
                            "frnPublicationDate": {
                                "time": iso_timestamp
                            },
                            "frnUrl": {
                                "url": "https://www.federalregister.gov/"
                                "documents/2026/07/17/official-2026-001"
                            },
                        }
                    ]
                }
            }
        }
        return (
            "text/html",
            (
                "<!doctype html><html><body><script id='__NEXT_DATA__' "
                "type='application/json'>"
                + json.dumps(body)
                + "</script></body></html>"
            ).encode(),
        )
    if source_id == "cn_mfa_releases":
        return (
            "text/html",
            (
                "<!doctype html><html><body><ul class='list1'><li>"
                f"<a href='/official-2026-001'>{title}（{iso_date}）</a>"
                "</li></ul></body></html>"
            ).encode(),
        )
    if source_id == "cn_mofcom_export_control":
        return (
            "text/html",
            (
                "<!doctype html><html><body><ul class='bjgList_01'><li>"
                f"<a href='/official-2026-001'>{title}</a>"
                f"<span>{iso_date}</span></li></ul></body></html>"
            ).encode(),
        )
    if source_id == "eeas_releases":
        return (
            "text/html",
            (
                "<!doctype html><html><body><div class='card'>"
                "<div class='card-body'>"
                f"<a href='/official-2026-001'>{title}</a></div>"
                f"<div class='card-footer node__meta'>{dmy_date}</div>"
                "</div></body></html>"
            ).encode(),
        )
    if source_id == "ofac_recent_actions":
        return (
            "text/html",
            (
                "<!doctype html><html><body><div class='views-row'>"
                f"<a href='/recent-actions/20260717'>{title}</a>"
                f"<div>{month_date} - Sanctions List Updates</div>"
                "</div></body></html>"
            ).encode(),
        )
    if source_id == "eurlex_official_journal":
        return (
            "application/sparql-results+json",
            json.dumps(
                {
                    "head": {"vars": ["act", "date", "title"]},
                    "results": {
                        "bindings": [
                            {
                                "act": {
                                    "type": "uri",
                                    "value": (
                                        "http://publications.europa.eu/resource/"
                                        "oj/L_202600001"
                                    ),
                                },
                                "date": {
                                    "type": "literal",
                                    "datatype": "http://www.w3.org/2001/XMLSchema#date",
                                    "value": iso_date,
                                },
                                "title": {
                                    "type": "literal",
                                    "xml:lang": "en",
                                    "value": title,
                                },
                            }
                        ]
                    },
                }
            ).encode(),
        )
    if source_id == "ustr_actions":
        return (
            "text/html",
            (
                "<!doctype html><html><body><article>"
                "<div class='field--name-body'><p>"
                f"<a href='/official-2026-001'>{title}</a> "
                f"({month_date})</p></div></article></body></html>"
            ).encode(),
        )
    marker = _FALLBACK_HTML_MARKERS[source_id]
    return (
        "text/html",
        (
            "<!doctype html><html><body>"
            f"<div class='{marker}'><article>"
            f"<a href='/official-2026-001'>{title}</a>"
            f"<time datetime='{iso_timestamp}'>{iso_date}</time>"
            "</article></div></body></html>"
        ).encode(),
    )


def _response(source_id: str, *, title: str | None = None, at: datetime | None = None):
    content_type, body = _source_fixture(source_id, title=title)
    adapter = _adapter(source_id)
    url = str(adapter["canonical_url_or_api"])
    retrieved = at or datetime(2026, 7, 17, 13, 0, tzinfo=timezone.utc)
    return GeopoliticalTransportResponse(
        request_url=url,
        final_url=url,
        content_type=content_type,
        body=body,
        retrieved_at=retrieved.isoformat(),
    )


@pytest.mark.parametrize("source_id", sorted(REQUIRED_SOURCE_IDS))
def test_every_required_source_has_a_stable_source_specific_parser(source_id: str):
    assert set(BUILTIN_SOURCE_PARSER_CONTRACTS) == REQUIRED_SOURCE_IDS

    first = parse_registered_geopolitical_page(source_id, _response(source_id))
    second = parse_registered_geopolitical_page(source_id, _response(source_id))

    assert first == second
    assert first.terminal_marker_observed is True
    assert first.terminal_proof_kind in adapters.TERMINAL_PROOF_KINDS
    assert first.next_url is None
    assert first.truncated is False
    assert len(first.publications) == 1
    publication = first.publications[0]
    assert publication.source_record_id
    expected_hour = (
        13
        if source_id == "gdelt_event_gkg"
        else (
            0
            if source_id
            in {
                "cn_mfa_releases",
                "cn_mofcom_export_control",
                "eeas_releases",
                "eurlex_official_journal",
                "ofac_recent_actions",
                "ustr_actions",
            }
            else 12
        )
    )
    assert publication.published_at == (
        f"2026-07-17T{expected_hour:02d}:00:00+00:00"
    )
    assert publication.event_type in _adapter(source_id)["covered_event_types"]


def test_source_parser_rejects_another_sources_shape():
    response = _response("ofac_recent_actions")
    with pytest.raises(DataVendorUnavailable, match="BIS schema"):
        parse_registered_geopolitical_page("bis_federal_register", response)


@pytest.mark.parametrize(
    ("source_id", "title"),
    (
        ("un_conflict_releases", "Client Challenge"),
        ("us_state_releases", "Technical Difficulties"),
    ),
)
def test_official_html_interstitial_is_not_transport_or_no_event_evidence(
    source_id: str, title: str
):
    response = _response(source_id)
    blocked = GeopoliticalTransportResponse(
        request_url=response.request_url,
        final_url=response.final_url,
        content_type="text/html",
        body=f"<!doctype html><html><head><title>{title}</title></head></html>".encode(),
        retrieved_at=response.retrieved_at,
    )

    with pytest.raises(DataVendorUnavailable, match="access/error interstitial"):
        parse_registered_geopolitical_page(source_id, blocked)


def test_dynamic_queries_and_ukmto_use_official_machine_endpoints():
    gdelt = _adapter("gdelt_event_gkg")
    request = adapters._request_url(
        "gdelt_event_gkg",
        str(gdelt["canonical_url_or_api"]),
        window_end=datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
    )
    parameters = urllib.parse.parse_qs(urllib.parse.urlparse(request).query)
    query = parameters["query"]
    assert query == [
        '(sanction OR "export control" OR tariff OR "armed conflict" OR '
        '"shipping disruption" OR "diplomatic escalation" OR '
        '"diplomatic de-escalation")'
    ]
    assert parameters["startdatetime"] == ["20260717113000"]
    assert parameters["enddatetime"] == ["20260717120000"]

    eurlex = _adapter("eurlex_official_journal")
    assert eurlex["retrieval_mode"] == "API"
    assert eurlex["canonical_url_or_api"] == (
        "https://publications.europa.eu/webapi/rdf/sparql"
    )
    request = adapters._request_url(
        "eurlex_official_journal",
        str(eurlex["canonical_url_or_api"]),
        window_end=datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
    )
    parameters = urllib.parse.parse_qs(urllib.parse.urlparse(request).query)
    sparql = parameters["query"][0]
    assert "official-journal-act_date_publication" in sparql
    assert '"2026-07-16"^^xsd:date' in sparql
    assert '"2026-07-17"^^xsd:date' in sparql
    assert "resource/authority/language/ENG" in sparql
    assert "LIMIT 250" in sparql
    assert parameters["format"] == ["application/sparql-results+json"]

    un_conflict = _adapter("un_conflict_releases")
    assert un_conflict["retrieval_mode"] == "RSS"
    assert un_conflict["canonical_url_or_api"] == (
        "https://news.un.org/feed/subscribe/en/news/topic/"
        "peace-and-security/feed/rss.xml"
    )

    unsc = _adapter("un_sc_sanctions")
    assert unsc["retrieval_mode"] == "FILE_FEED"
    assert unsc["canonical_url_or_api"] == (
        "https://scsanctions.un.org/resources/xml/en/name/consolidated.xml"
    )
    unsc_registration = next(
        row
        for row in GEOPOLITICAL_INITIAL_SOURCE_MANIFEST["registrations"]
        if row["source_id"] == "un_sc_sanctions"
    )
    assert unsc_registration["publisher_organization_id"] == (
        "UN_SECURITY_COUNCIL"
    )
    unsc_publisher = next(
        row
        for row in GEOPOLITICAL_INITIAL_SOURCE_MANIFEST["approved_publishers"]
        if row["publisher_organization_id"] == "UN_SECURITY_COUNCIL"
    )
    assert unsc_publisher["domain"] == (
        "unsolprodfiles.blob.core.windows.net"
    )

    ukmto = _adapter("ukmto_advisories")
    assert ukmto["retrieval_mode"] == "API"
    assert ukmto["canonical_url_or_api"] == (
        "https://sccd.royalnavy.mod.uk/api/ukmto/all"
    )


def test_eurlex_sparql_empty_window_is_terminal_and_cap_is_truncated():
    response = _response("eurlex_official_journal")
    payload = json.loads(response.body)
    binding = payload["results"]["bindings"][0]
    payload["results"]["bindings"] = []
    empty = GeopoliticalTransportResponse(
        request_url=response.request_url,
        final_url=response.final_url,
        content_type=response.content_type,
        body=json.dumps(payload).encode(),
        retrieved_at=response.retrieved_at,
    )
    parsed = parse_registered_geopolitical_page(
        "eurlex_official_journal", empty
    )
    assert parsed.publications == ()
    assert parsed.terminal_marker_observed is True
    assert parsed.truncated is False

    payload["results"]["bindings"] = [binding] * 250
    capped = GeopoliticalTransportResponse(
        request_url=response.request_url,
        final_url=response.final_url,
        content_type=response.content_type,
        body=json.dumps(payload).encode(),
        retrieved_at=response.retrieved_at,
    )
    parsed = parse_registered_geopolitical_page(
        "eurlex_official_journal", capped
    )
    assert parsed.terminal_marker_observed is False
    assert parsed.truncated is True


def test_unsc_xml_is_one_stable_list_revision():
    first = parse_registered_geopolitical_page(
        "un_sc_sanctions", _response("un_sc_sanctions")
    )
    second = parse_registered_geopolitical_page(
        "un_sc_sanctions", _response("un_sc_sanctions")
    )
    assert first == second
    assert len(first.publications) == 1
    publication = first.publications[0]
    assert publication.source_record_id == "unsc-consolidated-list"
    assert publication.event_type == "SANCTION"
    assert publication.published_at == "2026-07-17T12:00:00+00:00"


def test_live_transport_boundedly_decodes_gzip(monkeypatch):
    body = _source_fixture("un_conflict_releases")[1]

    class Headers(dict):
        def get_content_type(self):
            return "application/rss+xml"

    class Response:
        headers = Headers({"Content-Encoding": "gzip"})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def geturl(self):
            return "https://news.un.org/feed/rss.xml"

        def read(self, _):
            return gzip.compress(body)

    monkeypatch.setattr(adapters.urllib.request, "urlopen", lambda *_a, **_k: Response())
    response = adapters._live_fetch(
        "https://news.un.org/feed/rss.xml", ("un.org",)
    )
    assert response.body == body
    assert response.content_type == "application/rss+xml"


@pytest.mark.parametrize("source_id", ("eeas_releases", "ofac_recent_actions"))
def test_live_paginated_directory_stops_only_after_overlapping_day_is_proven(
    source_id: str,
):
    if source_id == "eeas_releases":
        first_row = (
            "<div class='card'><div class='card-body'>"
            "<a href='/new'>Diplomatic escalation involving Russia</a></div>"
            "<div class='card-footer node__meta'>17.07.2026</div></div>"
        )
        old_row = (
            "<div class='card'><div class='card-body'>"
            "<a href='/old'>Diplomatic escalation involving Russia</a></div>"
            "<div class='card-footer node__meta'>15.07.2026</div></div>"
        )
    else:
        first_row = (
            "<div class='views-row'><a href='/recent-actions/20260717'>"
            "United States sanctions Russia</a><div>July 17, 2026</div></div>"
        )
        old_row = (
            "<div class='views-row'><a href='/recent-actions/20260715'>"
            "United States sanctions Russia</a><div>July 15, 2026</div></div>"
        )
    adapter = _adapter(source_id)
    url = str(adapter["canonical_url_or_api"])
    response = GeopoliticalTransportResponse(
        request_url=url,
        final_url=url,
        content_type="text/html",
        body=(
            "<!doctype html><html><body>"
            + first_row
            + "<a rel='next' href='?page=1'>Next</a></body></html>"
        ).encode(),
        retrieved_at="2026-07-17T13:00:00+00:00",
    )
    incomplete = parse_registered_geopolitical_page(source_id, response)
    assert incomplete.terminal_marker_observed is False
    assert incomplete.terminal_proof_kind is None
    assert incomplete.next_url == f"{url}?page=1"

    complete = parse_registered_geopolitical_page(
        source_id,
        GeopoliticalTransportResponse(
            request_url=url,
            final_url=url,
            content_type="text/html",
            body=(
                "<!doctype html><html><body>"
                + first_row
                + old_row
                + "<a rel='next' href='?page=1'>Next</a></body></html>"
            ).encode(),
            retrieved_at="2026-07-17T13:00:00+00:00",
        ),
    )
    assert complete.terminal_marker_observed is True
    assert complete.terminal_proof_kind == "WINDOW_LOWER_BOUND_REACHED"
    assert complete.next_url is None


def test_one_source_capture_fetches_once_then_fans_out_and_keeps_raw_private(
    tmp_path: Path,
):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    calls: list[str] = []

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        calls.append(url)
        return _response(
            "ofac_recent_actions",
            title="Routine administrative notice",
            at=datetime(2026, 7, 17, 12, 2, tzinfo=timezone.utc),
        )

    result = capture_geopolitical_source(
        "ofac_recent_actions",
        fetch=fetch,
        store=store,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        poll_started_at="2026-07-17T12:00:00Z",
        nonproduction_transport_override=True,
    )

    expected_routes = [
        row
        for row in GEOPOLITICAL_INITIAL_SOURCE_MANIFEST["coverage_routes"]
        if row["applicability"] == "APPLICABLE"
        and "ofac_recent_actions" in row["required_source_ids"]
    ]
    assert len(calls) == 1
    assert result["route_poll_count"] == len(expected_routes)
    assert result["parsed_publication_count"] == 0
    assert result["production_eligible"] is False
    assert result["terminal_proof_kind"] == "PAGINATION_EXHAUSTED"
    assert "Routine administrative notice" not in str(result)
    captures = store.source_captures_as_of(
        datetime(2026, 7, 17, 13, 0, tzinfo=timezone.utc)
    )
    assert [row["source_capture_id"] for row in captures] == [
        result["source_capture_id"]
    ]
    pages = store.source_pages(result["source_capture_id"])
    assert len(pages) == 1
    assert b"Routine administrative notice" in pages[0]["body"]
    polls = store.polls_as_of(datetime(2026, 7, 17, 13, 0, tzinfo=timezone.utc))
    assert len(polls) == len(expected_routes)
    assert all(row["row_count"] == 0 for row in polls)
    assert all(row["parse_result"] == "SUCCESS" for row in polls)

    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER geo_source_pages_no_update")
        conn.execute(
            "UPDATE source_page_archive SET body = ? WHERE source_capture_id = ?",
            (b"tampered", result["source_capture_id"]),
        )
    with pytest.raises(DataVendorUnavailable, match="archive hash mismatch"):
        store.source_pages(result["source_capture_id"])


def test_raw_page_identity_separates_distinct_poll_windows(tmp_path: Path):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        return GeopoliticalTransportResponse(
            request_url=url,
            final_url=url,
            content_type="text/html",
            body=_source_fixture(
                "ofac_recent_actions", title="Routine administrative notice"
            )[1],
            retrieved_at="2026-07-17T13:00:00+00:00",
        )

    first = capture_geopolitical_source(
        "ofac_recent_actions",
        fetch=fetch,
        store=store,
        poll_started_at="2026-07-17T12:00:00+00:00",
        nonproduction_transport_override=True,
    )
    second = capture_geopolitical_source(
        "ofac_recent_actions",
        fetch=fetch,
        store=store,
        poll_started_at="2026-07-17T12:30:00+00:00",
        nonproduction_transport_override=True,
    )

    assert first["source_capture_id"] != second["source_capture_id"]
    first_page = store.source_pages(first["source_capture_id"])[0]
    second_page = store.source_pages(second["source_capture_id"])[0]
    assert first_page["page_archive_id"] != second_page["page_archive_id"]
    assert first_page["poll_started_at"] == "2026-07-17T12:00:00+00:00"
    assert second_page["poll_started_at"] == "2026-07-17T12:30:00+00:00"


def test_license_decision_is_append_only_and_revalidated_on_read(tmp_path: Path):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    decision = build_geopolitical_source_license_decision(
        "ofac_recent_actions",
        decision_status="APPROVED",
        decided_at="2026-07-16T00:00:00+00:00",
        authority_id="mosaic-data-governance-test",
    )
    store.append_source_license_decision(decision)
    with sqlite3.connect(store.db_path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(
                "UPDATE source_license_decisions SET decided_at = decided_at "
                "WHERE decision_id = ?",
                (decision["decision_id"],),
            )
        conn.execute("DROP TRIGGER geo_license_no_update")
        tampered = {**decision, "decision_status": "BLOCKED"}
        conn.execute(
            "UPDATE source_license_decisions SET payload_json = ? "
            "WHERE decision_id = ?",
            (json.dumps(tampered), decision["decision_id"]),
        )
    with pytest.raises(DataVendorUnavailable, match="identity/hash"):
        store.source_license_decision(decision["decision_id"])


def test_trusted_capture_rejects_caller_transport_and_clock(tmp_path: Path):
    with pytest.raises(DataVendorUnavailable, match="trusted runtime"):
        capture_geopolitical_source(
            "ofac_recent_actions",
            fetch=lambda *_: _response("ofac_recent_actions"),
            store=GeopoliticalEventStore(tmp_path / "events.sqlite3"),
        )
    with pytest.raises(DataVendorUnavailable, match="trusted runtime"):
        capture_geopolitical_source(
            "ofac_recent_actions",
            poll_started_at="2026-07-17T12:00:00Z",
            store=GeopoliticalEventStore(tmp_path / "events-2.sqlite3"),
        )


def test_required_source_batch_attempts_every_source_and_never_substitutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    source_by_url = {
        str(row["canonical_url_or_api"]).split("?", 1)[0]: str(row["source_id"])
        for row in GEOPOLITICAL_INITIAL_SOURCE_MANIFEST["adapter_contracts"]
        if row["source_id"] in REQUIRED_SOURCE_IDS
    }
    calls: list[str] = []

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        source_id = source_by_url[url.split("?", 1)[0]]
        calls.append(source_id)
        response = _response(source_id)
        if source_id == "marad_msci":
            return GeopoliticalTransportResponse(
                request_url=url,
                final_url=url,
                content_type="text/html",
                body=_source_fixture("ofac_recent_actions")[1],
                retrieved_at=response.retrieved_at,
            )
        return response

    monkeypatch.setattr(
        adapters,
        "_utc_now",
        lambda: datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(adapters, "_live_fetch", fetch)

    result = capture_required_geopolitical_sources(
        store=store, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )

    assert sorted(calls) == sorted(REQUIRED_SOURCE_IDS)
    assert result["required_source_ids"] == sorted(REQUIRED_SOURCE_IDS)
    assert result["successful_source_ids"] == sorted(
        REQUIRED_SOURCE_IDS - {"marad_msci"}
    )
    assert result["failed_source_ids"] == ["marad_msci"]
    assert result["all_sources_attempted"] is True
    assert result["all_source_captures_succeeded"] is False
    assert result["substitution_used"] is False
    captures = store.source_captures_as_of(
        datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
    )
    assert {row["source_id"] for row in captures} == REQUIRED_SOURCE_IDS
    failed = [row for row in captures if row["source_id"] == "marad_msci"]
    assert len(failed) == 1
    assert failed[0]["parse_result"] == "FAILED"


def test_required_source_batch_uses_failure_exception_capture_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    for started_at, retrieved_at in (
        ("2026-07-17T12:00:00+00:00", "2026-07-17T12:01:00+00:00"),
        ("2026-07-17T12:30:00+00:00", "2026-07-17T12:31:00+00:00"),
    ):
        with pytest.raises(DataVendorUnavailable):
            capture_geopolitical_source(
                "marad_msci",
                fetch=lambda url, _, at=retrieved_at: GeopoliticalTransportResponse(
                    request_url=url,
                    final_url=url,
                    content_type="text/html",
                    body=_source_fixture("ofac_recent_actions")[1],
                    retrieved_at=at,
                ),
                store=store,
                poll_started_at=started_at,
                nonproduction_transport_override=True,
            )
    archived = store.source_captures_as_of(
        datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc),
        source_id="marad_msci",
    )
    assert len(archived) == 2
    exact_failure_id = archived[0]["source_capture_id"]
    unrelated_later_id = archived[1]["source_capture_id"]

    def capture(source_id: str, **_: object) -> dict[str, object]:
        if source_id == "marad_msci":
            failure = DataVendorUnavailable("expected failure")
            failure.source_capture_id = exact_failure_id
            raise failure
        return {"source_capture_id": f"test-success:{source_id}"}

    monkeypatch.setattr(adapters, "capture_geopolitical_source", capture)
    result = capture_required_geopolitical_sources(
        store=store, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )

    marad = next(
        row for row in result["source_results"] if row["source_id"] == "marad_msci"
    )
    assert marad["source_capture_id"] == exact_failure_id
    assert marad["source_capture_id"] != unrelated_later_id


def test_source_schema_failure_is_archived_but_never_healthy(tmp_path: Path):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")

    with pytest.raises(DataVendorUnavailable, match="BIS schema") as raised:
        capture_geopolitical_source(
            "bis_federal_register",
            fetch=lambda url, _: GeopoliticalTransportResponse(
                request_url=url,
                final_url=url,
                content_type="text/html",
                body=_source_fixture("ofac_recent_actions")[1],
                retrieved_at="2026-07-17T13:00:00+00:00",
            ),
            store=store,
            poll_started_at="2026-07-17T12:59:00+00:00",
            nonproduction_transport_override=True,
        )

    captures = store.source_captures_as_of(
        datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
    )
    assert len(captures) == 1
    assert getattr(raised.value, "source_capture_id", None) == captures[0][
        "source_capture_id"
    ]
    assert captures[0]["parse_result"] == "FAILED"
    assert captures[0]["pagination_complete"] is False
    assert captures[0]["terminal_proof_kind"] is None
    assert store.source_pages(captures[0]["source_capture_id"])
    assert all(
        row["parse_result"] == "FAILED"
        for row in store.polls_as_of(
            datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
        )
    )
    assert store.events_as_of(
        datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
    ) == []


def test_late_revision_keeps_event_identity_and_supersedes_prior_revision(
    tmp_path: Path,
):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")

    def capture(title: str, *, started_at: str, retrieved_at: str) -> None:
        capture_geopolitical_source(
            "ofac_recent_actions",
            fetch=lambda url, _: GeopoliticalTransportResponse(
                request_url=url,
                final_url=url,
                content_type="text/html",
                body=_source_fixture("ofac_recent_actions", title=title)[1],
                retrieved_at=retrieved_at,
            ),
            store=store,
            poll_started_at=started_at,
            nonproduction_transport_override=True,
        )

    capture(
        "United States imposes sanctions on Russia",
        started_at="2026-07-17T12:01:00+00:00",
        retrieved_at="2026-07-17T12:02:00+00:00",
    )
    capture(
        "United States expands sanctions on Russia",
        started_at="2026-07-17T13:01:00+00:00",
        retrieved_at="2026-07-17T13:02:00+00:00",
    )

    revisions = store.events_as_of(
        datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
    )
    assert len(revisions) == 2
    assert len({row["geopolitical_event_id"] for row in revisions}) == 1
    revisions.sort(key=lambda row: row["retrieved_at"])
    assert revisions[1]["supersedes_revision_id"] == revisions[0][
        "event_revision_id"
    ]
    assert revisions[1]["event_revision_id"] != revisions[0][
        "event_revision_id"
    ]


def test_30_day_receipt_proves_every_slot_and_a_single_gap_blocks_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    interval = timedelta(
        minutes=_adapter("ofac_recent_actions")[
            "expected_poll_interval_minutes"
        ]
    )
    window_start = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)
    window_end = window_start + timedelta(days=30)
    runtime = {"now": window_start}

    def now() -> datetime:
        return runtime["now"]

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        retrieved_at = runtime["now"] + timedelta(minutes=1)
        content_type, body = _source_fixture(
            "ofac_recent_actions",
            title="Routine administrative notice",
            published_at=retrieved_at,
        )
        return GeopoliticalTransportResponse(
            request_url=url,
            final_url=url,
            content_type=content_type,
            body=body,
            retrieved_at=retrieved_at.isoformat(),
        )

    monkeypatch.setattr(adapters, "_utc_now", now)
    monkeypatch.setattr(adapters, "_live_fetch", fetch)
    expected_slots = int(timedelta(days=30) / interval)
    for ordinal in range(expected_slots):
        runtime["now"] = window_start + ordinal * interval
        capture_geopolitical_source(
            "ofac_recent_actions",
            store=store,
            manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        )

    decision = build_geopolitical_source_license_decision(
        "ofac_recent_actions",
        decision_status="APPROVED",
        decided_at="2026-06-16T00:00:00+00:00",
        authority_id="mosaic-data-governance-test",
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    )
    store.append_source_license_decision(
        decision, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )
    receipt = build_continuous_preflight_receipt(
        "ofac_recent_actions",
        window_end=window_end.isoformat(),
        license_decision_id=decision["decision_id"],
        store=store,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    )
    assert receipt["status"] == "READY"
    assert receipt["expected_slot_count"] == expected_slots
    assert receipt["observed_slot_count"] == expected_slots
    assert receipt["missing_slot_starts"] == []
    assert receipt["availability_ratio"] == 1.0
    assert receipt["observed_continuous_days"] == 30
    store.append_continuous_preflight_receipt(
        receipt, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )

    shifted = build_continuous_preflight_receipt(
        "ofac_recent_actions",
        window_end=(window_end + interval).isoformat(),
        license_decision_id=decision["decision_id"],
        store=store,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    )
    assert shifted["status"] == "PREFLIGHT_REQUIRED"
    assert shifted["observed_slot_count"] == expected_slots - 1
    assert len(shifted["missing_slot_starts"]) == 1

    blocked_decision = build_geopolitical_source_license_decision(
        "ofac_recent_actions",
        decision_status="BLOCKED",
        decided_at="2026-06-16T00:00:00+00:00",
        authority_id="mosaic-data-governance-test",
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    )
    store.append_source_license_decision(
        blocked_decision, manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    )
    blocked = build_continuous_preflight_receipt(
        "ofac_recent_actions",
        window_end=window_end.isoformat(),
        license_decision_id=blocked_decision["decision_id"],
        store=store,
        manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
    )
    assert blocked["license_verified"] is False
    assert blocked["status"] == "PREFLIGHT_REQUIRED"
    with pytest.raises(DataVendorUnavailable, match="license decision"):
        build_continuous_preflight_receipt(
            "ofac_recent_actions",
            window_end=window_end.isoformat(),
            license_decision_id="geo-license:missing",
            store=store,
            manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        )

    tampered = copy.deepcopy(receipt)
    tampered["observed_slot_count"] -= 1
    with pytest.raises(DataVendorUnavailable, match="receipt hash"):
        validate_continuous_preflight_receipt(
            tampered,
            manifest=GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
            store=store,
        )

    promoted = promote_geopolitical_manifest(
        GEOPOLITICAL_INITIAL_SOURCE_MANIFEST,
        receipts={"ofac_recent_actions": receipt},
        store=store,
    )
    ofac = next(
        row
        for row in promoted["registrations"]
        if row["source_id"] == "ofac_recent_actions"
    )
    assert ofac["registration_status"] == "ACTIVE_VERIFIED"
    assert promoted["manifest_readiness"] == "PREFLIGHT_REQUIRED"
    assert any(
        blocker.startswith("un_sc_sanctions:")
        for blocker in promoted["readiness_blockers"]
    )


def _daily_interval_manifest() -> dict:
    manifest = copy.deepcopy(GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)
    registrations = {
        row["source_id"]: row for row in manifest["registrations"]
    }
    for adapter in manifest["adapter_contracts"]:
        adapter["expected_poll_interval_minutes"] = 24 * 60
        adapter["max_capture_age_minutes"] = 25 * 60
        body = {
            key: value
            for key, value in adapter.items()
            if key != "adapter_contract_hash"
        }
        adapter["adapter_contract_hash"] = canonical_hash(body)
        registrations[adapter["source_id"]]["adapter_contract_hash"] = adapter[
            "adapter_contract_hash"
        ]
    body = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    manifest["manifest_hash"] = canonical_hash(body)
    return validate_geopolitical_manifest(manifest)


def _calendar_receipt(route_id: str, *, as_of_date: str, cutoff: datetime):
    captured = (cutoff - timedelta(minutes=1)).isoformat()
    return SourceCaptureReceipt.seal(
        {
            "schema_version": "source_capture_receipt_v1",
            "identity": {
                "source_family": "tushare",
                "route_id": route_id,
                "request_hash": canonical_hash(
                    {"route_id": route_id, "as_of_date": as_of_date}
                ),
                "capture_id": f"calendar:{route_id}:{as_of_date}",
            },
            "transport": {
                "redacted_url": "https://api.tushare.pro/<registered-endpoint>",
                "method": "POST",
                "query_keys": ["date"],
                "pagination_policy": "single-page",
                "page_count": 1,
            },
            "authority": {
                "provider": "tushare",
                "permission_tier": "configured-runtime",
                "api_version": "pro-v1",
                "parser_version": "test-calendar-v1",
            },
            "time": {
                "released_at": captured,
                "vintage_at": captured,
                "captured_at": captured,
                "knowledge_available_at": captured,
            },
            "pit": {
                "pit_mode": "OBSERVED_LIVE",
                "as_of_cutoff": cutoff.isoformat(),
                "eligible": True,
                "blocker_codes": [],
                "vintage_query": None,
            },
            "content": {
                "raw_content_hash": canonical_hash(
                    {"route_id": route_id, "rows": 1}
                ),
                "normalized_row_count": 1,
                "schema_hash": canonical_hash({"calendar": "v1"}),
            },
            "coverage": {
                "requested_start": as_of_date,
                "requested_end": as_of_date,
                "observed_start": as_of_date,
                "observed_end": as_of_date,
                "dimensions": {"currency": [route_id.rsplit(".", 1)[-1].upper()]},
            },
            "completeness": {
                "truncated": False,
                "next_page_token_present": False,
                "duplicate_count": 0,
                "empty_result_semantics": "NON_EMPTY",
            },
            "provenance": {
                "parent_capture_hash": None,
                "previous_revision_hash": None,
                "revision_reason": None,
            },
        }
    )


def test_full_required_source_receipts_publish_snapshot_and_warm_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = _daily_interval_manifest()
    event_store = GeopoliticalEventStore(tmp_path / "events.sqlite3")
    ledger = AgentDataMaterializationLedger(tmp_path / "materialization.sqlite3")
    as_of_date = "2026-07-17"
    cutoff = datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc)
    window_start = cutoff - timedelta(days=30)
    runtime: dict[str, object] = {"now": window_start, "source_id": ""}

    def now() -> datetime:
        return runtime["now"]  # type: ignore[return-value]

    def fetch(url: str, _: tuple[str, ...]) -> GeopoliticalTransportResponse:
        source_id = str(runtime["source_id"])
        retrieved_at = runtime["now"] + timedelta(minutes=1)  # type: ignore[operator]
        content_type, body = _source_fixture(
            source_id,
            title="Routine administrative notice",
            published_at=retrieved_at,
        )
        return GeopoliticalTransportResponse(
            request_url=url,
            final_url=url,
            content_type=content_type,
            body=body,
            retrieved_at=retrieved_at.isoformat(),
        )

    monkeypatch.setattr(adapters, "_utc_now", now)
    monkeypatch.setattr(adapters, "_live_fetch", fetch)
    for source_id in sorted(REQUIRED_SOURCE_IDS):
        runtime["source_id"] = source_id
        for ordinal in range(30):
            runtime["now"] = window_start + timedelta(days=ordinal)
            capture_geopolitical_source(
                source_id, store=event_store, manifest=manifest
            )
        decision = build_geopolitical_source_license_decision(
            source_id,
            decision_status="APPROVED",
            decided_at=(window_start - timedelta(days=1)).isoformat(),
            authority_id="mosaic-data-governance-test",
            manifest=manifest,
        )
        event_store.append_source_license_decision(decision, manifest=manifest)
        receipt = build_continuous_preflight_receipt(
            source_id,
            window_end=cutoff.isoformat(),
            license_decision_id=decision["decision_id"],
            store=event_store,
            manifest=manifest,
        )
        assert receipt["status"] == "READY"
        event_store.append_continuous_preflight_receipt(
            receipt, manifest=manifest
        )

    ready_manifest = promote_geopolitical_manifest(
        manifest,
        receipts=event_store.latest_continuous_preflight_receipts(cutoff),
        store=event_store,
    )
    assert ready_manifest["manifest_readiness"] == "READY"
    for route_id in (
        "tushare.eco_cal.cny",
        "tushare.eco_cal.eur",
        "tushare.eco_cal.usd",
    ):
        ledger.append_source_capture(
            _calendar_receipt(route_id, as_of_date=as_of_date, cutoff=cutoff)
        )

    output_root = tmp_path / "snapshots"
    audit = build_geopolitical_events_snapshot(
        as_of_date, store=event_store, manifest=ready_manifest
    )
    assert audit["readiness"] == "READY", [
        (
            row["source_id"],
            row["status"],
            row["poll_completed_at"],
            row["continuous_preflight_receipt_id"],
        )
        for row in audit["route_source_coverage"]
        if row["status"] != "HEALTHY"
    ][:20]
    first = materialize_geopolitical_snapshot(
        as_of_date=as_of_date,
        event_store=event_store,
        ledger=ledger,
        manifest=ready_manifest,
        output_root=output_root,
    )
    assert first.source_receipt is not None
    assert first.source_receipt.as_dict()["completeness"][
        "empty_result_semantics"
    ] == "NON_EMPTY"
    assert first.coverage_receipt.as_dict()["route_results"][0][
        "status"
    ] == "SUCCESS"
    assert first.build_receipt.as_dict()["terminal_state"] == "READY"
    assert first.snapshot is not None
    assert first.snapshot["empty_state"] == "EVENTS_PRESENT"
    destination = output_root / as_of_date / "geopolitical.json"
    assert destination.exists()

    monkeypatch.setattr(
        adapters,
        "_live_fetch",
        lambda *_: (_ for _ in ()).throw(AssertionError("unexpected transport")),
    )
    second = materialize_geopolitical_snapshot(
        as_of_date=as_of_date,
        event_store=event_store,
        ledger=ledger,
        manifest=ready_manifest,
        output_root=output_root,
    )
    assert second.coverage_receipt.receipt_hash == first.coverage_receipt.receipt_hash
    assert second.build_receipt.receipt_hash == first.build_receipt.receipt_hash
    assert second.snapshot == first.snapshot
