"""Tsinghua sino-US relations index (Plan §5.1 geopolitical).

Reads the year×month relations-index matrix published by Tsinghua's Institute
of International Relations (http://www.tuiir.tsinghua.edu.cn/kycg/zwgxsj.htm).
The index is roughly [-9, +9]; **negative = tension / confrontation**, positive
= cooperation. CSV layout: header ``年份,1月,…,12月``; one row per year.

Path resolution: ``MOSAIC_SINO_US_CSV`` env override, else
``/home/hap/sino-us-relation.csv`` (where the user keeps the downloaded file).
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from .exceptions import DataVendorUnavailable

_DATE_FMT = "%Y-%m-%d"
_DEFAULT_CSV = "/home/hap/sino-us-relation.csv"


def _csv_path() -> Path:
    return Path(os.getenv("MOSAIC_SINO_US_CSV") or _DEFAULT_CSV)


def _load_matrix(path: Path) -> dict[int, list[float | None]]:
    """Parse the CSV into ``{year: [m1..m12]}`` (None for blank cells)."""
    try:
        with path.open(encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    except OSError as exc:
        raise DataVendorUnavailable(
            f"sino-US relations CSV not readable at {path} "
            f"(set MOSAIC_SINO_US_CSV): {exc}"
        ) from exc
    out: dict[int, list[float | None]] = {}
    for row in rows[1:]:  # skip header
        if not row or not row[0].strip().isdigit():
            continue
        year = int(row[0])
        months: list[float | None] = []
        for cell in row[1:13]:
            cell = cell.strip()
            months.append(float(cell) if cell else None)
        out[year] = months + [None] * (12 - len(months))
    return out


def get_us_china_relations(curr_date: str, look_back_days: int = 365) -> str:
    """Sino-US relations index over a window (Tsinghua monthly series).

    Window = ``[curr_date - look_back_days, curr_date]`` (default ~1 year, since
    the series is monthly). Returns a markdown header + CSV of ``date,index``
    plus a one-line trend (latest value + change over the window). Negative
    values = tension. Used by ``geopolitical``.
    """
    try:
        end = datetime.strptime(curr_date, _DATE_FMT)
    except ValueError as exc:
        raise DataVendorUnavailable(
            f"curr_date must be YYYY-MM-DD, got {curr_date!r}: {exc}"
        ) from exc
    if look_back_days < 0:
        raise DataVendorUnavailable("look_back_days must be >= 0.")

    matrix = _load_matrix(_csv_path())
    start_ord = end.toordinal() - look_back_days

    points: list[tuple[str, float]] = []
    for year, months in sorted(matrix.items()):
        for m, val in enumerate(months, start=1):
            if val is None:
                continue
            d = datetime(year, m, 1)
            if start_ord <= d.toordinal() <= end.toordinal():
                points.append((d.strftime("%Y-%m"), val))

    title = f"中美关系指数 / Sino-US Relations Index ({datetime.fromordinal(max(start_ord, 1)).strftime('%Y-%m')} → {end.strftime('%Y-%m')})"
    if not points:
        return (
            f"# {title}\n"
            f"No relations-index data in window (series is monthly; "
            f"widen look_back_days). Negative = tension.\n"
        )

    points.sort()
    latest_date, latest = points[-1]
    first = points[0][1]
    change = latest - first
    direction = "改善/cooperation↑" if change > 0 else "恶化/tension↑" if change < 0 else "持平/flat"
    lines = [
        f"# {title}",
        f"# Source: Tsinghua IIR. Range ~[-9,+9]; negative = tension. "
        f"Latest {latest_date}={latest:+.1f}, Δ window {change:+.1f} ({direction}).",
        "date,index",
    ]
    lines += [f"{d},{v:+.1f}" for d, v in points]
    return "\n".join(lines) + "\n"
