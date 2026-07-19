"""SQLite persistence for daily-cycle agent recommendations (Plan §11.3 3A).

State → row expansion convention (Plan §11.3 3A design decisions):

    Layer 1 (10 macro agents)  → not persisted (no ticker; regime signals
                                  are inputs, not predictions).
    Layer 2 (10 sector agents) → 1 row per accepted security pick
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

import hashlib
import json
import logging
import math
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from mosaic.scorecard.macro_aggregation import MACRO_AGENTS as MACRO_AGENT_ORDER

logger = logging.getLogger(__name__)

# The v3 runtime has 28 logical agents and 29 accepted stages because CIO
# executes distinct proposal and final stages.  Keep the audit cardinality in
# one Python-side contract so bridge handlers and persistence cannot drift.
RUNTIME_AGENT_STAGE_COUNT = 29


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _display_clean(value: str) -> str:
    printable = "".join(
        character if character >= " " and character != "\x7f" else " "
        for character in value
    )
    normalized = " ".join(printable.split())
    return (
        normalized
        if len(normalized) <= 320
        else normalized[:319].rstrip() + "…"
    )


def _display_text(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return _display_clean(value)
    if (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    ):
        return format(value, ".15g")
    return "-"


def _display_pct(value: Any) -> str:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return "-"
    return f"{math.floor(float(value) * 100 + 0.5)}%"


def _display_objects(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _display_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _display_clean(item)
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _display_summaries(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(_display_clean(item))
        elif isinstance(item, Mapping):
            summary = item.get("summary")
            if isinstance(summary, str) and summary.strip():
                result.append(_display_clean(summary))
    return result


def _display_section(language: str, en: str, zh: str, values: list[str]) -> str:
    if not values:
        return ""
    return (
        f"{zh}：{'；'.join(values)}。"
        if language == "zh"
        else f"{en}: {'; '.join(values)}."
    )


def _display_claims(output: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for claim in _display_objects(output.get("claims")):
        statement = claim.get("statement")
        if isinstance(statement, str) and statement.strip():
            result.append(_display_clean(statement))
    return result


def _display_picks(value: Any, language: str) -> list[str]:
    result: list[str] = []
    for item in _display_objects(value):
        ticker = item.get("ts_code") or item.get("ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            continue
        action = item.get("position_action")
        conviction = item.get("conviction")
        thesis = item.get("thesis")
        text = _display_clean(ticker)
        if isinstance(action, str):
            text += f" {action}"
        if not isinstance(conviction, bool) and isinstance(conviction, (int, float)):
            text += f" {_display_pct(conviction)}"
        if isinstance(thesis, str):
            text += ("：" if language == "zh" else ": ") + _display_clean(thesis)
        result.append(text)
    return result


def _display_reason_items(value: Any) -> list[str]:
    result: list[str] = []
    for item in _display_objects(value):
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            continue
        ticker = item.get("ts_code") or item.get("ticker")
        prefix = f"{_display_clean(ticker)} " if isinstance(ticker, str) else ""
        result.append(prefix + _display_clean(reason))
    return result


def _display_risk_actions(value: Any) -> list[str]:
    result: list[str] = []
    for item in _display_objects(value):
        ticker = item.get("ts_code") or item.get("ticker")
        action = item.get("action")
        reason = item.get("reason")
        parts = [
            _display_clean(ticker) if isinstance(ticker, str) else "",
            _display_clean(action) if isinstance(action, str) else "",
            _display_clean(reason) if isinstance(reason, str) else "",
        ]
        rendered = " ".join(part for part in parts if part)
        if rendered:
            result.append(rendered)
    return result


def _display_direction_name(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "-"
    return _display_text(value.get("direction_id") or value.get("status"))


def _display_direction_thesis(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    thesis = value.get("thesis")
    return [_display_clean(thesis)] if isinstance(thesis, str) and thesis.strip() else []


def _display_relationships(value: Any, language: str) -> list[str]:
    result: list[str] = []
    for item in _display_objects(value):
        source = item.get("source_entity")
        target = item.get("target_entity")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        trigger = item.get("activation_trigger")
        suffix = (
            ("；触发条件：" if language == "zh" else "; trigger: ")
            + _display_clean(trigger)
            if isinstance(trigger, str)
            else ""
        )
        result.append(
            f"{_display_clean(source)} → {_display_clean(target)} "
            f"({_display_text(item.get('transmission_direction'))}){suffix}"
        )
    return result


def _accepted_display_projection(
    *,
    agent_id: str,
    accepted_output_kind: str | None,
    output: Mapping[str, Any],
) -> Mapping[str, Any]:
    nested_field = {
        "STANDARD_SECTOR_SELECTION": "selection",
        "SUPERINVESTOR_SELECTION": "selection",
        "CRO_RISK_REVIEW": "review",
        "ALPHA_DISCOVERY": "selection",
        "EXECUTION_ASSESSMENT": "assessment",
        "CIO_PROPOSAL": "decision",
        "CIO_FINAL": "decision",
    }.get(accepted_output_kind)
    if nested_field is None:
        return output
    nested = output.get(nested_field)
    if not isinstance(nested, Mapping):
        raise ValueError(f"{agent_id}: accepted display payload lacks {nested_field}")
    return {
        **nested,
        "confidence": output.get(
            "model_confidence", output.get("directional_confidence")
        ),
    }


def render_agent_display_narrative_text(
    *,
    layer: str,
    agent_id: str,
    output: Mapping[str, Any],
    language: str,
    accepted_output_kind: str | None = None,
) -> str:
    """Trusted Python mirror of the TypeScript UI projection contract."""
    output = _accepted_display_projection(
        agent_id=agent_id,
        accepted_output_kind=accepted_output_kind,
        output=output,
    )
    if layer == "macro":
        parts = [
            (
                f"结论：{_display_text(output.get('direction'))}，强度 "
                f"{_display_text(output.get('strength'))}/5，周期 "
                f"{_display_text(output.get('persistence_horizon'))}，置信度 "
                f"{_display_pct(output.get('confidence'))}。"
                if language == "zh"
                else f"Decision: {_display_text(output.get('direction'))}, strength "
                f"{_display_text(output.get('strength'))}/5, horizon "
                f"{_display_text(output.get('persistence_horizon'))}, confidence "
                f"{_display_pct(output.get('confidence'))}."
            ),
            _display_section(
                language,
                "Transmission",
                "传导渠道",
                _display_strings(output.get("channels"))[:5],
            ),
            _display_section(
                language,
                "Drivers",
                "主要驱动",
                _display_summaries(output.get("key_drivers"))[:4],
            ),
        ]
    elif layer == "sector" and agent_id == "relationship_mapper":
        factual = len(_display_objects(output.get("factual_edges")))
        predictive = len(_display_objects(output.get("predictive_edges")))
        status = _display_text(output.get("predictive_graph_status"))
        parts = [
            (
                f"结论：{status}；事实关系 {factual} 条，可评价预测关系 {predictive} 条。"
                if language == "zh"
                else f"Decision: {status}; {factual} factual and {predictive} evaluable predictive relationships."
            ),
            _display_section(
                language,
                "Predictive links",
                "预测关系",
                _display_relationships(output.get("predictive_edges"), language)[:4],
            ),
            _display_section(
                language,
                "Drivers",
                "主要驱动",
                _display_summaries(output.get("key_drivers"))[:4],
            ),
            _display_section(
                language,
                "Risks",
                "主要风险",
                _display_summaries(output.get("risks"))[:3],
            ),
        ]
    elif layer == "sector":
        preferred = _display_direction_name(output.get("preferred_direction"))
        least = _display_direction_name(output.get("least_preferred_direction"))
        parts = [
            (
                f"结论：最看好 {preferred}，最不看好 {least}，周期 "
                f"{_display_text(output.get('persistence_horizon'))}，置信度 "
                f"{_display_pct(output.get('confidence'))}。"
                if language == "zh"
                else f"Decision: preferred {preferred}, least preferred {least}, horizon "
                f"{_display_text(output.get('persistence_horizon'))}, confidence "
                f"{_display_pct(output.get('confidence'))}."
            ),
            _display_section(
                language,
                "Drivers",
                "主要驱动",
                _display_summaries(output.get("key_drivers"))[:4],
            ),
            _display_section(
                language,
                "Preferred rationale",
                "看好逻辑",
                _display_direction_thesis(output.get("preferred_direction")),
            ),
            _display_section(
                language,
                "Least-preferred rationale",
                "看空逻辑",
                _display_direction_thesis(output.get("least_preferred_direction")),
            ),
            _display_section(
                language,
                "Long candidates",
                "看好标的",
                _display_picks(output.get("long_picks"), language)[:5],
            ),
            _display_section(
                language,
                "Short or avoid",
                "看空或回避",
                _display_picks(output.get("short_or_avoid_picks"), language)[:5],
            ),
            _display_section(
                language,
                "Risks",
                "主要风险",
                _display_summaries(output.get("risks"))[:3],
            ),
        ]
    elif layer == "superinvestor":
        parts = [
            (
                f"结论：{_display_text(output.get('selection_status'))}，持有期 "
                f"{_display_text(output.get('holding_period'))}，置信度 "
                f"{_display_pct(output.get('confidence'))}。"
                if language == "zh"
                else f"Decision: {_display_text(output.get('selection_status'))}, holding period "
                f"{_display_text(output.get('holding_period'))}, confidence "
                f"{_display_pct(output.get('confidence'))}."
            ),
            _display_section(
                language,
                "Drivers",
                "主要驱动",
                _display_summaries(output.get("key_drivers"))[:4],
            ),
            _display_section(
                language,
                "Candidates",
                "候选标的",
                _display_picks(output.get("picks"), language)[:6],
            ),
            _display_section(
                language,
                "Risks",
                "主要风险",
                _display_summaries(output.get("risks"))[:3],
            ),
        ]
    else:
        parts = _render_decision_display_parts(agent_id, output, language)
    claims = _display_claims(output)[:3]
    if claims:
        parts.append(_display_section(language, "Evidence", "证据结论", claims))
    text = "\n".join(part for part in parts if part)
    return text if len(text) <= 2_000 else text[:1_999].rstrip() + "…"


def _render_decision_display_parts(
    agent_id: str, output: Mapping[str, Any], language: str
) -> list[str]:
    if agent_id == "cro":
        actions = output.get("candidate_actions", output.get("rejected_picks"))
        action_count = len(_display_objects(actions))
        return [
            (
                f"结论：{_display_text(output.get('review_disposition'))}，风险处置 {action_count} 项，"
                f"置信度 {_display_pct(output.get('confidence'))}。"
                if language == "zh"
                else f"Decision: {_display_text(output.get('review_disposition'))}, "
                f"{action_count} risk actions, confidence {_display_pct(output.get('confidence'))}."
            ),
            _display_section(
                language,
                "Risk actions",
                "风险处置",
                _display_risk_actions(actions)[:5],
            ),
            _display_section(
                language,
                "Required adjustments",
                "必要调整",
                _display_reason_items(output.get("required_adjustments"))[:5],
            ),
            _display_section(
                language,
                "Correlated risks",
                "相关风险",
                _display_summaries(output.get("correlated_risks"))[:4],
            ),
            _display_section(
                language,
                "Black swans",
                "黑天鹅情景",
                _display_summaries(output.get("black_swan_scenarios"))[:3],
            ),
        ]
    if agent_id == "alpha_discovery":
        picks = _display_objects(output.get("novel_picks"))
        rendered = []
        for item in picks:
            ticker = item.get("ts_code") or item.get("ticker")
            if not isinstance(ticker, str):
                continue
            why = item.get("thesis") or item.get("why_missed_by_others")
            rendered.append(
                _display_clean(ticker)
                + (
                    ("：" if language == "zh" else ": ") + _display_clean(why)
                    if isinstance(why, str) and why
                    else ""
                )
            )
        return [
            (
                f"结论：{_display_text(output.get('discovery_disposition'))}，发现 "
                f"{len(picks)} 个增量候选，置信度 {_display_pct(output.get('confidence'))}。"
                if language == "zh"
                else f"Decision: {_display_text(output.get('discovery_disposition'))}, "
                f"{len(picks)} incremental candidates, confidence "
                f"{_display_pct(output.get('confidence'))}."
            ),
            _display_section(language, "Candidates", "增量候选", rendered[:6]),
        ]
    if agent_id == "autonomous_execution":
        assessments = _display_objects(
            output.get("order_assessments", output.get("trades"))
        )
        rendered = []
        for item in assessments:
            ticker = item.get("ts_code") or item.get("ticker")
            if not isinstance(ticker, str):
                continue
            if isinstance(item.get("feasibility"), str):
                delta = item.get("requested_delta_weight")
                cost = item.get("predicted_cost_bps")
                reason = item.get("reason")
                rendered.append(
                    (
                        f"{_display_clean(ticker)} {_display_clean(item['feasibility'])}"
                        + (
                            f" {_display_pct(delta)}"
                            if not isinstance(delta, bool)
                            and isinstance(delta, (int, float))
                            else ""
                        )
                        + (
                            f" {_display_text(cost)}bps"
                            if not isinstance(cost, bool)
                            and isinstance(cost, (int, float))
                            else ""
                        )
                        + (
                            f": {_display_clean(reason)}"
                            if isinstance(reason, str)
                            else ""
                        )
                    )
                )
                continue
            size = item.get("size_pct")
            rendered_trade = (
                f"{_display_clean(ticker)} {_display_text(item.get('action'))} "
                f"{_display_pct(size) if not isinstance(size, bool) and isinstance(size, (int, float)) else ''}"
            )
            rendered.append(rendered_trade.strip())
        return [
            (
                f"结论：{_display_text(output.get('execution_disposition'))}，订单评估 "
                f"{len(assessments)} 笔，置信度 {_display_pct(output.get('confidence'))}。"
                if language == "zh"
                else f"Decision: {_display_text(output.get('execution_disposition'))}, "
                f"{len(assessments)} order assessments, confidence "
                f"{_display_pct(output.get('confidence'))}."
            ),
            _display_section(
                language, "Order assessments", "订单评估", rendered[:8]
            ),
            _display_section(
                language,
                "Checks",
                "执行检查",
                _display_reason_items(output.get("execution_checks"))[:5],
            ),
        ]
    actions = _display_objects(
        output.get("target_positions", output.get("portfolio_actions"))
    )
    rendered_actions = []
    for item in actions:
        ticker = item.get("ts_code") or item.get("ticker")
        if not isinstance(ticker, str):
            continue
        target = item.get("target_weight")
        target_text = (
            _display_pct(target)
            if not isinstance(target, bool) and isinstance(target, (int, float))
            else "-"
        )
        reason = item.get("position_decision_reason")
        rendered_actions.append(
            f"{_display_clean(ticker)} "
            f"{_display_text(item.get('position_decision') or item.get('action'))} "
            f"→ {target_text}"
            + (
                ("：" if language == "zh" else ": ") + _display_clean(reason)
                if isinstance(reason, str)
                else ""
            )
        )
    decision_reason = output.get("decision_reason")
    optional_reason = (
        " " + _display_clean(decision_reason)
        if isinstance(decision_reason, str) and decision_reason.strip()
        else ""
    )
    return [
        (
            f"结论：{_display_text(output.get('decision_disposition'))}，目标持仓 "
            f"{len(actions)} 项，置信度 {_display_pct(output.get('confidence'))}。"
            f"{optional_reason}"
            if language == "zh"
            else f"Decision: {_display_text(output.get('decision_disposition'))}, "
            f"{len(actions)} target positions, confidence "
            f"{_display_pct(output.get('confidence'))}.{optional_reason}"
        ),
        _display_section(language, "Portfolio", "组合动作", rendered_actions[:10]),
    ]

# Resolve <repoRoot>/data/scorecard.db at import time.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EXECUTION_BEHAVIOR_RELEASE_PATH = (
    _REPO_ROOT
    / "registry"
    / "prompt_checks"
    / "execution_behavior_release_manifest_v1.json"
)
_EXECUTION_BEHAVIOR_RELEASE_ARCHIVE_ROOT = (
    _REPO_ROOT
    / "registry"
    / "prompt_checks"
    / "execution_behavior_releases"
)
DEFAULT_DB_PATH = (
    Path(os.getenv("MOSAIC_DATA_DIR", str(_REPO_ROOT / "data"))) / "scorecard.db"
)


def _load_trusted_execution_behavior_release(
    expected_release_id: str,
) -> dict[str, Any]:
    """Load one immutable, hash-valid release archive by exact release ID."""
    from mosaic.scorecard.darwinian_v2 import canonical_hash

    prefix = "execution-behavior-release:"
    if (
        not isinstance(expected_release_id, str)
        or not expected_release_id.startswith(prefix)
        or len(expected_release_id) != len(prefix) + 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_release_id[len(prefix) :]
        )
    ):
        raise ValueError("execution behavior release ID is invalid")
    release_digest = expected_release_id[len(prefix) :]
    archive_root = _EXECUTION_BEHAVIOR_RELEASE_ARCHIVE_ROOT.resolve()
    try:
        candidates = sorted(
            path.resolve()
            for path in archive_root.glob(f"{release_digest}--*.json")
            if path.is_file()
        )
    except OSError as exc:
        raise ValueError("trusted execution behavior release is unavailable") from exc
    if len(candidates) != 1:
        detail = "unavailable" if not candidates else "ambiguous"
        raise ValueError(f"trusted execution behavior release is {detail}")
    release_path = candidates[0]
    if not release_path.is_relative_to(archive_root):
        raise ValueError("trusted execution behavior release escaped its archive")
    try:
        value = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("trusted execution behavior release is unavailable") from exc
    if not isinstance(value, dict):
        raise ValueError("trusted execution behavior release must be an object")
    supplied_hash = value.get("execution_behavior_release_hash")
    body = {
        key: item
        for key, item in value.items()
        if key != "execution_behavior_release_hash"
    }
    if not _is_sha256(supplied_hash) or supplied_hash != canonical_hash(body):
        raise ValueError("trusted execution behavior release hash mismatch")
    if value.get("execution_behavior_release_id") != expected_release_id:
        raise ValueError("trusted execution behavior release ID mismatch")
    release_content = {
        key: item
        for key, item in value.items()
        if key
        not in {
            "execution_behavior_release_id",
            "execution_behavior_release_hash",
        }
    }
    derived_release_id = (
        f"{prefix}{canonical_hash(release_content).removeprefix('sha256:')}"
    )
    if derived_release_id != expected_release_id:
        raise ValueError("trusted execution behavior release ID hash mismatch")
    expected_filename = (
        f"{release_digest}--{supplied_hash.removeprefix('sha256:')}.json"
    )
    if release_path.name != expected_filename:
        raise ValueError("trusted execution behavior release archive name mismatch")
    if (
        value.get("schema_version")
        != "execution_behavior_release_manifest_v1"
        or
        not isinstance(value.get("private_prompt_commit"), str)
        or not isinstance(value.get("provider_binding"), dict)
        or not isinstance(value.get("active_production_variants"), list)
        or not isinstance(value.get("variants"), list)
        or not value["variants"]
    ):
        raise ValueError("trusted execution behavior release is incomplete")
    return value

_DOMAIN_MUTATION_LIFECYCLE_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"proposed"},
    "proposed": {"validated", "invalid"},
    "validated": {"shadow_evaluating", "invalid"},
    "shadow_evaluating": {
        "needs_fill",
        "eligible_for_promotion",
        "reverted",
        "invalid",
    },
    "needs_fill": {"shadow_evaluating", "invalid"},
    "eligible_for_promotion": {"kept", "reverted"},
    "kept": set(),
    "reverted": set(),
    "invalid": set(),
}

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
    current_weight_pct REAL,                    -- CIO only: current portfolio weight [0, 100]
    delta_weight_pct REAL,                      -- CIO only: target-current [percentage points]
    position_decision TEXT,                     -- CIO only: HOLD/ADD/REDUCE/EXIT
    position_decision_reason TEXT,
    override_reason TEXT,
    thesis_status TEXT,                         -- CIO only: intact/weakened/broken/expired
    risk_flags_json TEXT,                       -- JSON array of CIO position risk flags
    declared_knob_influence_ids_json TEXT,      -- legacy audit only; new writes are NULL
    declared_influence_rationale TEXT,          -- legacy audit only; new writes are NULL
    verified_knob_audit_json TEXT,              -- stores the value-free private KNOT audit
    decision_agent_audits_json TEXT,            -- compact CRO/execution/CIO audit summary
    dissent_notes TEXT,
    rationale_snapshot TEXT,
    replay_triggered INTEGER NOT NULL DEFAULT 0,  -- 1 = produced by a CRO-veto replay cycle (R-A1)
    day_outcome_status TEXT NOT NULL DEFAULT 'legacy_unverified',
    backtest_run_id INTEGER,
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

-- Human-readable projections of accepted Agent outputs.  This is a UI-only
-- sidecar: no Darwinian/KNOT or downstream Agent query reads this table.
CREATE TABLE IF NOT EXISTS agent_display_narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cohort TEXT NOT NULL,
    date TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    bundle_hash TEXT NOT NULL,
    agent TEXT NOT NULL,
    layer TEXT NOT NULL CHECK(layer IN ('macro', 'sector', 'superinvestor', 'decision')),
    language TEXT NOT NULL CHECK(language IN ('zh', 'en')),
    source TEXT NOT NULL CHECK(source IN (
        'ACCEPTED_OUTPUT', 'NO_EVALUATION_OBJECT', 'NON_PRODUCTION_STRUCTURED_OUTPUT'
    )),
    source_output_id TEXT,
    source_output_hash TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    narrative_text TEXT NOT NULL,
    ui_only INTEGER NOT NULL CHECK(ui_only = 1),
    created_at TEXT NOT NULL,
    UNIQUE(cohort, date, trace_id, agent)
);

CREATE INDEX IF NOT EXISTS idx_agent_display_narratives_latest
    ON agent_display_narratives(cohort, created_at DESC, id DESC);

CREATE TRIGGER IF NOT EXISTS agent_display_narratives_no_update
    BEFORE UPDATE ON agent_display_narratives BEGIN
        SELECT RAISE(ABORT, 'agent_display_narratives is append-only');
    END;

CREATE TRIGGER IF NOT EXISTS agent_display_narratives_no_delete
    BEFORE DELETE ON agent_display_narratives BEGIN
        SELECT RAISE(ABORT, 'agent_display_narratives is append-only');
    END;

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

CREATE TABLE IF NOT EXISTS agent_run_outcomes (
    run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    agent TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('accepted', 'accepted_empty', 'rejected', 'timeout', 'error')),
    output_source TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    repair_count INTEGER NOT NULL,
    stop_reason TEXT NOT NULL,
    audit_json TEXT NOT NULL,
    PRIMARY KEY (run_id, trade_date, agent, stage)
);

CREATE TABLE IF NOT EXISTS backtest_day_outcomes (
    run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('accepted', 'failed_no_decision', 'legacy_unverified')),
    decision_disposition TEXT,
    action_count INTEGER NOT NULL,
    accepted_at TEXT,
    PRIMARY KEY (run_id, trade_date)
);

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
    mutation_id TEXT,                           -- stable parameter-mutation identifier
    transaction_id TEXT,                        -- candidate artifact transaction identifier
    experiment_id TEXT,                         -- preregistered evaluation episode identifier
    mutation_metadata_json TEXT,                -- hash-bound knob/card/evaluation policy
    mutation_lifecycle TEXT,                    -- proposed/validated/shadow_evaluating/...
    evaluation_result_json TEXT,                -- card-bound PIT EvaluationResult
    promotion_decision_json TEXT,               -- authorized keep/revert evidence
    promotion_decision_hash TEXT,
    promotion_approved_by TEXT,
    promotion_approval_policy_id TEXT,
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

CREATE TABLE IF NOT EXISTS domain_holdout_consumptions (
    holdout_id TEXT PRIMARY KEY,                -- preregistered untouched holdout hash
    mutation_id TEXT NOT NULL,
    prompt_version_id INTEGER NOT NULL,
    result_hash TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    UNIQUE(mutation_id, holdout_id)
);

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
    signal REAL,                              -- direction_sign * strength / 5
    confidence REAL,
    raw_output_json TEXT,                        -- original structured macro output
    consensus_stance TEXT,                       -- Layer 1 aggregate stance that day
    consensus_score REAL,
    label_type TEXT,                             -- e.g. benchmark_5d / benchmark_fallback_5d
    label_source_status TEXT,                    -- primary / fallback / missing / deferred
    label_value_5d REAL,                         -- raw value of the scoring label
    terminal_return_5d REAL,
    max_drawdown_5d REAL,
    realized_volatility_5d REAL,
    path_metric_5d REAL,
    benchmark_return_5d REAL,
    source_series_id TEXT,
    realized_label INTEGER CHECK (realized_label IN (-1, 0, 1)),
    hit_5d INTEGER,                              -- 1 if vote == realized_label
    raw_macro_score_5d REAL,                     -- MVP primary score
    influence_weight_equal REAL,                 -- diagnostics (Phase 8)
    effective_macro_score_5d REAL,               -- diagnostics (Phase 8)
    prompt_repo_id TEXT,
    prompt_sha256 TEXT,
    day_outcome_status TEXT NOT NULL DEFAULT 'legacy_unverified',
    backtest_run_id INTEGER,
    scored_at TEXT,                              -- NULL until the 5d window matures
    UNIQUE(cohort, agent, date)
);

CREATE TABLE IF NOT EXISTS macro_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL,
    source TEXT NOT NULL,
    endpoint_name TEXT,
    instrument TEXT,
    date TEXT NOT NULL,
    value REAL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    metadata_json TEXT,
    fetched_at TEXT,
    as_of_date TEXT NOT NULL,
    UNIQUE(series_id, date, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_macro_series_series_date
    ON macro_series(series_id, date, as_of_date);

CREATE TABLE IF NOT EXISTS macro_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    source TEXT NOT NULL,
    channel TEXT,
    query TEXT,
    title TEXT,
    url TEXT,
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content_excerpt TEXT,
    agent_tags_json TEXT,
    event_tags_json TEXT,
    sentiment_score REAL,
    quality_score REAL,
    UNIQUE(content_hash, discovered_at)
);

CREATE INDEX IF NOT EXISTS idx_macro_documents_discovered
    ON macro_documents(discovered_at);

CREATE TABLE IF NOT EXISTS macro_label_sources (
    agent TEXT NOT NULL,
    label_type TEXT NOT NULL,
    primary_series_id TEXT,
    proxy_series_ids_json TEXT,
    orientation_rule TEXT,
    lookback_days INTEGER,
    forward_horizon_trading_days INTEGER,
    fallback_label TEXT,
    availability_status TEXT,
    implementation_status TEXT,
    updated_at TEXT,
    PRIMARY KEY(agent, label_type)
);

-- Macro Agent role-contracts v2: namespace-safe append-only Darwinian ledgers.
-- The legacy darwinian_weights table remains readable for historical audits,
-- but production v2 readers use only the tables below.
CREATE TABLE IF NOT EXISTS darwinian_v2_evaluation_tracks (
    track_key_hash TEXT PRIMARY KEY,
    production_variant_roster_id TEXT NOT NULL,
    first_registered_roster_revision_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    agent_id TEXT NOT NULL,
    darwin_application_mode TEXT NOT NULL CHECK(
        darwin_application_mode IN ('DOWNSTREAM_USAGE_WEIGHT', 'EVOLUTION_ONLY')
    ),
    agent_contract_version TEXT NOT NULL,
    prompt_behavior_version TEXT NOT NULL,
    execution_behavior_version TEXT NOT NULL,
    component_weight_contract_version TEXT,
    reliability_adapter_contract_version TEXT,
    confidence_semantics_contract_version TEXT,
    outcome_contract_version TEXT NOT NULL,
    scoring_contract_version TEXT NOT NULL,
    sample_schedule_contract_version TEXT NOT NULL,
    rank_scope_contract_version TEXT NOT NULL,
    rank_scope TEXT NOT NULL,
    primary_label_id TEXT NOT NULL,
    contract_json TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    UNIQUE(
        production_variant_roster_id, cohort_id, language, agent_id,
        agent_contract_version, prompt_behavior_version, execution_behavior_version,
        component_weight_contract_version, reliability_adapter_contract_version,
        confidence_semantics_contract_version, outcome_contract_version,
        scoring_contract_version, sample_schedule_contract_version,
        rank_scope_contract_version, rank_scope, primary_label_id,
        darwin_application_mode
    )
);

CREATE TABLE IF NOT EXISTS darwinian_v2_usage_tracks (
    usage_track_key_hash TEXT PRIMARY KEY,
    production_variant_roster_id TEXT NOT NULL,
    evaluation_track_key_hash TEXT NOT NULL UNIQUE REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS darwinian_v2_production_variant_roster_revisions (
    production_variant_roster_revision_id TEXT PRIMARY KEY,
    production_variant_roster_revision_hash TEXT NOT NULL UNIQUE,
    production_variant_roster_id TEXT NOT NULL,
    execution_behavior_release_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    evaluation_track_key_hashes_json TEXT NOT NULL,
    usage_track_key_hashes_json TEXT NOT NULL,
    decision_evaluation_track_key_hashes_json TEXT NOT NULL,
    readiness TEXT NOT NULL CHECK(readiness IN ('READY', 'REJECTED')),
    prepared_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    effective_slot_sequence INTEGER NOT NULL CHECK(effective_slot_sequence >= 1),
    record_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_darwin_v2_roster_effective
    ON darwinian_v2_production_variant_roster_revisions(
        production_variant_roster_id, effective_at
    );

CREATE TABLE IF NOT EXISTS darwinian_v2_usage_weight_records (
    weight_record_id TEXT PRIMARY KEY,
    weight_record_hash TEXT NOT NULL UNIQUE,
    usage_track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_usage_tracks(usage_track_key_hash),
    record_kind TEXT NOT NULL CHECK(record_kind IN ('COLD_START_INITIALIZATION', 'MATURE_UPDATE')),
    darwin_weight REAL NOT NULL CHECK(darwin_weight >= 0.3 AND darwin_weight <= 2.5),
    previous_weight_record_id TEXT REFERENCES darwinian_v2_usage_weight_records(weight_record_id),
    n_eligible_scores INTEGER NOT NULL CHECK(n_eligible_scores >= 0),
    scoring_window_hash TEXT NOT NULL,
    update_event_id TEXT,
    effective_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(usage_track_key_hash, record_kind, update_event_id)
);

CREATE INDEX IF NOT EXISTS idx_darwin_v2_weight_effective
    ON darwinian_v2_usage_weight_records(usage_track_key_hash, effective_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_darwin_v2_one_cold_start
    ON darwinian_v2_usage_weight_records(usage_track_key_hash)
    WHERE record_kind = 'COLD_START_INITIALIZATION';

CREATE TABLE IF NOT EXISTS accepted_agent_outputs_v2 (
    accepted_output_id TEXT PRIMARY KEY,
    accepted_output_hash TEXT NOT NULL UNIQUE,
    graph_run_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_slot_id TEXT NOT NULL,
    operational_opportunity_audit_id TEXT NOT NULL,
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL REFERENCES darwinian_v2_production_variant_roster_revisions(production_variant_roster_revision_id),
    execution_behavior_release_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    accepted_output_kind TEXT NOT NULL,
    sample_origin TEXT NOT NULL CHECK(sample_origin IN (
        'PRODUCTION_ACTIVE', 'KNOT_RESEARCH_SHADOW',
        'KNOT_POST_PROMOTION_CHAMPION_SHADOW', 'KNOT_CONTROL_SHADOW'
    )),
    run_slot_kind TEXT NOT NULL CHECK(run_slot_kind IN ('OUTCOME_SCHEDULED', 'DOWNSTREAM_ONLY')),
    scheduled_sample_id TEXT,
    knot_pair_id TEXT,
    knot_pair_input_hash TEXT,
    research_pair_side TEXT CHECK(research_pair_side IN ('CHAMPION', 'CANDIDATE')),
    capability_id TEXT,
    capability_signature_hash TEXT,
    snapshot_bundle_id TEXT,
    snapshot_bundle_hash TEXT,
    runtime_input_hash TEXT,
    prompt_behavior_version TEXT,
    execution_behavior_version TEXT,
    evaluation_object_hash TEXT,
    as_of TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(operational_opportunity_audit_id, accepted_output_kind)
);

CREATE TABLE IF NOT EXISTS operational_opportunity_audits_v2 (
    operational_opportunity_audit_id TEXT PRIMARY KEY,
    operational_opportunity_audit_hash TEXT NOT NULL UNIQUE,
    graph_run_id TEXT NOT NULL,
    run_slot_id TEXT NOT NULL,
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL REFERENCES darwinian_v2_production_variant_roster_revisions(production_variant_roster_revision_id),
    execution_behavior_release_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    agent_id TEXT NOT NULL,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    sample_origin TEXT NOT NULL,
    run_slot_kind TEXT NOT NULL CHECK(run_slot_kind IN ('OUTCOME_SCHEDULED', 'DOWNSTREAM_ONLY')),
    scheduled_sample_id TEXT,
    knot_pair_id TEXT,
    knot_pair_input_hash TEXT,
    research_pair_side TEXT CHECK(research_pair_side IN ('CHAMPION', 'CANDIDATE')),
    capability_id TEXT,
    capability_signature_hash TEXT,
    snapshot_bundle_id TEXT,
    snapshot_bundle_hash TEXT,
    runtime_input_hash TEXT,
    prompt_behavior_version TEXT,
    execution_behavior_version TEXT,
    evaluation_object_hash TEXT,
    production_reliability_eligible INTEGER NOT NULL CHECK(production_reliability_eligible IN (0, 1)),
    disposition TEXT NOT NULL CHECK(disposition IN (
        'ACCEPTED', 'AGENT_FAILURE', 'EXOGENOUS_EXCLUSION',
        'NO_EVALUATION_OBJECT', 'DEPENDENCY_BLOCKED'
    )),
    accountable INTEGER NOT NULL CHECK(accountable IN (0, 1)),
    run_id TEXT,
    accepted_output_id TEXT REFERENCES accepted_agent_outputs_v2(accepted_output_id),
    failure_reason TEXT,
    fallback_used INTEGER NOT NULL CHECK(fallback_used IN (0, 1)),
    as_of TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operational_v2_reliability
    ON operational_opportunity_audits_v2(
        track_key_hash, production_reliability_eligible, accountable, recorded_at
    );

CREATE TABLE IF NOT EXISTS darwinian_v2_operational_reliability_records (
    reliability_record_id TEXT PRIMARY KEY,
    reliability_record_hash TEXT NOT NULL UNIQUE,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    cutoff_at TEXT NOT NULL,
    window_size INTEGER NOT NULL CHECK(window_size >= 0 AND window_size <= 30),
    accepted_count INTEGER NOT NULL CHECK(accepted_count >= 0),
    accountable_count INTEGER NOT NULL CHECK(accountable_count >= 0),
    operational_reliability REAL NOT NULL CHECK(operational_reliability >= 0 AND operational_reliability <= 1),
    reliability_state TEXT NOT NULL CHECK(reliability_state IN ('COLD_START', 'OBSERVED')),
    opportunity_set_hash TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(track_key_hash, cutoff_at, opportunity_set_hash)
);

CREATE TABLE IF NOT EXISTS agent_outcome_eligibility_revisions_v2 (
    audit_revision_id TEXT PRIMARY KEY,
    audit_revision_hash TEXT NOT NULL UNIQUE,
    audit_id TEXT NOT NULL,
    supersedes_revision_id TEXT REFERENCES agent_outcome_eligibility_revisions_v2(audit_revision_id),
    scheduled_sample_id TEXT NOT NULL,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    sample_origin TEXT NOT NULL,
    research_pair_side TEXT CHECK(research_pair_side IN ('CHAMPION', 'CANDIDATE')),
    knot_pair_id TEXT,
    knot_pair_input_hash TEXT,
    capability_id TEXT,
    capability_signature_hash TEXT,
    snapshot_bundle_id TEXT,
    snapshot_bundle_hash TEXT,
    runtime_input_hash TEXT,
    prompt_behavior_version TEXT,
    execution_behavior_version TEXT,
    evaluation_object_hash TEXT,
    accepted_output_hash TEXT,
    operational_opportunity_audit_id TEXT,
    operational_opportunity_audit_hash TEXT,
    disposition TEXT NOT NULL CHECK(disposition IN (
        'PENDING', 'SCORE', 'AGENT_FAILURE', 'EXOGENOUS_EXCLUSION'
    )),
    accepted_output_id TEXT REFERENCES accepted_agent_outputs_v2(accepted_output_id),
    opportunity_set_status TEXT NOT NULL CHECK(opportunity_set_status IN ('AVAILABLE', 'UNAVAILABLE')),
    audit_sequence INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(audit_id, audit_sequence)
);

CREATE TABLE IF NOT EXISTS evaluation_opportunity_sets_v2 (
    evaluation_opportunity_set_id TEXT PRIMARY KEY,
    evaluation_opportunity_set_hash TEXT NOT NULL UNIQUE,
    scheduled_sample_id TEXT NOT NULL UNIQUE,
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL REFERENCES darwinian_v2_production_variant_roster_revisions(production_variant_roster_revision_id),
    execution_behavior_release_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    sample_origin TEXT NOT NULL,
    opportunity_set_status TEXT NOT NULL CHECK(opportunity_set_status IN ('AVAILABLE', 'UNAVAILABLE')),
    member_state TEXT CHECK(member_state IN ('NON_EMPTY', 'EMPTY')),
    frozen_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcome_schedule_plans_v2 (
    outcome_schedule_plan_id TEXT PRIMARY KEY,
    outcome_schedule_plan_hash TEXT NOT NULL UNIQUE,
    graph_run_id TEXT NOT NULL UNIQUE,
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL REFERENCES darwinian_v2_production_variant_roster_revisions(production_variant_roster_revision_id),
    execution_behavior_release_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    trading_calendar_id TEXT NOT NULL,
    trading_calendar_snapshot_hash TEXT NOT NULL,
    as_of TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcome_schedule_slots_v2 (
    outcome_schedule_slot_id TEXT PRIMARY KEY,
    outcome_schedule_slot_hash TEXT NOT NULL UNIQUE,
    outcome_schedule_plan_id TEXT NOT NULL REFERENCES outcome_schedule_plans_v2(outcome_schedule_plan_id),
    graph_run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    run_slot_id TEXT NOT NULL,
    run_slot_kind TEXT NOT NULL CHECK(run_slot_kind IN ('OUTCOME_SCHEDULED', 'DOWNSTREAM_ONLY')),
    scheduled_sample_id TEXT UNIQUE,
    trigger_event_id TEXT,
    record_json TEXT NOT NULL,
    UNIQUE(outcome_schedule_plan_id, agent_id),
    UNIQUE(graph_run_id, run_slot_id)
);

CREATE TABLE IF NOT EXISTS outcome_event_schedule_decisions_v2 (
    event_schedule_decision_id TEXT PRIMARY KEY,
    event_schedule_decision_hash TEXT NOT NULL UNIQUE,
    outcome_schedule_plan_id TEXT NOT NULL REFERENCES outcome_schedule_plans_v2(outcome_schedule_plan_id),
    outcome_schedule_slot_id TEXT NOT NULL REFERENCES outcome_schedule_slots_v2(outcome_schedule_slot_id),
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    causal_dedupe_key TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK(disposition IN ('SELECTED', 'OVERLAPPING_WINDOW')),
    record_json TEXT NOT NULL,
    UNIQUE(track_key_hash, event_id),
    UNIQUE(track_key_hash, causal_dedupe_key)
);

CREATE TABLE IF NOT EXISTS evaluation_opportunity_set_generation_failures_v2 (
    generation_attempt_id TEXT PRIMARY KEY,
    generation_attempt_hash TEXT NOT NULL UNIQUE,
    outcome_schedule_plan_id TEXT NOT NULL REFERENCES outcome_schedule_plans_v2(outcome_schedule_plan_id),
    outcome_schedule_slot_id TEXT NOT NULL UNIQUE REFERENCES outcome_schedule_slots_v2(outcome_schedule_slot_id),
    scheduled_sample_id TEXT NOT NULL UNIQUE,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS no_evaluation_object_stage_skips_v2 (
    stage_skip_id TEXT PRIMARY KEY,
    stage_skip_hash TEXT NOT NULL UNIQUE,
    graph_run_id TEXT NOT NULL,
    outcome_schedule_plan_id TEXT NOT NULL REFERENCES outcome_schedule_plans_v2(outcome_schedule_plan_id),
    outcome_schedule_slot_id TEXT NOT NULL UNIQUE REFERENCES outcome_schedule_slots_v2(outcome_schedule_slot_id),
    scheduled_sample_id TEXT NOT NULL UNIQUE,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL CHECK(agent_id IN (
        'druckenmiller', 'munger', 'burry', 'ackman',
        'cro', 'alpha_discovery', 'autonomous_execution'
    )),
    evaluation_opportunity_set_id TEXT NOT NULL UNIQUE REFERENCES evaluation_opportunity_sets_v2(evaluation_opportunity_set_id),
    eligibility_audit_revision_id TEXT NOT NULL UNIQUE REFERENCES agent_outcome_eligibility_revisions_v2(audit_revision_id),
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS realized_outcome_observations_v2 (
    realized_outcome_observation_id TEXT PRIMARY KEY,
    realized_outcome_observation_hash TEXT NOT NULL UNIQUE,
    scheduled_sample_id TEXT NOT NULL,
    evaluation_opportunity_set_id TEXT NOT NULL REFERENCES evaluation_opportunity_sets_v2(evaluation_opportunity_set_id),
    agent_id TEXT NOT NULL,
    outcome_due_at TEXT NOT NULL,
    matured_at TEXT NOT NULL,
    source_evidence_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(scheduled_sample_id, realized_outcome_observation_hash)
);

CREATE TABLE IF NOT EXISTS agent_outcome_labels_v2 (
    outcome_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_label_id TEXT NOT NULL UNIQUE,
    outcome_label_hash TEXT NOT NULL UNIQUE,
    audit_revision_id TEXT NOT NULL UNIQUE REFERENCES agent_outcome_eligibility_revisions_v2(audit_revision_id),
    scheduled_sample_id TEXT NOT NULL,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    agent_id TEXT NOT NULL,
    primary_label_id TEXT NOT NULL,
    sample_origin TEXT NOT NULL,
    darwin_evaluation_eligible INTEGER NOT NULL CHECK(darwin_evaluation_eligible IN (0, 1)),
    usage_weight_eligible INTEGER NOT NULL CHECK(usage_weight_eligible IN (0, 1)),
    normalized_score REAL NOT NULL CHECK(normalized_score >= -1 AND normalized_score <= 1),
    outcome_due_at TEXT NOT NULL,
    matured_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outcome_labels_v2_track_sequence
    ON agent_outcome_labels_v2(track_key_hash, outcome_sequence);

CREATE TABLE IF NOT EXISTS component_calibration_signals_v2 (
    component_calibration_signal_id TEXT PRIMARY KEY,
    component_calibration_signal_hash TEXT NOT NULL UNIQUE,
    accepted_output_id TEXT NOT NULL REFERENCES accepted_agent_outputs_v2(accepted_output_id),
    operational_opportunity_audit_id TEXT NOT NULL REFERENCES operational_opportunity_audits_v2(operational_opportunity_audit_id),
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL,
    execution_behavior_release_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    language TEXT NOT NULL CHECK(language IN ('en', 'zh')),
    calibration_sample_role TEXT NOT NULL CHECK(calibration_sample_role IN ('FIT_REFERENCE', 'CROSS_VARIANT_DIAGNOSTIC')),
    agent_id TEXT NOT NULL,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    component TEXT NOT NULL,
    scheduled_sample_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    outcome_due_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(accepted_output_id, component)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_component_calibration_reference_agent_asof_component
    ON component_calibration_signals_v2(agent_id, as_of, component)
    WHERE calibration_sample_role = 'FIT_REFERENCE';

CREATE TABLE IF NOT EXISTS component_calibration_candidates_v2 (
    component_calibration_candidate_id TEXT PRIMARY KEY,
    component_calibration_candidate_hash TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    previous_component_weight_contract_version TEXT NOT NULL,
    calibration_contract_version TEXT NOT NULL,
    calibration_solver_version TEXT NOT NULL,
    calibration_half_year_slot TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    fit_sample_count INTEGER NOT NULL CHECK(fit_sample_count >= 0),
    candidate_status TEXT NOT NULL CHECK(candidate_status IN (
        'HELD_INSUFFICIENT_SAMPLES', 'HELD_INSUFFICIENT_FOLDS',
        'REJECTED_GATES', 'SHADOW_CANDIDATE'
    )),
    candidate_weight_set_hash TEXT,
    record_json TEXT NOT NULL,
    UNIQUE(agent_id, calibration_half_year_slot)
);

CREATE TABLE IF NOT EXISTS component_calibration_shadow_evaluations_v2 (
    component_calibration_shadow_evaluation_id TEXT PRIMARY KEY,
    component_calibration_shadow_evaluation_hash TEXT NOT NULL UNIQUE,
    component_calibration_candidate_id TEXT NOT NULL REFERENCES component_calibration_candidates_v2(component_calibration_candidate_id),
    accepted_output_id TEXT NOT NULL REFERENCES accepted_agent_outputs_v2(accepted_output_id),
    outcome_label_id TEXT NOT NULL REFERENCES agent_outcome_labels_v2(outcome_label_id),
    production_variant_roster_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    regime TEXT NOT NULL CHECK(regime IN ('NORMAL', 'STRESS')),
    current_loss REAL NOT NULL CHECK(current_loss >= 0),
    candidate_loss REAL NOT NULL CHECK(candidate_loss >= 0),
    record_json TEXT NOT NULL,
    UNIQUE(component_calibration_candidate_id, accepted_output_id)
);

CREATE TABLE IF NOT EXISTS component_calibration_shadow_checkpoints_v2 (
    component_calibration_shadow_checkpoint_id TEXT PRIMARY KEY,
    component_calibration_shadow_checkpoint_hash TEXT NOT NULL UNIQUE,
    component_calibration_candidate_id TEXT NOT NULL REFERENCES component_calibration_candidates_v2(component_calibration_candidate_id),
    agent_id TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    new_shadow_sample_count INTEGER NOT NULL CHECK(new_shadow_sample_count >= 0),
    checkpoint_status TEXT NOT NULL CHECK(checkpoint_status IN (
        'HELD_INSUFFICIENT_SAMPLES', 'REJECTED_GATES', 'PROMOTION_ELIGIBLE'
    )),
    record_json TEXT NOT NULL,
    UNIQUE(component_calibration_candidate_id, cutoff_at)
);

CREATE TABLE IF NOT EXISTS component_weight_release_revisions_v2 (
    component_weight_release_revision_id TEXT PRIMARY KEY,
    component_weight_release_revision_hash TEXT NOT NULL UNIQUE,
    agent_id TEXT NOT NULL,
    release_sequence INTEGER NOT NULL CHECK(release_sequence >= 1),
    supersedes_revision_id TEXT REFERENCES component_weight_release_revisions_v2(component_weight_release_revision_id),
    action TEXT NOT NULL CHECK(action IN ('PUBLISH', 'ROLLBACK')),
    component_calibration_candidate_id TEXT REFERENCES component_calibration_candidates_v2(component_calibration_candidate_id),
    component_calibration_shadow_checkpoint_id TEXT REFERENCES component_calibration_shadow_checkpoints_v2(component_calibration_shadow_checkpoint_id),
    previous_component_weight_contract_version TEXT NOT NULL,
    target_component_weight_contract_version TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(agent_id, release_sequence),
    UNIQUE(agent_id, effective_at)
);

CREATE TABLE IF NOT EXISTS darwinian_v2_usage_weight_update_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    checkpoint_hash TEXT NOT NULL UNIQUE,
    usage_track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_usage_tracks(usage_track_key_hash),
    production_variant_roster_revision_id TEXT NOT NULL,
    rank_scope TEXT NOT NULL,
    update_slot_id TEXT NOT NULL,
    update_disposition TEXT NOT NULL CHECK(update_disposition IN (
        'UPDATED', 'HELD_INSUFFICIENT_WINDOW',
        'HELD_INSUFFICIENT_PEERS', 'NO_NEW_OUTCOME'
    )),
    max_consumed_outcome_sequence INTEGER NOT NULL CHECK(max_consumed_outcome_sequence >= 0),
    update_event_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(usage_track_key_hash, update_slot_id, update_event_id)
);

CREATE TABLE IF NOT EXISTS darwinian_v2_usage_weight_batch_revisions (
    batch_revision_id TEXT PRIMARY KEY,
    batch_revision_hash TEXT NOT NULL UNIQUE,
    update_event_id TEXT NOT NULL,
    supersedes_revision_id TEXT REFERENCES darwinian_v2_usage_weight_batch_revisions(batch_revision_id),
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL,
    rank_scope TEXT NOT NULL,
    update_slot_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PREPARED', 'PUBLISHED', 'ABORTED')),
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(update_event_id, status)
);

CREATE TABLE IF NOT EXISTS darwinian_v2_usage_weight_snapshots (
    darwinian_snapshot_id TEXT PRIMARY KEY,
    darwinian_snapshot_hash TEXT NOT NULL UNIQUE,
    update_event_id TEXT NOT NULL,
    production_variant_roster_id TEXT NOT NULL,
    production_variant_roster_revision_id TEXT NOT NULL,
    rank_scope TEXT NOT NULL,
    update_slot_id TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(update_event_id, rank_scope)
);

CREATE TABLE IF NOT EXISTS darwinian_v2_evaluation_window_checkpoints (
    evaluation_checkpoint_id TEXT PRIMARY KEY,
    evaluation_checkpoint_hash TEXT NOT NULL UNIQUE,
    track_key_hash TEXT NOT NULL REFERENCES darwinian_v2_evaluation_tracks(track_key_hash),
    production_variant_roster_revision_id TEXT NOT NULL,
    rank_scope TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    maturity_state TEXT NOT NULL CHECK(maturity_state IN ('COLD_START', 'MATURE')),
    performance_band TEXT CHECK(performance_band IN ('Q1', 'Q2', 'Q3', 'Q4')),
    n_eligible_scores INTEGER NOT NULL CHECK(n_eligible_scores >= 0),
    window_coverage REAL NOT NULL CHECK(window_coverage >= 0 AND window_coverage <= 1),
    mean_normalized_score REAL,
    scoring_window_hash TEXT NOT NULL,
    max_consumed_outcome_sequence INTEGER NOT NULL CHECK(max_consumed_outcome_sequence >= 0),
    recorded_at TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(track_key_hash, cutoff_at, scoring_window_hash)
);

-- Immutability is enforced by SQLite itself, not by caller convention.
CREATE TRIGGER IF NOT EXISTS no_update_darwinian_v2_evaluation_tracks
BEFORE UPDATE ON darwinian_v2_evaluation_tracks BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwinian_v2_evaluation_tracks
BEFORE DELETE ON darwinian_v2_evaluation_tracks BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwinian_v2_usage_tracks
BEFORE UPDATE ON darwinian_v2_usage_tracks BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwinian_v2_usage_tracks
BEFORE DELETE ON darwinian_v2_usage_tracks BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwinian_v2_roster_revisions
BEFORE UPDATE ON darwinian_v2_production_variant_roster_revisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwinian_v2_roster_revisions
BEFORE DELETE ON darwinian_v2_production_variant_roster_revisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwinian_v2_weight_records
BEFORE UPDATE ON darwinian_v2_usage_weight_records BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwinian_v2_weight_records
BEFORE DELETE ON darwinian_v2_usage_weight_records BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_accepted_agent_outputs_v2
BEFORE UPDATE ON accepted_agent_outputs_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_accepted_agent_outputs_v2
BEFORE DELETE ON accepted_agent_outputs_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_operational_audits_v2
BEFORE UPDATE ON operational_opportunity_audits_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_operational_audits_v2
BEFORE DELETE ON operational_opportunity_audits_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_operational_reliability_v2
BEFORE UPDATE ON darwinian_v2_operational_reliability_records BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_operational_reliability_v2
BEFORE DELETE ON darwinian_v2_operational_reliability_records BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_outcome_eligibility_v2
BEFORE UPDATE ON agent_outcome_eligibility_revisions_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_outcome_eligibility_v2
BEFORE DELETE ON agent_outcome_eligibility_revisions_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_evaluation_opportunity_sets_v2
BEFORE UPDATE ON evaluation_opportunity_sets_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_evaluation_opportunity_sets_v2
BEFORE DELETE ON evaluation_opportunity_sets_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_outcome_schedule_plans_v2
BEFORE UPDATE ON outcome_schedule_plans_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_outcome_schedule_plans_v2
BEFORE DELETE ON outcome_schedule_plans_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_outcome_schedule_slots_v2
BEFORE UPDATE ON outcome_schedule_slots_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_outcome_schedule_slots_v2
BEFORE DELETE ON outcome_schedule_slots_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_outcome_event_schedule_decisions_v2
BEFORE UPDATE ON outcome_event_schedule_decisions_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_outcome_event_schedule_decisions_v2
BEFORE DELETE ON outcome_event_schedule_decisions_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_opportunity_generation_failures_v2
BEFORE UPDATE ON evaluation_opportunity_set_generation_failures_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_opportunity_generation_failures_v2
BEFORE DELETE ON evaluation_opportunity_set_generation_failures_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_no_evaluation_object_stage_skips_v2
BEFORE UPDATE ON no_evaluation_object_stage_skips_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_no_evaluation_object_stage_skips_v2
BEFORE DELETE ON no_evaluation_object_stage_skips_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_realized_outcome_observations_v2
BEFORE UPDATE ON realized_outcome_observations_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_realized_outcome_observations_v2
BEFORE DELETE ON realized_outcome_observations_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_outcome_labels_v2
BEFORE UPDATE ON agent_outcome_labels_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_outcome_labels_v2
BEFORE DELETE ON agent_outcome_labels_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_component_calibration_signals_v2
BEFORE UPDATE ON component_calibration_signals_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_component_calibration_signals_v2
BEFORE DELETE ON component_calibration_signals_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_component_calibration_candidates_v2
BEFORE UPDATE ON component_calibration_candidates_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_component_calibration_candidates_v2
BEFORE DELETE ON component_calibration_candidates_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_component_calibration_shadow_evaluations_v2
BEFORE UPDATE ON component_calibration_shadow_evaluations_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_component_calibration_shadow_evaluations_v2
BEFORE DELETE ON component_calibration_shadow_evaluations_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_component_calibration_shadow_checkpoints_v2
BEFORE UPDATE ON component_calibration_shadow_checkpoints_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_component_calibration_shadow_checkpoints_v2
BEFORE DELETE ON component_calibration_shadow_checkpoints_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_component_weight_release_revisions_v2
BEFORE UPDATE ON component_weight_release_revisions_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_component_weight_release_revisions_v2
BEFORE DELETE ON component_weight_release_revisions_v2 BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwin_v2_checkpoints
BEFORE UPDATE ON darwinian_v2_usage_weight_update_checkpoints BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwin_v2_checkpoints
BEFORE DELETE ON darwinian_v2_usage_weight_update_checkpoints BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwin_v2_batch_revisions
BEFORE UPDATE ON darwinian_v2_usage_weight_batch_revisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwin_v2_batch_revisions
BEFORE DELETE ON darwinian_v2_usage_weight_batch_revisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwin_v2_weight_snapshots
BEFORE UPDATE ON darwinian_v2_usage_weight_snapshots BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwin_v2_weight_snapshots
BEFORE DELETE ON darwinian_v2_usage_weight_snapshots BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_darwin_v2_evaluation_checkpoints
BEFORE UPDATE ON darwinian_v2_evaluation_window_checkpoints BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_darwin_v2_evaluation_checkpoints
BEFORE DELETE ON darwinian_v2_evaluation_window_checkpoints BEGIN SELECT RAISE(ABORT, 'append_only'); END;
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
    signal: Optional[float]
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
    if state.get("darwinian_runtime_binding") is not None:
        return _expand_formal_accepted_recommendations(state, date=date)

    # R-A1: provenance — was this cycle's portfolio produced after a CRO-veto
    # replay? Stamped on every row so the scorecard can segment first-pass vs
    # replayed recommendations.
    replay_flag = 1 if state.get("replay_triggered") else 0
    day_outcome_status = (
        "accepted" if state.get("day_outcome_status") == "accepted" else "legacy_unverified"
    )
    backtest_run_id = state.get("backtest_run_id")
    if not isinstance(backtest_run_id, int) or isinstance(backtest_run_id, bool):
        backtest_run_id = None

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
    decision_agent_audits_json = (
        _decision_agent_audits_json(layer4) if isinstance(layer4, dict) else None
    )
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
                    "current_weight_pct": _maybe_pct(action_obj.get("current_weight")),
                    "delta_weight_pct": _maybe_pct(action_obj.get("delta_weight")),
                    "position_decision": action_obj.get("position_decision"),
                    "position_decision_reason": action_obj.get("position_decision_reason"),
                    "override_reason": action_obj.get("override_reason"),
                    "thesis_status": action_obj.get("thesis_status"),
                    "risk_flags_json": _json_list_or_none(action_obj.get("risk_flags")),
                    # Legacy database columns remain nullable for old audit rows;
                    # private KNOT identifiers never cross the runtime boundary.
                    "declared_knob_influence_ids_json": None,
                    "declared_influence_rationale": None,
                    "verified_knob_audit_json": _json_object_or_none(
                        cio.get("private_knot_audit")
                    ),
                    "decision_agent_audits_json": decision_agent_audits_json,
                    "dissent_notes": action_obj.get("dissent_notes"),
                    "rationale_snapshot": _truncate(
                        action_obj.get("dissent_notes") or action_obj.get("thesis"),
                        200,
                    ),
                }
            )

    for row in rows:
        row["replay_triggered"] = replay_flag
        row["day_outcome_status"] = day_outcome_status
        row["backtest_run_id"] = backtest_run_id
        for key in (
            "current_weight_pct",
            "delta_weight_pct",
            "position_decision",
            "position_decision_reason",
            "override_reason",
            "thesis_status",
            "risk_flags_json",
            "declared_knob_influence_ids_json",
            "declared_influence_rationale",
            "verified_knob_audit_json",
            "decision_agent_audits_json",
            "dissent_notes",
        ):
            row.setdefault(key, None)

    return rows


def _expand_formal_accepted_recommendations(
    state: dict[str, Any],
    *,
    date: str,
) -> list[dict[str, Any]]:
    cohort = state.get("active_cohort") or "cohort_default"
    replay_flag = 1 if state.get("replay_triggered") else 0
    day_outcome_status = (
        "accepted" if state.get("day_outcome_status") == "accepted" else "legacy_unverified"
    )
    backtest_run_id = state.get("backtest_run_id")
    if not isinstance(backtest_run_id, int) or isinstance(backtest_run_id, bool):
        backtest_run_id = None
    rows: list[dict[str, Any]] = []
    records = _formal_accepted_payload_records(state)
    for record, payload in records:
        agent_id = str(record["agent_id"])
        kind = record.get("accepted_output_kind")
        if kind == "STANDARD_SECTOR_SELECTION":
            selection = payload.get("selection")
            if not isinstance(selection, dict):
                continue
            for pick in selection.get("long_picks") or []:
                if not isinstance(pick, dict) or not isinstance(pick.get("ts_code"), str):
                    continue
                conviction = float(pick.get("conviction") or 0.0)
                rows.append(
                    {
                        "cohort": cohort,
                        "agent": agent_id,
                        "ticker": pick["ts_code"],
                        "date": date,
                        "action": "LONG",
                        "conviction": conviction,
                        "target_weight_pct": conviction * 100.0,
                        "current_weight_pct": None,
                        "delta_weight_pct": None,
                        "position_decision": None,
                        "position_decision_reason": None,
                        "override_reason": None,
                        "thesis_status": None,
                        "risk_flags_json": None,
                        "declared_knob_influence_ids_json": None,
                        "declared_influence_rationale": None,
                        "verified_knob_audit_json": None,
                        "decision_agent_audits_json": None,
                        "dissent_notes": None,
                        "rationale_snapshot": _truncate(pick.get("thesis"), 200),
                        "replay_triggered": replay_flag,
                        "day_outcome_status": day_outcome_status,
                        "backtest_run_id": backtest_run_id,
                    }
                )
        elif kind == "SUPERINVESTOR_SELECTION":
            selection = payload.get("selection")
            if not isinstance(selection, dict):
                continue
            for pick in selection.get("picks") or []:
                if not isinstance(pick, dict) or not isinstance(pick.get("ts_code"), str):
                    continue
                conviction = float(pick.get("conviction") or 0.0)
                rows.append(
                    {
                        "cohort": cohort,
                        "agent": agent_id,
                        "ticker": pick["ts_code"],
                        "date": date,
                        "action": "LONG",
                        "conviction": conviction,
                        "target_weight_pct": conviction * 100.0,
                        "current_weight_pct": None,
                        "delta_weight_pct": None,
                        "position_decision": None,
                        "position_decision_reason": None,
                        "override_reason": None,
                        "thesis_status": None,
                        "risk_flags_json": None,
                        "declared_knob_influence_ids_json": None,
                        "declared_influence_rationale": None,
                        "verified_knob_audit_json": None,
                        "decision_agent_audits_json": None,
                        "dissent_notes": None,
                        "rationale_snapshot": _truncate(pick.get("thesis"), 200),
                        "replay_triggered": replay_flag,
                        "day_outcome_status": day_outcome_status,
                        "backtest_run_id": backtest_run_id,
                    }
                )
        elif kind == "CIO_FINAL":
            decision = payload.get("decision")
            if not isinstance(decision, dict):
                continue
            operational_by_ticker = {
                row.get("ticker"): row
                for row in state.get("portfolio_actions") or []
                if isinstance(row, dict) and isinstance(row.get("ticker"), str)
            }
            action_by_decision = {
                "ADD": "BUY",
                "REDUCE": "REDUCE",
                "EXIT": "SELL",
                "HOLD": "HOLD",
            }
            for position in decision.get("target_positions") or []:
                if not isinstance(position, dict) or not isinstance(position.get("ts_code"), str):
                    continue
                ticker = position["ts_code"]
                operational = operational_by_ticker.get(ticker, {})
                target_weight = float(position.get("target_weight") or 0.0)
                position_decision = position.get("position_decision")
                rows.append(
                    {
                        "cohort": cohort,
                        "agent": "cio",
                        "ticker": ticker,
                        "date": date,
                        "action": action_by_decision.get(position_decision, "HOLD"),
                        "conviction": None,
                        "target_weight_pct": target_weight * 100.0,
                        "current_weight_pct": _maybe_pct(operational.get("current_weight")),
                        "delta_weight_pct": _maybe_pct(operational.get("delta_weight")),
                        "position_decision": position_decision,
                        "position_decision_reason": decision.get("decision_reason"),
                        "override_reason": None,
                        "thesis_status": position.get("thesis_status"),
                        "risk_flags_json": _json_list_or_none(position.get("risk_flags")),
                        "declared_knob_influence_ids_json": None,
                        "declared_influence_rationale": None,
                        "verified_knob_audit_json": None,
                        "decision_agent_audits_json": _json_list_or_none(
                            [
                                audit
                                for audit in state.get("agent_run_audits") or []
                                if isinstance(audit, dict)
                                and audit.get("agent")
                                in {"alpha_discovery", "cro", "autonomous_execution", "cio"}
                            ]
                        ),
                        "dissent_notes": None,
                        "rationale_snapshot": _truncate(
                            decision.get("decision_reason"), 200
                        ),
                        "replay_triggered": replay_flag,
                        "day_outcome_status": day_outcome_status,
                        "backtest_run_id": backtest_run_id,
                    }
                )
    return rows


def _formal_accepted_payload_records(
    state: Mapping[str, Any],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    records = state.get("accepted_output_records")
    if not isinstance(records, list):
        raise ValueError("formal accepted state requires accepted_output_records")
    result: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("accepted output record must be an object")
        envelope = record.get("output")
        payload = envelope.get("payload") if isinstance(envelope, Mapping) else None
        if not isinstance(payload, Mapping):
            raise ValueError("accepted output record payload must be an object")
        result.append((record, payload))
    return result


def _maybe_pct(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) * 100.0


def _json_list_or_none(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    return json.dumps([str(item) for item in value], ensure_ascii=False)


def _json_object_or_none(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decision_agent_audits_json(layer4: dict[str, Any]) -> str | None:
    rows: dict[str, dict[str, Any]] = {}
    for agent in ("cro", "autonomous_execution", "cio"):
        output = layer4.get(agent)
        if not isinstance(output, dict):
            continue
        row: dict[str, Any] = {}
        audit = output.get("private_knot_audit")
        if isinstance(audit, dict):
            for key in (
                "snapshot_hash",
                "accepted",
                "output_selection",
                "reason_codes",
                "tool_status_summary",
                "runtime_source_status_summary",
            ):
                if key in audit:
                    row[key] = audit[key]
        if row:
            rows[agent] = row
    if not rows:
        return None
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Macro-signal expansion (Layer 1) — preserves ten independent v2 transmissions.
# Legacy consensus/influence database columns remain nullable for old audit rows.
# ---------------------------------------------------------------------------

MACRO_AGENTS: frozenset[str] = frozenset(
    MACRO_AGENT_ORDER
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
    """Map a current macro output to its directional sign for hit-rate reporting."""
    if agent not in MACRO_AGENTS:
        return 0
    direction = out.get("direction")
    return 1 if direction == "SUPPORTIVE" else (-1 if direction == "ADVERSE" else 0)


def _macro_signal(agent: str, out: dict[str, Any]) -> float:
    """Return the canonical TypeScript-compatible signal s_i in [-1, 1]."""
    if agent not in MACRO_AGENTS:
        return 0.0
    direction = out.get("direction")
    strength = out.get("strength")
    if direction not in {"SUPPORTIVE", "NEUTRAL", "ADVERSE"}:
        raise ValueError(f"invalid macro direction for {agent}: {direction!r}")
    if not isinstance(strength, int) or isinstance(strength, bool) or strength not in range(6):
        raise ValueError(f"invalid macro strength for {agent}: {strength!r}")
    if direction == "NEUTRAL" and strength != 0:
        raise ValueError(f"NEUTRAL requires strength=0 for {agent}")
    if direction != "NEUTRAL" and strength == 0:
        raise ValueError(f"non-neutral direction requires strength in 1..5 for {agent}")
    return _macro_vote(agent, out) * strength / 5.0


def _macro_equal_weight_influence(
    rows: list[dict[str, Any]],
) -> dict[str, Optional[float]]:
    """Retained column projection; no cross-role Macro influence exists in v2."""
    return {str(row["agent"]): None for row in rows}


def expand_state_to_macro_signals(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Project a daily-cycle state's Layer 1 outputs into macro_signals rows.

    Returns one row per accepted v2 role. Legacy consensus/influence columns are
    always ``None``; scoring columns are filled later by the role-owned scorer.
    """
    cohort = state.get("active_cohort") or "cohort_default"
    date = state.get("as_of_date")
    if not isinstance(date, str) or not date:
        raise ValueError("state.as_of_date is required to expand macro signals")

    consensus_stance = None
    consensus_score = None

    prompt_repo_id = state.get("prompt_repo_id")
    prompt_sha256 = state.get("prompt_sha256")
    day_outcome_status = (
        "accepted" if state.get("day_outcome_status") == "accepted" else "legacy_unverified"
    )
    backtest_run_id = state.get("backtest_run_id")
    if not isinstance(backtest_run_id, int) or isinstance(backtest_run_id, bool):
        backtest_run_id = None

    rows: list[dict[str, Any]] = []
    macro_outputs = (
        {
            str(record["agent_id"]): dict(payload)
            for record, payload in _formal_accepted_payload_records(state)
            if record.get("accepted_output_kind") == "MACRO_TRANSMISSION"
        }
        if state.get("darwinian_runtime_binding") is not None
        else state.get("layer1_outputs") or {}
    )
    for agent, out in macro_outputs.items():
        if agent not in MACRO_AGENTS or not isinstance(out, dict):
            continue
        conf = out.get("confidence")
        signal = _macro_signal(agent, out)
        rows.append(
            {
                "cohort": cohort,
                "agent": agent,
                "date": date,
                "vote": _macro_vote(agent, out),
                "signal": signal,
                "confidence": float(conf) if conf is not None else None,
                "raw_output_json": json.dumps(out, ensure_ascii=False),
                "consensus_stance": consensus_stance,
                "consensus_score": consensus_score,
                "prompt_repo_id": prompt_repo_id,
                "prompt_sha256": prompt_sha256,
                "day_outcome_status": day_outcome_status,
                "backtest_run_id": backtest_run_id,
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
            for column, ddl in (
                ("current_weight_pct", "REAL"),
                ("delta_weight_pct", "REAL"),
                ("position_decision", "TEXT"),
                ("position_decision_reason", "TEXT"),
                ("override_reason", "TEXT"),
                ("thesis_status", "TEXT"),
                ("risk_flags_json", "TEXT"),
                ("declared_knob_influence_ids_json", "TEXT"),
                ("declared_influence_rationale", "TEXT"),
                ("verified_knob_audit_json", "TEXT"),
                ("decision_agent_audits_json", "TEXT"),
                ("dissent_notes", "TEXT"),
                ("day_outcome_status", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
                ("backtest_run_id", "INTEGER"),
            ):
                self._ensure_column(conn, "recommendations", column, ddl)
            self._ensure_column(conn, "prompt_versions", "prompt_repo_id", "TEXT")
            self._ensure_column(conn, "prompt_versions", "prompt_base_commit_hash", "TEXT")
            self._ensure_column(conn, "prompt_versions", "prompt_sha256", "TEXT")
            self._ensure_column(conn, "prompt_versions", "code_commit_hash", "TEXT")
            self._ensure_column(conn, "prompt_versions", "mutation_id", "TEXT")
            self._ensure_column(conn, "prompt_versions", "transaction_id", "TEXT")
            self._ensure_column(conn, "prompt_versions", "experiment_id", "TEXT")
            self._ensure_column(conn, "prompt_versions", "mutation_metadata_json", "TEXT")
            self._ensure_column(conn, "prompt_versions", "mutation_lifecycle", "TEXT")
            self._ensure_column(conn, "prompt_versions", "evaluation_result_json", "TEXT")
            self._ensure_column(conn, "prompt_versions", "promotion_decision_json", "TEXT")
            self._ensure_column(conn, "prompt_versions", "promotion_decision_hash", "TEXT")
            self._ensure_column(conn, "prompt_versions", "promotion_approved_by", "TEXT")
            self._ensure_column(
                conn, "prompt_versions", "promotion_approval_policy_id", "TEXT"
            )
            self._ensure_column(conn, "backtest_runs", "prompt_commit_ref", "TEXT")
            self._ensure_column(conn, "backtest_runs", "prompt_repo_id", "TEXT")
            self._ensure_column(conn, "backtest_runs", "prompt_sha256", "TEXT")
            self._ensure_column(conn, "backtest_runs", "code_commit_hash", "TEXT")
            self._ensure_column(conn, "macro_signals", "influence_weight_equal", "REAL")
            self._ensure_column(conn, "macro_signals", "signal", "REAL")
            self._ensure_column(conn, "macro_signals", "effective_macro_score_5d", "REAL")
            self._ensure_column(conn, "macro_signals", "terminal_return_5d", "REAL")
            self._ensure_column(conn, "macro_signals", "max_drawdown_5d", "REAL")
            self._ensure_column(conn, "macro_signals", "realized_volatility_5d", "REAL")
            self._ensure_column(conn, "macro_signals", "path_metric_5d", "REAL")
            self._ensure_column(conn, "macro_signals", "source_series_id", "TEXT")
            self._ensure_column(
                conn,
                "macro_signals",
                "day_outcome_status",
                "TEXT NOT NULL DEFAULT 'legacy_unverified'",
            )
            self._ensure_column(conn, "macro_signals", "backtest_run_id", "INTEGER")
            for column, ddl in (
                ("prepared_at", "TEXT"),
                ("recorded_at", "TEXT"),
                ("effective_slot_sequence", "INTEGER"),
            ):
                self._ensure_column(
                    conn,
                    "darwinian_v2_production_variant_roster_revisions",
                    column,
                    ddl,
                )
            conn.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_darwin_v2_roster_effective_slot
                    ON darwinian_v2_production_variant_roster_revisions(
                        production_variant_roster_id, effective_slot_sequence
                    )
                    WHERE effective_slot_sequence IS NOT NULL;
                CREATE TRIGGER IF NOT EXISTS require_darwin_v2_roster_revision_timing
                BEFORE INSERT ON darwinian_v2_production_variant_roster_revisions
                WHEN NEW.prepared_at IS NULL OR NEW.recorded_at IS NULL OR
                     NEW.effective_slot_sequence IS NULL OR
                     NEW.effective_slot_sequence < 1
                BEGIN
                    SELECT RAISE(ABORT, 'roster revision requires authoritative timing');
                END;
                """
            )
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
            self._ensure_column(
                conn,
                "agent_outcome_eligibility_revisions_v2",
                "research_pair_side",
                "TEXT CHECK(research_pair_side IN ('CHAMPION', 'CANDIDATE'))",
            )
            knot_lineage_columns = (
                ("knot_pair_id", "TEXT"),
                ("knot_pair_input_hash", "TEXT"),
                (
                    "research_pair_side",
                    "TEXT CHECK(research_pair_side IN ('CHAMPION', 'CANDIDATE'))",
                ),
                ("capability_id", "TEXT"),
                ("capability_signature_hash", "TEXT"),
                ("snapshot_bundle_id", "TEXT"),
                ("snapshot_bundle_hash", "TEXT"),
                ("runtime_input_hash", "TEXT"),
                ("prompt_behavior_version", "TEXT"),
                ("execution_behavior_version", "TEXT"),
                ("evaluation_object_hash", "TEXT"),
            )
            for table in (
                "accepted_agent_outputs_v2",
                "operational_opportunity_audits_v2",
            ):
                for column, ddl in knot_lineage_columns:
                    self._ensure_column(conn, table, column, ddl)
            for column, ddl in knot_lineage_columns:
                self._ensure_column(
                    conn,
                    "agent_outcome_eligibility_revisions_v2",
                    column,
                    ddl,
                )
            self._ensure_column(
                conn,
                "agent_outcome_eligibility_revisions_v2",
                "accepted_output_hash",
                "TEXT",
            )
            self._ensure_column(
                conn,
                "agent_outcome_eligibility_revisions_v2",
                "operational_opportunity_audit_id",
                "TEXT",
            )
            self._ensure_column(
                conn,
                "agent_outcome_eligibility_revisions_v2",
                "operational_opportunity_audit_hash",
                "TEXT",
            )
            self._install_knot_lineage_guards(conn)

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, ddl: str
    ) -> None:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    @staticmethod
    def _install_knot_lineage_guards(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            DROP INDEX IF EXISTS uq_accepted_knot_pair_side_v2;
            DROP INDEX IF EXISTS uq_operational_knot_pair_side_v2;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_accepted_knot_pair_side_v2
                ON accepted_agent_outputs_v2(knot_pair_id, research_pair_side)
                WHERE knot_pair_id IS NOT NULL AND agent_id <> 'cio';
            CREATE UNIQUE INDEX IF NOT EXISTS uq_accepted_knot_cio_phase_v2
                ON accepted_agent_outputs_v2(
                    knot_pair_id, research_pair_side, accepted_output_kind
                )
                WHERE knot_pair_id IS NOT NULL AND agent_id = 'cio';
            CREATE UNIQUE INDEX IF NOT EXISTS uq_operational_knot_pair_side_v2
                ON operational_opportunity_audits_v2(knot_pair_id, research_pair_side)
                WHERE knot_pair_id IS NOT NULL AND agent_id <> 'cio';
            CREATE UNIQUE INDEX IF NOT EXISTS uq_operational_knot_cio_phase_v2
                ON operational_opportunity_audits_v2(
                    knot_pair_id,
                    research_pair_side,
                    COALESCE(json_extract(record_json, '$.accepted_output_kind'), '')
                )
                WHERE knot_pair_id IS NOT NULL AND agent_id = 'cio';

            CREATE TRIGGER IF NOT EXISTS require_accepted_knot_lineage_v2
            BEFORE INSERT ON accepted_agent_outputs_v2
            WHEN NEW.sample_origin IN (
                'KNOT_RESEARCH_SHADOW', 'KNOT_POST_PROMOTION_CHAMPION_SHADOW'
            ) AND (
                NEW.knot_pair_id IS NULL OR NEW.knot_pair_input_hash IS NULL OR
                NEW.research_pair_side IS NULL OR NEW.capability_id IS NULL OR
                NEW.capability_signature_hash IS NULL OR
                NEW.snapshot_bundle_id IS NULL OR NEW.snapshot_bundle_hash IS NULL OR
                NEW.runtime_input_hash IS NULL OR
                NEW.prompt_behavior_version IS NULL OR
                NEW.execution_behavior_version IS NULL OR
                NEW.evaluation_object_hash IS NULL
            ) BEGIN
                SELECT RAISE(ABORT, 'KNOT accepted output requires complete lineage');
            END;

            CREATE TRIGGER IF NOT EXISTS forbid_production_accepted_knot_lineage_v2
            BEFORE INSERT ON accepted_agent_outputs_v2
            WHEN NEW.sample_origin = 'PRODUCTION_ACTIVE' AND (
                NEW.knot_pair_id IS NOT NULL OR NEW.knot_pair_input_hash IS NOT NULL OR
                NEW.research_pair_side IS NOT NULL OR NEW.capability_id IS NOT NULL OR
                NEW.capability_signature_hash IS NOT NULL OR
                NEW.snapshot_bundle_id IS NOT NULL OR NEW.snapshot_bundle_hash IS NOT NULL OR
                NEW.runtime_input_hash IS NOT NULL OR
                NEW.evaluation_object_hash IS NOT NULL OR
                json_type(NEW.record_json, '$.knot_pair_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.knot_pair_input_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.research_pair_side') IS NOT NULL OR
                json_type(NEW.record_json, '$.capability_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.capability_signature_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.snapshot_bundle_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.snapshot_bundle_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.runtime_input_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.evaluation_object_hash') IS NOT NULL
            ) BEGIN
                SELECT RAISE(ABORT, 'production accepted output cannot carry KNOT lineage');
            END;

            CREATE TRIGGER IF NOT EXISTS require_operational_knot_lineage_v2
            BEFORE INSERT ON operational_opportunity_audits_v2
            WHEN NEW.sample_origin IN (
                'KNOT_RESEARCH_SHADOW', 'KNOT_POST_PROMOTION_CHAMPION_SHADOW'
            ) AND NEW.disposition IN ('ACCEPTED', 'AGENT_FAILURE') AND (
                NEW.knot_pair_id IS NULL OR NEW.knot_pair_input_hash IS NULL OR
                NEW.research_pair_side IS NULL OR NEW.capability_id IS NULL OR
                NEW.capability_signature_hash IS NULL OR
                NEW.snapshot_bundle_id IS NULL OR NEW.snapshot_bundle_hash IS NULL OR
                NEW.runtime_input_hash IS NULL OR
                NEW.prompt_behavior_version IS NULL OR
                NEW.execution_behavior_version IS NULL OR
                (NEW.disposition = 'ACCEPTED' AND NEW.evaluation_object_hash IS NULL)
            ) BEGIN
                SELECT RAISE(ABORT, 'KNOT operational audit requires complete lineage');
            END;

            CREATE TRIGGER IF NOT EXISTS forbid_production_operational_knot_lineage_v2
            BEFORE INSERT ON operational_opportunity_audits_v2
            WHEN NEW.sample_origin = 'PRODUCTION_ACTIVE' AND (
                NEW.knot_pair_id IS NOT NULL OR NEW.knot_pair_input_hash IS NOT NULL OR
                NEW.research_pair_side IS NOT NULL OR NEW.capability_id IS NOT NULL OR
                NEW.capability_signature_hash IS NOT NULL OR
                NEW.snapshot_bundle_id IS NOT NULL OR NEW.snapshot_bundle_hash IS NOT NULL OR
                NEW.runtime_input_hash IS NOT NULL OR
                NEW.evaluation_object_hash IS NOT NULL OR
                json_type(NEW.record_json, '$.knot_pair_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.knot_pair_input_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.research_pair_side') IS NOT NULL OR
                json_type(NEW.record_json, '$.capability_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.capability_signature_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.snapshot_bundle_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.snapshot_bundle_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.runtime_input_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.evaluation_object_hash') IS NOT NULL
            ) BEGIN
                SELECT RAISE(ABORT, 'production operational audit cannot carry KNOT lineage');
            END;

            CREATE TRIGGER IF NOT EXISTS require_eligibility_knot_lineage_v2
            BEFORE INSERT ON agent_outcome_eligibility_revisions_v2
            WHEN NEW.sample_origin IN (
                'KNOT_RESEARCH_SHADOW', 'KNOT_POST_PROMOTION_CHAMPION_SHADOW'
            ) AND (
                NEW.knot_pair_id IS NULL OR NEW.knot_pair_input_hash IS NULL OR
                NEW.research_pair_side IS NULL OR NEW.capability_id IS NULL OR
                NEW.capability_signature_hash IS NULL OR
                NEW.snapshot_bundle_id IS NULL OR NEW.snapshot_bundle_hash IS NULL OR
                NEW.runtime_input_hash IS NULL OR
                NEW.prompt_behavior_version IS NULL OR
                NEW.execution_behavior_version IS NULL OR
                NEW.operational_opportunity_audit_id IS NULL OR
                NEW.operational_opportunity_audit_hash IS NULL OR
                (NEW.disposition IN ('PENDING', 'SCORE') AND (
                    NEW.evaluation_object_hash IS NULL OR
                    NEW.accepted_output_hash IS NULL
                ))
            ) BEGIN
                SELECT RAISE(ABORT, 'KNOT eligibility requires complete lineage');
            END;

            CREATE TRIGGER IF NOT EXISTS forbid_production_eligibility_knot_lineage_v2
            BEFORE INSERT ON agent_outcome_eligibility_revisions_v2
            WHEN NEW.sample_origin = 'PRODUCTION_ACTIVE' AND (
                NEW.knot_pair_id IS NOT NULL OR NEW.knot_pair_input_hash IS NOT NULL OR
                NEW.research_pair_side IS NOT NULL OR NEW.capability_id IS NOT NULL OR
                NEW.capability_signature_hash IS NOT NULL OR
                NEW.snapshot_bundle_id IS NOT NULL OR NEW.snapshot_bundle_hash IS NOT NULL OR
                NEW.runtime_input_hash IS NOT NULL OR
                NEW.evaluation_object_hash IS NOT NULL OR
                NEW.operational_opportunity_audit_id IS NOT NULL OR
                NEW.operational_opportunity_audit_hash IS NOT NULL OR
                json_type(NEW.record_json, '$.knot_pair_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.knot_pair_input_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.research_pair_side') IS NOT NULL OR
                json_type(NEW.record_json, '$.capability_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.capability_signature_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.snapshot_bundle_id') IS NOT NULL OR
                json_type(NEW.record_json, '$.snapshot_bundle_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.runtime_input_hash') IS NOT NULL OR
                json_type(NEW.record_json, '$.evaluation_object_hash') IS NOT NULL OR
                json_type(
                    NEW.record_json, '$.operational_opportunity_audit_id'
                ) IS NOT NULL OR
                json_type(
                    NEW.record_json, '$.operational_opportunity_audit_hash'
                ) IS NOT NULL
            ) BEGIN
                SELECT RAISE(ABORT, 'production eligibility cannot carry KNOT lineage');
            END;
            """
        )

    # ── Darwinian v2 immutable contracts ────────────────────────────────

    def register_darwinian_production_variant(
        self,
        *,
        cohort_id: str,
        language: str,
        execution_behavior_release_id: str,
        behavior_bindings: Mapping[str, Mapping[str, Any]],
        effective_at: str,
        prepared_at: str | None = None,
        recorded_at: str | None = None,
        effective_slot_sequence: int | None = None,
    ) -> dict[str, Any]:
        from mosaic.scorecard.darwinian_v2 import register_production_variant

        with self._connect() as conn:
            return register_production_variant(
                conn,
                cohort_id=cohort_id,
                language=language,
                execution_behavior_release_id=execution_behavior_release_id,
                behavior_bindings=behavior_bindings,
                effective_at=effective_at,
                prepared_at=prepared_at,
                recorded_at=recorded_at,
                effective_slot_sequence=effective_slot_sequence,
            )

    def get_darwinian_v2_weight_snapshot(
        self,
        *,
        production_variant_roster_revision_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        from mosaic.scorecard.darwinian_v2 import get_production_weight_snapshot

        with self._connect() as conn:
            return get_production_weight_snapshot(
                conn,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                as_of=as_of,
            )

    def append_darwinian_v2_accepted_cycle(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        from mosaic.scorecard.darwinian_v2 import append_accepted_cycle

        with self._connect() as conn:
            return append_accepted_cycle(conn, state=state)

    def append_knot_pair_side_execution_result(
        self,
        *,
        knot_pair_id: str,
        pair_side: str,
        graph_run_id: str,
        run_id: str,
        result_disposition: str,
        recorded_at: str,
        validated_output: Mapping[str, Any] | None = None,
        strict_receipt_verifier: Any | None = None,
        failure_reason: str | None = None,
        cio_failure_phase: str | None = None,
        cio_output_phase: str | None = None,
    ) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import append_knot_pair_side_execution_result

        with self._connect() as conn:
            return append_knot_pair_side_execution_result(
                conn,
                knot_pair_id=knot_pair_id,
                pair_side=pair_side,
                graph_run_id=graph_run_id,
                run_id=run_id,
                result_disposition=result_disposition,
                recorded_at=recorded_at,
                validated_output=validated_output,
                strict_receipt_verifier=strict_receipt_verifier,
                failure_reason=failure_reason,
                cio_failure_phase=cio_failure_phase,
                cio_output_phase=cio_output_phase,
            )

    def append_knot_cio_proposal_execution_result(
        self,
        *,
        knot_pair_id: str,
        pair_side: str,
        graph_run_id: str,
        run_id: str,
        result_disposition: str,
        recorded_at: str,
        validated_output: Mapping[str, Any],
        strict_receipt_verifier: Any,
        failure_reason: str | None = None,
        cio_failure_phase: str | None = None,
        cio_output_phase: str | None = None,
    ) -> dict[str, Any]:
        """Persist a CIO proposal and its dependency ref in one transaction."""
        from mosaic.scorecard.knot_v2 import (
            append_knot_cio_proposal_ref,
            append_knot_pair_side_execution_result,
        )

        with self._connect() as conn:
            result = append_knot_pair_side_execution_result(
                conn,
                knot_pair_id=knot_pair_id,
                pair_side=pair_side,
                graph_run_id=graph_run_id,
                run_id=run_id,
                result_disposition=result_disposition,
                recorded_at=recorded_at,
                validated_output=validated_output,
                strict_receipt_verifier=strict_receipt_verifier,
                failure_reason=failure_reason,
                cio_failure_phase=cio_failure_phase,
                cio_output_phase=cio_output_phase,
            )
            proposal_output_id = result.get("proposal_output_id")
            if not isinstance(proposal_output_id, str) or not proposal_output_id:
                raise ValueError("accepted CIO proposal did not persist a proposal ID")
            proposal_ref = append_knot_cio_proposal_ref(
                conn,
                knot_pair_id=knot_pair_id,
                pair_side=pair_side,
                graph_run_id=graph_run_id,
                proposal_accepted_output_id=proposal_output_id,
                recorded_at=recorded_at,
            )
            return {**result, "cio_proposal_ref": proposal_ref}

    def prepare_outcome_schedule_plan(
        self,
        *,
        production_variant_roster_revision_id: str,
        graph_run_id: str,
        as_of: str,
        prepared_at: str,
        trading_calendar_snapshot: Mapping[str, Any],
        verified_event_candidates: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        from mosaic.scorecard.outcome_scheduler import prepare_outcome_schedule_plan

        with self._connect() as conn:
            return prepare_outcome_schedule_plan(
                conn,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                graph_run_id=graph_run_id,
                as_of=as_of,
                prepared_at=prepared_at,
                trading_calendar_snapshot=trading_calendar_snapshot,
                verified_event_candidates=verified_event_candidates,
            )

    def resolve_scheduled_sample_context(
        self, *, scheduled_sample_id: str
    ) -> dict[str, Any]:
        """Resolve immutable plan context for one scheduled outcome sample."""
        from mosaic.scorecard.darwinian_v2 import canonical_hash

        with self._connect() as conn:
            row = conn.execute(
                "SELECT s.record_json AS slot_json, p.record_json AS plan_json "
                "FROM outcome_schedule_slots_v2 s "
                "JOIN outcome_schedule_plans_v2 p USING(outcome_schedule_plan_id) "
                "WHERE s.scheduled_sample_id = ?",
                (scheduled_sample_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown scheduled_sample_id")
        slot = json.loads(row["slot_json"])
        plan = json.loads(row["plan_json"])
        if (
            slot.get("scheduled_sample_id") != scheduled_sample_id
            or slot.get("run_slot_kind") != "OUTCOME_SCHEDULED"
            or slot.get("outcome_schedule_plan_id")
            != plan.get("outcome_schedule_plan_id")
            or slot.get("outcome_schedule_slot_hash")
            != canonical_hash(
                {
                    key: value
                    for key, value in slot.items()
                    if key != "outcome_schedule_slot_hash"
                }
            )
            or plan.get("outcome_schedule_plan_hash")
            != canonical_hash(
                {
                    key: value
                    for key, value in plan.items()
                    if key != "outcome_schedule_plan_hash"
                }
            )
        ):
            raise ValueError("scheduled sample context hash/lineage mismatch")
        return {
            "scheduled_sample_id": scheduled_sample_id,
            "as_of": plan["as_of"],
            "agent_id": slot["agent_id"],
            "track_key_hash": slot["track_key_hash"],
            "outcome_schedule_plan_id": plan["outcome_schedule_plan_id"],
        }

    def freeze_scheduled_outcome_opportunity(
        self,
        *,
        outcome_schedule_plan_id: str,
        agent_id: str,
        qualification_predicate_version: str,
        member_refs: Sequence[Mapping[str, Any]],
        source_evidence_by_required_source_id: Mapping[str, Sequence[str]],
        projection_snapshot_hash: str,
    ) -> dict[str, Any]:
        from mosaic.scorecard.outcome_scheduler import freeze_scheduled_opportunity

        with self._connect() as conn:
            return freeze_scheduled_opportunity(
                conn,
                outcome_schedule_plan_id=outcome_schedule_plan_id,
                agent_id=agent_id,
                qualification_predicate_version=qualification_predicate_version,
                member_refs=member_refs,
                source_evidence_by_required_source_id=(
                    source_evidence_by_required_source_id
                ),
                projection_snapshot_hash=projection_snapshot_hash,
            )

    def record_scheduled_outcome_opportunity_failure(
        self,
        *,
        outcome_schedule_plan_id: str,
        agent_id: str,
        qualification_predicate_version: str,
        source_evidence_by_required_source_id: Mapping[str, Sequence[str]],
        error_codes: Sequence[str],
        attempted_at: str,
    ) -> dict[str, Any]:
        from mosaic.scorecard.outcome_scheduler import (
            record_scheduled_opportunity_failure,
        )

        with self._connect() as conn:
            return record_scheduled_opportunity_failure(
                conn,
                outcome_schedule_plan_id=outcome_schedule_plan_id,
                agent_id=agent_id,
                qualification_predicate_version=qualification_predicate_version,
                source_evidence_by_required_source_id=(
                    source_evidence_by_required_source_id
                ),
                error_codes=error_codes,
                attempted_at=attempted_at,
            )

    def create_no_evaluation_object_stage_skip(
        self,
        *,
        outcome_schedule_plan_id: str,
        agent_id: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        from mosaic.scorecard.outcome_scheduler import (
            create_no_evaluation_object_stage_skip,
        )

        with self._connect() as conn:
            return create_no_evaluation_object_stage_skip(
                conn,
                outcome_schedule_plan_id=outcome_schedule_plan_id,
                agent_id=agent_id,
                recorded_at=recorded_at,
            )

    def prepare_darwinian_v2_production_variant(
        self,
        *,
        binding: Mapping[str, Any],
        as_of: str,
    ) -> dict[str, Any]:
        from mosaic.scorecard.darwinian_v2 import prepare_production_variant

        with self._connect() as conn:
            return prepare_production_variant(conn, binding=binding, as_of=as_of)

    def refresh_darwinian_v2_evaluation_windows(
        self,
        *,
        production_variant_roster_revision_id: str,
        cutoff_at: str,
        trading_dates: Sequence[str],
    ) -> list[dict[str, Any]]:
        from mosaic.scorecard.darwinian_updates import refresh_evaluation_windows

        with self._connect() as conn:
            return refresh_evaluation_windows(
                conn,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                cutoff_at=cutoff_at,
                trading_dates=trading_dates,
            )

    def publish_darwinian_v2_weight_updates(
        self,
        *,
        production_variant_roster_revision_id: str,
        cutoff_at: str,
        trading_dates: Sequence[str],
    ) -> list[dict[str, Any]]:
        from mosaic.scorecard.darwinian_updates import publish_usage_weight_updates

        with self._connect() as conn:
            return publish_usage_weight_updates(
                conn,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                cutoff_at=cutoff_at,
                trading_dates=trading_dates,
            )

    def register_knot_research_track(
        self,
        *,
        knot_nomination_audit_id: str,
        production_variant_roster_revision_id: str,
        target_evaluation_track_key_hash: str,
        mutation_definition: Mapping[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import (
            build_knot_mutation_manifest,
            register_knot_research_track,
        )

        with self._connect() as conn:
            revision_row = conn.execute(
                "SELECT execution_behavior_release_id "
                "FROM darwinian_v2_production_variant_roster_revisions "
                "WHERE production_variant_roster_revision_id = ?",
                (production_variant_roster_revision_id,),
            ).fetchone()
            if revision_row is None:
                raise ValueError("unknown production variant roster revision")
            release = _load_trusted_execution_behavior_release(
                str(revision_row["execution_behavior_release_id"])
            )
            mutation_manifest = build_knot_mutation_manifest(
                mutation_definition=mutation_definition,
                execution_release_manifest=release,
                built_at=created_at,
            )
            return register_knot_research_track(
                conn,
                knot_nomination_audit_id=knot_nomination_audit_id,
                production_variant_roster_revision_id=(
                    production_variant_roster_revision_id
                ),
                target_evaluation_track_key_hash=target_evaluation_track_key_hash,
                mutation_manifest=mutation_manifest,
                execution_release_manifest=release,
                created_at=created_at,
            )

    def publish_knot_nomination_audit(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import publish_knot_nomination_audit

        with self._connect() as conn:
            return publish_knot_nomination_audit(conn, **kwargs)

    def preregister_knot_pair_assignment(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import preregister_knot_pair_assignment

        with self._connect() as conn:
            return preregister_knot_pair_assignment(conn, **kwargs)

    def publish_knot_research_schedule(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import publish_knot_research_schedule

        with self._connect() as conn:
            return publish_knot_research_schedule(conn, **kwargs)

    def freeze_knot_pair_input(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import freeze_knot_pair_input

        with self._connect() as conn:
            return freeze_knot_pair_input(conn, **kwargs)

    def resolve_knot_strict_schema_binding(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import resolve_knot_strict_schema_binding

        with self._connect() as conn:
            return resolve_knot_strict_schema_binding(conn, **kwargs)

    def resolve_knot_control_strict_schema_binding(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import (
            resolve_knot_control_strict_schema_binding,
        )

        with self._connect() as conn:
            return resolve_knot_control_strict_schema_binding(conn, **kwargs)

    def append_knot_research_score_record(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import append_knot_research_score_record

        with self._connect() as conn:
            return append_knot_research_score_record(conn, **kwargs)

    def append_knot_sector_inference_cost_audit(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import append_knot_sector_inference_cost_audit

        with self._connect() as conn:
            return append_knot_sector_inference_cost_audit(conn, **kwargs)

    def resolve_knot_sector_usage_binding(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import resolve_knot_sector_usage_binding

        with self._connect() as conn:
            return resolve_knot_sector_usage_binding(conn, **kwargs)

    def append_knot_control_dependency_result(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import append_knot_control_dependency_result

        with self._connect() as conn:
            return append_knot_control_dependency_result(conn, **kwargs)

    def append_knot_cio_dependency_blocked_audit(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import append_knot_cio_dependency_blocked_audit

        with self._connect() as conn:
            return append_knot_cio_dependency_blocked_audit(conn, **kwargs)

    def finalize_knot_pair(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import finalize_knot_pair

        with self._connect() as conn:
            return finalize_knot_pair(conn, **kwargs)

    def publish_knot_promotion_revision(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import publish_knot_promotion_revision

        release_id = kwargs.get("new_execution_behavior_release_id")
        kwargs["new_execution_release_manifest"] = (
            _load_trusted_execution_behavior_release(release_id)
            if isinstance(release_id, str) and release_id
            else None
        )
        with self._connect() as conn:
            return publish_knot_promotion_revision(conn, **kwargs)

    def publish_knot_promotion_batch(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import publish_knot_promotion_batch

        release_id = kwargs.get("new_execution_behavior_release_id")
        kwargs["new_execution_release_manifest"] = (
            _load_trusted_execution_behavior_release(str(release_id))
        )
        with self._connect() as conn:
            return publish_knot_promotion_batch(conn, **kwargs)

    def publish_knot_rollback_revision(self, **kwargs: Any) -> dict[str, Any]:
        from mosaic.scorecard.knot_v2 import publish_knot_rollback_revision

        release_id = kwargs.get("new_execution_behavior_release_id")
        kwargs["new_execution_release_manifest"] = (
            _load_trusted_execution_behavior_release(str(release_id))
        )
        with self._connect() as conn:
            return publish_knot_rollback_revision(conn, **kwargs)

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
                    target_weight_pct, current_weight_pct, delta_weight_pct,
                    position_decision, position_decision_reason, override_reason,
                    thesis_status, risk_flags_json, declared_knob_influence_ids_json,
                    declared_influence_rationale, verified_knob_audit_json,
                    decision_agent_audits_json, dissent_notes, rationale_snapshot,
                    replay_triggered, day_outcome_status, backtest_run_id
                ) VALUES (
                    :cohort, :agent, :ticker, :date, :action, :conviction,
                    :target_weight_pct, :current_weight_pct, :delta_weight_pct,
                    :position_decision, :position_decision_reason, :override_reason,
                    :thesis_status, :risk_flags_json, :declared_knob_influence_ids_json,
                    :declared_influence_rationale, :verified_knob_audit_json,
                    :decision_agent_audits_json, :dissent_notes, :rationale_snapshot,
                    :replay_triggered, :day_outcome_status, :backtest_run_id
                )
                ON CONFLICT(cohort, agent, ticker, date) DO UPDATE SET
                    action = excluded.action,
                    conviction = excluded.conviction,
                    target_weight_pct = excluded.target_weight_pct,
                    current_weight_pct = excluded.current_weight_pct,
                    delta_weight_pct = excluded.delta_weight_pct,
                    position_decision = excluded.position_decision,
                    position_decision_reason = excluded.position_decision_reason,
                    override_reason = excluded.override_reason,
                    thesis_status = excluded.thesis_status,
                    risk_flags_json = excluded.risk_flags_json,
                    declared_knob_influence_ids_json = excluded.declared_knob_influence_ids_json,
                    declared_influence_rationale = excluded.declared_influence_rationale,
                    verified_knob_audit_json = excluded.verified_knob_audit_json,
                    decision_agent_audits_json = excluded.decision_agent_audits_json,
                    dissent_notes = excluded.dissent_notes,
                    rationale_snapshot = excluded.rationale_snapshot,
                    replay_triggered = excluded.replay_triggered,
                    day_outcome_status = excluded.day_outcome_status,
                    backtest_run_id = excluded.backtest_run_id
                """,
                rows,
            )
        return len(rows)

    def append_agent_display_narratives_from_state(
        self, state: dict[str, Any]
    ) -> int:
        """Persist the exact 28-Agent UI narrative sidecar for one live run.

        The bundle is derived by TypeScript from accepted structured outputs.
        It is intentionally stored outside recommendation, outcome, Darwinian,
        and KNOT tables so no decision or evaluation path can consume it.
        """
        bundle = state.get("agent_display_narratives")
        if not isinstance(bundle, dict):
            raise ValueError("agent_display_narratives must be an object")
        bundle_fields = {
            "schema_version",
            "trace_id",
            "cohort",
            "as_of_date",
            "language",
            "narrative_count",
            "narratives",
            "bundle_hash",
        }
        if set(bundle) != bundle_fields:
            raise ValueError("agent display narrative bundle fields mismatch")
        if bundle.get("schema_version") != "agent_display_narrative_bundle_v1":
            raise ValueError("agent display narrative bundle version mismatch")

        from mosaic.scorecard.darwinian_v2 import canonical_hash

        bundle_body = {
            key: value for key, value in bundle.items() if key != "bundle_hash"
        }
        if bundle.get("bundle_hash") != canonical_hash(bundle_body):
            raise ValueError("agent display narrative bundle_hash mismatch")

        cohort = state.get("active_cohort")
        date = state.get("as_of_date")
        trace_id = state.get("trace_id")
        if not all(isinstance(value, str) and value.strip() for value in (cohort, date, trace_id)):
            raise ValueError("agent display narratives require cohort, date, and trace_id")
        if (
            bundle.get("cohort") != cohort
            or bundle.get("as_of_date") != date
            or bundle.get("trace_id") != trace_id
        ):
            raise ValueError("agent display narrative bundle owner mismatch")

        language = bundle.get("language")
        bundle_hash = bundle.get("bundle_hash")
        narratives = bundle.get("narratives")
        if language not in ("zh", "en"):
            raise ValueError("agent display narrative language must be zh or en")
        if not _is_sha256(bundle_hash):
            raise ValueError("agent display narrative bundle_hash must be sha256")
        if (
            bundle.get("narrative_count") != 28
            or not isinstance(narratives, list)
            or len(narratives) != 28
        ):
            raise ValueError("agent display narrative bundle must contain exactly 28 Agents")

        from mosaic.bridge.tool_capabilities import AGENTS_BY_LAYER, ALL_AGENT_IDS

        layer_by_agent = {
            agent: layer for layer, agents in AGENTS_BY_LAYER.items() for agent in agents
        }
        if [row.get("agent_id") for row in narratives if isinstance(row, dict)] != list(
            ALL_AGENT_IDS
        ):
            raise ValueError("agent display narrative roster or order mismatch")

        accepted_refs = state.get("accepted_output_refs", {})
        accepted_records = state.get("accepted_output_records", [])
        stage_skips = state.get("outcome_stage_skips", {})
        if not isinstance(accepted_refs, Mapping):
            raise ValueError("agent display narrative accepted_output_refs must be an object")
        if not isinstance(accepted_records, list):
            raise ValueError("agent display narrative accepted_output_records must be an array")
        if not isinstance(stage_skips, Mapping):
            raise ValueError("agent display narrative outcome_stage_skips must be an object")

        records_by_id: dict[str, Mapping[str, Any]] = {}
        for record in accepted_records:
            if not isinstance(record, Mapping):
                raise ValueError("agent display narrative accepted records must be objects")
            record_id = record.get("accepted_output_id")
            record_agent = record.get("agent_id")
            record_kind = record.get("accepted_output_kind")
            if (
                not isinstance(record_id, str)
                or not record_id
                or record_id in records_by_id
            ):
                raise ValueError("agent display narrative accepted record ID is invalid")
            expected_kinds = (
                {"MACRO_TRANSMISSION"}
                if record_agent in AGENTS_BY_LAYER["macro"]
                else {"RELATIONSHIP_GRAPH"}
                if record_agent == "relationship_mapper"
                else {"STANDARD_SECTOR_SELECTION"}
                if record_agent in AGENTS_BY_LAYER["sector"]
                else {"SUPERINVESTOR_SELECTION"}
                if record_agent in AGENTS_BY_LAYER["superinvestor"]
                else {"CRO_RISK_REVIEW"}
                if record_agent == "cro"
                else {"ALPHA_DISCOVERY"}
                if record_agent == "alpha_discovery"
                else {"EXECUTION_ASSESSMENT"}
                if record_agent == "autonomous_execution"
                else {"CIO_PROPOSAL", "CIO_FINAL"}
                if record_agent == "cio"
                else set()
            )
            if record_kind not in expected_kinds:
                raise ValueError(
                    "agent display narrative accepted record kind/owner mismatch"
                )
            record_as_of = record.get("as_of")
            if (
                record.get("graph_run_id") != trace_id
                or record.get("cohort_id") != cohort
                or record.get("language") != language
                or not isinstance(record_as_of, str)
                or record_as_of[:10] != date
            ):
                raise ValueError(
                    "agent display narrative accepted record run owner mismatch"
                )
            without_hash = {
                key: value for key, value in record.items() if key != "accepted_output_hash"
            }
            if record.get("accepted_output_hash") != canonical_hash(without_hash):
                raise ValueError("agent display narrative accepted record hash mismatch")
            records_by_id[record_id] = record

        refs_by_agent: dict[str, list[Mapping[str, Any]]] = {}
        referenced_record_ids: set[str] = set()
        for ref_key, ref in accepted_refs.items():
            if not isinstance(ref, Mapping):
                raise ValueError("agent display narrative accepted refs must be objects")
            agent_id = ref.get("agent_id")
            record_id = ref.get("accepted_output_id")
            if not isinstance(agent_id, str) or agent_id not in layer_by_agent:
                raise ValueError("agent display narrative accepted ref owner is invalid")
            if ref_key != f"{ref.get('accepted_output_kind')}:{agent_id}":
                raise ValueError("agent display narrative accepted ref key mismatch")
            record = records_by_id.get(str(record_id))
            if record is None or any(
                ref.get(field) != record.get(field)
                for field in (
                    "agent_id",
                    "accepted_output_kind",
                    "accepted_output_id",
                    "accepted_output_hash",
                )
            ):
                raise ValueError("agent display narrative accepted ref lineage mismatch")
            referenced_record_ids.add(str(record_id))
            refs_by_agent.setdefault(agent_id, []).append(ref)
        if referenced_record_ids != set(records_by_id):
            raise ValueError("agent display narrative accepted record closure mismatch")

        def narrative_ref(agent_id: str) -> Mapping[str, Any] | None:
            refs = refs_by_agent.get(agent_id, [])
            if agent_id == "cio":
                finals = [
                    ref
                    for ref in refs
                    if ref.get("accepted_output_kind") == "CIO_FINAL"
                ]
                if len(finals) > 1:
                    raise ValueError("cio display narrative has duplicate final refs")
                return finals[0] if finals else None
            if len(refs) > 1:
                raise ValueError(f"{agent_id}: display narrative has duplicate accepted refs")
            return refs[0] if refs else None

        created_at = datetime.now(timezone.utc).isoformat()
        rows: list[dict[str, Any]] = []
        narrative_fields = {
            "schema_version",
            "narrative_id",
            "agent_id",
            "layer",
            "language",
            "source",
            "source_output_id",
            "source_output_hash",
            "narrative_text",
            "ui_only",
        }
        for row in narratives:
            if not isinstance(row, dict):
                raise ValueError("agent display narrative rows must be objects")
            if set(row) != narrative_fields:
                raise ValueError("agent display narrative row fields mismatch")
            agent = row.get("agent_id")
            source = row.get("source")
            source_output_id = row.get("source_output_id")
            narrative_text = row.get("narrative_text")
            narrative_id = row.get("narrative_id")
            if row.get("schema_version") != "agent_display_narrative_v1":
                raise ValueError(f"{agent}: agent display narrative version mismatch")
            if row.get("layer") != layer_by_agent.get(agent):
                raise ValueError(f"{agent}: agent display narrative layer mismatch")
            if row.get("language") != language or row.get("ui_only") is not True:
                raise ValueError(f"{agent}: agent display narrative UI contract mismatch")
            if source not in (
                "ACCEPTED_OUTPUT",
                "NO_EVALUATION_OBJECT",
                "NON_PRODUCTION_STRUCTURED_OUTPUT",
            ):
                raise ValueError(f"{agent}: agent display narrative source is invalid")
            if source == "ACCEPTED_OUTPUT" and not (
                isinstance(source_output_id, str) and source_output_id.strip()
            ):
                raise ValueError(f"{agent}: accepted narrative lacks source_output_id")
            if source != "ACCEPTED_OUTPUT" and source_output_id is not None:
                raise ValueError(f"{agent}: non-accepted narrative cannot name an output id")
            if source_output_id is not None and not isinstance(source_output_id, str):
                raise ValueError(f"{agent}: source_output_id must be a string or null")
            if not _is_sha256(row.get("source_output_hash")):
                raise ValueError(f"{agent}: source_output_hash must be sha256")
            accepted_ref = narrative_ref(str(agent))
            skip = stage_skips.get(agent)
            if accepted_ref is not None and skip is not None:
                raise ValueError(f"{agent}: narrative cannot be accepted and skipped")
            if source == "ACCEPTED_OUTPUT" and (
                accepted_ref is None
                or source_output_id != accepted_ref.get("accepted_output_id")
                or row["source_output_hash"]
                != accepted_ref.get("accepted_output_hash")
            ):
                raise ValueError(f"{agent}: accepted narrative lineage mismatch")
            if source == "NO_EVALUATION_OBJECT":
                if not isinstance(skip, Mapping) or skip.get("agent_id") != agent:
                    raise ValueError(f"{agent}: skipped narrative lineage is missing")
                skip_body = {
                    key: value for key, value in skip.items() if key != "stage_skip_hash"
                }
                if (
                    skip.get("stage_skip_hash") != canonical_hash(skip_body)
                    or row["source_output_hash"] != skip.get("stage_skip_hash")
                ):
                    raise ValueError(f"{agent}: skipped narrative lineage mismatch")
            elif skip is not None:
                raise ValueError(f"{agent}: non-skipped narrative has a stage skip")
            if source == "NON_PRODUCTION_STRUCTURED_OUTPUT":
                if accepted_ref is not None:
                    raise ValueError(
                        f"{agent}: non-production narrative has accepted lineage"
                    )
                raise ValueError(
                    f"{agent}: non-production display narratives cannot be persisted"
                )
            narrative_body = {
                key: value for key, value in row.items() if key != "narrative_id"
            }
            expected_narrative_id = (
                "agent-display:"
                + canonical_hash(narrative_body).removeprefix("sha256:")
            )
            if not (
                isinstance(narrative_id, str)
                and narrative_id == expected_narrative_id
            ):
                raise ValueError(f"{agent}: narrative_id hash mismatch")
            if not (
                isinstance(narrative_text, str)
                and narrative_text.strip()
                and len(narrative_text) <= 2_000
            ):
                raise ValueError(f"{agent}: narrative_text must contain 1-2000 characters")
            if source == "NO_EVALUATION_OBJECT":
                expected_text = (
                    "本轮没有符合该角色合同的可评价对象，因此运行时未调用模型并确定性"
                    "跳过该阶段。该结果不是中性判断。"
                    if language == "zh"
                    else "No object satisfied this role's evaluation contract, so runtime "
                    "skipped the model call deterministically. This is not a neutral "
                    "judgment."
                )
            else:
                accepted_record = records_by_id.get(str(source_output_id))
                output = (
                    accepted_record.get("output")
                    if isinstance(accepted_record, Mapping)
                    else None
                )
                payload = output.get("payload") if isinstance(output, Mapping) else None
                if not isinstance(payload, Mapping):
                    raise ValueError(
                        f"{agent}: accepted narrative lacks trusted structured output"
                    )
                expected_text = render_agent_display_narrative_text(
                    layer=row["layer"],
                    agent_id=str(agent),
                    output=payload,
                    language=language,
                    accepted_output_kind=(
                        accepted_record.get("accepted_output_kind")
                        if isinstance(accepted_record, Mapping)
                        else None
                    ),
                )
            if narrative_text != expected_text:
                raise ValueError(
                    f"{agent}: narrative_text does not match trusted structured output"
                )
            rows.append(
                {
                    "cohort": cohort,
                    "date": date,
                    "trace_id": trace_id,
                    "bundle_hash": bundle_hash,
                    "agent": agent,
                    "layer": row["layer"],
                    "language": language,
                    "source": source,
                    "source_output_id": source_output_id,
                    "source_output_hash": row["source_output_hash"],
                    "narrative_id": narrative_id,
                    "narrative_text": narrative_text,
                    "created_at": created_at,
                }
            )

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO agent_display_narratives (
                    cohort, date, trace_id, bundle_hash, agent, layer, language,
                    source, source_output_id, source_output_hash, narrative_id,
                    narrative_text, ui_only, created_at
                ) VALUES (
                    :cohort, :date, :trace_id, :bundle_hash, :agent, :layer, :language,
                    :source, :source_output_id, :source_output_hash, :narrative_id,
                    :narrative_text, 1, :created_at
                )
                ON CONFLICT(cohort, date, trace_id, agent) DO NOTHING
                """,
                rows,
            )
            persisted = conn.execute(
                "SELECT cohort, date, trace_id, bundle_hash, agent, layer, language, "
                "source, source_output_id, source_output_hash, narrative_id, "
                "narrative_text, ui_only FROM agent_display_narratives "
                "WHERE cohort = ? AND date = ? AND trace_id = ?",
                (cohort, date, trace_id),
            ).fetchall()
            persisted_by_agent = {row["agent"]: dict(row) for row in persisted}
            if set(persisted_by_agent) != set(ALL_AGENT_IDS):
                raise ValueError("agent display narrative append is incomplete")
            for expected in rows:
                actual = persisted_by_agent[expected["agent"]]
                comparable = {
                    key: value
                    for key, value in expected.items()
                    if key != "created_at"
                }
                comparable["ui_only"] = 1
                if actual != comparable:
                    raise ValueError(
                        f"{expected['agent']}: conflicting append-only display narrative"
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
            "WHERE scored_at IS NULL AND day_outcome_status = 'accepted'"
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
                    cohort, agent, date, vote, signal, confidence, raw_output_json,
                    consensus_stance, consensus_score, influence_weight_equal,
                    prompt_repo_id, prompt_sha256, day_outcome_status, backtest_run_id
                ) VALUES (
                    :cohort, :agent, :date, :vote, :signal, :confidence, :raw_output_json,
                    :consensus_stance, :consensus_score, :influence_weight_equal,
                    :prompt_repo_id, :prompt_sha256, :day_outcome_status, :backtest_run_id
                )
                ON CONFLICT(cohort, agent, date) DO UPDATE SET
                    vote = excluded.vote,
                    signal = excluded.signal,
                    confidence = excluded.confidence,
                    raw_output_json = excluded.raw_output_json,
                    consensus_stance = excluded.consensus_stance,
                    consensus_score = excluded.consensus_score,
                    influence_weight_equal = excluded.influence_weight_equal,
                    prompt_repo_id = excluded.prompt_repo_id,
                    prompt_sha256 = excluded.prompt_sha256,
                    day_outcome_status = excluded.day_outcome_status,
                    backtest_run_id = excluded.backtest_run_id
                """,
                rows,
            )
        return len(rows)

    def list_pending_macro(
        self, cohort: Optional[str] = None, before_date: Optional[str] = None
    ) -> list[PendingMacroRow]:
        """Macro signals with scored_at IS NULL (and date <= before_date)."""
        sql = (
            "SELECT id, cohort, agent, date, vote, signal, confidence, influence_weight_equal "
            "FROM macro_signals "
            "WHERE scored_at IS NULL AND day_outcome_status = 'accepted'"
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
                    date=r["date"], vote=r["vote"], signal=r["signal"],
                    confidence=r["confidence"],
                    influence_weight_equal=r["influence_weight_equal"],
                )
                for r in conn.execute(sql, params).fetchall()
            ]

    def list_macro_signals(
        self,
        cohort: str,
        *,
        since_date: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return raw macro signal rows, regardless of scoring status."""
        sql = (
            "SELECT id, cohort, agent, date, vote, signal, confidence, label_type, "
            "       label_source_status, label_value_5d, benchmark_return_5d, "
            "       terminal_return_5d, max_drawdown_5d, realized_volatility_5d, "
            "       path_metric_5d, source_series_id, realized_label, hit_5d, raw_macro_score_5d, "
            "       influence_weight_equal, effective_macro_score_5d, scored_at "
            "FROM macro_signals WHERE cohort = ? AND day_outcome_status = 'accepted'"
        )
        params: list[Any] = [cohort]
        if since_date:
            sql += " AND date >= ?"
            params.append(since_date)
        if before_date:
            sql += " AND date <= ?"
            params.append(before_date)
        sql += " ORDER BY date, id"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def update_macro_scoring(self, row_id: int, fields: dict[str, Any]) -> None:
        """Fill macro scoring columns for one row. ``fields`` keys are column names."""
        allowed = {
            "label_type", "label_source_status", "label_value_5d", "terminal_return_5d",
            "max_drawdown_5d", "realized_volatility_5d", "path_metric_5d",
            "benchmark_return_5d", "source_series_id", "realized_label", "hit_5d",
            "raw_macro_score_5d", "influence_weight_equal", "effective_macro_score_5d",
            "scored_at",
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
            "SELECT agent, vote, signal, hit_5d, raw_macro_score_5d, effective_macro_score_5d, "
            "influence_weight_equal, label_type, label_source_status, date "
            "FROM macro_signals WHERE cohort = ? AND scored_at IS NOT NULL "
            "AND day_outcome_status = 'accepted'"
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
            label_counts: dict[str, int] = {}
            status_counts: dict[str, int] = {}
            latest_label_type = None
            latest_date = max((r["date"] for r in recs), default=None)
            for r in recs:
                if r["label_type"]:
                    label_counts[str(r["label_type"])] = label_counts.get(str(r["label_type"]), 0) + 1
                if r["label_source_status"]:
                    status = str(r["label_source_status"])
                    status_counts[status] = status_counts.get(status, 0) + 1
                if latest_date is not None and r["date"] == latest_date and r["label_type"]:
                    latest_label_type = str(r["label_type"])
            status_total = sum(status_counts.values())
            out.append(
                {
                    "agent": agent,
                    "n_obs": len(recs),
                    "mean_raw_macro_score_5d": (sum(raws) / len(raws)) if raws else None,
                    "mean_effective_macro_score_5d": (sum(effs) / len(effs)) if effs else None,
                    "hit_rate_5d": (sum(hits) / len(hits)) if hits else None,
                    "mean_influence_weight_equal": (sum(infs) / len(infs)) if infs else None,
                    "latest_label_type": latest_label_type,
                    "label_type_counts": label_counts,
                    "label_source_status_counts": status_counts,
                    "primary_label_rate": (
                        status_counts.get("primary", 0) / status_total
                    ) if status_total else None,
                    "fallback_label_rate": (
                        status_counts.get("fallback", 0) / status_total
                    ) if status_total else None,
                    "missing_label_rate": (
                        status_counts.get("missing", 0) / status_total
                    ) if status_total else None,
                    "sharpe_window": _sharpe(raws),
                    "latest_signal_date": latest_date,
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
            "       terminal_return_5d, max_drawdown_5d, realized_volatility_5d, "
            "       path_metric_5d, source_series_id, realized_label, hit_5d, raw_macro_score_5d, "
            "       influence_weight_equal, effective_macro_score_5d, scored_at "
            "FROM macro_signals "
            "WHERE cohort = ? AND scored_at IS NOT NULL AND raw_macro_score_5d IS NOT NULL "
            "AND day_outcome_status = 'accepted'"
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

    # ── macro data-source stores (plan: macro_series / macro_documents / label sources)

    @staticmethod
    def _json_or_none(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def append_macro_series(self, rows: dict[str, Any] | list[dict[str, Any]]) -> int:
        """Upsert point-in-time macro series observations."""
        batch = [rows] if isinstance(rows, dict) else list(rows)
        if not batch:
            return 0
        now = self._now_iso()
        norm_rows = []
        for row in batch:
            norm_rows.append(
                {
                    "series_id": row["series_id"],
                    "source": row["source"],
                    "endpoint_name": row.get("endpoint_name"),
                    "instrument": row.get("instrument"),
                    "date": row["date"],
                    "value": row.get("value"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                    "metadata_json": self._json_or_none(row.get("metadata_json", row.get("metadata"))),
                    "fetched_at": row.get("fetched_at") or now,
                    "as_of_date": row.get("as_of_date") or row["date"],
                }
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO macro_series (
                    series_id, source, endpoint_name, instrument, date, value,
                    open, high, low, close, volume, metadata_json, fetched_at, as_of_date
                ) VALUES (
                    :series_id, :source, :endpoint_name, :instrument, :date, :value,
                    :open, :high, :low, :close, :volume, :metadata_json, :fetched_at, :as_of_date
                )
                ON CONFLICT(series_id, date, as_of_date) DO UPDATE SET
                    source = excluded.source,
                    endpoint_name = excluded.endpoint_name,
                    instrument = excluded.instrument,
                    value = excluded.value,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    metadata_json = excluded.metadata_json,
                    fetched_at = excluded.fetched_at
                """,
                norm_rows,
            )
        return len(norm_rows)

    def list_macro_series(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        as_of_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM macro_series WHERE series_id = ?"
        params: list[Any] = [series_id]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        if as_of_date:
            sql += " AND as_of_date <= ?"
            params.append(as_of_date)
        sql += " ORDER BY date, as_of_date"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def append_macro_documents(self, rows: dict[str, Any] | list[dict[str, Any]]) -> int:
        """Upsert OpenCLI/Tushare document observations by content hash/discovery time."""
        batch = [rows] if isinstance(rows, dict) else list(rows)
        if not batch:
            return 0
        now = self._now_iso()
        norm_rows = []
        for row in batch:
            norm_rows.append(
                {
                    "document_id": row.get("document_id") or row["content_hash"],
                    "source": row["source"],
                    "channel": row.get("channel"),
                    "query": row.get("query"),
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "published_at": row.get("published_at"),
                    "discovered_at": row.get("discovered_at") or now,
                    "content_hash": row["content_hash"],
                    "content_excerpt": row.get("content_excerpt"),
                    "agent_tags_json": self._json_or_none(row.get("agent_tags_json", row.get("agent_tags"))),
                    "event_tags_json": self._json_or_none(row.get("event_tags_json", row.get("event_tags"))),
                    "sentiment_score": row.get("sentiment_score"),
                    "quality_score": row.get("quality_score"),
                }
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO macro_documents (
                    document_id, source, channel, query, title, url, published_at,
                    discovered_at, content_hash, content_excerpt, agent_tags_json,
                    event_tags_json, sentiment_score, quality_score
                ) VALUES (
                    :document_id, :source, :channel, :query, :title, :url, :published_at,
                    :discovered_at, :content_hash, :content_excerpt, :agent_tags_json,
                    :event_tags_json, :sentiment_score, :quality_score
                )
                ON CONFLICT(content_hash, discovered_at) DO UPDATE SET
                    document_id = excluded.document_id,
                    source = excluded.source,
                    channel = excluded.channel,
                    query = excluded.query,
                    title = excluded.title,
                    url = excluded.url,
                    published_at = excluded.published_at,
                    content_excerpt = excluded.content_excerpt,
                    agent_tags_json = excluded.agent_tags_json,
                    event_tags_json = excluded.event_tags_json,
                    sentiment_score = excluded.sentiment_score,
                    quality_score = excluded.quality_score
                """,
                norm_rows,
            )
        return len(norm_rows)

    def list_macro_documents(
        self,
        *,
        source: Optional[str] = None,
        agent: Optional[str] = None,
        discovered_at_lte: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM macro_documents WHERE 1 = 1"
        params: list[Any] = []
        if source:
            sql += " AND source = ?"
            params.append(source)
        if agent:
            sql += " AND agent_tags_json LIKE ?"
            params.append(f"%{agent}%")
        if discovered_at_lte:
            sql += " AND discovered_at <= ?"
            params.append(discovered_at_lte)
        sql += " ORDER BY discovered_at, id"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def upsert_macro_label_source(self, row: dict[str, Any]) -> None:
        now = self._now_iso()
        payload = {
            "agent": row["agent"],
            "label_type": row["label_type"],
            "primary_series_id": row.get("primary_series_id"),
            "proxy_series_ids_json": self._json_or_none(
                row.get("proxy_series_ids_json", row.get("proxy_series_ids"))
            ),
            "orientation_rule": row.get("orientation_rule"),
            "lookback_days": row.get("lookback_days"),
            "forward_horizon_trading_days": row.get("forward_horizon_trading_days"),
            "fallback_label": row.get("fallback_label"),
            "availability_status": row.get("availability_status"),
            "implementation_status": row.get("implementation_status"),
            "updated_at": row.get("updated_at") or now,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO macro_label_sources (
                    agent, label_type, primary_series_id, proxy_series_ids_json,
                    orientation_rule, lookback_days, forward_horizon_trading_days,
                    fallback_label, availability_status, implementation_status, updated_at
                ) VALUES (
                    :agent, :label_type, :primary_series_id, :proxy_series_ids_json,
                    :orientation_rule, :lookback_days, :forward_horizon_trading_days,
                    :fallback_label, :availability_status, :implementation_status, :updated_at
                )
                ON CONFLICT(agent, label_type) DO UPDATE SET
                    primary_series_id = excluded.primary_series_id,
                    proxy_series_ids_json = excluded.proxy_series_ids_json,
                    orientation_rule = excluded.orientation_rule,
                    lookback_days = excluded.lookback_days,
                    forward_horizon_trading_days = excluded.forward_horizon_trading_days,
                    fallback_label = excluded.fallback_label,
                    availability_status = excluded.availability_status,
                    implementation_status = excluded.implementation_status,
                    updated_at = excluded.updated_at
                """,
                payload,
            )

    def list_macro_label_sources(self, agent: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM macro_label_sources"
        params: list[Any] = []
        if agent:
            sql += " WHERE agent = ?"
            params.append(agent)
        sql += " ORDER BY agent, label_type"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

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
            "WHERE cohort = ? AND alpha_5d IS NOT NULL AND day_outcome_status = 'accepted'"
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
            "WHERE cohort = ? AND day_outcome_status = 'accepted'"
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
                "SELECT MAX(date) AS d FROM recommendations WHERE cohort = ? AND agent = 'cio' "
                "AND day_outcome_status = 'accepted'",
                (cohort,),
            ).fetchone()
            latest = row["d"] if row else None
            if not latest:
                return {"cohort": cohort, "date": None, "actions": []}
            cur = conn.execute(
                "SELECT ticker, action, target_weight_pct, rationale_snapshot, "
                "       forward_return_5d, scored_at, current_weight_pct, delta_weight_pct, "
                "       position_decision, position_decision_reason, override_reason, "
                "       thesis_status, risk_flags_json, declared_knob_influence_ids_json, "
                "       declared_influence_rationale, verified_knob_audit_json, "
                "       decision_agent_audits_json, dissent_notes "
                "FROM recommendations WHERE cohort = ? AND agent = 'cio' AND date = ? "
                "AND day_outcome_status = 'accepted' "
                "ORDER BY target_weight_pct DESC, ticker",
                (cohort, latest),
            )
            return {"cohort": cohort, "date": latest, "actions": [dict(r) for r in cur.fetchall()]}

    def get_latest_agent_display_narratives(self, cohort: str) -> dict[str, Any]:
        """Return the latest complete UI-only Agent narrative bundle."""
        with self._connect() as conn:
            latest = conn.execute(
                "SELECT date, trace_id, bundle_hash, language "
                "FROM agent_display_narratives WHERE cohort = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (cohort,),
            ).fetchone()
            if not latest:
                return {
                    "schema_version": "agent_display_narrative_bundle_v1",
                    "cohort": cohort,
                    "date": None,
                    "trace_id": None,
                    "bundle_hash": None,
                    "language": None,
                    "narratives": [],
                }
            rows = conn.execute(
                "SELECT agent AS agent_id, layer, language, source, source_output_id, "
                "source_output_hash, narrative_id, narrative_text, ui_only "
                "FROM agent_display_narratives "
                "WHERE cohort = ? AND date = ? AND trace_id = ?",
                (cohort, latest["date"], latest["trace_id"]),
            ).fetchall()

        from mosaic.bridge.tool_capabilities import ALL_AGENT_IDS

        by_agent = {row["agent_id"]: dict(row) for row in rows}
        narratives = []
        for agent in ALL_AGENT_IDS:
            row = by_agent.get(agent)
            if row is None:
                raise ValueError("latest agent display narrative bundle is incomplete")
            row["schema_version"] = "agent_display_narrative_v1"
            row["ui_only"] = bool(row["ui_only"])
            narratives.append(row)
        return {
            "schema_version": "agent_display_narrative_bundle_v1",
            "cohort": cohort,
            "date": latest["date"],
            "trace_id": latest["trace_id"],
            "bundle_hash": latest["bundle_hash"],
            "language": latest["language"],
            "narratives": narratives,
        }

    def compute_win_rate(
        self, cohort: str, since_date: Optional[str] = None, agent: str = "cio"
    ) -> list[dict[str, Any]]:
        """Per-ticker directional hit rate over SCORED rows: a pick "wins" when
        sign(action) · forward_return_5d > 0. HOLD rows carry no directional bet
        and are excluded. Returns rows sorted by win_rate desc, with n + avg
        forward return so a high rate on n=1 is visible as low-confidence."""
        sql = (
            "SELECT ticker, action, forward_return_5d FROM recommendations "
            "WHERE cohort = ? AND agent = ? AND forward_return_5d IS NOT NULL "
            "AND day_outcome_status = 'accepted'"
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
        *,
        agent_run_audits: Optional[list[dict[str, Any]]] = None,
        decision_disposition: Optional[str] = None,
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
                raise ValueError("backtest action requires a non-empty ticker")
            if action not in ("BUY", "SELL", "HOLD", "REDUCE"):
                raise ValueError(f"{ticker}: invalid backtest action {action!r}")
            if not isinstance(target_weight, (int, float)):
                raise ValueError(f"{ticker}: target_weight must be numeric")
            if not 0 <= float(target_weight) <= 1:
                raise ValueError(f"{ticker}: target_weight must be within [0, 1]")
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
        audits = agent_run_audits or []
        audit_keys = {(audit.get("agent"), audit.get("stage")) for audit in audits}
        accepted = len(audits) == RUNTIME_AGENT_STAGE_COUNT and all(
            audit.get("status") in ("accepted", "accepted_empty") for audit in audits
        ) and len(audit_keys) == RUNTIME_AGENT_STAGE_COUNT
        if agent_run_audits is not None and not accepted:
            raise ValueError(
                "backtest day requires "
                f"{RUNTIME_AGENT_STAGE_COUNT} unique accepted agent-stage audits"
            )
        if decision_disposition not in (
            None,
            "TARGET_PORTFOLIO",
            "HOLD_CURRENT",
            "ALL_CASH",
        ):
            raise ValueError("invalid decision_disposition")
        if accepted and decision_disposition is None:
            raise ValueError("accepted backtest day requires decision_disposition")
        if decision_disposition == "TARGET_PORTFOLIO" and not rows:
            raise ValueError("TARGET_PORTFOLIO requires portfolio actions")
        if decision_disposition == "ALL_CASH" and any(
            row["action"] != "SELL" or row["target_weight"] > 1e-9 for row in rows
        ):
            raise ValueError("ALL_CASH actions must be zero-target SELL exits")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM backtest_actions WHERE run_id = ? AND trade_date = ?",
                (run_id, trade_date),
            )
            if rows:
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
            conn.execute(
                "DELETE FROM agent_run_outcomes WHERE run_id = ? AND trade_date = ?",
                (run_id, trade_date),
            )
            if audits:
                conn.executemany(
                    """
                    INSERT INTO agent_run_outcomes (
                        run_id, trade_date, agent, stage, status, output_source,
                        attempt_count, repair_count, stop_reason, audit_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            trade_date,
                            audit.get("agent"),
                            audit.get("stage"),
                            audit.get("status"),
                            audit.get("output_source", "none"),
                            int(audit.get("attempt_count", 0)),
                            int(audit.get("repair_count", 0)),
                            audit.get("stop_reason", "unknown"),
                            json.dumps(audit, ensure_ascii=False, sort_keys=True),
                        )
                        for audit in audits
                    ],
                )
            # Written last in the same transaction: consumers only see a complete accepted day.
            conn.execute(
                """
                INSERT INTO backtest_day_outcomes (
                    run_id, trade_date, status, decision_disposition, action_count, accepted_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, trade_date) DO UPDATE SET
                    status = excluded.status,
                    decision_disposition = excluded.decision_disposition,
                    action_count = excluded.action_count,
                    accepted_at = excluded.accepted_at
                """,
                (
                    run_id,
                    trade_date,
                    "accepted" if accepted else "legacy_unverified",
                    decision_disposition,
                    len(rows),
                    now if accepted else None,
                ),
            )
        return len(rows)

    def complete_backtest_run(self, run_id: int) -> None:
        """Mark a backtest run as fully populated (stage-1 done)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            invalid = conn.execute(
                "SELECT trade_date, status FROM backtest_day_outcomes "
                "WHERE run_id = ? AND status <> 'accepted' ORDER BY trade_date LIMIT 1",
                (run_id,),
            ).fetchone()
            if invalid:
                raise ValueError(
                    f"backtest day {invalid['trade_date']} is {invalid['status']}; "
                    "run cannot be completed"
                )
            accepted_count = conn.execute(
                "SELECT COUNT(*) AS n FROM backtest_day_outcomes "
                "WHERE run_id = ? AND status = 'accepted'",
                (run_id,),
            ).fetchone()["n"]
            if accepted_count == 0:
                raise ValueError("backtest run has no accepted day outcomes")
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

    def is_backtest_day_accepted(
        self,
        run_id: int,
        trade_date: str,
        decision_disposition: Optional[str] = None,
    ) -> bool:
        """Return whether the strict backtest gate accepted this exact day."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, decision_disposition FROM backtest_day_outcomes "
                "WHERE run_id = ? AND trade_date = ?",
                (run_id, trade_date),
            ).fetchone()
            return bool(
                row
                and row["status"] == "accepted"
                and (
                    decision_disposition is None
                    or row["decision_disposition"] == decision_disposition
                )
            )

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
            "SELECT a.trade_date, a.ticker, a.action, a.target_weight, a.holding_period, "
            "       a.dissent_notes FROM backtest_actions AS a "
            "JOIN backtest_day_outcomes AS o "
            "  ON o.run_id = a.run_id AND o.trade_date = a.trade_date "
            "WHERE a.run_id = ? AND o.status = 'accepted'"
        )
        params: list[Any] = [run_id]
        if trade_date:
            sql += " AND a.trade_date = ?"
            params.append(trade_date)
        sql += " ORDER BY a.trade_date, a.ticker"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def summarize_backtest_actions(self, run_id: int) -> dict[str, Any]:
        """Aggregate cached stage-1 backtest actions without invoking qlib.

        This powers operator/TUI carry-over diagnostics. Performance metrics
        that require stage-2 market replay are reported as unavailable rather
        than inferred from cached target weights.
        """
        actions = self.get_backtest_actions(run_id)
        dates = sorted({row["trade_date"] for row in actions})
        action_counts: dict[str, int] = {}
        holding_period_counts: dict[str, int] = {}
        by_ticker: dict[str, list[dict[str, Any]]] = {}
        for row in actions:
            action = str(row["action"])
            action_counts[action] = action_counts.get(action, 0) + 1
            holding_period = row.get("holding_period") or "unspecified"
            holding_period_counts[holding_period] = holding_period_counts.get(holding_period, 0) + 1
            by_ticker.setdefault(str(row["ticker"]), []).append(row)

        turnover_proxy = 0.0
        max_observed_holding_days = 0
        stale_thesis_proxy_count = 0
        for rows in by_ticker.values():
            rows.sort(key=lambda row: row["trade_date"])
            previous = 0.0
            seen_dates: set[str] = set()
            for row in rows:
                target = float(row["target_weight"])
                turnover_proxy += abs(target - previous)
                previous = target
                seen_dates.add(str(row["trade_date"]))
            max_observed_holding_days = max(max_observed_holding_days, max(len(seen_dates) - 1, 0))
            if max(len(seen_dates) - 1, 0) >= 20:
                stale_thesis_proxy_count += 1

        return {
            "run_id": run_id,
            "action_count": len(actions),
            "trade_day_count": len(dates),
            "first_trade_date": dates[0] if dates else None,
            "last_trade_date": dates[-1] if dates else None,
            "ticker_count": len(by_ticker),
            "turnover_proxy": round(turnover_proxy, 6),
            "max_observed_holding_days": max_observed_holding_days,
            "stale_thesis_proxy_count": stale_thesis_proxy_count,
            "action_counts": action_counts,
            "holding_period_counts": holding_period_counts,
            "metric_availability": {
                "turnover": "stage1_proxy_from_target_weight_changes",
                "holding_days": "stage1_observed_trade_day_count",
                "exit_after_hold_alpha": "requires_stage2_scored_positions",
                "reduce_opportunity_cost": "requires_stage2_scored_positions",
                "stop_loss_avoided_drawdown": "requires_stage2_scored_positions",
            },
        }

    # ── backtest_failed_days (R-A3) ──────────────────────────────────────

    def record_backtest_failed_days(
        self,
        run_id: int,
        failures: list[tuple[str, str]],
        *,
        agent_run_audits_by_date: Optional[dict[str, dict[str, Any]]] = None,
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
                "DELETE FROM backtest_actions WHERE run_id = ? AND trade_date = ?",
                [(run_id, date) for _, date, _, _ in rows],
            )
            conn.executemany(
                "DELETE FROM agent_run_outcomes WHERE run_id = ? AND trade_date = ?",
                [(run_id, date) for _, date, _, _ in rows],
            )
            audits_by_date = agent_run_audits_by_date or {}
            for _, date, _, _ in rows:
                audit = audits_by_date.get(date)
                if not audit:
                    continue
                status = audit.get("status")
                if status not in ("rejected", "timeout", "error"):
                    raise ValueError("failed-day audit must have a terminal failure status")
                conn.execute(
                    """
                    INSERT INTO agent_run_outcomes (
                        run_id, trade_date, agent, stage, status, output_source,
                        attempt_count, repair_count, stop_reason, audit_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        date,
                        audit.get("agent"),
                        audit.get("stage"),
                        status,
                        audit.get("output_source", "none"),
                        int(audit.get("attempt_count", 0)),
                        int(audit.get("repair_count", 0)),
                        audit.get("stop_reason", "unknown"),
                        json.dumps(audit, ensure_ascii=False, sort_keys=True),
                    ),
                )
            conn.executemany(
                """
                INSERT INTO backtest_day_outcomes (
                    run_id, trade_date, status, decision_disposition, action_count, accepted_at
                ) VALUES (?, ?, 'failed_no_decision', NULL, 0, NULL)
                ON CONFLICT(run_id, trade_date) DO UPDATE SET
                    status = excluded.status,
                    decision_disposition = NULL,
                    action_count = 0,
                    accepted_at = NULL
                """,
                [(run_id, date) for _, date, _, _ in rows],
            )
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
        mutation_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Back-fill the mutation commit + summary once the TS mutator has
        written and committed the rewrite (``autoresearch.record_mutation``)."""
        metadata_json = _json_object_or_none(mutation_metadata)
        mutation_id = None
        transaction_id = None
        experiment_id = None
        mutation_lifecycle = None
        if mutation_metadata is not None:
            mutation_id = mutation_metadata.get("mutation_id")
            transaction_id = mutation_metadata.get("transaction_id")
            experiment_id = mutation_metadata.get("experiment_id")
            for field, value in (
                ("mutation_id", mutation_id),
                ("transaction_id", transaction_id),
                ("experiment_id", experiment_id),
            ):
                if not isinstance(value, str) or not value:
                    raise ValueError(f"mutation metadata {field} must be a non-empty string")
            mutation_lifecycle = "proposed"
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE prompt_versions
                SET modification_commit_hash = :mod,
                    modification_summary = :summary,
                    prompt_repo_id = COALESCE(:prompt_repo_id, prompt_repo_id),
                    prompt_base_commit_hash = COALESCE(:prompt_base_commit_hash, prompt_base_commit_hash),
                    prompt_sha256 = COALESCE(:prompt_sha256, prompt_sha256),
                    code_commit_hash = COALESCE(:code_commit_hash, code_commit_hash),
                    mutation_id = COALESCE(:mutation_id, mutation_id),
                    transaction_id = COALESCE(:transaction_id, transaction_id),
                    experiment_id = COALESCE(:experiment_id, experiment_id),
                    mutation_metadata_json = COALESCE(:mutation_metadata_json, mutation_metadata_json),
                    mutation_lifecycle = COALESCE(:mutation_lifecycle, mutation_lifecycle)
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
                    "mutation_id": mutation_id,
                    "transaction_id": transaction_id,
                    "experiment_id": experiment_id,
                    "mutation_metadata_json": metadata_json,
                    "mutation_lifecycle": mutation_lifecycle,
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

    def set_version_mutation_lifecycle(
        self,
        version_id: int,
        lifecycle: str,
        *,
        decided_at: Optional[str] = None,
    ) -> None:
        """Apply one legal domain mutation lifecycle transition."""
        if lifecycle not in _DOMAIN_MUTATION_LIFECYCLE_TRANSITIONS:
            raise ValueError(f"unknown domain mutation lifecycle: {lifecycle!r}")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mutation_lifecycle FROM prompt_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"prompt_version {version_id} not found")
            current = row["mutation_lifecycle"]
            if current == lifecycle:
                return
            allowed = _DOMAIN_MUTATION_LIFECYCLE_TRANSITIONS.get(current, set())
            if lifecycle not in allowed:
                raise ValueError(
                    f"illegal domain mutation lifecycle transition: {current!r} -> {lifecycle!r}"
                )
            status = None
            if lifecycle == "kept":
                status = "keep"
            elif lifecycle == "reverted":
                status = "revert"
            elif lifecycle == "invalid":
                status = "invalid"
            terminal_at = decided_at or (_utcnow_iso() if status else None)
            conn.execute(
                """
                UPDATE prompt_versions
                SET mutation_lifecycle = ?,
                    status = COALESCE(?, status),
                    decided_at = COALESCE(?, decided_at)
                WHERE id = ?
                """,
                (lifecycle, status, terminal_at, version_id),
            )

    def set_domain_evaluation_result(
        self, version_id: int, result: dict[str, Any]
    ) -> None:
        """Persist the language-neutral EvaluationResult for one mutation."""
        encoded = _json_object_or_none(result)
        if encoded is None:
            raise ValueError("domain evaluation result must be an object")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE prompt_versions SET evaluation_result_json = ? WHERE id = ?",
                (encoded, version_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"prompt_version {version_id} not found")

    def evaluate_domain_mutation(
        self,
        mutation_metadata: Mapping[str, Any],
        sample_manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Evaluate and consume holdout state in this server-owned database."""
        from mosaic.autoresearch.domain_evaluator import evaluate_domain_mutation

        with self._connect() as conn:
            return evaluate_domain_mutation(
                mutation_metadata,
                sample_manifest,
                holdout_consumption_ledger=conn,
            )

    def consume_domain_holdout(
        self,
        version_id: int,
        *,
        holdout_id: str,
        mutation_id: str,
        result_hash: str,
    ) -> bool:
        """Consume an untouched holdout once; exact retries are idempotent."""
        for value, field in (
            (holdout_id, "holdout_id"),
            (result_hash, "result_hash"),
        ):
            if (
                not isinstance(value, str)
                or not value.startswith("sha256:")
                or len(value) != 71
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                raise ValueError(f"{field} must be a sha256 digest")
        if not isinstance(mutation_id, str) or not mutation_id:
            raise ValueError("mutation_id must be a non-empty string")
        with self._connect() as conn:
            version = conn.execute(
                "SELECT mutation_id FROM prompt_versions WHERE id = ?", (version_id,)
            ).fetchone()
            if version is None:
                raise ValueError(f"prompt_version {version_id} not found")
            if version["mutation_id"] != mutation_id:
                raise ValueError("holdout mutation_id does not match prompt version")
            existing = conn.execute(
                "SELECT mutation_id, prompt_version_id, result_hash "
                "FROM domain_holdout_consumptions WHERE holdout_id = ?",
                (holdout_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["mutation_id"] == mutation_id
                    and existing["prompt_version_id"] == version_id
                    and existing["result_hash"] == result_hash
                ):
                    return False
                raise ValueError("untouched holdout has already been consumed")
            conn.execute(
                "INSERT INTO domain_holdout_consumptions "
                "(holdout_id, mutation_id, prompt_version_id, result_hash, consumed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (holdout_id, mutation_id, version_id, result_hash, _utcnow_iso()),
            )
        return True

    def get_domain_holdout_consumption(self, holdout_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT holdout_id, mutation_id, prompt_version_id, result_hash, consumed_at "
                "FROM domain_holdout_consumptions WHERE holdout_id = ?",
                (holdout_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_version_mutation_metadata(self, version_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mutation_metadata_json FROM prompt_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None or row["mutation_metadata_json"] is None:
            return None
        value = json.loads(row["mutation_metadata_json"])
        return value if isinstance(value, dict) else None

    def get_domain_evaluation_result(self, version_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT evaluation_result_json FROM prompt_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None or row["evaluation_result_json"] is None:
            return None
        value = json.loads(row["evaluation_result_json"])
        return value if isinstance(value, dict) else None

    def record_domain_promotion_decision(
        self,
        version_id: int,
        decision: dict[str, Any],
        *,
        decision_hash: str,
    ) -> bool:
        """Atomically persist one authorized promotion decision."""
        encoded = _json_object_or_none(decision)
        if encoded is None:
            raise ValueError("domain promotion decision must be an object")
        if (
            not isinstance(decision_hash, str)
            or len(decision_hash) != 71
            or not decision_hash.startswith("sha256:")
            or any(
                character not in "0123456789abcdef" for character in decision_hash[7:]
            )
        ):
            raise ValueError("domain promotion decision_hash must be a sha256 digest")
        action = decision.get("decision")
        if action not in ("keep", "revert"):
            raise ValueError("domain promotion decision must be keep or revert")
        approved_by = decision.get("approved_by")
        approval_policy_id = decision.get("approval_policy_id")
        if not isinstance(approved_by, str) or not approved_by:
            raise ValueError("domain promotion approved_by is required")
        if not isinstance(approval_policy_id, str) or not approval_policy_id:
            raise ValueError("domain promotion approval_policy_id is required")
        canonical = json.dumps(
            decision,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        if decision_hash != expected_hash:
            raise ValueError("domain promotion decision_hash does not match decision")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT mutation_lifecycle, promotion_decision_json, "
                "promotion_decision_hash FROM prompt_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"prompt_version {version_id} not found")
            if row["promotion_decision_json"] is not None:
                if (
                    row["promotion_decision_json"] == encoded
                    and row["promotion_decision_hash"] == decision_hash
                ):
                    return False
                raise ValueError("domain promotion decision already exists")
            if row["mutation_lifecycle"] != "eligible_for_promotion":
                raise ValueError("domain mutation is not eligible for promotion review")
            conn.execute(
                """
                UPDATE prompt_versions
                SET mutation_lifecycle = ?, status = ?, decided_at = ?,
                    promotion_decision_json = ?, promotion_decision_hash = ?,
                    promotion_approved_by = ?, promotion_approval_policy_id = ?
                WHERE id = ?
                """,
                (
                    "kept" if action == "keep" else "reverted",
                    action,
                    decision.get("decided_at") or _utcnow_iso(),
                    encoded,
                    decision_hash,
                    approved_by,
                    approval_policy_id,
                    version_id,
                ),
            )
        return True

    def get_domain_promotion_decision(self, version_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT promotion_decision_json FROM prompt_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
        if row is None or row["promotion_decision_json"] is None:
            return None
        value = json.loads(row["promotion_decision_json"])
        return value if isinstance(value, dict) else None

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
