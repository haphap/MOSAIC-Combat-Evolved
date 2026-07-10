"""``prompts.*`` JSON-RPC handlers (Plan §6.2 / §11.5 4B).

Git-aware prompt read/write backing the TS mutator (4B) and evaluator (4C):

    * prompts.read(agent, cohort, lang, ref?)
        - ref omitted → read the working-tree file (cohort → cohort_default
          fallback, same chain as the TS loader).
        - ref set     → read the file as it exists at that commit/branch via
          ``git show`` (cohort path, falling back to cohort_default).
      → {"content": str, "path": <repo-relative path>}

    * prompts.write(agent, cohort, contents, branch?, message?)
        - ``contents`` maps language ("zh"/"en") → markdown. Writing the whole
          {zh, en} pair in one call keeps a mutation branch to a single commit
          (Plan §11.5 git decision: "每条 feature branch 只含 1 个 commit").
        - branch set     → commit the files on ``branch`` via git_ops (the
          mutation path). → {"commit_hash": str, "branch": str, "paths": [...]}
        - branch omitted → write straight to the working tree (TEST ONLY,
          dirties the tree). → {"paths": [...]}

Note: this deviates from the literal ``prompts.write(..., lang, content)``
pseudo-signature in the plan to honour the single-commit invariant; the 4E
orchestrator calls it once with both languages.

Agent→layer resolution mirrors ``mosaic-ts/src/agents/prompts/cohorts.ts``
(Plan §5). Kept Python-side so the handler is self-contained and unit-testable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method

# Mirror of cohorts.ts AGENTS_BY_LAYER (Plan §5). Keep in sync with the TS map.
_AGENTS_BY_LAYER: dict[str, tuple[str, ...]] = {
    "macro": (
        "central_bank", "geopolitical", "china", "dollar", "yield_curve",
        "commodities", "volatility", "emerging_markets", "news_sentiment",
        "institutional_flow",
    ),
    "sector": (
        "semiconductor", "energy", "biotech", "consumer", "industrials",
        "financials", "relationship_mapper",
    ),
    "superinvestor": ("druckenmiller", "munger", "burry", "ackman"),
    "decision": ("cro", "alpha_discovery", "autonomous_execution", "cio"),
}
_LAYER_BY_AGENT: dict[str, str] = {
    agent: layer for layer, agents in _AGENTS_BY_LAYER.items() for agent in agents
}
_ALL_AGENTS = tuple(agent for agents in _AGENTS_BY_LAYER.values() for agent in agents)
_DEFAULT_COHORT = "cohort_default"
_LANGS = ("zh", "en")
_WRITE_TARGETS = ("private_git", "project_git", "working_tree")
_CANONICAL_PROMPT_REPO_ID = "https://github.com/haphap/MOSAIC-Prompts"
_PROMPT_CONTRACT_VERSION = "rke_prompt_contract_v1"
_RESEARCH_KNOBS_FENCE_RE = re.compile(r"```research-knobs\s*\n([\s\S]*?)```")
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_CANDIDATE_BRANCH_RE = re.compile(r"^(?:cohort|autoresearch)/[A-Za-z0-9_./-]+$")
_SAFE_CANDIDATE_FILE_RE = re.compile(
    r"^(?:prompts/mosaic/[A-Za-z0-9_-]+/(?:macro|sector|superinvestor|decision)/"
    r"[A-Za-z0-9_-]+\.(?:zh|en)\.md|"
    r"registry/domain_knobs/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.json)$"
)
_PROMPT_CONTRACT_CATEGORIES = {
    "role_boundary": ("role boundary", "角色边界"),
    "required_inputs_tools": ("required inputs", "required tools", "必需输入", "必需工具"),
    "rke_prior_policy": ("rke prior policy", "rke 先验策略"),
    "workflow": ("workflow", "工作流程"),
    "output_schema": ("output schema", "输出 schema"),
    "audit_footprint_contract": (
        "audit and footprint contract",
        "audit/footprint contract",
        "审计与足迹契约",
        "审计/足迹契约",
    ),
    "privacy_boundary": ("privacy boundary", "隐私边界"),
    "confidence_policy": ("confidence policy", "置信度策略"),
    "refusal_no_action": ("refusal and no-action", "refusal/no-action", "拒绝与 no-action"),
    "autoresearch_evolution_contract": ("autoresearch evolution contract", "autoresearch 演化契约"),
}
_AUDIT_FOOTPRINT_TOKENS = {
    "claim_type": ("claim type", "claim_type"),
    "target": ("target",),
    "confidence": ("confidence",),
    "current_data_confirmation": ("current-data confirmation", "current_data_confirmed"),
    "stale_prior": ("stale prior", "stale"),
    "contradictory_prior": ("contradictory prior", "contradictory"),
    "rke_context_hash": ("rke context hash", "rke_context_hash"),
    "ranking_policy_id": ("ranking_policy_id",),
    "retrieval_rank": ("retrieval_rank",),
    "priority_bucket": ("priority_bucket",),
    "truncation_audit": ("truncation audit", "truncated_item_count"),
}
_PRIVACY_TOKENS = {
    "report_prose": ("report prose",),
    "source_spans": ("source spans", "source_span_ids"),
    "prompt_body": ("prompt body",),
    "local_paths": ("local paths",),
    "urls": ("urls",),
    "reviewer_text": ("reviewer text",),
    "licensed_metadata": ("licensed metadata",),
}
_IMMUTABLE_GUARDRAIL_TOKENS = {
    "role boundary": ("role boundary", "角色边界"),
    "output schema": ("output schema", "输出 schema"),
    "required tools": ("required tools", "必需工具"),
    "current-data gate": ("current-data gate", "current data gate", "当前数据门槛"),
    "rke-prior policy": ("rke-prior policy", "rke prior policy", "rke 先验策略"),
    "privacy boundary": ("privacy boundary", "隐私边界"),
    "audit/footprint contract": ("audit/footprint contract", "审计/足迹契约"),
    "shadow/promotion safety policy": (
        "shadow/promotion safety policy",
        "shadow/promotion 安全策略",
    ),
}
_STANDARD_SECTOR_FIELDS = ("longs", "shorts", "sector_score", "key_drivers", "confidence")
_SUPERINVESTOR_FIELDS = ("picks", "philosophy_note", "key_drivers", "confidence")
_AGENT_SCHEMA_FIELDS: dict[str, tuple[str, ...]] = {
    "central_bank": (
        "stance",
        "key_rate_change_bps",
        "qe_qt_balance_change",
        "next_window",
        "key_drivers",
        "confidence",
    ),
    "china": ("policy_direction", "sector_focus", "risk_drivers", "key_drivers", "confidence"),
    "geopolitical": (
        "escalation_level",
        "hot_zones",
        "trade_impact",
        "key_drivers",
        "confidence",
    ),
    "dollar": (
        "dxy_trend",
        "cny_pressure",
        "dxy_cny_correlation",
        "key_drivers",
        "confidence",
    ),
    "yield_curve": (
        "curve_shape",
        "recession_signal",
        "cn_us_spread_bps",
        "key_drivers",
        "confidence",
    ),
    "commodities": (
        "oil_regime",
        "metals_regime",
        "ag_regime",
        "china_demand_signal",
        "key_drivers",
        "confidence",
    ),
    "volatility": ("vix_regime", "ivx_regime", "regime_filter", "key_drivers", "confidence"),
    "emerging_markets": (
        "em_relative",
        "hk_a_share_ratio",
        "capital_flow",
        "key_drivers",
        "confidence",
    ),
    "news_sentiment": (
        "retail_sentiment_score",
        "hot_topics",
        "contrarian_flag",
        "key_drivers",
        "confidence",
    ),
    "institutional_flow": (
        "main_net_flow_cny",
        "top_buyers",
        "sectors_in_out",
        "key_drivers",
        "confidence",
    ),
    "semiconductor": _STANDARD_SECTOR_FIELDS,
    "energy": _STANDARD_SECTOR_FIELDS,
    "biotech": _STANDARD_SECTOR_FIELDS,
    "consumer": _STANDARD_SECTOR_FIELDS,
    "industrials": _STANDARD_SECTOR_FIELDS,
    "financials": _STANDARD_SECTOR_FIELDS,
    "relationship_mapper": (
        "supply_chains",
        "ownership_clusters",
        "contagion_risks",
        "key_drivers",
        "confidence",
    ),
    "druckenmiller": _SUPERINVESTOR_FIELDS,
    "munger": _SUPERINVESTOR_FIELDS,
    "burry": _SUPERINVESTOR_FIELDS,
    "ackman": _SUPERINVESTOR_FIELDS,
    "cro": ("rejected_picks", "correlated_risks", "black_swan_scenarios", "confidence"),
    "alpha_discovery": ("novel_picks", "confidence"),
    "autonomous_execution": ("trades", "confidence"),
    "cio": ("portfolio_actions", "confidence"),
}


def _repo_root() -> Path:
    """Repo root; ``MOSAIC_REPO_ROOT`` override lets tests point at a tmp repo."""
    env = os.getenv("MOSAIC_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def _rel_path(agent: str, cohort: str, lang: str) -> str:
    layer = _LAYER_BY_AGENT.get(agent)
    if layer is None:
        raise RpcError(INVALID_PARAMS, f"unknown agent '{agent}'")
    return f"prompts/mosaic/{cohort}/{layer}/{agent}.{lang}.md"


def _require_str(params: dict, key: str) -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty string")
    return val.strip()


def _require_lang(params: dict) -> str:
    lang = _require_str(params, "lang")
    if lang not in _LANGS:
        raise RpcError(INVALID_PARAMS, f"'lang' must be one of {_LANGS}, got {lang!r}")
    return lang


def _git():
    from mosaic.autoresearch.git_ops import GitOps

    return GitOps(_repo_root())


def _private_git():
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
            "prompts.write(target=private_git)",
        )
    try:
        return GitOps(validate_private_prompt_repo(repo, project_root=_repo_root()))
    except PromptRepoError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc


def _prompt_repo_id() -> str:
    return os.getenv("MOSAIC_PROMPTS_REPO_ID") or os.getenv(
        "MOSAIC_PRIVATE_PROMPT_REPO_ID", "private"
    )


def _formal_prompt_repo_id() -> str:
    return os.getenv("MOSAIC_PROMPTS_REPO_ID") or os.getenv(
        "MOSAIC_PRIVATE_PROMPT_REPO_ID", _CANONICAL_PROMPT_REPO_ID
    )


def _public_write_allowed(params: dict[str, Any]) -> bool:
    # Per-invocation only — deliberately NOT honoring a long-lived env var, so the
    # escape hatch can't be left globally enabled (plan principle 7).
    return bool(params.get("allow_public_prompt_write"))


def _prompt_sha256(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[rel].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _domain_registry_extra_files(
    value: Any,
    *,
    agent: str,
    cohort: str,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) != 1:
        raise RpcError(INVALID_PARAMS, "'extra_files' must contain exactly one domain registry")
    expected_path = f"registry/domain_knobs/{cohort}/{agent}.json"
    content = value.get(expected_path)
    if not isinstance(content, str) or not content:
        raise RpcError(
            INVALID_PARAMS,
            f"'extra_files' may only contain {expected_path!r}",
        )
    try:
        registry = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RpcError(INVALID_PARAMS, "domain knob registry must be valid JSON") from exc
    if not isinstance(registry, dict):
        raise RpcError(INVALID_PARAMS, "domain knob registry must be an object")
    expected_keys = {
        "schema_version",
        "agent",
        "cohort",
        "catalog_version",
        "values_by_path",
        "weight_groups",
        "cross_field_groups",
        "last_mutation_id",
    }
    if set(registry) != expected_keys:
        raise RpcError(INVALID_PARAMS, "domain knob registry fields do not match v1 schema")
    owner = registry.get("agent")
    if (
        registry.get("schema_version") != "domain_knob_values_v1"
        or registry.get("catalog_version") != "domain_knob_catalog_v1"
        or registry.get("cohort") != cohort
        or not isinstance(owner, str)
        or owner.split(".")[-1] != agent
        or not isinstance(registry.get("values_by_path"), dict)
        or not all(
            isinstance(path, str) and path.startswith("/rule_packs/")
            for path in registry["values_by_path"]
        )
        or not isinstance(registry.get("last_mutation_id"), str)
    ):
        raise RpcError(INVALID_PARAMS, "domain knob registry identity or values are invalid")
    return {expected_path: content}


def _require_candidate_branch(params: dict[str, Any]) -> str:
    branch = _require_str(params, "branch")
    if (
        not _SAFE_CANDIDATE_BRANCH_RE.fullmatch(branch)
        or ".." in branch
        or branch.endswith("/")
    ):
        raise RpcError(INVALID_PARAMS, "candidate branch is outside the autoresearch namespace")
    return branch


def _prompt_contract_check_ref(prompt_sha256: str) -> str:
    return f"prompt-contract:{_PROMPT_CONTRACT_VERSION}:{prompt_sha256}"


def _formal_prompt_version_id(prompt_sha256: str) -> int:
    if not prompt_sha256:
        return 0
    return int(prompt_sha256[:12], 16) % 2_000_000_000 + 1


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _safe_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _research_knobs_enabled_agents() -> set[str]:
    raw = os.getenv("MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _research_knobs_enabled(agent: str, enabled: set[str]) -> bool:
    return "*" in enabled or agent in enabled


def _canonical_research_knobs_fence(text: str) -> tuple[str | None, list[str]]:
    matches = list(_RESEARCH_KNOBS_FENCE_RE.finditer(text))
    if len(matches) != 1:
        return None, [f"research_knobs_fence_count_{len(matches)}"]
    body = matches[0].group(1)
    lines = [line.rstrip() for line in body.strip().splitlines()]
    return "\n".join(lines), []


def _git_run(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def _git_dirty_count(repo: Path) -> int:
    return len(_git_run(repo, "status", "--porcelain").splitlines())


def _optional_str_list(
    params: dict[str, Any],
    key: str,
    *,
    allowed: tuple[str, ...],
    default: tuple[str, ...],
) -> tuple[str, ...]:
    values = params.get(key)
    if values is None:
        return default
    if not isinstance(values, list) or not values:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a non-empty list")
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RpcError(INVALID_PARAMS, f"'{key}' entries must be non-empty strings")
        normalized = value.strip()
        if normalized not in allowed:
            raise RpcError(INVALID_PARAMS, f"unsupported {key} entry {normalized!r}")
        out.append(normalized)
    return tuple(out)


def _formal_prompt_source() -> dict[str, Any]:
    """Resolve the private prompt source for formal benchmark/replay preflight."""
    from mosaic.autoresearch.prompt_repo import (
        private_prompt_repo_from_env,
        validate_private_prompt_repo,
    )

    explicit_root = os.getenv("MOSAIC_PROMPTS_ROOT")
    if explicit_root and explicit_root.strip():
        prompts_root = Path(explicit_root).expanduser().resolve()
        if not prompts_root.exists():
            return {"ready": False, "blocked_reason": "private_prompt_unavailable"}
        try:
            repo_root = Path(_git_run(prompts_root, "rev-parse", "--show-toplevel")).resolve()
            revision = _git_run(repo_root, "rev-parse", "HEAD")
            project_root = _repo_root()
            if repo_root == project_root or repo_root.is_relative_to(project_root):
                return {"ready": False, "blocked_reason": "prompt_provenance_unavailable"}
            dirty_count = _git_dirty_count(repo_root)
            if dirty_count:
                return {
                    "ready": False,
                    "blocked_reason": "private_prompt_repo_dirty",
                    "resolved_source": "private_root",
                    "prompt_repo_id": _formal_prompt_repo_id(),
                    "prompt_repo_revision": revision,
                    "prompt_repo_dirty_count": dirty_count,
                }
        except Exception:
            return {"ready": False, "blocked_reason": "prompt_provenance_unavailable"}
        return {
            "ready": True,
            "resolved_source": "private_root",
            "repo_root": repo_root,
            "prompts_root": prompts_root,
            "prompt_repo_id": _formal_prompt_repo_id(),
            "prompt_repo_revision": revision,
        }

    repo = private_prompt_repo_from_env()
    if repo is None:
        return {"ready": False, "blocked_reason": "private_prompt_unavailable"}
    try:
        repo_root = validate_private_prompt_repo(repo, project_root=_repo_root())
        revision = _git_run(repo_root, "rev-parse", "HEAD")
        dirty_count = _git_dirty_count(repo_root)
        if dirty_count:
            return {
                "ready": False,
                "blocked_reason": "private_prompt_repo_dirty",
                "resolved_source": "private_repo",
                "prompt_repo_id": _formal_prompt_repo_id(),
                "prompt_repo_revision": revision,
                "prompt_repo_dirty_count": dirty_count,
            }
    except Exception:
        return {"ready": False, "blocked_reason": "prompt_provenance_unavailable"}
    return {
        "ready": True,
        "resolved_source": "private_repo",
        "repo_root": repo_root,
        "prompts_root": repo_root / "prompts" / "mosaic",
        "prompt_repo_id": _formal_prompt_repo_id(),
        "prompt_repo_revision": revision,
    }


def _blocked_prompt_preflight_row(
    *,
    cohort: str,
    agent: str,
    lang: str,
    reason: str,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layer = _LAYER_BY_AGENT[agent]
    row = {
        "agent": agent,
        "layer": layer,
        "cohort": cohort,
        "lang": lang,
        "status": "blocked",
        "blocked_reason": reason,
        "fallback_used": False,
    }
    if source and source.get("ready"):
        path = Path(source["prompts_root"]) / cohort / layer / f"{agent}.{lang}.md"
        rel = path.relative_to(Path(source["repo_root"]))
        row.update({
            "prompt_repo_id": source["prompt_repo_id"],
            "prompt_repo_revision": source["prompt_repo_revision"],
            "prompt_file_path": rel.as_posix(),
            "resolved_source": source["resolved_source"],
        })
    return row


def _store():
    from mosaic.scorecard import get_store

    return get_store()


def _require_int(params: dict[str, Any], key: str) -> int:
    val = params.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be an integer")
    return val


def _optional_str(params: dict[str, Any], key: str) -> str | None:
    val = params.get(key)
    if val is None:
        return None
    if not isinstance(val, str):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a string when provided")
    return val


@method("prompts.read")
def prompts_read(params: dict[str, Any]) -> dict[str, Any]:
    agent = _require_str(params, "agent")
    cohort = _require_str(params, "cohort")
    lang = _require_lang(params)
    ref: Optional[str] = params.get("ref") or None

    # cohort path first, then cohort_default fallback (mirrors the TS loader).
    candidates = [cohort] + ([_DEFAULT_COHORT] if cohort != _DEFAULT_COHORT else [])
    rels = [_rel_path(agent, c, lang) for c in candidates]

    if ref:
        git = _git()
        from mosaic.autoresearch.git_ops import GitError

        for rel in rels:
            try:
                return {"content": git.show_file(ref, rel), "path": rel}
            except GitError:
                continue
        raise RpcError(INVALID_PARAMS, f"prompt not found at ref {ref!r}: tried {rels}")

    root = _repo_root()
    for rel in rels:
        fp = root / rel
        if fp.exists():
            return {"content": fp.read_text(encoding="utf-8"), "path": rel}
    raise RpcError(INVALID_PARAMS, f"prompt not found: tried {rels}")


@method("prompts.write")
def prompts_write(params: dict[str, Any]) -> dict[str, Any]:
    agent = _require_str(params, "agent")
    cohort = _require_str(params, "cohort")
    if not _SAFE_PATH_SEGMENT_RE.fullmatch(cohort):
        raise RpcError(INVALID_PARAMS, "'cohort' must be a safe path segment")
    contents = params.get("contents")
    if not isinstance(contents, dict) or not contents:
        raise RpcError(INVALID_PARAMS, "'contents' must be a non-empty {lang: text} object")
    for lang, text in contents.items():
        if lang not in _LANGS or not isinstance(text, str):
            raise RpcError(INVALID_PARAMS, f"invalid contents entry {lang!r}")

    branch: Optional[str] = params.get("branch") or None
    target = params.get("target") or ("project_git" if branch else "working_tree")
    if target not in _WRITE_TARGETS:
        raise RpcError(INVALID_PARAMS, f"'target' must be one of {_WRITE_TARGETS}, got {target!r}")
    if params.get("extra_files") is not None and target != "private_git":
        raise RpcError(INVALID_PARAMS, "domain registry write-back requires target=private_git")

    # Always write to the cohort-specific path (no fallback — a mutation
    # creates/overwrites the cohort's own file).
    prompt_files = {_rel_path(agent, cohort, lang): text for lang, text in contents.items()}
    extra_files = _domain_registry_extra_files(
        params.get("extra_files"),
        agent=agent,
        cohort=cohort,
    )
    files = {**prompt_files, **extra_files}
    prompt_sha256 = _prompt_sha256(prompt_files)
    extra_files_sha256 = _prompt_sha256(extra_files) if extra_files else None
    # Default keeps the existing autoresearch mutation path (a project-repo
    # feature branch); ``private_git`` is opt-in via an explicit ``target`` until
    # Phase 5 moves the evaluation worktree + read-at-ref to the private repo too.
    # (Flipping the default before then breaks the optimize→evaluate loop, since
    # ``autoresearch.prepare_worktree`` / ``prompts.read(ref)`` still use the
    # project repo. Phase 6's CI provenance guard is what blocks optimized
    # prompts from reaching project PRs in the interim.)
    if target == "private_git":
        if not branch:
            raise RpcError(INVALID_PARAMS, "prompts.write(target=private_git) requires 'branch'")
        message = params.get("message") or f"autoresearch: mutate {agent} prompt ({cohort})"
        try:
            git = _private_git()
            base_commit = git.rev_parse("main")
            commit = git.write_and_commit(files, message=message, branch=branch)
        except Exception as exc:
            if isinstance(exc, RpcError):
                raise
            raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc
        return {
            "target": target,
            "prompt_repo_id": _prompt_repo_id(),
            "prompt_base_commit_hash": base_commit,
            "prompt_sha256": prompt_sha256,
            "extra_files_sha256": extra_files_sha256,
            "commit_hash": commit,
            "prompt_commit_hash": commit,
            "branch": branch,
            "paths": sorted(files),
        }

    if target == "project_git":
        if not branch:
            raise RpcError(INVALID_PARAMS, "prompts.write(target=project_git) requires 'branch'")
        # A project-repo feature-branch commit is the existing autoresearch
        # mutation mechanism (isolated on a branch, not the tracked tree), so it
        # is not gated by the escape hatch. The working-tree path below — which
        # dirties tracked ``prompts/mosaic/**`` directly — is.
        message = params.get("message") or f"autoresearch: mutate {agent} prompt ({cohort})"
        try:
            git = _git()
            base_commit = git.rev_parse("main")
            commit = git.write_and_commit(files, message=message, branch=branch)
        except Exception as exc:
            raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc
        return {
            "target": target,
            "prompt_repo_id": "project",
            "prompt_base_commit_hash": base_commit,
            "prompt_sha256": prompt_sha256,
            "commit_hash": commit,
            "prompt_commit_hash": commit,
            "branch": branch,
            "paths": sorted(files),
        }

    if not _public_write_allowed(params):
        raise RpcError(
            INVALID_PARAMS,
            "working-tree prompt writes require allow_public_prompt_write=true",
        )

    # Working-tree write (test-only / explicit baseline escape hatch).
    root = _repo_root()
    for rel, text in files.items():
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(text, encoding="utf-8")
    return {
        "target": target,
        "prompt_repo_id": "project",
        "prompt_sha256": prompt_sha256,
        "paths": sorted(files),
    }


@method("prompts.candidate_state")
def prompts_candidate_state(params: dict[str, Any]) -> dict[str, Any]:
    """Inspect a private candidate ref without returning prompt/registry content."""
    branch = _require_candidate_branch(params)
    expected_hashes = params.get("expected_hashes")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        raise RpcError(INVALID_PARAMS, "'expected_hashes' must be a non-empty object")
    for path, expected_hash in expected_hashes.items():
        if (
            not isinstance(path, str)
            or not _SAFE_CANDIDATE_FILE_RE.fullmatch(path)
            or not isinstance(expected_hash, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_hash)
        ):
            raise RpcError(INVALID_PARAMS, "candidate file path or hash is invalid")
    git = _private_git()
    if not git.branch_exists(branch):
        return {"candidate_visible": False, "new_commit": None, "hashes_match": False}
    commit = git.rev_parse(branch)
    hashes_match = True
    for path, expected_hash in expected_hashes.items():
        try:
            content = git.show_file(commit, path)
        except Exception:
            hashes_match = False
            break
        actual_hash = f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        if actual_hash != expected_hash:
            hashes_match = False
            break
    return {
        "candidate_visible": hashes_match,
        "new_commit": commit if hashes_match else None,
        "hashes_match": hashes_match,
    }


@method("prompts.abort_candidate")
def prompts_abort_candidate(params: dict[str, Any]) -> dict[str, Any]:
    """Delete an isolated private candidate ref during transaction recovery."""
    branch = _require_candidate_branch(params)
    git = _private_git()
    if git.branch_exists(branch):
        git.delete_branch(branch, force=True)
    return {"ok": True}


@method("prompts.init_private_repo")
def prompts_init_private_repo(params: dict[str, Any]) -> dict[str, Any]:
    path = _require_str(params, "path")
    seed_baseline = bool(params.get("seed_baseline", False))
    try:
        from mosaic.autoresearch.prompt_repo import (
            PromptRepoError,
            init_private_prompt_repo,
        )

        result = init_private_prompt_repo(
            path,
            project_root=_repo_root(),
            seed_baseline=seed_baseline,
        )
    except PromptRepoError as exc:
        # User-supplied path is invalid (inside project repo, non-git, etc.).
        raise RpcError(INVALID_PARAMS, str(exc)) from exc
    except Exception as exc:
        raise RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}") from exc
    return dict(result)


@method("prompts.audit_versions")
def prompts_audit_versions(params: dict[str, Any]) -> dict[str, Any]:
    """List prompt version metadata only; never returns prompt body."""
    cohort = _optional_str(params, "cohort")
    status = _optional_str(params, "status")
    agent = _optional_str(params, "agent")
    limit = params.get("limit", 20)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise RpcError(INVALID_PARAMS, "'limit' must be a positive integer")
    rows = _store().list_prompt_versions(cohort=cohort, status=status, agent=agent)[:limit]
    safe_rows = []
    for row in rows:
        safe_rows.append({
            "id": row["id"],
            "cohort": row["cohort"],
            "agent": row["agent"],
            "status": row["status"],
            "branch_name": row["branch_name"],
            "base_commit_hash": row["base_commit_hash"],
            "modification_commit_hash": row.get("modification_commit_hash"),
            "prompt_repo_id": row.get("prompt_repo_id"),
            "prompt_base_commit_hash": row.get("prompt_base_commit_hash"),
            "prompt_sha256": row.get("prompt_sha256"),
            "code_commit_hash": row.get("code_commit_hash"),
            "mutation_id": row.get("mutation_id"),
            "mutation_lifecycle": row.get("mutation_lifecycle"),
            "delta_sharpe": row.get("delta_sharpe"),
            "created_at": row.get("created_at"),
            "decided_at": row.get("decided_at"),
            "modification_summary": row.get("modification_summary"),
        })
    return {"versions": safe_rows}


@method("prompts.preflight")
def prompts_preflight(params: dict[str, Any]) -> dict[str, Any]:
    """Resolve formal benchmark/replay prompt provenance without prompt bodies."""
    cohort = _optional_str(params, "cohort") or _DEFAULT_COHORT
    agents = _optional_str_list(
        params,
        "agents",
        allowed=_ALL_AGENTS,
        default=_ALL_AGENTS,
    )
    langs = _optional_str_list(
        params,
        "langs",
        allowed=_LANGS,
        default=_LANGS,
    )
    source = _formal_prompt_source()
    rows: list[dict[str, Any]] = []
    for agent in agents:
        layer = _LAYER_BY_AGENT[agent]
        for lang in langs:
            if not source.get("ready"):
                rows.append(
                    _blocked_prompt_preflight_row(
                        cohort=cohort,
                        agent=agent,
                        lang=lang,
                        reason=str(source["blocked_reason"]),
                    )
                )
                continue

            path = Path(source["prompts_root"]) / cohort / layer / f"{agent}.{lang}.md"
            rel = path.relative_to(Path(source["repo_root"]))
            if not path.exists():
                rows.append(
                    _blocked_prompt_preflight_row(
                        cohort=cohort,
                        agent=agent,
                        lang=lang,
                        reason="private_prompt_unavailable",
                        source=source,
                    )
                )
                continue
            text = path.read_text(encoding="utf-8")
            rows.append({
                "agent": agent,
                "layer": layer,
                "cohort": cohort,
                "lang": lang,
                "status": "ready",
                "prompt_repo_id": source["prompt_repo_id"],
                "prompt_repo_revision": source["prompt_repo_revision"],
                "prompt_file_path": rel.as_posix(),
                "prompt_sha256": _prompt_sha256({rel.as_posix(): text}),
                "resolved_source": source["resolved_source"],
                "fallback_used": False,
            })
    blocked = [row for row in rows if row["status"] != "ready"]
    return {
        "ready": not blocked,
        "cohort": cohort,
        "expected_prompt_repo_id": _CANONICAL_PROMPT_REPO_ID,
        "source_status": {
            "ready": bool(source.get("ready")),
            "blocked_reason": source.get("blocked_reason")
            if isinstance(source.get("blocked_reason"), str)
            else "",
            "resolved_source": source.get("resolved_source")
            if isinstance(source.get("resolved_source"), str)
            else "",
            "prompt_repo_id": source.get("prompt_repo_id")
            if isinstance(source.get("prompt_repo_id"), str)
            else "",
            "prompt_repo_revision": source.get("prompt_repo_revision")
            if isinstance(source.get("prompt_repo_revision"), str)
            else "",
            "prompt_repo_dirty_count": source.get("prompt_repo_dirty_count")
            if isinstance(source.get("prompt_repo_dirty_count"), int)
            else 0,
        },
        "row_count": len(rows),
        "blocked_count": len(blocked),
        "rows": rows,
    }


def _contract_input_rows(
    params: dict[str, Any],
    cohort: str,
    agents: tuple[str, ...],
    langs: tuple[str, ...],
) -> list[dict[str, Any]]:
    supplied = params.get("prompt_rows")
    if supplied is not None:
        if not isinstance(supplied, list) or not supplied:
            raise RpcError(INVALID_PARAMS, "'prompt_rows' must be a non-empty list")
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(supplied, 1):
            if not isinstance(row, dict):
                raise RpcError(INVALID_PARAMS, f"prompt_rows[{index}] must be an object")
            rows.append(dict(row))
        return rows

    if any(
        key in params
        for key in (
            "prompt_repo_id",
            "prompt_repo_revision",
            "prompt_file_path",
            "prompt_sha256",
        )
    ):
        agent = _require_str(params, "agent")
        lang = _require_lang(params)
        return [
            {
                "agent": agent,
                "layer": _LAYER_BY_AGENT.get(agent, ""),
                "cohort": cohort,
                "lang": lang,
                "prompt_repo_id": _safe_str(params.get("prompt_repo_id")),
                "prompt_repo_revision": _safe_str(params.get("prompt_repo_revision")),
                "prompt_file_path": _safe_str(params.get("prompt_file_path")),
                "prompt_sha256": _safe_str(params.get("prompt_sha256")),
                "benchmark_run_id": _safe_str(params.get("benchmark_run_id")),
            }
        ]

    return list(prompts_preflight({"cohort": cohort, "agents": list(agents), "langs": list(langs)})["rows"])


def _contract_categories(text: str) -> dict[str, bool]:
    lower = text.casefold()
    return {
        category: any(f"## {alias}" in lower or f"{alias}:" in lower for alias in aliases)
        for category, aliases in _PROMPT_CONTRACT_CATEGORIES.items()
    }


def _missing_token_groups(text: str, groups: dict[str, tuple[str, ...]]) -> list[str]:
    lower = text.casefold()
    return [
        name
        for name, tokens in groups.items()
        if not any(token.casefold() in lower for token in tokens)
    ]


def _check_prompt_contract_text(agent: str, text: str) -> tuple[list[str], dict[str, bool]]:
    lower = text.casefold()
    categories = _contract_categories(text)
    blockers = [
        f"required_section_missing:{category}"
        for category, present in categories.items()
        if not present
    ]

    for field in _AGENT_SCHEMA_FIELDS.get(agent, ()):
        if field.casefold() not in lower:
            blockers.append(f"schema_field_missing:{field}")

    if "get_rke_research_context" not in lower and "injected rke context" not in lower:
        blockers.append("required_tool_missing:get_rke_research_context")
    if not any(
        token in lower
        for token in ("missing tool", "tool unavailable", "fallback", "工具缺失", "工具不可用")
    ):
        blockers.append("missing_tool_fallback_missing")
    if not any(token in lower for token in ("confidence cap", "caps confidence", "置信度上限")):
        blockers.append("missing_tool_confidence_cap_missing")
    if "current data" not in lower and "current-data" not in lower and "当前数据" not in lower:
        blockers.append("current_data_policy_missing")
    if not (
        ("research prior" in lower or "研究先验" in lower)
        and (
            "not current data" in lower
            or "cannot replace current" in lower
            or "不是当前数据" in lower
            or "不能替代当前数据" in lower
        )
        and (
            "cannot directly create trades" in lower
            or "no trade without current data confirmation" in lower
            or "不能直接生成交易" in lower
            or "没有当前数据确认就不交易" in lower
        )
    ):
        blockers.append("rke_current_data_separation_missing")
    if any(
        token in lower
        for token in (
            "rke prior is current data",
            "rke context is current data",
            "rke prior can directly create trades",
        )
    ):
        blockers.append("rke_prior_treated_as_current_data")

    for name in _missing_token_groups(text, _AUDIT_FOOTPRINT_TOKENS):
        blockers.append(f"audit_footprint_token_missing:{name}")
    for name in _missing_token_groups(text, _PRIVACY_TOKENS):
        blockers.append(f"privacy_token_missing:{name}")
    if not (("mutable" in lower or "可变" in lower) and ("immutable" in lower or "不可变" in lower)):
        blockers.append("autoresearch_mutable_immutable_boundary_missing")
    for name in _missing_token_groups(text, _IMMUTABLE_GUARDRAIL_TOKENS):
        blockers.append(f"immutable_guardrail_missing:{name}")

    return blockers, categories


def _read_contract_prompt(
    source: dict[str, Any],
    rel_text: str,
) -> tuple[str | None, str | None]:
    rel_path = Path(rel_text)
    if not rel_text or rel_path.is_absolute() or ".." in rel_path.parts:
        return None, "prompt_file_path_invalid"
    repo_root = Path(source["repo_root"])
    path = (repo_root / rel_path).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError:
        return None, "prompt_file_path_invalid"
    if not path.exists():
        return None, "private_prompt_unavailable"
    return path.read_text(encoding="utf-8"), None


@method("prompts.contract_check")
def prompts_contract_check(params: dict[str, Any]) -> dict[str, Any]:
    """Validate private prompt contracts without returning prompt bodies."""
    cohort = _optional_str(params, "cohort") or _DEFAULT_COHORT
    agents = _optional_str_list(
        params,
        "agents",
        allowed=_ALL_AGENTS,
        default=_ALL_AGENTS,
    )
    langs = _optional_str_list(params, "langs", allowed=_LANGS, default=_LANGS)
    benchmark_run_id = _safe_str(params.get("benchmark_run_id"))
    rows = _contract_input_rows(params, cohort, agents, langs)
    source = _formal_prompt_source()
    research_knobs_enabled = _research_knobs_enabled_agents()

    checked_rows: list[dict[str, Any]] = []
    categories_by_agent_lang: dict[tuple[str, str], dict[str, bool]] = {}
    knobs_by_agent_lang: dict[tuple[str, str], str] = {}
    for input_row in rows:
        agent = _safe_str(input_row.get("agent"))
        lang = _safe_str(input_row.get("lang"))
        layer = _LAYER_BY_AGENT.get(agent, _safe_str(input_row.get("layer")))
        blockers: list[str] = []
        prompt_sha = _safe_str(input_row.get("prompt_sha256"))
        prompt_repo_id = _safe_str(input_row.get("prompt_repo_id"))
        prompt_repo_revision = _safe_str(input_row.get("prompt_repo_revision"))
        prompt_file_path = _safe_str(input_row.get("prompt_file_path"))
        row_run_id = _safe_str(input_row.get("benchmark_run_id"))
        categories = {category: False for category in _PROMPT_CONTRACT_CATEGORIES}
        research_knobs_required = _research_knobs_enabled(agent, research_knobs_enabled)
        research_knobs_check_passed = not research_knobs_required

        if agent not in _ALL_AGENTS:
            blockers.append("unknown_agent")
        if lang not in _LANGS:
            blockers.append("unsupported_lang")
        if benchmark_run_id and row_run_id and row_run_id != benchmark_run_id:
            blockers.append("benchmark_run_id_mismatch")
        if not source.get("ready"):
            blockers.append(_safe_str(source.get("blocked_reason")) or "prompt_source_unavailable")
        else:
            if not prompt_repo_id:
                blockers.append("prompt_repo_id_missing")
            elif prompt_repo_id != _safe_str(source.get("prompt_repo_id")):
                blockers.append("prompt_repo_id_mismatch")
            if not prompt_repo_revision:
                blockers.append("prompt_repo_revision_missing")
            elif prompt_repo_revision != _safe_str(source.get("prompt_repo_revision")):
                blockers.append("prompt_repo_revision_mismatch")
            text, read_error = _read_contract_prompt(source, prompt_file_path)
            if read_error:
                blockers.append(read_error)
            elif text is not None:
                computed_sha = _prompt_sha256({prompt_file_path: text})
                if not prompt_sha:
                    blockers.append("prompt_sha256_missing")
                    prompt_sha = computed_sha
                elif prompt_sha != computed_sha:
                    blockers.append("prompt_sha256_mismatch")
                text_blockers, categories = _check_prompt_contract_text(agent, text)
                blockers.extend(text_blockers)
                if research_knobs_required:
                    knobs_fence, knobs_failures = _canonical_research_knobs_fence(text)
                    if knobs_failures:
                        blockers.extend(knobs_failures)
                    else:
                        research_knobs_check_passed = True
                        if knobs_fence is not None:
                            knobs_by_agent_lang[(agent, lang)] = knobs_fence

        categories_by_agent_lang[(agent, lang)] = categories
        checked_rows.append(
            {
                "agent": agent,
                "layer": layer,
                "lang": lang,
                "prompt_repo_id": prompt_repo_id,
                "prompt_repo_revision": prompt_repo_revision,
                "prompt_file_path": prompt_file_path,
                "prompt_sha256": prompt_sha,
                "prompt_contract_check_ref": _prompt_contract_check_ref(prompt_sha)
                if prompt_sha
                else "",
                "benchmark_run_id": benchmark_run_id or row_run_id,
                "ready": not blockers,
                "blockers": sorted(set(blockers)),
                "contract_categories": categories,
                "research_knobs_required": research_knobs_required,
                "research_knobs_check_passed": research_knobs_check_passed,
            }
        )

    for agent in {row["agent"] for row in checked_rows}:
        zh = categories_by_agent_lang.get((agent, "zh"))
        en = categories_by_agent_lang.get((agent, "en"))
        if zh is None or en is None or zh == en:
            continue
        for row in checked_rows:
            if row["agent"] == agent and row["lang"] in {"zh", "en"}:
                row["ready"] = False
                row["blockers"] = sorted(set(row["blockers"]) | {"bilingual_contract_category_drift"})
    for agent in {row["agent"] for row in checked_rows if row.get("research_knobs_required")}:
        zh = knobs_by_agent_lang.get((agent, "zh"))
        en = knobs_by_agent_lang.get((agent, "en"))
        if zh is None or en is None or zh == en:
            continue
        for row in checked_rows:
            if row["agent"] == agent and row["lang"] in {"zh", "en"}:
                row["ready"] = False
                row["research_knobs_check_passed"] = False
                row["blockers"] = sorted(set(row["blockers"]) | {"research_knobs_bilingual_drift"})

    blocker_counts: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    ready_counts = {"ready": 0, "blocked": 0}
    for row in checked_rows:
        layer_counts[row["layer"]] = layer_counts.get(row["layer"], 0) + 1
        lang_counts[row["lang"]] = lang_counts.get(row["lang"], 0) + 1
        ready_counts["ready" if row["ready"] else "blocked"] += 1
        for blocker in row["blockers"]:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    return {
        "schema_version": "prompt_contract_check_v1",
        "contract_version": _PROMPT_CONTRACT_VERSION,
        "benchmark_run_id": benchmark_run_id,
        "cohort": cohort,
        "ready": bool(checked_rows) and all(row["ready"] for row in checked_rows),
        "row_count": len(checked_rows),
        "ready_count": ready_counts["ready"],
        "blocked_count": ready_counts["blocked"],
        "blocked_reasons": sorted(blocker_counts),
        "counts_by_layer": layer_counts,
        "counts_by_language": lang_counts,
        "counts_by_ready_status": ready_counts,
        "counts_by_blocker_code": blocker_counts,
        "rows": checked_rows,
    }


@method("prompts.formal_release_checks")
def prompts_formal_release_checks(params: dict[str, Any]) -> dict[str, Any]:
    """Emit no-body formal prompt release checks from private prompt pins."""
    cohort = _optional_str(params, "cohort") or _DEFAULT_COHORT
    agents = _optional_str_list(
        params,
        "agents",
        allowed=_ALL_AGENTS,
        default=_ALL_AGENTS,
    )
    langs = _optional_str_list(params, "langs", allowed=_LANGS, default=_LANGS)
    benchmark_run_id = _safe_str(params.get("benchmark_run_id"))
    contract = prompts_contract_check(
        {
            "cohort": cohort,
            "agents": list(agents),
            "langs": list(langs),
            "benchmark_run_id": benchmark_run_id,
        }
    )
    preflight = prompts_preflight(
        {"cohort": cohort, "agents": list(agents), "langs": list(langs)}
    )
    source_ready = bool(preflight["source_status"].get("ready"))

    rows: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    for row in contract["rows"]:
        prompt_sha = _safe_str(row.get("prompt_sha256"))
        row_blockers = list(row.get("blockers") or [])
        if not source_ready:
            row_blockers.append(
                _safe_str(preflight["source_status"].get("blocked_reason"))
                or "prompt_source_unavailable"
            )
        if not row.get("ready"):
            row_blockers.append("prompt_contract_check_not_passed")
        for blocker in sorted(set(row_blockers)):
            _count(blocker_counts, blocker)
        release_passed = bool(prompt_sha) and not row_blockers
        rows.append(
            {
                "agent": _safe_str(row.get("agent")),
                "layer": _safe_str(row.get("layer")),
                "lang": _safe_str(row.get("lang")),
                "benchmark_run_id": benchmark_run_id,
                "prompt_version_id": _formal_prompt_version_id(prompt_sha),
                "prompt_repo_id": _safe_str(row.get("prompt_repo_id")),
                "prompt_repo_revision": _safe_str(row.get("prompt_repo_revision")),
                "prompt_file_path": _safe_str(row.get("prompt_file_path")),
                "prompt_sha256": prompt_sha,
                "audit_version_ref": f"prompt-audit:{_PROMPT_CONTRACT_VERSION}:{prompt_sha}"
                if prompt_sha
                else "",
                "verify_release_ref": f"prompt-release:{_PROMPT_CONTRACT_VERSION}:{prompt_sha}"
                if prompt_sha
                else "",
                "leak_drift_check_ref": (
                    f"prompt-leak-drift:{_PROMPT_CONTRACT_VERSION}:{prompt_sha}"
                    if prompt_sha
                    else ""
                ),
                "prompt_contract_check_ref": _safe_str(
                    row.get("prompt_contract_check_ref")
                ),
                "verify_release_passed": release_passed,
                "leak_drift_passed": release_passed,
                "prompt_contract_check_passed": row.get("ready") is True,
                "research_knobs_required": row.get("research_knobs_required") is True,
                "research_knobs_check_passed": row.get("research_knobs_check_passed") is True,
                "ready": release_passed,
                "blockers": sorted(set(row_blockers)),
            }
        )

    ready_count = sum(1 for row in rows if row["ready"])
    return {
        "schema_version": "prompt_formal_release_checks_v1",
        "benchmark_run_id": benchmark_run_id,
        "cohort": cohort,
        "ready": bool(rows) and ready_count == len(rows),
        "row_count": len(rows),
        "ready_count": ready_count,
        "blocked_count": len(rows) - ready_count,
        "blocked_reasons": sorted(blocker_counts),
        "prompt_source_status": preflight["source_status"],
        "rows": rows,
    }


@method("prompts.verify_release")
def prompts_verify_release(params: dict[str, Any]) -> dict[str, Any]:
    """Verify a kept prompt version can be pinned for release.

    Checks:
      - version exists and has private prompt metadata
      - committed prompt file digest matches prompt_sha256
      - registry-scan compatibility gate passes for current code/tools
    """
    from mosaic.autoresearch.evaluator import validate_prompt_tool_compatibility
    from mosaic.autoresearch.git_ops import GitError

    version_id = _require_int(params, "version_id")
    require_kept = bool(params.get("require_kept", True))
    store = _store()
    version = store.get_prompt_version(version_id)
    if version is None:
        raise RpcError(INVALID_PARAMS, f"prompt version {version_id} not found")

    mutation_metadata = store.get_version_mutation_metadata(version_id)
    promotion_decision = store.get_domain_promotion_decision(version_id)
    evaluation_result = store.get_domain_evaluation_result(version_id)
    domain_mutation = bool(
        mutation_metadata and mutation_metadata.get("mutation_kind") == "domain_knob"
    )
    promotion_ok = not domain_mutation
    if domain_mutation and mutation_metadata and promotion_decision and evaluation_result:
        promotion_ok = bool(
            version.get("mutation_lifecycle") == "kept"
            and promotion_decision.get("decision") == "keep"
            and version.get("promotion_decision_hash")
            == _canonical_json_hash(promotion_decision)
            and promotion_decision.get("mutation_id")
            == mutation_metadata.get("mutation_id")
            and promotion_decision.get("experiment_id")
            == mutation_metadata.get("experiment_id")
            and promotion_decision.get("transaction_manifest_hash")
            == mutation_metadata.get("transaction_manifest_hash")
            and promotion_decision.get("evaluation_result_hash")
            == evaluation_result.get("result_hash")
            and promotion_decision.get("prompt_commit_hash")
            == version.get("modification_commit_hash")
            and promotion_decision.get("prompt_sha256")
            == version.get("prompt_sha256")
            and promotion_decision.get("code_commit_hash")
            == version.get("code_commit_hash")
        )
    checks: dict[str, Any] = {
        "status_ok": (not require_kept) or version.get("status") == "keep",
        "metadata_ok": bool(
            version.get("modification_commit_hash")
            and version.get("prompt_repo_id")
            and version.get("prompt_sha256")
            and version.get("code_commit_hash")
        ),
        "sha_ok": False,
        "compatible": False,
        "promotion_ok": promotion_ok,
    }
    details: dict[str, Any] = {}
    try:
        git = _private_git() if version.get("prompt_repo_id") == "private" else _git()
    except RpcError as exc:
        # e.g. a private version when MOSAIC_PRIVATE_PROMPT_REPO is unset — report
        # not-ready with a reason rather than throwing, to match the structured checks.
        details["repo_error"] = str(exc)
        return {
            "ready": False,
            "checks": checks,
            "details": details,
            "pin": {
                "version_id": version["id"],
                "cohort": version["cohort"],
                "agent": version["agent"],
                "code_commit_hash": version.get("code_commit_hash"),
                "prompt_repo_id": version.get("prompt_repo_id"),
                "prompt_commit_hash": version.get("modification_commit_hash"),
                "prompt_sha256": version.get("prompt_sha256"),
                "mutation_id": (mutation_metadata or {}).get("mutation_id"),
                "experiment_id": (mutation_metadata or {}).get("experiment_id"),
                "keep_decision_hash": version.get("promotion_decision_hash"),
                "evaluation_result_hash": (evaluation_result or {}).get("result_hash"),
                "transaction_manifest_hash": (mutation_metadata or {}).get(
                    "transaction_manifest_hash"
                ),
            },
        }

    files: dict[str, str] = {}
    if version.get("modification_commit_hash"):
        for lang in _LANGS:
            rel = _rel_path(version["agent"], version["cohort"], lang)
            try:
                files[rel] = git.show_file(version["modification_commit_hash"], rel)
            except GitError:
                details.setdefault("missing_files", []).append(rel)
    if files:
        computed_sha = _prompt_sha256(files)
        checks["sha_ok"] = computed_sha == version.get("prompt_sha256")
        details["computed_prompt_sha256"] = computed_sha

    try:
        compatibility = validate_prompt_tool_compatibility(version, git, baseline_git=_git())
        checks["compatible"] = bool(compatibility["compatible"])
        details["compatibility"] = compatibility
    except Exception as exc:
        details["compatibility_error"] = f"{type(exc).__name__}: {exc}"

    ready = all(bool(v) for v in checks.values())
    return {
        "ready": ready,
        "checks": checks,
        "details": details,
        "pin": {
            "version_id": version["id"],
            "cohort": version["cohort"],
            "agent": version["agent"],
            "code_commit_hash": version.get("code_commit_hash"),
            "prompt_repo_id": version.get("prompt_repo_id"),
            "prompt_commit_hash": version.get("modification_commit_hash"),
            "prompt_sha256": version.get("prompt_sha256"),
            "mutation_id": (mutation_metadata or {}).get("mutation_id"),
            "experiment_id": (mutation_metadata or {}).get("experiment_id"),
            "keep_decision_hash": version.get("promotion_decision_hash"),
            "evaluation_result_hash": (evaluation_result or {}).get("result_hash"),
            "transaction_manifest_hash": (mutation_metadata or {}).get(
                "transaction_manifest_hash"
            ),
        },
    }
