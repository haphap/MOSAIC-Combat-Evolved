"""Forward-return scorer (Plan §11.3 sub-step 3B).

Pulls pending recommendations from ``ScorecardStore``, fetches forward
prices via Tushare (5d + 21d horizons aligned by trading days, not
calendar days), computes alpha vs benchmark, writes scoring columns back.

Scoring algorithm per row:
    1. Resolve d0 close and d_N close from Tushare.
    2. forward_return_N = (close_N - close_d0) / close_d0
    3. alpha_5d = forward_return_5d - benchmark_return_5d
    4. UPDATE recommendations row with the three numbers + scored_at = today.

Suspension / missing data: write NULL for the affected horizon but still
fill scored_at so the row stops being "pending" (otherwise it would be
re-attempted forever).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Default benchmark for A-share alpha calc (Plan §11.3 design decision #5).
DEFAULT_BENCHMARK = "000300.SH"

# Forward horizons in trading days (Plan §11.3 design decision #3).
HORIZON_5D = 5
HORIZON_21D = 21


def _benchmark_ticker() -> str:
    return os.getenv("MOSAIC_BENCHMARK_TICKER", DEFAULT_BENCHMARK).strip() or DEFAULT_BENCHMARK


# ---------------------------------------------------------------------------
# Price-fetch shim
# ---------------------------------------------------------------------------


def _fetch_close(ts_code: str, target_date_iso: str) -> Optional[float]:
    """Return the close price of ``ts_code`` on ``target_date_iso``, or None
    if the row is missing (suspension, holiday after wrong alignment, etc).

    Uses ``tushare.pro.daily()`` for A-share / ``index_daily()`` for indices.
    """
    try:
        from mosaic.dataflows.tushare import (
            _fetch_price_data,  # type: ignore[attr-defined]
            _get_pro_client,  # type: ignore[attr-defined]
            _normalize_ts_code,  # type: ignore[attr-defined]
            _to_api_date,  # type: ignore[attr-defined]
        )
    except Exception as exc:
        logger.error("tushare data flow unavailable: %s", exc)
        return None

    try:
        pro = _get_pro_client()
    except Exception as exc:
        logger.warning("tushare client unavailable: %s", exc)
        return None

    api_date = _to_api_date(target_date_iso)
    norm = _normalize_ts_code(ts_code)
    try:
        # Indices (000300.SH) need pro.index_daily; A-share / HK / US use _fetch_price_data
        if norm.endswith(".SH") and norm.startswith("000") and len(norm.split(".")[0]) == 6:
            df = pro.index_daily(ts_code=norm, start_date=api_date, end_date=api_date)
        else:
            df = _fetch_price_data(pro, norm, api_date, api_date)
    except Exception as exc:
        logger.warning("Tushare fetch failed for %s on %s: %s", norm, target_date_iso, exc)
        return None

    if df is None or df.empty:
        return None
    # Tushare returns 'close' column; typed as numeric.
    try:
        return float(df["close"].iloc[0])
    except (KeyError, IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreOutcome:
    forward_return_5d: Optional[float]
    forward_return_21d: Optional[float]
    alpha_5d: Optional[float]


class Scorer:
    """Drives ``ScorecardStore.list_pending`` → fetch closes → write scoring.

    Stateless modulo the underlying SQLite store + Tushare HTTP client.
    Designed to be invoked from a bridge handler or a daily cron;
    ``score_pending`` is idempotent — only rows with NULL ``scored_at`` are
    touched.
    """

    def __init__(self, store, benchmark: Optional[str] = None) -> None:
        self.store = store
        self.benchmark = benchmark or _benchmark_ticker()

    def score_pending(self, cohort: str, today: str) -> dict:
        """Score every row in ``cohort`` whose 21d horizon has matured.

        ``today`` is the as-of date (YYYY-MM-DD). Rows whose date + 21
        trading days ≤ today are eligible. Earlier rows still get their
        5d horizon scored even if 21d hasn't matured (in which case
        forward_return_21d is left NULL alongside scored_at = today —
        i.e. we mark scored once 5d is filled).

        Returns ``{"scored": int, "skipped_immature": int, "skipped_missing": int}``.
        """
        from mosaic.dataflows.calendar import next_trading_day  # local import to avoid cycle at module load

        # Cutoff: rows whose date + 5 trading days ≤ today are at least 5d-eligible.
        # We don't need date+21 to be matured; the 21d slot can stay NULL.
        # But we DO need the row's date itself to be ≤ today - 5 trading days
        # (otherwise the 5d window hasn't even closed yet).
        five_days_back = next_trading_day(today, 0)  # snap today to a trading day
        # Use previous_trading_day to compute the cutoff for "rows whose 5d
        # forward window has closed by today".
        from mosaic.dataflows.calendar import previous_trading_day

        cutoff_5d = previous_trading_day(five_days_back, HORIZON_5D)

        pending = self.store.list_pending(cohort=cohort, before_date=cutoff_5d)

        outcome = {"scored": 0, "skipped_immature": 0, "skipped_missing": 0}

        # Cache benchmark closes — benchmark_close[date_iso] → float | None.
        benchmark_cache: dict[str, Optional[float]] = {}

        def _bench_close(date_iso: str) -> Optional[float]:
            if date_iso not in benchmark_cache:
                benchmark_cache[date_iso] = _fetch_close(self.benchmark, date_iso)
            return benchmark_cache[date_iso]

        scored_at_iso = today

        for row in pending:
            d0 = row.date

            # Forward target dates
            t_5d = next_trading_day(d0, HORIZON_5D)
            t_21d = next_trading_day(d0, HORIZON_21D)

            # 5d horizon: must be on-or-before today; otherwise skip the whole row.
            if t_5d > today:
                outcome["skipped_immature"] += 1
                continue

            close_d0 = _fetch_close(row.ticker, d0)
            close_5d = _fetch_close(row.ticker, t_5d)
            close_21d = _fetch_close(row.ticker, t_21d) if t_21d <= today else None

            forward_return_5d: Optional[float] = None
            forward_return_21d: Optional[float] = None
            alpha_5d: Optional[float] = None

            if close_d0 is None or close_d0 == 0:
                # Can't price — log & mark scored anyway to drop from pending.
                outcome["skipped_missing"] += 1
            else:
                if close_5d is not None:
                    forward_return_5d = (close_5d - close_d0) / close_d0
                if close_21d is not None:
                    forward_return_21d = (close_21d - close_d0) / close_d0

                if forward_return_5d is not None:
                    bench_d0 = _bench_close(d0)
                    bench_5d = _bench_close(t_5d)
                    if bench_d0 not in (None, 0) and bench_5d is not None:
                        bench_return_5d = (bench_5d - bench_d0) / bench_d0
                        alpha_5d = forward_return_5d - bench_return_5d

            self.store.update_scoring(
                row_id=row.id,
                forward_return_5d=forward_return_5d,
                forward_return_21d=forward_return_21d,
                alpha_5d=alpha_5d,
                scored_at=scored_at_iso,
            )
            outcome["scored"] += 1

        return outcome
