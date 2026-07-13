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

import hashlib
import json
import math
import os
import re
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


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _authorized_prompt_release_operators() -> set[str]:
    raw = os.getenv("MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


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
            "private autoresearch branches",
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
                f"private prompt branch not found in configured prompt repo: {branch}",
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
    historical_sandbox = bool(params.get("historical_sandbox", False))
    historical_run_id = params.get("historical_run_id")
    if historical_sandbox:
        if not isinstance(historical_run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]+", historical_run_id
        ):
            raise RpcError(
                INVALID_PARAMS,
                "historical_sandbox requires a safe 'historical_run_id'",
            )
    as_of_date = params.get("as_of_date")
    if as_of_date is not None:
        if not historical_sandbox:
            raise RpcError(
                INVALID_PARAMS,
                "'as_of_date' is restricted to historical_sandbox triggers",
            )
        if not isinstance(as_of_date, str):
            raise RpcError(INVALID_PARAMS, "'as_of_date' must be YYYY-MM-DD")
        try:
            now = datetime.strptime(as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise RpcError(INVALID_PARAMS, "'as_of_date' must be YYYY-MM-DD") from exc
    else:
        now = _now()

    base_prompt_commit = params.get("base_prompt_commit")
    if base_prompt_commit is not None:
        if not historical_sandbox or not isinstance(base_prompt_commit, str):
            raise RpcError(
                INVALID_PARAMS,
                "'base_prompt_commit' requires historical_sandbox and a string ref",
            )
        try:
            base_prompt_commit = _private_git_ops().rev_parse(base_prompt_commit)
        except Exception as exc:
            raise RpcError(AUTORESEARCH_ERROR, f"invalid private prompt base ref: {exc}") from exc

    code_commit_hash = params.get("code_commit_hash")
    if code_commit_hash is not None and not isinstance(code_commit_hash, str):
        raise RpcError(INVALID_PARAMS, "'code_commit_hash' must be a string")

    store = _store()
    config = _config()

    # Monthly cap check (applies to any new trigger for this cohort).
    cap_result = check_monthly_cap(store, cohort, now, config)
    if not cap_result:
        raise RpcError(AUTORESEARCH_ERROR, cap_result.reason)

    # Early idempotency check when force_agent is known (avoids cooldown
    # rejection on what would be a no-op duplicate trigger).
    if force_agent:
        today_str = now.strftime("%Y-%m-%d")
        branch_name = (
            f"history/{historical_run_id}/{cohort}/{force_agent}/{today_str}"
            if historical_sandbox
            else f"cohort/{cohort}/auto/{force_agent}/{today_str}"
        )
        existing = store.get_version_by_branch(branch_name)
        if existing:
            return {
                "version_id": existing["id"],
                "agent": existing["agent"],
                "branch_name": existing["branch_name"],
                "base_commit": existing["base_commit_hash"],
                "existing": True,
                "prompt_commit_hash": existing.get("modification_commit_hash"),
                "prompt_sha256": existing.get("prompt_sha256"),
                "prompt_base_commit_hash": existing.get("prompt_base_commit_hash"),
            }

    # Select agent.
    agent = _select_agent(store, cohort, force_agent, config, now)

    # Idempotency: if the branch_name already has a version, return it.
    today_str = now.strftime("%Y-%m-%d")
    branch_name = (
            f"history/{historical_run_id}/{cohort}/{agent}/{today_str}"
        if historical_sandbox
        else f"cohort/{cohort}/auto/{agent}/{today_str}"
    )
    existing = store.get_version_by_branch(branch_name)
    if existing:
        return {
            "version_id": existing["id"],
            "agent": existing["agent"],
            "branch_name": existing["branch_name"],
            "base_commit": existing["base_commit_hash"],
            "existing": True,
            "prompt_commit_hash": existing.get("modification_commit_hash"),
            "prompt_sha256": existing.get("prompt_sha256"),
            "prompt_base_commit_hash": existing.get("prompt_base_commit_hash"),
        }

    # Cooldown check.
    cooldown_result = check_cooldown(store, cohort, agent, now, config)
    if not cooldown_result:
        raise RpcError(AUTORESEARCH_ERROR, cooldown_result.reason)

    git = _git_ops()
    project_commit = git.current_commit()
    base_commit = base_prompt_commit or project_commit
    code_commit = code_commit_hash or project_commit

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
        code_commit_hash=code_commit,
        created_at=now.isoformat(),
    )
    store.append_log(
        version_id,
        "triggered",
        f"agent={agent}, prompt_branch={branch_name}, code_base={code_commit[:12]}",
        created_at=now.isoformat(),
    )

    return {
        "version_id": version_id,
        "agent": agent,
        "branch_name": branch_name,
        "base_commit": base_commit,
        "existing": False,
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
        mutation_metadata: dict | None

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
    mutation_metadata = params.get("mutation_metadata")
    if mutation_metadata is not None and not isinstance(mutation_metadata, dict):
        raise RpcError(INVALID_PARAMS, "'mutation_metadata' must be an object")

    store = _store()
    existing_version = store.get_prompt_version(version_id)
    if existing_version is None:
        raise RpcError(INVALID_PARAMS, f"prompt_version {version_id} not found")
    if mutation_metadata is not None:
        existing_metadata = store.get_version_mutation_metadata(version_id)
        if existing_metadata is not None:
            if (
                existing_metadata == mutation_metadata
                and existing_version.get("modification_commit_hash") == commit_hash
            ):
                return {"ok": True, "idempotent": True}
            raise RpcError(
                AUTORESEARCH_ERROR,
                f"prompt_version {version_id} already has different mutation metadata",
            )
    store.set_version_mutation(
        version_id,
        commit_hash,
        summary,
        prompt_repo_id=prompt_repo_id,
        prompt_base_commit_hash=prompt_base_commit_hash,
        prompt_sha256=prompt_sha256,
        code_commit_hash=code_commit_hash,
        mutation_metadata=mutation_metadata,
    )
    if mutation_metadata is not None:
        store.append_log(version_id, "proposed", f"mutation_id={mutation_metadata['mutation_id']}")
        store.set_version_mutation_lifecycle(version_id, "validated")
        store.append_log(version_id, "validated", f"mutation_id={mutation_metadata['mutation_id']}")
    else:
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
    from mosaic.autoresearch.domain_evaluator import (
        DomainEvaluationError,
        evaluate_domain_mutation,
    )
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
    domain_sample_manifest = params.get("domain_sample_manifest")
    if domain_sample_manifest is not None and not isinstance(domain_sample_manifest, dict):
        raise RpcError(INVALID_PARAMS, "'domain_sample_manifest' must be an object")
    if domain_sample_manifest is not None and version_id_filter is None:
        raise RpcError(
            INVALID_PARAMS,
            "'domain_sample_manifest' requires a specific 'version_id'",
        )

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

        mutation_metadata = store.get_version_mutation_metadata(version_id)
        is_contract_evaluated_mutation = bool(
            mutation_metadata
            and (
                mutation_metadata.get("mutation_kind")
                in ("domain_knob", "generic_knob")
                or mutation_metadata.get("domain_card_id")
                or mutation_metadata.get("domain_card_ids")
            )
        )
        if is_contract_evaluated_mutation:
            lifecycle = store.get_prompt_version(version_id).get("mutation_lifecycle")
            if lifecycle in ("eligible_for_promotion", "reverted", "invalid", "kept"):
                results.append(
                    {
                        "version_id": version_id,
                        "status": lifecycle,
                        "evaluation_result": store.get_domain_evaluation_result(version_id),
                    }
                )
                continue
            if domain_sample_manifest is None:
                if lifecycle == "validated":
                    store.set_version_mutation_lifecycle(version_id, "shadow_evaluating")
                    store.append_log(version_id, "shadow_evaluating", "awaiting PIT sample manifest")
                    lifecycle = "shadow_evaluating"
                if lifecycle == "shadow_evaluating":
                    store.set_version_mutation_lifecycle(version_id, "needs_fill")
                    store.append_log(version_id, "needs_fill", "missing PIT sample manifest")
                results.append(
                    {
                        "version_id": version_id,
                        "status": "needs_fill",
                        "missing_domain_samples": True,
                        "missing_paired_samples": True,
                    }
                )
                continue
            try:
                if lifecycle == "validated":
                    store.set_version_mutation_lifecycle(version_id, "shadow_evaluating")
                elif lifecycle == "needs_fill":
                    store.set_version_mutation_lifecycle(version_id, "shadow_evaluating")
                evaluation_result = evaluate_domain_mutation(
                    mutation_metadata, domain_sample_manifest
                )
                if evaluation_result.get("holdout_consumption_required") is True:
                    try:
                        store.consume_domain_holdout(
                            version_id,
                            holdout_id=evaluation_result["holdout_id"],
                            mutation_id=evaluation_result["mutation_id"],
                            result_hash=evaluation_result["result_hash"],
                        )
                    except ValueError as exc:
                        raise DomainEvaluationError(str(exc)) from exc
                store.set_domain_evaluation_result(version_id, evaluation_result)
                evaluation_status = evaluation_result["status"]
                store.set_version_mutation_lifecycle(version_id, evaluation_status)
                store.append_log(
                    version_id,
                    evaluation_status,
                    (
                        f"metric={evaluation_result['metric_id']} "
                        f"samples={evaluation_result['sample_count']} "
                        f"effect={evaluation_result.get('effect_size')}"
                    ),
                )
                results.append(
                    {
                        "version_id": version_id,
                        "status": evaluation_status,
                        "evaluation_result": evaluation_result,
                    }
                )
            except DomainEvaluationError as exc:
                current = store.get_prompt_version(version_id).get("mutation_lifecycle")
                if current not in ("invalid", "reverted", "kept"):
                    store.set_version_mutation_lifecycle(version_id, "invalid")
                store.append_log(version_id, "invalid", str(exc))
                results.append(
                    {
                        "version_id": version_id,
                        "status": "invalid",
                        "detail": str(exc),
                    }
                )
            continue

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

    mutation_ids = {row["id"]: row.get("mutation_id") for row in versions}
    for result in results:
        mutation_id = mutation_ids.get(result["version_id"])
        if mutation_id:
            result["mutation_id"] = mutation_id
    return {"results": results}


# ---------------------------------------------------------------------------
# autoresearch.historical_validate
# ---------------------------------------------------------------------------


@method("autoresearch.historical_validate")
def autoresearch_historical_validate(params: dict[str, Any]) -> dict[str, Any]:
    """Read-only tool/output-contract validation for a historical candidate."""

    from mosaic.autoresearch.evaluator import validate_prompt_tool_compatibility

    version_id = _require_int(params, "version_id")
    version = _store().get_prompt_version(version_id)
    if version is None:
        raise RpcError(INVALID_PARAMS, f"prompt version {version_id} not found")
    if not str(version.get("branch_name") or "").startswith("history/"):
        raise RpcError(
            AUTORESEARCH_ERROR,
            "historical validation is restricted to history/* candidate branches",
        )
    if version.get("prompt_repo_id") != "private":
        raise RpcError(AUTORESEARCH_ERROR, "historical validation requires private prompts")
    try:
        result = validate_prompt_tool_compatibility(
            version,
            _git_ops_for_branch(version["branch_name"], version),
            baseline_git=_git_ops(),
        )
    except Exception as exc:
        raise RpcError(AUTORESEARCH_ERROR, f"historical compatibility check failed: {exc}") from exc
    return {
        "version_id": version_id,
        "compatible": bool(result.get("compatible")),
        "unknown_tools": result.get("unknown_tools", []),
        "missing_files": result.get("missing_files", []),
        "dropped_output_sections": result.get("dropped_output_sections", []),
    }


# ---------------------------------------------------------------------------
# autoresearch.historical_decide
# ---------------------------------------------------------------------------


@method("autoresearch.historical_decide")
def autoresearch_historical_decide(params: dict[str, Any]) -> dict[str, Any]:
    """Apply a keep/revert inside an isolated historical prompt branch.

    Unlike the normal decider this method never merges or deletes the private
    prompt repository's default branch.  A keep copies only the mutated agent's
    zh/en files onto an explicit ``history/.../active/...`` branch.  The call is
    idempotent so a checkpoint recovery can safely repeat it.
    """

    version_id = _require_int(params, "version_id")
    decision = _require_str(params, "decision")
    if decision not in ("keep", "revert"):
        raise RpcError(INVALID_PARAMS, "'decision' must be 'keep' or 'revert'")
    decided_at_raw = _require_str(params, "decided_at")
    try:
        decided_at = datetime.strptime(decided_at_raw, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        ).isoformat()
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, "'decided_at' must be YYYY-MM-DD") from exc

    store = _store()
    version = store.get_prompt_version(version_id)
    if version is None:
        raise RpcError(INVALID_PARAMS, f"prompt version {version_id} not found")
    branch_name = str(version.get("branch_name") or "")
    if not branch_name.startswith("history/"):
        raise RpcError(
            AUTORESEARCH_ERROR,
            "historical decisions are restricted to history/* candidate branches",
        )
    if version.get("status") in ("keep", "revert"):
        expected = "keep" if decision == "keep" else "revert"
        if version["status"] != expected:
            raise RpcError(AUTORESEARCH_ERROR, "historical decision already finalized")
        active_commit = _require_str(params, "base_ref")
        active_branch = params.get("active_branch")
        if decision == "keep" and isinstance(active_branch, str):
            try:
                active_commit = _private_git_ops().rev_parse(active_branch)
            except Exception:
                pass
        return {
            "version_id": version_id,
            "decision": decision,
            "active_commit": active_commit,
            "created": False,
        }

    if decision == "revert":
        store.decide_version(version_id, "revert", decided_at=decided_at)
        store.append_log(
            version_id,
            "historical_reverted",
            "historical sandbox candidate rejected; branch retained for audit",
            created_at=decided_at,
        )
        return {
            "version_id": version_id,
            "decision": decision,
            "active_commit": _require_str(params, "base_ref"),
            "created": True,
        }

    active_branch = _require_str(params, "active_branch")
    base_ref = _require_str(params, "base_ref")
    if not active_branch.startswith("history/") or "/active/" not in active_branch:
        raise RpcError(
            INVALID_PARAMS,
            "'active_branch' must be an isolated history/*/active/* branch",
        )
    if version.get("prompt_repo_id") != "private":
        raise RpcError(AUTORESEARCH_ERROR, "historical keep requires a private prompt commit")
    candidate_commit = version.get("modification_commit_hash")
    if not isinstance(candidate_commit, str) or not candidate_commit:
        raise RpcError(AUTORESEARCH_ERROR, "historical candidate commit is missing")

    from mosaic.bridge.handlers.prompts import _rel_path

    git = _private_git_ops()
    try:
        resolved_base = git.rev_parse(base_ref)
        candidate_commit = git.rev_parse(candidate_commit)
        files = {
            _rel_path(version["agent"], version["cohort"], lang): git.show_file(
                candidate_commit,
                _rel_path(version["agent"], version["cohort"], lang),
            )
            for lang in ("zh", "en")
        }
        branch_exists = git.branch_exists(active_branch)
        active_ref = git.rev_parse(active_branch) if branch_exists else resolved_base

        def _active_content_matches(path: str, content: str) -> bool:
            try:
                return git.show_file(active_branch, path) == content
            except Exception:
                return False

        already_applied = branch_exists and all(
            _active_content_matches(path, content) for path, content in files.items()
        )
        if active_ref != resolved_base and not already_applied:
            raise RpcError(
                AUTORESEARCH_ERROR,
                "historical active branch does not match the checkpoint base ref",
            )
        active_commit = (
            active_ref
            if already_applied
            else git.write_and_commit(
                files,
                message=(
                    f"historical sandbox: keep {version['agent']} "
                    f"for {version['cohort']} at {decided_at_raw}"
                ),
                branch=active_branch,
                base_ref=resolved_base,
            )
        )
    except RpcError:
        raise
    except Exception as exc:
        raise RpcError(AUTORESEARCH_ERROR, f"historical prompt promotion failed: {exc}") from exc

    store.decide_version(version_id, "keep", decided_at=decided_at)
    store.append_log(
        version_id,
        "historical_kept",
        f"sandbox_active_commit={active_commit}",
        created_at=decided_at,
    )
    return {
        "version_id": version_id,
        "decision": decision,
        "active_commit": active_commit,
        "created": True,
    }


# ---------------------------------------------------------------------------
# autoresearch.review_domain_promotion
# ---------------------------------------------------------------------------


@method("autoresearch.review_domain_promotion")
def autoresearch_review_domain_promotion(params: dict[str, Any]) -> dict[str, Any]:
    """Record an explicit operator keep/revert decision after holdout evaluation."""
    version_id = _require_int(params, "version_id")
    decision = _require_str(params, "decision")
    if decision not in ("keep", "revert"):
        raise RpcError(INVALID_PARAMS, "'decision' must be 'keep' or 'revert'")
    approved_by = _require_str(params, "approved_by")
    if approved_by not in _authorized_prompt_release_operators():
        raise RpcError(INVALID_PARAMS, "'approved_by' is not an authorized prompt release operator")
    approval_policy_id = _require_str(params, "approval_policy_id")
    if approval_policy_id not in (
        "domain_release_manual_v1",
        "decision_release_manual_v1",
    ):
        raise RpcError(INVALID_PARAMS, "unsupported domain promotion approval policy")
    review_reason = _require_str(params, "review_reason")
    store = _store()
    version = store.get_prompt_version(version_id)
    if version is None:
        raise RpcError(INVALID_PARAMS, f"prompt version {version_id} not found")
    existing_decision = store.get_domain_promotion_decision(version_id)
    if existing_decision is not None:
        if (
            existing_decision.get("decision") != decision
            or existing_decision.get("approved_by") != approved_by
            or existing_decision.get("approval_policy_id") != approval_policy_id
            or existing_decision.get("review_reason") != review_reason
        ):
            raise RpcError(AUTORESEARCH_ERROR, "domain promotion decision already exists")
        return {
            "version_id": version_id,
            "status": "kept" if decision == "keep" else "reverted",
            "decision_hash": _canonical_hash(existing_decision),
            "decision": existing_decision,
            "created": False,
        }
    if version.get("mutation_lifecycle") != "eligible_for_promotion":
        raise RpcError(AUTORESEARCH_ERROR, "domain mutation is not eligible for promotion")
    metadata = store.get_version_mutation_metadata(version_id)
    evaluation = store.get_domain_evaluation_result(version_id)
    if not metadata or metadata.get("mutation_kind") not in (
        "domain_knob",
        "generic_knob",
    ):
        raise RpcError(AUTORESEARCH_ERROR, "prompt version is not a governed knob mutation")
    if not evaluation or evaluation.get("status") != "eligible_for_promotion":
        raise RpcError(AUTORESEARCH_ERROR, "eligible domain evaluation result is missing")
    if evaluation.get("holdout_consumption_required") is not True:
        raise RpcError(AUTORESEARCH_ERROR, "domain evaluation did not consume a holdout")
    holdout = store.get_domain_holdout_consumption(evaluation.get("holdout_id"))
    if (
        not holdout
        or holdout.get("mutation_id") != metadata.get("mutation_id")
        or holdout.get("result_hash") != evaluation.get("result_hash")
    ):
        raise RpcError(AUTORESEARCH_ERROR, "holdout consumption evidence is not closed")
    if not metadata.get("transaction_manifest_hash"):
        raise RpcError(AUTORESEARCH_ERROR, "mutation transaction evidence is missing")
    if not all(
        version.get(field)
        for field in (
            "modification_commit_hash",
            "prompt_sha256",
            "code_commit_hash",
        )
    ):
        raise RpcError(AUTORESEARCH_ERROR, "prompt/code release pin metadata is missing")
    decided_at = datetime.now(timezone.utc).isoformat()
    decision_evidence = {
        "schema_version": "domain_promotion_decision_v1",
        "version_id": version_id,
        "mutation_id": metadata["mutation_id"],
        "experiment_id": metadata["experiment_id"],
        "decision": decision,
        "approved_by": approved_by,
        "approval_policy_id": approval_policy_id,
        "review_reason": review_reason,
        "evaluation_result_hash": evaluation["result_hash"],
        "pit_audit_hash": evaluation["pit_audit_hash"],
        "holdout_id": evaluation["holdout_id"],
        "transaction_manifest_hash": metadata["transaction_manifest_hash"],
        "prompt_commit_hash": version.get("modification_commit_hash"),
        "prompt_sha256": version.get("prompt_sha256"),
        "code_commit_hash": version.get("code_commit_hash"),
        "decided_at": decided_at,
    }
    decision_hash = _canonical_hash(decision_evidence)
    try:
        created = store.record_domain_promotion_decision(
            version_id,
            decision_evidence,
            decision_hash=decision_hash,
        )
    except ValueError as exc:
        raise RpcError(AUTORESEARCH_ERROR, str(exc)) from exc
    store.append_log(
        version_id,
        "kept" if decision == "keep" else "reverted",
        f"promotion_decision={decision_hash}; approved_by={approved_by}",
    )
    return {
        "version_id": version_id,
        "status": "kept" if decision == "keep" else "reverted",
        "decision_hash": decision_hash,
        "decision": decision_evidence,
        "created": created,
    }


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
