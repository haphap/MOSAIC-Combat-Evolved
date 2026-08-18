#!/usr/bin/env python3
"""Probe active ECB history adapters without persisting provider rows."""

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
    EU_REAL_ECONOMY_SERIES_MAP,
)
from mosaic.dataflows.official_macro_adapters import (
    OFFICIAL_MACRO_ADAPTER_VERSION,
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
        set(EU_REAL_ECONOMY_SERIES_MAP)
        | {
            item
            for values in EURO_AREA_FINANCIAL_SERIES_MAP.values()
            for item in values
            if not item.startswith("official.") and not item.startswith("tushare.")
        }
    )


def build_preflight(*, generated_at: str, as_of_date: str) -> dict[str, Any]:
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise ValueError("generated_at must include timezone")
    as_of = datetime.fromisoformat(as_of_date).date()
    cutoff = datetime.combine(as_of, time.max, tzinfo=timezone.utc).isoformat()
    observation_start = datetime(
        as_of.year - 1, 1, 1, tzinfo=timezone.utc
    ).date().isoformat()
    observation_end = as_of.isoformat()
    targets = [
        *(('ECB', series_id) for series_id in _ecb_series()),
    ]
    checks = []
    for provider, series_key in targets:
        try:
            kwargs: dict[str, Any] = {
                "provider": provider,
                "series_key": series_key,
                "as_of": cutoff,
            }
            kwargs.update(
                {
                    "include_history": True,
                    "observation_start": observation_start,
                    "observation_end": observation_end,
                }
            )
            result = fetch_official_series(**kwargs)
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
                "reason": "authoritative_vintage_history_transport_verified",
            }
        )
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
                row["transport_status"] == "ACTIVE" for row in checks
            ),
            "production_snapshot_ready": False,
            "production_blocker": (
                "archive receipts and route eligibility are not established by transport preflight"
            ),
        },
    }
    return {**body, "preflight_hash": canonical_hash(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at")
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat()
    artifact = build_preflight(generated_at=generated_at, as_of_date=args.as_of)
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
