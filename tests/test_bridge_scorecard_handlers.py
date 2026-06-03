"""Tests for scorecard.* + darwinian.* JSON-RPC handlers (Plan §11.3 sub-step 3D).

In-process tests that exercise handler logic by calling the registered
@method functions directly. Subprocess-style end-to-end coverage is
provided by ``tests/test_bridge_protocol.py`` separately.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Importing the handlers package wires them via @method decorators.
from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.scorecard import ScorecardStore


def dispatch(method: str, params: dict):
    """Test shim: invoke a registered RPC handler directly."""
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


# ---------------------------------------------------------------------------
# Patch _store() in the handler modules to use a tmp-path SQLite.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path: Path, monkeypatch):
    """Override the lazy _store() factory in both handler modules."""
    db = tmp_path / "scorecard.db"
    store = ScorecardStore(db_path=db)

    def _factory():
        return store

    # Re-import to grab the modules at runtime
    sc = importlib.import_module("mosaic.bridge.handlers.scorecard")
    dw = importlib.import_module("mosaic.bridge.handlers.darwinian")
    monkeypatch.setattr(sc, "_store", _factory)
    monkeypatch.setattr(dw, "_store", _factory)
    return store


def _sample_state(date: str = "2024-06-24") -> dict:
    return {
        "active_cohort": "cohort_default",
        "as_of_date": date,
        "layer1_outputs": {},
        "layer2_outputs": {},
        "layer3_outputs": {
            "ackman": {
                "agent": "ackman",
                "picks": [
                    {
                        "ticker": "600519.SH",
                        "thesis": "moat",
                        "conviction": 0.8,
                        "holding_period": "5Y+",
                    }
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
                        "ticker": "600519.SH",
                        "action": "BUY",
                        "target_weight": 0.4,
                        "holding_period": "5Y+",
                        "dissent_notes": "",
                    },
                ],
                "confidence": 0.55,
            },
        },
    }


# ===========================================================================
# scorecard.append
# ===========================================================================


class TestScorecardAppend:
    def test_happy_path(self, tmp_store):
        result = dispatch("scorecard.append", {"state": _sample_state()})
        # ackman pick + cio action = 2 rows; no layer1 macro outputs in sample
        assert result == {"ingested": 2, "macro_ingested": 0}

    def test_idempotent_re_ingest(self, tmp_store):
        dispatch("scorecard.append", {"state": _sample_state()})
        result = dispatch("scorecard.append", {"state": _sample_state()})
        assert result == {"ingested": 2, "macro_ingested": 0}  # upsert
        with tmp_store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
        assert count == 2  # not 4

    def test_missing_state_object(self, tmp_store):
        with pytest.raises(RpcError) as excinfo:
            dispatch("scorecard.append", {})
        assert excinfo.value.code == -32602  # INVALID_PARAMS
        assert "must be an object" in excinfo.value.message

    def test_missing_as_of_date_in_state(self, tmp_store):
        state = _sample_state()
        del state["as_of_date"]
        with pytest.raises(RpcError) as excinfo:
            dispatch("scorecard.append", {"state": state})
        assert excinfo.value.code == -32602
        assert "as_of_date" in excinfo.value.message


# ===========================================================================
# scorecard.score_pending
# ===========================================================================


class TestScorecardScorePending:
    def test_missing_cohort_param(self, tmp_store):
        with pytest.raises(RpcError) as excinfo:
            dispatch("scorecard.score_pending", {"today": "2024-07-01"})
        assert excinfo.value.code == -32602

    def test_missing_today_param(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch("scorecard.score_pending", {"cohort": "cohort_default"})

    def test_empty_cohort_returns_zero_scored(self, tmp_store):
        result = dispatch(
            "scorecard.score_pending",
            {"cohort": "cohort_default", "today": "2024-07-01"},
        )
        assert result == {
            "scored": 0, "skipped_immature": 0, "skipped_missing": 0,
            "macro_scored": 0, "macro_skipped_immature": 0, "macro_skipped_missing": 0,
        }


# ===========================================================================
# scorecard.list_skill
# ===========================================================================


class TestScorecardListSkill:
    def test_empty_returns_empty_rows(self, tmp_store):
        result = dispatch("scorecard.list_skill", {"cohort": "cohort_default"})
        assert result == {"rows": []}

    def test_aggregates_per_agent(self, tmp_store, monkeypatch):
        # Manually seed scored rows using helpers from weights tests
        from datetime import datetime, timedelta

        store = tmp_store
        base = datetime.strptime("2024-07-31", "%Y-%m-%d").date()

        def _seed(agent: str, alphas: list[float]):
            for i, alpha in enumerate(alphas):
                d = base - timedelta(days=i + 1)
                # Skip weekends to keep dates valid
                while d.weekday() >= 5:
                    d -= timedelta(days=1)
                date_iso = d.isoformat()
                state = {
                    "active_cohort": "cohort_default",
                    "as_of_date": date_iso,
                    "layer1_outputs": {},
                    "layer2_outputs": {},
                    "layer3_outputs": {},
                    "layer4_outputs": {
                        "cro": None,
                        "alpha_discovery": None,
                        "autonomous_execution": None,
                        "cio": {
                            "agent": "cio",
                            "portfolio_actions": [
                                {
                                    "ticker": f"{agent}-{i}.SH",
                                    "action": "BUY",
                                    "target_weight": 0.5,
                                    "holding_period": "6M",
                                    "dissent_notes": "",
                                }
                            ],
                            "confidence": 0.5,
                        },
                    },
                }
                store.append_from_state(state)
                with store._connect() as conn:
                    conn.execute(
                        "UPDATE recommendations SET agent = ? WHERE ticker = ?",
                        (agent, f"{agent}-{i}.SH"),
                    )
                    row_id = conn.execute(
                        "SELECT id FROM recommendations WHERE ticker = ?",
                        (f"{agent}-{i}.SH",),
                    ).fetchone()["id"]
                store.update_scoring(
                    row_id=row_id,
                    forward_return_5d=alpha + 0.01,
                    forward_return_21d=None,
                    alpha_5d=alpha,
                    scored_at="2024-07-31",
                )

        _seed("ackman", [0.01, 0.011, 0.009, 0.012, 0.010, 0.011])
        _seed("druckenmiller", [-0.005, -0.006, -0.004, -0.005, -0.006, -0.005])

        result = dispatch("scorecard.list_skill", {"cohort": "cohort_default"})
        rows = result["rows"]
        assert len(rows) == 2
        agents = {r["agent"]: r for r in rows}

        ackman = agents["ackman"]
        assert ackman["n_obs"] == 6
        assert ackman["mean_alpha_5d"] > 0
        assert ackman["sharpe_window"] > 0

        druck = agents["druckenmiller"]
        assert druck["n_obs"] == 6
        assert druck["mean_alpha_5d"] < 0
        assert druck["sharpe_window"] < 0

    def test_below_min_obs_yields_null_sharpe(self, tmp_store):
        # 4 obs < MIN_OBS = 5 → sharpe NULL
        from datetime import datetime, timedelta

        base = datetime.strptime("2024-07-31", "%Y-%m-%d").date()
        for i in range(4):
            d = base - timedelta(days=i + 1)
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            state = {
                "active_cohort": "cohort_default",
                "as_of_date": d.isoformat(),
                "layer1_outputs": {},
                "layer2_outputs": {},
                "layer3_outputs": {},
                "layer4_outputs": {
                    "cro": None,
                    "alpha_discovery": None,
                    "autonomous_execution": None,
                    "cio": {
                        "agent": "cio",
                        "portfolio_actions": [
                            {
                                "ticker": f"AAA-{i}.SH",
                                "action": "BUY",
                                "target_weight": 0.5,
                                "holding_period": "6M",
                                "dissent_notes": "",
                            }
                        ],
                        "confidence": 0.5,
                    },
                },
            }
            tmp_store.append_from_state(state)
            with tmp_store._connect() as conn:
                row_id = conn.execute(
                    "SELECT id FROM recommendations WHERE ticker = ?",
                    (f"AAA-{i}.SH",),
                ).fetchone()["id"]
            tmp_store.update_scoring(row_id, 0.01, None, 0.01, "2024-07-31")

        result = dispatch("scorecard.list_skill", {"cohort": "cohort_default"})
        cio = next(r for r in result["rows"] if r["agent"] == "cio")
        assert cio["n_obs"] == 4
        assert cio["sharpe_window"] is None

    def test_invalid_since_param(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch(
                "scorecard.list_skill",
                {"cohort": "cohort_default", "since": 12345},
            )


# ===========================================================================
# darwinian.compute
# ===========================================================================


class TestDarwinianCompute:
    def test_empty_store_returns_zero(self, tmp_store):
        result = dispatch(
            "darwinian.compute",
            {"cohort": "cohort_default", "today": "2024-07-31"},
        )
        assert result == {"written": 0, "agents_uniform_fallback": 0}

    def test_missing_cohort_param(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch("darwinian.compute", {"today": "2024-07-31"})

    def test_uses_runtime_config_for_weight_rewrite(self, tmp_store):
        from mosaic.dataflows.config import set_config

        agents = [
            "semiconductor", "energy", "biotech", "consumer",
            "industrials", "financials", "ackman", "cio",
        ]
        for idx, agent in enumerate(agents):
            with tmp_store._connect() as conn:
                conn.execute(
                    "INSERT INTO recommendations("
                    "cohort, agent, ticker, date, action, alpha_5d, scored_at"
                    ") VALUES (?, ?, ?, '2024-07-01', 'BUY', ?, '2024-07-08')",
                    ("cohort_default", agent, f"{agent[:4].upper()}.SH", 0.1 - idx * 0.01),
                )

        set_config(
            {
                "darwinian": {
                    "weight_rewrite_enabled": True,
                    "min_scored_observations_per_agent": 1,
                    "min_ranked_agents_per_scope": 8,
                }
            }
        )
        try:
            result = dispatch(
                "darwinian.compute",
                {"cohort": "cohort_default", "today": "2024-07-31"},
            )
        finally:
            set_config({})

        assert result["written"] == 8
        row = dispatch(
            "darwinian.get_weights",
            {"cohort": "cohort_default", "date": "2024-07-31"},
        )["weights"]["semiconductor"]
        assert row["update_action"] == "up"
        assert row["performance_metric"] == "alpha_5d_mean_30d"
        assert row["weight"] == pytest.approx(1.05)


# ===========================================================================
# darwinian.get_weights
# ===========================================================================


class TestDarwinianGetWeights:
    def test_empty_returns_empty_dict(self, tmp_store):
        result = dispatch("darwinian.get_weights", {"cohort": "cohort_default"})
        assert result == {"weights": {}}

    def test_returns_seeded_weights(self, tmp_store):
        tmp_store.upsert_darwinian_weights(
            [
                {
                    "cohort": "cohort_default",
                    "agent": "ackman",
                    "date": "2024-07-31",
                    "weight": 1.5,
                    "rolling_sharpe_30": 1.0,
                    "rolling_sharpe_90": 0.8,
                    "quartile": 1,
                },
            ]
        )
        result = dispatch(
            "darwinian.get_weights",
            {"cohort": "cohort_default", "date": "2024-07-31"},
        )
        assert "ackman" in result["weights"]
        assert result["weights"]["ackman"]["weight"] == pytest.approx(1.5)
        assert result["weights"]["ackman"]["quartile"] == 1

    def test_returns_unified_weight_metadata(self, tmp_store):
        tmp_store.upsert_darwinian_weights(
            [
                {
                    "cohort": "cohort_default",
                    "agent": "volatility",
                    "layer": "macro",
                    "date": "2024-07-31",
                    "weight": 1.05,
                    "previous_weight": 1.0,
                    "performance_metric": "raw_macro_score_5d",
                    "performance_value": 0.02,
                    "normalized_performance": 0.02,
                    "rank_scope": "macro",
                    "quartile": 1,
                    "update_action": "up",
                    "n_obs": 10,
                    "source_table": "macro_signals",
                    "source_date": "2024-07-24",
                },
            ]
        )
        result = dispatch(
            "darwinian.get_weights",
            {"cohort": "cohort_default", "date": "2024-07-31"},
        )
        row = result["weights"]["volatility"]
        assert row["layer"] == "macro"
        assert row["performance_metric"] == "raw_macro_score_5d"
        assert row["rank_scope"] == "macro"
        assert row["source_table"] == "macro_signals"

    def test_invalid_date_param(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch(
                "darwinian.get_weights",
                {"cohort": "cohort_default", "date": 12345},
            )


# ===========================================================================
# Method registration
# ===========================================================================


def test_all_5_methods_registered():
    from mosaic.bridge.registry import all_methods

    methods = set(all_methods())
    expected = {
        "scorecard.append",
        "scorecard.score_pending",
        "scorecard.list_skill",
        "scorecard.latest_cio_actions",
        "scorecard.win_rate",
        "darwinian.compute",
        "darwinian.get_weights",
    }
    assert expected.issubset(methods)


class TestSignalsRpc:
    def _seed(self, store):
        with store._connect() as conn:
            conn.executemany(
                "INSERT INTO recommendations(cohort,agent,ticker,date,action,"
                "target_weight_pct,forward_return_5d,scored_at) VALUES (?,?,?,?,?,?,?,?)",
                [
                    ("cohort_default", "cio", "510300.SH", "2024-06-25", "BUY", 30.0, None, None),
                    ("cohort_default", "cio", "510300.SH", "2024-06-10", "BUY", 30.0, 0.03, "x"),
                    ("cohort_default", "cio", "512880.SH", "2024-06-10", "SELL", 0.0, -0.04, "x"),
                ],
            )

    def test_latest_cio_actions_rpc(self, tmp_store):
        self._seed(tmp_store)
        out = dispatch("scorecard.latest_cio_actions", {"cohort": "cohort_default"})
        assert out["date"] == "2024-06-25"
        assert out["actions"][0]["ticker"] == "510300.SH"

    def test_win_rate_rpc(self, tmp_store):
        self._seed(tmp_store)
        rows = dispatch("scorecard.win_rate", {"cohort": "cohort_default"})["rows"]
        by = {r["ticker"]: r for r in rows}
        assert by["510300.SH"]["win_rate"] == 1.0
        assert by["512880.SH"]["win_rate"] == 1.0

    def test_latest_cio_actions_requires_cohort(self):
        with pytest.raises(RpcError):
            dispatch("scorecard.latest_cio_actions", {})

    def test_win_rate_rejects_bad_since(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch("scorecard.win_rate", {"cohort": "cohort_default", "since": 123})
