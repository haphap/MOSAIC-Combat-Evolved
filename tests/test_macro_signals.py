"""Tests for the macro_signals path (autoresearch macro plan, Phases 1-3):
expand → ingest → benchmark-5d scoring → list_macro_skill. No network: the
benchmark price fetch + trading calendar are monkeypatched.
"""

from __future__ import annotations

import datetime as _dt
import unittest
from unittest.mock import patch

from mosaic.scorecard import expand_state_to_macro_signals, expand_state_to_recommendations
from mosaic.scorecard.macro_labels import (
    BENCHMARK_FALLBACK_LABEL,
    list_macro_label_inventory,
    primary_label_for_agent,
)
from mosaic.scorecard.store import ScorecardStore
from mosaic.scorecard.scorer import MacroScorer


def _state(outputs: dict, date: str = "2024-01-02", cohort: str = "cohort_default") -> dict:
    return {
        "active_cohort": cohort,
        "as_of_date": date,
        "layer1_outputs": outputs,
        "layer1_consensus": {"stance": "BULLISH", "confidence": 0.6},
    }


# Deterministic calendar: ±N calendar days (good enough for unit tests).
def _ntd(d: str, n: int) -> str:
    return (_dt.date.fromisoformat(d) + _dt.timedelta(days=n)).isoformat()


def _ptd(d: str, n: int) -> str:
    return (_dt.date.fromisoformat(d) - _dt.timedelta(days=n)).isoformat()


def _cal_patch():
    return patch.multiple(
        "mosaic.dataflows.calendar", next_trading_day=_ntd, previous_trading_day=_ptd
    )


class TestExpand(unittest.TestCase):
    def test_vote_mapping(self):
        rows = expand_state_to_macro_signals(
            _state(
                {
                    "central_bank": {"agent": "central_bank", "stance": "ACCOMMODATIVE", "confidence": 0.8},
                    "yield_curve": {"agent": "yield_curve", "recession_signal": "RED", "confidence": 0.5},
                    "volatility": {"agent": "volatility", "regime_filter": "NEUTRAL", "confidence": 0.4},
                    "institutional_flow": {
                        "agent": "institutional_flow",
                        "sectors_in_out": [{"net_amount_cny": 1500}, {"net_amount_cny": -200}],
                        "confidence": 0.6,
                    },
                }
            )
        )
        by = {r["agent"]: r for r in rows}
        self.assertEqual(by["central_bank"]["vote"], 1)
        self.assertEqual(by["yield_curve"]["vote"], -1)
        self.assertEqual(by["volatility"]["vote"], 0)
        self.assertEqual(by["institutional_flow"]["vote"], 1)  # net +1300 > 1000
        self.assertEqual(by["central_bank"]["consensus_stance"], "BULLISH")

    def test_macro_excluded_from_recommendations(self):
        st = _state({"central_bank": {"agent": "central_bank", "stance": "TIGHTENING", "confidence": 0.5}})
        self.assertEqual(expand_state_to_recommendations(st), [])
        self.assertEqual(len(expand_state_to_macro_signals(st)), 1)

    def test_as_of_date_required(self):
        with self.assertRaises(ValueError):
            expand_state_to_macro_signals({"active_cohort": "c", "layer1_outputs": {}})


class TestIngestIdempotent(unittest.TestCase):
    def test_idempotent_upsert(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as d:
            store = ScorecardStore(db_path=os.path.join(d, "t.db"))
            st = _state({"dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5}})
            self.assertEqual(store.append_macro_signals_from_state(st), 1)
            store.append_macro_signals_from_state(st)  # re-ingest
            with store._connect() as conn:
                n = conn.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
            self.assertEqual(n, 1)


class TestMacroScorer(unittest.TestCase):
    def _run(self, vote_output, bench_ret, today="2024-02-01", neutral_band=None):
        import tempfile
        import os
        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(_state(vote_output, date=d0))

        t5 = _ntd(d0, 5)
        closes = {(d0): 100.0, (t5): 100.0 * (1.0 + bench_ret)}

        def fake_close(ts, date):
            return closes.get(date)

        def fake_series(ts, start, end):
            return [100.0, 101.0, 100.5, 101.5, 100.0, 101.0]  # nonzero vol

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", fake_series):
            out = MacroScorer(
                store,
                benchmark="000300.SH",
                neutral_band=neutral_band,
                agent_specific_labels_enabled=False,
            ).score_pending("cohort_default", today)
        with store._connect() as conn:
            row = conn.execute(
                "SELECT vote, realized_label, hit_5d, raw_macro_score_5d, label_source_status, scored_at "
                "FROM macro_signals"
            ).fetchone()
        return out, dict(row)

    def test_bullish_vote_benchmark_up_hits_positive(self):
        out, row = self._run(
            {"volatility": {"agent": "volatility", "regime_filter": "RISK_ON", "confidence": 0.8}},
            bench_ret=0.03,
        )
        self.assertEqual(out["macro_scored"], 1)
        self.assertEqual(row["vote"], 1)
        self.assertEqual(row["realized_label"], 1)
        self.assertEqual(row["hit_5d"], 1)
        self.assertGreater(row["raw_macro_score_5d"], 0)

    def test_bearish_vote_benchmark_down_hits_positive(self):
        _, row = self._run(
            {"yield_curve": {"agent": "yield_curve", "recession_signal": "RED", "confidence": 0.7}},
            bench_ret=-0.03,
        )
        self.assertEqual(row["vote"], -1)
        self.assertEqual(row["realized_label"], -1)
        self.assertEqual(row["hit_5d"], 1)
        self.assertGreater(row["raw_macro_score_5d"], 0)  # vote*move = (-1)*(neg) > 0

    def test_neutral_small_move_positive_big_move_negative(self):
        _, small = self._run(
            {"volatility": {"agent": "volatility", "regime_filter": "NEUTRAL", "confidence": 0.6}},
            bench_ret=0.001,  # within band
        )
        self.assertEqual(small["realized_label"], 0)
        self.assertGreater(small["raw_macro_score_5d"], 0)
        _, big = self._run(
            {"volatility": {"agent": "volatility", "regime_filter": "NEUTRAL", "confidence": 0.6}},
            bench_ret=0.05,  # big move
        )
        self.assertLess(big["raw_macro_score_5d"], 0)

    def test_neutral_band_override_controls_realized_label(self):
        _, row = self._run(
            {"volatility": {"agent": "volatility", "regime_filter": "RISK_ON", "confidence": 0.8}},
            bench_ret=0.01,
            neutral_band=0.02,
        )
        self.assertEqual(row["realized_label"], 0)
        self.assertEqual(row["hit_5d"], 0)

    def test_missing_benchmark_marks_scored(self):
        import tempfile
        import os
        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state({"dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5}}, date=d0)
        )
        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", lambda ts, date: None), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: []):
            out = MacroScorer(store).score_pending("cohort_default", "2024-02-01")
        self.assertEqual(out["macro_skipped_missing"], 1)
        with store._connect() as conn:
            r = conn.execute("SELECT scored_at, label_source_status FROM macro_signals").fetchone()
        self.assertIsNotNone(r["scored_at"])      # not pending forever
        self.assertEqual(r["label_source_status"], "missing")


class TestMacroSkill(unittest.TestCase):
    def test_aggregation(self):
        import tempfile
        import os
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        # two scored rows for one agent
        store.append_macro_signals_from_state(
            _state({"dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5}}, date="2024-01-02")
        )
        with store._connect() as conn:
            rid = conn.execute("SELECT id FROM macro_signals").fetchone()[0]
        store.update_macro_scoring(rid, {"hit_5d": 1, "raw_macro_score_5d": 0.02, "scored_at": "2024-02-01"})
        rows = store.list_macro_skill("cohort_default")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "dollar")
        self.assertAlmostEqual(rows[0]["mean_raw_macro_score_5d"], 0.02)
        self.assertEqual(rows[0]["hit_rate_5d"], 1.0)
        self.assertIsNone(rows[0]["sharpe_window"])  # n_obs < 5

    def test_sharpe_window_uses_5d_horizon_annualization(self):
        import tempfile
        import os
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        scores = [0.01, 0.02, -0.01, 0.03, 0.0]
        for i, score in enumerate(scores, start=1):
            date = f"2024-01-0{i}"
            store.append_macro_signals_from_state(
                _state(
                    {"dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5}},
                    date=date,
                )
            )
            with store._connect() as conn:
                rid = conn.execute(
                    "SELECT id FROM macro_signals WHERE agent='dollar' AND date=?",
                    (date,),
                ).fetchone()[0]
            store.update_macro_scoring(
                rid,
                {"hit_5d": 1, "raw_macro_score_5d": score, "scored_at": "2024-02-01"},
            )

        row = store.list_macro_skill("cohort_default")[0]
        mean = sum(scores) / len(scores)
        var = sum((x - mean) ** 2 for x in scores) / (len(scores) - 1)
        expected = (mean / (var ** 0.5)) * ((252.0 / 5.0) ** 0.5)
        self.assertAlmostEqual(row["sharpe_window"], expected)


class TestMacroAgentSpecificLabels(unittest.TestCase):
    def test_inventory_exposes_sources_and_primary_gate(self):
        rows = list_macro_label_inventory()
        self.assertGreaterEqual(len(rows), 20)
        by_key = {(r["agent"], r["label_type"]): r for r in rows}
        self.assertTrue(by_key[("volatility", "max_drawdown_5d")]["available_now"])
        self.assertEqual(
            by_key[("institutional_flow", "flow_continuation_5d")]["implementation_status"],
            "deferred",
        )
        self.assertIn("主力资金流", by_key[("institutional_flow", "flow_continuation_5d")]["data_source"])
        self.assertEqual(primary_label_for_agent("volatility").label_type, "max_drawdown_5d")
        self.assertIsNone(primary_label_for_agent("dollar"))

    def test_available_agent_specific_label_is_primary(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state(
                {
                    "volatility": {
                        "agent": "volatility",
                        "regime_filter": "RISK_OFF",
                        "confidence": 0.8,
                    }
                },
                date=d0,
            )
        )
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 98.0}.get(date)

        def fake_series(ts, start, end):
            return [100.0, 103.0, 97.0, 99.0, 98.0]

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", fake_series):
            MacroScorer(store, benchmark="000300.SH").score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status, label_value_5d, "
                "realized_label, hit_5d, raw_macro_score_5d FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], "max_drawdown_5d")
        self.assertEqual(row["label_source_status"], "primary")
        self.assertLess(row["label_value_5d"], -0.005)
        self.assertEqual(row["realized_label"], -1)
        self.assertEqual(row["hit_5d"], 1)
        self.assertGreater(row["raw_macro_score_5d"], 0)

    def test_max_drawdown_endpoint_only_series_is_marked_fallback(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state(
                {
                    "volatility": {
                        "agent": "volatility",
                        "regime_filter": "RISK_OFF",
                        "confidence": 0.8,
                    }
                },
                date=d0,
            )
        )
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 98.0}.get(date)

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100.0]):
            MacroScorer(store, benchmark="000300.SH").score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], "max_drawdown_5d")
        self.assertEqual(row["label_source_status"], "fallback")

    def test_unavailable_agent_label_records_benchmark_fallback(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state(
                {"dollar": {"agent": "dollar", "dxy_trend": "WEAKENING", "confidence": 0.5}},
                date=d0,
            )
        )
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 102.0}.get(date)

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]):
            MacroScorer(store, benchmark="000300.SH").score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], BENCHMARK_FALLBACK_LABEL)
        self.assertEqual(row["label_source_status"], "fallback")


class TestMacroInfluenceDiagnostics(unittest.TestCase):
    def test_expand_records_equal_weight_leave_one_out_influence(self):
        rows = expand_state_to_macro_signals(
            _state(
                {
                    "central_bank": {
                        "agent": "central_bank",
                        "stance": "ACCOMMODATIVE",
                        "confidence": 1.0,
                    },
                    "yield_curve": {
                        "agent": "yield_curve",
                        "recession_signal": "RED",
                        "confidence": 1.0,
                    },
                }
            )
        )
        by = {r["agent"]: r for r in rows}
        self.assertAlmostEqual(by["central_bank"]["influence_weight_equal"], 1.0)
        self.assertAlmostEqual(by["yield_curve"]["influence_weight_equal"], 1.0)

    def test_effective_macro_score_is_influence_scaled_diagnostic(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state(
                {
                    "central_bank": {
                        "agent": "central_bank",
                        "stance": "ACCOMMODATIVE",
                        "confidence": 1.0,
                    },
                    "yield_curve": {
                        "agent": "yield_curve",
                        "recession_signal": "RED",
                        "confidence": 1.0,
                    },
                },
                date=d0,
            )
        )
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 102.0}.get(date)

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]):
            MacroScorer(
                store,
                benchmark="000300.SH",
                agent_specific_labels_enabled=False,
            ).score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            rows = conn.execute(
                "SELECT raw_macro_score_5d, influence_weight_equal, "
                "effective_macro_score_5d FROM macro_signals ORDER BY agent"
            ).fetchall()
        for row in rows:
            self.assertAlmostEqual(
                row["effective_macro_score_5d"],
                row["raw_macro_score_5d"] * row["influence_weight_equal"],
            )
        skill = {r["agent"]: r for r in store.list_macro_skill("cohort_default")}
        self.assertIsNotNone(skill["central_bank"]["mean_effective_macro_score_5d"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
