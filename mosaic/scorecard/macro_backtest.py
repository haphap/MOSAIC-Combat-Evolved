"""Benchmark-fallback vs agent-specific macro label backtest comparison.

The companion to the P6 rollout gate (``macro_full_label_sources_enabled``):
re-scores already-matured ``macro_signals`` two ways — the validated PR #73
benchmark set vs the full agent-specific path labels — *without* persisting, and
reports per-agent / overall skill so an operator can decide whether to flip the
gate. keep/revert remains a portfolio-ΔSharpe decision; this only compares the
macro proxy signal quality.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Optional


def _agg(raws: list[float], hits: list[int]) -> dict[str, Any]:
    n = len(raws)
    if n == 0:
        return {"n": 0, "mean_raw": None, "hit_rate": None, "sharpe": None}
    mean = sum(raws) / n
    hit_rate = sum(hits) / len(hits) if hits else None
    sharpe: Optional[float] = None
    if n >= 5:
        var = sum((x - mean) ** 2 for x in raws) / max(n - 1, 1)
        std = math.sqrt(var)
        sharpe = 0.0 if std == 0 else (mean / std) * math.sqrt(252.0 / 5.0)
    return {"n": n, "mean_raw": mean, "hit_rate": hit_rate, "sharpe": sharpe}


def compare_label_sources(
    store,
    cohort: str,
    *,
    today: str,
    since: Optional[str] = None,
    benchmark: Optional[str] = None,
) -> dict[str, Any]:
    """Compare benchmark-fallback vs agent-specific scoring over matured signals.

    Returns ``{cohort, n_signals, benchmark, agent_specific, by_agent, delta}``
    where each family report is ``{n, mean_raw, hit_rate, sharpe}`` and
    ``agent_specific`` also carries ``primary_rate`` / ``fallback_rate``.
    """
    from mosaic.dataflows.calendar import next_trading_day, previous_trading_day
    from mosaic.scorecard.macro_labels import BENCHMARK_FALLBACK_LABEL
    from mosaic.scorecard.scorer import MacroScorer, _fetch_close
    from mosaic.scorecard.store import PendingMacroRow

    last_trading_day = previous_trading_day(today, 0)
    cutoff_5d = previous_trading_day(last_trading_day, 5)
    rows = store.list_macro_signals(cohort, since_date=since, before_date=cutoff_5d)

    bench_scorer = MacroScorer(
        store, benchmark=benchmark, agent_specific_labels_enabled=True,
        full_label_sources_enabled=False,
    )
    full_scorer = MacroScorer(
        store, benchmark=benchmark, agent_specific_labels_enabled=True,
        full_label_sources_enabled=True,
    )

    bench_cache: dict[str, Optional[float]] = {}

    def _bclose(date_iso: str) -> Optional[float]:
        if date_iso not in bench_cache:
            bench_cache[date_iso] = _fetch_close(bench_scorer.benchmark, date_iso)
        return bench_cache[date_iso]

    per_agent: dict[str, dict[str, list]] = defaultdict(
        lambda: {"b_raw": [], "b_hit": [], "a_raw": [], "a_hit": [], "a_status": []}
    )

    for r in rows:
        d0 = r["date"]
        t5 = next_trading_day(d0, 5)
        if t5 > last_trading_day:
            continue
        b0, b5 = _bclose(d0), _bclose(t5)
        if b0 in (None, 0) or b5 is None:
            continue
        bench_ret = (b5 - b0) / b0
        row = PendingMacroRow(
            id=int(r["id"]), cohort=cohort, agent=r["agent"], date=d0,
            vote=int(r["vote"]), confidence=r["confidence"], influence_weight_equal=None,
        )
        bf = bench_scorer._benchmark_label_fields(
            row=row, bench_ret=bench_ret, label_type="benchmark_5d", label_source_status="primary",
        )
        af = full_scorer._agent_specific_label_fields(row=row, bench_ret=bench_ret, t_5d=t5)
        if af is None:
            af = full_scorer._benchmark_label_fields(
                row=row, bench_ret=bench_ret,
                label_type=BENCHMARK_FALLBACK_LABEL, label_source_status="fallback",
            )
        pa = per_agent[r["agent"]]
        pa["b_raw"].append(bf["raw_macro_score_5d"])
        pa["b_hit"].append(bf["hit_5d"])
        pa["a_raw"].append(af["raw_macro_score_5d"])
        pa["a_hit"].append(af["hit_5d"])
        pa["a_status"].append(af["label_source_status"])

    all_b_raw, all_b_hit, all_a_raw, all_a_hit, all_status = [], [], [], [], []
    by_agent: dict[str, Any] = {}
    for agent, pa in sorted(per_agent.items()):
        all_b_raw += pa["b_raw"]
        all_b_hit += pa["b_hit"]
        all_a_raw += pa["a_raw"]
        all_a_hit += pa["a_hit"]
        all_status += pa["a_status"]
        n = len(pa["a_status"]) or 1
        by_agent[agent] = {
            "benchmark": _agg(pa["b_raw"], pa["b_hit"]),
            "agent_specific": _agg(pa["a_raw"], pa["a_hit"]),
            "primary_rate": sum(s == "primary" for s in pa["a_status"]) / n,
            "fallback_rate": sum(s == "fallback" for s in pa["a_status"]) / n,
        }

    bench = _agg(all_b_raw, all_b_hit)
    agent_specific = _agg(all_a_raw, all_a_hit)
    n_all = len(all_status) or 1
    agent_specific["primary_rate"] = sum(s == "primary" for s in all_status) / n_all
    agent_specific["fallback_rate"] = sum(s == "fallback" for s in all_status) / n_all

    def _d(a: Optional[float], b: Optional[float]) -> Optional[float]:
        return None if a is None or b is None else a - b

    return {
        "cohort": cohort,
        "n_signals": len(all_status),
        "benchmark": bench,
        "agent_specific": agent_specific,
        "by_agent": by_agent,
        "delta": {
            "mean_raw": _d(agent_specific["mean_raw"], bench["mean_raw"]),
            "hit_rate": _d(agent_specific["hit_rate"], bench["hit_rate"]),
            "sharpe": _d(agent_specific["sharpe"], bench["sharpe"]),
        },
    }
