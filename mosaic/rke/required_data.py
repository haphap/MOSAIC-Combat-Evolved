"""Shared canonicalization helpers for report-intelligence required data."""

from __future__ import annotations

import re
from typing import Any, Iterable


def canonical_metric_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    lowered = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered[:120]


def normalize_required_data_item(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("metric:"):
        text = text.removeprefix("metric:").strip()
    metric = canonical_metric_name(text)
    return f"metric:{metric}" if metric else ""


def normalize_required_data_items(values: Iterable[Any]) -> list[str]:
    normalized = [
        item
        for item in (normalize_required_data_item(value) for value in values)
        if item
    ]
    return list(dict.fromkeys(normalized))
