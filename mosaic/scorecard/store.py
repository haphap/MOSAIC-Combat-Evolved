"""SQLite persistence for daily-cycle agent recommendations (Plan §11.3 3A).

State → row expansion convention (Plan §11.3 3A design decisions):

    Layer 1 (10 macro agents)  → not persisted (no ticker; regime signals
                                  are inputs, not predictions).
    Layer 2 (7 sector agents)  → 1 row per longs[] entry; shorts dropped
                                  (A-share short-selling not viable).
                                  target_weight_pct = conviction × 100.
    Layer 3 (4 superinvestors) → 1 row per picks[] entry.
                                  target_weight_pct = conviction × 100.
    Layer 4 (cio only)         → 1 row per portfolio_actions[] entry.
                                  target_weight_pct = target_weight × 100;
                                  conviction = NULL (§14 R-A2: CIO has no
                                  per-pick conviction, only a portfolio weight).

UNIQUE(cohort, agent, ticker, date) — duplicate ingest is idempotent
(ON CONFLICT DO UPDATE keeps the latest fields; doesn't overwrite scoring
columns once they're populated).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# Resolve <repoRoot>/data/scorecard.db at import time.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = (
    Path(os.getenv("MOSAIC_DATA_DIR", str(_REPO_ROOT / "data"))) / "scorecard.db"
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    agent TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,                         -- YYYY-MM-DD
    action TEXT NOT NULL,                       -- BUY/SELL/HOLD/REDUCE/LONG/SHORT
    conviction REAL,                            -- [0, 1]
    target_weight_pct REAL,                     -- [0, 100]
    rationale_snapshot TEXT,
    forward_return_5d REAL,                     -- NULL until scored
    forward_return_21d REAL,
    alpha_5d REAL,
    scored_at TEXT,                             -- NULL = pending
    UNIQUE(cohort, agent, ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_rec_pending
    ON recommendations(scored_at) WHERE scored_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_rec_cohort_agent_date
    ON recommendations(cohort, agent, date);

CREATE TABLE IF NOT EXISTS darwinian_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    agent TEXT NOT NULL,
    date TEXT NOT NULL,                         -- YYYY-MM-DD
    weight REAL NOT NULL CHECK (weight >= 0.3 AND weight <= 2.5),
    rolling_sharpe_30 REAL,
    rolling_sharpe_90 REAL,
    quartile INTEGER,                           -- 1 (best) ... 4 (worst)
    UNIQUE(cohort, agent, date)
);

-- Phase 3.5C: two-stage backtest cache (Plan §11.4 design decision #7).
-- Stage 1 (TS): batch-runs daily-cycles for [start, end] writing to
-- backtest_actions. Stage 2 (Python qlib): replays from this table — pure
-- read, no LLM calls — so mutation evaluation in Phase 4 is fast and
-- deterministic.
CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    start_date TEXT NOT NULL,                   -- YYYY-MM-DD
    end_date TEXT NOT NULL,                     -- YYYY-MM-DD
    prompt_commit_hash TEXT NOT NULL,           -- tracks which prompt version this run used
    created_at TEXT NOT NULL,
    completed_at TEXT,                          -- NULL = stage 1 in progress / failed
    UNIQUE(cohort, start_date, end_date, prompt_commit_hash)
);

CREATE TABLE IF NOT EXISTS backtest_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,                   -- YYYY-MM-DD
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,                       -- BUY/SELL/HOLD/REDUCE
    target_weight REAL NOT NULL,                -- [0, 1]
    holding_period TEXT,                        -- 1W/1M/3M/6M/1Y/5Y+ or NULL
    dissent_notes TEXT,
    UNIQUE(run_id, trade_date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_btactions_run_date
    ON backtest_actions(run_id, trade_date);

-- Phase 4 autoresearch: prompt mutation provenance + audit log (Plan §7, §11.5).
-- A "version" is one feature-branch attempt at improving one agent's prompt.
-- Lifecycle: created (pending, no mod_commit yet) → mutation recorded
-- (mod_commit filled) → evaluated (pre/post/delta filled) → decided
-- (status = keep | revert). branch_name is globally unique (one branch per
-- attempt). modification_commit_hash links to backtest_runs.prompt_commit_hash.
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    agent TEXT NOT NULL,
    branch_name TEXT NOT NULL,                  -- cohort/<cohort>/auto/<agent>/<YYYY-MM-DD>
    base_commit_hash TEXT NOT NULL,             -- main HEAD the branch forked from
    modification_commit_hash TEXT,              -- NULL until TS mutator commits the rewrite
    modification_summary TEXT,                  -- LLM-authored one-line "what changed"
    created_at TEXT NOT NULL,                   -- ISO-8601
    status TEXT NOT NULL,                       -- pending / keep / revert
    decided_at TEXT,                            -- ISO-8601, set when status leaves pending
    pre_sharpe REAL,                            -- base prompt backtest Sharpe
    post_sharpe REAL,                           -- mutated prompt backtest Sharpe
    delta_sharpe REAL,                          -- post - pre
    UNIQUE(branch_name)
);

CREATE INDEX IF NOT EXISTS idx_pv_pending
    ON prompt_versions(status, created_at) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_pv_cohort_agent
    ON prompt_versions(cohort, agent, created_at);

CREATE TABLE IF NOT EXISTS autoresearch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_version_id INTEGER REFERENCES prompt_versions(id) ON DELETE CASCADE,
    event TEXT NOT NULL,                        -- triggered/mutated/evaluated/kept/reverted
    detail TEXT,
    created_at TEXT NOT NULL                    -- ISO-8601
);

CREATE INDEX IF NOT EXISTS idx_arlog_version
    ON autoresearch_log(prompt_version_id);

-- Phase 5 PRISM: cohort training run tracking (Plan section 7).
CREATE TABLE IF NOT EXISTS cohort_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    date TEXT NOT NULL,                         -- YYYY-MM-DD
    cycle_started_at TEXT,                      -- ISO-8601
    cycle_completed_at TEXT,                    -- ISO-8601
    llm_calls INTEGER,
    llm_cost_usd REAL,
    cio_action TEXT,
    cio_target_weight REAL,
    notes TEXT,
    UNIQUE(cohort, date)
);

-- Phase 6 JANUS: daily meta-weighting output (Plan §11.7).
CREATE TABLE IF NOT EXISTS janus_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                         -- YYYY-MM-DD
    weights_json TEXT NOT NULL,                 -- {cohort: weight}
    regime_label TEXT,
    dominant_cohort TEXT,
    concentration REAL,
    n_blended INTEGER,
    n_contested INTEGER,
    created_at TEXT NOT NULL,                   -- ISO-8601
    UNIQUE(date)
);
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingRow:
    """Minimal row tuple needed by Phase 3B scorer."""

    id: int
    cohort: str
    agent: str
    ticker: str
    date: str
    action: str


# ---------------------------------------------------------------------------
# State expansion (pure function, exported for testing without a DB)
# ---------------------------------------------------------------------------


def expand_state_to_recommendations(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Project a daily-cycle final state dict into recommendation rows.

    See module docstring for the per-layer expansion convention.

    Returns a list of dicts with keys:
        cohort / agent / ticker / date / action / conviction /
        target_weight_pct / rationale_snapshot
    """
    cohort = state.get("active_cohort") or "cohort_default"
    date = state.get("as_of_date")
    if not isinstance(date, str) or not date:
        raise ValueError("state.as_of_date is required to expand recommendations")

    rows: list[dict[str, Any]] = []

    # ── Layer 2 sector agents ─────────────────────────────────────────────
    for sector_id, out in (state.get("layer2_outputs") or {}).items():
        if not isinstance(out, dict):
            continue
        # relationship_mapper has a different shape (no longs/shorts) — skip
        # since its output is structural, not pickwise.
        if out.get("agent") == "relationship_mapper":
            continue
        for pick in out.get("longs", []) or []:
            ticker = pick.get("ticker")
            if not ticker:
                continue
            conviction = float(pick.get("conviction") or 0.0)
            rows.append(
                {
                    "cohort": cohort,
                    "agent": sector_id,
                    "ticker": ticker,
                    "date": date,
                    "action": "LONG",
                    "conviction": conviction,
                    "target_weight_pct": conviction * 100.0,
                    "rationale_snapshot": _truncate(pick.get("thesis"), 200),
                }
            )

    # ── Layer 3 superinvestor agents ──────────────────────────────────────
    for super_id, out in (state.get("layer3_outputs") or {}).items():
        if not isinstance(out, dict):
            continue
        philosophy = out.get("philosophy_note") or ""
        for pick in out.get("picks", []) or []:
            ticker = pick.get("ticker")
            if not ticker:
                continue
            conviction = float(pick.get("conviction") or 0.0)
            thesis = pick.get("thesis") or ""
            rationale = thesis if thesis else philosophy
            rows.append(
                {
                    "cohort": cohort,
                    "agent": super_id,
                    "ticker": ticker,
                    "date": date,
                    "action": "LONG",
                    "conviction": conviction,
                    "target_weight_pct": conviction * 100.0,
                    "rationale_snapshot": _truncate(rationale, 200),
                }
            )

    # ── Layer 4 cio only (other L4 agents don't carry tickers per se) ────
    layer4 = state.get("layer4_outputs") or {}
    cio = layer4.get("cio") if isinstance(layer4, dict) else None
    if isinstance(cio, dict):
        for action_obj in cio.get("portfolio_actions", []) or []:
            ticker = action_obj.get("ticker")
            if not ticker:
                continue
            target_weight = float(action_obj.get("target_weight") or 0.0)
            rows.append(
                {
                    "cohort": cohort,
                    "agent": "cio",
                    "ticker": ticker,
                    "date": date,
                    "action": action_obj.get("action") or "HOLD",
                    # §14 R-A2: CIO has no per-pick conviction — it emits a
                    # portfolio target_weight. Storing target_weight as a
                    # "conviction" proxy makes it falsely comparable to the
                    # real per-pick conviction of L2/L3 agents. Write NULL to
                    # mark it explicitly not-comparable; target_weight_pct still
                    # carries the real position weight. (autoresearch evaluates
                    # CIO mutations via portfolio Sharpe, not conviction — Plan
                    # §11.5 decision #10.)
                    "conviction": None,
                    "target_weight_pct": target_weight * 100.0,
                    "rationale_snapshot": _truncate(
                        action_obj.get("dissent_notes") or action_obj.get("thesis"),
                        200,
                    ),
                }
            )

    return rows


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ScorecardStore:
    """Thin SQLite wrapper. Holds the connection lazily; safe across threads
    only when each thread calls ``.connect()`` — the bridge handler is
    single-threaded so we don't bother with a connection pool.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── lifecycle ────────────────────────────────────────────────────────

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    # ── recommendations ──────────────────────────────────────────────────

    def append_from_state(self, state: dict[str, Any]) -> int:
        """Ingest a daily-cycle final state. Returns the number of rows
        upserted.

        Idempotent: re-ingesting the same (cohort, agent, ticker, date) updates
        action / conviction / target_weight_pct / rationale_snapshot but does
        NOT touch scoring columns (forward_return_5d / forward_return_21d /
        alpha_5d / scored_at). This lets you re-run ``daily-cycle`` and have
        the ingest pick up corrections without invalidating already-scored
        history.
        """
        rows = expand_state_to_recommendations(state)
        if not rows:
            return 0

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO recommendations (
                    cohort, agent, ticker, date, action, conviction,
                    target_weight_pct, rationale_snapshot
                ) VALUES (
                    :cohort, :agent, :ticker, :date, :action, :conviction,
                    :target_weight_pct, :rationale_snapshot
                )
                ON CONFLICT(cohort, agent, ticker, date) DO UPDATE SET
                    action = excluded.action,
                    conviction = excluded.conviction,
                    target_weight_pct = excluded.target_weight_pct,
                    rationale_snapshot = excluded.rationale_snapshot
                """,
                rows,
            )
        return len(rows)

    def list_pending(
        self,
        cohort: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> list[PendingRow]:
        """Return rows where scored_at IS NULL.

        ``before_date`` (inclusive) filters rows whose forward window has
        already had time to mature (e.g. only score rows where date + 5
        trading days <= today). Caller computes the cutoff.
        """
        sql = (
            "SELECT id, cohort, agent, ticker, date, action FROM recommendations "
            "WHERE scored_at IS NULL"
        )
        params: list[Any] = []
        if cohort:
            sql += " AND cohort = ?"
            params.append(cohort)
        if before_date:
            sql += " AND date <= ?"
            params.append(before_date)
        sql += " ORDER BY date, id"

        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return [
                PendingRow(
                    id=row["id"],
                    cohort=row["cohort"],
                    agent=row["agent"],
                    ticker=row["ticker"],
                    date=row["date"],
                    action=row["action"],
                )
                for row in cur.fetchall()
            ]

    def update_scoring(
        self,
        row_id: int,
        forward_return_5d: Optional[float],
        forward_return_21d: Optional[float],
        alpha_5d: Optional[float],
        scored_at: str,
    ) -> None:
        """Used by Phase 3B scorer to fill the scoring columns."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE recommendations SET
                    forward_return_5d = :forward_return_5d,
                    forward_return_21d = :forward_return_21d,
                    alpha_5d = :alpha_5d,
                    scored_at = :scored_at
                WHERE id = :id
                """,
                {
                    "id": row_id,
                    "forward_return_5d": forward_return_5d,
                    "forward_return_21d": forward_return_21d,
                    "alpha_5d": alpha_5d,
                    "scored_at": scored_at,
                },
            )
            # §14 R-T5: surface a silent no-op (row_id absent) instead of
            # swallowing it — Phase 4 may add a purge path that deletes rows
            # out from under a scorer pass.
            if cur.rowcount == 0:
                logger.warning(
                    "update_scoring: no recommendation row with id=%s (no-op)", row_id
                )

    def list_scored(
        self,
        cohort: str,
        agent: Optional[str] = None,
        since_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return scored rows (alpha_5d IS NOT NULL) for skill / weight calc."""
        sql = (
            "SELECT id, cohort, agent, ticker, date, action, conviction, "
            "       target_weight_pct, forward_return_5d, forward_return_21d, "
            "       alpha_5d, scored_at "
            "FROM recommendations "
            "WHERE cohort = ? AND alpha_5d IS NOT NULL"
        )
        params: list[Any] = [cohort]
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        if since_date:
            sql += " AND date >= ?"
            params.append(since_date)
        sql += " ORDER BY date, id"

        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def list_recommendations(
        self,
        cohort: str,
        agent: Optional[str] = None,
        date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return recommendation rows (scored or not) filtered by cohort and
        optionally agent / date. Used by JANUS to read CIO picks for blending."""
        sql = (
            "SELECT id, cohort, agent, ticker, date, action, conviction, "
            "       target_weight_pct, rationale_snapshot FROM recommendations "
            "WHERE cohort = ?"
        )
        params: list[Any] = [cohort]
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        if date:
            sql += " AND date = ?"
            params.append(date)
        sql += " ORDER BY date, id"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── darwinian_weights (placeholder; populated by Phase 3C) ────────────

    def upsert_darwinian_weights(self, rows: Iterable[dict[str, Any]]) -> int:
        """Upsert (cohort, agent, date) → weight. Returns count written."""
        rows = list(rows)
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO darwinian_weights (
                    cohort, agent, date, weight,
                    rolling_sharpe_30, rolling_sharpe_90, quartile
                ) VALUES (
                    :cohort, :agent, :date, :weight,
                    :rolling_sharpe_30, :rolling_sharpe_90, :quartile
                )
                ON CONFLICT(cohort, agent, date) DO UPDATE SET
                    weight = excluded.weight,
                    rolling_sharpe_30 = excluded.rolling_sharpe_30,
                    rolling_sharpe_90 = excluded.rolling_sharpe_90,
                    quartile = excluded.quartile
                """,
                rows,
            )
        return len(rows)

    def get_darwinian_weights(
        self, cohort: str, date: Optional[str] = None
    ) -> dict[str, dict[str, Any]]:
        """Return ``{agent: {weight, sharpe_30, sharpe_90, quartile}}``.

        If ``date`` is None, returns the latest row per (cohort, agent).
        """
        if date:
            sql = (
                "SELECT agent, weight, rolling_sharpe_30, rolling_sharpe_90, quartile "
                "FROM darwinian_weights WHERE cohort = ? AND date = ?"
            )
            params: list[Any] = [cohort, date]
        else:
            sql = (
                "SELECT agent, weight, rolling_sharpe_30, rolling_sharpe_90, quartile "
                "FROM darwinian_weights w1 "
                "WHERE cohort = ? AND date = ("
                "  SELECT MAX(date) FROM darwinian_weights w2 "
                "  WHERE w2.cohort = w1.cohort AND w2.agent = w1.agent"
                ")"
            )
            params = [cohort]

        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return {
                row["agent"]: {
                    "weight": row["weight"],
                    "sharpe_30": row["rolling_sharpe_30"],
                    "sharpe_90": row["rolling_sharpe_90"],
                    "quartile": row["quartile"],
                }
                for row in cur.fetchall()
            }

    # ── backtest_runs / backtest_actions (Phase 3.5C two-stage cache) ─────

    def create_backtest_run(
        self,
        *,
        cohort: str,
        start_date: str,
        end_date: str,
        prompt_commit_hash: str,
    ) -> int:
        """Open a new backtest run row and return its id.

        Idempotent: if a run with the same (cohort, start_date, end_date,
        prompt_commit_hash) already exists, returns its id instead of
        creating a duplicate (UPSERT-style).
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO backtest_runs (
                    cohort, start_date, end_date, prompt_commit_hash, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cohort, start_date, end_date, prompt_commit_hash)
                DO UPDATE SET created_at = created_at  -- no-op; preserves original timestamp
                RETURNING id
                """,
                (cohort, start_date, end_date, prompt_commit_hash, now),
            )
            row = cur.fetchone()
            return int(row["id"])

    def append_backtest_actions(
        self,
        run_id: int,
        trade_date: str,
        actions: list[dict[str, Any]],
    ) -> int:
        """Insert (or upsert) per-trade-day portfolio_actions for a run.

        ``actions`` is the list-shape produced by CIO's portfolio_actions:
        each item must have ``ticker``, ``action``, ``target_weight``,
        and may have ``holding_period`` and ``dissent_notes``.
        """
        rows = []
        for a in actions:
            ticker = a.get("ticker")
            action = a.get("action")
            target_weight = a.get("target_weight")
            if not isinstance(ticker, str) or not ticker:
                continue
            if action not in ("BUY", "SELL", "HOLD", "REDUCE"):
                continue
            if not isinstance(target_weight, (int, float)):
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "trade_date": trade_date,
                    "ticker": ticker,
                    "action": action,
                    "target_weight": float(target_weight),
                    "holding_period": a.get("holding_period"),
                    "dissent_notes": _truncate(a.get("dissent_notes"), 500),
                }
            )
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO backtest_actions (
                    run_id, trade_date, ticker, action,
                    target_weight, holding_period, dissent_notes
                ) VALUES (
                    :run_id, :trade_date, :ticker, :action,
                    :target_weight, :holding_period, :dissent_notes
                )
                ON CONFLICT(run_id, trade_date, ticker) DO UPDATE SET
                    action = excluded.action,
                    target_weight = excluded.target_weight,
                    holding_period = excluded.holding_period,
                    dissent_notes = excluded.dissent_notes
                """,
                rows,
            )
        return len(rows)

    def complete_backtest_run(self, run_id: int) -> None:
        """Mark a backtest run as fully populated (stage-1 done)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE backtest_runs SET completed_at = ? WHERE id = ?",
                (now, run_id),
            )

    def get_backtest_run(self, run_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, cohort, start_date, end_date, prompt_commit_hash, "
                "       created_at, completed_at "
                "FROM backtest_runs WHERE id = ?",
                (run_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_backtest_runs(
        self,
        cohort: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, cohort, start_date, end_date, prompt_commit_hash, "
            "       created_at, completed_at FROM backtest_runs WHERE 1=1"
        )
        params: list[Any] = []
        if cohort:
            sql += " AND cohort = ?"
            params.append(cohort)
        if since:
            sql += " AND created_at >= ?"
            params.append(since)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_backtest_actions(
        self,
        run_id: int,
        trade_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT trade_date, ticker, action, target_weight, holding_period, "
            "       dissent_notes FROM backtest_actions WHERE run_id = ?"
        )
        params: list[Any] = [run_id]
        if trade_date:
            sql += " AND trade_date = ?"
            params.append(trade_date)
        sql += " ORDER BY trade_date, ticker"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── prompt_versions (Phase 4 autoresearch, Plan §7 / §11.5 4A) ────────

    def create_prompt_version(
        self,
        *,
        cohort: str,
        agent: str,
        branch_name: str,
        base_commit_hash: str,
        created_at: Optional[str] = None,
    ) -> int:
        """Open a pending prompt-version row (the "shell" created by
        ``autoresearch.trigger`` before the TS mutator has produced content).

        Idempotent on ``branch_name``: re-calling with an existing branch
        returns the existing row's id (so a re-triggered cycle for the same
        (cohort, agent, date) doesn't create duplicates).
        """
        created_at = created_at or _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO prompt_versions (
                    cohort, agent, branch_name, base_commit_hash,
                    created_at, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(branch_name) DO UPDATE SET branch_name = branch_name
                RETURNING id
                """,
                (cohort, agent, branch_name, base_commit_hash, created_at),
            )
            return int(cur.fetchone()["id"])

    def set_version_mutation(
        self,
        version_id: int,
        modification_commit_hash: str,
        modification_summary: Optional[str] = None,
    ) -> None:
        """Back-fill the mutation commit + summary once the TS mutator has
        written and committed the rewrite (``autoresearch.record_mutation``)."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE prompt_versions
                SET modification_commit_hash = :mod, modification_summary = :summary
                WHERE id = :id
                """,
                {
                    "id": version_id,
                    "mod": modification_commit_hash,
                    "summary": _truncate(modification_summary, 1000),
                },
            )
            if cur.rowcount == 0:
                logger.warning(
                    "set_version_mutation: no prompt_version id=%s", version_id
                )

    def set_version_eval(
        self,
        version_id: int,
        pre_sharpe: Optional[float],
        post_sharpe: Optional[float],
        delta_sharpe: Optional[float],
    ) -> None:
        """Record the backtest evaluation (Plan §11.5 4C ``compute_delta``)."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE prompt_versions
                SET pre_sharpe = :pre, post_sharpe = :post, delta_sharpe = :delta
                WHERE id = :id
                """,
                {
                    "id": version_id,
                    "pre": pre_sharpe,
                    "post": post_sharpe,
                    "delta": delta_sharpe,
                },
            )
            if cur.rowcount == 0:
                logger.warning("set_version_eval: no prompt_version id=%s", version_id)

    def decide_version(
        self,
        version_id: int,
        status: str,
        decided_at: Optional[str] = None,
    ) -> None:
        """Terminal transition: ``status`` ∈ {keep, revert}."""
        if status not in ("keep", "revert"):
            raise ValueError(f"status must be 'keep' or 'revert', got {status!r}")
        decided_at = decided_at or _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE prompt_versions SET status = ?, decided_at = ? WHERE id = ?",
                (status, decided_at, version_id),
            )
            if cur.rowcount == 0:
                logger.warning("decide_version: no prompt_version id=%s", version_id)

    def get_prompt_version(self, version_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM prompt_versions WHERE id = ?", (version_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_version_by_branch(self, branch_name: str) -> Optional[dict[str, Any]]:
        """Lookup used by ``autoresearch.trigger`` for idempotency."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM prompt_versions WHERE branch_name = ?", (branch_name,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_prompt_versions(
        self,
        cohort: Optional[str] = None,
        status: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM prompt_versions WHERE 1=1"
        params: list[Any] = []
        if cohort:
            sql += " AND cohort = ?"
            params.append(cohort)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        sql += " ORDER BY created_at DESC, id DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def list_active_branches(
        self, cohort: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Pending versions = feature branches that still exist in git
        (not yet merged/deleted). Used by ``autoresearch.list_active_branches``."""
        sql = (
            "SELECT id, cohort, agent, branch_name, base_commit_hash, "
            "       modification_commit_hash, created_at "
            "FROM prompt_versions WHERE status = 'pending'"
        )
        params: list[Any] = []
        if cohort:
            sql += " AND cohort = ?"
            params.append(cohort)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def last_mutation_at(self, cohort: str, agent: str) -> Optional[str]:
        """Most recent prompt_version created_at for (cohort, agent), any
        status. Feeds the 24h cooldown check."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT MAX(created_at) AS m FROM prompt_versions "
                "WHERE cohort = ? AND agent = ?",
                (cohort, agent),
            )
            row = cur.fetchone()
            return row["m"] if row and row["m"] else None

    def count_mutations_this_month(self, cohort: str, now_iso: str) -> int:
        """Count prompt_versions created in the same calendar month as
        ``now_iso`` (YYYY-MM prefix match). Feeds the monthly cap check."""
        month_prefix = now_iso[:7]  # YYYY-MM
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM prompt_versions "
                "WHERE cohort = ? AND substr(created_at, 1, 7) = ?",
                (cohort, month_prefix),
            )
            return int(cur.fetchone()["c"])

    # ── autoresearch_log ──────────────────────────────────────────────────

    def append_log(
        self,
        version_id: Optional[int],
        event: str,
        detail: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> int:
        created_at = created_at or _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO autoresearch_log (prompt_version_id, event, detail, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (version_id, event, _truncate(detail, 1000), created_at),
            )
            return int(cur.lastrowid)

    def get_log(
        self,
        cohort: Optional[str] = None,
        days: Optional[int] = None,
        now_iso: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Audit trail, newest first. ``cohort`` filters via the parent
        prompt_version; ``days`` keeps entries with created_at within the
        trailing window (relative to ``now_iso`` or current UTC)."""
        sql = (
            "SELECT l.id, l.prompt_version_id, l.event, l.detail, l.created_at, "
            "       v.cohort, v.agent, v.branch_name "
            "FROM autoresearch_log l "
            "LEFT JOIN prompt_versions v ON v.id = l.prompt_version_id "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if cohort:
            sql += " AND v.cohort = ?"
            params.append(cohort)
        if days is not None:
            from datetime import datetime, timedelta, timezone

            base = (
                datetime.fromisoformat(now_iso)
                if now_iso
                else datetime.now(timezone.utc)
            )
            cutoff = (base - timedelta(days=days)).isoformat()
            sql += " AND l.created_at >= ?"
            params.append(cutoff)
        sql += " ORDER BY l.created_at DESC, l.id DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── cohort_runs (Phase 5 PRISM) ──────────────────────────────────────

    def create_cohort_run(
        self,
        cohort: str,
        date: str,
        notes: Optional[str] = None,
    ) -> int:
        """INSERT OR IGNORE a cohort run entry and return its id."""
        now = _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO cohort_runs (cohort, date, cycle_started_at, notes)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cohort, date) DO UPDATE SET cohort = cohort
                RETURNING id
                """,
                (cohort, date, now, _truncate(notes, 500)),
            )
            return int(cur.fetchone()["id"])

    def complete_cohort_run(
        self,
        run_id: int,
        llm_calls: Optional[int] = None,
        llm_cost_usd: Optional[float] = None,
        cio_action: Optional[str] = None,
        cio_target_weight: Optional[float] = None,
    ) -> None:
        """Mark a cohort run as completed with optional metrics."""
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE cohort_runs SET
                    cycle_completed_at = ?,
                    llm_calls = ?,
                    llm_cost_usd = ?,
                    cio_action = ?,
                    cio_target_weight = ?
                WHERE id = ?
                """,
                (now, llm_calls, llm_cost_usd, cio_action, cio_target_weight, run_id),
            )

    def get_cohort_runs(
        self,
        cohort: str,
        since_date: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return cohort runs, newest first."""
        sql = "SELECT * FROM cohort_runs WHERE cohort = ?"
        params: list[Any] = [cohort]
        if since_date:
            sql += " AND date >= ?"
            params.append(since_date)
        sql += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_cohort_status_summary(self, cohort: str) -> dict[str, Any]:
        """Return summary status for a cohort.

        Returns {cohort, n_runs, last_date, n_mutations, sharpe_latest}.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS n, MAX(date) AS last_date "
                "FROM cohort_runs WHERE cohort = ?",
                (cohort,),
            )
            row = cur.fetchone()
            n_runs = row["n"] if row else 0
            last_date = row["last_date"] if row else None

            # Count mutations from prompt_versions.
            cur2 = conn.execute(
                "SELECT COUNT(*) AS n FROM prompt_versions WHERE cohort = ?",
                (cohort,),
            )
            n_mutations = cur2.fetchone()["n"]

            # Latest Sharpe from prompt_versions (most recent post_sharpe).
            cur3 = conn.execute(
                "SELECT post_sharpe FROM prompt_versions "
                "WHERE cohort = ? AND post_sharpe IS NOT NULL "
                "ORDER BY decided_at DESC LIMIT 1",
                (cohort,),
            )
            sharpe_row = cur3.fetchone()
            sharpe_latest = float(sharpe_row["post_sharpe"]) if sharpe_row else None

        return {
            "cohort": cohort,
            "n_runs": n_runs,
            "last_date": last_date,
            "n_mutations": n_mutations,
            "sharpe_latest": sharpe_latest,
        }

    # ── janus_runs (Phase 6 JANUS, Plan §11.7) ───────────────────────────

    def record_janus_run(
        self,
        *,
        date: str,
        weights_json: str,
        regime_label: Optional[str],
        dominant_cohort: Optional[str],
        concentration: Optional[float],
        n_blended: int,
        n_contested: int,
    ) -> int:
        """Upsert the daily JANUS meta-weighting output (idempotent on date)."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO janus_runs (
                    date, weights_json, regime_label, dominant_cohort,
                    concentration, n_blended, n_contested, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    weights_json = excluded.weights_json,
                    regime_label = excluded.regime_label,
                    dominant_cohort = excluded.dominant_cohort,
                    concentration = excluded.concentration,
                    n_blended = excluded.n_blended,
                    n_contested = excluded.n_contested,
                    created_at = excluded.created_at
                RETURNING id
                """,
                (
                    date, weights_json, regime_label, dominant_cohort,
                    concentration, n_blended, n_contested, _utcnow_iso(),
                ),
            )
            return int(cur.fetchone()["id"])

    def get_janus_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Return the most recent ``days`` JANUS runs, newest first.

        ``days`` is a row LIMIT, not a calendar window — janus_runs holds one
        row per date, so it equals a day-window only when dates are contiguous.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM janus_runs ORDER BY date DESC LIMIT ?", (days,)
            )
            return [dict(r) for r in cur.fetchall()]




def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truncate(text: Optional[str], max_len: int) -> Optional[str]:
    if not text:
        return None
    s = str(text).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"
