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
from typing import Any, Optional

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


# Index code-space allowlist (PR #3 review hotfix #3). Each entry is
# (prefix, market_suffix) — e.g. SSE indices use 000xxx.SH while the SZ
# stock with the same numeric prefix (000001.SZ = Ping An Bank) is *not* an
# index. The market suffix disambiguates.
_INDEX_PREFIXES: tuple[tuple[str, str], ...] = (
    ("000", "SH"),  # SSE: 000300 沪深300, 000016 上证50, 000905 中证500, 000001 上证综指
    ("399", "SZ"),  # SZSE: 399001 深证成指, 399006 创业板指, 399300 (alt CSI300)
    ("932", "SH"),  # CSI national indices (post-2023)
)


def _is_a_share_index(norm: str) -> bool:
    """Return True for A-share index ts_codes that need pro.index_daily."""
    code, _, market = norm.partition(".")
    if len(code) != 6 or market not in ("SH", "SZ"):
        return False
    for prefix, expected_market in _INDEX_PREFIXES:
        if code.startswith(prefix) and market == expected_market:
            return True
    return False


def _is_a_share_etf(norm: str) -> bool:
    """Return True for A-share ETF ts_codes that need pro.fund_daily.

    ETF/LOF code-space largely disjoint from stocks: SH funds are 5xxxxx
    (51/50/56/58…), SZ funds are 1xxxxx (15/16/18…); stocks are sh6/sz0/sz3.

    Caveat: SZ exchange-traded convertible bonds also live in 1xxxxx
    (12xxxx.SZ — 123/127/128…), so a bond ts_code would route here and
    ``fund_daily`` would return nothing ⇒ None (unscored). This matches the
    existing ``qlib_local`` routing and is harmless for today's input set (the
    CIO only recommends broad-based ETFs). Tightening to 15/16/18 would be more
    precise but is over-engineering until a bond ts_code is actually fed in.

    NOTE: this duplicates the ETF code-space encoded in
    ``mosaic.dataflows.qlib_local._is_etf_instrument`` (different format:
    5xxxxx.SH vs sh5xxxxx). If the prefix set changes, keep both in sync; a
    shared helper is the eventual cleanup.
    """
    code, _, market = norm.partition(".")
    if len(code) != 6:
        return False
    return (market == "SH" and code.startswith("5")) or (market == "SZ" and code.startswith("1"))


def _fetch_close(ts_code: str, target_date_iso: str) -> Optional[float]:
    """Return the close price of ``ts_code`` on ``target_date_iso``, or None
    if the row is missing (suspension, holiday after wrong alignment, etc).

    Routes by ts_code: ``pro.index_daily()`` for A-share indices,
    ``pro.fund_daily()`` for ETFs, else ``pro.daily()`` (A-share / HK / US
    stocks via ``_fetch_price_data``).
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
        # Route to pro.index_daily for known A-share index prefixes
        # (PR #3 review hotfix #3). Previously detected via implicit
        # "000xxx.SH" heuristic which missed legitimate indices like
        # 399300.SZ. Allowlist of canonical A-share index code spaces:
        #   * 000xxx.SH — SSE indices (000300 沪深300, 000016 上证50,
        #                              000905 中证500, 000001 上证综指)
        #   * 399xxx.SZ — SZSE indices (399001 深证成指, 399006 创业板指,
        #                               399300 alt CSI300)
        #   * 932xxx.SH — CSI national indices (newer, post-2023)
        if _is_a_share_index(norm):
            df = pro.index_daily(ts_code=norm, start_date=api_date, end_date=api_date)
        elif _is_a_share_etf(norm):
            # ETFs (5xxxxx.SH / 1xxxxx.SZ) price via pro.fund_daily, so ETF
            # recommendations get forward returns scored just like stocks.
            df = pro.fund_daily(ts_code=norm, start_date=api_date, end_date=api_date)
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

        Snap-direction (PR #3 review hotfix #2): when ``today`` falls on a
        weekend or public holiday, snap **backward** to the previous trading
        day. Snapping forward would yield a future date, causing the scorer
        to fetch nonexistent close prices and prematurely mark rows as
        scored with NULL returns.

        Returns ``{"scored": int, "skipped_immature": int, "skipped_missing": int}``.
        """
        from mosaic.dataflows.calendar import (  # local import to avoid cycle at module load
            next_trading_day,
            previous_trading_day,
        )

        # Snap today BACKWARD to the last completed trading day. The 5d
        # forward window has only matured if its end date is ≤ today's
        # last-completed trading day.
        last_trading_day = previous_trading_day(today, 0)
        cutoff_5d = previous_trading_day(last_trading_day, HORIZON_5D)

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

            # 5d horizon: must be on-or-before today's last completed trading
            # day; otherwise skip the whole row.
            if t_5d > last_trading_day:
                outcome["skipped_immature"] += 1
                continue

            close_d0 = _fetch_close(row.ticker, d0)
            close_5d = _fetch_close(row.ticker, t_5d)
            close_21d = (
                _fetch_close(row.ticker, t_21d) if t_21d <= last_trading_day else None
            )

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


# ---------------------------------------------------------------------------
# Macro scorer (autoresearch macro plan — MVP: benchmark 5d direction label)
# ---------------------------------------------------------------------------

MACRO_VOL_FLOOR = 0.005          # floor for vol_scale_5d (avoid div-by-tiny)
_DEFAULT_MACRO_NEUTRAL_BAND = 0.005   # ±0.5% raw-return band for realized_label
_MACRO_VOL_LOOKBACK_CAL_DAYS = 40     # calendar days of benchmark history for realized vol
_MACRO_MOVE_CLAMP = 3.0


def _macro_neutral_band() -> float:
    """Single source: autoresearch.macro_neutral_band (default 0.005, raw return)."""
    try:
        from mosaic.default_config import DEFAULT_CONFIG

        band = DEFAULT_CONFIG.get("autoresearch", {}).get("macro_neutral_band")
        return float(band) if band is not None else _DEFAULT_MACRO_NEUTRAL_BAND
    except Exception:  # noqa: BLE001
        return _DEFAULT_MACRO_NEUTRAL_BAND


def _macro_agent_specific_labels_enabled() -> bool:
    try:
        from mosaic.default_config import DEFAULT_CONFIG

        value = DEFAULT_CONFIG.get("autoresearch", {}).get(
            "macro_agent_specific_labels_enabled", True
        )
        return bool(value)
    except Exception:  # noqa: BLE001
        return True


def _fetch_benchmark_series(ts_code: str, start_iso: str, end_iso: str) -> list[float]:
    """Benchmark index closes over [start, end] (chronological). [] on failure.

    Used only to estimate trailing realized vol for ``vol_scale_5d``.
    """
    try:
        from mosaic.dataflows.tushare import (  # type: ignore[attr-defined]
            _get_pro_client,
            _normalize_ts_code,
            _to_api_date,
        )
        pro = _get_pro_client()
        norm = _normalize_ts_code(ts_code)
        df = pro.index_daily(
            ts_code=norm, start_date=_to_api_date(start_iso), end_date=_to_api_date(end_iso)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("benchmark series fetch failed for %s: %s", ts_code, exc)
        return []
    if df is None or df.empty:
        return []
    try:
        df = df.sort_values("trade_date")
        return [float(x) for x in df["close"].tolist()]
    except Exception:  # noqa: BLE001
        return []


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def _max_drawdown(closes: list[float]) -> float:
    peak: Optional[float] = None
    worst = 0.0
    for close in closes:
        if close <= 0:
            continue
        peak = close if peak is None else max(peak, close)
        if peak:
            worst = min(worst, (close - peak) / peak)
    return worst


def _score_directional_move(
    *,
    vote: int,
    confidence: float,
    directional_return: float,
    vol_scale: float,
    neutral_band: float,
) -> float:
    norm_move = _clip(
        directional_return / vol_scale,
        -_MACRO_MOVE_CLAMP,
        _MACRO_MOVE_CLAMP,
    )
    if vote != 0:
        return confidence * vote * norm_move
    neutral_band_norm = neutral_band / vol_scale
    return confidence * (neutral_band_norm - abs(norm_move))


class MacroScorer:
    """Score pending macro_signals by benchmark 5d direction (MVP).

    Fills realized_label / hit_5d / raw_macro_score_5d (vol-scaled) and marks
    rows scored so they leave the pending set. ``influence`` / agent-specific
    labels are follow-ups (left NULL here).
    """

    def __init__(
        self,
        store,
        benchmark: Optional[str] = None,
        neutral_band: Optional[float] = None,
        agent_specific_labels_enabled: Optional[bool] = None,
    ) -> None:
        self.store = store
        self.benchmark = benchmark or _benchmark_ticker()
        self.neutral_band = (
            float(neutral_band) if neutral_band is not None else _macro_neutral_band()
        )
        self.agent_specific_labels_enabled = (
            bool(agent_specific_labels_enabled)
            if agent_specific_labels_enabled is not None
            else _macro_agent_specific_labels_enabled()
        )
        self._vol_cache: dict[str, float] = {}

    def _vol_scale(self, d0_iso: str) -> float:
        if d0_iso in self._vol_cache:
            return self._vol_cache[d0_iso]
        from mosaic.dataflows.calendar import previous_trading_day  # local import

        start = previous_trading_day(d0_iso, _MACRO_VOL_LOOKBACK_CAL_DAYS // 2)
        closes = _fetch_benchmark_series(self.benchmark, start, d0_iso)
        vs = MACRO_VOL_FLOOR
        rets = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]
        if len(rets) >= 5:
            mean = sum(rets) / len(rets)
            std = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
            vs = max(std * (HORIZON_5D ** 0.5), MACRO_VOL_FLOOR)
        self._vol_cache[d0_iso] = vs
        return vs

    def _benchmark_label_fields(
        self,
        *,
        row,
        bench_ret: float,
        label_type: str,
        label_source_status: str,
    ) -> dict[str, Any]:
        band = self.neutral_band
        realized = 1 if bench_ret > band else (-1 if bench_ret < -band else 0)
        conf = float(row.confidence) if row.confidence is not None else 0.0
        raw = _score_directional_move(
            vote=int(row.vote),
            confidence=conf,
            directional_return=bench_ret,
            vol_scale=self._vol_scale(row.date),
            neutral_band=band,
        )
        return {
            "label_type": label_type,
            "label_source_status": label_source_status,
            "label_value_5d": bench_ret,
            "benchmark_return_5d": bench_ret,
            "realized_label": realized,
            "hit_5d": 1 if row.vote == realized else 0,
            "raw_macro_score_5d": raw,
        }

    def _agent_specific_label_fields(
        self,
        *,
        row,
        bench_ret: float,
        t_5d: str,
    ) -> Optional[dict[str, Any]]:
        if not self.agent_specific_labels_enabled:
            return None
        from mosaic.scorecard.macro_labels import primary_label_for_agent

        spec = primary_label_for_agent(row.agent)
        if spec is None:
            return None

        if spec.label_type == "max_drawdown_5d":
            closes = _fetch_benchmark_series(self.benchmark, row.date, t_5d)
            label_source_status = "primary"
            if len(closes) < 2:
                # Exact endpoint closes are already known by the caller; they
                # still give a conservative 2-point drawdown estimate.
                closes = [1.0, 1.0 + bench_ret]
                label_source_status = "fallback"
            mdd = _max_drawdown(closes)
            band = self.neutral_band
            if mdd < -band:
                realized = -1
                directional_return = min(bench_ret, mdd)
            elif bench_ret > band:
                realized = 1
                directional_return = bench_ret
            elif bench_ret < -band:
                realized = -1
                directional_return = bench_ret
            else:
                realized = 0
                directional_return = bench_ret
            conf = float(row.confidence) if row.confidence is not None else 0.0
            raw = _score_directional_move(
                vote=int(row.vote),
                confidence=conf,
                directional_return=directional_return,
                vol_scale=self._vol_scale(row.date),
                neutral_band=band,
            )
            return {
                "label_type": spec.label_type,
                "label_source_status": label_source_status,
                "label_value_5d": mdd,
                "benchmark_return_5d": bench_ret,
                "realized_label": realized,
                "hit_5d": 1 if row.vote == realized else 0,
                "raw_macro_score_5d": raw,
            }
        return None

    def score_pending(self, cohort: str, today: str) -> dict:
        """Score matured macro signals. Returns macro_* counts."""
        from mosaic.dataflows.calendar import next_trading_day, previous_trading_day

        last_trading_day = previous_trading_day(today, 0)
        cutoff_5d = previous_trading_day(last_trading_day, HORIZON_5D)
        pending = self.store.list_pending_macro(cohort=cohort, before_date=cutoff_5d)

        outcome = {"macro_scored": 0, "macro_skipped_immature": 0, "macro_skipped_missing": 0}
        bench_cache: dict[str, Optional[float]] = {}

        def _bench(date_iso: str) -> Optional[float]:
            if date_iso not in bench_cache:
                bench_cache[date_iso] = _fetch_close(self.benchmark, date_iso)
            return bench_cache[date_iso]

        for row in pending:
            d0 = row.date
            t_5d = next_trading_day(d0, HORIZON_5D)
            if t_5d > last_trading_day:
                outcome["macro_skipped_immature"] += 1
                continue

            b0, b5 = _bench(d0), _bench(t_5d)
            if b0 in (None, 0) or b5 is None:
                # Can't price the benchmark — mark scored (missing) so it drops.
                label_type = "benchmark_5d"
                if self.agent_specific_labels_enabled:
                    from mosaic.scorecard.macro_labels import (
                        BENCHMARK_FALLBACK_LABEL,
                        primary_label_for_agent,
                    )

                    spec = primary_label_for_agent(row.agent)
                    label_type = spec.label_type if spec is not None else BENCHMARK_FALLBACK_LABEL
                self.store.update_macro_scoring(
                    row.id,
                    {
                        "label_type": label_type,
                        "label_source_status": "missing",
                        "influence_weight_equal": row.influence_weight_equal,
                        "scored_at": today,
                    },
                )
                outcome["macro_skipped_missing"] += 1
                continue

            bench_ret = (b5 - b0) / b0
            fields = self._agent_specific_label_fields(
                row=row,
                bench_ret=bench_ret,
                t_5d=t_5d,
            )
            if fields is None and self.agent_specific_labels_enabled:
                from mosaic.scorecard.macro_labels import BENCHMARK_FALLBACK_LABEL

                fields = self._benchmark_label_fields(
                    row=row,
                    bench_ret=bench_ret,
                    label_type=BENCHMARK_FALLBACK_LABEL,
                    label_source_status="fallback",
                )
            elif fields is None:
                fields = self._benchmark_label_fields(
                    row=row,
                    bench_ret=bench_ret,
                    label_type="benchmark_5d",
                    label_source_status="primary",
                )

            influence = row.influence_weight_equal
            if influence is not None and fields.get("raw_macro_score_5d") is not None:
                fields["effective_macro_score_5d"] = (
                    float(influence) * float(fields["raw_macro_score_5d"])
                )
            else:
                fields["effective_macro_score_5d"] = None
            fields["influence_weight_equal"] = influence
            fields["scored_at"] = today

            self.store.update_macro_scoring(row.id, fields)
            outcome["macro_scored"] += 1

        return outcome
