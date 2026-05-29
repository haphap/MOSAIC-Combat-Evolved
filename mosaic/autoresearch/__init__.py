"""MOSAIC autoresearch package (Plan §11.5, Phase 4).

The ATLAS self-improvement loop: select an agent, have an LLM rewrite its
prompt, commit the rewrite to a feature branch, evaluate before/after via a
backtest ΔSharpe, then keep (merge) or revert (delete) the branch — all under
the cooldown / lockout / monthly-cap constraints.

This package owns the *Python-side* primitives (Plan §11.5 design decision
#1 — "TS proposes + orchestrates, Python persists + does the accounting"):

  * :mod:`mosaic.autoresearch.git_ops`     — git branch/commit/merge/worktree
  * :mod:`mosaic.autoresearch.constraints` — cooldown / cap / keep-lockout

SQLite provenance (prompt_versions / autoresearch_log) lives in
:mod:`mosaic.scorecard.store` so it shares the single ``data/scorecard.db``.
"""

from mosaic.autoresearch.constraints import (
    ConstraintResult,
    check_cooldown,
    check_keep_lockout,
    check_monthly_cap,
)
from mosaic.autoresearch.git_ops import GitError, GitOps

__all__ = [
    "ConstraintResult",
    "GitError",
    "GitOps",
    "check_cooldown",
    "check_keep_lockout",
    "check_monthly_cap",
]
