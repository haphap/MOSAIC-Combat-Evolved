"""Closed, versioned Tushare endpoint registry for the v2 agent runtime.

SDK method presence is not permission evidence.  An endpoint is usable only
after a real permission/schema/PIT smoke promotes it to ``ACTIVE_VERIFIED``.
The four operator-confirmed unavailable document endpoints are permanently
disabled in this revision and are never probed at startup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable, Literal

TUSHARE_ENDPOINT_REGISTRY_VERSION = "tushare_endpoint_registry_v2"
TUSHARE_PREFLIGHT_SCHEMA_VERSION = "tushare_endpoint_preflight_v2"
TushareEndpointStatus = Literal[
    "ACTIVE_VERIFIED",
    "PRECHECK_REQUIRED",
    "DISABLED_PERMISSION_DENIED",
]

OPERATOR_DISABLED_PERMISSION_ENDPOINTS = frozenset(
    {"major_news", "news", "npr", "monetary_policy"}
)

# This is the exact closure required by plan §6.1.  Unknown endpoint strings
# are denied even if the installed Tushare SDK happens to implement them.
TUSHARE_ENDPOINT_IDS: tuple[str, ...] = (
    "eco_cal",
    "cn_pmi",
    "cn_gdp",
    "cn_cpi",
    "cn_ppi",
    "shibor",
    "shibor_quote",
    "yc_cb",
    "us_tycr",
    "trade_cal",
    "stock_basic",
    "stock_st",
    "daily",
    "daily_basic",
    "adj_factor",
    "suspend_d",
    "stk_limit",
    "index_basic",
    "index_classify",
    "index_member_all",
    "index_daily",
    "index_weight",
    "fund_basic",
    "etf_index",
    "fund_daily",
    "fund_adj",
    "fund_nav",
    "fund_share",
    "fund_portfolio",
    "fut_basic",
    "fut_daily",
    "fut_wsr",
    "fx_obasic",
    "fx_daily",
    "moneyflow",
    "moneyflow_ind_ths",
    "top_list",
    "top10_holders",
    "top10_floatholders",
    "stock_company",
    "fina_indicator",
    "forecast",
    "express",
    "income",
    "balancesheet",
    "cashflow",
    "fina_mainbz",
    "disclosure_date",
    "research_report",
    "major_news",
    "news",
    "npr",
    "monetary_policy",
)

_DOC_IDS: dict[str, str] = {
    "daily": "27",
    "index_classify": "181",
    "index_member_all": "335",
    "moneyflow": "170",
    "moneyflow_ind_ths": "343",
    "stock_st": "397",
    "eco_cal": "233",
    "fx_obasic": "178",
    "fx_daily": "179",
    "us_tycr": "219",
    "disclosure_date": "162",
}

_PREFLIGHT_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "data_sources"
    / "tushare_endpoint_preflight_v2.json"
)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load_preflight_checks(path: Path = _PREFLIGHT_PATH) -> dict[str, dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load Tushare preflight registry: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != TUSHARE_PREFLIGHT_SCHEMA_VERSION
        or payload.get("registry_version") != TUSHARE_ENDPOINT_REGISTRY_VERSION
    ):
        raise RuntimeError("Tushare preflight registry version mismatch")
    without_hash = {
        key: value for key, value in payload.items() if key != "artifact_hash"
    }
    if payload.get("artifact_hash") != _canonical_hash(without_hash):
        raise RuntimeError("Tushare preflight registry hash mismatch")
    rows = payload.get("checks")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Tushare preflight registry has no checks")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Tushare preflight rows must be objects")
        endpoint = row.get("endpoint")
        status = row.get("status")
        permission_result = row.get("permission_result")
        observed_row_count = row.get("observed_row_count")
        if (
            endpoint not in TUSHARE_ENDPOINT_IDS
            or endpoint in result
            or status
            not in {
                "ACTIVE_VERIFIED",
                "PRECHECK_REQUIRED",
                "DISABLED_PERMISSION_DENIED",
            }
            or permission_result
            not in {
                "NON_EMPTY_RESPONSE",
                "EMPTY_RESPONSE",
                "TRUNCATION_RISK",
                "PERMISSION_DENIED",
            }
            or row.get("pit_assessment") not in {"LOCAL_CAPTURE_ONLY", "NOT_APPLICABLE"}
            or row.get("raw_payload_committed") is not False
            or not isinstance(observed_row_count, int)
            or observed_row_count < 0
        ):
            raise RuntimeError(f"invalid Tushare preflight row: {endpoint!r}")
        for field in (
            "permission_checked_at",
            "permission_evidence_id",
            "schema_contract_version",
        ):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise RuntimeError(f"Tushare preflight {endpoint} lacks {field}")
        expected_columns = row.get("expected_columns")
        if (
            not isinstance(expected_columns, list)
            or permission_result in {"NON_EMPTY_RESPONSE", "TRUNCATION_RISK"}
            and not expected_columns
            or len(expected_columns) != len(set(expected_columns))
            or any(
                not isinstance(column, str) or not column for column in expected_columns
            )
        ):
            raise RuntimeError(f"Tushare preflight {endpoint} has invalid columns")
        coverage_smoke = row.get("coverage_smoke")
        if not isinstance(coverage_smoke, dict):
            raise RuntimeError(f"Tushare preflight {endpoint} lacks coverage smoke")
        if status == "ACTIVE_VERIFIED":
            if (
                permission_result != "NON_EMPTY_RESPONSE"
                or observed_row_count < 1
                or coverage_smoke.get("status") != "COMPLETE"
                or coverage_smoke.get("truncated_leaf_count") != 0
                or not isinstance(coverage_smoke.get("query_count"), int)
                or coverage_smoke["query_count"] < 1
                or endpoint == "eco_cal"
                and coverage_smoke.get("registered_currency_count") != 10
            ):
                raise RuntimeError(
                    f"Tushare preflight {endpoint} lacks complete coverage smoke"
                )
        elif status == "DISABLED_PERMISSION_DENIED":
            if permission_result != "PERMISSION_DENIED" or observed_row_count != 0:
                raise RuntimeError(f"invalid permission denial evidence for {endpoint}")
        elif coverage_smoke.get("status") not in {
            "PERMISSION_SCHEMA_ONLY",
            "EMPTY_RESPONSE",
            "TRUNCATION_RISK",
        }:
            raise RuntimeError(f"invalid precheck coverage status for {endpoint}")
        result[endpoint] = row
    return result


PREFLIGHT_ENDPOINT_CHECKS = _load_preflight_checks()
VERIFIED_ENDPOINT_PREFLIGHTS = {
    endpoint: row
    for endpoint, row in PREFLIGHT_ENDPOINT_CHECKS.items()
    if row["status"] == "ACTIVE_VERIFIED"
}
DYNAMIC_PERMISSION_DENIAL_ENDPOINTS = frozenset(
    endpoint
    for endpoint, row in PREFLIGHT_ENDPOINT_CHECKS.items()
    if row["status"] == "DISABLED_PERMISSION_DENIED"
    and endpoint not in OPERATOR_DISABLED_PERMISSION_ENDPOINTS
)
DISABLED_PERMISSION_ENDPOINTS = (
    OPERATOR_DISABLED_PERMISSION_ENDPOINTS | DYNAMIC_PERMISSION_DENIAL_ENDPOINTS
)


@dataclass(frozen=True)
class TushareEndpointRegistration:
    endpoint: str
    status: TushareEndpointStatus
    permission_checked_at: str | None
    permission_evidence_id: str | None
    schema_contract_version: str | None
    runtime_client_enabled: bool
    agent_tool_exposed: Literal[False] = False
    doc_url: str = "https://tushare.pro/document/1?doc_id=108"
    point_in_time_rule: str = "release/announcement/first-seen time and every observation date must be <= as_of"

    # Compatibility aliases retained for registry reports; they do not restore
    # the old candidate/fallback semantics.
    @property
    def endpoint_name(self) -> str:
        return self.endpoint

    @property
    def catalog_status(self) -> str:
        return self.status

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["registry_version"] = TUSHARE_ENDPOINT_REGISTRY_VERSION
        payload["endpoint_name"] = self.endpoint
        payload["catalog_status"] = self.status
        payload["agent_tags"] = []
        return payload


def _registration(endpoint: str) -> TushareEndpointRegistration:
    disabled = endpoint in DISABLED_PERMISSION_ENDPOINTS
    verified = VERIFIED_ENDPOINT_PREFLIGHTS.get(endpoint)
    checked = PREFLIGHT_ENDPOINT_CHECKS.get(endpoint)
    doc_id = _DOC_IDS.get(endpoint)
    return TushareEndpointRegistration(
        endpoint=endpoint,
        status=(
            "DISABLED_PERMISSION_DENIED"
            if disabled
            else "ACTIVE_VERIFIED"
            if verified
            else "PRECHECK_REQUIRED"
        ),
        permission_checked_at=(
            str((verified or checked)["permission_checked_at"])
            if verified or checked
            else None
        ),
        permission_evidence_id=(
            str(checked["permission_evidence_id"])
            if checked
            else "operator_confirmed_permission_denied_v1"
            if disabled
            else None
        ),
        schema_contract_version=(
            str((verified or checked)["schema_contract_version"])
            if verified or checked
            else None
        ),
        runtime_client_enabled=verified is not None,
        doc_url=(
            f"https://tushare.pro/document/2?doc_id={doc_id}"
            if doc_id
            else "https://tushare.pro/document/1?doc_id=108"
        ),
    )


DEFAULT_ENDPOINT_CATALOG: tuple[TushareEndpointRegistration, ...] = tuple(
    _registration(endpoint) for endpoint in TUSHARE_ENDPOINT_IDS
)


def list_endpoint_catalog() -> list[dict]:
    return [entry.as_dict() for entry in DEFAULT_ENDPOINT_CATALOG]


def catalog_by_endpoint() -> dict[str, dict]:
    return {row["endpoint"]: row for row in list_endpoint_catalog()}


def endpoint_registration(endpoint: str) -> TushareEndpointRegistration:
    if endpoint not in TUSHARE_ENDPOINT_IDS:
        raise ValueError(f"DENY_UNKNOWN_ENDPOINT:{endpoint}")
    return DEFAULT_ENDPOINT_CATALOG[TUSHARE_ENDPOINT_IDS.index(endpoint)]


def assert_endpoint_runtime_enabled(endpoint: str) -> TushareEndpointRegistration:
    registration = endpoint_registration(endpoint)
    if (
        registration.status != "ACTIVE_VERIFIED"
        or not registration.runtime_client_enabled
    ):
        raise PermissionError(
            f"TUSHARE_ENDPOINT_NOT_ACTIVE:{endpoint}:{registration.status}"
        )
    return registration


def promote_verified_endpoint(
    endpoint: str,
    *,
    permission_checked_at: str,
    permission_evidence_id: str,
    schema_contract_version: str,
) -> TushareEndpointRegistration:
    """Pure builder used by a future audited registry-release command.

    It deliberately refuses the four permission-denied endpoints; changing
    those requires a new registry revision and shadow validation.
    """
    current = endpoint_registration(endpoint)
    if endpoint in DISABLED_PERMISSION_ENDPOINTS:
        raise ValueError(
            f"disabled endpoint requires a new registry revision: {endpoint}"
        )
    if not all(
        isinstance(value, str) and value.strip()
        for value in (
            permission_checked_at,
            permission_evidence_id,
            schema_contract_version,
        )
    ):
        raise ValueError(
            "verified endpoint promotion requires complete evidence fields"
        )
    return replace(
        current,
        status="ACTIVE_VERIFIED",
        permission_checked_at=permission_checked_at,
        permission_evidence_id=permission_evidence_id,
        schema_contract_version=schema_contract_version,
        runtime_client_enabled=True,
    )


def validate_catalog_coverage(
    entries: Iterable[TushareEndpointRegistration] = DEFAULT_ENDPOINT_CATALOG,
) -> dict[str, object]:
    rows = list(entries)
    ids = [row.endpoint for row in rows]
    missing = sorted(set(TUSHARE_ENDPOINT_IDS) - set(ids))
    unknown = sorted(set(ids) - set(TUSHARE_ENDPOINT_IDS))
    duplicates = sorted({endpoint for endpoint in ids if ids.count(endpoint) > 1})
    invalid: list[str] = []
    for row in rows:
        if row.agent_tool_exposed is not False:
            invalid.append(f"{row.endpoint}:agent_tool_exposed")
        if row.status == "ACTIVE_VERIFIED":
            if not (
                row.runtime_client_enabled
                and row.permission_checked_at
                and row.permission_evidence_id
                and row.schema_contract_version
            ):
                invalid.append(f"{row.endpoint}:active_without_evidence")
        elif row.runtime_client_enabled:
            invalid.append(f"{row.endpoint}:inactive_client_enabled")
        if row.endpoint in DISABLED_PERMISSION_ENDPOINTS and row.status != (
            "DISABLED_PERMISSION_DENIED"
        ):
            invalid.append(f"{row.endpoint}:disabled_status_drift")
        if not row.point_in_time_rule:
            invalid.append(f"{row.endpoint}:missing_pit_rule")
    return {
        "ok": not missing and not unknown and not duplicates and not invalid,
        "registry_version": TUSHARE_ENDPOINT_REGISTRY_VERSION,
        "n_endpoints": len(rows),
        "missing_endpoints": missing,
        "unknown_endpoints": unknown,
        "duplicate_endpoints": duplicates,
        "invalid_registrations": sorted(invalid),
    }


def refresh_catalog(snapshot_path: str | Path | None = None) -> list[dict]:
    """Write the public registration metadata; no vendor response is included."""
    rows = list_endpoint_catalog()
    if snapshot_path is not None:
        path = Path(snapshot_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return rows


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the closed Tushare registry")
    parser.add_argument("command", choices=("refresh", "validate", "list"))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if args.command == "refresh":
        print(json.dumps({"n_endpoints": len(refresh_catalog(args.out or None))}))
        return 0
    if args.command == "validate":
        result = validate_catalog_coverage()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    print(
        json.dumps(
            list_endpoint_catalog(), ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = [
    "DEFAULT_ENDPOINT_CATALOG",
    "DISABLED_PERMISSION_ENDPOINTS",
    "DYNAMIC_PERMISSION_DENIAL_ENDPOINTS",
    "OPERATOR_DISABLED_PERMISSION_ENDPOINTS",
    "PREFLIGHT_ENDPOINT_CHECKS",
    "TUSHARE_ENDPOINT_IDS",
    "TUSHARE_ENDPOINT_REGISTRY_VERSION",
    "TUSHARE_PREFLIGHT_SCHEMA_VERSION",
    "TushareEndpointRegistration",
    "VERIFIED_ENDPOINT_PREFLIGHTS",
    "assert_endpoint_runtime_enabled",
    "catalog_by_endpoint",
    "endpoint_registration",
    "list_endpoint_catalog",
    "promote_verified_endpoint",
    "refresh_catalog",
    "validate_catalog_coverage",
]
