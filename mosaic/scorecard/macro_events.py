"""Deterministic document event/sentiment classifier (macro plan P4).

The crawler (``dataflows.tushare_documents`` / ``opencli_news``) persists raw
documents into ``macro_documents`` with empty ``event_tags`` / ``sentiment_score``.
This module fills them and builds a **point-in-time daily sentiment/event
index** that macro agents consume as evidence.

Design constraints from ``docs/macro-agent-data-source-plan.md`` (P4/§news_sentiment):
    * Deterministic, lexicon-based — **never** an LLM subjective sentiment used
      directly as a realised label (plan line 473). The index is evidence / a
      percentile trigger, not a forward-return label by itself.
    * Look-ahead safe: a document only enters the index when it carries a
      ``published_at`` inside the window AND was ``discovered_at`` on/before the
      as-of date. Undated documents stay evidence-only (plan line 585).
    * Classification failures must never block market path labels (plan line
      586): every public function degrades to neutral / empty, never raises.

The lexicons are intentionally small and explicit; extend them as new event
families are validated rather than reaching for a model.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Event family → (risk-on orientation, bilingual keyword lexicon). Orientation
# is the common risk-on convention shared with macro_path_labels: +1 risk-on,
# -1 risk-off. Keywords are matched case-insensitively as substrings (Chinese
# needs no word boundaries; English keywords are chosen to be unambiguous).
EVENT_LEXICON: dict[str, tuple[int, tuple[str, ...]]] = {
    "policy_support": (
        1,
        ("降准", "降息", "宽松", "刺激", "稳增长", "利好", "扶持", "减税", "支持政策",
         "stimulus", "easing", "rate cut", "support", "boost", "accommodative"),
    ),
    "policy_tightening": (
        -1,
        ("加息", "收紧", "紧缩", "去杠杆", "监管收紧",
         "rate hike", "tightening", "hawkish", "crackdown"),
    ),
    "liquidity_easing": (
        1,
        ("逆回购", "流动性投放", "净投放", "mlf", "omo", "释放流动性",
         "liquidity injection", "reverse repo"),
    ),
    "risk_off": (
        -1,
        ("避险", "暴跌", "大跌", "恐慌", "抛售", "重挫", "下挫", "回撤",
         "risk-off", "risk off", "selloff", "sell-off", "plunge", "crash", "panic", "rout"),
    ),
    "risk_on": (
        1,
        ("反弹", "大涨", "走强", "乐观", "回暖", "新高",
         "rally", "rebound", "surge", "optimism", "risk-on", "risk on", "record high"),
    ),
    "dollar_pressure": (
        -1,
        ("美元走强", "美元指数", "贬值", "资本外流", "人民币承压", "汇率承压",
         "dollar strength", "depreciation", "capital outflow", "fx pressure"),
    ),
    "geopolitical_escalation": (
        -1,
        ("冲突", "制裁", "战争", "关税", "紧张", "脱钩", "出口管制",
         "conflict", "sanction", "war", "tariff", "tension", "export control", "decoupling"),
    ),
    "commodity_shock": (
        -1,
        ("减产", "供应中断", "油价飙升", "断供", "限产",
         "supply shock", "opec cut", "oil surge", "supply disruption"),
    ),
}

# Standalone sentiment lexicons (used when no event family fires, and to refine
# the sign within a document). Bilingual, deterministic.
_POSITIVE_WORDS: tuple[str, ...] = (
    "利好", "上涨", "增长", "回暖", "改善", "乐观", "提振", "走强", "复苏", "超预期",
    "gain", "rise", "growth", "improve", "optimis", "upbeat", "beat", "recover", "strong",
)
_NEGATIVE_WORDS: tuple[str, ...] = (
    "利空", "下跌", "下滑", "恶化", "悲观", "走弱", "衰退", "不及预期", "风险", "承压",
    "loss", "fall", "decline", "worse", "pessimis", "weak", "recession", "miss", "risk", "slump",
)


def _count_hits(haystack: str, words: tuple[str, ...]) -> int:
    return sum(1 for w in words if w in haystack)


def classify_text(text: str) -> dict[str, Any]:
    """Classify free text into ``{event_tags, sentiment_score}`` deterministically.

    ``sentiment_score`` is ``(pos - neg) / (pos + neg)`` over matched sentiment
    words (event-family orientation also contributes), clamped to ``[-1, 1]``;
    ``0.0`` when nothing matches. ``event_tags`` is the sorted list of fired
    event families. Never raises.
    """
    try:
        hay = (text or "").lower()
        if not hay.strip():
            return {"event_tags": [], "sentiment_score": 0.0}

        event_tags: list[str] = []
        pos = _count_hits(hay, _POSITIVE_WORDS)
        neg = _count_hits(hay, _NEGATIVE_WORDS)
        for family, (orientation, words) in EVENT_LEXICON.items():
            hits = _count_hits(hay, words)
            if hits:
                event_tags.append(family)
                # An event family nudges sentiment by its risk-on orientation.
                if orientation >= 0:
                    pos += hits
                else:
                    neg += hits

        total = pos + neg
        score = 0.0 if total == 0 else (pos - neg) / total
        score = max(-1.0, min(1.0, score))
        return {"event_tags": sorted(event_tags), "sentiment_score": score}
    except Exception as exc:  # noqa: BLE001 - classification must never block scoring
        logger.debug("classify_text failed: %s", exc)
        return {"event_tags": [], "sentiment_score": 0.0}


def classify_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Classify a ``macro_documents`` row (title + excerpt)."""
    text = " ".join(
        str(doc.get(field) or "")
        for field in ("title", "content_excerpt", "query")
    )
    return classify_text(text)


def classify_persisted_documents(
    store,
    *,
    source: Optional[str] = None,
    discovered_at_lte: Optional[str] = None,
    only_unclassified: bool = True,
) -> dict[str, int]:
    """Enrich persisted ``macro_documents`` with event tags + sentiment in place.

    Re-persists each row via ``append_macro_documents`` (its ON CONFLICT updates
    ``event_tags_json`` / ``sentiment_score``), so this is idempotent. By default
    only rows with no event tags yet are (re)classified. Returns counts.
    """
    rows = store.list_macro_documents(source=source, discovered_at_lte=discovered_at_lte)
    updates: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if only_unclassified and (row.get("event_tags_json") or row.get("sentiment_score") is not None):
            skipped += 1
            continue
        result = classify_document(row)
        merged = dict(row)
        merged["event_tags"] = result["event_tags"]
        merged["sentiment_score"] = result["sentiment_score"]
        updates.append(merged)
    persisted = store.append_macro_documents(updates) if updates else 0
    return {"classified": persisted, "skipped": skipped, "total": len(rows)}


def _published_within(published_at: Optional[str], start: str, end: str) -> bool:
    """True iff ``published_at`` parses to a date inside ``[start, end]``.

    Undated documents return False — they stay evidence-only and never enter the
    point-in-time index (plan line 585).
    """
    if not published_at:
        return False
    from mosaic.dataflows.opencli_news import _parse_loose_date

    parsed = _parse_loose_date(str(published_at))
    if parsed is None:
        return False
    day = parsed.replace(tzinfo=None).strftime("%Y-%m-%d")
    return start <= day <= end


def build_sentiment_index(
    store,
    agent: str,
    as_of_date: str,
    *,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Build a point-in-time daily sentiment/event index for ``agent``.

    Only documents (a) tagged for ``agent``, (b) ``discovered_at`` on/before
    ``as_of_date``, and (c) carrying a ``published_at`` inside
    ``[as_of_date - lookback_days, as_of_date]`` enter the index. Returns
    ``{agent, as_of_date, lookback_days, n_documents, n_evidence_only,
    sentiment_index, event_counts, dominant_event}``. Never raises.
    """
    from datetime import datetime, timedelta

    try:
        end = as_of_date
        start = (
            datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%d")
        docs = store.list_macro_documents(agent=agent)

        scores: list[float] = []
        event_counts: dict[str, int] = {}
        evidence_only = 0
        for doc in docs:
            # Point-in-time: discovered on/before the as-of *date*.
            discovered = str(doc.get("discovered_at") or "")[:10]
            if discovered and discovered > as_of_date:
                continue
            if not _published_within(doc.get("published_at"), start, end):
                evidence_only += 1
                continue
            # Use stored classification if present, else classify on the fly.
            if doc.get("sentiment_score") is not None or doc.get("event_tags_json"):
                score = doc.get("sentiment_score")
                tags = _decode_tags(doc.get("event_tags_json"))
                if score is None:
                    result = classify_document(doc)
                    score, tags = result["sentiment_score"], result["event_tags"]
            else:
                result = classify_document(doc)
                score, tags = result["sentiment_score"], result["event_tags"]
            scores.append(float(score))
            for tag in tags:
                event_counts[tag] = event_counts.get(tag, 0) + 1

        n = len(scores)
        index = sum(scores) / n if n else None
        dominant = max(event_counts, key=event_counts.get) if event_counts else None
        return {
            "agent": agent,
            "as_of_date": as_of_date,
            "lookback_days": lookback_days,
            "n_documents": n,
            "n_evidence_only": evidence_only,
            "sentiment_index": index,
            "event_counts": event_counts,
            "dominant_event": dominant,
        }
    except Exception as exc:  # noqa: BLE001 - evidence index must never block scoring
        logger.debug("build_sentiment_index failed for %s: %s", agent, exc)
        return {
            "agent": agent,
            "as_of_date": as_of_date,
            "lookback_days": lookback_days,
            "n_documents": 0,
            "n_evidence_only": 0,
            "sentiment_index": None,
            "event_counts": {},
            "dominant_event": None,
        }


def event_orientation(index: dict[str, Any]) -> dict[str, Any]:
    """Map a sentiment/event index to a risk-on event signal.

    Returns ``{orientation, strength, event_label}`` where orientation is +1
    (risk-on) / -1 (risk-off) / 0 (neutral), strength in ``[0, 1]``. This is the
    hook a future percentile-triggered path scorer consumes — it never produces
    a realised label on its own.
    """
    dominant = index.get("dominant_event")
    si = index.get("sentiment_index")
    if dominant and dominant in EVENT_LEXICON:
        orientation = EVENT_LEXICON[dominant][0]
    elif si is not None and abs(si) > 1e-9:
        orientation = 1 if si > 0 else -1
    else:
        orientation = 0
    strength = min(1.0, abs(si)) if si is not None else 0.0
    return {"orientation": orientation, "strength": strength, "event_label": dominant}


def _decode_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        import json

        decoded = json.loads(value)
        return [str(v) for v in decoded] if isinstance(decoded, list) else []
    except Exception:  # noqa: BLE001
        return []


__all__ = [
    "EVENT_LEXICON",
    "build_sentiment_index",
    "classify_document",
    "classify_persisted_documents",
    "classify_text",
    "event_orientation",
]
