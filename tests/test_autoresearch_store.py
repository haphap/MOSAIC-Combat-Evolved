"""Tests for the Phase 4 autoresearch store layer (Plan §11.5 4A).

Covers prompt_versions + autoresearch_log: the version state machine
(pending → mutation recorded → evaluated → keep/revert), idempotent
trigger, monthly-cap / cooldown counters, the audit log, and the
get_store() singleton (§14 R-T4) + update_scoring no-op warning (§14 R-T5).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from mosaic.scorecard import get_store, reset_store_cache
from mosaic.scorecard.store import ScorecardStore


@pytest.fixture
def store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


def _new_version(store: ScorecardStore, **overrides) -> int:
    kwargs = dict(
        cohort="crisis_2008",
        agent="volatility",
        branch_name="cohort/crisis_2008/auto/volatility/2008-09-15",
        base_commit_hash="a" * 40,
        created_at="2008-09-15T09:00:00+00:00",
    )
    kwargs.update(overrides)
    return store.create_prompt_version(**kwargs)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_tables_created(self, store: ScorecardStore):
        with store._connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            prompt_version_cols = {
                r[1] for r in conn.execute("PRAGMA table_info(prompt_versions)")
            }
        assert "prompt_versions" in tables
        assert "autoresearch_log" in tables
        assert {"prompt_repo_id", "prompt_sha256", "code_commit_hash"}.issubset(
            prompt_version_cols
        )

    def test_reinstantiate_is_idempotent(self, store: ScorecardStore):
        # CREATE TABLE IF NOT EXISTS — second instance must not raise.
        ScorecardStore(db_path=store.db_path)

    def test_old_prompt_versions_table_gets_repo_metadata_columns(self, tmp_path: Path):
        db_path = tmp_path / "old.db"
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE prompt_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cohort TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    base_commit_hash TEXT NOT NULL,
                    modification_commit_hash TEXT,
                    modification_summary TEXT,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decided_at TEXT,
                    pre_sharpe REAL,
                    post_sharpe REAL,
                    delta_sharpe REAL,
                    UNIQUE(branch_name)
                )
                """
            )

        migrated = ScorecardStore(db_path=db_path)
        with migrated._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(prompt_versions)")}
        assert {"prompt_repo_id", "prompt_sha256", "code_commit_hash"}.issubset(cols)


# ---------------------------------------------------------------------------
# prompt_versions lifecycle
# ---------------------------------------------------------------------------


class TestPromptVersionLifecycle:
    def test_create_starts_pending(self, store: ScorecardStore):
        vid = _new_version(store)
        v = store.get_prompt_version(vid)
        assert v["status"] == "pending"
        assert v["modification_commit_hash"] is None
        assert v["delta_sharpe"] is None
        assert v["agent"] == "volatility"
        assert v["code_commit_hash"] == "a" * 40

    def test_create_is_idempotent_on_branch(self, store: ScorecardStore):
        vid1 = _new_version(store)
        vid2 = _new_version(store)  # same branch_name
        assert vid1 == vid2
        assert len(store.list_prompt_versions()) == 1

    def test_record_mutation_fills_commit(self, store: ScorecardStore):
        vid = _new_version(store)
        store.set_version_mutation(
            vid,
            "b" * 40,
            "tighten VIX/iVX ratio rule",
            prompt_repo_id="private",
            prompt_sha256="f" * 64,
            code_commit_hash="c" * 40,
        )
        v = store.get_prompt_version(vid)
        assert v["modification_commit_hash"] == "b" * 40
        assert v["modification_summary"] == "tighten VIX/iVX ratio rule"
        assert v["prompt_repo_id"] == "private"
        assert v["prompt_sha256"] == "f" * 64
        assert v["code_commit_hash"] == "c" * 40
        assert v["status"] == "pending"  # still pending until decided

    def test_set_eval_fills_sharpe(self, store: ScorecardStore):
        vid = _new_version(store)
        store.set_version_eval(vid, pre_sharpe=0.8, post_sharpe=1.05, delta_sharpe=0.25)
        v = store.get_prompt_version(vid)
        assert v["pre_sharpe"] == pytest.approx(0.8)
        assert v["post_sharpe"] == pytest.approx(1.05)
        assert v["delta_sharpe"] == pytest.approx(0.25)

    def test_decide_keep(self, store: ScorecardStore):
        vid = _new_version(store)
        store.decide_version(vid, "keep", decided_at="2008-09-22T17:00:00+00:00")
        v = store.get_prompt_version(vid)
        assert v["status"] == "keep"
        assert v["decided_at"] == "2008-09-22T17:00:00+00:00"

    def test_decide_revert(self, store: ScorecardStore):
        vid = _new_version(store)
        store.decide_version(vid, "revert")
        assert store.get_prompt_version(vid)["status"] == "revert"

    def test_decide_rejects_bad_status(self, store: ScorecardStore):
        vid = _new_version(store)
        with pytest.raises(ValueError, match="keep.*revert"):
            store.decide_version(vid, "maybe")

    def test_mark_incompatible_is_terminal(self, store: ScorecardStore):
        vid = _new_version(store)
        store.mark_version_incompatible(
            vid,
            "unknown_tools=['get_removed_tool']",
            decided_at="2008-09-16T09:00:00+00:00",
        )
        v = store.get_prompt_version(vid)
        assert v["status"] == "incompatible"
        assert v["decided_at"] == "2008-09-16T09:00:00+00:00"
        assert "get_removed_tool" in v["modification_summary"]

    def test_get_version_by_branch(self, store: ScorecardStore):
        vid = _new_version(store)
        v = store.get_version_by_branch(
            "cohort/crisis_2008/auto/volatility/2008-09-15"
        )
        assert v is not None and v["id"] == vid
        assert store.get_version_by_branch("nope") is None

    def test_missing_id_warns_not_raises(self, store: ScorecardStore, caplog):
        with caplog.at_level(logging.WARNING):
            store.set_version_eval(99999, 0.1, 0.2, 0.1)
            store.set_version_mutation(99999, "c" * 40, "x")
        assert any("99999" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Listing / filtering
# ---------------------------------------------------------------------------


class TestListing:
    def test_list_filters(self, store: ScorecardStore):
        _new_version(store, agent="volatility",
                     branch_name="cohort/crisis_2008/auto/volatility/2008-09-15")
        v2 = _new_version(store, agent="cro",
                          branch_name="cohort/crisis_2008/auto/cro/2008-09-15")
        _new_version(store, cohort="euphoria_2021", agent="cro",
                     branch_name="cohort/euphoria_2021/auto/cro/2021-01-10")
        store.decide_version(v2, "keep")

        assert len(store.list_prompt_versions(cohort="crisis_2008")) == 2
        assert len(store.list_prompt_versions(agent="cro")) == 2
        assert len(store.list_prompt_versions(status="keep")) == 1
        assert len(store.list_prompt_versions(cohort="crisis_2008", status="pending")) == 1

    def test_active_branches_are_pending_only(self, store: ScorecardStore):
        v1 = _new_version(store, branch_name="cohort/crisis_2008/auto/volatility/2008-09-15")
        v2 = _new_version(store, agent="cro",
                          branch_name="cohort/crisis_2008/auto/cro/2008-09-15")
        store.decide_version(v2, "revert")
        active = store.list_active_branches("crisis_2008")
        assert len(active) == 1
        assert active[0]["id"] == v1


# ---------------------------------------------------------------------------
# Constraint counters
# ---------------------------------------------------------------------------


class TestCounters:
    def test_last_mutation_at(self, store: ScorecardStore):
        assert store.last_mutation_at("crisis_2008", "volatility") is None
        _new_version(store, created_at="2008-09-15T09:00:00+00:00")
        _new_version(
            store,
            branch_name="cohort/crisis_2008/auto/volatility/2008-09-16",
            created_at="2008-09-16T09:00:00+00:00",
        )
        assert store.last_mutation_at("crisis_2008", "volatility") == "2008-09-16T09:00:00+00:00"

    def test_count_mutations_this_month(self, store: ScorecardStore):
        _new_version(store, branch_name="b1", created_at="2008-09-01T09:00:00+00:00")
        _new_version(store, branch_name="b2", created_at="2008-09-30T09:00:00+00:00")
        _new_version(store, branch_name="b3", created_at="2008-10-01T09:00:00+00:00")
        assert store.count_mutations_this_month("crisis_2008", "2008-09-15T12:00:00+00:00") == 2
        assert store.count_mutations_this_month("crisis_2008", "2008-10-15T12:00:00+00:00") == 1
        assert store.count_mutations_this_month("other", "2008-09-15T12:00:00+00:00") == 0


# ---------------------------------------------------------------------------
# autoresearch_log
# ---------------------------------------------------------------------------


class TestLog:
    def test_append_and_query(self, store: ScorecardStore):
        vid = _new_version(store)
        store.append_log(vid, "triggered", "selected volatility", "2008-09-15T09:00:00+00:00")
        store.append_log(vid, "mutated", "commit bbbb", "2008-09-15T09:05:00+00:00")
        store.append_log(vid, "kept", "delta 0.25", "2008-09-22T17:00:00+00:00")
        log = store.get_log(cohort="crisis_2008")
        assert [e["event"] for e in log] == ["kept", "mutated", "triggered"]  # newest first
        assert log[0]["agent"] == "volatility"  # joined from prompt_versions

    def test_days_window(self, store: ScorecardStore):
        vid = _new_version(store)
        store.append_log(vid, "triggered", None, "2008-09-01T09:00:00+00:00")
        store.append_log(vid, "kept", None, "2008-09-20T09:00:00+00:00")
        recent = store.get_log(days=7, now_iso="2008-09-22T09:00:00+00:00")
        assert [e["event"] for e in recent] == ["kept"]

    def test_cohort_filter(self, store: ScorecardStore):
        v1 = _new_version(store)
        v2 = _new_version(
            store,
            cohort="euphoria_2021",
            branch_name="cohort/euphoria_2021/auto/cro/2021-01-10",
        )
        store.append_log(v1, "triggered", None)
        store.append_log(v2, "triggered", None)
        assert len(store.get_log(cohort="crisis_2008")) == 1
        assert len(store.get_log(cohort="euphoria_2021")) == 1
        assert len(store.get_log()) == 2


# ---------------------------------------------------------------------------
# get_store singleton (§14 R-T4) + update_scoring warning (§14 R-T5)
# ---------------------------------------------------------------------------


class TestStoreSingleton:
    def test_same_path_returns_same_instance(self, tmp_path: Path):
        reset_store_cache()
        db = tmp_path / "s.db"
        a = get_store(db)
        b = get_store(db)
        assert a is b
        reset_store_cache()

    def test_different_path_distinct(self, tmp_path: Path):
        reset_store_cache()
        a = get_store(tmp_path / "a.db")
        b = get_store(tmp_path / "b.db")
        assert a is not b
        reset_store_cache()


class TestUpdateScoringWarning:
    def test_warns_on_missing_row(self, store: ScorecardStore, caplog):
        with caplog.at_level(logging.WARNING):
            store.update_scoring(424242, 0.1, 0.2, 0.05, "2008-09-22")
        assert any("424242" in rec.message for rec in caplog.records)
