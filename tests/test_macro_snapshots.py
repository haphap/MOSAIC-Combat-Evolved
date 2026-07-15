from __future__ import annotations

import json

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_snapshots import (
    ALFRED_SERIES_MAP,
    mark_legacy_macro_output,
    validate_role_snapshot,
)


def observation(**overrides):
    row = {
        "series_id": "cn_cpi",
        "period_start": "2024-05-01",
        "period_end": "2024-05-31",
        "released_at": "2024-06-12T01:30:00Z",
        "vintage_at": "2024-06-12T01:30:00Z",
        "actual": 0.3,
        "previous": 0.3,
        "expected": 0.4,
        "unit": "percent_yoy",
        "source": "tushare",
        "pit_status": "AVAILABLE_AS_OF",
        "evidence_id": "macro:cn_cpi:2024-05:20240612",
    }
    row.update(overrides)
    return row


def payload(role="china", **overrides):
    value = {
        "schema_version": "macro_role_snapshot_v1",
        "role": role,
        "as_of_date": "2024-06-30",
        "observations": [observation()],
        "events": [],
    }
    value.update(overrides)
    return value


def test_snapshot_contract_keeps_release_vintage_surprise_and_evidence_fields():
    result = validate_role_snapshot(payload(), "china", "2024-06-30")
    row = result["observations"][0]
    assert set(row) == {
        "series_id",
        "period_start",
        "period_end",
        "released_at",
        "vintage_at",
        "actual",
        "previous",
        "expected",
        "unit",
        "source",
        "pit_status",
        "evidence_id",
    }
    assert len(result["snapshot_hash"]) == 64
    json.dumps(result)


@pytest.mark.parametrize("field", ["released_at", "vintage_at"])
def test_future_release_or_vintage_is_rejected(field):
    bad = payload(observations=[observation(**{field: "2024-07-01T00:00:00Z"})])
    with pytest.raises(DataVendorUnavailable, match="future macro observation"):
        validate_role_snapshot(bad, "china", "2024-06-30")


def test_unregistered_alfred_series_has_no_implicit_fallback():
    bad = payload(
        role="us_economy",
        observations=[observation(series_id="UNREGISTERED", source="ALFRED")],
    )
    with pytest.raises(DataVendorUnavailable, match="unregistered ALFRED"):
        validate_role_snapshot(bad, "us_economy", "2024-06-30")
    assert {row["series_id"] for row in ALFRED_SERIES_MAP.values()} >= {
        "GDPC1",
        "PAYEMS",
        "CPIAUCSL",
        "PCEPI",
    }


def test_news_events_are_only_available_to_china_and_geopolitical():
    event = {
        "event_id": "event-1",
        "published_at": "2024-06-20T02:00:00Z",
        "source": "tushare.major_news",
        "content_hash": "sha256:abc",
        "title": "policy event",
        "evidence_id": "event:event-1",
    }
    allowed = payload(observations=[], events=[event])
    assert validate_role_snapshot(allowed, "china", "2024-06-30")["events"]
    denied = payload(role="volatility", observations=[], events=[event])
    with pytest.raises(DataVendorUnavailable, match="not permitted"):
        validate_role_snapshot(denied, "volatility", "2024-06-30")


def test_observations_reject_news_and_unregistered_sources():
    news = payload(observations=[observation(source="tushare.major_news")])
    with pytest.raises(DataVendorUnavailable, match="event library"):
        validate_role_snapshot(news, "china", "2024-06-30")

    unknown = payload(observations=[observation(source="unregistered_vendor")])
    with pytest.raises(DataVendorUnavailable, match="unapproved macro observation source"):
        validate_role_snapshot(unknown, "china", "2024-06-30")


def test_event_library_rejects_duplicate_content_hashes():
    first = {
        "event_id": "event-1",
        "published_at": "2024-06-20T02:00:00Z",
        "source": "tushare.major_news",
        "content_hash": "sha256:abc",
        "title": "policy event",
        "evidence_id": "event:event-1",
    }
    duplicate = {**first, "event_id": "event-2", "evidence_id": "event:event-2"}
    with pytest.raises(DataVendorUnavailable, match="duplicate event content hashes"):
        validate_role_snapshot(
            payload(observations=[], events=[first, duplicate]),
            "china",
            "2024-06-30",
        )


@pytest.mark.parametrize("agent", ["emerging_markets", "news_sentiment"])
def test_legacy_outputs_are_readable_but_unverified(agent):
    marked = mark_legacy_macro_output({"agent": agent, "old_value": 1})
    assert marked["legacy_status"] == "legacy_unverified"
