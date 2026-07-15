"""Tests for the macro_signals path (autoresearch macro plan, Phases 1-3):
expand → ingest → benchmark-5d scoring → list_macro_skill. No network: the
benchmark price fetch + trading calendar are monkeypatched.
"""

from __future__ import annotations

import datetime as _dt
import unittest
from unittest.mock import patch

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.scorecard import expand_state_to_macro_signals, expand_state_to_recommendations
from mosaic.scorecard.macro_aggregation import aggregate_macro_transmissions
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
        "day_outcome_status": "accepted",
        "layer1_outputs": outputs,
        "layer1_consensus": {"stance": "BULLISH", "confidence": 0.6},
    }


def _macro(
    agent: str,
    direction: str = "NEUTRAL",
    confidence: float = 0.7,
    strength: int | None = None,
) -> dict:
    return {
        "agent": agent,
        "direction": direction,
        "strength": strength if strength is not None else (0 if direction == "NEUTRAL" else 5),
        "confidence": confidence,
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
                    "central_bank": _macro("central_bank", "SUPPORTIVE", 0.8),
                    "yield_curve": _macro("yield_curve", "ADVERSE", 0.5),
                    "volatility": _macro("volatility", "NEUTRAL", 0.4),
                    "institutional_flow": _macro("institutional_flow", "SUPPORTIVE", 0.6),
                }
            )
        )
        by = {r["agent"]: r for r in rows}
        self.assertEqual(by["central_bank"]["vote"], 1)
        self.assertEqual(by["yield_curve"]["vote"], -1)
        self.assertEqual(by["volatility"]["vote"], 0)
        self.assertEqual(by["institutional_flow"]["vote"], 1)
        self.assertEqual(by["central_bank"]["signal"], 1.0)
        self.assertEqual(by["yield_curve"]["signal"], -1.0)
        self.assertEqual(by["central_bank"]["consensus_stance"], "BULLISH")

    def test_signal_scales_direction_by_strength(self):
        rows = expand_state_to_macro_signals(
            _state({"china": _macro("china", "SUPPORTIVE", strength=2)})
        )
        self.assertEqual(rows[0]["vote"], 1)
        self.assertEqual(rows[0]["signal"], 0.4)

    def test_macro_excluded_from_recommendations(self):
        st = _state({"central_bank": _macro("central_bank", "ADVERSE", 0.5)})
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
            st = _state({"dollar": _macro("dollar", "SUPPORTIVE", 0.5)})
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
                "SELECT vote, signal, realized_label, hit_5d, raw_macro_score_5d, "
                "label_source_status, scored_at "
                "FROM macro_signals"
            ).fetchone()
        return out, dict(row)

    def test_bullish_vote_benchmark_up_hits_positive(self):
        out, row = self._run(
            {"volatility": _macro("volatility", "SUPPORTIVE", 0.8)},
            bench_ret=0.03,
        )
        self.assertEqual(out["macro_scored"], 1)
        self.assertEqual(row["vote"], 1)
        self.assertEqual(row["realized_label"], 1)
        self.assertEqual(row["hit_5d"], 1)
        self.assertGreater(row["raw_macro_score_5d"], 0)

    def test_bearish_vote_benchmark_down_hits_positive(self):
        _, row = self._run(
            {"yield_curve": _macro("yield_curve", "ADVERSE", 0.7)},
            bench_ret=-0.03,
        )
        self.assertEqual(row["vote"], -1)
        self.assertEqual(row["realized_label"], -1)
        self.assertEqual(row["hit_5d"], 1)
        self.assertGreater(row["raw_macro_score_5d"], 0)  # vote*move = (-1)*(neg) > 0

    def test_neutral_small_move_positive_big_move_negative(self):
        _, small = self._run(
            {"volatility": _macro("volatility", "NEUTRAL", 0.6)},
            bench_ret=0.001,  # within band
        )
        self.assertEqual(small["realized_label"], 0)
        self.assertGreater(small["raw_macro_score_5d"], 0)
        _, big = self._run(
            {"volatility": _macro("volatility", "NEUTRAL", 0.6)},
            bench_ret=0.05,  # big move
        )
        self.assertLess(big["raw_macro_score_5d"], 0)

    def test_neutral_band_override_controls_realized_label(self):
        _, row = self._run(
            {"volatility": _macro("volatility", "SUPPORTIVE", 0.8)},
            bench_ret=0.01,
            neutral_band=0.02,
        )
        self.assertEqual(row["realized_label"], 0)
        self.assertEqual(row["hit_5d"], 0)

    def test_raw_score_uses_strength_scaled_signal(self):
        _, weak = self._run(
            {"china": _macro("china", "SUPPORTIVE", 0.8, strength=1)},
            bench_ret=0.03,
        )
        _, strong = self._run(
            {"china": _macro("china", "SUPPORTIVE", 0.8, strength=5)},
            bench_ret=0.03,
        )
        self.assertEqual(weak["signal"], 0.2)
        self.assertAlmostEqual(
            weak["raw_macro_score_5d"],
            strong["raw_macro_score_5d"] / 5,
        )

    def test_missing_benchmark_marks_scored(self):
        import tempfile
        import os
        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state({"dollar": _macro("dollar", "SUPPORTIVE", 0.5)}, date=d0)
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
            _state({"dollar": _macro("dollar", "SUPPORTIVE", 0.5)}, date="2024-01-02")
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
                    {"dollar": _macro("dollar", "SUPPORTIVE", 0.5)},
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
        expected_primary = {
            "central_bank": "rate_sensitive_path_5d",
            "china": "china_growth_proxy_path_5d",
            "us_economy": "us_demand_transmission_path_5d",
            "geopolitical": "risk_off_path_5d",
            "dollar": "cny_pressure_path_5d",
            "yield_curve": "curve_sensitive_path_5d",
            "commodities": "commodity_basket_path_5d",
            "volatility": "volatility_shock_path_5d",
            "market_breadth": "market_breadth_confirmation_5d",
            "institutional_flow": "flow_followthrough_path_5d",
        }
        for agent, label_type in expected_primary.items():
            self.assertTrue(by_key[(agent, label_type)]["available_now"])
            self.assertEqual(
                by_key[(agent, label_type)]["implementation_status"],
                "implemented",
            )
            self.assertEqual(primary_label_for_agent(agent).label_type, label_type)
        self.assertTrue(by_key[("volatility", "max_drawdown_5d")]["available_now"])
        self.assertEqual(
            by_key[("institutional_flow", "flow_continuation_5d")]["implementation_status"],
            "deferred",
        )
        self.assertIn("主力资金流", by_key[("institutional_flow", "flow_continuation_5d")]["data_source"])

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
                        **_macro("volatility", "ADVERSE", 0.8),
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
            MacroScorer(store, benchmark="000300.SH", full_label_sources_enabled=True).score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status, label_value_5d, terminal_return_5d, "
                "max_drawdown_5d, path_metric_5d, source_series_id, realized_label, "
                "hit_5d, raw_macro_score_5d FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], "volatility_shock_path_5d")
        self.assertEqual(row["label_source_status"], "primary")
        self.assertIsNotNone(row["source_series_id"])
        self.assertLess(row["max_drawdown_5d"], -0.005)
        self.assertLess(row["label_value_5d"], -0.005)
        self.assertEqual(row["label_value_5d"], row["path_metric_5d"])
        self.assertLess(row["terminal_return_5d"], 0)
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
                    "volatility": _macro("volatility", "ADVERSE", 0.8)
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
            MacroScorer(store, benchmark="000300.SH", full_label_sources_enabled=True).score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], "volatility_shock_path_5d")
        self.assertEqual(row["label_source_status"], "fallback")

    def test_unavailable_agent_label_records_primary_label_with_fallback_status(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state(
                {"dollar": _macro("dollar", "SUPPORTIVE", 0.5)},
                date=d0,
            )
        )
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 102.0}.get(date)

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]), \
             patch("mosaic.scorecard.scorer._fetch_instrument_series", lambda *a: []):
            MacroScorer(store, benchmark="000300.SH", full_label_sources_enabled=True).score_pending("cohort_default", "2024-02-01")

        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], "cny_pressure_path_5d")
        self.assertEqual(row["label_source_status"], "fallback")

    def test_missing_breadth_label_is_not_replaced_by_benchmark(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(
            _state(
                {"market_breadth": _macro("market_breadth", "SUPPORTIVE", 0.7)},
                date=d0,
            )
        )
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 102.0}.get(date)

        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]), \
             patch(
                 "mosaic.dataflows.market_breadth.load_market_breadth_inputs",
                 side_effect=DataVendorUnavailable("private PIT table missing"),
             ):
            out = MacroScorer(
                store,
                benchmark="000300.SH",
                full_label_sources_enabled=True,
            ).score_pending("cohort_default", "2024-02-01")

        self.assertEqual(out["macro_scored"], 0)
        self.assertEqual(out["macro_skipped_missing"], 1)
        with store._connect() as conn:
            row = conn.execute(
                "SELECT label_type, label_source_status, raw_macro_score_5d, "
                "source_series_id FROM macro_signals"
            ).fetchone()
        self.assertEqual(row["label_type"], "market_breadth_confirmation_5d")
        self.assertEqual(row["label_source_status"], "missing")
        self.assertIsNone(row["raw_macro_score_5d"])
        self.assertEqual(
            row["source_series_id"],
            "market_breadth:required_label_unavailable",
        )

    def test_all_macro_agents_score_with_primary_path_label(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        outputs = {
            agent: _macro(agent, "SUPPORTIVE", 0.7)
            for agent in (
                "china",
                "us_economy",
                "central_bank",
                "dollar",
                "yield_curve",
                "commodities",
                "geopolitical",
                "volatility",
                "market_breadth",
                "institutional_flow",
            )
        }
        expected_labels = {
            "central_bank": "rate_sensitive_path_5d",
            "china": "china_growth_proxy_path_5d",
            "us_economy": "us_demand_transmission_path_5d",
            "geopolitical": "risk_off_path_5d",
            "dollar": "cny_pressure_path_5d",
            "yield_curve": "curve_sensitive_path_5d",
            "commodities": "commodity_basket_path_5d",
            "volatility": "volatility_shock_path_5d",
            "market_breadth": "market_breadth_confirmation_5d",
            "institutional_flow": "flow_followthrough_path_5d",
        }
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        store.append_macro_signals_from_state(_state(outputs, date=d0))
        t5 = _ntd(d0, 5)

        def fake_close(ts, date):
            return {d0: 100.0, t5: 102.0}.get(date)

        dated = [(d0, 100.0), (_ntd(d0, 1), 101.0), (t5, 102.0)]
        with _cal_patch(), \
             patch("mosaic.scorecard.scorer._fetch_close", fake_close), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series", lambda *a: [100, 101, 102]), \
             patch("mosaic.scorecard.scorer._fetch_instrument_series", lambda *a: [100, 101, 102]), \
             patch("mosaic.scorecard.scorer._fetch_benchmark_series_dated", lambda *a: dated), \
             patch("mosaic.scorecard.scorer._fetch_instrument_series_dated", lambda *a: dated), \
             patch("mosaic.dataflows.market_breadth.load_market_breadth_inputs", return_value=object()), \
             patch(
                 "mosaic.dataflows.market_breadth.compute_forward_breadth_confirmation",
                 return_value={
                     "breadth_composite_change_5d": 0.01,
                     "equal_weight_relative_return_5d": 0.01,
                     "combined_score_5d": 0.01,
                 },
             ):
            out = MacroScorer(store, benchmark="000300.SH", full_label_sources_enabled=True).score_pending("cohort_default", "2024-02-01")

        self.assertEqual(out["macro_scored"], 10)
        with store._connect() as conn:
            rows = conn.execute(
                "SELECT agent, label_type, label_source_status, path_metric_5d, source_series_id "
                "FROM macro_signals ORDER BY agent"
            ).fetchall()
        self.assertEqual({r["agent"] for r in rows}, set(expected_labels))
        for row in rows:
            self.assertEqual(row["label_type"], expected_labels[row["agent"]])
            self.assertNotEqual(row["label_type"], BENCHMARK_FALLBACK_LABEL)
            self.assertIn(row["label_source_status"], {"primary", "fallback"})
            self.assertIsNotNone(row["path_metric_5d"])
            self.assertIsNotNone(row["source_series_id"])


class TestMacroInfluenceDiagnostics(unittest.TestCase):
    def test_partial_role_set_has_no_formal_aggregation_influence(self):
        rows = expand_state_to_macro_signals(
            _state(
                {
                    "central_bank": {
                        **_macro("central_bank", "SUPPORTIVE", 1.0),
                    },
                    "yield_curve": {
                        **_macro("yield_curve", "ADVERSE", 1.0),
                    },
                }
            )
        )
        by = {r["agent"]: r for r in rows}
        self.assertIsNone(by["central_bank"]["influence_weight_equal"])
        self.assertIsNone(by["yield_curve"]["influence_weight_equal"])

    def test_complete_role_set_influence_matches_six_group_aggregation(self):
        outputs = {
            agent: _macro(agent, "SUPPORTIVE", 0.8, strength=(index % 5) + 1)
            for index, agent in enumerate(
                (
                    "china",
                    "us_economy",
                    "central_bank",
                    "dollar",
                    "yield_curve",
                    "commodities",
                    "geopolitical",
                    "volatility",
                    "market_breadth",
                    "institutional_flow",
                )
            )
        }
        outputs["central_bank"] = _macro("central_bank", "ADVERSE", 0.8, strength=4)
        rows = expand_state_to_macro_signals(_state(outputs))
        baseline = aggregate_macro_transmissions(outputs)["score"]
        for row in rows:
            without = {agent: dict(output) for agent, output in outputs.items()}
            without[row["agent"]]["confidence"] = 0.0
            expected = abs(baseline - aggregate_macro_transmissions(without)["score"])
            self.assertAlmostEqual(row["influence_weight_equal"], expected)

    def test_effective_macro_score_is_influence_scaled_diagnostic(self):
        import os
        import tempfile

        d0 = "2024-01-02"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ScorecardStore(db_path=os.path.join(tmp.name, "t.db"))
        outputs = {
            agent: _macro(agent, "SUPPORTIVE", 1.0)
            for agent in (
                "china",
                "us_economy",
                "central_bank",
                "dollar",
                "yield_curve",
                "commodities",
                "geopolitical",
                "volatility",
                "market_breadth",
                "institutional_flow",
            )
        }
        outputs["central_bank"] = _macro("central_bank", "ADVERSE", 1.0)
        store.append_macro_signals_from_state(_state(outputs, date=d0))
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
