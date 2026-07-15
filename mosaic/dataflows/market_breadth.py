"""Deterministic point-in-time A-share market-breadth snapshot."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import DataVendorUnavailable

BREADTH_SCHEMA_VERSION = "market_breadth_snapshot_v1"
CORE_COVERAGE_MIN = 0.90
ROLLING_PERCENTILE_DAYS = 252


class BreadthCoverageError(DataVendorUnavailable):
    """Raised when current core breadth coverage is below 90%."""


class BreadthHistoryError(DataVendorUnavailable):
    """Raised when the 252-day PIT state window cannot be formed."""


@dataclass(frozen=True)
class BreadthInputs:
    stock_basic: Any
    daily: Any
    adj_factor: Any
    suspensions: Any | None = None


def _normalise_date(series):
    import pandas as pd  # noqa: PLC0415

    values = series.astype(str).str.strip()
    compact = pd.to_datetime(values, format="%Y%m%d", errors="coerce")
    return compact.where(compact.notna(), pd.to_datetime(values, errors="coerce"))


def _prepare_inputs(inputs: BreadthInputs, as_of_date: str):
    import pandas as pd  # noqa: PLC0415

    cutoff = pd.Timestamp(as_of_date)
    basic = inputs.stock_basic.copy()
    daily = inputs.daily.copy()
    factors = inputs.adj_factor.copy()
    required_basic = {"ts_code", "list_date"}
    required_daily = {"ts_code", "trade_date", "close", "pre_close", "amount"}
    required_factors = {"ts_code", "trade_date", "adj_factor"}
    for name, frame, required in (
        ("stock_basic", basic, required_basic),
        ("daily", daily, required_daily),
        ("adj_factor", factors, required_factors),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise DataVendorUnavailable(f"market breadth {name} missing columns: {sorted(missing)}")

    basic["list_date"] = _normalise_date(basic["list_date"])
    if "delist_date" not in basic.columns:
        basic["delist_date"] = pd.NaT
    else:
        basic["delist_date"] = _normalise_date(basic["delist_date"])
    daily["trade_date"] = _normalise_date(daily["trade_date"])
    factors["trade_date"] = _normalise_date(factors["trade_date"])
    daily = daily.loc[daily["trade_date"].notna() & (daily["trade_date"] <= cutoff)].copy()
    factors = factors.loc[
        factors["trade_date"].notna() & (factors["trade_date"] <= cutoff)
    ].copy()
    if daily.duplicated(["ts_code", "trade_date"]).any():
        raise DataVendorUnavailable("market breadth daily contains duplicate code/date rows")
    if factors.duplicated(["ts_code", "trade_date"]).any():
        raise DataVendorUnavailable("market breadth adj_factor contains duplicate code/date rows")

    daily = daily.merge(factors, on=["ts_code", "trade_date"], how="left", validate="one_to_one")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily["pre_close"] = pd.to_numeric(daily["pre_close"], errors="coerce")
    daily["amount"] = pd.to_numeric(daily["amount"], errors="coerce")
    daily["adj_factor"] = pd.to_numeric(daily["adj_factor"], errors="coerce")
    daily["adjusted_close"] = daily["close"] * daily["adj_factor"]
    grouped = daily.groupby("ts_code", sort=False, group_keys=False)
    daily["history_count"] = grouped.cumcount() + 1
    daily["return"] = daily["close"] / daily["pre_close"] - 1.0
    daily["ma20"] = grouped["adjusted_close"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    daily["ma60"] = grouped["adjusted_close"].transform(
        lambda values: values.rolling(60, min_periods=60).mean()
    )
    daily["high20"] = grouped["adjusted_close"].transform(
        lambda values: values.rolling(20, min_periods=20).max()
    )
    daily["low20"] = grouped["adjusted_close"].transform(
        lambda values: values.rolling(20, min_periods=20).min()
    )
    daily["amount20_prior"] = grouped["amount"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).mean()
    )

    first_60 = (
        daily.loc[daily["history_count"] == 60, ["ts_code", "trade_date"]]
        .set_index("ts_code")["trade_date"]
        .to_dict()
    )
    suspension_pairs: set[tuple[str, Any]] = set()
    if inputs.suspensions is not None and not inputs.suspensions.empty:
        suspensions = inputs.suspensions.copy()
        if not {"ts_code", "trade_date"}.issubset(suspensions.columns):
            raise DataVendorUnavailable("market breadth suspensions missing ts_code/trade_date")
        suspensions["trade_date"] = _normalise_date(suspensions["trade_date"])
        suspension_pairs = set(zip(suspensions["ts_code"], suspensions["trade_date"], strict=False))
    return basic, daily, first_60, suspension_pairs


def _eligible_codes(basic, first_60: dict[str, Any], suspensions: set[tuple[str, Any]], day):
    listed = basic.loc[
        basic["list_date"].notna()
        & (basic["list_date"] <= day)
        & (basic["delist_date"].isna() | (basic["delist_date"] > day)),
        "ts_code",
    ]
    return {
        code
        for code in listed.astype(str)
        if code in first_60 and first_60[code] <= day and (code, day) not in suspensions
    }


def _cross_section_metrics(current, eligible: set[str]) -> dict[str, float | int]:
    import numpy as np  # noqa: PLC0415

    eligible_count = len(eligible)
    valid = current.loc[current["ts_code"].isin(eligible)].dropna(
        subset=[
            "return",
            "adjusted_close",
            "ma20",
            "ma60",
            "high20",
            "low20",
            "amount",
            "amount20_prior",
        ]
    )
    observed_count = len(valid)
    coverage = observed_count / eligible_count if eligible_count else 0.0
    if observed_count == 0:
        return {
            "eligible_count": eligible_count,
            "observed_count": 0,
            "coverage_ratio": coverage,
        }

    returns = valid["return"].astype(float)
    advances = int((returns > 0).sum())
    declines = int((returns < 0).sum())
    above20 = float((valid["adjusted_close"] > valid["ma20"]).mean())
    above60 = float((valid["adjusted_close"] > valid["ma60"]).mean())
    new_highs = int(np.isclose(valid["adjusted_close"], valid["high20"], equal_nan=False).sum())
    new_lows = int(np.isclose(valid["adjusted_close"], valid["low20"], equal_nan=False).sum())
    expansion = float((valid["amount"] > valid["amount20_prior"]).mean())
    amount = valid["amount"].clip(lower=0).astype(float).sort_values(ascending=False)
    top_count = max(1, math.ceil(observed_count * 0.10))
    total_amount = float(amount.sum())
    concentration = float(amount.head(top_count).sum() / total_amount) if total_amount > 0 else 0.0
    advance_decline = (advances - declines) / observed_count
    trend_signal = ((2 * above20 - 1) + (2 * above60 - 1)) / 2
    high_low = (new_highs - new_lows) / observed_count
    turnover_signal = 2 * expansion - 1
    composite = (advance_decline + trend_signal + high_low + turnover_signal) / 4
    return {
        "advance_decline_balance": float(advance_decline),
        "above_ma20_pct": above20,
        "above_ma60_pct": above60,
        "new_high_low_20d_balance": float(high_low),
        "turnover_expansion_pct": expansion,
        "return_dispersion": float(returns.std(ddof=0)),
        "top_decile_turnover_share": concentration,
        "breadth_composite": float(composite),
        "eligible_count": eligible_count,
        "observed_count": observed_count,
        "coverage_ratio": float(coverage),
    }


def compute_market_breadth_snapshot(
    inputs: BreadthInputs,
    as_of_date: str,
    *,
    min_percentile_observations: int = ROLLING_PERCENTILE_DAYS,
) -> dict[str, Any]:
    import pandas as pd  # noqa: PLC0415

    basic, daily, first_60, suspensions = _prepare_inputs(inputs, as_of_date)
    as_of = pd.Timestamp(as_of_date)
    dates = sorted(
        pd.Timestamp(day) for day in daily["trade_date"].dropna().unique() if day <= as_of
    )
    history: list[dict[str, Any]] = []
    for day in dates:
        eligible = _eligible_codes(basic, first_60, suspensions, day)
        metrics = _cross_section_metrics(daily.loc[daily["trade_date"] == day], eligible)
        if metrics.get("coverage_ratio", 0.0) >= CORE_COVERAGE_MIN and "breadth_composite" in metrics:
            history.append({"trade_date": day, **metrics})

    current_eligible = _eligible_codes(basic, first_60, suspensions, as_of)
    current = _cross_section_metrics(daily.loc[daily["trade_date"] == as_of], current_eligible)
    if current.get("coverage_ratio", 0.0) < CORE_COVERAGE_MIN:
        raise BreadthCoverageError(
            "market breadth core coverage below 90%: "
            f"{current.get('observed_count', 0)}/{current.get('eligible_count', 0)}"
        )
    history = [row for row in history if row["trade_date"] <= as_of]
    if len(history) < min_percentile_observations or len(history) < 21:
        raise BreadthHistoryError(
            f"market breadth requires {max(min_percentile_observations, 21)} valid PIT days; "
            f"found {len(history)}"
        )
    window = history[-ROLLING_PERCENTILE_DAYS:]
    composites = pd.Series([row["breadth_composite"] for row in window], dtype=float)
    concentrations = pd.Series([row["top_decile_turnover_share"] for row in window], dtype=float)
    q40 = float(composites.quantile(0.40))
    q60 = float(composites.quantile(0.60))
    concentration_q20 = float(concentrations.quantile(0.20))
    concentration_q80 = float(concentrations.quantile(0.80))
    delta20 = float(history[-1]["breadth_composite"] - history[-21]["breadth_composite"])
    composite = float(current["breadth_composite"])
    state = (
        "BROADENING"
        if composite > q60 and delta20 > 0
        else "NARROWING"
        if composite < q40 and delta20 < 0
        else "MIXED"
    )
    concentration_value = float(current["top_decile_turnover_share"])
    concentration_state = (
        "HIGH"
        if concentration_value > concentration_q80
        else "LOW"
        if concentration_value < concentration_q20
        else "NORMAL"
    )
    payload: dict[str, Any] = {
        "schema_version": BREADTH_SCHEMA_VERSION,
        "as_of_date": as_of_date,
        **{key: round(value, 10) if isinstance(value, float) else value for key, value in current.items()},
        "breadth_composite_change_20d": round(delta20, 10),
        "breadth_composite_q40_252d": round(q40, 10),
        "breadth_composite_q60_252d": round(q60, 10),
        "concentration_q20_252d": round(concentration_q20, 10),
        "concentration_q80_252d": round(concentration_q80, 10),
        "breadth_state": state,
        "concentration_state": concentration_state,
        "methodology": {
            "universe": "PIT listed/not-delisted, >=60 observations, known suspensions excluded",
            "adjustment": "only adjustment factors dated on/before as_of",
            "composite": "equal weight: advance/decline, trend breadth, new-high/low, turnover diffusion",
            "state_window": ROLLING_PERCENTILE_DAYS,
            "limit_diagnostics_in_core": False,
        },
    }
    payload["evidence_id"] = f"market_breadth:{as_of_date}"
    payload["snapshot_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return payload


def market_breadth_data_root() -> Path:
    explicit = os.getenv("MOSAIC_MARKET_BREADTH_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.getenv("MOSAIC_CACHE_DIR", "~/.mosaic/cache")).expanduser() / "market_breadth"


def _read_table(root: Path, stem: str, *, optional: bool = False):
    import pandas as pd  # noqa: PLC0415

    for suffix, reader in ((".parquet", pd.read_parquet), (".csv", pd.read_csv)):
        path = root / f"{stem}{suffix}"
        if path.is_file():
            return reader(path)
    if optional:
        return None
    raise DataVendorUnavailable(f"market breadth private PIT table missing: {root}/{stem}.parquet|csv")


def load_market_breadth_inputs(root: Path | None = None) -> BreadthInputs:
    data_root = root or market_breadth_data_root()
    return BreadthInputs(
        stock_basic=_read_table(data_root, "stock_basic"),
        daily=_read_table(data_root, "daily"),
        adj_factor=_read_table(data_root, "adj_factor"),
        suspensions=_read_table(data_root, "suspensions", optional=True),
    )


def render_market_breadth_snapshot(as_of_date: str, root: Path | None = None) -> str:
    return json.dumps(
        compute_market_breadth_snapshot(load_market_breadth_inputs(root), as_of_date),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_forward_breadth_confirmation(
    inputs: BreadthInputs,
    start_date: str,
    end_date: str,
    benchmark_return: float,
) -> dict[str, float]:
    """Score breadth change and PIT equal-weight A-shares versus benchmark 50/50."""
    import pandas as pd  # noqa: PLC0415

    start_snapshot = compute_market_breadth_snapshot(inputs, start_date)
    end_snapshot = compute_market_breadth_snapshot(inputs, end_date)
    basic, daily, first_60, suspensions = _prepare_inputs(inputs, end_date)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    universe = _eligible_codes(basic, first_60, suspensions, start)
    prices = daily.loc[
        daily["ts_code"].isin(universe) & daily["trade_date"].isin([start, end]),
        ["ts_code", "trade_date", "adjusted_close"],
    ].dropna()
    pivot = prices.pivot(index="ts_code", columns="trade_date", values="adjusted_close")
    if start not in pivot.columns or end not in pivot.columns:
        raise BreadthCoverageError("equal-weight breadth label is missing start/end prices")
    valid = pivot[[start, end]].dropna()
    coverage = len(valid) / len(universe) if universe else 0.0
    if coverage < CORE_COVERAGE_MIN:
        raise BreadthCoverageError(
            f"equal-weight breadth label coverage below 90%: {len(valid)}/{len(universe)}"
        )
    equal_weight_return = float((valid[end] / valid[start] - 1.0).mean())
    relative_return = equal_weight_return - float(benchmark_return)
    breadth_change = float(
        end_snapshot["breadth_composite"] - start_snapshot["breadth_composite"]
    )
    combined = 0.5 * breadth_change + 0.5 * relative_return
    return {
        "breadth_composite_change_5d": breadth_change,
        "equal_weight_relative_return_5d": relative_return,
        "combined_score_5d": combined,
    }


__all__ = [
    "BREADTH_SCHEMA_VERSION",
    "BreadthCoverageError",
    "BreadthHistoryError",
    "BreadthInputs",
    "CORE_COVERAGE_MIN",
    "ROLLING_PERCENTILE_DAYS",
    "compute_market_breadth_snapshot",
    "compute_forward_breadth_confirmation",
    "load_market_breadth_inputs",
    "market_breadth_data_root",
    "render_market_breadth_snapshot",
]
