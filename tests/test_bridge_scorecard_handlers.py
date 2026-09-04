"""Tests for scorecard.* + darwinian.* JSON-RPC handlers (Plan §11.3 sub-step 3D).

In-process tests that exercise handler logic by calling the registered
@method functions directly. Subprocess-style end-to-end coverage is
provided by ``tests/test_bridge_protocol.py`` separately.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest

# Importing the handlers package wires them via @method decorators.
from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.scorecard import ScorecardStore
from mosaic.scorecard.darwinian_v2 import canonical_hash


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
        "day_outcome_status": "accepted",
        "agent_run_audits": [
            {
                "agent": f"agent_{index}",
                "stage": "primary",
                "status": "accepted",
            }
            for index in range(26)
        ],
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


def _formal_scorecard_state(
    store: ScorecardStore,
    *,
    trace_id: str,
    as_of_date: str,
) -> dict:
    from mosaic.bridge.tool_capabilities import AGENTS_BY_LAYER, ALL_AGENT_IDS
    from mosaic.scorecard.darwinian_v2 import canonical_hash
    from mosaic.scorecard.store import render_agent_display_narrative_text
    from tests.test_darwinian_v2_accepted_cycle import (
        _accepted_macro_attributions,
        _attach_accepted_records,
        _attach_schedule,
        _reseal_cio_final_record,
        _state,
    )

    state = _state()
    state["trace_id"] = trace_id
    state["as_of_date"] = as_of_date
    state["day_outcome_status"] = "accepted"
    state["portfolio_actions"] = [
        {
            "ticker": "510300.SH",
            "current_weight": 0.2,
            "delta_weight": 0.2,
        }
    ]
    for audit in state["agent_run_audits"]:
        audit["run_id"] = trace_id
    _attach_schedule(store, state)
    _attach_accepted_records(state)

    for record in state["accepted_output_records"]:
        if record["accepted_output_kind"] != "CIO_FINAL":
            continue
        payload = record["output"]["payload"]
        decision = payload["decision"]
        claim_ref = decision["claims"][0]["claim_id"]
        decision.update(
            {
                "decision_disposition": "TARGET_PORTFOLIO",
                "target_positions": [
                    {
                        "position_local_id": "position:510300.SH",
                        "ts_code": "510300.SH",
                        "target_weight": 0.4,
                        "position_decision": "ADD",
                        "holding_period": "MONTHS",
                        "thesis_status": "INTACT",
                        "risk_flags": [],
                        "claim_refs": [claim_ref],
                    }
                ],
                "cash_weight": 0.6,
                "decision_reason": f"accepted {trace_id}",
            }
        )
        payload["accepted_macro_input_attributions"] = _accepted_macro_attributions(
            decision
        )
        _reseal_cio_final_record(state, record)

    layer_by_agent = {
        agent: layer
        for layer, agents in AGENTS_BY_LAYER.items()
        for agent in agents
    }
    records_by_id = {
        record["accepted_output_id"]: record
        for record in state["accepted_output_records"]
    }
    narratives = []
    for agent in ALL_AGENT_IDS:
        ref = state["accepted_output_refs"].get(f"CIO_FINAL:{agent}")
        if ref is None:
            ref = next(
                item
                for item in state["accepted_output_refs"].values()
                if item["agent_id"] == agent
                and item["accepted_output_kind"] != "CIO_PROPOSAL"
            )
        record = records_by_id[ref["accepted_output_id"]]
        body = {
            "schema_version": "agent_display_narrative_v1",
            "agent_id": agent,
            "layer": layer_by_agent[agent],
            "language": "zh",
            "source": "ACCEPTED_OUTPUT",
            "source_output_id": ref["accepted_output_id"],
            "source_output_hash": ref["accepted_output_hash"],
            "narrative_text": render_agent_display_narrative_text(
                layer=layer_by_agent[agent],
                agent_id=agent,
                output=record["output"]["payload"],
                language="zh",
                accepted_output_kind=record["accepted_output_kind"],
            ),
            "ui_only": True,
        }
        narratives.append(
            {
                **body,
                "narrative_id": (
                    "agent-display:"
                    + canonical_hash(body).removeprefix("sha256:")
                ),
            }
        )
    bundle_body = {
        "schema_version": "agent_display_narrative_bundle_v1",
        "trace_id": trace_id,
        "cohort": "cohort_default",
        "as_of_date": as_of_date,
        "language": "zh",
        "narrative_count": len(narratives),
        "narratives": narratives,
    }
    state["agent_display_narratives"] = {
        **bundle_body,
        "bundle_hash": canonical_hash(bundle_body),
    }
    return state


# ===========================================================================
# scorecard.append
# ===========================================================================


class TestScorecardAppend:
    def test_happy_path(self, tmp_store):
        result = dispatch("scorecard.append", {"state": _sample_state()})
        # ackman pick + cio action = 2 rows; no layer1 macro outputs in sample
        assert result == {"ingested": 2, "macro_ingested": 0}

    def test_live_enforce_requires_committed_cycle_publication(
        self, tmp_store, monkeypatch
    ):
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
        state = {**_sample_state(), "mode": "live", "trace_id": "daily-run-1"}

        with pytest.raises(RpcError, match="agent_cycle_publication_hash"):
            dispatch("scorecard.append", {"state": state})

        with tmp_store._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0

    def test_live_enforce_validates_publication_before_writing(
        self, tmp_store, monkeypatch
    ):
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
        authority = importlib.import_module("mosaic.dataflows.agent_cycle_authority")
        materialization = importlib.import_module("mosaic.dataflows.agent_materialization")
        ledger = object()
        calls = []
        monkeypatch.setattr(
            materialization,
            "open_agent_data_materialization_ledger",
            lambda *, create: ledger,
        )
        monkeypatch.setattr(
            authority,
            "require_committed_agent_cycle",
            lambda **kwargs: calls.append(kwargs),
        )
        state = {
            **_sample_state(),
            "mode": "live",
            "trace_id": "daily-run-1",
            "agent_cycle_publication_hash": "sha256:" + "1" * 64,
        }

        result = dispatch("scorecard.append", {"state": state})

        assert result == {"ingested": 2, "macro_ingested": 0}
        assert calls == [
            {
                "ledger": ledger,
                "state": state,
                "publication_hash": "sha256:" + "1" * 64,
            }
        ]

    def test_live_shadow_requires_and_validates_isolated_cycle_publication(
        self, tmp_store, tmp_path, monkeypatch
    ):
        shadow_root = tmp_path / "shadow"
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "shadow")
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT", str(shadow_root))
        state = {**_sample_state(), "mode": "live", "trace_id": "shadow-run-1"}

        with pytest.raises(RpcError, match="agent_cycle_publication_hash"):
            dispatch("scorecard.append", {"state": state})

        authority = importlib.import_module("mosaic.dataflows.agent_cycle_authority")
        materialization = importlib.import_module("mosaic.dataflows.agent_materialization")
        opened_paths = []
        ledger = object()

        def open_ledger(*, create):
            assert create is False
            opened_paths.append(materialization.agent_data_materialization_db_path())
            return ledger

        calls = []
        monkeypatch.setattr(
            materialization, "open_agent_data_materialization_ledger", open_ledger
        )
        monkeypatch.setattr(
            authority,
            "require_committed_agent_cycle",
            lambda **kwargs: calls.append(kwargs),
        )
        accepted = {
            **state,
            "agent_cycle_publication_hash": "sha256:" + "3" * 64,
        }

        assert dispatch("scorecard.append", {"state": accepted}) == {
            "ingested": 2,
            "macro_ingested": 0,
        }
        assert opened_paths == [
            shadow_root / "agent_materialization" / "materialization.sqlite3"
        ]
        assert calls == [
            {
                "ledger": ledger,
                "state": accepted,
                "publication_hash": "sha256:" + "3" * 64,
            }
        ]

    def test_shadow_store_resolves_below_the_isolated_runtime_root(
        self, tmp_path, monkeypatch
    ):
        shadow_root = tmp_path / "shadow"
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "shadow")
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT", str(shadow_root))
        scorecard = importlib.import_module("mosaic.bridge.handlers.scorecard")
        darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")
        package = importlib.import_module("mosaic.scorecard")
        package.reset_store_cache()
        try:
            expected_path = shadow_root / "scorecard" / "scorecard.db"
            store = package.get_store()
            assert store.db_path == expected_path
            assert store.db_path != package.DEFAULT_DB_PATH
            assert scorecard._store().db_path == expected_path
            assert darwinian._store().db_path == expected_path
            monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
            production_store = package.get_store()
            assert production_store.db_path == package.DEFAULT_DB_PATH
            assert production_store is not store
        finally:
            package.reset_store_cache()

    def test_live_normal_does_not_require_cycle_publication(
        self, tmp_store, monkeypatch
    ):
        monkeypatch.delenv("MOSAIC_ENSURE_SNAPSHOT_MODE", raising=False)
        state = {**_sample_state(), "mode": "live", "trace_id": "daily-run-1"}

        assert dispatch("scorecard.append", {"state": state}) == {
            "ingested": 2,
            "macro_ingested": 0,
        }

    def test_live_off_mode_is_invalid(self, tmp_store, monkeypatch):
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "off")
        state = {**_sample_state(), "mode": "live", "trace_id": "off-run"}

        with pytest.raises(RpcError, match="must be shadow or enforce when set"):
            dispatch("scorecard.append", {"state": state})

        with tmp_store._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0

    def test_idempotent_re_ingest(self, tmp_store):
        dispatch("scorecard.append", {"state": _sample_state()})
        result = dispatch("scorecard.append", {"state": _sample_state()})
        assert result == {"ingested": 2, "macro_ingested": 0}  # upsert
        with tmp_store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
        assert count == 2  # not 4

    def test_ui_narratives_are_stripped_from_evaluation_writers(
        self, tmp_store, monkeypatch
    ):
        state = _sample_state()
        state["trace_id"] = "trace-1"
        state["agent_display_narratives"] = {"ui_only": True}
        evaluation_states = []
        narrative_states = []

        monkeypatch.setattr(
            tmp_store,
            "append_from_state",
            lambda payload, **_kwargs: evaluation_states.append(payload) or 2,
        )
        monkeypatch.setattr(
            tmp_store,
            "append_macro_signals_from_state",
            lambda payload, **_kwargs: evaluation_states.append(payload) or 0,
        )
        monkeypatch.setattr(
            tmp_store,
            "append_agent_display_narratives_from_state",
            lambda payload, **_kwargs: narrative_states.append(payload) or 25,
        )

        result = dispatch("scorecard.append", {"state": state})
        assert result["agent_narratives_ingested"] == 25
        assert all(
            "agent_display_narratives" not in payload
            for payload in evaluation_states
        )
        assert narrative_states[0]["agent_display_narratives"] == {"ui_only": True}

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

    def test_rejects_missing_agent_stage_audits(self, tmp_store):
        state = _sample_state()
        state.pop("agent_run_audits")
        with pytest.raises(RpcError) as excinfo:
            dispatch("scorecard.append", {"state": state})
        assert excinfo.value.code == -32602
        assert "26 unique accepted" in excinfo.value.message

    def test_backtest_requires_matching_accepted_day(self, tmp_store):
        state = _sample_state()
        run_id = tmp_store.create_backtest_run(
            cohort="cohort_default",
            start_date=state["as_of_date"],
            end_date=state["as_of_date"],
            prompt_commit_hash="strict-contract-test",
        )
        state.update(
            mode="backtest",
            backtest_run_id=run_id,
            decision_disposition="TARGET_PORTFOLIO",
        )
        with pytest.raises(RpcError) as excinfo:
            dispatch("scorecard.append", {"state": state})
        assert "matching accepted backtest day" in excinfo.value.message

        actions = state["layer4_outputs"]["cio"]["portfolio_actions"]
        tmp_store.append_backtest_actions(
            run_id,
            state["as_of_date"],
            actions,
            agent_run_audits=state["agent_run_audits"],
            decision_disposition="TARGET_PORTFOLIO",
        )
        assert dispatch("scorecard.append", {"state": state})["ingested"] == 2

    def test_formal_append_is_atomic_idempotent_and_latest_is_sealed(
        self,
        tmp_store,
        monkeypatch,
    ):
        accepted = _formal_scorecard_state(
            tmp_store,
            trace_id="graph-run-atomic-accepted",
            as_of_date="2026-07-17",
        )
        missing_narratives = dict(accepted)
        missing_narratives.pop("agent_display_narratives")
        with pytest.raises(RpcError, match="requires agent_display_narratives"):
            dispatch("scorecard.append", {"state": missing_narratives})
        with tmp_store._connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM accepted_agent_outputs_v2"
            ).fetchone()[0] == 0
        result = dispatch("scorecard.append", {"state": accepted})
        assert result["ingested"] >= 1
        assert result["macro_ingested"] == 8
        assert result["agent_narratives_ingested"] == 25
        retry = dispatch("scorecard.append", {"state": accepted})
        assert retry["ingested"] == result["ingested"]
        assert retry["macro_ingested"] == result["macro_ingested"]
        assert retry["agent_narratives_ingested"] == result[
            "agent_narratives_ingested"
        ]

        latest_cio = dispatch(
            "scorecard.latest_cio_actions",
            {"cohort": "cohort_default"},
        )
        assert latest_cio["date"] == "2026-07-17"
        latest_action = latest_cio["actions"][0]
        assert latest_action["ticker"] == "510300.SH"
        assert latest_action["current_weight_pct"] == pytest.approx(20.0)
        assert latest_action["delta_weight_pct"] == pytest.approx(20.0)
        assert latest_action["position_decision"] == "ADD"
        assert latest_action["position_decision_reason"] == (
            "accepted graph-run-atomic-accepted"
        )
        assert latest_action["thesis_status"] == "INTACT"
        assert latest_action["risk_flags_json"] == "[]"
        latest_narratives = dispatch(
            "scorecard.latest_agent_narratives",
            {"cohort": "cohort_default"},
        )
        assert latest_narratives["trace_id"] == "graph-run-atomic-accepted"

        with pytest.raises(RpcError, match="recommendations are sealed"):
            dispatch(
                "scorecard.append",
                {"state": _sample_state(date="2026-07-17")},
            )
        with pytest.raises(sqlite3.IntegrityError, match="recommendations are sealed"):
            with tmp_store._connect() as conn:
                conn.execute(
                    "UPDATE recommendations SET graph_run_id = ? "
                    "WHERE graph_run_id = ?",
                    ("graph-run-same-day-conflict", accepted["trace_id"]),
                )
        with pytest.raises(sqlite3.IntegrityError, match="macro signals are sealed"):
            with tmp_store._connect() as conn:
                conn.execute(
                    "UPDATE macro_signals SET graph_run_id = ? "
                    "WHERE graph_run_id = ?",
                    ("graph-run-same-day-conflict", accepted["trace_id"]),
                )
        with pytest.raises(sqlite3.IntegrityError, match="narratives are sealed"):
            with tmp_store._connect() as conn:
                conn.execute(
                    "INSERT INTO agent_display_narratives ("
                    "cohort, date, trace_id, bundle_hash, agent, layer, language, "
                    "source, source_output_id, source_output_hash, narrative_id, "
                    "narrative_text, ui_only, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (
                        "cohort_default",
                        "2026-07-17",
                        "graph-run-same-day-conflict",
                        f"sha256:{'1' * 64}",
                        "china",
                        "macro",
                        "zh",
                        "NO_EVALUATION_OBJECT",
                        None,
                        f"sha256:{'2' * 64}",
                        "agent-display:conflict",
                        "conflict",
                        "2026-07-17T09:00:00+08:00",
                    ),
                )
        with tmp_store._connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM recommendations "
                "WHERE graph_run_id = ?",
                ("graph-run-same-day-conflict",),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM recommendations "
                "WHERE cohort = ? AND date = ? AND ticker = ?",
                ("cohort_default", "2026-07-17", "600519.SH"),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM macro_signals "
                "WHERE graph_run_id = ?",
                ("graph-run-same-day-conflict",),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM agent_display_narratives "
                "WHERE trace_id = ?",
                ("graph-run-same-day-conflict",),
            ).fetchone()[0] == 0

        rejected = _formal_scorecard_state(
            tmp_store,
            trace_id="graph-run-atomic-rejected",
            as_of_date="2026-07-20",
        )
        darwinian = importlib.import_module("mosaic.scorecard.darwinian_v2")
        original_append = darwinian.append_accepted_cycle

        def fail_after_darwin_writes(conn, *, state):
            original_append(conn, state=state)
            assert conn.execute(
                "SELECT COUNT(*) FROM accepted_agent_outputs_v2 "
                "WHERE graph_run_id = ?",
                (state["trace_id"],),
            ).fetchone()[0] == 26
            raise ValueError("injected post-Darwin validation failure")

        monkeypatch.setattr(
            darwinian,
            "append_accepted_cycle",
            fail_after_darwin_writes,
        )
        with pytest.raises(RpcError, match="injected post-Darwin"):
            dispatch("scorecard.append", {"state": rejected})

        with tmp_store._connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM recommendations WHERE graph_run_id = ?",
                (rejected["trace_id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM macro_signals WHERE graph_run_id = ?",
                (rejected["trace_id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM agent_display_narratives WHERE trace_id = ?",
                (rejected["trace_id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM accepted_agent_outputs_v2 "
                "WHERE graph_run_id = ?",
                (rejected["trace_id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM operational_opportunity_audits_v2 "
                "WHERE graph_run_id = ?",
                (rejected["trace_id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM scorecard_accepted_runs "
                "WHERE graph_run_id = ?",
                (rejected["trace_id"],),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(*) FROM scorecard_accepted_runs"
            ).fetchone()[0] == 1

        assert dispatch(
            "scorecard.latest_cio_actions",
            {"cohort": "cohort_default"},
        )["date"] == "2026-07-17"
        assert dispatch(
            "scorecard.latest_agent_narratives",
            {"cohort": "cohort_default"},
        )["trace_id"] == "graph-run-atomic-accepted"


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

    def test_runtime_macro_full_label_gate_is_passed_to_scorer(self, tmp_store, monkeypatch):
        from datetime import date, timedelta
        from unittest.mock import patch

        d0 = "2024-01-02"
        t5 = (date.fromisoformat(d0) + timedelta(days=5)).isoformat()
        tmp_store.append_macro_signals_from_state(
            {
                "active_cohort": "cohort_default",
                "as_of_date": d0,
                "day_outcome_status": "accepted",
                "layer1_outputs": {
                    "us_financial_conditions": {
                        "agent": "us_financial_conditions",
                        "direction": "SUPPORTIVE",
                        "strength": 5,
                        "confidence": 0.6,
                    }
                },
                "legacy_layer1_consensus": {"stance": "BULLISH", "confidence": 0.6},
            }
        )

        sc = importlib.import_module("mosaic.bridge.handlers.scorecard")
        monkeypatch.setattr(
            sc,
            "_config",
            lambda: {
                "autoresearch": {
                    "macro_agent_specific_labels_enabled": True,
                    "macro_full_label_sources_enabled": True,
                    "macro_neutral_band": 0.005,
                }
            },
        )
        with patch.multiple(
            "mosaic.dataflows.calendar",
            next_trading_day=lambda d, n: (date.fromisoformat(d) + timedelta(days=n)).isoformat(),
            previous_trading_day=lambda d, n: (date.fromisoformat(d) - timedelta(days=n)).isoformat(),
        ), patch(
            "mosaic.scorecard.scorer._fetch_close",
            lambda ts, day: {d0: 100.0, t5: 102.0}.get(day),
        ), patch(
            "mosaic.scorecard.scorer._fetch_benchmark_series",
            lambda *a: [100.0, 101.0, 102.0],
        ), patch(
            "mosaic.scorecard.scorer._fetch_instrument_series",
            lambda *a: [7.2, 7.1, 7.0],
        ):
            result = dispatch(
                "scorecard.score_pending",
                {"cohort": "cohort_default", "today": "2024-02-01"},
            )

        assert result["macro_scored"] == 1
        with tmp_store._connect() as conn:
            row = conn.execute("SELECT label_type FROM macro_signals").fetchone()
        assert row["label_type"] == "us_financial_conditions_a_share_path_5d"


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
                    "day_outcome_status": "accepted",
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
                "day_outcome_status": "accepted",
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
# darwinian.prepare_daily_cycle_outcomes
# ===========================================================================


class TestDarwinianPrepareDailyCycleOutcomes:
    def test_missing_event_coverage_uses_cold_start_before_first_accepted_cycle(
        self, monkeypatch
    ):
        calendar_module = importlib.import_module("mosaic.dataflows.calendar")
        inputs_module = importlib.import_module(
            "mosaic.dataflows.outcome_runtime_inputs"
        )
        darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")
        cold_start_coverage = {"china": {"candidates": []}}
        observed = {}

        class Store:
            def has_accepted_darwinian_cycle(self, **_kwargs):
                return False

            def prepare_outcome_schedule_plan(self, **kwargs):
                observed.update(kwargs)
                return {
                    "outcome_schedule_plan_id": "plan-1",
                    "outcome_schedule_plan_hash": "sha256:" + "1" * 64,
                    "event_candidate_input_hash": "sha256:" + "2" * 64,
                }

        monkeypatch.setattr(darwinian, "_store", Store)
        monkeypatch.setattr(
            calendar_module,
            "verified_trading_calendar_snapshot",
            lambda *_args, **_kwargs: {"snapshot_hash": "sha256:" + "3" * 64},
        )
        monkeypatch.setattr(
            inputs_module,
            "load_verified_event_coverage",
            lambda _as_of: (_ for _ in ()).throw(FileNotFoundError("unavailable")),
        )
        monkeypatch.setattr(
            inputs_module,
            "build_cold_start_event_coverage",
            lambda: cold_start_coverage,
        )

        result = dispatch(
            "darwinian.prepare_daily_cycle_outcomes",
            {
                "production_variant_roster_revision_id": "revision-1",
                "graph_run_id": "run-1",
                "as_of": "2025-06-16T15:00:00+08:00",
                "prepared_at": "2025-06-16T15:00:00+08:00",
            },
        )

        assert observed["verified_event_candidates"] is cold_start_coverage
        assert result["event_candidate_input_hash"] == "sha256:" + "2" * 64

    def test_missing_event_coverage_still_fails_after_an_accepted_cycle(
        self, monkeypatch
    ):
        calendar_module = importlib.import_module("mosaic.dataflows.calendar")
        inputs_module = importlib.import_module(
            "mosaic.dataflows.outcome_runtime_inputs"
        )
        darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")

        class Store:
            def has_accepted_darwinian_cycle(self, **_kwargs):
                return True

        monkeypatch.setattr(darwinian, "_store", Store)
        monkeypatch.setattr(
            calendar_module,
            "verified_trading_calendar_snapshot",
            lambda *_args, **_kwargs: {"snapshot_hash": "sha256:" + "3" * 64},
        )
        monkeypatch.setattr(
            inputs_module,
            "load_verified_event_coverage",
            lambda _as_of: (_ for _ in ()).throw(FileNotFoundError("unavailable")),
        )

        with pytest.raises(RpcError, match="unavailable"):
            dispatch(
                "darwinian.prepare_daily_cycle_outcomes",
                {
                    "production_variant_roster_revision_id": "revision-1",
                    "graph_run_id": "run-1",
                    "as_of": "2025-06-16T15:00:00+08:00",
                    "prepared_at": "2025-06-16T15:00:00+08:00",
                },
            )


# ===========================================================================
# darwinian.freeze_outcome_opportunity
# ===========================================================================


def test_missing_l1_l2_projection_uses_runtime_authority(monkeypatch):
    inputs = importlib.import_module("mosaic.dataflows.outcome_runtime_inputs")
    preparer = importlib.import_module("mosaic.dataflows.agent_stage_preparer")
    authority_module = importlib.import_module(
        "mosaic.scorecard.opportunity_authority"
    )
    darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")
    from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS

    domain_hash = "sha256:" + "4" * 64
    member_refs = [{"path_snapshot_id": "macro-path-snapshot:us-financial"}]
    authority = {
        "member_refs": member_refs,
        "runtime_authority_binding": {
            "source_tool_id": "get_us_financial_conditions_snapshot",
            "source_snapshot_hash": "sha256:" + "5" * 64,
            "domain_hash": domain_hash,
        },
    }
    observed = {}
    call_order = []

    class Store:
        def resolve_scheduled_sample_context(self, **_kwargs):
            return {
                "agent_id": "us_financial_conditions",
                "outcome_schedule_plan_id": "plan-1",
                "as_of": "2025-06-17T15:00:00+08:00",
                "graph_run_id": "graph-1",
            }

        def freeze_scheduled_outcome_opportunity(self, **kwargs):
            observed.update(kwargs)
            return {"run_allowed": True}

    monkeypatch.setattr(darwinian, "_store", Store)
    monkeypatch.setattr(
        inputs,
        "load_evaluation_opportunity_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        authority_module,
        "materialize_pre_run_authority",
        lambda **kwargs: call_order.append(("authority", kwargs)) or authority,
    )
    monkeypatch.setattr(
        preparer,
        "ensure_agent_stage_materialization",
        lambda request: call_order.append(("prepare", request))
        or {
            "historical_replay_captured_at": "2026-08-31T01:40:11+08:00"
        },
    )

    result = dispatch(
        "darwinian.freeze_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "us_financial_conditions",
        },
    )

    assert result["run_allowed"] is True
    assert call_order == [
        (
            "prepare",
            {
                "agent_id": "us_financial_conditions",
                "stage": "us_financial_conditions",
                "as_of": "2025-06-17",
            },
        ),
        (
            "authority",
            {
                "agent_id": "us_financial_conditions",
                "as_of": "2025-06-17T15:00:00+08:00",
                "graph_run_id": "graph-1",
                "schedule_slot": {
                    "agent_id": "us_financial_conditions",
                    "outcome_schedule_plan_id": "plan-1",
                    "as_of": "2025-06-17T15:00:00+08:00",
                    "graph_run_id": "graph-1",
                },
                "historical_replay_captured_at": (
                    "2026-08-31T01:40:11+08:00"
                ),
            },
        ),
    ]
    assert observed["member_refs"] == member_refs
    assert observed["runtime_authority_binding"] == authority[
        "runtime_authority_binding"
    ]
    assert set(observed["source_evidence_by_required_source_id"]) == set(
        OUTCOME_CONTRACTS["us_financial_conditions"]["required_source_ids"]
    )
    assert all(
        evidence[0].startswith("runtime-authority:us_financial_conditions:")
        and evidence[0].endswith(domain_hash[7:])
        for evidence in observed["source_evidence_by_required_source_id"].values()
    )


# ===========================================================================
# darwinian.freeze_superinvestor_outcome_opportunity
# ===========================================================================


def test_missing_superinvestor_projection_uses_runtime_authority(monkeypatch):
    preparer = importlib.import_module("mosaic.dataflows.agent_stage_preparer")
    inputs = importlib.import_module("mosaic.dataflows.outcome_runtime_inputs")
    capabilities = importlib.import_module("mosaic.bridge.tool_capabilities")
    darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")
    from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS

    member_refs = [{"candidate_ref": "candidate:000333", "ts_code": "000333.SZ"}]
    snapshot = {
        "snapshot_hash": "sha256:" + "6" * 64,
        "candidate_universe": member_refs,
        "candidate_scope_hash": "sha256:" + "7" * 64,
        "candidate_universe_id": "candidate-universe:druckenmiller",
        "candidate_universe_hash": "sha256:" + "8" * 64,
    }
    authority_hash = canonical_hash(
        {
            "contract_version": "evaluation_opportunity_source_authority_v1",
            "agent_id": "druckenmiller",
            "tool_id": "get_superinvestor_candidate_snapshot",
            "source_snapshot_hash": snapshot["snapshot_hash"],
            "candidate_scope_hash": snapshot["candidate_scope_hash"],
            "candidate_universe_id": snapshot["candidate_universe_id"],
            "candidate_universe_hash": snapshot["candidate_universe_hash"],
            "member_refs": member_refs,
        }
    )
    observed = {}
    materialized = {}
    preparation_requests = []

    class Store:
        def resolve_scheduled_sample_context(self, **_kwargs):
            return {
                "agent_id": "druckenmiller",
                "outcome_schedule_plan_id": "plan-1",
                "as_of": "2025-06-17T15:00:00+08:00",
                "graph_run_id": "graph-1",
                "prepared_at": "2025-06-17T15:00:00+08:00",
            }

        def freeze_scheduled_outcome_opportunity(self, **kwargs):
            observed.update(kwargs)
            return {"run_allowed": True}

    monkeypatch.setattr(darwinian, "_store", Store)
    monkeypatch.setattr(
        inputs,
        "load_evaluation_opportunity_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        preparer,
        "ensure_agent_stage_materialization",
        lambda request: preparation_requests.append(request) or {"status": "READY"},
    )
    def materialize(*_args, **kwargs):
        materialized.update(kwargs)
        return json.dumps(snapshot)

    monkeypatch.setattr(capabilities, "materialize_tool_payload", materialize)

    result = dispatch(
        "darwinian.freeze_superinvestor_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "druckenmiller",
            "recorded_at": "2025-06-17T15:00:00+08:00",
            "accepted_output_refs": [{"agent_id": "semiconductor"}],
            "runtime_inputs": {
                "accepted_output_refs": [{"agent_id": "semiconductor"}],
                "accepted_output_records": [],
                "bound_runtime_state": {"current_positions": {}},
            },
        },
    )

    assert result["run_allowed"] is True
    assert materialized["expected_runtime_input_hash"] == canonical_hash(
        preparation_requests[0]["runtime_inputs"]
    )
    assert preparation_requests == [
        {
            "agent_id": "druckenmiller",
            "stage": "druckenmiller",
            "as_of": "2025-06-17",
            "graph_run_id": "graph-1",
            "runtime_inputs": {
                "accepted_output_refs": [{"agent_id": "semiconductor"}],
                "accepted_output_records": [],
                "bound_runtime_state": {"current_positions": {}},
            },
            "candidate_scope": {
                "accepted_output_refs": [{"agent_id": "semiconductor"}],
            },
        }
    ]
    assert observed["member_refs"] == member_refs
    assert set(observed["source_evidence_by_required_source_id"]) == set(
        OUTCOME_CONTRACTS["druckenmiller"]["required_source_ids"]
    )
    assert all(
        evidence[0].startswith("runtime-authority:druckenmiller:")
        and evidence[0].endswith(authority_hash[7:])
        for evidence in observed["source_evidence_by_required_source_id"].values()
    )


# ===========================================================================
# darwinian.freeze_stage_outcome_opportunity
# ===========================================================================


def test_cio_frozen_baseline_uses_cross_runtime_left_fold():
    darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    candidates = [
        {
            "proposal_position_ref": f"position-{index}",
            "ts_code": f"60000{index}.SH",
            "current_weight": weight,
            "proposed_target_weight": weight,
        }
        for index, weight in enumerate((0.1, 0.2, 0.3), start=1)
    ]
    authority = {
        "agent_id": "cio",
        "stage": "cio_final",
        "snapshot_id": "runtime-snapshot:cio",
        "snapshot_hash": "sha256:" + "1" * 64,
        "candidate_scope_hash": "sha256:" + "2" * 64,
        "candidate_universe_id": "candidate-universe:cio",
        "candidate_universe_hash": canonical_hash(
            {"candidate_status": "AVAILABLE", "candidate_universe": candidates}
        ),
        "candidate_status": "AVAILABLE",
        "candidate_universe": candidates,
        "upstream_accepted_output_refs": [],
    }
    payload, _members = darwinian._expected_decision_frozen_object("cio", authority)
    left_fold = 0.0
    for row in candidates:
        left_fold += row["current_weight"]

    assert left_fold != sum(row["current_weight"] for row in candidates)
    assert payload["portfolio_context"]["baseline_cash_weight"] == 1.0 - left_fold


@pytest.mark.parametrize("has_candidate", [False, True])
def test_missing_decision_projection_uses_runtime_frozen_object(
    monkeypatch, has_candidate
):
    inputs = importlib.import_module("mosaic.dataflows.outcome_runtime_inputs")
    tools = importlib.import_module("mosaic.bridge.tool_capabilities")
    darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")
    from mosaic.scorecard.darwinian_v2 import canonical_hash
    from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS

    candidate_universe = (
        [
            {
                "candidate_ref": "candidate:000333",
                "ts_code": "000333.SZ",
                "proposed_target_weight": 0.04,
            }
        ]
        if has_candidate
        else []
    )
    candidate_status = "AVAILABLE" if has_candidate else "EMPTY_CONFIRMED"
    authority = {
        "agent_id": "cro",
        "stage": "cro",
        "snapshot_id": "runtime-snapshot:cro",
        "snapshot_hash": "sha256:" + "1" * 64,
        "candidate_scope_hash": "sha256:" + "2" * 64,
        "candidate_universe_id": "candidate-universe:cro",
        "candidate_universe_hash": canonical_hash(
            {
                "candidate_status": candidate_status,
                "candidate_universe": candidate_universe,
            }
        ),
        "candidate_status": candidate_status,
        "candidate_universe": candidate_universe,
        "upstream_accepted_output_refs": [],
        "role_context": {},
    }
    object_payload, members = darwinian._expected_decision_frozen_object(
        "cro", authority
    )
    frozen_hash = canonical_hash(object_payload)
    frozen_object = {
        "schema_version": "decision_stage_frozen_object_set_v1",
        "agent_id": "cro",
        "object_kind": "CRO_CANDIDATE_UNIVERSE",
        "frozen_object_set_id": f"cro-candidate-universe:{frozen_hash[7:]}",
        "frozen_object_set_hash": frozen_hash,
        "object_payload": object_payload,
        "member_refs": members,
    }
    observed = {}
    materialized = {}

    class Store:
        def resolve_scheduled_sample_context(self, **_kwargs):
            return {
                "agent_id": "cro",
                "outcome_schedule_plan_id": "plan-1",
                "as_of": "2025-06-16T15:00:00+08:00",
                "graph_run_id": "graph-1",
            }

        def freeze_scheduled_outcome_opportunity(self, **kwargs):
            observed.update(kwargs)
            return {
                "run_allowed": True,
                "evaluation_opportunity_set_id": "opportunity-1",
                "evaluation_opportunity_set_hash": "sha256:" + "3" * 64,
                "frozen_object_set_id": frozen_object["frozen_object_set_id"],
                "frozen_object_set_hash": frozen_hash,
            }

        def create_no_evaluation_object_stage_skip(self, **_kwargs):
            return {"stage_skip": {"agent_id": "cro"}}

    monkeypatch.setattr(darwinian, "_store", Store)
    monkeypatch.setattr(
        inputs,
        "load_evaluation_opportunity_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    def materialize(*_args, **kwargs):
        materialized.update(kwargs)
        return json.dumps(authority)

    monkeypatch.setattr(tools, "materialize_tool_payload", materialize)

    result = dispatch(
        "darwinian.freeze_stage_outcome_opportunity",
        {
            "outcome_schedule_plan_id": "plan-1",
            "scheduled_sample_id": "sample-1",
            "agent_id": "cro",
            "recorded_at": "2025-06-16T15:00:00+08:00",
            "runtime_input_hash": "sha256:" + "4" * 64,
            "frozen_object": frozen_object,
        },
    )

    if has_candidate:
        assert "stage_skip" not in result
    else:
        assert result["stage_skip"] == {"agent_id": "cro"}
    assert materialized["expected_runtime_input_hash"] == "sha256:" + "4" * 64
    assert observed["member_refs"] == members
    assert set(observed["source_evidence_by_required_source_id"]) == set(
        OUTCOME_CONTRACTS["cro"]["required_source_ids"]
    )
    assert all(
        evidence[0].startswith("runtime-frozen:cro:")
        and evidence[0].endswith(frozen_hash[7:])
        for evidence in observed["source_evidence_by_required_source_id"].values()
    )


def test_accepted_execution_control_can_have_empty_evaluation_opportunity():
    darwinian = importlib.import_module("mosaic.bridge.handlers.darwinian")

    class Store:
        def resolve_no_evaluation_object_stage_skip(self, **kwargs):
            if kwargs["agent_id"] != "autonomous_execution":
                return None
            return {
                "stage_skip_id": "skip:execution",
                "stage_skip_hash": "sha256:" + "1" * 64,
            }

    darwinian._assert_server_owned_decision_control_sources(
        Store(),
        agent_id="cio",
        graph_run_id="graph-1",
        runtime_authority={
            "role_context": {
                "cro_control_source": {
                    "source_status": "ACCEPTED_OUTPUT",
                    "agent_id": "cro",
                    "accepted_output_kind": "CRO_RISK_REVIEW",
                    "accepted_output_id": "accepted:cro",
                    "accepted_output_hash": "sha256:" + "2" * 64,
                    "stage_skip_id": None,
                    "stage_skip_hash": None,
                },
                "execution_control_source": {
                    "source_status": "ACCEPTED_OUTPUT",
                    "agent_id": "autonomous_execution",
                    "accepted_output_kind": "EXECUTION_ASSESSMENT",
                    "accepted_output_id": "accepted:execution",
                    "accepted_output_hash": "sha256:" + "3" * 64,
                    "stage_skip_id": None,
                    "stage_skip_hash": None,
                },
            }
        },
    )


# ===========================================================================
# darwinian.compute
# ===========================================================================


class TestDarwinianCompute:
    def test_empty_store_returns_zero(self, tmp_store):
        result = dispatch(
            "darwinian.compute",
            {
                "cohort": "cohort_default",
                "today": "2024-07-31",
                "audit_only": True,
            },
        )
        assert result == {
            "status": "legacy_unverified",
            "audit_only": True,
            "written": 0,
            "agents_uniform_fallback": 0,
        }

    def test_missing_cohort_param(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch(
                "darwinian.compute",
                {"today": "2024-07-31", "audit_only": True},
            )

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
                    "cohort, agent, ticker, date, action, alpha_5d, scored_at, "
                    "day_outcome_status) VALUES (?, ?, ?, '2024-07-01', 'BUY', ?, "
                    "'2024-07-08', 'accepted')",
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
                {
                    "cohort": "cohort_default",
                    "today": "2024-07-31",
                    "audit_only": True,
                },
            )
        finally:
            set_config({})

        assert result["written"] == 8
        row = dispatch(
            "darwinian.get_weights",
            {
                "cohort": "cohort_default",
                "date": "2024-07-31",
                "audit_only": True,
            },
        )["weights"]["semiconductor"]
        assert row["update_action"] == "up"
        assert row["performance_metric"] == "alpha_5d_mean_30d"
        assert row["weight"] == pytest.approx(1.05)


# ===========================================================================
# darwinian.get_weights
# ===========================================================================


class TestDarwinianGetWeights:
    def test_empty_returns_empty_dict(self, tmp_store):
        result = dispatch(
            "darwinian.get_weights",
            {"cohort": "cohort_default", "audit_only": True},
        )
        assert result == {
            "status": "legacy_unverified",
            "audit_only": True,
            "weights": {},
        }

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
            {
                "cohort": "cohort_default",
                "date": "2024-07-31",
                "audit_only": True,
            },
        )
        assert "ackman" in result["weights"]
        assert result["weights"]["ackman"]["weight"] == pytest.approx(1.5)
        assert result["weights"]["ackman"]["quartile"] == 1

    def test_returns_unified_weight_metadata(self, tmp_store):
        tmp_store.upsert_darwinian_weights(
            [
                {
                    "cohort": "cohort_default",
                    "agent": "us_financial_conditions",
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
            {
                "cohort": "cohort_default",
                "date": "2024-07-31",
                "audit_only": True,
            },
        )
        row = result["weights"]["us_financial_conditions"]
        assert row["layer"] == "macro"
        assert row["performance_metric"] == "raw_macro_score_5d"
        assert row["rank_scope"] == "macro"
        assert row["source_table"] == "macro_signals"

    def test_invalid_date_param(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch(
                "darwinian.get_weights",
                {
                    "cohort": "cohort_default",
                    "date": 12345,
                    "audit_only": True,
                },
            )

    @pytest.mark.parametrize("method", ["darwinian.compute", "darwinian.get_weights"])
    def test_legacy_surface_requires_explicit_audit_only(self, tmp_store, method):
        params = {"cohort": "cohort_default"}
        if method == "darwinian.compute":
            params["today"] = "2024-07-31"
        with pytest.raises(RpcError, match="legacy_unverified/audit_only"):
            dispatch(method, params)


# ===========================================================================
# Method registration
# ===========================================================================


def test_scorecard_and_legacy_audit_methods_registered_without_knot_rpc():
    from mosaic.bridge.registry import all_methods

    methods = set(all_methods())
    expected = {
        "scorecard.append",
        "scorecard.score_pending",
        "scorecard.list_skill",
        "scorecard.latest_cio_actions",
        "scorecard.latest_agent_narratives",
        "scorecard.win_rate",
        "darwinian.compute",
        "darwinian.get_weights",
    }
    assert expected.issubset(methods)
    assert not any(method.startswith("darwinian.knot_") for method in methods)


class TestSignalsRpc:
    def _seed(self, store):
        with store._connect() as conn:
            conn.executemany(
                "INSERT INTO recommendations(cohort,agent,ticker,date,action,"
                "target_weight_pct,forward_return_5d,scored_at,day_outcome_status) "
                "VALUES (?,?,?,?,?,?,?,?, 'accepted')",
                [
                    ("cohort_default", "cio", "510300.SH", "2024-06-25", "BUY", 30.0, None, None),
                    ("cohort_default", "cio", "510300.SH", "2024-06-10", "BUY", 30.0, 0.03, "x"),
                    ("cohort_default", "cio", "512880.SH", "2024-06-10", "SELL", 0.0, -0.04, "x"),
                ],
            )

    def test_latest_cio_actions_hides_unsealed_rows(self, tmp_store):
        self._seed(tmp_store)
        out = dispatch("scorecard.latest_cio_actions", {"cohort": "cohort_default"})
        assert out == {
            "cohort": "cohort_default",
            "date": None,
            "actions": [],
        }

    def test_latest_agent_narratives_rpc_empty(self, tmp_store):
        out = dispatch(
            "scorecard.latest_agent_narratives", {"cohort": "cohort_default"}
        )
        assert out["date"] is None
        assert out["narratives"] == []

    def test_win_rate_rpc(self, tmp_store):
        self._seed(tmp_store)
        rows = dispatch("scorecard.win_rate", {"cohort": "cohort_default"})["rows"]
        by = {r["ticker"]: r for r in rows}
        assert by["510300.SH"]["win_rate"] == 1.0
        assert by["512880.SH"]["win_rate"] == 1.0

    def test_latest_cio_actions_requires_cohort(self):
        with pytest.raises(RpcError):
            dispatch("scorecard.latest_cio_actions", {})

    def test_latest_agent_narratives_requires_cohort(self):
        with pytest.raises(RpcError):
            dispatch("scorecard.latest_agent_narratives", {})

    def test_win_rate_rejects_bad_since(self, tmp_store):
        with pytest.raises(RpcError):
            dispatch("scorecard.win_rate", {"cohort": "cohort_default", "since": 123})
