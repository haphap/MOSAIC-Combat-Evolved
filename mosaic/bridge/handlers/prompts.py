"""Read-only Prompt inspection and release-preflight JSON-RPC handlers.

Candidate rendering and commits belong to the private Prompt repository. This
public surface reads Prompt content at explicit Git refs, initializes a private
repository when requested, and validates release/audit contracts; it has no
general Prompt writer or Candidate-state authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from mosaic.scorecard.canonical_json import canonical_hash

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method


def _load_agents_by_layer() -> dict[str, tuple[str, ...]]:
    manifest_path = (
        Path(__file__).resolve().parents[3]
        / "registry"
        / "prompt_checks"
        / "runtime_agent_manifest_v5.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("runtime agent manifest is invalid")
    if payload.get("schema_version") != "runtime_agent_manifest_v5":
        raise RuntimeError("runtime agent manifest schema version is invalid")
    layers = ("macro", "sector", "superinvestor", "decision")
    grouped: dict[str, list[str]] = {layer: [] for layer in layers}
    seen: set[str] = set()
    for row in payload.get("agents", []):
        if not isinstance(row, dict):
            raise RuntimeError("runtime agent manifest row is invalid")
        layer = row.get("layer")
        agent = row.get("agent")
        if layer not in grouped or not isinstance(agent, str) or not agent:
            raise RuntimeError("runtime agent manifest binding is invalid")
        if agent in seen:
            raise RuntimeError(f"runtime agent manifest duplicates agent: {agent}")
        seen.add(agent)
        grouped[layer].append(agent)
    declared_count = payload.get("runtime_agent_count")
    if declared_count != len(seen) or any(not grouped[layer] for layer in layers):
        raise RuntimeError("runtime agent manifest roster is incomplete")
    return {layer: tuple(grouped[layer]) for layer in layers}


_AGENTS_BY_LAYER = _load_agents_by_layer()
_LAYER_BY_AGENT: dict[str, str] = {
    agent: layer for layer, agents in _AGENTS_BY_LAYER.items() for agent in agents
}
_ALL_AGENTS = tuple(agent for agents in _AGENTS_BY_LAYER.values() for agent in agents)
_DEFAULT_COHORT = "cohort_default"
_LANGS = ("zh", "en")
_WRITE_TARGETS = ("private_git", "project_git", "working_tree")
_CANONICAL_PROMPT_REPO_ID = "https://github.com/haphap/MOSAIC-Prompts"
_PROMPT_CONTRACT_VERSION = "runtime_prompt_contract_v2"
_LEGACY_RKE_PROMPT_CONTRACT_VERSION = "rke_prompt_contract_v1"
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_CANDIDATE_BRANCH_RE = re.compile(r"^(?:cohort|autoresearch)/[A-Za-z0-9_./-]+$")
_SAFE_CANDIDATE_FILE_RE = re.compile(
    r"^prompts/mosaic/[A-Za-z0-9_-]+/(?:macro|sector|superinvestor|decision)/"
    r"[A-Za-z0-9_-]+\.(?:zh|en)\.md$"
)
_LEGACY_RKE_PROMPT_CONTRACT_CATEGORIES = {
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
_LEGACY_STANDARD_SECTOR_FIELDS = (
    "longs",
    "shorts",
    "sector_score",
    "key_drivers",
    "confidence",
)
_LEGACY_SUPERINVESTOR_FIELDS = (
    "picks",
    "philosophy_note",
    "key_drivers",
    "confidence",
)
_LEGACY_RKE_AGENT_SCHEMA_FIELDS: dict[str, tuple[str, ...]] = {
    agent: _LEGACY_STANDARD_SECTOR_FIELDS
    for agent in _AGENTS_BY_LAYER["sector"]
    if agent != "relationship_mapper"
}
_LEGACY_RKE_AGENT_SCHEMA_FIELDS.update(
    {
        "relationship_mapper": (
            "supply_chains",
            "ownership_clusters",
            "contagion_risks",
            "key_drivers",
            "confidence",
        ),
        **{
            agent: _LEGACY_SUPERINVESTOR_FIELDS
            for agent in _AGENTS_BY_LAYER["superinvestor"]
        },
        "cro": (
            "rejected_picks",
            "correlated_risks",
            "black_swan_scenarios",
            "confidence",
        ),
        "alpha_discovery": ("novel_picks", "confidence"),
        "autonomous_execution": ("trades", "confidence"),
        "cio": ("portfolio_actions", "confidence"),
    }
)


def _load_runtime_prompt_contracts() -> dict[str, dict[str, tuple[str, ...]]]:
    path = (
        Path(__file__).resolve().parents[3]
        / "registry"
        / "prompt_checks"
        / "runtime_agent_manifest_v5.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("agents") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "runtime_agent_manifest_v5"
        or not isinstance(rows, list)
    ):
        raise RuntimeError("runtime prompt contract manifest is invalid")
    contracts: dict[str, dict[str, tuple[str, ...]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("runtime prompt contract row is invalid")
        agent = row.get("agent")
        tools = row.get("required_tools")
        fields = row.get("output_schema_fields")
        if (
            not isinstance(agent, str)
            or agent in contracts
            or not isinstance(tools, list)
            or not isinstance(fields, list)
            or any(not isinstance(item, str) or not item for item in (*tools, *fields))
        ):
            raise RuntimeError("runtime prompt contract binding is invalid")
        contracts[agent] = {
            "required_tools": tuple(tools),
            "output_schema_fields": tuple(fields),
        }
    if set(contracts) != set(_ALL_AGENTS):
        raise RuntimeError("runtime prompt contract roster mismatch")
    return contracts


_RUNTIME_PROMPT_CONTRACTS = _load_runtime_prompt_contracts()
_AGENT_SCHEMA_FIELDS: dict[str, tuple[str, ...]] = {
    agent: contract["output_schema_fields"]
    for agent, contract in _RUNTIME_PROMPT_CONTRACTS.items()
}
_KNOWN_RUNTIME_TOOLS = frozenset(
    tool
    for contract in _RUNTIME_PROMPT_CONTRACTS.values()
    for tool in contract["required_tools"]
)
_MODEL_PROMPT_FORBIDDEN_PATTERNS = {
    "production_rke_input_forbidden": re.compile(
        r"\b(?:get_rke_research_context|rke[ _-]?(?:prior|context))\b", re.IGNORECASE
    ),
    "private_knot_content_forbidden": re.compile(
        r"\b(?:knot|darwinian|research[ _-]?knob)\b",
        re.IGNORECASE,
    ),
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


def _raw_prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _expected_base_hashes(value: Any, files: dict[str, str]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) != set(files):
        raise RpcError(
            INVALID_PARAMS,
            "'expected_base_hashes' must cover exactly the candidate files",
        )
    if not all(
        isinstance(path, str)
        and isinstance(expected_hash, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_hash)
        for path, expected_hash in value.items()
    ):
        raise RpcError(INVALID_PARAMS, "'expected_base_hashes' contains an invalid hash")
    return value


def _assert_expected_base_hashes(
    git: Any,
    base_commit: str,
    expected_hashes: dict[str, str],
) -> None:
    mismatched: list[str] = []
    for path, expected_hash in expected_hashes.items():
        try:
            content = git.show_file(base_commit, path)
        except Exception:
            mismatched.append(path)
            continue
        actual_hash = f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        if actual_hash != expected_hash:
            mismatched.append(path)
    if mismatched:
        raise RpcError(
            INVALID_PARAMS,
            f"candidate base files do not match expected hashes: {', '.join(sorted(mismatched))}",
        )


def _require_candidate_branch(params: dict[str, Any]) -> str:
    branch = _require_str(params, "branch")
    if (
        not _SAFE_CANDIDATE_BRANCH_RE.fullmatch(branch)
        or ".." in branch
        or branch.endswith("/")
    ):
        raise RpcError(INVALID_PARAMS, "candidate branch is outside the autoresearch namespace")
    return branch


def _prompt_contract_check_ref(
    prompt_sha256: str, contract_version: str = _PROMPT_CONTRACT_VERSION
) -> str:
    return f"prompt-contract:{contract_version}:{prompt_sha256}"


def _formal_prompt_version_id(prompt_sha256: str) -> int:
    if not prompt_sha256:
        return 0
    return int(prompt_sha256[:12], 16) % 2_000_000_000 + 1


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _safe_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical_json_hash(value: Any) -> str:
    return canonical_hash(value)


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


def _git_show_utf8(cwd: Path, revision: str, relative_path: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"{revision}:{relative_path}"],
        cwd=str(cwd),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise FileNotFoundError(relative_path)
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("private prompt is not valid UTF-8") from exc


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
    requested_revision = _optional_str(params, "prompt_repo_revision")
    allow_non_head_revision = params.get("allow_non_head_revision", False)
    if not isinstance(allow_non_head_revision, bool):
        raise RpcError(INVALID_PARAMS, "'allow_non_head_revision' must be boolean")
    if source.get("ready") and requested_revision:
        if re.fullmatch(r"[0-9a-f]{40}", requested_revision) is None:
            raise RpcError(INVALID_PARAMS, "'prompt_repo_revision' must be a full commit hash")
        try:
            resolved_revision = _git_run(
                Path(source["repo_root"]),
                "rev-parse",
                "--verify",
                f"{requested_revision}^{{commit}}",
            )
        except Exception as exc:
            raise RpcError(INVALID_PARAMS, "prompt repository revision is unavailable") from exc
        if resolved_revision != requested_revision:
            raise RpcError(INVALID_PARAMS, "prompt repository revision must be canonical")
        if (
            requested_revision != source["prompt_repo_revision"]
            and not allow_non_head_revision
        ):
            raise RpcError(
                INVALID_PARAMS,
                "non-HEAD prompt revision requires a verified release context",
            )
        source = {**source, "prompt_repo_revision": requested_revision}
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
            try:
                text = _git_show_utf8(
                    Path(source["repo_root"]),
                    source["prompt_repo_revision"],
                    rel.as_posix(),
                )
            except FileNotFoundError:
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
            rows.append({
                "agent": agent,
                "layer": layer,
                "cohort": cohort,
                "lang": lang,
                "status": "ready",
                "prompt_repo_id": source["prompt_repo_id"],
                "prompt_repo_revision": source["prompt_repo_revision"],
                "prompt_file_path": rel.as_posix(),
                "prompt_sha256": _raw_prompt_sha256(text),
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


def _legacy_rke_contract_categories(text: str) -> dict[str, bool]:
    lower = text.casefold()
    return {
        category: any(f"## {alias}" in lower or f"{alias}:" in lower for alias in aliases)
        for category, aliases in _LEGACY_RKE_PROMPT_CONTRACT_CATEGORIES.items()
    }


def _missing_token_groups(text: str, groups: dict[str, tuple[str, ...]]) -> list[str]:
    lower = text.casefold()
    return [
        name
        for name, tokens in groups.items()
        if not any(token.casefold() in lower for token in tokens)
    ]


def _check_legacy_rke_prompt_contract_text(
    agent: str, text: str
) -> tuple[list[str], dict[str, bool]]:
    lower = text.casefold()
    categories = _legacy_rke_contract_categories(text)
    blockers = [
        f"required_section_missing:{category}"
        for category, present in categories.items()
        if not present
    ]

    for field in _LEGACY_RKE_AGENT_SCHEMA_FIELDS.get(agent, ()):
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


def _runtime_contract_categories(agent: str, text: str) -> dict[str, bool]:
    lower = text.casefold()
    contract = _RUNTIME_PROMPT_CONTRACTS[agent]
    return {
        "role_scope": f"# {agent.casefold()}" in lower,
        "cohort_lens": (
            "<!-- cohort-behavior:start -->" in lower
            and "<!-- cohort-behavior:end -->" in lower
        ),
        "runtime_tool_contract": all(
            tool.casefold() in lower for tool in contract["required_tools"]
        ),
        "runtime_schema_contract": (
            "<!-- runtime-evidence-contract:start -->" in lower
            and "<!-- runtime-evidence-contract:end -->" in lower
            and all(
                field.casefold() in lower
                for field in contract["output_schema_fields"]
            )
        ),
        "evidence_closure": all(
            token in lower
            for token in ("claims", "claim_refs", "evidence_id", "research_rule_refs")
        ),
        "pit_or_frozen_scope": any(
            token in lower for token in ("as-of", "pit", "frozen", "截至", "冻结")
        ),
        "insufficient_evidence_disposition": any(
            token in lower
            for token in ("reject", "abstain", "insufficient", "拒绝", "弃权", "不足")
        ),
    }


def _check_runtime_prompt_contract_text(
    agent: str, text: str
) -> tuple[list[str], dict[str, bool]]:
    lower = text.casefold()
    contract = _RUNTIME_PROMPT_CONTRACTS[agent]
    categories = _runtime_contract_categories(agent, text)
    blockers = [
        f"required_contract_missing:{category}"
        for category, present in categories.items()
        if not present
    ]
    for tool in contract["required_tools"]:
        if tool.casefold() not in lower:
            blockers.append(f"required_tool_missing:{tool}")
    mentioned_tools = set(re.findall(r"\bget_[a-z0-9_]+\b", lower))
    unexpected_tools = sorted(mentioned_tools - set(contract["required_tools"]))
    blockers.extend(f"unapproved_tool_mentioned:{tool}" for tool in unexpected_tools)
    for field in contract["output_schema_fields"]:
        if field.casefold() not in lower:
            blockers.append(f"schema_field_missing:{field}")
    if "```json" in lower or re.search(r"\{\s*[\"'][a-zA-Z0-9_]", text):
        blockers.append("handwritten_json_schema_forbidden")
    for blocker, pattern in _MODEL_PROMPT_FORBIDDEN_PATTERNS.items():
        if pattern.search(text):
            blockers.append(blocker)
    return sorted(set(blockers)), categories


def _contract_mode(params: dict[str, Any]) -> tuple[str, str]:
    mode = _optional_str(params, "contract_mode") or "production_v2"
    if mode == "production_v2":
        return mode, _PROMPT_CONTRACT_VERSION
    if mode == "rke_shadow_fixture_v1":
        return mode, _LEGACY_RKE_PROMPT_CONTRACT_VERSION
    raise RpcError(INVALID_PARAMS, "contract_mode must be production_v2 or rke_shadow_fixture_v1")


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
    contract_mode, contract_version = _contract_mode(params)
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
    checked_rows: list[dict[str, Any]] = []
    categories_by_agent_lang: dict[tuple[str, str], dict[str, bool]] = {}
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
        categories = (
            {category: False for category in _LEGACY_RKE_PROMPT_CONTRACT_CATEGORIES}
            if contract_mode == "rke_shadow_fixture_v1"
            else {category: False for category in _runtime_contract_categories(agent, "")}
            if agent in _RUNTIME_PROMPT_CONTRACTS
            else {}
        )

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
                computed_sha = _raw_prompt_sha256(text)
                if not prompt_sha:
                    blockers.append("prompt_sha256_missing")
                    prompt_sha = computed_sha
                elif prompt_sha != computed_sha:
                    blockers.append("prompt_sha256_mismatch")
                if contract_mode == "rke_shadow_fixture_v1":
                    text_blockers, categories = _check_legacy_rke_prompt_contract_text(
                        agent, text
                    )
                else:
                    text_blockers, categories = _check_runtime_prompt_contract_text(
                        agent, text
                    )
                blockers.extend(text_blockers)

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
                "prompt_contract_check_ref": _prompt_contract_check_ref(
                    prompt_sha, contract_version
                )
                if prompt_sha
                else "",
                "benchmark_run_id": benchmark_run_id or row_run_id,
                "ready": not blockers,
                "blockers": sorted(set(blockers)),
                "contract_categories": categories,
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
        "contract_mode": contract_mode,
        "contract_version": contract_version,
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
    contract_mode, contract_version = _contract_mode(params)
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
            "contract_mode": contract_mode,
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
                "audit_version_ref": f"prompt-audit:{contract_version}:{prompt_sha}"
                if prompt_sha
                else "",
                "verify_release_ref": f"prompt-release:{contract_version}:{prompt_sha}"
                if prompt_sha
                else "",
                "leak_drift_check_ref": (
                    f"prompt-leak-drift:{contract_version}:{prompt_sha}"
                    if prompt_sha
                    else ""
                ),
                "prompt_contract_check_ref": _safe_str(
                    row.get("prompt_contract_check_ref")
                ),
                "verify_release_passed": release_passed,
                "leak_drift_passed": release_passed,
                "prompt_contract_check_passed": row.get("ready") is True,
                "ready": release_passed,
                "blockers": sorted(set(row_blockers)),
            }
        )

    ready_count = sum(1 for row in rows if row["ready"])
    return {
        "schema_version": "prompt_formal_release_checks_v1",
        "contract_mode": contract_mode,
        "contract_version": contract_version,
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
