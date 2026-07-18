#!/usr/bin/env python3
"""Generate the closed geopolitical source and coverage manifest.

The manifest intentionally starts fail-closed.  A source may move from
``PREFLIGHT_REQUIRED`` to ``ACTIVE_VERIFIED`` only after its append-only local
poll ledger proves the registered 30-day availability and latency contract.
This generator never performs network I/O and never writes source prose.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    ROOT / "registry" / "data_sources" / "geopolitical_initial_source_manifest_v2.json"
)

SCHEMA_VERSION = "geopolitical_initial_source_manifest_v2"
SOURCE_REGISTRY_VERSION = "geopolitical_source_registry_v2"
COVERAGE_SCOPE_VERSION = "geopolitical_coverage_scope_v2"
SOURCE_COVERAGE_CONTRACT_VERSION = "geopolitical_source_coverage_v2"

EVENT_TYPES = (
    "SANCTION",
    "EXPORT_CONTROL",
    "TARIFF_TRADE_RESTRICTION",
    "ARMED_CONFLICT",
    "SHIPPING_DISRUPTION",
    "DIPLOMATIC_ESCALATION",
    "DIPLOMATIC_DEESCALATION",
)
ACTORS = ("CN", "US", "EU", "RU", "UA", "IR", "IL", "KP", "KR")
REGIONS = (
    "TAIWAN_STRAIT",
    "SOUTH_CHINA_SEA",
    "RED_SEA_BAB_EL_MANDEB",
    "STRAIT_OF_HORMUZ",
    "BLACK_SEA",
    "KOREAN_PENINSULA",
)


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "cn_mfa_releases": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "CN_MFA",
        "origin": "CN_MFA",
        "domain": "mfa.gov.cn",
        "url": "https://www.mfa.gov.cn/web/zyxw/",
        "mode": "HTML_DIRECTORY",
        "events": (
            "SANCTION",
            "EXPORT_CONTROL",
            "TARIFF_TRADE_RESTRICTION",
            "ARMED_CONFLICT",
            "DIPLOMATIC_ESCALATION",
            "DIPLOMATIC_DEESCALATION",
        ),
    },
    "cn_mofcom_export_control": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "CN_MOFCOM",
        "origin": "CN_MOFCOM",
        "domain": "mofcom.gov.cn",
        "url": "https://aqygzj.mofcom.gov.cn/",
        "mode": "HTML_DIRECTORY",
        "events": ("SANCTION", "EXPORT_CONTROL", "TARIFF_TRADE_RESTRICTION"),
    },
    "un_sc_sanctions": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "UN",
        "origin": "UN_SECURITY_COUNCIL",
        "domain": "un.org",
        "url": "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
        "mode": "FILE_FEED",
        "events": ("SANCTION",),
    },
    "ofac_recent_actions": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "US_TREASURY_OFAC",
        "origin": "US_TREASURY_OFAC",
        "domain": "ofac.treasury.gov",
        "url": "https://ofac.treasury.gov/recent-actions",
        "mode": "HTML_DIRECTORY",
        "events": ("SANCTION",),
    },
    "bis_federal_register": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "US_COMMERCE_BIS",
        "origin": "US_COMMERCE_BIS",
        "domain": "bis.gov",
        "url": "https://www.bis.gov/regulations/federal-register-notices",
        "mode": "HTML_DIRECTORY",
        "events": ("EXPORT_CONTROL",),
    },
    "ustr_actions": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "USTR",
        "origin": "USTR",
        "domain": "ustr.gov",
        "url": "https://ustr.gov/issue-areas/enforcement/section-301-investigations",
        "mode": "HTML_DIRECTORY",
        "events": ("TARIFF_TRADE_RESTRICTION",),
    },
    "eu_council_sanctions": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "EU_COUNCIL",
        "origin": "EU_COUNCIL",
        "domain": "consilium.europa.eu",
        "url": "https://www.consilium.europa.eu/en/policies/sanctions/",
        "mode": "HTML_DIRECTORY",
        "events": ("SANCTION", "EXPORT_CONTROL", "TARIFF_TRADE_RESTRICTION"),
    },
    "eurlex_official_journal": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "EU_PUBLICATIONS_OFFICE",
        "origin": "EUR_LEX",
        "domain": "eur-lex.europa.eu",
        "url": "https://eur-lex.europa.eu/oj/direct-access.html",
        "mode": "HTML_DIRECTORY",
        "events": ("SANCTION", "EXPORT_CONTROL", "TARIFF_TRADE_RESTRICTION"),
    },
    "marad_msci": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "US_MARAD",
        "origin": "US_MARAD",
        "domain": "maritime.dot.gov",
        "url": "https://www.maritime.dot.gov/msci-advisories",
        "mode": "HTML_DIRECTORY",
        "events": ("SHIPPING_DISRUPTION",),
    },
    "ukmto_advisories": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "UKMTO",
        "origin": "UKMTO",
        "domain": "ukmto.org",
        "url": "https://www.ukmto.org/indian-ocean/recent-incidents",
        "mode": "HTML_DIRECTORY",
        "events": ("SHIPPING_DISRUPTION",),
    },
    "gdelt_event_gkg": {
        "kind": "STRUCTURED_DISCOVERY",
        "organization": "GDELT_PROJECT",
        "origin": "GDELT",
        "domain": "gdeltproject.org",
        "url": "https://data.gdeltproject.org/gdeltv2/lastupdate.txt",
        "mode": "FILE_FEED",
        "events": EVENT_TYPES,
    },
    "un_conflict_releases": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "UN",
        "origin": "UN_NEWS_CONFLICT",
        "domain": "un.org",
        "url": "https://press.un.org/en/content/security-council/press-release",
        "mode": "HTML_DIRECTORY",
        "events": ("ARMED_CONFLICT",),
    },
    "us_state_releases": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "US_STATE",
        "origin": "US_STATE",
        "domain": "state.gov",
        "url": "https://www.state.gov/press-releases/",
        "mode": "HTML_DIRECTORY",
        "events": (
            "ARMED_CONFLICT",
            "DIPLOMATIC_ESCALATION",
            "DIPLOMATIC_DEESCALATION",
        ),
    },
    "eeas_releases": {
        "kind": "OFFICIAL_PRIMARY",
        "organization": "EEAS",
        "origin": "EEAS",
        "domain": "eeas.europa.eu",
        "url": "https://www.eeas.europa.eu/eeas/press-material_en",
        "mode": "HTML_DIRECTORY",
        "events": (
            "ARMED_CONFLICT",
            "DIPLOMATIC_ESCALATION",
            "DIPLOMATIC_DEESCALATION",
        ),
    },
    "ocha_reliefweb": {
        "kind": "OPTIONAL_CONTEXT",
        "organization": "UN_OCHA",
        "origin": "RELIEFWEB_PARTNER_NETWORK",
        "domain": "reliefweb.int",
        "url": "https://api.reliefweb.int/v2/reports",
        "mode": "API",
        "events": ("ARMED_CONFLICT",),
        "required": False,
        "no_event": False,
    },
}

EVENT_SOURCE_MAP = {
    "SANCTION": (
        "cn_mfa_releases",
        "cn_mofcom_export_control",
        "un_sc_sanctions",
        "ofac_recent_actions",
        "eu_council_sanctions",
        "eurlex_official_journal",
        "gdelt_event_gkg",
    ),
    "EXPORT_CONTROL": (
        "cn_mfa_releases",
        "cn_mofcom_export_control",
        "bis_federal_register",
        "eu_council_sanctions",
        "eurlex_official_journal",
        "gdelt_event_gkg",
    ),
    "TARIFF_TRADE_RESTRICTION": (
        "cn_mfa_releases",
        "cn_mofcom_export_control",
        "ustr_actions",
        "eu_council_sanctions",
        "eurlex_official_journal",
        "gdelt_event_gkg",
    ),
    "ARMED_CONFLICT": (
        "gdelt_event_gkg",
        "un_conflict_releases",
        "us_state_releases",
        "eeas_releases",
    ),
    "SHIPPING_DISRUPTION": ("marad_msci", "ukmto_advisories", "gdelt_event_gkg"),
    "DIPLOMATIC_ESCALATION": (
        "cn_mfa_releases",
        "us_state_releases",
        "eeas_releases",
        "gdelt_event_gkg",
    ),
    "DIPLOMATIC_DEESCALATION": (
        "cn_mfa_releases",
        "us_state_releases",
        "eeas_releases",
        "gdelt_event_gkg",
    ),
}


def build_manifest() -> dict[str, Any]:
    adapters: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    publishers: list[dict[str, Any]] = []
    for source_id, spec in sorted(SOURCE_SPECS.items()):
        contract_id = f"geo_adapter:{source_id}:v2"
        adapter = {
            "adapter_contract_id": contract_id,
            "adapter_contract_version": "geopolitical_source_adapter_v2",
            "source_id": source_id,
            "canonical_url_or_api": spec["url"],
            "retrieval_mode": spec["mode"],
            "pagination_or_cursor_contract": "append-only cursor or complete directory enumeration; reject detected truncation",
            "continuous_scope_query_template": "event_type={event_type};subject_type={subject_type};actor_id={actor_id};region_id={region_id}",
            "covered_actor_ids": list(ACTORS),
            "covered_region_ids": list(REGIONS),
            "global_scope_capable": True,
            "covered_event_types": list(spec["events"]),
            "source_time_zone": "UTC",
            "published_at_field": "source_published_at_or_verified_first_seen_at",
            "license_classification": "public_metadata_and_hash_only",
            "expected_poll_interval_minutes": 15
            if source_id == "gdelt_event_gkg"
            else 240,
            "max_capture_age_minutes": 45 if source_id == "gdelt_event_gkg" else 720,
            "truncation_detection_contract": "complete pagination/cursor closure and stable terminal marker required",
            "no_event_claim_capable": bool(spec.get("no_event", True)),
            "expected_response_schema_hash": canonical_hash(
                {"source_id": source_id, "contract": "metadata_v2"}
            ),
        }
        adapter["adapter_contract_hash"] = canonical_hash(adapter)
        adapters.append(adapter)
        required = bool(spec.get("required", True))
        registration = {
            "source_id": source_id,
            "provider_kind": spec["kind"],
            "registration_status": "PREFLIGHT_REQUIRED",
            "source_contract_version": "geopolitical_source_registration_v2",
            "adapter_contract_id": contract_id,
            "adapter_contract_hash": adapter["adapter_contract_hash"],
            "required": required,
            "required_for_event_types": list(spec["events"]) if required else [],
            "publisher_organization_id": spec["organization"],
            "upstream_origin_family": spec["origin"],
            "source_backend": "DIRECT",
            "tushare_endpoint_id": None,
            "preflight": {
                "status": "PREFLIGHT_REQUIRED",
                "required_continuous_days": 30,
                "observed_continuous_days": 0,
                "window_started_at": None,
                "window_completed_at": None,
                "availability_ratio": None,
                "p95_capture_lag_minutes": None,
                "schema_verified": False,
                "pagination_verified": False,
                "publication_time_verified": False,
                "license_verified": False,
                "evidence_id": f"geo-preflight:{source_id}:not-started",
            },
        }
        registrations.append(registration)
        publishers.append(
            {
                "domain": spec["domain"],
                "publisher_organization_id": spec["organization"],
                "allowed_event_types": list(spec["events"]),
                "upstream_origin_family": spec["origin"],
                "independence_rule": "organization_and_upstream_origin_must_both_differ",
            }
        )

    routes: list[dict[str, Any]] = []
    for event_type in EVENT_TYPES:
        for subject_type, subjects in (
            ("ACTOR", ACTORS),
            ("REGION", REGIONS),
            ("GLOBAL", (None,)),
        ):
            for subject in subjects:
                route_key = {
                    "event_type": event_type,
                    "subject_type": subject_type,
                    "actor_id": subject if subject_type == "ACTOR" else None,
                    "region_id": subject if subject_type == "REGION" else None,
                }
                route_id = (
                    "geo-route:"
                    + canonical_hash(route_key).removeprefix("sha256:")[:24]
                )
                applicable = not (
                    event_type == "SHIPPING_DISRUPTION" and subject_type == "ACTOR"
                )
                route: dict[str, Any] = {
                    "coverage_route_id": route_id,
                    "event_type": event_type,
                    "subject_type": subject_type,
                    "actor_id": route_key["actor_id"],
                    "region_id": route_key["region_id"],
                    "actor_official_source_id": None,
                }
                if applicable:
                    reason = {
                        "ACTOR": "ISSUER_OR_TARGET_WATCHLIST_SCOPE",
                        "REGION": "REGION_WATCHLIST_SCOPE",
                        "GLOBAL": "MATERIAL_A_SHARE_TRANSMISSION_SCOPE",
                    }[subject_type]
                    required_sources = list(EVENT_SOURCE_MAP[event_type])
                    route.update(
                        {
                            "applicability": "APPLICABLE",
                            "applicability_reason_code": reason,
                            "required_source_ids": required_sources,
                            "no_event_evidence_source_ids": required_sources,
                            "route_status": "PREFLIGHT_REQUIRED",
                        }
                    )
                else:
                    route.update(
                        {
                            "applicability": "NOT_APPLICABLE",
                            "applicability_reason_code": "NO_REGISTERED_MATERIAL_LINK",
                            "required_source_ids": [],
                            "no_event_evidence_source_ids": [],
                            "route_status": "NOT_APPLICABLE",
                        }
                    )
                route["coverage_route_hash"] = canonical_hash(route)
                routes.append(route)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_registry_version": SOURCE_REGISTRY_VERSION,
        "coverage_scope_version": COVERAGE_SCOPE_VERSION,
        "source_coverage_contract_version": SOURCE_COVERAGE_CONTRACT_VERSION,
        "active_event_types": list(EVENT_TYPES),
        "watchlist_actor_ids": list(ACTORS),
        "watchlist_region_ids": list(REGIONS),
        "registrations": registrations,
        "adapter_contracts": adapters,
        "approved_publishers": publishers,
        "coverage_routes": routes,
        "manifest_readiness": "PREFLIGHT_REQUIRED",
        "readiness_blockers": [
            f"{source_id}:30_day_preflight_required"
            for source_id, spec in sorted(SOURCE_SPECS.items())
            if spec.get("required", True)
        ],
        "raw_source_content_committed": False,
    }
    manifest["coverage_scope_hash"] = canonical_hash(
        {
            "coverage_scope_version": COVERAGE_SCOPE_VERSION,
            "watchlist_actor_ids": manifest["watchlist_actor_ids"],
            "watchlist_region_ids": manifest["watchlist_region_ids"],
            "coverage_routes": routes,
        }
    )
    manifest["manifest_hash"] = canonical_hash(manifest)
    return manifest


def main() -> None:
    payload = build_manifest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)} {payload['manifest_hash']}")


if __name__ == "__main__":
    main()
