"""Phase 4C: backtest evaluation helpers (Plan ss11.5 4C).

Two functions:

  * :func:`ensure_baseline_run` -- checks whether a completed backtest_run
    already covers the given (cohort, start, end, base_commit). If not, the
    caller must trigger a ``backtest-fill`` before evaluation can proceed.

  * :func:`compute_delta` -- given a prompt_version id whose both runs (base
    and mod) are complete, reads their Sharpe metrics and records
    pre/post/delta on the version row.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TOOL_TOKEN_RE = re.compile(r"\bget_[A-Za-z0-9_]+\b")


def ensure_baseline_run(
    store,
    cohort: str,
    start_date: str,
    end_date: str,
    base_commit: str,
    *,
    prompt_repo_id: Optional[str] = None,
    prompt_sha256: Optional[str] = None,
    code_commit_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Check if a completed backtest_run exists for the given parameters.

    Returns:
        {"run_id": int | None, "needs_fill": bool}

    A run is considered valid when it matches (cohort, start_date, end_date,
    prompt_commit_hash/prompt_commit_ref matches ``base_commit`` and has a
    non-null ``completed_at``. When repo-aware metadata is supplied, it must
    match too.
    """
    runs = store.list_backtest_runs(cohort=cohort)
    for run in runs:
        commit_matches = (
            run["prompt_commit_hash"] == base_commit
            or run.get("prompt_commit_ref") == base_commit
        )
        metadata_matches = True
        if prompt_repo_id is not None:
            metadata_matches = metadata_matches and run.get("prompt_repo_id") == prompt_repo_id
        if prompt_sha256 is not None:
            metadata_matches = metadata_matches and run.get("prompt_sha256") == prompt_sha256
        if code_commit_hash is not None:
            metadata_matches = metadata_matches and run.get("code_commit_hash") == code_commit_hash
        if (
            run["start_date"] == start_date
            and run["end_date"] == end_date
            and commit_matches
            and metadata_matches
            and run["completed_at"] is not None
        ):
            return {"run_id": run["id"], "needs_fill": False}
    return {"run_id": None, "needs_fill": True}


def _find_run_sharpe(store, run_id: int) -> Optional[float]:
    """Get the Sharpe ratio for a completed backtest run via qlib stage-2."""
    try:
        from mosaic.backtest import run_backtest

        metrics = run_backtest(run_id=run_id, store=store)
        return float(metrics.sharpe)
    except ImportError:
        return None
    except Exception:
        return None


def scan_prompt_tool_tokens(text: str) -> set[str]:
    """Return get_* tool tokens mentioned in prompt text.

    This is intentionally a narrow v1 compatibility gate: it catches prompt
    references to removed/renamed tools, but not schema or role-contract drift.
    """
    return set(_TOOL_TOKEN_RE.findall(text))


def validate_prompt_tool_compatibility(
    version: dict[str, Any],
    git,
    available_tools: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Check a prompt commit against the current tools.list registry.

    Returns ``{"compatible": bool, "unknown_tools": [...], "referenced_tools": [...]}``.
    The gate reads the committed prompt files at ``modification_commit_hash`` so
    evaluation does not accidentally validate the floating working tree.
    """
    from mosaic.bridge.handlers.prompts import _LANGS, _rel_path
    from mosaic.bridge.handlers.tools import tools_list
    from mosaic.autoresearch.git_ops import GitError

    ref = version.get("modification_commit_hash")
    if not isinstance(ref, str) or not ref:
        raise ValueError("prompt version has no modification_commit_hash")
    agent = version["agent"]
    cohort = version["cohort"]

    if available_tools is None:
        available_tools = {tool["name"] for tool in tools_list({})}

    referenced: set[str] = set()
    missing_files: list[str] = []
    for lang in _LANGS:
        rel = _rel_path(agent, cohort, lang)
        try:
            referenced.update(scan_prompt_tool_tokens(git.show_file(ref, rel)))
        except GitError:
            missing_files.append(rel)

    unknown = sorted(referenced - available_tools)
    return {
        "compatible": not unknown and not missing_files,
        "referenced_tools": sorted(referenced),
        "unknown_tools": unknown,
        "missing_files": missing_files,
    }


def compute_delta(
    store,
    version_id: int,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evaluate a prompt_version by comparing base vs modification Sharpe.

    Reads the version row to get cohort, base_commit_hash, and
    modification_commit_hash. Looks up backtest_runs for each commit. If
    either run does not exist or is not complete, raises ValueError.

    On success: writes pre/post/delta to the version row via
    store.set_version_eval and appends a log entry. Returns
    {"pre_sharpe": float, "post_sharpe": float, "delta_sharpe": float}.
    """
    from mosaic.default_config import DEFAULT_CONFIG

    cfg = config if config is not None else DEFAULT_CONFIG
    cohorts_cfg = cfg.get("cohorts", {})

    version = store.get_prompt_version(version_id)
    if version is None:
        raise ValueError(f"prompt_version {version_id} not found")

    cohort = version["cohort"]
    base_commit = version["base_commit_hash"]
    mod_commit = version.get("modification_commit_hash")

    if not mod_commit:
        raise ValueError(
            f"prompt_version {version_id} has no modification_commit_hash "
            "(mutation not yet recorded)"
        )

    # Determine date range from cohort config.
    cohort_info = cohorts_cfg.get(cohort, {})
    start_date = cohort_info.get("start", "")
    end_date = cohort_info.get("end", "")
    if not start_date or not end_date:
        raise ValueError(
            f"cohort '{cohort}' not found in config.cohorts or missing start/end"
        )

    # Find completed base run.
    base_result = ensure_baseline_run(store, cohort, start_date, end_date, base_commit)
    if base_result["needs_fill"]:
        raise ValueError(
            f"no completed base backtest run for cohort={cohort}, "
            f"commit={base_commit[:8]}... (run backtest-fill first)"
        )

    # Find completed mod run.
    mod_result = ensure_baseline_run(
        store,
        cohort,
        start_date,
        end_date,
        mod_commit,
        prompt_repo_id=version.get("prompt_repo_id"),
        prompt_sha256=version.get("prompt_sha256"),
        code_commit_hash=version.get("code_commit_hash"),
    )
    if mod_result["needs_fill"]:
        raise ValueError(
            f"no completed mod backtest run for cohort={cohort}, "
            f"commit={mod_commit[:8]}... (run backtest-fill first)"
        )

    # Retrieve Sharpe for each run.
    pre_sharpe = _find_run_sharpe(store, base_result["run_id"])
    post_sharpe = _find_run_sharpe(store, mod_result["run_id"])

    if pre_sharpe is None:
        raise ValueError(
            f"cannot determine Sharpe for base run (cohort={cohort}, "
            f"commit={base_commit[:8]}...); qlib stage-2 may not have run"
        )
    if post_sharpe is None:
        raise ValueError(
            f"cannot determine Sharpe for mod run (cohort={cohort}, "
            f"commit={mod_commit[:8]}...); qlib stage-2 may not have run"
        )

    delta_sharpe = post_sharpe - pre_sharpe

    # Persist evaluation results.
    store.set_version_eval(version_id, pre_sharpe, post_sharpe, delta_sharpe)
    store.append_log(
        version_id,
        "evaluated",
        f"pre={pre_sharpe:.4f} post={post_sharpe:.4f} delta={delta_sharpe:.4f}",
    )

    logger.info(
        "compute_delta: version %d evaluated (delta=%.4f)",
        version_id,
        delta_sharpe,
    )

    return {
        "pre_sharpe": pre_sharpe,
        "post_sharpe": post_sharpe,
        "delta_sharpe": delta_sharpe,
    }
