"""``autoresearch.*`` JSON-RPC handlers (Plan ss11.5 4C/4D).

Exposes the prompt-mutation lifecycle to the TS orchestrator:

    * autoresearch.trigger       -- select agent, create branch + version shell
    * autoresearch.record_mutation -- back-fill mod commit after TS mutator writes
    * autoresearch.evaluate_pending -- compute delta + decide for ready versions
    * autoresearch.get_log       -- audit trail
    * autoresearch.list_active_branches -- pending feature branches
    * autoresearch.revert_modification  -- manual revert with lockout check
    * autoresearch.prepare_worktree     -- isolated project/private checkout for evaluation
    * autoresearch.cleanup_worktree     -- remove an evaluation worktree
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
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


def _private_git_ops():
    from mosaic.autoresearch.git_ops import GitOps
    from mosaic.autoresearch.prompt_repo import (
        PromptRepoError,
        private_prompt_repo_from_env,
        validate_private_prompt_repo,
    )

    repo = private_prompt_repo_from_env()
    if repo is None:
        raise RpcError(
            INVALID_PARAMS,
            "MOSAIC_PRIVATE_PROMPT_REPO is required for private autoresearch branches",
        )
    try:
        return GitOps(validate_private_prompt_repo(repo, project_root=_repo_root()))
    except PromptRepoError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc


def _git_ops_for_branch(branch: str, version: dict[str, Any] | None = None):
    prompt_repo_id = (version or {}).get("prompt_repo_id")
    if prompt_repo_id == "private":
        private_git = _private_git_ops()
        if not private_git.branch_exists(branch):
            raise RpcError(
                AUTORESEARCH_ERROR,
                f"private prompt branch not found in MOSAIC_PRIVATE_PROMPT_REPO: {branch}",
            )
        return private_git

    project_git = _git_ops()
    if project_git.branch_exists(branch):
        return project_git
    try:
        private_git = _private_git_ops()
        if private_git.branch_exists(branch):
            return private_git
    except RpcError:
        pass
    return project_git


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


def _run_fill_spec(
    *,
    kind: str,
    cohort: str,
    start_date: str,
    end_date: str,
    prompt_commit_hash: str,
    prompt_repo_id: str | None = None,
    prompt_sha256: str | None = None,
    code_commit_hash: str | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "kind": kind,
        "cohort": cohort,
        "start_date": start_date,
        "end_date": end_date,
        "prompt_commit_hash": prompt_commit_hash,
    }
    if prompt_repo_id:
        spec["prompt_repo_id"] = prompt_repo_id
    if prompt_sha256:
        spec["prompt_sha256"] = prompt_sha256
    if code_commit_hash:
        spec["code_commit_hash"] = code_commit_hash
    if prompt_repo_id == "private":
        spec["private_prompt_commit"] = prompt_commit_hash
    return spec


# ---------------------------------------------------------------------------
# autoresearch.trigger
# ---------------------------------------------------------------------------


@method("autoresearch.trigger")
def autoresearch_trigger(params: dict[str, Any]) -> dict[str, Any]:
    """Select an agent and create a pending prompt_version.

    Params:
        cohort:       str
        force_agent:  str | None -- bypass selection, use this agent
        dry_run:      bool -- select + check constraints only; do NOT create
                      the prompt_versions row (version_id=None)

    Returns:
        {version_id, agent, branch_name, base_commit}
        (version_id is None when dry_run=True)
    """
    from mosaic.autoresearch.constraints import check_cooldown, check_monthly_cap

    cohort = _require_str(params, "cohort")
    force_agent = params.get("force_agent") or None
    if force_agent is not None and not isinstance(force_agent, str):
        raise RpcError(INVALID_PARAMS, "'force_agent' must be a string")
    dry_run = bool(params.get("dry_run", False))

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

    git = _git_ops()
    base_commit = git.current_commit()

    # Dry-run: report the selection (agent + would-be branch) without
    # creating a git branch or a prompt_versions row (Plan §11.5 4E: dry-run
    # "只生成不提交"). version_id=None signals the orchestrator not to persist.
    if dry_run:
        return {
            "version_id": None,
            "agent": agent,
            "branch_name": branch_name,
            "base_commit": base_commit,
            "dry_run": True,
        }

    # Create version shell in DB.
    version_id = store.create_prompt_version(
        cohort=cohort,
        agent=agent,
        branch_name=branch_name,
        base_commit_hash=base_commit,
        code_commit_hash=base_commit,
    )
    store.append_log(
        version_id,
        "triggered",
        f"agent={agent}, prompt_branch={branch_name}, code_base={base_commit[:12]}",
    )

    return {
        "version_id": version_id,
        "agent": agent,
        "branch_name": branch_name,
        "base_commit": base_commit,
    }


def _select_agent(
    store, cohort: str, force_agent: str | None, config: dict, now: datetime
) -> str:
    """Layer-aware agent selection (autoresearch macro plan Phase 4).

    macro agents are ranked *within the macro layer* by ``mean_raw_macro_score_5d``
    (worst first); non-macro agents keep the rolling-Sharpe ranking. The two
    metrics are never mixed. macro is only eligible when it hasn't been mutated
    within ``min_macro_interval_days`` (the static-quota realization for the MVP).
    A recent-revert penalty deprioritizes agents reverted in the last
    ``recent_revert_penalty_days``. ``force_agent`` bypasses selection but still
    enforces cooldown.
    """
    from mosaic.autoresearch.constraints import check_cooldown
    from mosaic.bridge.handlers.prompts import _LAYER_BY_AGENT

    if force_agent:
        cd = check_cooldown(store, cohort, force_agent, now, config)
        if not cd:
            raise RpcError(
                AUTORESEARCH_ERROR,
                f"forced agent '{force_agent}' is on cooldown: {cd.reason}",
            )
        return force_agent

    ar = (config or {}).get("autoresearch", {}) or {}
    macro_quota = float(ar.get("macro_quota", 0.2))
    macro_enabled = macro_quota > 0
    if not macro_enabled:
        min_macro_interval_days = 10**9
    else:
        quota_interval_days = max(1, math.ceil(1.0 / min(macro_quota, 1.0)))
        min_macro_interval_days = max(
            int(ar.get("min_macro_interval_days", 5)),
            quota_interval_days,
        )
    recent_revert_penalty_days = int(ar.get("recent_revert_penalty_days", 14))

    all_agents = list(_LAYER_BY_AGENT.keys())
    macro_agents = [a for a in all_agents if _LAYER_BY_AGENT[a] == "macro"]
    nonmacro_agents = [a for a in all_agents if _LAYER_BY_AGENT[a] != "macro"]

    # Agents with a recent revert are tried last (penalty, not a hard block).
    revert_since = (now - timedelta(days=recent_revert_penalty_days)).isoformat()
    penalized = store.recently_reverted_agents(cohort, revert_since)

    # macro layer ranked worst→best by mean_raw_macro_score_5d. Cold-start
    # macro agents stay out of automatic selection until they have real score.
    macro_skill = {r["agent"]: r for r in store.list_macro_skill(cohort)}
    scored_macro_agents = [
        a
        for a in macro_agents
        if (macro_skill.get(a) or {}).get("mean_raw_macro_score_5d") is not None
    ]

    def macro_key(a: str) -> float:
        return float(macro_skill[a]["mean_raw_macro_score_5d"])

    # non-macro ranked worst→best by rolling Sharpe (existing metric).
    weights = store.get_darwinian_weights(cohort)

    def sharpe_key(a: str) -> float:
        w = weights.get(a)
        if w and w.get("sharpe_30") is not None:
            return float(w["sharpe_30"])
        return 0.0

    def _first_eligible(ranked: list[str]) -> str | None:
        # Prefer non-penalized; only fall back to penalized agents if needed.
        for allow_penalized in (False, True):
            for a in ranked:
                if not allow_penalized and a in penalized:
                    continue
                if check_cooldown(store, cohort, a, now, config):
                    return a
        return None

    # Is the macro layer due? (no macro mutation within the interval)
    macro_due = True
    last_macro = store.last_mutation_at_any(cohort, macro_agents)
    if last_macro:
        last_dt = datetime.fromisoformat(last_macro)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        macro_due = (now - last_dt) >= timedelta(days=min_macro_interval_days)

    if macro_enabled and macro_due and scored_macro_agents:
        chosen = _first_eligible(sorted(scored_macro_agents, key=macro_key))
        if chosen:
            return chosen

    chosen = _first_eligible(sorted(nonmacro_agents, key=sharpe_key))
    if chosen:
        return chosen

    # Last resort: any agent (e.g. macro when not "due" but everything else is
    # on cooldown) — never silently fail if something is eligible.
    chosen = _first_eligible(sorted(all_agents, key=sharpe_key))
    if chosen:
        return chosen

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
        prompt_repo_id: str | None
        prompt_base_commit_hash: str | None
        prompt_sha256: str | None
        code_commit_hash: str | None

    Returns:
        {"ok": true}
    """
    version_id = _require_int(params, "version_id")
    commit_hash = _require_str(params, "commit_hash")
    summary = params.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise RpcError(INVALID_PARAMS, "'summary' must be a string")
    prompt_repo_id = params.get("prompt_repo_id")
    if prompt_repo_id is not None and not isinstance(prompt_repo_id, str):
        raise RpcError(INVALID_PARAMS, "'prompt_repo_id' must be a string")
    prompt_base_commit_hash = params.get("prompt_base_commit_hash")
    if prompt_base_commit_hash is not None and not isinstance(prompt_base_commit_hash, str):
        raise RpcError(INVALID_PARAMS, "'prompt_base_commit_hash' must be a string")
    prompt_sha256 = params.get("prompt_sha256")
    if prompt_sha256 is not None and not isinstance(prompt_sha256, str):
        raise RpcError(INVALID_PARAMS, "'prompt_sha256' must be a string")
    code_commit_hash = params.get("code_commit_hash")
    if code_commit_hash is not None and not isinstance(code_commit_hash, str):
        raise RpcError(INVALID_PARAMS, "'code_commit_hash' must be a string")

    store = _store()
    store.set_version_mutation(
        version_id,
        commit_hash,
        summary,
        prompt_repo_id=prompt_repo_id,
        prompt_base_commit_hash=prompt_base_commit_hash,
        prompt_sha256=prompt_sha256,
        code_commit_hash=code_commit_hash,
    )
    store.append_log(version_id, "mutated", f"commit={commit_hash[:12]}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# autoresearch.evaluate_pending
# ---------------------------------------------------------------------------


@method("autoresearch.evaluate_pending")
def autoresearch_evaluate_pending(params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate pending versions that have a modification commit.

    For each version: if both backtest runs (base + mod) are complete,
    compute delta and decide. Otherwise, report needs_fill.

    Params:
        cohort:     str | None -- filter to a specific cohort
        version_id: int | None -- evaluate only this version (the orchestrator
                    passes the version it just triggered, so a layer of N agents
                    does N single-version evaluations instead of N full-cohort
                    scans — §14 R-A/§11.6 O(N²) fix). When omitted, scans all
                    pending versions (resume / `prism evaluate` CLI contract).

    Returns:
        {"results": [{version_id, status, delta_sharpe?}, ...]}
    """
    from mosaic.autoresearch.decider import decide
    from mosaic.autoresearch.evaluator import (
        compute_delta,
        ensure_baseline_run,
        validate_prompt_tool_compatibility,
    )

    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")
    version_id_filter = params.get("version_id")
    if version_id_filter is not None and (
        not isinstance(version_id_filter, int) or isinstance(version_id_filter, bool)
    ):
        raise RpcError(INVALID_PARAMS, "'version_id' must be an integer when provided")

    store = _store()
    config = _config()
    cohorts_cfg = config.get("cohorts", {})

    # Scope the work set. With a version_id we evaluate just that one row (O(1)
    # lookup, still pending+mutated-gated below); otherwise scan all pending.
    if version_id_filter is not None:
        one = store.get_prompt_version(version_id_filter)
        versions = [one] if one and one.get("status") == "pending" else []
    else:
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

        git = _git_ops_for_branch(v["branch_name"], v)
        compatibility = validate_prompt_tool_compatibility(v, git, baseline_git=_git_ops())
        if not compatibility["compatible"]:
            detail = (
                "unknown_tools="
                f"{compatibility['unknown_tools']}; "
                f"missing_files={compatibility['missing_files']}; "
                f"dropped_output_sections={compatibility.get('dropped_output_sections', [])}"
            )
            store.mark_version_incompatible(version_id, detail)
            store.append_log(version_id, "incompatible", detail)
            results.append({
                "version_id": version_id,
                "status": "incompatible",
                "detail": detail,
            })
            continue

        # Check if both runs exist.
        base_check = ensure_baseline_run(
            store, v_cohort, start_date, end_date, v["base_commit_hash"]
        )
        mod_check = ensure_baseline_run(
            store,
            v_cohort,
            start_date,
            end_date,
            mod_commit,
            prompt_repo_id=v.get("prompt_repo_id"),
            prompt_sha256=v.get("prompt_sha256"),
            code_commit_hash=v.get("code_commit_hash"),
        )

        if base_check["needs_fill"] or mod_check["needs_fill"]:
            missing_runs = []
            if base_check["needs_fill"]:
                missing_runs.append(
                    _run_fill_spec(
                        kind="base",
                        cohort=v_cohort,
                        start_date=start_date,
                        end_date=end_date,
                        prompt_commit_hash=v["base_commit_hash"],
                    )
                )
            if mod_check["needs_fill"]:
                missing_runs.append(
                    _run_fill_spec(
                        kind="mod",
                        cohort=v_cohort,
                        start_date=start_date,
                        end_date=end_date,
                        prompt_commit_hash=mod_commit,
                        prompt_repo_id=v.get("prompt_repo_id"),
                        prompt_sha256=v.get("prompt_sha256"),
                        code_commit_hash=v.get("code_commit_hash"),
                    )
                )
            results.append({
                "version_id": version_id,
                "status": "needs_fill",
                "missing_runs": missing_runs,
            })
            continue

        # Both runs complete: evaluate + decide.
        try:
            delta_result = compute_delta(store, version_id, config)
            # Re-read version after eval writes.
            updated_version = store.get_prompt_version(version_id)
            git = _git_ops_for_branch(updated_version["branch_name"], updated_version)
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
        branch: str -- branch name or ref to checkout (legacy project path)
        ref: str | None -- explicit ref; preferred for pinned prompt commits
        repo_target: str | None -- project_git (default) | private_git

    Returns:
        {"path": str, "repo_target": str, "prompts_root": str | None}
    """
    target = params.get("repo_target") or "project_git"
    if target not in ("project_git", "private_git"):
        raise RpcError(
            INVALID_PARAMS,
            "'repo_target' must be one of ('project_git', 'private_git')",
        )
    ref = params.get("ref") or params.get("branch")
    if not isinstance(ref, str) or not ref.strip():
        raise RpcError(INVALID_PARAMS, "'ref' or 'branch' must be a non-empty string")
    ref = ref.strip()
    git = _private_git_ops() if target == "private_git" else _git_ops()

    try:
        wt_path = git.add_worktree(ref)
    except Exception as exc:
        raise RpcError(
            AUTORESEARCH_ERROR, f"add_worktree failed: {exc}"
        ) from exc

    result = {"path": str(wt_path), "repo_target": target}
    if target == "private_git":
        result["prompts_root"] = str(wt_path / "prompts" / "mosaic")
    return result


# ---------------------------------------------------------------------------
# autoresearch.cleanup_worktree
# ---------------------------------------------------------------------------


@method("autoresearch.cleanup_worktree")
def autoresearch_cleanup_worktree(params: dict[str, Any]) -> dict[str, Any]:
    """Remove a previously created evaluation worktree.

    Params:
        path: str -- path returned by prepare_worktree
        repo_target: str | None -- project_git (default) | private_git

    Returns:
        {"ok": true}
    """
    path = _require_str(params, "path")
    target = params.get("repo_target") or "project_git"
    if target not in ("project_git", "private_git"):
        raise RpcError(
            INVALID_PARAMS,
            "'repo_target' must be one of ('project_git', 'private_git')",
        )
    git = _private_git_ops() if target == "private_git" else _git_ops()

    try:
        git.remove_worktree(Path(path))
    except Exception as exc:
        raise RpcError(
            AUTORESEARCH_ERROR, f"remove_worktree failed: {exc}"
        ) from exc

    return {"ok": True}


# ---------------------------------------------------------------------------
# autoresearch.gc_worktrees
# ---------------------------------------------------------------------------


@method("autoresearch.gc_worktrees")
def autoresearch_gc_worktrees(params: dict[str, Any]) -> dict[str, Any]:
    """Remove stale managed worktrees for project/private prompt repos.

    Params:
        repo_target: str | None -- project_git (default) | private_git | all
        max_age_hours: float | int | None -- default 24

    Returns:
        {"results": [{"repo_target", "removed", "kept", "missing"}]}
    """
    target = params.get("repo_target") or "all"
    if target not in ("project_git", "private_git", "all"):
        raise RpcError(
            INVALID_PARAMS,
            "'repo_target' must be one of ('project_git', 'private_git', 'all')",
        )
    max_age = params.get("max_age_hours", 24)
    if not isinstance(max_age, (int, float)) or isinstance(max_age, bool) or max_age < 0:
        raise RpcError(INVALID_PARAMS, "'max_age_hours' must be a non-negative number")

    targets = ["project_git", "private_git"] if target == "all" else [target]
    results: list[dict[str, Any]] = []
    for item in targets:
        if item == "private_git":
            try:
                git = _private_git_ops()
            except RpcError:
                # ``all`` shouldn't fail just because no private repo is configured;
                # an explicit ``private_git`` target still surfaces the error.
                if target == "all":
                    results.append({
                        "repo_target": item, "removed": [], "kept": [], "skipped": [],
                        "missing": True, "skipped_reason": "private prompt repo not configured",
                    })
                    continue
                raise
        else:
            git = _git_ops()
        try:
            result = git.gc_worktrees(max_age_hours=float(max_age))
        except Exception as exc:
            raise RpcError(AUTORESEARCH_ERROR, f"gc_worktrees failed: {exc}") from exc
        results.append({"repo_target": item, **result})
    return {"results": results}
