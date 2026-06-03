"""Tushare document crawler → ``macro_documents`` (autoresearch macro plan P5).

Persists Tushare news/corpus documents (the OpenCLI side is handled in
``opencli_news``) so they become a *point-in-time* event source: each row is
stamped with ``discovered_at`` (crawl time) and ``published_at`` (from the
item). Historical scoring only reads documents discovered on/before the signal
date, so a backfill stamped "now" can never leak into past scoring.

The Tushare call is injectable (``fetch=``) so tests run without a vendor key.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from mosaic.dataflows.opencli_news import _normalise_macro_document
from mosaic.scorecard.macro_events import classify_document

# Event-capable Tushare endpoints used as macro document sources. Kept small and
# explicit; extend via the ``endpoints=`` arg as more are validated.
_DEFAULT_DOC_ENDPOINTS: tuple[str, ...] = ("news",)
_DEFAULT_NEWS_SOURCE = "sina"

DocFetch = Callable[[str, str, str], list[dict]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_tushare_fetch(endpoint: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch documents from a Tushare endpoint via the generic ``pro.query``."""
    from mosaic.dataflows.tushare import (  # type: ignore[attr-defined]
        _get_pro_client,
        _to_api_date,
    )

    pro = _get_pro_client()
    params: dict[str, Any] = {
        "start_date": _to_api_date(start_date),
        "end_date": _to_api_date(end_date),
    }
    if endpoint in {"news", "llm_corpus_topic"}:
        params["src"] = _DEFAULT_NEWS_SOURCE
    df = pro.query(endpoint, **params)
    if df is None or getattr(df, "empty", True):
        return []
    return df.to_dict("records")


def crawl_macro_documents(
    store,
    *,
    start_date: str,
    end_date: str,
    endpoints: Optional[list[str]] = None,
    discovered_at: Optional[str] = None,
    fetch: Optional[DocFetch] = None,
) -> dict[str, Any]:
    """Crawl Tushare document endpoints and persist into ``macro_documents``.

    ``discovered_at`` defaults to now (correct for a live crawl). One row per
    item, tagged with the endpoint's macro agents; deduped by content hash.
    Returns ``{"endpoints", "fetched", "persisted", "errors"}``.
    """
    from mosaic.dataflows.tushare_catalog import catalog_by_endpoint

    catalog = catalog_by_endpoint()
    eps = endpoints or [e for e in _DEFAULT_DOC_ENDPOINTS if e in catalog]
    fetch = fetch or _default_tushare_fetch
    stamp = discovered_at or _now_iso()

    rows: list[dict] = []
    seen: set[str] = set()
    fetched = 0
    errors: list[dict[str, str]] = []
    for ep in eps:
        spec = catalog.get(ep) or {}
        agent_tags = list(spec.get("agent_tags") or ("news_sentiment",))
        try:
            items = fetch(ep, start_date, end_date)
        except Exception as exc:  # noqa: BLE001 - one bad endpoint shouldn't abort the crawl
            errors.append({"endpoint": ep, "error": f"{type(exc).__name__}: {exc}"})
            items = []
        for item in items or []:
            fetched += 1
            row = _normalise_macro_document(
                item=item, agent=agent_tags[0], query=ep,
                source="tushare", channel=ep, discovered_at=stamp,
            )
            row["agent_tags"] = agent_tags  # one row tagged for all relevant agents
            h = row["content_hash"]
            if h in seen:
                continue
            seen.add(h)
            # Deterministic event/sentiment classification at ingest (P4); the
            # index reader stays look-ahead-safe regardless of when this runs.
            classified = classify_document(row)
            row["event_tags"] = classified["event_tags"]
            row["sentiment_score"] = classified["sentiment_score"]
            rows.append(row)

    persisted = store.append_macro_documents(rows) if rows else 0
    return {"endpoints": eps, "fetched": fetched, "persisted": persisted, "errors": errors}
