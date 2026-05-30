"""Minimal vendor-CSV parsing helpers used by the paper engine's price lookup.

Ported from ETFAgents ``detail.py`` (only the three functions the engine needs);
vendor output carries a ``#`` comment preamble + ``Label: value`` summary lines
before the real CSV header, which these skip.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

_SUMMARY_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z\s]*:\s")

_CSV_HEADER_FIELDS = {
    "trade_date", "ts_code", "symbol", "stk_code", "end_date",
    "nav_date", "name", "open", "close", "unit_nav", "fd_share",
    "fund_share", "stk_mkv_ratio", "pct_chg",
}


def _parse_csv_rows(csv_text: str, limit: int | None = None) -> list[dict[str, str]]:
    if not csv_text or csv_text.startswith("No "):
        return []
    lines = csv_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _SUMMARY_LINE_RE.match(stripped):
            continue
        if "," in stripped:
            fields = {f.strip().lower() for f in stripped.split(",")}
            if fields & _CSV_HEADER_FIELDS:
                header_idx = i
                break
    if header_idx is None:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    rows = list(reader)
    if limit is not None:
        rows = rows[:limit] if limit > 0 else []
    return rows


def _parse_csv_last_row(csv_text: str) -> dict[str, str] | None:
    rows = _parse_csv_rows(csv_text)
    return rows[-1] if rows else None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
