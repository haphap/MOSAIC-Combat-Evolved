"""Read-only legacy autoresearch audit and generic Git worktree RPCs.

The retired prompt mutation/evaluation protocol is intentionally absent. New
Prompt Candidates and experiments use ``prompt_optimizer.*``. These handlers
only expose historical queries plus worktree lifecycle operations shared by
backtest and prompt-inspection commands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..protocol import AUTORESEARCH_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


def _store():
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
            "MOSAIC_PROMPTS_REPO or MOSAIC_PRIVATE_PROMPT_REPO is required for "
            "private prompt worktrees",
        )
    try:
        return GitOps(validate_private_prompt_repo(repo, project_root=_repo_root()))
    except PromptRepoError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return value.strip()


@method("autoresearch.get_log")
def autoresearch_get_log(params: dict[str, Any]) -> dict[str, Any]:
    """Return immutable historical autoresearch log rows."""
    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")
    days = params.get("days")
    if days is not None and (
        not isinstance(days, int) or isinstance(days, bool) or days < 1
    ):
        raise RpcError(INVALID_PARAMS, "'days' must be a positive integer")
    return {"entries": _store().get_log(cohort=cohort, days=days)}


@method("autoresearch.list_active_branches")
def autoresearch_list_active_branches(params: dict[str, Any]) -> dict[str, Any]:
    """Return unresolved branches from the historical prompt-version ledger."""
    cohort = params.get("cohort")
    if cohort is not None and not isinstance(cohort, str):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a string when provided")
    return {"branches": _store().list_active_branches(cohort=cohort)}


@method("autoresearch.prepare_worktree")
def autoresearch_prepare_worktree(params: dict[str, Any]) -> dict[str, Any]:
    """Check out a pinned project/private ref for non-mutating evaluation."""
    target = params.get("repo_target") or "project_git"
    if target not in ("project_git", "private_git"):
        raise RpcError(
            INVALID_PARAMS,
            "'repo_target' must be one of ('project_git', 'private_git')",
        )
    ref = params.get("ref") or params.get("branch")
    if not isinstance(ref, str) or not ref.strip():
        raise RpcError(INVALID_PARAMS, "'ref' or 'branch' must be a non-empty string")
    git = _private_git_ops() if target == "private_git" else _git_ops()
    try:
        worktree = git.add_worktree(ref.strip())
    except Exception as exc:
        raise RpcError(AUTORESEARCH_ERROR, f"add_worktree failed: {exc}") from exc

    result = {"path": str(worktree), "repo_target": target}
    if target == "private_git":
        result["prompts_root"] = str(worktree / "prompts" / "mosaic")
    return result


@method("autoresearch.cleanup_worktree")
def autoresearch_cleanup_worktree(params: dict[str, Any]) -> dict[str, Any]:
    """Remove a worktree created by :func:`autoresearch_prepare_worktree`."""
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
        raise RpcError(AUTORESEARCH_ERROR, f"remove_worktree failed: {exc}") from exc
    return {"ok": True}


@method("autoresearch.gc_worktrees")
def autoresearch_gc_worktrees(params: dict[str, Any]) -> dict[str, Any]:
    """Remove stale managed worktrees without changing Prompt history."""
    target = params.get("repo_target") or "all"
    if target not in ("project_git", "private_git", "all"):
        raise RpcError(
            INVALID_PARAMS,
            "'repo_target' must be one of ('project_git', 'private_git', 'all')",
        )
    max_age = params.get("max_age_hours", 24)
    if (
        not isinstance(max_age, (int, float))
        or isinstance(max_age, bool)
        or max_age < 0
    ):
        raise RpcError(INVALID_PARAMS, "'max_age_hours' must be a non-negative number")

    results: list[dict[str, Any]] = []
    targets = ["project_git", "private_git"] if target == "all" else [target]
    for item in targets:
        if item == "private_git":
            try:
                git = _private_git_ops()
            except RpcError:
                if target != "all":
                    raise
                results.append(
                    {
                        "repo_target": item,
                        "removed": [],
                        "kept": [],
                        "skipped": [],
                        "missing": True,
                        "skipped_reason": "private prompt repo not configured",
                    }
                )
                continue
        else:
            git = _git_ops()
        try:
            result = git.gc_worktrees(max_age_hours=float(max_age))
        except Exception as exc:
            raise RpcError(AUTORESEARCH_ERROR, f"gc_worktrees failed: {exc}") from exc
        results.append({"repo_target": item, **result})
    return {"results": results}
