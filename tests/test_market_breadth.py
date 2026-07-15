from __future__ import annotations

import pandas as pd
import pytest

from mosaic.dataflows.market_breadth import (
    BreadthCoverageError,
    BreadthInputs,
    compute_forward_breadth_confirmation,
    compute_market_breadth_snapshot,
)


def breadth_inputs(periods=330) -> tuple[BreadthInputs, pd.DatetimeIndex]:
    dates = pd.bdate_range("2023-01-02", periods=periods)
    basic = pd.DataFrame(
        [
            {"ts_code": "A.SH", "list_date": dates[0], "delist_date": None},
            {"ts_code": "B.SZ", "list_date": dates[10], "delist_date": None},
            {"ts_code": "C.SH", "list_date": dates[0], "delist_date": dates[-5]},
            {"ts_code": "NEW.SZ", "list_date": dates[-20], "delist_date": None},
        ]
    )
    daily_rows = []
    factor_rows = []
    for code, start, end in (
        ("A.SH", 0, periods),
        ("B.SZ", 10, periods),
        ("C.SH", 0, periods - 5),
        ("NEW.SZ", periods - 20, periods),
    ):
        prior = 100.0
        for index in range(start, end):
            day = dates[index]
            trend = 1.0 + (0.001 if code != "C.SH" else -0.0003)
            adjusted = prior * trend
            factor = 2.0 if code == "A.SH" and index >= 170 else 1.0
            raw_close = adjusted / factor
            raw_pre_close = raw_close / trend
            daily_rows.append(
                {
                    "ts_code": code,
                    "trade_date": day,
                    "close": raw_close,
                    "pre_close": raw_pre_close,
                    "amount": 1000 + index * (3 if code == "A.SH" else 2),
                }
            )
            factor_rows.append(
                {"ts_code": code, "trade_date": day, "adj_factor": factor}
            )
            prior = adjusted
    return (
        BreadthInputs(
            stock_basic=basic,
            daily=pd.DataFrame(daily_rows),
            adj_factor=pd.DataFrame(factor_rows),
            suspensions=pd.DataFrame(columns=["ts_code", "trade_date"]),
        ),
        dates,
    )


def test_pit_universe_excludes_delisted_and_new_names_without_survivorship_shortcuts():
    inputs, dates = breadth_inputs()
    snapshot = compute_market_breadth_snapshot(inputs, dates[-1].date().isoformat())
    assert snapshot["eligible_count"] == 2  # A/B; C delisted, NEW has <60 observations
    assert snapshot["observed_count"] == 2
    assert snapshot["coverage_ratio"] == 1.0
    assert snapshot["methodology"]["limit_diagnostics_in_core"] is False


def test_known_suspension_is_excluded_but_missing_unsuspended_data_rejects_stage():
    inputs, dates = breadth_inputs()
    as_of = dates[-1]
    inputs.daily.drop(
        inputs.daily.index[
            (inputs.daily["ts_code"] == "B.SZ") & (inputs.daily["trade_date"] == as_of)
        ],
        inplace=True,
    )
    inputs.adj_factor.drop(
        inputs.adj_factor.index[
            (inputs.adj_factor["ts_code"] == "B.SZ")
            & (inputs.adj_factor["trade_date"] == as_of)
        ],
        inplace=True,
    )
    with pytest.raises(BreadthCoverageError, match="below 90%"):
        compute_market_breadth_snapshot(inputs, as_of.date().isoformat())

    suspended_inputs = BreadthInputs(
        inputs.stock_basic,
        inputs.daily,
        inputs.adj_factor,
        pd.DataFrame([{"ts_code": "B.SZ", "trade_date": as_of}]),
    )
    snapshot = compute_market_breadth_snapshot(suspended_inputs, as_of.date().isoformat())
    assert snapshot["eligible_count"] == 1
    assert snapshot["coverage_ratio"] == 1.0


def test_adjustment_and_future_rows_do_not_leak_into_as_of_snapshot():
    inputs, dates = breadth_inputs()
    as_of = dates[-10].date().isoformat()
    baseline = compute_market_breadth_snapshot(inputs, as_of)
    future_daily = inputs.daily.loc[inputs.daily["trade_date"] > pd.Timestamp(as_of)].copy()
    future_daily["close"] *= 100
    future_factors = inputs.adj_factor.loc[
        inputs.adj_factor["trade_date"] > pd.Timestamp(as_of)
    ].copy()
    future_factors["adj_factor"] *= 50
    leaked = BreadthInputs(
        inputs.stock_basic,
        pd.concat([inputs.daily.loc[inputs.daily["trade_date"] <= pd.Timestamp(as_of)], future_daily]),
        pd.concat(
            [
                inputs.adj_factor.loc[inputs.adj_factor["trade_date"] <= pd.Timestamp(as_of)],
                future_factors,
            ]
        ),
        inputs.suspensions,
    )
    assert compute_market_breadth_snapshot(leaked, as_of) == baseline
    assert baseline["above_ma60_pct"] == pytest.approx(2 / 3)


def test_rolling_252_day_state_and_50_50_forward_label_are_deterministic():
    inputs, dates = breadth_inputs()
    snapshot = compute_market_breadth_snapshot(inputs, dates[-1].date().isoformat())
    assert snapshot["breadth_state"] in {"BROADENING", "NARROWING", "MIXED"}
    assert snapshot["concentration_state"] in {"HIGH", "LOW", "NORMAL"}
    assert snapshot["breadth_composite_q40_252d"] <= snapshot["breadth_composite_q60_252d"]

    components = compute_forward_breadth_confirmation(
        inputs,
        dates[-5].date().isoformat(),
        dates[-1].date().isoformat(),
        benchmark_return=0.01,
    )
    expected = 0.5 * components["breadth_composite_change_5d"] + 0.5 * components[
        "equal_weight_relative_return_5d"
    ]
    assert components["combined_score_5d"] == pytest.approx(expected)
