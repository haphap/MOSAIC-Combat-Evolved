"""Legacy audit surface for disabled Tushare document endpoints.

``major_news``, ``news``, ``npr`` and ``monetary_policy`` are unavailable to
this deployment.  V2 event collection uses registered official adapters (with
GDELT only for discovery), so this module never constructs a client or polls a
fallback endpoint.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from mosaic.dataflows.tushare_catalog import (
    DISABLED_PERMISSION_ENDPOINTS,
    endpoint_registration,
)

_DEFAULT_DOC_ENDPOINTS: tuple[str, ...] = ()
DocFetch = Callable[[str, str, str], list[dict]]


def _default_tushare_fetch(endpoint: str, start_date: str, end_date: str) -> list[dict]:
    del start_date, end_date
    registration = endpoint_registration(endpoint)
    raise PermissionError(
        f"TUSHARE_DOCUMENT_ENDPOINT_DISABLED:{endpoint}:{registration.status}"
    )


def crawl_macro_documents(
    store,
    *,
    start_date: str,
    end_date: str,
    endpoints: Optional[list[str]] = None,
    discovered_at: Optional[str] = None,
    fetch: Optional[DocFetch] = None,
) -> dict[str, Any]:
    """Return an auditable refusal without invoking a supplied fetch callback."""
    del store, start_date, end_date, discovered_at, fetch
    requested = list(endpoints or _DEFAULT_DOC_ENDPOINTS)
    errors: list[dict[str, str]] = []
    for endpoint in requested:
        registration = endpoint_registration(endpoint)
        reason = (
            "DISABLED_PERMISSION_DENIED"
            if endpoint in DISABLED_PERMISSION_ENDPOINTS
            else registration.status
        )
        errors.append(
            {
                "endpoint": endpoint,
                "error": f"TUSHARE_DOCUMENT_ENDPOINT_NOT_ACTIVE:{reason}",
            }
        )
    return {
        "endpoints": requested,
        "fetched": 0,
        "persisted": 0,
        "errors": errors,
        "runtime_client_constructed": False,
    }


__all__ = ["crawl_macro_documents"]
