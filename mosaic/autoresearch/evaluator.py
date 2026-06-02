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
# Output-schema section header, e.g. ``## Output schema`` / ``## 输出 schema``.
_OUTPUT_SECTION_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*(?:output|输出)", re.IGNORECASE | re.MULTILINE)


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

    Part of the compatibility gate: catches prompt references to removed/renamed
    tools. Paired with the output-section check below; full field-level schema /
    role-contract validation still needs the deferred declarative-metadata layer.
    """
    return set(_TOOL_TOKEN_RE.findall(text))


def has_output_section(text: str) -> bool:
    """True if the prompt retains an output-schema section header.

    Every baseline prompt carries a ``## Output schema`` / ``## 输出 schema``
    section that drives the parseable structured output the agent's schema
    expects. A mutation that strips it is a structural contract regression
    (the model loses its output-format instructions).
    """
    return _OUTPUT_SECTION_RE.search(text) is not None


def validate_prompt_tool_compatibility(
    version: dict[str, Any],
    git,
    available_tools: Optional[set[str]] = None,
    baseline_git=None,
) -> dict[str, Any]:
    """Check a prompt commit against the current code (registry + contract).

    Two gates, both reading the committed files at ``modification_commit_hash``
    (never the floating working tree):
      * tool existence — referenced ``get_*`` tools must exist in ``tools.list``;
      * output-section preservation — if the project baseline for this agent has
        an output-schema section, the mutation must keep one (else the structured
        output the agent parses is likely broken).

    ``baseline_git`` reads the *project* repo (where the public baseline lives) at
    ``base_commit_hash`` — required for the output-section gate on private
    versions, whose ``git`` points at the private repo. When it can't be resolved,
    the output gate fails open (only positive baseline evidence triggers it).
    """
    from mosaic.bridge.handlers.prompts import _LANGS, _rel_path, _repo_root
    from mosaic.bridge.handlers.tools import tools_list
    from mosaic.autoresearch.git_ops import GitError, GitOps

    ref = version.get("modification_commit_hash")
    if not isinstance(ref, str) or not ref:
        raise ValueError("prompt version has no modification_commit_hash")
    agent = version["agent"]
    cohort = version["cohort"]
    base_commit = version.get("base_commit_hash")

    if available_tools is None:
        available_tools = {tool["name"] for tool in tools_list({})}

    if baseline_git is None and isinstance(base_commit, str) and base_commit:
        try:
            baseline_git = GitOps(_repo_root())
        except GitError:
            baseline_git = None

    def _baseline_had_section(rel: str) -> bool:
        if baseline_git is None or not base_commit:
            return False  # can't verify → fail open (no false positives)
        try:
            return has_output_section(baseline_git.show_file(base_commit, rel))
        except GitError:
            return False

    referenced: set[str] = set()
    missing_files: list[str] = []
    dropped_output_sections: list[str] = []
    for lang in _LANGS:
        rel = _rel_path(agent, cohort, lang)
        try:
            mod_text = git.show_file(ref, rel)
        except GitError:
            missing_files.append(rel)
            continue
        referenced.update(scan_prompt_tool_tokens(mod_text))
        if not has_output_section(mod_text) and _baseline_had_section(rel):
            dropped_output_sections.append(rel)

    unknown = sorted(referenced - available_tools)
    return {
        "compatible": not unknown and not missing_files and not dropped_output_sections,
        "referenced_tools": sorted(referenced),
        "unknown_tools": unknown,
        "missing_files": missing_files,
        "dropped_output_sections": dropped_output_sections,
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
