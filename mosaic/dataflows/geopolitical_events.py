"""Fail-closed geopolitical event registry and point-in-time snapshots.

Public artifacts contain only contracts, hashes, source metadata and synthetic
fixtures.  Poll responses and event evidence live in the operator's private
SQLite cache.  Discovery is deliberately separated from confirmation: GDELT
may surface a risk flag, but it cannot by itself create a confirmed event.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .exceptions import DataVendorUnavailable

MANIFEST_SCHEMA_VERSION = "geopolitical_initial_source_manifest_v2"
EVENT_REGISTRY_VERSION = "geopolitical_verified_event_registry_v2"
ROLE_SNAPSHOT_SCHEMA_VERSION = "geopolitical_role_snapshot_v2"
EVENT_TYPES = (
    "SANCTION",
    "EXPORT_CONTROL",
    "TARIFF_TRADE_RESTRICTION",
    "ARMED_CONFLICT",
    "SHIPPING_DISRUPTION",
    "DIPLOMATIC_ESCALATION",
    "DIPLOMATIC_DEESCALATION",
)
WATCHLIST_ACTORS = ("CN", "US", "EU", "RU", "UA", "IR", "IL", "KP", "KR")
WATCHLIST_REGIONS = (
    "TAIWAN_STRAIT",
    "SOUTH_CHINA_SEA",
    "RED_SEA_BAB_EL_MANDEB",
    "STRAIT_OF_HORMUZ",
    "BLACK_SEA",
    "KOREAN_PENINSULA",
)
REQUIRED_SOURCE_IDS = frozenset(
    {
        "cn_mfa_releases",
        "cn_mofcom_export_control",
        "un_sc_sanctions",
        "ofac_recent_actions",
        "bis_federal_register",
        "ustr_actions",
        "eu_council_sanctions",
        "eurlex_official_journal",
        "marad_msci",
        "ukmto_advisories",
        "gdelt_event_gkg",
        "un_conflict_releases",
        "us_state_releases",
        "eeas_releases",
    }
)
OPTIONAL_SOURCE_IDS = frozenset({"ocha_reliefweb"})
ALL_SOURCE_IDS = REQUIRED_SOURCE_IDS | OPTIONAL_SOURCE_IDS
# No source-specific parser or continuous-preflight receipt verifier is
# implemented in this checkout yet.  These registries are deliberately empty:
# root reachability and a self-authored manifest cannot promote production.
# A future source promotion must add executable parser code and receipt
# verification here in the same change that activates the source.
BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS = frozenset()
VERIFIED_GEOPOLITICAL_PREFLIGHT_RECEIPT_SOURCE_IDS = frozenset()
_STRUCTURED_SMOKE_ARTIFACT_ROOTS = (
    "economic_calendar",
    "geopolitical_events",
    "macro_snapshots",
    "market_breadth",
    "runtime_snapshots",
    "sector_snapshots",
)
_A_SHARE_TIMEZONE = ZoneInfo("Asia/Shanghai")
_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "data_sources"
    / "geopolitical_initial_source_manifest_v2.json"
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: Any) -> str:
    return (
        "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    )


def _without_hash(payload: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != field}


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(
            f"geopolitical {field} must be a non-empty timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataVendorUnavailable(f"geopolitical {field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DataVendorUnavailable(f"geopolitical {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _as_of_cutoff(as_of: str) -> datetime:
    try:
        local_date = date.fromisoformat(as_of)
    except ValueError as exc:
        raise DataVendorUnavailable("geopolitical as_of must be YYYY-MM-DD") from exc
    return datetime.combine(
        local_date, time(15, 0), tzinfo=_A_SHARE_TIMEZONE
    ).astimezone(timezone.utc)


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DataVendorUnavailable(f"geopolitical {field} must be a non-empty string")
    return value.strip()


def load_geopolitical_manifest(path: Path = _MANIFEST_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load geopolitical source manifest: {exc}") from exc
    return validate_geopolitical_manifest(payload)


def runtime_geopolitical_manifest() -> dict[str, Any]:
    """Load an operator-owned readiness manifest when one is explicitly bound.

    The committed manifest remains the fail-closed default.  A private runtime
    manifest is useful only after the required transport preflight has matured;
    it receives the same closure and hash validation as the public manifest.
    """
    explicit = os.getenv("MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST")
    if not explicit:
        return GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
    return load_geopolitical_manifest(Path(explicit).expanduser())


def validate_geopolitical_manifest(payload: Any) -> dict[str, Any]:
    """Validate source closure, adapter hashes and all actor/region routes."""
    if not isinstance(payload, dict):
        raise DataVendorUnavailable("geopolitical manifest must be an object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise DataVendorUnavailable("geopolitical manifest schema version mismatch")
    if payload.get("manifest_hash") != _canonical_hash(
        _without_hash(payload, "manifest_hash")
    ):
        raise DataVendorUnavailable("geopolitical manifest hash mismatch")
    if tuple(payload.get("active_event_types", ())) != EVENT_TYPES:
        raise DataVendorUnavailable("geopolitical active event type closure mismatch")
    if tuple(payload.get("watchlist_actor_ids", ())) != WATCHLIST_ACTORS:
        raise DataVendorUnavailable("geopolitical actor watchlist closure mismatch")
    if tuple(payload.get("watchlist_region_ids", ())) != WATCHLIST_REGIONS:
        raise DataVendorUnavailable("geopolitical region watchlist closure mismatch")
    if payload.get("raw_source_content_committed") is not False:
        raise DataVendorUnavailable(
            "geopolitical public manifest cannot contain source content"
        )

    registrations = payload.get("registrations")
    adapters = payload.get("adapter_contracts")
    publishers = payload.get("approved_publishers")
    routes = payload.get("coverage_routes")
    if not all(
        isinstance(rows, list) for rows in (registrations, adapters, publishers, routes)
    ):
        raise DataVendorUnavailable("geopolitical manifest arrays are required")

    registration_by_source: dict[str, dict[str, Any]] = {}
    for row in registrations:
        if not isinstance(row, dict):
            raise DataVendorUnavailable("geopolitical registrations must be objects")
        source_id = _required_string(row, "source_id")
        if source_id in registration_by_source:
            raise DataVendorUnavailable(f"duplicate geopolitical source {source_id}")
        if (
            row.get("source_backend") != "DIRECT"
            or row.get("tushare_endpoint_id") is not None
        ):
            raise DataVendorUnavailable(
                "geopolitical v2 sources cannot copy Tushare permission state"
            )
        if row.get("provider_kind") not in {
            "OFFICIAL_PRIMARY",
            "STRUCTURED_DISCOVERY",
            "OPTIONAL_CONTEXT",
        }:
            raise DataVendorUnavailable(f"invalid provider kind for {source_id}")
        if row.get("registration_status") not in {
            "ACTIVE_VERIFIED",
            "PREFLIGHT_REQUIRED",
            "DISABLED_CONTRACT",
        }:
            raise DataVendorUnavailable(f"invalid registration status for {source_id}")
        required = source_id in REQUIRED_SOURCE_IDS
        if row.get("required") is not required:
            raise DataVendorUnavailable(f"required status mismatch for {source_id}")
        event_types = row.get("required_for_event_types")
        if not isinstance(event_types, list) or any(
            item not in EVENT_TYPES for item in event_types
        ):
            raise DataVendorUnavailable(f"invalid event types for {source_id}")
        if not required and event_types:
            raise DataVendorUnavailable(
                "optional context cannot expand required event coverage"
            )
        preflight = row.get("preflight")
        if (
            not isinstance(preflight, dict)
            or preflight.get("required_continuous_days") != 30
        ):
            raise DataVendorUnavailable(
                f"{source_id} lacks a 30-day preflight contract"
            )
        status = preflight.get("status")
        if status not in {"READY", "PREFLIGHT_REQUIRED", "FAILED"}:
            raise DataVendorUnavailable(f"invalid preflight status for {source_id}")
        if row.get("registration_status") == "ACTIVE_VERIFIED":
            ready_fields = (
                preflight.get("status") == "READY",
                preflight.get("observed_continuous_days", 0) >= 30,
                isinstance(preflight.get("availability_ratio"), (int, float)),
                isinstance(preflight.get("p95_capture_lag_minutes"), (int, float)),
                preflight.get("schema_verified") is True,
                preflight.get("pagination_verified") is True,
                preflight.get("publication_time_verified") is True,
                preflight.get("license_verified") is True,
            )
            if not all(ready_fields):
                raise DataVendorUnavailable(
                    f"{source_id} activated without complete preflight"
                )
        registration_by_source[source_id] = row
    if set(registration_by_source) != ALL_SOURCE_IDS:
        raise DataVendorUnavailable("geopolitical initial source closure mismatch")

    adapter_by_id: dict[str, dict[str, Any]] = {}
    for row in adapters:
        if not isinstance(row, dict):
            raise DataVendorUnavailable("geopolitical adapters must be objects")
        adapter_id = _required_string(row, "adapter_contract_id")
        source_id = _required_string(row, "source_id")
        if adapter_id in adapter_by_id or source_id not in registration_by_source:
            raise DataVendorUnavailable("duplicate or orphan geopolitical adapter")
        if row.get("adapter_contract_hash") != _canonical_hash(
            _without_hash(row, "adapter_contract_hash")
        ):
            raise DataVendorUnavailable(f"adapter hash mismatch for {source_id}")
        registration = registration_by_source[source_id]
        if (
            registration.get("adapter_contract_id") != adapter_id
            or registration.get("adapter_contract_hash") != row["adapter_contract_hash"]
        ):
            raise DataVendorUnavailable(f"adapter binding mismatch for {source_id}")
        if not isinstance(row.get("covered_actor_ids"), list) or not isinstance(
            row.get("covered_region_ids"), list
        ):
            raise DataVendorUnavailable(f"adapter scope missing for {source_id}")
        if any(item not in EVENT_TYPES for item in row.get("covered_event_types", [])):
            raise DataVendorUnavailable(f"adapter event scope mismatch for {source_id}")
        if not isinstance(row.get("no_event_claim_capable"), bool):
            raise DataVendorUnavailable(
                f"adapter no-event capability missing for {source_id}"
            )
        adapter_by_id[adapter_id] = row
    if len(adapter_by_id) != len(registration_by_source):
        raise DataVendorUnavailable(
            "each geopolitical source needs exactly one adapter"
        )

    publisher_keys: set[tuple[str, str, str]] = set()
    for row in publishers:
        if not isinstance(row, dict):
            raise DataVendorUnavailable("approved publishers must be objects")
        key = (
            _required_string(row, "domain"),
            _required_string(row, "publisher_organization_id"),
            _required_string(row, "upstream_origin_family"),
        )
        if key in publisher_keys or row.get("independence_rule") != (
            "organization_and_upstream_origin_must_both_differ"
        ):
            raise DataVendorUnavailable("invalid approved publisher registry")
        publisher_keys.add(key)
    if len(publisher_keys) != len(registration_by_source):
        raise DataVendorUnavailable(
            "approved publisher registry must cover every source"
        )

    expected_route_keys = (
        {
            (event_type, "ACTOR", actor, None)
            for event_type in EVENT_TYPES
            for actor in WATCHLIST_ACTORS
        }
        | {
            (event_type, "REGION", None, region)
            for event_type in EVENT_TYPES
            for region in WATCHLIST_REGIONS
        }
        | {(event_type, "GLOBAL", None, None) for event_type in EVENT_TYPES}
    )
    route_keys: set[tuple[str, str, Any, Any]] = set()
    route_ids: set[str] = set()
    for row in routes:
        if not isinstance(row, dict):
            raise DataVendorUnavailable("geopolitical routes must be objects")
        route_id = _required_string(row, "coverage_route_id")
        if route_id in route_ids or row.get("coverage_route_hash") != _canonical_hash(
            _without_hash(row, "coverage_route_hash")
        ):
            raise DataVendorUnavailable("duplicate route or route hash mismatch")
        route_ids.add(route_id)
        key = (
            row.get("event_type"),
            row.get("subject_type"),
            row.get("actor_id"),
            row.get("region_id"),
        )
        if key in route_keys:
            raise DataVendorUnavailable("duplicate geopolitical coverage route")
        route_keys.add(key)
        subject_type = row.get("subject_type")
        if subject_type == "ACTOR" and (
            row.get("actor_id") not in WATCHLIST_ACTORS
            or row.get("region_id") is not None
        ):
            raise DataVendorUnavailable("invalid actor coverage route")
        if subject_type == "REGION" and (
            row.get("region_id") not in WATCHLIST_REGIONS
            or row.get("actor_id") is not None
        ):
            raise DataVendorUnavailable("invalid region coverage route")
        if subject_type == "GLOBAL" and (
            row.get("actor_id") is not None or row.get("region_id") is not None
        ):
            raise DataVendorUnavailable("invalid global coverage route")
        if row.get("applicability") == "NOT_APPLICABLE":
            if (
                row.get("applicability_reason_code") != "NO_REGISTERED_MATERIAL_LINK"
                or row.get("required_source_ids") != []
                or row.get("no_event_evidence_source_ids") != []
                or row.get("route_status") != "NOT_APPLICABLE"
            ):
                raise DataVendorUnavailable("invalid not-applicable route")
            continue
        if row.get("applicability") != "APPLICABLE":
            raise DataVendorUnavailable("coverage route applicability is required")
        expected_reason = {
            "ACTOR": "ISSUER_OR_TARGET_WATCHLIST_SCOPE",
            "REGION": "REGION_WATCHLIST_SCOPE",
            "GLOBAL": "MATERIAL_A_SHARE_TRANSMISSION_SCOPE",
        }.get(subject_type)
        if row.get("applicability_reason_code") != expected_reason:
            raise DataVendorUnavailable(
                "coverage route reason does not match subject type"
            )
        required_sources = row.get("required_source_ids")
        no_event_sources = row.get("no_event_evidence_source_ids")
        if (
            not isinstance(required_sources, list)
            or not required_sources
            or len(required_sources) != len(set(required_sources))
            or not isinstance(no_event_sources, list)
            or not no_event_sources
            or not set(no_event_sources).issubset(required_sources)
        ):
            raise DataVendorUnavailable(
                "applicable route lacks closed required/no-event sources"
            )
        for source_id in required_sources:
            registration = registration_by_source.get(source_id)
            if registration is None or not registration["required"]:
                raise DataVendorUnavailable(
                    f"route references unavailable source {source_id}"
                )
            adapter = adapter_by_id[registration["adapter_contract_id"]]
            if row["event_type"] not in adapter["covered_event_types"]:
                raise DataVendorUnavailable(
                    f"{source_id} does not cover route event type"
                )
            if (
                subject_type == "ACTOR"
                and row["actor_id"] not in adapter["covered_actor_ids"]
            ):
                raise DataVendorUnavailable(f"{source_id} does not cover route actor")
            if (
                subject_type == "REGION"
                and row["region_id"] not in adapter["covered_region_ids"]
            ):
                raise DataVendorUnavailable(f"{source_id} does not cover route region")
            if (
                subject_type == "GLOBAL"
                and adapter.get("global_scope_capable") is not True
            ):
                raise DataVendorUnavailable(f"{source_id} lacks global scope")
        for source_id in no_event_sources:
            registration = registration_by_source[source_id]
            adapter = adapter_by_id[registration["adapter_contract_id"]]
            if adapter.get("no_event_claim_capable") is not True:
                raise DataVendorUnavailable(
                    f"{source_id} cannot support no-event evidence"
                )
        statuses = {
            registration_by_source[source]["registration_status"]
            for source in required_sources
        }
        expected_status = (
            "ACTIVE_VERIFIED"
            if statuses == {"ACTIVE_VERIFIED"}
            else "PREFLIGHT_REQUIRED"
        )
        if row.get("route_status") != expected_status:
            raise DataVendorUnavailable(
                "coverage route readiness does not match source readiness"
            )
    if route_keys != expected_route_keys:
        raise DataVendorUnavailable(
            "geopolitical actor/region/global route closure mismatch"
        )

    expected_scope_hash = _canonical_hash(
        {
            "coverage_scope_version": payload.get("coverage_scope_version"),
            "watchlist_actor_ids": payload["watchlist_actor_ids"],
            "watchlist_region_ids": payload["watchlist_region_ids"],
            "coverage_routes": routes,
        }
    )
    if payload.get("coverage_scope_hash") != expected_scope_hash:
        raise DataVendorUnavailable("geopolitical coverage scope hash mismatch")
    expected_blockers: list[str] = []
    for source_id in sorted(REQUIRED_SOURCE_IDS):
        registration = registration_by_source[source_id]
        if registration["registration_status"] != "ACTIVE_VERIFIED":
            expected_blockers.append(f"{source_id}:30_day_preflight_required")
        if source_id not in BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS:
            expected_blockers.append(f"{source_id}:source_specific_parser_missing")
        if source_id not in VERIFIED_GEOPOLITICAL_PREFLIGHT_RECEIPT_SOURCE_IDS:
            expected_blockers.append(
                f"{source_id}:continuous_preflight_receipt_verifier_missing"
            )
    supplied_blockers = payload.get("readiness_blockers")
    if (
        not isinstance(supplied_blockers, list)
        or len(supplied_blockers) != len(set(supplied_blockers))
        or set(supplied_blockers) != set(expected_blockers)
    ):
        raise DataVendorUnavailable("geopolitical readiness blockers mismatch")
    expected_readiness = "READY" if not expected_blockers else "PREFLIGHT_REQUIRED"
    if payload.get("manifest_readiness") != expected_readiness:
        raise DataVendorUnavailable("geopolitical manifest readiness mismatch")
    return payload


GEOPOLITICAL_INITIAL_SOURCE_MANIFEST = load_geopolitical_manifest()


def geopolitical_store_path() -> Path:
    explicit = os.getenv("MOSAIC_GEOPOLITICAL_EVENT_DB")
    if explicit:
        return Path(explicit).expanduser()
    cache = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    return cache / "geopolitical_events" / "events.sqlite3"


def _structured_smoke_geopolitical_binding(as_of: str) -> bool:
    if os.getenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS") != "structured_smoke":
        return False
    cache_root = Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser()
    marker_path = cache_root / "structured_smoke_fixture_bundle.json"
    if marker_path.is_symlink():
        raise DataVendorUnavailable(
            "geopolitical structured-smoke fixture marker is unavailable"
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataVendorUnavailable(
            "geopolitical structured-smoke fixture marker is unavailable"
        ) from exc
    expected_fields = {
        "schema_version",
        "as_of_date",
        "fixture_class",
        "contains_vendor_prose",
        "cache_root",
        "geopolitical_manifest",
        "geopolitical_manifest_hash",
        "artifact_inventory",
        "artifact_inventory_hash",
        "bundle_hash",
    }
    if not isinstance(marker, dict) or set(marker) != expected_fields:
        raise DataVendorUnavailable(
            "geopolitical structured-smoke fixture marker fields mismatch"
        )
    body = {key: value for key, value in marker.items() if key != "bundle_hash"}
    manifest_path = os.getenv("MOSAIC_GEOPOLITICAL_SOURCE_MANIFEST")
    expected_bundle_hash = os.getenv(
        "MOSAIC_NON_PRODUCTION_FIXTURE_BUNDLE_HASH"
    )
    if (
        marker.get("schema_version") != "structured_smoke_fixture_bundle_v1"
        or marker.get("as_of_date") != as_of
        or marker.get("fixture_class") != "SYNTHETIC_NON_PRODUCTION"
        or marker.get("contains_vendor_prose") is not False
        or Path(str(marker.get("cache_root"))).resolve() != cache_root.resolve()
        or not manifest_path
        or Path(str(marker.get("geopolitical_manifest"))).resolve()
        != Path(manifest_path).expanduser().resolve()
        or marker.get("bundle_hash") != _canonical_hash(body)
        or not _is_sha256_string(expected_bundle_hash)
        or marker.get("bundle_hash") != expected_bundle_hash
    ):
        raise DataVendorUnavailable(
            "geopolitical structured-smoke fixture marker binding mismatch"
        )
    _validate_structured_smoke_artifact_inventory(cache_root, marker)
    manifest = runtime_geopolitical_manifest()
    if marker.get("geopolitical_manifest_hash") != manifest.get("manifest_hash"):
        raise DataVendorUnavailable(
            "geopolitical structured-smoke manifest hash mismatch"
        )
    return True


def _validate_structured_smoke_artifact_inventory(
    cache_root: Path, marker: Mapping[str, Any]
) -> None:
    supplied = marker.get("artifact_inventory")
    if not isinstance(supplied, list) or not supplied:
        raise DataVendorUnavailable(
            "geopolitical structured-smoke artifact inventory is empty"
        )
    normalized: list[dict[str, str]] = []
    for row in supplied:
        if not isinstance(row, dict) or set(row) != {
            "relative_path",
            "content_sha256",
        }:
            raise DataVendorUnavailable(
                "geopolitical structured-smoke artifact inventory row is invalid"
            )
        relative_path = row.get("relative_path")
        content_hash = row.get("content_sha256")
        if (
            not isinstance(relative_path, str)
            or not any(
                relative_path.startswith(f"{root}/")
                for root in _STRUCTURED_SMOKE_ARTIFACT_ROOTS
            )
            or "\\" in relative_path
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
            or not _is_sha256_string(content_hash)
        ):
            raise DataVendorUnavailable(
                "geopolitical structured-smoke artifact inventory row is invalid"
            )
        normalized.append(
            {"relative_path": relative_path, "content_sha256": content_hash}
        )
    expected_order = sorted(normalized, key=lambda row: row["relative_path"])
    if (
        normalized != expected_order
        or len({row["relative_path"] for row in normalized}) != len(normalized)
        or marker.get("artifact_inventory_hash") != _canonical_hash(normalized)
    ):
        raise DataVendorUnavailable(
            "geopolitical structured-smoke artifact inventory binding mismatch"
        )
    observed: list[dict[str, str]] = []
    try:
        for root_name in _STRUCTURED_SMOKE_ARTIFACT_ROOTS:
            directory = cache_root / root_name
            if directory.is_symlink() or not directory.is_dir():
                raise DataVendorUnavailable(
                    "geopolitical structured-smoke artifact directory is invalid"
                )
            for path in sorted(directory.rglob("*")):
                if path.is_symlink():
                    raise DataVendorUnavailable(
                        "geopolitical structured-smoke artifact tree contains a symlink"
                    )
                if path.is_dir():
                    continue
                if not path.is_file():
                    raise DataVendorUnavailable(
                        "geopolitical structured-smoke artifact tree contains a non-file entry"
                    )
                observed.append(
                    {
                        "relative_path": path.relative_to(cache_root).as_posix(),
                        "content_sha256": (
                            f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
                        ),
                    }
                )
    except OSError as exc:
        raise DataVendorUnavailable(
            "geopolitical structured-smoke artifact tree is unavailable"
        ) from exc
    observed.sort(key=lambda row: row["relative_path"])
    if observed != normalized:
        raise DataVendorUnavailable(
            "geopolitical structured-smoke artifact inventory mismatch"
        )


def _is_sha256_string(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def scope_query_hash(route: Mapping[str, Any], adapter: Mapping[str, Any]) -> str:
    return _canonical_hash(
        {
            "template": adapter["continuous_scope_query_template"],
            "event_type": route["event_type"],
            "subject_type": route["subject_type"],
            "actor_id": route.get("actor_id"),
            "region_id": route.get("region_id"),
        }
    )


def coverage_query_key(
    route: Mapping[str, Any], source_id: str, query_hash: str
) -> str:
    return _canonical_hash(
        {
            "coverage_route_id": route["coverage_route_id"],
            "coverage_route_hash": route["coverage_route_hash"],
            "source_id": source_id,
            "scope_query_hash": query_hash,
        }
    )


class GeopoliticalEventStore:
    """Append-only private ledger for poll evidence and event revisions."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_poll_observations (
                    observation_id TEXT PRIMARY KEY,
                    coverage_query_key TEXT NOT NULL,
                    poll_completed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS geo_poll_query_time
                  ON source_poll_observations(coverage_query_key, poll_completed_at);
                CREATE TABLE IF NOT EXISTS event_revisions (
                    event_revision_id TEXT PRIMARY KEY,
                    geopolitical_event_id TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS geo_event_time
                  ON event_revisions(geopolitical_event_id, retrieved_at);
                CREATE TRIGGER IF NOT EXISTS geo_polls_no_update
                  BEFORE UPDATE ON source_poll_observations BEGIN
                    SELECT RAISE(ABORT, 'source_poll_observations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS geo_polls_no_delete
                  BEFORE DELETE ON source_poll_observations BEGIN
                    SELECT RAISE(ABORT, 'source_poll_observations is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS geo_events_no_update
                  BEFORE UPDATE ON event_revisions BEGIN
                    SELECT RAISE(ABORT, 'event_revisions is append-only');
                  END;
                CREATE TRIGGER IF NOT EXISTS geo_events_no_delete
                  BEFORE DELETE ON event_revisions BEGIN
                    SELECT RAISE(ABORT, 'event_revisions is append-only');
                  END;
                """
            )

    def append_poll_observation(
        self, payload: Mapping[str, Any], *, manifest: Mapping[str, Any] | None = None
    ) -> None:
        manifest = manifest or GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
        row = validate_poll_observation(payload, manifest=manifest)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO source_poll_observations VALUES (?, ?, ?, ?)",
                    (
                        row["observation_id"],
                        row["coverage_query_key"],
                        row["poll_completed_at"],
                        _canonical_json(row),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = conn.execute(
                    "SELECT payload_json FROM source_poll_observations WHERE observation_id = ?",
                    (row["observation_id"],),
                ).fetchone()
                if existing is None or existing["payload_json"] != _canonical_json(row):
                    raise DataVendorUnavailable(
                        "conflicting geopolitical poll observation"
                    ) from exc

    def append_event_revision(
        self, payload: Mapping[str, Any], *, manifest: Mapping[str, Any] | None = None
    ) -> None:
        manifest = manifest or GEOPOLITICAL_INITIAL_SOURCE_MANIFEST
        row = validate_event_revision(payload, manifest=manifest)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO event_revisions VALUES (?, ?, ?, ?)",
                    (
                        row["event_revision_id"],
                        row["geopolitical_event_id"],
                        row["retrieved_at"],
                        _canonical_json(row),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = conn.execute(
                    "SELECT payload_json FROM event_revisions WHERE event_revision_id = ?",
                    (row["event_revision_id"],),
                ).fetchone()
                if existing is None or existing["payload_json"] != _canonical_json(row):
                    raise DataVendorUnavailable(
                        "conflicting geopolitical event revision"
                    ) from exc

    def polls_as_of(self, cutoff: datetime) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM source_poll_observations WHERE poll_completed_at <= ?",
                (cutoff.isoformat(),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def events_as_of(self, cutoff: datetime) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM event_revisions WHERE retrieved_at <= ?",
                (cutoff.isoformat(),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def _manifest_indexes(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    registrations = {row["source_id"]: row for row in manifest["registrations"]}
    adapters = {row["source_id"]: row for row in manifest["adapter_contracts"]}
    routes = {row["coverage_route_id"]: row for row in manifest["coverage_routes"]}
    return registrations, adapters, routes


def validate_poll_observation(
    payload: Mapping[str, Any], *, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    required = (
        "observation_id",
        "coverage_route_id",
        "coverage_route_hash",
        "source_id",
        "scope_query_hash",
        "coverage_query_key",
        "poll_started_at",
        "poll_completed_at",
        "http_status",
        "row_count",
        "pagination_complete",
        "truncated",
        "schema_hash",
        "response_content_hash",
        "ingestion_mode",
        "parse_result",
        "error_class",
        "coverage_evidence_id",
    )
    if not isinstance(payload, Mapping) or any(
        field not in payload for field in required
    ):
        raise DataVendorUnavailable(
            "geopolitical poll observation fields are incomplete"
        )
    row = {field: payload[field] for field in required}
    _, adapters, routes = _manifest_indexes(manifest)
    route = routes.get(row["coverage_route_id"])
    adapter = adapters.get(row["source_id"])
    if (
        route is None
        or adapter is None
        or row["source_id"] not in route["required_source_ids"]
    ):
        raise DataVendorUnavailable(
            "poll observation is outside the registered route/source scope"
        )
    if row["coverage_route_hash"] != route["coverage_route_hash"]:
        raise DataVendorUnavailable("poll observation route hash mismatch")
    expected_scope_hash = scope_query_hash(route, adapter)
    if row["scope_query_hash"] != expected_scope_hash or row[
        "coverage_query_key"
    ] != coverage_query_key(route, row["source_id"], expected_scope_hash):
        raise DataVendorUnavailable("poll observation query binding mismatch")
    started = _parse_datetime(row["poll_started_at"], "poll_started_at")
    completed = _parse_datetime(row["poll_completed_at"], "poll_completed_at")
    if completed < started:
        raise DataVendorUnavailable("poll completion precedes poll start")
    if not isinstance(row["http_status"], int) or not isinstance(row["row_count"], int):
        raise DataVendorUnavailable("poll status and row count must be integers")
    if (
        row["row_count"] < 0
        or not isinstance(row["pagination_complete"], bool)
        or not isinstance(row["truncated"], bool)
    ):
        raise DataVendorUnavailable("poll pagination fields are invalid")
    for field in (
        "observation_id",
        "schema_hash",
        "response_content_hash",
        "coverage_evidence_id",
    ):
        _required_string(row, field)
    if row["parse_result"] not in {"SUCCESS", "FAILED"}:
        raise DataVendorUnavailable("poll parse_result is invalid")
    if row["ingestion_mode"] not in {
        "PRODUCTION_REGISTERED_PARSER",
        "NON_PRODUCTION_CALLBACK",
    }:
        raise DataVendorUnavailable("poll ingestion_mode is invalid")
    if row["error_class"] is not None and not isinstance(row["error_class"], str):
        raise DataVendorUnavailable("poll error_class is invalid")
    return row


def validate_event_revision(
    payload: Mapping[str, Any], *, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    required = (
        "geopolitical_event_id",
        "event_revision_id",
        "supersedes_revision_id",
        "event_type",
        "lifecycle_status",
        "verification_status",
        "actors",
        "affected_regions",
        "affected_channels",
        "published_at",
        "effective_at",
        "first_seen_at",
        "retrieved_at",
        "time_status",
        "primary_source_tier",
        "source_evidence_ids",
        "evidence_bundle_id",
        "causal_dedupe_key",
        "normalized_content_hash",
        "evidence_catalog",
    )
    if not isinstance(payload, Mapping) or any(
        field not in payload for field in required
    ):
        raise DataVendorUnavailable("geopolitical event revision fields are incomplete")
    row = {field: payload[field] for field in required}
    if row["event_type"] not in manifest["active_event_types"]:
        raise DataVendorUnavailable("event type is not active")
    if row["lifecycle_status"] not in {
        "DISCOVERED",
        "ANNOUNCED",
        "EFFECTIVE",
        "ESCALATED",
        "DEESCALATED",
        "RESOLVED",
        "EXPIRED",
    } or row["verification_status"] not in {
        "OFFICIAL_CONFIRMED",
        "MULTISOURCE_CONFIRMED",
        "UNCONFIRMED",
        "CONFLICT",
    }:
        raise DataVendorUnavailable("event lifecycle or verification status is invalid")
    if (
        not isinstance(row["actors"], list)
        or not row["actors"]
        or any(not isinstance(item, str) or not item for item in row["actors"])
    ):
        raise DataVendorUnavailable("event actors must be non-empty")
    if not isinstance(row["affected_channels"], list) or not row["affected_channels"]:
        raise DataVendorUnavailable("event affected channels must be non-empty")
    if not isinstance(row["affected_regions"], list):
        raise DataVendorUnavailable("event affected regions must be an array")
    first_seen = _parse_datetime(row["first_seen_at"], "first_seen_at")
    retrieved = _parse_datetime(row["retrieved_at"], "retrieved_at")
    if retrieved < first_seen:
        raise DataVendorUnavailable("event retrieval precedes first seen time")
    published = None
    if row["published_at"] is not None:
        published = _parse_datetime(row["published_at"], "published_at")
        if published > first_seen or published > retrieved:
            raise DataVendorUnavailable(
                "event publication time cannot follow first-seen or retrieval time"
            )
    if row["effective_at"] is not None:
        _parse_datetime(row["effective_at"], "effective_at")
    if row["time_status"] == "VERIFIED" and published is None:
        raise DataVendorUnavailable("verified event time requires published_at")
    if row["time_status"] not in {"VERIFIED", "UNVERIFIED"}:
        raise DataVendorUnavailable("event time status is invalid")
    if not isinstance(row["evidence_catalog"], list) or not row["evidence_catalog"]:
        raise DataVendorUnavailable("event evidence catalog is required")
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    registrations, adapters, routes = _manifest_indexes(manifest)
    for evidence in row["evidence_catalog"]:
        if not isinstance(evidence, Mapping):
            raise DataVendorUnavailable("event evidence entries must be objects")
        evidence_id = _required_string(evidence, "evidence_id")
        source_id = _required_string(evidence, "source_id")
        if evidence_id in evidence_by_id or source_id not in registrations:
            raise DataVendorUnavailable("duplicate or unregistered event evidence")
        if row["event_type"] not in adapters[source_id]["covered_event_types"]:
            raise DataVendorUnavailable(
                "event evidence source does not cover event type"
            )
        if evidence.get("published_at") is not None:
            evidence_published = _parse_datetime(
                evidence["published_at"], "evidence published_at"
            )
            if evidence_published > retrieved:
                raise DataVendorUnavailable(
                    "event evidence publication time cannot follow retrieval time"
                )
        _required_string(evidence, "content_hash")
        evidence_by_id[evidence_id] = evidence
    if row["source_evidence_ids"] != list(evidence_by_id):
        raise DataVendorUnavailable(
            "event source evidence IDs must exactly bind the catalog order"
        )
    source_ids = [evidence["source_id"] for evidence in evidence_by_id.values()]
    provider_kinds = [registrations[source]["provider_kind"] for source in source_ids]
    expected_tier = (
        "OFFICIAL_PRIMARY"
        if "OFFICIAL_PRIMARY" in provider_kinds
        else "STRUCTURED_DISCOVERY"
        if "STRUCTURED_DISCOVERY" in provider_kinds
        else "OPTIONAL_CONTEXT"
    )
    if row["primary_source_tier"] != expected_tier:
        raise DataVendorUnavailable("event primary source tier is not evidence-derived")
    if (
        row["verification_status"] == "OFFICIAL_CONFIRMED"
        and "OFFICIAL_PRIMARY" not in provider_kinds
    ):
        raise DataVendorUnavailable("official confirmation requires official evidence")
    if row["verification_status"] == "MULTISOURCE_CONFIRMED":
        independent = {
            (
                registrations[source]["publisher_organization_id"],
                registrations[source]["upstream_origin_family"],
            )
            for source in source_ids
            if registrations[source]["provider_kind"] != "OPTIONAL_CONTEXT"
        }
        if len(independent) < 2:
            raise DataVendorUnavailable(
                "multisource confirmation lacks two independent sources"
            )
        content_hashes = {
            evidence["content_hash"] for evidence in evidence_by_id.values()
        }
        if len(content_hashes) < 2:
            raise DataVendorUnavailable(
                "mirrored content cannot confirm an event twice"
            )
    if row["verification_status"] == "UNCONFIRMED" and (
        not provider_kinds or set(provider_kinds) != {"STRUCTURED_DISCOVERY"}
    ):
        # Multiple discovery rows are allowed, but no official row may remain
        # labelled unconfirmed without an explicit conflict.
        if "OFFICIAL_PRIMARY" in provider_kinds:
            raise DataVendorUnavailable("official evidence cannot remain unconfirmed")
    for field in (
        "geopolitical_event_id",
        "event_revision_id",
        "evidence_bundle_id",
        "causal_dedupe_key",
        "normalized_content_hash",
    ):
        _required_string(row, field)
    if row["supersedes_revision_id"] is not None and not isinstance(
        row["supersedes_revision_id"], str
    ):
        raise DataVendorUnavailable("event supersedes revision ID is invalid")
    del row["evidence_catalog"]
    row["_evidence_catalog"] = [dict(item) for item in payload["evidence_catalog"]]
    return row


def build_geopolitical_events_snapshot(
    as_of: str,
    *,
    store: GeopoliticalEventStore | None = None,
    manifest: Mapping[str, Any] | None = None,
    allow_nonproduction_fixture: bool = False,
) -> dict[str, Any]:
    manifest = validate_geopolitical_manifest(
        dict(manifest or GEOPOLITICAL_INITIAL_SOURCE_MANIFEST)
    )
    store = store or GeopoliticalEventStore(geopolitical_store_path())
    cutoff = _as_of_cutoff(as_of)
    registrations, adapters, _ = _manifest_indexes(manifest)

    latest_poll: dict[str, dict[str, Any]] = {}
    for observation in store.polls_as_of(cutoff):
        current = latest_poll.get(observation["coverage_query_key"])
        if (
            current is None
            or observation["poll_completed_at"] > current["poll_completed_at"]
        ):
            latest_poll[observation["coverage_query_key"]] = observation

    route_source_coverage: list[dict[str, Any]] = []
    type_query_keys: dict[str, list[str]] = {
        event_type: [] for event_type in EVENT_TYPES
    }
    type_no_event_keys: dict[str, list[str]] = {
        event_type: [] for event_type in EVENT_TYPES
    }
    for route in manifest["coverage_routes"]:
        if route["applicability"] != "APPLICABLE":
            continue
        for source_id in route["required_source_ids"]:
            adapter = adapters[source_id]
            query_hash = scope_query_hash(route, adapter)
            query_key = coverage_query_key(route, source_id, query_hash)
            type_query_keys[route["event_type"]].append(query_key)
            if source_id in route["no_event_evidence_source_ids"]:
                type_no_event_keys[route["event_type"]].append(query_key)
            observation = latest_poll.get(query_key)
            status = "UNAVAILABLE"
            completed_at = None
            last_success = None
            observed_lag = None
            evidence_id = f"geo-coverage-missing:{query_key}"
            if observation is not None:
                completed_at = observation["poll_completed_at"]
                evidence_id = observation["coverage_evidence_id"]
                completed = _parse_datetime(completed_at, "poll_completed_at")
                age_minutes = (cutoff - completed).total_seconds() / 60
                if (
                    observation["schema_hash"]
                    != adapter["expected_response_schema_hash"]
                ):
                    status = "SCHEMA_DRIFT"
                elif (
                    observation["http_status"] < 200
                    or observation["http_status"] >= 300
                    or (
                        observation.get("ingestion_mode")
                        != "PRODUCTION_REGISTERED_PARSER"
                        and not (
                            allow_nonproduction_fixture
                            and observation.get("ingestion_mode")
                            == "NON_PRODUCTION_CALLBACK"
                        )
                    )
                    or observation["parse_result"] != "SUCCESS"
                    or observation["error_class"] is not None
                    or observation["pagination_complete"] is not True
                    or observation["truncated"] is True
                ):
                    status = "UNAVAILABLE"
                elif age_minutes > adapter["max_capture_age_minutes"]:
                    status = "STALE"
                    last_success = completed_at
                else:
                    status = "HEALTHY"
                    last_success = completed_at
            coverage = {
                "coverage_query_key": query_key,
                "coverage_route_id": route["coverage_route_id"],
                "coverage_route_hash": route["coverage_route_hash"],
                "event_type": route["event_type"],
                "source_id": source_id,
                "source_family": registrations[source_id]["upstream_origin_family"],
                "scope_query_hash": query_hash,
                "required": True,
                "poll_started_at": observation["poll_started_at"]
                if observation
                else cutoff.isoformat(),
                "poll_completed_at": completed_at,
                "last_successful_poll_at": last_success,
                "expected_poll_interval_minutes": adapter[
                    "expected_poll_interval_minutes"
                ],
                "max_capture_age_minutes": adapter["max_capture_age_minutes"],
                "observed_publication_lag_minutes": observed_lag,
                "status": status,
                "coverage_evidence_id": evidence_id,
                "subject_type": route["subject_type"],
                "actor_id": route["actor_id"],
                "region_id": route["region_id"],
            }
            route_source_coverage.append(coverage)

    latest_events: dict[str, dict[str, Any]] = {}
    for event in store.events_as_of(cutoff):
        if _parse_datetime(event["retrieved_at"], "retrieved_at") > cutoff:
            continue
        current = latest_events.get(event["geopolitical_event_id"])
        if current is None or event["retrieved_at"] > current["retrieved_at"]:
            latest_events[event["geopolitical_event_id"]] = event
    events: list[dict[str, Any]] = []
    content_hashes: set[str] = set()
    for event in sorted(
        latest_events.values(), key=lambda item: item["geopolitical_event_id"]
    ):
        if (
            event["published_at"] is not None
            and _parse_datetime(event["published_at"], "published_at") > cutoff
        ):
            continue
        if event["normalized_content_hash"] in content_hashes:
            raise DataVendorUnavailable(
                "duplicate normalized geopolitical event content"
            )
        content_hashes.add(event["normalized_content_hash"])
        events.append(
            {key: value for key, value in event.items() if not key.startswith("_")}
        )

    coverage_by_event_type: list[dict[str, Any]] = []
    for event_type in EVENT_TYPES:
        required_keys = sorted(set(type_query_keys[event_type]))
        rows = [row for row in route_source_coverage if row["event_type"] == event_type]
        healthy_keys = sorted(
            row["coverage_query_key"] for row in rows if row["status"] == "HEALTHY"
        )
        unhealthy_keys = sorted(set(required_keys) - set(healthy_keys))
        no_event_keys = sorted(set(type_no_event_keys[event_type]))
        event_present = any(event["event_type"] == event_type for event in events)
        query_complete = not unhealthy_keys and set(required_keys) == {
            row["coverage_query_key"] for row in rows
        }
        no_event_complete = set(no_event_keys).issubset(healthy_keys) and bool(
            no_event_keys
        )
        status = (
            "EVENTS_PRESENT"
            if event_present
            else "COVERAGE_CONFIRMED_NO_EVENT"
            if query_complete and no_event_complete
            else "COVERAGE_UNAVAILABLE"
        )
        coverage_by_event_type.append(
            {
                "event_type": event_type,
                "watchlist_scope_hash": manifest["coverage_scope_hash"],
                "required_query_keys": required_keys,
                "healthy_query_keys": healthy_keys,
                "unhealthy_query_keys": unhealthy_keys,
                "required_source_ids": sorted({row["source_id"] for row in rows}),
                "healthy_source_ids": sorted(
                    {row["source_id"] for row in rows if row["status"] == "HEALTHY"}
                ),
                "no_event_evidence_source_ids": sorted(
                    {
                        source
                        for route in manifest["coverage_routes"]
                        if route["event_type"] == event_type
                        and route["applicability"] == "APPLICABLE"
                        for source in route["no_event_evidence_source_ids"]
                    }
                ),
                "no_event_evidence_query_keys": no_event_keys,
                "query_complete": query_complete,
                "status": status,
                "coverage_evidence_ids": sorted(
                    {row["coverage_evidence_id"] for row in rows}
                ),
            }
        )

    complete = all(
        row["status"] != "COVERAGE_UNAVAILABLE" for row in coverage_by_event_type
    )
    manifest_ready = (
        manifest["manifest_readiness"] == "READY" or allow_nonproduction_fixture
    )
    snapshot = {
        "as_of": as_of,
        "event_registry_version": EVENT_REGISTRY_VERSION,
        "source_registry_version": manifest["source_registry_version"],
        "coverage_scope_version": manifest["coverage_scope_version"],
        "source_coverage_contract_version": manifest[
            "source_coverage_contract_version"
        ],
        "coverage_scope_hash": manifest["coverage_scope_hash"],
        "active_event_types": list(EVENT_TYPES),
        "registrations": manifest["registrations"],
        "route_source_coverage": sorted(
            route_source_coverage, key=lambda item: item["coverage_query_key"]
        ),
        "coverage_by_event_type": coverage_by_event_type,
        "events": events,
        "empty_state": (
            "EVENTS_PRESENT"
            if events
            else "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
            if complete and manifest_ready
            else "COVERAGE_INCOMPLETE"
        ),
        "readiness": "READY" if complete and manifest_ready else "REJECTED",
    }
    snapshot["snapshot_hash"] = _canonical_hash(snapshot)
    return snapshot


def load_geopolitical_events_snapshot(as_of: str) -> dict[str, Any]:
    manifest = runtime_geopolitical_manifest()
    allow_nonproduction_fixture = _structured_smoke_geopolitical_binding(as_of)
    snapshot = build_geopolitical_events_snapshot(
        as_of,
        manifest=manifest,
        allow_nonproduction_fixture=allow_nonproduction_fixture,
    )
    if snapshot["readiness"] != "READY":
        raise DataVendorUnavailable(
            "geopolitical snapshot rejected: a built-in source parser, verified "
            "continuous-preflight receipt, or route coverage is incomplete"
        )
    return snapshot


def build_geopolitical_role_snapshot(as_of: str) -> dict[str, Any]:
    """Project the full coverage audit into a bounded model-visible snapshot.

    Query keys, route rows and adapter registrations remain available in the
    private deterministic audit. The Agent receives event records plus exact
    per-family coverage counts and hashes, preserving the no-event proof
    without consuming the 128K model context with transport diagnostics.
    """
    snapshot = load_geopolitical_events_snapshot(as_of)
    coverage_rows = []
    for row in snapshot["coverage_by_event_type"]:
        evidence_hash = _canonical_hash(
            {
                "event_type": row["event_type"],
                "watchlist_scope_hash": row["watchlist_scope_hash"],
                "required_query_keys": row["required_query_keys"],
                "healthy_query_keys": row["healthy_query_keys"],
                "unhealthy_query_keys": row["unhealthy_query_keys"],
                "coverage_evidence_ids": row["coverage_evidence_ids"],
            }
        )
        coverage_rows.append(
            {
                "event_type": row["event_type"],
                "status": row["status"],
                "query_complete": row["query_complete"],
                "required_query_count": len(row["required_query_keys"]),
                "healthy_query_count": len(row["healthy_query_keys"]),
                "unhealthy_query_count": len(row["unhealthy_query_keys"]),
                "required_source_ids": row["required_source_ids"],
                "healthy_source_ids": row["healthy_source_ids"],
                "coverage_evidence_hash": evidence_hash,
                "evidence_id": (
                    "geopolitical-coverage:"
                    f"{evidence_hash.removeprefix('sha256:')}"
                ),
            }
        )
    projected: dict[str, Any] = {
        "schema_version": ROLE_SNAPSHOT_SCHEMA_VERSION,
        "role": "geopolitical",
        "as_of_date": as_of,
        "event_registry_version": snapshot["event_registry_version"],
        "source_registry_version": snapshot["source_registry_version"],
        "coverage_scope_version": snapshot["coverage_scope_version"],
        "coverage_scope_hash": snapshot["coverage_scope_hash"],
        "registration_statuses": [
            {
                "source_id": row["source_id"],
                "provider_kind": row["provider_kind"],
                "registration_status": row["registration_status"],
            }
            for row in snapshot["registrations"]
        ],
        "coverage_by_event_type": coverage_rows,
        "events": snapshot["events"],
        "empty_state": snapshot["empty_state"],
        "readiness": snapshot["readiness"],
        "direct_data_quality": 1.0,
        "evidence_id": f"geopolitical-role-snapshot:{as_of}",
    }
    projected["snapshot_hash"] = _canonical_hash(projected)
    return projected


def render_geopolitical_events_snapshot(as_of: str) -> str:
    return _canonical_json(load_geopolitical_events_snapshot(as_of))


__all__ = [
    "ALL_SOURCE_IDS",
    "BUILTIN_GEOPOLITICAL_PARSER_SOURCE_IDS",
    "EVENT_REGISTRY_VERSION",
    "EVENT_TYPES",
    "GEOPOLITICAL_INITIAL_SOURCE_MANIFEST",
    "GeopoliticalEventStore",
    "MANIFEST_SCHEMA_VERSION",
    "OPTIONAL_SOURCE_IDS",
    "REQUIRED_SOURCE_IDS",
    "ROLE_SNAPSHOT_SCHEMA_VERSION",
    "VERIFIED_GEOPOLITICAL_PREFLIGHT_RECEIPT_SOURCE_IDS",
    "WATCHLIST_ACTORS",
    "WATCHLIST_REGIONS",
    "build_geopolitical_events_snapshot",
    "build_geopolitical_role_snapshot",
    "coverage_query_key",
    "geopolitical_store_path",
    "load_geopolitical_events_snapshot",
    "load_geopolitical_manifest",
    "runtime_geopolitical_manifest",
    "render_geopolitical_events_snapshot",
    "scope_query_hash",
    "validate_event_revision",
    "validate_geopolitical_manifest",
    "validate_poll_observation",
]
