#!/usr/bin/env python3
"""Probe closed EU/ECB/World Bank adapters without persisting provider rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.macro_source_contracts import (
    EURO_AREA_FINANCIAL_SERIES_MAP,
    EU_SERIES_MAP,
)
from mosaic.dataflows.official_macro_adapters import (
    OFFICIAL_MACRO_ADAPTER_VERSION,
    WORLD_BANK_EU_CONTEXT_SERIES,
    fetch_official_series,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "registry" / "data_sources" / "official_macro_source_preflight_v1.json"
)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _ecb_series() -> list[str]:
    return sorted(
        {
            item
            for values in EURO_AREA_FINANCIAL_SERIES_MAP.values()
            for item in values
            if not item.startswith("official.") and not item.startswith("tushare.")
        }
    )


def build_preflight(*, generated_at: str) -> dict[str, Any]:
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise ValueError("generated_at must include timezone")
    cutoff = datetime.combine(generated.date(), time.max, tzinfo=timezone.utc).isoformat()
    targets = [
        *(('EUROSTAT', series_key) for series_key in sorted(EU_SERIES_MAP)),
        *(('ECB', series_id) for series_id in _ecb_series()),
        *(('WORLD_BANK', series_key) for series_key in sorted(WORLD_BANK_EU_CONTEXT_SERIES)),
    ]
    checks = []
    for provider, series_key in targets:
        try:
            result = fetch_official_series(
                provider=provider,
                series_key=series_key,
                as_of=cutoff,
            )
        except DataVendorUnavailable as exc:
            checks.append(
                {
                    "provider": provider,
                    "series_key": series_key,
                    "transport_status": "UNAVAILABLE",
                    "snapshot_readiness": "BLOCKED",
                    "reason": str(exc),
                }
            )
            continue
        checks.append(
            {
                key: result[key]
                for key in (
                    "provider",
                    "series_key",
                    "source",
                    "usage_mode",
                    "request_url",
                    "content_type",
                    "retrieved_at",
                    "payload_hash",
                    "row_count",
                    "elapsed_ms",
                    "pit_status",
                )
            }
            | {
                "transport_status": "ACTIVE",
                "snapshot_readiness": "PREFLIGHT_ONLY",
                "reason": "release_timestamp_and_archived_vintage_join_required",
            }
        )
    required = [
        row for row in checks if row["provider"] in {"EUROSTAT", "ECB"}
    ]
    body = {
        "schema_version": "official_macro_source_preflight_v1",
        "adapter_version": OFFICIAL_MACRO_ADAPTER_VERSION,
        "generated_at": generated.isoformat(),
        "raw_provider_rows_committed": False,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "active_transport_count": sum(
                row["transport_status"] == "ACTIVE" for row in checks
            ),
            "required_transport_ready": all(
                row["transport_status"] == "ACTIVE" for row in required
            ),
            "production_snapshot_ready": False,
            "production_blocker": (
                "archived release/vintage coverage is not established by a live transport probe"
            ),
        },
    }
    return {**body, "preflight_hash": canonical_hash(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat()
    artifact = build_preflight(generated_at=generated_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.out} active="
        f"{artifact['summary']['active_transport_count']}/{artifact['summary']['check_count']}"
    )
    return 0 if artifact["summary"]["required_transport_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
