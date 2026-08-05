#!/usr/bin/env python3
"""Write a metadata-only root transport preflight for geopolitical sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_events import REQUIRED_SOURCE_IDS
from mosaic.dataflows.geopolitical_source_adapters import (
    GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION,
    probe_geopolitical_source_transport,
    registered_geopolitical_source_ids,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "registry"
    / "data_sources"
    / "geopolitical_source_transport_preflight_v1.json"
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_preflight(*, generated_at: str) -> dict[str, Any]:
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise ValueError("generated_at must include timezone")
    checks = []
    for source_id in registered_geopolitical_source_ids():
        try:
            checks.append(probe_geopolitical_source_transport(source_id))
        except DataVendorUnavailable as exc:
            checks.append(
                {
                    "source_id": source_id,
                    "required": source_id in REQUIRED_SOURCE_IDS,
                    "transport_status": "UNAVAILABLE",
                    "production_readiness": "BLOCKED",
                    "raw_source_content_committed": False,
                    "reason": str(exc),
                }
            )
    required = [row for row in checks if row.get("required") is True]
    body = {
        "schema_version": "geopolitical_source_transport_preflight_v1",
        "adapter_version": GEOPOLITICAL_TRANSPORT_ADAPTER_VERSION,
        "generated_at": generated.isoformat(),
        "raw_source_content_committed": False,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "active_transport_count": sum(
                row["transport_status"] == "ACTIVE" for row in checks
            ),
            "required_root_transport_ready": bool(required)
            and all(row["transport_status"] == "ACTIVE" for row in required),
            "production_event_coverage_ready": False,
            "production_blocker": (
                "route-complete polling, publication-time parsing, pagination, "
                "and 30 continuous days of health evidence are not established"
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
        f"{artifact['summary']['active_transport_count']}/"
        f"{artifact['summary']['check_count']}"
    )
    return 0 if artifact["summary"]["required_root_transport_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
