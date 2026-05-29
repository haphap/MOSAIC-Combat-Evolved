"""Tests for Phase 3.5C two-stage backtest cache (store + bridge handlers)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401 — registers @methods
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.scorecard import ScorecardStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


@pytest.fixture
def patched_store(tmp_store: ScorecardStore, monkeypatch) -> ScorecardStore:
    """Override _store() in the backtest handler module to point at tmp_store."""
    bt = importlib.import_module("mosaic.bridge.handlers.backtest")
    monkeypatch.setattr(bt, "_store", lambda: tmp_store)
    return tmp_store


def dispatch(method: str, params: dict):
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


SAMPLE_ACTIONS = [
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
]


# ===========================================================================
# Store-level tests
# ===========================================================================


class TestBacktestStore:
    def test_schema_creates_tables(self, tmp_store: ScorecardStore):
        with tmp_store._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "backtest_runs" in tables
        assert "backtest_actions" in tables

    def test_create_run_returns_id(self, tmp_store: ScorecardStore):
        run_id = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc123",
        )
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_create_run_idempotent(self, tmp_store: ScorecardStore):
        kwargs = dict(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc123",
        )
        first = tmp_store.create_backtest_run(**kwargs)
        second = tmp_store.create_backtest_run(**kwargs)
        assert first == second
        with tmp_store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
        assert count == 1

    def test_different_prompt_hash_creates_separate_run(self, tmp_store: ScorecardStore):
        first = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        second = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="def",
        )
        assert first != second

    def test_append_actions(self, tmp_store: ScorecardStore):
        run_id = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc123",
        )
        n = tmp_store.append_backtest_actions(run_id, "2024-02-15", SAMPLE_ACTIONS)
        assert n == 2

        actions = tmp_store.get_backtest_actions(run_id)
        assert len(actions) == 2
        first = next(a for a in actions if a["ticker"] == "688981.SH")
        assert first["action"] == "BUY"
        assert first["target_weight"] == pytest.approx(0.4)

    def test_append_actions_idempotent(self, tmp_store: ScorecardStore):
        run_id = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc123",
        )
        tmp_store.append_backtest_actions(run_id, "2024-02-15", SAMPLE_ACTIONS)
        # Re-append with modified target_weight — should UPDATE, not duplicate
        modified = [{**SAMPLE_ACTIONS[0], "target_weight": 0.5}]
        tmp_store.append_backtest_actions(run_id, "2024-02-15", modified)

        actions = tmp_store.get_backtest_actions(run_id, trade_date="2024-02-15")
        assert len(actions) == 2  # not 3
        first = next(a for a in actions if a["ticker"] == "688981.SH")
        assert first["target_weight"] == pytest.approx(0.5)

    def test_filters_invalid_actions(self, tmp_store: ScorecardStore):
        run_id = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc123",
        )
        bad_actions = [
            {"ticker": "X", "action": "BUY", "target_weight": 0.5},
            {"ticker": "", "action": "BUY", "target_weight": 0.5},  # empty ticker
            {"ticker": "Y", "action": "MAYBE", "target_weight": 0.5},  # invalid action
            {"ticker": "Z", "action": "BUY", "target_weight": "x"},  # non-numeric
        ]
        n = tmp_store.append_backtest_actions(run_id, "2024-02-15", bad_actions)
        assert n == 1  # only the X row survived filtering

    def test_complete_run_sets_completed_at(self, tmp_store: ScorecardStore):
        run_id = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc123",
        )
        run = tmp_store.get_backtest_run(run_id)
        assert run is not None
        assert run["completed_at"] is None

        tmp_store.complete_backtest_run(run_id)
        run2 = tmp_store.get_backtest_run(run_id)
        assert run2 is not None
        assert run2["completed_at"] is not None

    def test_list_runs_filters_cohort(self, tmp_store: ScorecardStore):
        tmp_store.create_backtest_run(
            cohort="cohort_a",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        tmp_store.create_backtest_run(
            cohort="cohort_b",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        runs_a = tmp_store.list_backtest_runs(cohort="cohort_a")
        assert len(runs_a) == 1
        assert runs_a[0]["cohort"] == "cohort_a"


# ===========================================================================
# Bridge handler tests
# ===========================================================================


class TestBacktestHandlers:
    def test_create_run_handler(self, patched_store: ScorecardStore):
        result = dispatch(
            "backtest.create_run",
            {
                "cohort": "cohort_default",
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "prompt_commit_hash": "abc123",
            },
        )
        assert "run_id" in result
        assert isinstance(result["run_id"], int)

    def test_create_run_validates_params(self, patched_store: ScorecardStore):
        with pytest.raises(RpcError):
            dispatch("backtest.create_run", {"cohort": "x"})  # missing other fields

    def test_append_actions_handler(self, patched_store: ScorecardStore):
        run_id = patched_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        result = dispatch(
            "backtest.append_actions",
            {
                "run_id": run_id,
                "trade_date": "2024-02-15",
                "actions": SAMPLE_ACTIONS,
            },
        )
        assert result == {"appended": 2}

    def test_append_actions_invalid_run_id(self, patched_store: ScorecardStore):
        with pytest.raises(RpcError, match="positive integer"):
            dispatch(
                "backtest.append_actions",
                {"run_id": -1, "trade_date": "2024-02-15", "actions": []},
            )

    def test_append_actions_invalid_actions_type(self, patched_store: ScorecardStore):
        run_id = patched_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        with pytest.raises(RpcError, match="must be an array"):
            dispatch(
                "backtest.append_actions",
                {
                    "run_id": run_id,
                    "trade_date": "2024-02-15",
                    "actions": {"not": "an array"},
                },
            )

    def test_complete_run_handler(self, patched_store: ScorecardStore):
        run_id = patched_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        result = dispatch("backtest.complete_run", {"run_id": run_id})
        assert result == {"ok": True}

    def test_get_run_summary(self, patched_store: ScorecardStore):
        run_id = patched_store.create_backtest_run(
            cohort="cohort_default",
            start_date="2024-01-01",
            end_date="2024-03-31",
            prompt_commit_hash="abc",
        )
        patched_store.append_backtest_actions(run_id, "2024-02-15", SAMPLE_ACTIONS)
        patched_store.append_backtest_actions(run_id, "2024-02-22", SAMPLE_ACTIONS)
        result = dispatch("backtest.get_run", {"run_id": run_id})
        assert result["run_id"] == run_id if "run_id" in result else result["id"] == run_id
        assert result["action_count"] == 4
        assert result["distinct_trade_days"] == 2
        assert result["first_trade_date"] == "2024-02-15"
        assert result["last_trade_date"] == "2024-02-22"

    def test_get_run_not_found(self, patched_store: ScorecardStore):
        with pytest.raises(RpcError, match="not found"):
            dispatch("backtest.get_run", {"run_id": 99999})

    def test_list_runs_handler(self, patched_store: ScorecardStore):
        for cohort in ("a", "b"):
            patched_store.create_backtest_run(
                cohort=cohort,
                start_date="2024-01-01",
                end_date="2024-03-31",
                prompt_commit_hash="abc",
            )
        result = dispatch("backtest.list_runs", {})
        assert len(result["runs"]) == 2
        result_a = dispatch("backtest.list_runs", {"cohort": "a"})
        assert len(result_a["runs"]) == 1


def test_all_5_methods_registered():
    from mosaic.bridge.registry import all_methods

    expected = {
        "backtest.create_run",
        "backtest.append_actions",
        "backtest.complete_run",
        "backtest.get_run",
        "backtest.list_runs",
    }
    assert expected.issubset(set(all_methods()))
