"""Tests for mosaic.autoresearch.constraints (Plan §11.5 4A)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mosaic.autoresearch.constraints import (
    check_cooldown,
    check_keep_lockout,
    check_monthly_cap,
)
from mosaic.scorecard.store import ScorecardStore

# Small config to make the windows easy to reason about in tests.
CFG = {
    "autoresearch": {
        "agent_mutation_cooldown_hours": 24,
        "keep_revert_lockout_days": 3,
        "monthly_modification_cap_per_cohort": 3,
    }
}


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> ScorecardStore:
    return ScorecardStore(db_path=tmp_path / "scorecard.db")


def _version(store: ScorecardStore, *, agent="volatility", branch, created_at):
    return store.create_prompt_version(
        cohort="crisis_2008",
        agent=agent,
        branch_name=branch,
        base_commit_hash="a" * 40,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_ok_when_no_history(self, store: ScorecardStore):
        res = check_cooldown(store, "crisis_2008", "volatility",
                             _dt("2008-09-15T09:00:00+00:00"), CFG)
        assert res.ok

    def test_blocked_within_window(self, store: ScorecardStore):
        _version(store, branch="b1", created_at="2008-09-15T09:00:00+00:00")
        # 12h later — still inside the 24h cooldown.
        res = check_cooldown(store, "crisis_2008", "volatility",
                             _dt("2008-09-15T21:00:00+00:00"), CFG)
        assert not res.ok
        assert "cooldown" in res.reason

    def test_ok_after_window(self, store: ScorecardStore):
        _version(store, branch="b1", created_at="2008-09-15T09:00:00+00:00")
        res = check_cooldown(store, "crisis_2008", "volatility",
                             _dt("2008-09-16T10:00:00+00:00"), CFG)
        assert res.ok

    def test_per_agent_isolation(self, store: ScorecardStore):
        _version(store, agent="volatility", branch="b1",
                 created_at="2008-09-15T09:00:00+00:00")
        # A different agent is unaffected by volatility's cooldown.
        res = check_cooldown(store, "crisis_2008", "cro",
                             _dt("2008-09-15T10:00:00+00:00"), CFG)
        assert res.ok

    def test_bool_protocol(self, store: ScorecardStore):
        # ConstraintResult is truthy/falsy directly.
        _version(store, branch="b1", created_at="2008-09-15T09:00:00+00:00")
        assert not check_cooldown(store, "crisis_2008", "volatility",
                                  _dt("2008-09-15T10:00:00+00:00"), CFG)


# ---------------------------------------------------------------------------
# monthly cap
# ---------------------------------------------------------------------------


class TestMonthlyCap:
    def test_ok_below_cap(self, store: ScorecardStore):
        _version(store, branch="b1", created_at="2008-09-01T09:00:00+00:00")
        _version(store, branch="b2", created_at="2008-09-05T09:00:00+00:00")
        res = check_monthly_cap(store, "crisis_2008",
                                _dt("2008-09-15T09:00:00+00:00"), CFG)
        assert res.ok

    def test_blocked_at_cap(self, store: ScorecardStore):
        for i in range(3):  # cap is 3
            _version(store, branch=f"b{i}", created_at=f"2008-09-0{i + 1}T09:00:00+00:00")
        res = check_monthly_cap(store, "crisis_2008",
                                _dt("2008-09-15T09:00:00+00:00"), CFG)
        assert not res.ok
        assert "monthly cap" in res.reason

    def test_resets_next_month(self, store: ScorecardStore):
        for i in range(3):
            _version(store, branch=f"b{i}", created_at=f"2008-09-0{i + 1}T09:00:00+00:00")
        # October is a fresh month.
        res = check_monthly_cap(store, "crisis_2008",
                                _dt("2008-10-01T09:00:00+00:00"), CFG)
        assert res.ok


# ---------------------------------------------------------------------------
# keep lockout
# ---------------------------------------------------------------------------


class TestKeepLockout:
    def test_noop_for_non_keep(self, store: ScorecardStore):
        vid = _version(store, branch="b1", created_at="2008-09-15T09:00:00+00:00")
        v = store.get_prompt_version(vid)  # status pending
        res = check_keep_lockout(store, v, _dt("2008-09-15T10:00:00+00:00"), CFG)
        assert res.ok

    def test_blocked_within_lockout(self, store: ScorecardStore):
        vid = _version(store, branch="b1", created_at="2008-09-15T09:00:00+00:00")
        store.decide_version(vid, "keep", decided_at="2008-09-22T17:00:00+00:00")
        v = store.get_prompt_version(vid)
        # 1 day later — inside the 3-day lockout.
        res = check_keep_lockout(store, v, _dt("2008-09-23T17:00:00+00:00"), CFG)
        assert not res.ok
        assert "lockout" in res.reason

    def test_ok_after_lockout(self, store: ScorecardStore):
        vid = _version(store, branch="b1", created_at="2008-09-15T09:00:00+00:00")
        store.decide_version(vid, "keep", decided_at="2008-09-22T17:00:00+00:00")
        v = store.get_prompt_version(vid)
        res = check_keep_lockout(store, v, _dt("2008-09-26T18:00:00+00:00"), CFG)
        assert res.ok

    def test_kept_without_decided_at_allows(self, store: ScorecardStore):
        # Defensive: kept row with no decided_at → allow (don't crash).
        v = {"id": 1, "status": "keep", "decided_at": None}
        res = check_keep_lockout(store, v, _dt("2008-09-23T17:00:00+00:00"), CFG)
        assert res.ok
