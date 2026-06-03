"""Phase 4: layer-aware _select_agent (autoresearch macro plan).

macro ranked within its own layer by mean_raw_macro_score_5d; gated by
min_macro_interval_days; recent-revert penalty; force_agent still honored.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from mosaic.bridge.handlers.autoresearch import _select_agent
from mosaic.bridge.handlers.prompts import _LAYER_BY_AGENT
from mosaic.default_config import DEFAULT_CONFIG
from mosaic.scorecard.store import ScorecardStore

_NOW = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
_COHORT = "cohort_default"


def _store():
    d = tempfile.TemporaryDirectory()
    return ScorecardStore(db_path=os.path.join(d.name, "t.db")), d


def _add_scored_macro(store, agent, raw, date="2024-02-01"):
    store.append_macro_signals_from_state(
        {
            "active_cohort": _COHORT,
            "as_of_date": date,
            "layer1_outputs": {agent: {"agent": agent, "confidence": 0.5}},
            "layer1_consensus": {},
        }
    )
    with store._connect() as conn:
        rid = conn.execute(
            "SELECT id FROM macro_signals WHERE agent=? AND date=?", (agent, date)
        ).fetchone()[0]
    store.update_macro_scoring(rid, {"raw_macro_score_5d": raw, "scored_at": date})


def _add_version(store, agent, created_at, status="pending", decided_at=None):
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO prompt_versions "
            "(cohort, agent, branch_name, base_commit_hash, created_at, status, decided_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (_COHORT, agent, f"b/{agent}/{created_at}", "deadbeef", created_at, status, decided_at),
        )


class TestLayerAwareSelect(unittest.TestCase):
    def test_macro_due_picks_worst_macro(self):
        store, d = _store()
        self.addCleanup(d.cleanup)
        _add_scored_macro(store, "volatility", -0.05)   # worst
        _add_scored_macro(store, "dollar", +0.05)
        chosen = _select_agent(store, _COHORT, None, DEFAULT_CONFIG, _NOW)
        self.assertEqual(chosen, "volatility")

    def test_macro_not_due_picks_nonmacro(self):
        store, d = _store()
        self.addCleanup(d.cleanup)
        _add_scored_macro(store, "volatility", -0.05)
        # a macro mutation 1h ago → macro not due (interval 5d)
        _add_version(store, "volatility", (_NOW - timedelta(hours=1)).isoformat())
        chosen = _select_agent(store, _COHORT, None, DEFAULT_CONFIG, _NOW)
        self.assertNotEqual(_LAYER_BY_AGENT[chosen], "macro")

    def test_no_macro_skill_falls_back_to_nonmacro(self):
        store, d = _store()
        self.addCleanup(d.cleanup)
        chosen = _select_agent(store, _COHORT, None, DEFAULT_CONFIG, _NOW)
        self.assertNotEqual(_LAYER_BY_AGENT[chosen], "macro")

    def test_macro_quota_zero_disables_macro_auto_selection(self):
        store, d = _store()
        self.addCleanup(d.cleanup)
        _add_scored_macro(store, "volatility", -0.05)
        cfg = {
            **DEFAULT_CONFIG,
            "autoresearch": {
                **DEFAULT_CONFIG["autoresearch"],
                "macro_quota": 0,
            },
        }
        chosen = _select_agent(store, _COHORT, None, cfg, _NOW)
        self.assertNotEqual(_LAYER_BY_AGENT[chosen], "macro")

    def test_recent_revert_penalty_skips_agent(self):
        store, d = _store()
        self.addCleanup(d.cleanup)
        _add_scored_macro(store, "volatility", -0.05)   # worst, but penalized
        _add_scored_macro(store, "dollar", -0.01)       # next worst
        # volatility reverted 7d ago: past cooldown + interval, but within penalty window
        _add_version(
            store, "volatility", (_NOW - timedelta(days=7)).isoformat(),
            status="revert", decided_at=(_NOW - timedelta(days=7)).isoformat(),
        )
        chosen = _select_agent(store, _COHORT, None, DEFAULT_CONFIG, _NOW)
        self.assertEqual(chosen, "dollar")

    def test_force_agent_honored(self):
        store, d = _store()
        self.addCleanup(d.cleanup)
        self.assertEqual(
            _select_agent(store, _COHORT, "central_bank", DEFAULT_CONFIG, _NOW), "central_bank"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
