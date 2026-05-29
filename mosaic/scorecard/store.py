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
                                  target_weight_pct = target_weight × 100.

UNIQUE(cohort, agent, ticker, date) — duplicate ingest is idempotent
(ON CONFLICT DO UPDATE keeps the latest fields; doesn't overwrite scoring
columns once they're populated).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

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
                    # CIO doesn't expose conviction per pick — use target_weight
                    # as a proxy (1.0 weight = full conviction).
                    "conviction": target_weight,
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
            conn.execute(
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: Optional[str], max_len: int) -> Optional[str]:
    if not text:
        return None
    s = str(text).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"
