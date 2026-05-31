"""Phase 4D: keep/revert decision logic (Plan ss11.5 4D).

After evaluation computes ``delta_sharpe`` for a prompt_version, the decider
applies the keep/revert threshold:

  * delta >= keep_threshold (default 0.1): merge branch to main, mark
    version ``keep``, append log.
  * delta < keep_threshold: delete branch, mark version ``revert``, append
    log.

The :func:`decide` function is the single entry point. It is called
automatically by ``autoresearch.evaluate_pending`` after compute_delta
succeeds, and may also be invoked manually via future RPC extensions.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from mosaic.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def _ar_cfg(config: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    cfg = config if config is not None else DEFAULT_CONFIG
    return cfg.get("autoresearch", {}) or {}


def decide(
    store,
    git_ops,
    version: dict[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Apply keep/revert logic to a fully-evaluated prompt_version.

    Args:
        store: ScorecardStore instance.
        git_ops: GitOps instance for branch operations.
        version: dict from store.get_prompt_version (must have delta_sharpe).
        config: Optional config dict (defaults to DEFAULT_CONFIG).

    Returns:
        The decided status string: ``'keep'`` or ``'revert'``.

    Raises:
        ValueError: if version has no delta_sharpe (not yet evaluated).
    """
    delta_sharpe = version.get("delta_sharpe")
    if delta_sharpe is None:
        raise ValueError(
            f"version {version.get('id')} has no delta_sharpe -- "
            "call compute_delta first"
        )

    version_id = version["id"]
    branch = version["branch_name"]
    keep_threshold = float(_ar_cfg(config).get("keep_threshold_delta_sharpe", 0.1))

    if delta_sharpe >= keep_threshold:
        # Keep path: merge the feature branch into main.
        try:
            git_ops.merge_to_main(branch)
        except Exception as exc:
            logger.warning(
                "decide: merge_to_main(%s) failed: %s; proceeding with keep status",
                branch,
                exc,
            )
        else:
            # Opt-in: mirror the merged main to a self-hosted git server.
            git_cfg = _ar_cfg(config).get("git", {}) or {}
            if git_cfg.get("push"):
                remote = str(git_cfg.get("remote", "origin"))
                try:
                    git_ops.push("main", remote)
                except Exception as exc:
                    logger.warning(
                        "decide: push(main → %s) failed: %s; keep stands locally",
                        remote,
                        exc,
                    )
        store.decide_version(version_id, "keep")
        store.append_log(
            version_id,
            "kept",
            f"delta_sharpe={delta_sharpe:.4f} >= threshold={keep_threshold}",
        )
        logger.info("decide: version %d kept (delta=%.4f)", version_id, delta_sharpe)
        return "keep"
    else:
        # Revert path: delete the feature branch.
        try:
            git_ops.delete_branch(branch)
        except Exception as exc:
            logger.warning(
                "decide: delete_branch(%s) failed: %s; proceeding with revert status",
                branch,
                exc,
            )
        store.decide_version(version_id, "revert")
        store.append_log(
            version_id,
            "reverted",
            f"delta_sharpe={delta_sharpe:.4f} < threshold={keep_threshold}",
        )
        logger.info("decide: version %d reverted (delta=%.4f)", version_id, delta_sharpe)
        return "revert"
