from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_source_adapters import (
    GeopoliticalTransportResponse,
    probe_geopolitical_source_transport,
    registered_geopolitical_source_ids,
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
