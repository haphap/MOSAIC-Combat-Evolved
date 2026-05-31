"""Tests for mosaic.scorecard.store (Plan §11.3 sub-step 3A)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mosaic.scorecard.store import (
    ScorecardStore,
    expand_state_to_recommendations,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_state(date: str = "2024-06-24", cohort: str = "cohort_default") -> dict:
    """A minimal valid daily-cycle final state covering all 4 layers.

    Mirrors the shape produced by ``DailyCycleState`` in mosaic-ts. Layer 1
    is intentionally non-empty but shouldn't yield rows (no tickers).
    """
    return {
        "active_cohort": cohort,
        "as_of_date": date,
        "mode": "live",
        "trace_id": "test",
        "layer1_outputs": {
            "central_bank": {
                "agent": "central_bank",
                "stance": "ACCOMMODATIVE",
                "key_drivers": ["d1"],
                "confidence": 0.7,
            },
        },
        "layer2_outputs": {
            "semiconductor": {
                "agent": "semiconductor",
                "longs": [
                    {"ticker": "688981.SH", "thesis": "国产替代", "conviction": 0.8},
                    {"ticker": "002371.SZ", "thesis": "设备链", "conviction": 0.6},
                ],
                "shorts": [{"ticker": "EXCLUDE.ME", "thesis": "x", "conviction": 0.5}],
                "sector_score": 0.6,
                "key_drivers": ["d"],
                "confidence": 0.5,
            },
            "consumer": {
                "agent": "consumer",
                "longs": [{"ticker": "600519.SH", "thesis": "moat", "conviction": 0.7}],
                "shorts": [],
                "sector_score": 0.4,
                "key_drivers": ["d"],
                "confidence": 0.4,
            },
            "relationship_mapper": {  # different shape — should be skipped
                "agent": "relationship_mapper",
                "supply_chains": [
                    {"name": "semi", "tickers": ["688981.SH"], "risk": "export"}
                ],
                "ownership_clusters": [],
                "contagion_risks": ["x"],
                "key_drivers": ["d"],
                "confidence": 0.4,
            },
        },
        "layer3_outputs": {
            "druckenmiller": {
                "agent": "druckenmiller",
                "picks": [
                    {
                        "ticker": "688981.SH",
                        "thesis": "regime",
                        "conviction": 0.7,
                        "holding_period": "6M",
                    },
                ],
                "philosophy_note": "macro/momentum",
                "key_drivers": ["d"],
                "confidence": 0.6,
            },
            "ackman": {
                "agent": "ackman",
                "picks": [
                    {
                        "ticker": "600519.SH",
                        "thesis": "FCF compounder",
                        "conviction": 0.85,
                        "holding_period": "5Y+",
                    },
                ],
                "philosophy_note": "quality compounder",
                "key_drivers": ["d"],
                "confidence": 0.7,
            },
        },
        "layer4_outputs": {
            "cro": None,
            "alpha_discovery": None,
            "autonomous_execution": None,
            "cio": {
                "agent": "cio",
                "portfolio_actions": [
                    {
                        "ticker": "688981.SH",
                        "action": "BUY",
                        "target_weight": 0.4,
                        "holding_period": "6M",
                        "dissent_notes": "",
                    },
                    {
                        "ticker": "600519.SH",
                        "action": "BUY",
                        "target_weight": 0.3,
                        "holding_period": "5Y+",
                        "dissent_notes": "alpha_discovery surfaced this",
                    },
                ],
                "confidence": 0.55,
            },
        },
        "portfolio_actions": [],
        "llm_calls": [],
    }


@pytest.fixture
def store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


# ---------------------------------------------------------------------------
# expand_state_to_recommendations (pure)
# ---------------------------------------------------------------------------


class TestExpandState:
    def test_l2_longs_become_rows_per_pick(self):
        rows = expand_state_to_recommendations(_sample_state())
        l2_rows = [r for r in rows if r["agent"] in ("semiconductor", "consumer")]
        # semiconductor: 2 longs, consumer: 1 long → 3 rows
        assert len(l2_rows) == 3
        # All actions are LONG (not BUY/SELL)
        assert all(r["action"] == "LONG" for r in l2_rows)
        # target_weight_pct = conviction × 100
        semi_first = next(r for r in l2_rows if r["ticker"] == "688981.SH" and r["agent"] == "semiconductor")
        assert semi_first["target_weight_pct"] == pytest.approx(80.0)

    def test_l2_shorts_excluded(self):
        rows = expand_state_to_recommendations(_sample_state())
        assert not any(r["ticker"] == "EXCLUDE.ME" for r in rows)

    def test_l2_relationship_mapper_excluded(self):
        rows = expand_state_to_recommendations(_sample_state())
        assert not any(r["agent"] == "relationship_mapper" for r in rows)

    def test_l3_picks_become_rows(self):
        rows = expand_state_to_recommendations(_sample_state())
        l3_rows = [r for r in rows if r["agent"] in ("druckenmiller", "ackman")]
        assert len(l3_rows) == 2
        ackman = next(r for r in l3_rows if r["agent"] == "ackman")
        assert ackman["ticker"] == "600519.SH"
        assert ackman["target_weight_pct"] == pytest.approx(85.0)
        assert ackman["rationale_snapshot"] == "FCF compounder"

    def test_l3_falls_back_to_philosophy_when_thesis_empty(self):
        state = _sample_state()
        state["layer3_outputs"]["druckenmiller"]["picks"][0]["thesis"] = ""
        rows = expand_state_to_recommendations(state)
        druck = next(r for r in rows if r["agent"] == "druckenmiller")
        assert druck["rationale_snapshot"] == "macro/momentum"

    def test_l4_cio_actions_become_rows(self):
        rows = expand_state_to_recommendations(_sample_state())
        cio_rows = [r for r in rows if r["agent"] == "cio"]
        assert len(cio_rows) == 2
        first = next(r for r in cio_rows if r["ticker"] == "688981.SH")
        assert first["action"] == "BUY"
        assert first["target_weight_pct"] == pytest.approx(40.0)
        # §14 R-A2: CIO has no per-pick conviction → stored as None (not the
        # target_weight proxy), so it isn't falsely comparable to L2/L3.
        assert first["conviction"] is None
        # dissent_notes empty → rationale_snapshot is None
        assert first["rationale_snapshot"] is None
        second = next(r for r in cio_rows if r["ticker"] == "600519.SH")
        assert second["rationale_snapshot"] == "alpha_discovery surfaced this"

    def test_l1_macro_outputs_not_persisted(self):
        rows = expand_state_to_recommendations(_sample_state())
        assert not any(r["agent"] == "central_bank" for r in rows)

    def test_total_row_count(self):
        # 3 L2 longs + 2 L3 picks + 2 CIO actions = 7 rows
        rows = expand_state_to_recommendations(_sample_state())
        assert len(rows) == 7

    def test_missing_as_of_date_raises(self):
        state = _sample_state()
        state["as_of_date"] = ""
        with pytest.raises(ValueError, match="as_of_date"):
            expand_state_to_recommendations(state)

    def test_truncates_long_rationale(self):
        state = _sample_state()
        state["layer3_outputs"]["druckenmiller"]["picks"][0]["thesis"] = "x" * 500
        rows = expand_state_to_recommendations(state)
        druck = next(r for r in rows if r["agent"] == "druckenmiller")
        assert len(druck["rationale_snapshot"]) == 200
        assert druck["rationale_snapshot"].endswith("…")


# ---------------------------------------------------------------------------
# ScorecardStore — schema + ingest
# ---------------------------------------------------------------------------


class TestScorecardStore:
    def test_init_creates_tables(self, store: ScorecardStore):
        # Re-instantiating must not error (CREATE IF NOT EXISTS).
        ScorecardStore(db_path=store.db_path)
        with store._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "recommendations" in tables
        assert "darwinian_weights" in tables

    def test_append_from_state_writes_expected_rows(self, store: ScorecardStore):
        n = store.append_from_state(_sample_state())
        assert n == 7
        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
        assert count == 7

    def test_unique_constraint_via_upsert(self, store: ScorecardStore):
        # First ingest
        store.append_from_state(_sample_state())
        # Modify a rationale and re-ingest → idempotent, no duplicate rows
        modified = _sample_state()
        modified["layer3_outputs"]["druckenmiller"]["picks"][0]["thesis"] = "updated thesis"
        n = store.append_from_state(modified)
        assert n == 7  # rows still upserted (returns count)
        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
            druck = conn.execute(
                "SELECT rationale_snapshot FROM recommendations "
                "WHERE agent = 'druckenmiller'"
            ).fetchone()
        assert count == 7
        assert druck["rationale_snapshot"] == "updated thesis"

    def test_upsert_does_not_clobber_scoring_columns(self, store: ScorecardStore):
        store.append_from_state(_sample_state())
        # Score one row
        with store._connect() as conn:
            row_id = conn.execute(
                "SELECT id FROM recommendations WHERE agent='cio' AND ticker='688981.SH'"
            ).fetchone()["id"]
        store.update_scoring(
            row_id=row_id,
            forward_return_5d=0.05,
            forward_return_21d=0.10,
            alpha_5d=0.02,
            scored_at="2024-07-01",
        )
        # Re-ingest the same state → scored columns should be preserved
        store.append_from_state(_sample_state())
        with store._connect() as conn:
            row = conn.execute(
                "SELECT forward_return_5d, alpha_5d, scored_at FROM recommendations "
                "WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["forward_return_5d"] == pytest.approx(0.05)
        assert row["alpha_5d"] == pytest.approx(0.02)
        assert row["scored_at"] == "2024-07-01"

    def test_list_pending_filters_scored_and_date(self, store: ScorecardStore):
        store.append_from_state(_sample_state(date="2024-06-24"))
        store.append_from_state(_sample_state(date="2024-06-25"))
        # Score one row from 06-24
        with store._connect() as conn:
            row_id = conn.execute(
                "SELECT id FROM recommendations WHERE date='2024-06-24' "
                "AND agent='semiconductor' LIMIT 1"
            ).fetchone()["id"]
        store.update_scoring(row_id, 0.01, 0.02, 0.005, "2024-07-01")

        pending_all = store.list_pending(cohort="cohort_default")
        # 14 total - 1 scored = 13
        assert len(pending_all) == 13

        pending_old = store.list_pending(
            cohort="cohort_default", before_date="2024-06-24"
        )
        # Only 06-24 rows remain pending; 7 - 1 = 6
        assert len(pending_old) == 6
        assert all(p.date == "2024-06-24" for p in pending_old)

    def test_list_pending_other_cohort_isolation(self, store: ScorecardStore):
        store.append_from_state(_sample_state(cohort="cohort_default"))
        store.append_from_state(_sample_state(cohort="euphoria_2021"))
        a = store.list_pending(cohort="cohort_default")
        b = store.list_pending(cohort="euphoria_2021")
        assert len(a) == 7
        assert len(b) == 7
        assert all(p.cohort == "cohort_default" for p in a)
        assert all(p.cohort == "euphoria_2021" for p in b)

    def test_empty_state_no_rows(self, store: ScorecardStore):
        empty = {
            "active_cohort": "cohort_default",
            "as_of_date": "2024-06-24",
            "layer1_outputs": {},
            "layer2_outputs": {},
            "layer3_outputs": {},
            "layer4_outputs": {
                "cro": None,
                "alpha_discovery": None,
                "autonomous_execution": None,
                "cio": None,
            },
        }
        n = store.append_from_state(empty)
        assert n == 0

    def test_list_scored_excludes_pending(self, store: ScorecardStore):
        store.append_from_state(_sample_state())
        # Score 2 rows
        with store._connect() as conn:
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM recommendations LIMIT 2"
                ).fetchall()
            ]
        for row_id in ids:
            store.update_scoring(row_id, 0.01, 0.02, 0.005, "2024-07-01")
        scored = store.list_scored("cohort_default")
        assert len(scored) == 2
        assert all(r["alpha_5d"] is not None for r in scored)


# ---------------------------------------------------------------------------
# Darwinian weights (Phase 3C will use this)
# ---------------------------------------------------------------------------


class TestDarwinianWeights:
    def test_upsert_and_get(self, store: ScorecardStore):
        store.upsert_darwinian_weights(
            [
                {
                    "cohort": "cohort_default",
                    "agent": "central_bank",
                    "date": "2024-06-24",
                    "weight": 1.5,
                    "rolling_sharpe_30": 1.0,
                    "rolling_sharpe_90": 0.8,
                    "quartile": 1,
                },
                {
                    "cohort": "cohort_default",
                    "agent": "ackman",
                    "date": "2024-06-24",
                    "weight": 0.8,
                    "rolling_sharpe_30": 0.3,
                    "rolling_sharpe_90": 0.4,
                    "quartile": 3,
                },
            ]
        )
        weights = store.get_darwinian_weights("cohort_default", "2024-06-24")
        assert len(weights) == 2
        assert weights["central_bank"]["weight"] == pytest.approx(1.5)
        assert weights["ackman"]["quartile"] == 3

    def test_weight_check_constraint(self, store: ScorecardStore):
        with pytest.raises(Exception):  # noqa: PT011 - sqlite3 IntegrityError
            store.upsert_darwinian_weights(
                [
                    {
                        "cohort": "cohort_default",
                        "agent": "x",
                        "date": "2024-06-24",
                        "weight": 3.0,  # > 2.5 max → CHECK violation
                        "rolling_sharpe_30": None,
                        "rolling_sharpe_90": None,
                        "quartile": None,
                    }
                ]
            )

    def test_get_latest_per_agent_when_date_omitted(self, store: ScorecardStore):
        # Two dates for the same (cohort, agent)
        for dt in ("2024-06-24", "2024-06-25"):
            store.upsert_darwinian_weights(
                [
                    {
                        "cohort": "cohort_default",
                        "agent": "ackman",
                        "date": dt,
                        "weight": 1.0 if dt == "2024-06-24" else 1.5,
                        "rolling_sharpe_30": None,
                        "rolling_sharpe_90": None,
                        "quartile": None,
                    }
                ]
            )
        latest = store.get_darwinian_weights("cohort_default")
        assert latest["ackman"]["weight"] == pytest.approx(1.5)


class TestSignalsAndWinRate:
    """Phase 10: get_latest_cio_actions + compute_win_rate (read-only)."""

    def _insert(self, store: ScorecardStore, rows: list[tuple]) -> None:
        with store._connect() as conn:
            conn.executemany(
                "INSERT INTO recommendations(cohort,agent,ticker,date,action,"
                "target_weight_pct,forward_return_5d,scored_at) VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )

    def test_latest_cio_actions_picks_most_recent_date(self, store: ScorecardStore):
        self._insert(
            store,
            [
                ("cohort_default", "cio", "510300.SH", "2024-06-24", "BUY", 30.0, None, None),
                ("cohort_default", "cio", "512880.SH", "2024-06-25", "BUY", 15.0, None, None),
                ("cohort_default", "cio", "159915.SZ", "2024-06-25", "SELL", 0.0, None, None),
            ],
        )
        out = store.get_latest_cio_actions("cohort_default")
        assert out["date"] == "2024-06-25"
        assert {a["ticker"] for a in out["actions"]} == {"512880.SH", "159915.SZ"}

    def test_latest_cio_actions_empty_when_none(self, store: ScorecardStore):
        out = store.get_latest_cio_actions("cohort_default")
        assert out == {"cohort": "cohort_default", "date": None, "actions": []}

    def test_win_rate_direction_and_hold_exclusion(self, store: ScorecardStore):
        self._insert(
            store,
            [
                # 510300 BUY: one up (win), one down (loss) → 0.5 over n=2
                ("cohort_default", "cio", "510300.SH", "2024-06-01", "BUY", 30.0, 0.03, "x"),
                ("cohort_default", "cio", "510300.SH", "2024-06-02", "BUY", 30.0, -0.02, "x"),
                # 512880 SELL with price down → directional win
                ("cohort_default", "cio", "512880.SH", "2024-06-01", "SELL", 0.0, -0.04, "x"),
                # HOLD excluded (no directional bet)
                ("cohort_default", "cio", "999.SH", "2024-06-01", "HOLD", 0.0, 0.05, "x"),
                # unscored row ignored
                ("cohort_default", "cio", "510300.SH", "2024-06-03", "BUY", 30.0, None, None),
            ],
        )
        rows = store.compute_win_rate("cohort_default")
        by = {r["ticker"]: r for r in rows}
        assert "999.SH" not in by  # HOLD excluded
        assert by["512880.SH"]["win_rate"] == 1.0 and by["512880.SH"]["n"] == 1
        assert by["510300.SH"]["win_rate"] == 0.5 and by["510300.SH"]["n"] == 2
        # sorted by win_rate desc
        assert rows[0]["ticker"] == "512880.SH"
