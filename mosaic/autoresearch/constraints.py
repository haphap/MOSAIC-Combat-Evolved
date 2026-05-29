"""Autoresearch mutation constraints (Plan §1, §8, §11.5 4A).

Three independent checks, each a pure function of (store state, config, now):

  * :func:`check_cooldown`     — the same (cohort, agent) may get at most one
    new mutation per ``agent_mutation_cooldown_hours`` (default 24h).
  * :func:`check_monthly_cap`  — at most ``monthly_modification_cap_per_cohort``
    mutations per cohort per calendar month (default 100).
  * :func:`check_keep_lockout` — a *kept* mutation may not be reverted until
    ``keep_revert_lockout_days`` have elapsed (default 3 days). Only applies
    to versions whose status is already ``keep``.

Constraints are enforced Python-side as the single source of truth (Plan
§11.5 design decision #6); the TS orchestrator only calls in. ``now`` is
always passed explicitly (a tz-aware datetime) so the checks are deterministic
and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from mosaic.default_config import DEFAULT_CONFIG


@dataclass(frozen=True)
class ConstraintResult:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:  # allow ``if check(...):``
        return self.ok


def _ar_cfg(config: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    cfg = config if config is not None else DEFAULT_CONFIG
    return cfg.get("autoresearch", {}) or {}


def _parse(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp; assume UTC when no tzinfo present."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check_cooldown(
    store,
    cohort: str,
    agent: str,
    now: datetime,
    config: Optional[Mapping[str, Any]] = None,
) -> ConstraintResult:
    """Reject if (cohort, agent) was mutated within the cooldown window."""
    hours = int(_ar_cfg(config).get("agent_mutation_cooldown_hours", 24))
    last = store.last_mutation_at(cohort, agent)
    if not last:
        return ConstraintResult(True)
    elapsed = now - _parse(last)
    if elapsed < timedelta(hours=hours):
        remaining = timedelta(hours=hours) - elapsed
        return ConstraintResult(
            False,
            f"cooldown: {agent} in {cohort} was mutated {_fmt(elapsed)} ago; "
            f"{_fmt(remaining)} left of the {hours}h window",
        )
    return ConstraintResult(True)


def check_monthly_cap(
    store,
    cohort: str,
    now: datetime,
    config: Optional[Mapping[str, Any]] = None,
) -> ConstraintResult:
    """Reject if the cohort already hit its monthly mutation cap."""
    cap = int(_ar_cfg(config).get("monthly_modification_cap_per_cohort", 100))
    now_iso = now.isoformat()
    count = store.count_mutations_this_month(cohort, now_iso)
    if count >= cap:
        return ConstraintResult(
            False,
            f"monthly cap: {cohort} has {count} mutations this month (cap {cap})",
        )
    return ConstraintResult(True)


def check_keep_lockout(
    store,
    version: Mapping[str, Any],
    now: datetime,
    config: Optional[Mapping[str, Any]] = None,
) -> ConstraintResult:
    """Reject reverting a kept mutation inside the lockout window.

    No-op (returns ok) for versions that aren't in ``keep`` status — only a
    kept-then-merged change is protected from being yanked back immediately.
    """
    if version.get("status") != "keep":
        return ConstraintResult(True)
    days = int(_ar_cfg(config).get("keep_revert_lockout_days", 3))
    decided_at = version.get("decided_at")
    if not decided_at:
        # Kept but no decision timestamp — be conservative, allow.
        return ConstraintResult(True)
    elapsed = now - _parse(decided_at)
    if elapsed < timedelta(days=days):
        remaining = timedelta(days=days) - elapsed
        return ConstraintResult(
            False,
            f"keep lockout: version {version.get('id')} was kept {_fmt(elapsed)} "
            f"ago; {_fmt(remaining)} left of the {days}d lockout",
        )
    return ConstraintResult(True)


def _fmt(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"
