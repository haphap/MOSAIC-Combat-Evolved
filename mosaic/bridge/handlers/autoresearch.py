"""``autoresearch.*`` JSON-RPC handlers (Plan ss11.5 4C/4D).

Exposes the prompt-mutation lifecycle to the TS orchestrator:

    * autoresearch.trigger       -- select agent, create branch + version shell
    * autoresearch.record_mutation -- back-fill mod commit after TS mutator writes
    * autoresearch.evaluate_pending -- compute delta + decide for ready versions
    * autoresearch.get_log       -- audit trail
    * autoresearch.list_active_branches -- pending feature branches
    * autoresearch.revert_modification  -- manual revert with lockout check
    * autoresearch.prepare_worktree     -- isolated checkout for evaluation
    * autoresearch.cleanup_worktree     -- remove an evaluation worktree
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..protocol import AUTORESEARCH_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store():
    """Lazy-import scorecard store singleton (ss14 R-T4)."""
    from mosaic.scorecard import get_store

    return get_store()


def _repo_root() -> Path:
    env = os.getenv("MOSAIC_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def _git_ops():
    from mosaic.autoresearch.git_ops import GitOps

    return GitOps(_repo_root())


def _config():
    from mosaic.default_config import DEFAULT_CONFIG

    return DEFAULT_CONFIG


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


def _require_int(params: dict, key: str) -> int:
    val = params.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an integer")
    return val


# ---------------------------------------------------------------------------
# autoresearch.trigger
# ---------------------------------------------------------------------------


@method("autoresearch.trigger")
def autoresearch_trigger(params: dict[str, Any]) -> dict[str, Any]:
    """Select an agent and create a pending prompt_version + git branch.

    Params:
        cohort:       str
        force_agent:  str | None -- bypass selection, use this agent

    Returns:
        {version_id, agent, branch_name, base_commit}
    """
    from mosaic.autoresearch.constraints import check_cooldown, check_monthly_cap

    cohort = _require_str(params, "cohort")
    force_agent = params.get("force_agent") or None
    if force_agent is not None and not isinstance(force_agent, str):
        raise RpcError(INVALID_PARAMS, "'force_agent' must be a string")

    store = _store()
    config = _config()
    now = _now()

    # Monthly cap check (applies to any new trigger for this cohort).
    cap_result = check_monthly_cap(store, cohort, now, config)
    if not cap_result:
        raise RpcError(AUTORESEARCH_ERROR, cap_result.reason)

    # Early idempotency check when force_agent is known (avoids cooldown
    # rejection on what would be a no-op duplicate trigger).
    if force_agent:
        today_str = now.strftime("%Y-%m-%d")
        branch_name = f"cohort/{cohort}/auto/{force_agent}/{today_str}"
        existing = store.get_version_by_branch(branch_name)
        if existing:
            return {
                "version_id": existing["id"],
                "agent": existing["agent"],
                "branch_name": existing["branch_name"],
                "base_commit": existing["base_commit_hash"],
            }

    # Select agent.
    agent = _select_agent(store, cohort, force_agent, config, now)

    # Idempotency: if the branch_name already has a version, return it.
    today_str = now.strftime("%Y-%m-%d")
    branch_name = f"cohort/{cohort}/auto/{agent}/{today_str}"
    existing = store.get_version_by_branch(branch_name)
    if existing:
        return {
            "version_id": existing["id"],
            "agent": existing["agent"],
            "branch_name": existing["branch_name"],
            "base_commit": existing["base_commit_hash"],
        }

    # Cooldown check.
    cooldown_result = check_cooldown(store, cohort, agent, now, config)
    if not cooldown_result:
        raise RpcError(AUTORESEARCH_ERROR, cooldown_result.reason)

    # Create branch.
    git = _git_ops()
    base_commit = git.current_commit()

    # Create branch in git.
    try:
        if not git.branch_exists(branch_name):
            git.create_branch(branch_name, "main")
    except Exception as exc:
        raise RpcError(
            AUTORESEARCH_ERROR, f"failed to create branch: {exc}"
        ) from exc

    # Create version shell in DB.
    version_id = store.create_prompt_version(
        cohort=cohort,
        agent=agent,
        branch_name=branch_name,
        base_commit_hash=base_commit,
    )
    store.append_log(version_id, "triggered", f"agent={agent}, branch={branch_name}")

    return {
        "version_id": version_id,
        "agent": agent,
        "branch_name": branch_name,
        "base_commit": base_commit,
    }


def _select_agent(
    store, cohort: str, force_agent: str | None, config: dict, now: datetime
) -> str:
    """Pick the agent with the lowest rolling Sharpe that passes constraints.

    If force_agent is set, use that directly (still must pass cooldown).
    """
    from mosaic.autoresearch.constraints import check_cooldown

    if force_agent:
        # Still enforce cooldown even when agent is forced.
        cd = check_cooldown(store, cohort, force_agent, now, config)
        if not cd:
            raise RpcError(
                AUTORESEARCH_ERROR,
                f"forced agent '{force_agent}' is on cooldown: {cd.reason}",
            )
        return force_agent

    # Get Darwinian weights (which include sharpe_30) for agent ranking.
    weights = store.get_darwinian_weights(cohort)

    # All agents eligible for mutation (from the layer map).
    from mosaic.bridge.handlers.prompts import _LAYER_BY_AGENT

    all_agents = list(_LAYER_BY_AGENT.keys())

    # Sort agents by rolling sharpe (lowest first = most in need of improvement).
    def sharpe_key(agent_name: str) -> float:
        w = weights.get(agent_name)
        if w and w.get("sharpe_30") is not None:
            return float(w["sharpe_30"])
        return 0.0  # no data = neutral priority

    candidates = sorted(all_agents, key=sharpe_key)

    for candidate in candidates:
        cd = check_cooldown(store, cohort, candidate, now, config)
        if cd:
            return candidate

    # All agents are on cooldown.
    raise RpcError(
        AUTORESEARCH_ERROR,
        f"all agents in cohort '{cohort}' are on cooldown; try again later",
    )


# ---------------------------------------------------------------------------
# autoresearch.record_mutation
# ---------------------------------------------------------------------------


@method("autoresearch.record_mutation")
def autoresearch_record_mutation(params: dict[str, Any]) -> dict[str, Any]:
    """Back-fill the mutation commit on a pending version.

    Params:
        version_id:   int
        commit_hash:  str
        summary:      str | None

    Returns:
        {"ok": true}
    """
    version_id = _require_int(params, "version_id")
    commit_hash = _require_str(params, "commit_hash")
    summary = params.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise RpcError(INVALID_PARAMS, "'summary' must be a string")

    store = _store()
    store.set_version_mutation(version_id, commit_hash, summary)
    store.append_log(version_id, "mutated", f"commit={commit_hash[:12]}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# autoresearch.evaluate_pending
# ---------------------------------------------------------------------------


@method("autoresearch.evaluate_pending")
def autoresearch_evaluate_pending(params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all pending versions that have a modification commit.

    For each version: if both backtest runs (base + mod) are complete,
    compute delta and decide. Otherwise, report needs_fill.

    Params:
        cohort: str | None -- filter to a specific cohort

    Returns:
        {"results": [{version_id, status, delta_sharpe?}, ...]}
    """
    from mosaic.autoresearch.decider import decide
    from mosaic.autoresearch.evaluator import compute_delta, ensure_baseline_run

    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")

    store = _store()
    config = _config()
    cohorts_cfg = config.get("cohorts", {})

    # Get pending versions with a mod commit.
    versions = store.list_prompt_versions(cohort=cohort, status="pending")
    results: list[dict[str, Any]] = []

    for v in versions:
        version_id = v["id"]
        mod_commit = v.get("modification_commit_hash")
        if not mod_commit:
            # Not yet mutated, skip.
            continue

        v_cohort = v["cohort"]
        cohort_info = cohorts_cfg.get(v_cohort, {})
        start_date = cohort_info.get("start", "")
        end_date = cohort_info.get("end", "")

        if not start_date or not end_date:
            results.append({"version_id": version_id, "status": "error",
                            "detail": f"cohort '{v_cohort}' missing date range"})
            continue

        # Check if both runs exist.
        base_check = ensure_baseline_run(
            store, v_cohort, start_date, end_date, v["base_commit_hash"]
        )
        mod_check = ensure_baseline_run(
            store, v_cohort, start_date, end_date, mod_commit
        )

        if base_check["needs_fill"] or mod_check["needs_fill"]:
            results.append({"version_id": version_id, "status": "needs_fill"})
            continue

        # Both runs complete: evaluate + decide.
        try:
            delta_result = compute_delta(store, version_id, config)
            # Re-read version after eval writes.
            updated_version = store.get_prompt_version(version_id)
            git = _git_ops()
            status = decide(store, git, updated_version, config)
            # decide() returns the stored state-machine value (keep/revert);
            # expose the past-tense form (kept/reverted) on the RPC boundary so
            # it matches the autoresearch_log event names and the TS consumers.
            rpc_status = {"keep": "kept", "revert": "reverted"}.get(status, status)
            results.append({
                "version_id": version_id,
                "status": rpc_status,
                "delta_sharpe": delta_result["delta_sharpe"],
            })
        except ValueError as exc:
            results.append({
                "version_id": version_id,
                "status": "error",
                "detail": str(exc),
            })
        except Exception as exc:
            results.append({
                "version_id": version_id,
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}",
            })

    return {"results": results}


# ---------------------------------------------------------------------------
# autoresearch.get_log
# ---------------------------------------------------------------------------


@method("autoresearch.get_log")
def autoresearch_get_log(params: dict[str, Any]) -> dict[str, Any]:
    """Return the autoresearch audit log.

    Params:
        cohort: str | None
        days:   int | None -- trailing window

    Returns:
        {"entries": [...]}
    """
    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")
    days = params.get("days")
    if days is not None:
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise RpcError(INVALID_PARAMS, "'days' must be a positive integer")

    entries = _store().get_log(cohort=cohort, days=days)
    return {"entries": entries}


# ---------------------------------------------------------------------------
# autoresearch.list_active_branches
# ---------------------------------------------------------------------------


@method("autoresearch.list_active_branches")
def autoresearch_list_active_branches(params: dict[str, Any]) -> dict[str, Any]:
    """List pending prompt_version branches.

    Params:
        cohort: str | None

    Returns:
        {"branches": [...]}
    """
    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")

    branches = _store().list_active_branches(cohort=cohort)
    return {"branches": branches}


# ---------------------------------------------------------------------------
# autoresearch.revert_modification
# ---------------------------------------------------------------------------


@method("autoresearch.revert_modification")
def autoresearch_revert_modification(params: dict[str, Any]) -> dict[str, Any]:
    """Manually revert a kept modification (respects keep_lockout).

    Params:
        version_id: int

    Returns:
        {"ok": true}
    """
    from mosaic.autoresearch.constraints import check_keep_lockout

    version_id = _require_int(params, "version_id")
    store = _store()
    config = _config()

    version = store.get_prompt_version(version_id)
    if version is None:
        raise RpcError(INVALID_PARAMS, f"prompt_version {version_id} not found")

    # Check keep lockout.
    lockout = check_keep_lockout(store, version, _now(), config)
    if not lockout:
        raise RpcError(AUTORESEARCH_ERROR, lockout.reason)

    branch = version["branch_name"]
    git = _git_ops()

    try:
        git.delete_branch(branch)
    except Exception:
        pass  # Branch may already be deleted.

    store.decide_version(version_id, "revert")
    store.append_log(version_id, "reverted", "manual revert via autoresearch.revert_modification")

    return {"ok": True}


# ---------------------------------------------------------------------------
# autoresearch.prepare_worktree
# ---------------------------------------------------------------------------


@method("autoresearch.prepare_worktree")
def autoresearch_prepare_worktree(params: dict[str, Any]) -> dict[str, Any]:
    """Check out a branch/ref into an isolated worktree for evaluation.

    Params:
        branch: str -- branch name or ref to checkout

    Returns:
        {"path": str}
    """
    branch = _require_str(params, "branch")
    git = _git_ops()

    try:
        wt_path = git.add_worktree(branch)
    except Exception as exc:
        raise RpcError(
            AUTORESEARCH_ERROR, f"add_worktree failed: {exc}"
        ) from exc

    return {"path": str(wt_path)}


# ---------------------------------------------------------------------------
# autoresearch.cleanup_worktree
# ---------------------------------------------------------------------------


@method("autoresearch.cleanup_worktree")
def autoresearch_cleanup_worktree(params: dict[str, Any]) -> dict[str, Any]:
    """Remove a previously created evaluation worktree.

    Params:
        path: str -- path returned by prepare_worktree

    Returns:
        {"ok": true}
    """
    path = _require_str(params, "path")
    git = _git_ops()

    try:
        git.remove_worktree(Path(path))
    except Exception as exc:
        raise RpcError(
            AUTORESEARCH_ERROR, f"remove_worktree failed: {exc}"
        ) from exc

    return {"ok": True}
