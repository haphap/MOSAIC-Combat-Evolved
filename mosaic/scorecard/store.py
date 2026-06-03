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

import json
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
    replay_triggered INTEGER NOT NULL DEFAULT 0,  -- 1 = produced by a CRO-veto replay cycle (R-A1)
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
    layer TEXT,
    date TEXT NOT NULL,                         -- YYYY-MM-DD
    weight REAL NOT NULL CHECK (weight >= 0.3 AND weight <= 2.5),
    previous_weight REAL,
    performance_metric TEXT,
    performance_value REAL,
    normalized_performance REAL,
    rank_scope TEXT,
    rolling_sharpe_30 REAL,
    rolling_sharpe_90 REAL,
    quartile INTEGER,                           -- 1 (best) ... 4 (worst)
    update_action TEXT,
    n_obs INTEGER,
    source_table TEXT,
    source_date TEXT,
    updated_at TEXT,
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
    prompt_commit_hash TEXT NOT NULL,           -- legacy cache tag; repo-aware runs store an expanded prompt-v2 key here
    prompt_commit_ref TEXT,                     -- raw prompt commit/ref when prompt_commit_hash is an expanded cache key
    prompt_repo_id TEXT,                        -- project | private prompt repo identifier
    prompt_sha256 TEXT,                         -- deterministic digest of prompt file contents
    code_commit_hash TEXT,                      -- project code commit paired with this prompt run
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

-- R-A3: per-run record of trade days that failed during stage-1 fill, so an
-- operator (or a future autoresearch auto-retry) can query what to re-run
-- instead of scraping the terminal log. Rows are cleared as days succeed.
CREATE TABLE IF NOT EXISTS backtest_failed_days (
    run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    date TEXT NOT NULL,                         -- YYYY-MM-DD that failed
    error TEXT NOT NULL,                        -- truncated failure message
    recorded_at TEXT NOT NULL,                  -- ISO-8601
    PRIMARY KEY (run_id, date)                  -- idempotent: re-record overwrites
);

-- Phase 4 autoresearch: prompt mutation provenance + audit log (Plan §7, §11.5).
-- A "version" is one feature-branch attempt at improving one agent's prompt.
-- Lifecycle: created (pending, no mod_commit yet) → mutation recorded
-- (mod_commit filled) → evaluated (pre/post/delta filled) → decided
-- (status = keep | revert | incompatible). branch_name is globally unique (one branch per
-- attempt). modification_commit_hash links to backtest_runs.prompt_commit_hash.
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    agent TEXT NOT NULL,
    branch_name TEXT NOT NULL,                  -- cohort/<cohort>/auto/<agent>/<YYYY-MM-DD>
    base_commit_hash TEXT NOT NULL,             -- project code HEAD when this version was triggered
    modification_commit_hash TEXT,              -- NULL until TS mutator commits the rewrite
    prompt_base_commit_hash TEXT,               -- private prompt repo base commit used for the mutation branch
    prompt_repo_id TEXT,                        -- project | private prompt repo identifier
    prompt_sha256 TEXT,                         -- deterministic digest of the committed prompt files
    code_commit_hash TEXT,                      -- project code commit paired with this prompt mutation
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

-- Phase 7 MiroFish: synthetic forward-training runs (Plan §11.8). Isolated
-- from real P&L / scorecard alpha — this is imagination-mode training only.
CREATE TABLE IF NOT EXISTS mirofish_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                         -- YYYY-MM-DD
    agent TEXT NOT NULL,
    scenario_type TEXT NOT NULL,                -- base/bull/bear/tail_up/tail_down/all
    n_scenarios INTEGER,
    avg_score REAL,
    detail_json TEXT,
    created_at TEXT NOT NULL,                   -- ISO-8601
    UNIQUE(date, agent, scenario_type)
);

CREATE TABLE IF NOT EXISTS mirofish_context (
    date TEXT PRIMARY KEY,                       -- YYYY-MM-DD (one latest context per day)
    regime TEXT,                                 -- base scenario regime
    csi300_return REAL,                          -- base scenario CSI300 cumulative return
    hct_ticker TEXT,                             -- highest-conviction (largest |return|) ticker
    hct_direction TEXT,                          -- LONG / SHORT
    tail_summary TEXT,                            -- worst-case (tail_down) one-liner
    detail_json TEXT,                            -- full derived summary (JSON)
    created_at TEXT NOT NULL                     -- ISO-8601
);

-- Layer 1 macro-agent signals (autoresearch macro plan). Macro agents emit
-- regime signals, not ticker recommendations, so they live here instead of
-- ``recommendations``. Scored later by direction (benchmark 5d in MVP).
CREATE TABLE IF NOT EXISTS macro_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    agent TEXT NOT NULL,
    date TEXT NOT NULL,                          -- YYYY-MM-DD (signal as-of date)
    vote INTEGER NOT NULL CHECK (vote IN (-1, 0, 1)),
    confidence REAL,
    raw_output_json TEXT,                        -- original structured macro output
    consensus_stance TEXT,                       -- Layer 1 aggregate stance that day
    consensus_score REAL,
    label_type TEXT,                             -- e.g. benchmark_5d / benchmark_fallback_5d
    label_source_status TEXT,                    -- primary / fallback / missing / deferred
    label_value_5d REAL,                         -- raw value of the scoring label
    benchmark_return_5d REAL,
    realized_label INTEGER CHECK (realized_label IN (-1, 0, 1)),
    hit_5d INTEGER,                              -- 1 if vote == realized_label
    raw_macro_score_5d REAL,                     -- MVP primary score
    influence_weight_equal REAL,                 -- diagnostics (Phase 8)
    effective_macro_score_5d REAL,               -- diagnostics (Phase 8)
    prompt_repo_id TEXT,
    prompt_sha256 TEXT,
    scored_at TEXT,                              -- NULL until the 5d window matures
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


@dataclass(frozen=True)
class PendingMacroRow:
    """Minimal macro-signal row needed by the macro scorer."""

    id: int
    cohort: str
    agent: str
    date: str
    vote: int
    confidence: Optional[float]
    influence_weight_equal: Optional[float]


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

    # R-A1: provenance — was this cycle's portfolio produced after a CRO-veto
    # replay? Stamped on every row so the scorecard can segment first-pass vs
    # replayed recommendations.
    replay_flag = 1 if state.get("replay_triggered") else 0

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

    for row in rows:
        row["replay_triggered"] = replay_flag

    return rows


# ---------------------------------------------------------------------------
# Macro-signal expansion (Layer 1) — mirrors the TS aggregator vote table
# (mosaic-ts/src/agents/macro/_aggregator.ts ``voteForAgent``). Keep in sync.
# ---------------------------------------------------------------------------

MACRO_AGENTS: frozenset[str] = frozenset(
    {
        "central_bank", "china", "geopolitical", "dollar", "yield_curve",
        "commodities", "volatility", "emerging_markets", "news_sentiment",
        "institutional_flow",
    }
)


_SHARPE_MIN_OBS = 5
_SHARPE_ANNUALIZATION = (252.0 / 5.0) ** 0.5


def _sharpe(values: list[float]) -> Optional[float]:
    """Annualized Sharpe of a score series; None below ``_SHARPE_MIN_OBS``.

    Same convention as ``scorecard.list_skill`` (n>=5, (mean/std)·sqrt(252)).
    """
    n = len(values)
    if n < _SHARPE_MIN_OBS:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
    std = var ** 0.5
    return 0.0 if std == 0 else (mean / std) * _SHARPE_ANNUALIZATION


def _macro_vote(agent: str, out: dict[str, Any]) -> int:
    """Map a macro agent's structured output to a directional vote in {-1,0,+1}.

    Canonical mapping — must match the TS aggregator's ``voteForAgent``.
    """
    if agent == "central_bank":
        s = out.get("stance")
        return 1 if s == "ACCOMMODATIVE" else (-1 if s == "TIGHTENING" else 0)
    if agent == "china":
        d = out.get("policy_direction")
        return 1 if d == "PRO_GROWTH" else (-1 if d == "RESTRAINING" else 0)
    if agent == "geopolitical":
        try:
            lvl = int(out.get("escalation_level"))
        except (TypeError, ValueError):
            return 0
        return 1 if lvl <= 2 else (-1 if lvl >= 4 else 0)
    if agent == "dollar":
        t = out.get("dxy_trend")
        return 1 if t == "WEAKENING" else (-1 if t == "STRENGTHENING" else 0)
    if agent == "yield_curve":
        r = out.get("recession_signal")
        return 1 if r == "GREEN" else (-1 if r == "RED" else 0)
    if agent == "commodities":
        c = out.get("china_demand_signal")
        return 1 if c == "ACCELERATING" else (-1 if c == "DECELERATING" else 0)
    if agent == "volatility":
        r = out.get("regime_filter")
        return 1 if r == "RISK_ON" else (-1 if r == "RISK_OFF" else 0)
    if agent == "emerging_markets":
        e = out.get("em_relative")
        return 1 if e == "OUTPERFORMING" else (-1 if e == "UNDERPERFORMING" else 0)
    if agent == "news_sentiment":
        score = float(out.get("retail_sentiment_score") or 0.0)
        if out.get("contrarian_flag"):
            return -1 if score > 0 else 0
        return 1 if score > 0.3 else (-1 if score < -0.3 else 0)
    if agent == "institutional_flow":
        sectors = out.get("sectors_in_out") or []
        net = sum(
            float(s.get("net_amount_cny") or 0.0)
            for s in sectors
            if isinstance(s, dict)
        )
        return 1 if net > 1000 else (-1 if net < -1000 else 0)
    return 0


def _macro_consensus_score(votes: Iterable[tuple[int, Optional[float]]]) -> float:
    weighted_sum = 0.0
    total_weight = 0.0
    for vote, confidence in votes:
        conf = float(confidence) if confidence is not None else 0.0
        weighted_sum += int(vote) * conf
        total_weight += conf
    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _macro_equal_weight_influence(
    rows: list[dict[str, Any]],
) -> dict[str, float]:
    """Equal-Darwinian-weight leave-one-out influence for Layer 1 diagnostics.

    This intentionally mirrors the current Layer-1 formula
    ``sum(vote*confidence)/sum(confidence)`` with every macro agent's
    Darwinian weight fixed at 1.0. It must not read updated Darwinian weights,
    otherwise influence could feed back into the weight update loop.
    """
    vote_conf = [
        (int(r["vote"]), r.get("confidence"))
        for r in rows
    ]
    with_agent = _macro_consensus_score(vote_conf)
    out: dict[str, float] = {}
    for idx, row in enumerate(rows):
        without = _macro_consensus_score([vc for j, vc in enumerate(vote_conf) if j != idx])
        out[str(row["agent"])] = abs(with_agent - without)
    return out


def expand_state_to_macro_signals(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Project a daily-cycle state's Layer 1 outputs into macro_signals rows.

    Returns dicts with: cohort / agent / date / vote / confidence /
    raw_output_json / consensus_stance / consensus_score / prompt_repo_id /
    prompt_sha256. Scoring columns are filled later by the macro scorer.
    """
    cohort = state.get("active_cohort") or "cohort_default"
    date = state.get("as_of_date")
    if not isinstance(date, str) or not date:
        raise ValueError("state.as_of_date is required to expand macro signals")

    consensus = state.get("layer1_consensus") or {}
    consensus_stance = consensus.get("stance") if isinstance(consensus, dict) else None
    consensus_score = None
    if isinstance(consensus, dict):
        for key in ("score", "layer_1_consensus_score", "confidence"):
            if consensus.get(key) is not None:
                consensus_score = float(consensus[key])
                break

    prompt_repo_id = state.get("prompt_repo_id")
    prompt_sha256 = state.get("prompt_sha256")

    rows: list[dict[str, Any]] = []
    for agent, out in (state.get("layer1_outputs") or {}).items():
        if agent not in MACRO_AGENTS or not isinstance(out, dict):
            continue
        conf = out.get("confidence")
        rows.append(
            {
                "cohort": cohort,
                "agent": agent,
                "date": date,
                "vote": _macro_vote(agent, out),
                "confidence": float(conf) if conf is not None else None,
                "raw_output_json": json.dumps(out, ensure_ascii=False),
                "consensus_stance": consensus_stance,
                "consensus_score": consensus_score,
                "prompt_repo_id": prompt_repo_id,
                "prompt_sha256": prompt_sha256,
            }
        )
    influence = _macro_equal_weight_influence(rows)
    for row in rows:
        row["influence_weight_equal"] = influence.get(row["agent"])
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
            # Lightweight migration for DBs created before replay_triggered (R-A1).
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)")}
            if "replay_triggered" not in cols:
                conn.execute(
                    "ALTER TABLE recommendations "
                    "ADD COLUMN replay_triggered INTEGER NOT NULL DEFAULT 0"
                )
            self._ensure_column(conn, "prompt_versions", "prompt_repo_id", "TEXT")
            self._ensure_column(conn, "prompt_versions", "prompt_base_commit_hash", "TEXT")
            self._ensure_column(conn, "prompt_versions", "prompt_sha256", "TEXT")
            self._ensure_column(conn, "prompt_versions", "code_commit_hash", "TEXT")
            self._ensure_column(conn, "backtest_runs", "prompt_commit_ref", "TEXT")
            self._ensure_column(conn, "backtest_runs", "prompt_repo_id", "TEXT")
            self._ensure_column(conn, "backtest_runs", "prompt_sha256", "TEXT")
            self._ensure_column(conn, "backtest_runs", "code_commit_hash", "TEXT")
            self._ensure_column(conn, "macro_signals", "influence_weight_equal", "REAL")
            self._ensure_column(conn, "macro_signals", "effective_macro_score_5d", "REAL")
            for column, ddl in (
                ("layer", "TEXT"),
                ("previous_weight", "REAL"),
                ("performance_metric", "TEXT"),
                ("performance_value", "REAL"),
                ("normalized_performance", "REAL"),
                ("rank_scope", "TEXT"),
                ("update_action", "TEXT"),
                ("n_obs", "INTEGER"),
                ("source_table", "TEXT"),
                ("source_date", "TEXT"),
                ("updated_at", "TEXT"),
            ):
                self._ensure_column(conn, "darwinian_weights", column, ddl)

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, ddl: str
    ) -> None:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

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
                    target_weight_pct, rationale_snapshot, replay_triggered
                ) VALUES (
                    :cohort, :agent, :ticker, :date, :action, :conviction,
                    :target_weight_pct, :rationale_snapshot, :replay_triggered
                )
                ON CONFLICT(cohort, agent, ticker, date) DO UPDATE SET
                    action = excluded.action,
                    conviction = excluded.conviction,
                    target_weight_pct = excluded.target_weight_pct,
                    rationale_snapshot = excluded.rationale_snapshot,
                    replay_triggered = excluded.replay_triggered
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

    # ── macro signals (Layer 1) ──────────────────────────────────────────

    def append_macro_signals_from_state(self, state: dict[str, Any]) -> int:
        """Ingest Layer 1 macro outputs into ``macro_signals``. Returns rows upserted.

        Idempotent on (cohort, agent, date): re-ingest refreshes vote/confidence/
        raw_output/consensus/provenance but never touches scoring columns
        (realized_label / raw_macro_score_5d / scored_at / …).
        """
        rows = expand_state_to_macro_signals(state)
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO macro_signals (
                    cohort, agent, date, vote, confidence, raw_output_json,
                    consensus_stance, consensus_score, influence_weight_equal,
                    prompt_repo_id, prompt_sha256
                ) VALUES (
                    :cohort, :agent, :date, :vote, :confidence, :raw_output_json,
                    :consensus_stance, :consensus_score, :influence_weight_equal,
                    :prompt_repo_id, :prompt_sha256
                )
                ON CONFLICT(cohort, agent, date) DO UPDATE SET
                    vote = excluded.vote,
                    confidence = excluded.confidence,
                    raw_output_json = excluded.raw_output_json,
                    consensus_stance = excluded.consensus_stance,
                    consensus_score = excluded.consensus_score,
                    influence_weight_equal = excluded.influence_weight_equal,
                    prompt_repo_id = excluded.prompt_repo_id,
                    prompt_sha256 = excluded.prompt_sha256
                """,
                rows,
            )
        return len(rows)

    def list_pending_macro(
        self, cohort: Optional[str] = None, before_date: Optional[str] = None
    ) -> list[PendingMacroRow]:
        """Macro signals with scored_at IS NULL (and date <= before_date)."""
        sql = (
            "SELECT id, cohort, agent, date, vote, confidence, influence_weight_equal "
            "FROM macro_signals "
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
            return [
                PendingMacroRow(
                    id=r["id"], cohort=r["cohort"], agent=r["agent"],
                    date=r["date"], vote=r["vote"], confidence=r["confidence"],
                    influence_weight_equal=r["influence_weight_equal"],
                )
                for r in conn.execute(sql, params).fetchall()
            ]

    def update_macro_scoring(self, row_id: int, fields: dict[str, Any]) -> None:
        """Fill macro scoring columns for one row. ``fields`` keys are column names."""
        allowed = {
            "label_type", "label_source_status", "label_value_5d", "benchmark_return_5d",
            "realized_label", "hit_5d", "raw_macro_score_5d", "influence_weight_equal",
            "effective_macro_score_5d", "scored_at",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in sets)
        sets["id"] = row_id
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE macro_signals SET {assignments} WHERE id = :id", sets)
            if cur.rowcount == 0:
                logger.warning("update_macro_scoring: no macro_signals row id=%s", row_id)

    def list_macro_skill(self, cohort: str, since: Optional[str] = None) -> list[dict[str, Any]]:
        """Aggregate scored macro signals per agent (autoresearch macro skill)."""
        sql = (
            "SELECT agent, vote, hit_5d, raw_macro_score_5d, effective_macro_score_5d, "
            "influence_weight_equal, date "
            "FROM macro_signals WHERE cohort = ? AND scored_at IS NOT NULL"
        )
        params: list[Any] = [cohort]
        if since:
            sql += " AND date >= ?"
            params.append(since)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        by_agent: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            by_agent.setdefault(r["agent"], []).append(r)

        out: list[dict[str, Any]] = []
        for agent, recs in by_agent.items():
            raws = [r["raw_macro_score_5d"] for r in recs if r["raw_macro_score_5d"] is not None]
            effs = [
                r["effective_macro_score_5d"]
                for r in recs
                if r["effective_macro_score_5d"] is not None
            ]
            infs = [
                r["influence_weight_equal"]
                for r in recs
                if r["influence_weight_equal"] is not None
            ]
            hits = [r["hit_5d"] for r in recs if r["hit_5d"] is not None]
            out.append(
                {
                    "agent": agent,
                    "n_obs": len(recs),
                    "mean_raw_macro_score_5d": (sum(raws) / len(raws)) if raws else None,
                    "mean_effective_macro_score_5d": (sum(effs) / len(effs)) if effs else None,
                    "hit_rate_5d": (sum(hits) / len(hits)) if hits else None,
                    "mean_influence_weight_equal": (sum(infs) / len(infs)) if infs else None,
                    "sharpe_window": _sharpe(raws),
                    "latest_signal_date": max((r["date"] for r in recs), default=None),
                }
            )
        out.sort(key=lambda d: d["agent"])
        return out

    def list_scored_macro(
        self,
        cohort: str,
        agent: Optional[str] = None,
        since_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return scored macro rows with raw_macro_score_5d for Darwinian ranking."""
        sql = (
            "SELECT id, cohort, agent, date, vote, confidence, label_type, "
            "       label_source_status, label_value_5d, benchmark_return_5d, "
            "       realized_label, hit_5d, raw_macro_score_5d, "
            "       influence_weight_equal, effective_macro_score_5d, scored_at "
            "FROM macro_signals "
            "WHERE cohort = ? AND scored_at IS NOT NULL AND raw_macro_score_5d IS NOT NULL"
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
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

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

    def get_latest_cio_actions(self, cohort: str) -> dict[str, Any]:
        """The most recent CIO portfolio actions for a cohort — "what to trade
        today": ticker / action / target_weight_pct / rationale, for the latest
        date the CIO produced any. Read-only."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(date) AS d FROM recommendations WHERE cohort = ? AND agent = 'cio'",
                (cohort,),
            ).fetchone()
            latest = row["d"] if row else None
            if not latest:
                return {"cohort": cohort, "date": None, "actions": []}
            cur = conn.execute(
                "SELECT ticker, action, target_weight_pct, rationale_snapshot, "
                "       forward_return_5d, scored_at "
                "FROM recommendations WHERE cohort = ? AND agent = 'cio' AND date = ? "
                "ORDER BY target_weight_pct DESC, ticker",
                (cohort, latest),
            )
            return {"cohort": cohort, "date": latest, "actions": [dict(r) for r in cur.fetchall()]}

    def compute_win_rate(
        self, cohort: str, since_date: Optional[str] = None, agent: str = "cio"
    ) -> list[dict[str, Any]]:
        """Per-ticker directional hit rate over SCORED rows: a pick "wins" when
        sign(action) · forward_return_5d > 0. HOLD rows carry no directional bet
        and are excluded. Returns rows sorted by win_rate desc, with n + avg
        forward return so a high rate on n=1 is visible as low-confidence."""
        sql = (
            "SELECT ticker, action, forward_return_5d FROM recommendations "
            "WHERE cohort = ? AND agent = ? AND forward_return_5d IS NOT NULL"
        )
        params: list[Any] = [cohort, agent]
        if since_date:
            sql += " AND date >= ?"
            params.append(since_date)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        agg: dict[str, dict[str, float]] = {}
        for r in rows:
            sign = _action_sign(r["action"])
            if sign == 0:
                continue  # HOLD: no directional bet
            a = agg.setdefault(r["ticker"], {"wins": 0.0, "n": 0.0, "sum_ret": 0.0})
            ret = float(r["forward_return_5d"])
            a["wins"] += 1.0 if sign * ret > 0 else 0.0
            a["n"] += 1.0
            a["sum_ret"] += sign * ret
        out = [
            {
                "ticker": t,
                "win_rate": round(v["wins"] / v["n"], 4),
                "n": int(v["n"]),
                "avg_dir_return_5d": round(v["sum_ret"] / v["n"], 4),
            }
            for t, v in agg.items()
        ]
        out.sort(key=lambda x: (x["win_rate"], x["n"]), reverse=True)
        return out


    def upsert_darwinian_weights(self, rows: Iterable[dict[str, Any]]) -> int:
        """Upsert (cohort, agent, date) → weight. Returns count written."""
        rows = list(rows)
        if not rows:
            return 0
        normalized_rows = []
        for row in rows:
            normalized = {
                "cohort": row["cohort"],
                "agent": row["agent"],
                "layer": row.get("layer"),
                "date": row["date"],
                "weight": row["weight"],
                "previous_weight": row.get("previous_weight"),
                "performance_metric": row.get("performance_metric"),
                "performance_value": row.get("performance_value"),
                "normalized_performance": row.get("normalized_performance"),
                "rank_scope": row.get("rank_scope"),
                "rolling_sharpe_30": row.get("rolling_sharpe_30"),
                "rolling_sharpe_90": row.get("rolling_sharpe_90"),
                "quartile": row.get("quartile"),
                "update_action": row.get("update_action"),
                "n_obs": row.get("n_obs"),
                "source_table": row.get("source_table"),
                "source_date": row.get("source_date"),
                "updated_at": row.get("updated_at"),
            }
            normalized_rows.append(normalized)
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO darwinian_weights (
                    cohort, agent, layer, date, weight, previous_weight,
                    performance_metric, performance_value, normalized_performance,
                    rank_scope, rolling_sharpe_30, rolling_sharpe_90, quartile,
                    update_action, n_obs, source_table, source_date, updated_at
                ) VALUES (
                    :cohort, :agent, :layer, :date, :weight, :previous_weight,
                    :performance_metric, :performance_value, :normalized_performance,
                    :rank_scope, :rolling_sharpe_30, :rolling_sharpe_90, :quartile,
                    :update_action, :n_obs, :source_table, :source_date, :updated_at
                )
                ON CONFLICT(cohort, agent, date) DO UPDATE SET
                    weight = excluded.weight,
                    layer = excluded.layer,
                    previous_weight = excluded.previous_weight,
                    performance_metric = excluded.performance_metric,
                    performance_value = excluded.performance_value,
                    normalized_performance = excluded.normalized_performance,
                    rank_scope = excluded.rank_scope,
                    rolling_sharpe_30 = excluded.rolling_sharpe_30,
                    rolling_sharpe_90 = excluded.rolling_sharpe_90,
                    quartile = excluded.quartile,
                    update_action = excluded.update_action,
                    n_obs = excluded.n_obs,
                    source_table = excluded.source_table,
                    source_date = excluded.source_date,
                    updated_at = excluded.updated_at
                """,
                normalized_rows,
            )
        return len(rows)

    def get_darwinian_weights(
        self,
        cohort: str,
        date: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> dict[str, dict[str, Any]]:
        """Return ``{agent: {weight, sharpe_30, sharpe_90, quartile}}``.

        If ``date`` is None, returns the latest row per (cohort, agent).
        """
        select_cols = (
            "agent, layer, weight, previous_weight, performance_metric, "
            "performance_value, normalized_performance, rank_scope, "
            "rolling_sharpe_30, rolling_sharpe_90, quartile, update_action, "
            "n_obs, source_table, source_date, updated_at"
        )
        if date:
            sql = (
                f"SELECT {select_cols} "
                "FROM darwinian_weights WHERE cohort = ? AND date = ?"
            )
            params: list[Any] = [cohort, date]
        else:
            sql = (
                f"SELECT {select_cols} "
                "FROM darwinian_weights w1 "
                "WHERE cohort = ? AND date = ("
                "  SELECT MAX(date) FROM darwinian_weights w2 "
                "  WHERE w2.cohort = w1.cohort AND w2.agent = w1.agent"
                + (" AND w2.date < ?" if before_date else "")
                + ")"
            )
            params = [cohort]
            if before_date:
                params.append(before_date)

        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return {
                row["agent"]: {
                    "weight": row["weight"],
                    "sharpe_30": row["rolling_sharpe_30"],
                    "sharpe_90": row["rolling_sharpe_90"],
                    "quartile": row["quartile"],
                    "layer": row["layer"],
                    "previous_weight": row["previous_weight"],
                    "performance_metric": row["performance_metric"],
                    "performance_value": row["performance_value"],
                    "normalized_performance": row["normalized_performance"],
                    "rank_scope": row["rank_scope"],
                    "update_action": row["update_action"],
                    "n_obs": row["n_obs"],
                    "source_table": row["source_table"],
                    "source_date": row["source_date"],
                    "updated_at": row["updated_at"],
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
        prompt_repo_id: Optional[str] = None,
        prompt_sha256: Optional[str] = None,
        code_commit_hash: Optional[str] = None,
    ) -> int:
        """Open a new backtest run row and return its id.

        Idempotent: legacy callers key by ``prompt_commit_hash``. Repo-aware
        callers also pass prompt repo/SHA/code metadata; those fields are folded
        into the persisted cache tag so independent code↔prompt pairs do not
        collide on the old unique constraint.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache_key = _backtest_cache_key(
            prompt_commit_hash,
            prompt_repo_id=prompt_repo_id,
            prompt_sha256=prompt_sha256,
            code_commit_hash=code_commit_hash,
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO backtest_runs (
                    cohort, start_date, end_date, prompt_commit_hash,
                    prompt_commit_ref, prompt_repo_id, prompt_sha256,
                    code_commit_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cohort, start_date, end_date, prompt_commit_hash)
                DO UPDATE SET created_at = created_at  -- no-op; preserves original timestamp
                RETURNING id
                """,
                (
                    cohort,
                    start_date,
                    end_date,
                    cache_key,
                    prompt_commit_hash,
                    prompt_repo_id,
                    prompt_sha256,
                    code_commit_hash,
                    now,
                ),
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
                "       prompt_commit_ref, prompt_repo_id, prompt_sha256, "
                "       code_commit_hash, created_at, completed_at "
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
            "       prompt_commit_ref, prompt_repo_id, prompt_sha256, "
            "       code_commit_hash, created_at, completed_at "
            "FROM backtest_runs WHERE 1=1"
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

    # ── backtest_failed_days (R-A3) ──────────────────────────────────────

    def record_backtest_failed_days(
        self, run_id: int, failures: list[tuple[str, str]]
    ) -> int:
        """Upsert ``(date, error)`` failures for ``run_id``. Idempotent on
        (run_id, date). Returns the number of rows written."""
        if not failures:
            return 0
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [(run_id, date, _truncate(error, 500) or "", now) for date, error in failures]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO backtest_failed_days (run_id, date, error, recorded_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, date) DO UPDATE SET
                    error = excluded.error,
                    recorded_at = excluded.recorded_at
                """,
                rows,
            )
        return len(rows)

    def get_backtest_failed_days(self, run_id: int) -> list[dict[str, Any]]:
        """Return ``[{date, error, recorded_at}]`` for ``run_id`` (date-sorted)."""
        with self._connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT date, error, recorded_at FROM backtest_failed_days "
                    "WHERE run_id = ? ORDER BY date",
                    (run_id,),
                ).fetchall()
            ]

    def clear_backtest_failed_days(
        self, run_id: int, dates: Optional[list[str]] = None
    ) -> int:
        """Delete failed-day rows for ``run_id``. ``dates=None`` clears all;
        otherwise only the given dates (e.g. ones that succeeded on retry).
        Returns the number of rows deleted."""
        with self._connect() as conn:
            if dates is None:
                cur = conn.execute(
                    "DELETE FROM backtest_failed_days WHERE run_id = ?", (run_id,)
                )
            elif not dates:
                return 0
            else:
                placeholders = ",".join("?" for _ in dates)
                cur = conn.execute(
                    f"DELETE FROM backtest_failed_days WHERE run_id = ? AND date IN ({placeholders})",
                    [run_id, *dates],
                )
            return cur.rowcount

    # ── prompt_versions (Phase 4 autoresearch, Plan §7 / §11.5 4A) ────────

    def create_prompt_version(
        self,
        *,
        cohort: str,
        agent: str,
        branch_name: str,
        base_commit_hash: str,
        code_commit_hash: Optional[str] = None,
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
                    code_commit_hash, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(branch_name) DO UPDATE SET branch_name = branch_name
                RETURNING id
                """,
                (
                    cohort,
                    agent,
                    branch_name,
                    base_commit_hash,
                    code_commit_hash or base_commit_hash,
                    created_at,
                ),
            )
            return int(cur.fetchone()["id"])

    def set_version_mutation(
        self,
        version_id: int,
        modification_commit_hash: str,
        modification_summary: Optional[str] = None,
        *,
        prompt_repo_id: Optional[str] = None,
        prompt_base_commit_hash: Optional[str] = None,
        prompt_sha256: Optional[str] = None,
        code_commit_hash: Optional[str] = None,
    ) -> None:
        """Back-fill the mutation commit + summary once the TS mutator has
        written and committed the rewrite (``autoresearch.record_mutation``)."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE prompt_versions
                SET modification_commit_hash = :mod,
                    modification_summary = :summary,
                    prompt_repo_id = COALESCE(:prompt_repo_id, prompt_repo_id),
                    prompt_base_commit_hash = COALESCE(:prompt_base_commit_hash, prompt_base_commit_hash),
                    prompt_sha256 = COALESCE(:prompt_sha256, prompt_sha256),
                    code_commit_hash = COALESCE(:code_commit_hash, code_commit_hash)
                WHERE id = :id
                """,
                {
                    "id": version_id,
                    "mod": modification_commit_hash,
                    "summary": _truncate(modification_summary, 1000),
                    "prompt_repo_id": prompt_repo_id,
                    "prompt_base_commit_hash": prompt_base_commit_hash,
                    "prompt_sha256": prompt_sha256,
                    "code_commit_hash": code_commit_hash,
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

    def mark_version_incompatible(
        self,
        version_id: int,
        detail: str,
        decided_at: Optional[str] = None,
    ) -> None:
        """Terminal transition for a code↔prompt compatibility failure."""
        decided_at = decided_at or _utcnow_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE prompt_versions
                SET status = 'incompatible',
                    decided_at = ?,
                    modification_summary = COALESCE(modification_summary, ?)
                WHERE id = ?
                """,
                (decided_at, _truncate(detail, 1000), version_id),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_version_incompatible: no prompt_version id=%s", version_id
                )

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

    def last_mutation_at_any(self, cohort: str, agents: Iterable[str]) -> Optional[str]:
        """Most recent prompt_version created_at across ``agents`` (any status).

        Feeds the macro-layer interval gate (autoresearch macro plan Phase 4)."""
        agents = list(agents)
        if not agents:
            return None
        placeholders = ",".join("?" for _ in agents)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT MAX(created_at) AS m FROM prompt_versions "
                f"WHERE cohort = ? AND agent IN ({placeholders})",
                (cohort, *agents),
            ).fetchone()
            return row["m"] if row and row["m"] else None

    def recently_reverted_agents(self, cohort: str, since_iso: str) -> set[str]:
        """Agents with a ``revert`` decision at/after ``since_iso`` (recent-revert
        penalty, autoresearch macro plan Phase 4)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT agent FROM prompt_versions "
                "WHERE cohort = ? AND status = 'revert' AND decided_at >= ?",
                (cohort, since_iso),
            ).fetchall()
            return {r["agent"] for r in rows}

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

    # ── mirofish_runs (Phase 7 MiroFish, Plan §11.8) ─────────────────────

    def record_mirofish_run(
        self,
        *,
        date: str,
        agent: str,
        scenario_type: str,
        n_scenarios: int,
        avg_score: Optional[float],
        detail_json: Optional[str] = None,
    ) -> int:
        """Upsert a synthetic forward-training run (idempotent on
        (date, agent, scenario_type))."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO mirofish_runs (
                    date, agent, scenario_type, n_scenarios, avg_score,
                    detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, agent, scenario_type) DO UPDATE SET
                    n_scenarios = excluded.n_scenarios,
                    avg_score = excluded.avg_score,
                    detail_json = excluded.detail_json,
                    created_at = excluded.created_at
                RETURNING id
                """,
                (date, agent, scenario_type, n_scenarios, avg_score,
                 _truncate(detail_json, 4000), _utcnow_iso()),
            )
            return int(cur.fetchone()["id"])

    def get_mirofish_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Return the most recent ``days`` mirofish_runs rows, newest first
        (row LIMIT, not a calendar window)."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM mirofish_runs ORDER BY date DESC, id DESC LIMIT ?", (days,)
            )
            return [dict(r) for r in cur.fetchall()]

    # ── mirofish_context (Phase 7M Step 1: scenario context for prompt feedback) ──

    def save_mirofish_context(self, *, date: str, context: dict[str, Any]) -> None:
        """Upsert the latest derived MiroFish scenario context for ``date``
        (one row per day; idempotent). ``context`` is the dict from
        ``derive_context`` — regime / csi300 / HCT / tail summary + detail."""
        import json as _json

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mirofish_context (
                    date, regime, csi300_return, hct_ticker, hct_direction,
                    tail_summary, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    regime = excluded.regime,
                    csi300_return = excluded.csi300_return,
                    hct_ticker = excluded.hct_ticker,
                    hct_direction = excluded.hct_direction,
                    tail_summary = excluded.tail_summary,
                    detail_json = excluded.detail_json,
                    created_at = excluded.created_at
                """,
                (
                    date,
                    context.get("regime"),
                    context.get("csi300_return"),
                    context.get("hct_ticker"),
                    context.get("hct_direction"),
                    context.get("tail_summary"),
                    _json.dumps(context, ensure_ascii=False),
                    _utcnow_iso(),
                ),
            )

    def get_latest_mirofish_context(
        self, as_of_date: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Return the most recent MiroFish context, or None. Shape = the full
        context ``save`` derived (merged from ``detail_json``) plus ``date`` and
        ``created_at`` provenance — so callers get one consistent dict, not a
        raw DB row, and never need to re-parse ``detail_json``.

        ``as_of_date`` (YYYY-MM-DD) bounds the lookup to ``date <= as_of_date``
        so a backtest replaying a historical cycle can't be handed a context
        generated for a later date (anti-lookahead, mirroring the project's
        date-bound discipline). When omitted, returns the newest row."""
        import json as _json

        sql = "SELECT * FROM mirofish_context"
        params: list[Any] = []
        if as_of_date:
            sql += " WHERE date <= ?"
            params.append(as_of_date)
        sql += " ORDER BY date DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        try:
            context = _json.loads(row["detail_json"]) if row["detail_json"] else {}
        except (ValueError, TypeError):
            context = {}
        context["date"] = row["date"]
        context["created_at"] = row["created_at"]
        return context




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


def _backtest_cache_key(
    prompt_commit_hash: str,
    *,
    prompt_repo_id: Optional[str] = None,
    prompt_sha256: Optional[str] = None,
    code_commit_hash: Optional[str] = None,
) -> str:
    if not any((prompt_repo_id, prompt_sha256, code_commit_hash)):
        return prompt_commit_hash
    parts = [
        prompt_repo_id or "unknown_repo",
        prompt_commit_hash,
        prompt_sha256 or "unknown_sha",
        code_commit_hash or "unknown_code",
    ]
    return "prompt-v2:" + ":".join(parts)


_LONG_ACTIONS = {"BUY", "LONG"}
_SHORT_ACTIONS = {"SELL", "SHORT", "REDUCE"}


def _action_sign(action: Optional[str]) -> int:
    """+1 long / -1 short / 0 neutral (HOLD/unknown) for win-rate direction."""
    a = (action or "").upper()
    if a in _LONG_ACTIONS:
        return 1
    if a in _SHORT_ACTIONS:
        return -1
    return 0
