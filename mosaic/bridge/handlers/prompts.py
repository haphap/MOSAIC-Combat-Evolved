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
import os
from pathlib import Path
from typing import Any, Optional

from ..protocol import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from ..registry import method

# Mirror of cohorts.ts AGENTS_BY_LAYER (Plan §5). Keep in sync with the TS map.
_LAYER_BY_AGENT: dict[str, str] = {
    **dict.fromkeys(
        [
            "central_bank", "geopolitical", "china", "dollar", "yield_curve",
            "commodities", "volatility", "emerging_markets", "news_sentiment",
            "institutional_flow",
        ],
        "macro",
    ),
    **dict.fromkeys(
        ["semiconductor", "energy", "biotech", "consumer", "industrials",
         "financials", "relationship_mapper"],
        "sector",
    ),
    **dict.fromkeys(["druckenmiller", "aschenbrenner", "baker", "ackman"], "superinvestor"),
    **dict.fromkeys(["cro", "alpha_discovery", "autonomous_execution", "cio"], "decision"),
}
_DEFAULT_COHORT = "cohort_default"
_LANGS = ("zh", "en")
_WRITE_TARGETS = ("private_git", "project_git", "working_tree")


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
            "MOSAIC_PRIVATE_PROMPT_REPO is required for prompts.write(target=private_git)",
        )
    try:
        return GitOps(validate_private_prompt_repo(repo, project_root=_repo_root()))
    except PromptRepoError as exc:
        raise RpcError(INVALID_PARAMS, str(exc)) from exc


def _prompt_repo_id() -> str:
    return os.getenv("MOSAIC_PRIVATE_PROMPT_REPO_ID", "private")


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
    contents = params.get("contents")
    if not isinstance(contents, dict) or not contents:
        raise RpcError(INVALID_PARAMS, "'contents' must be a non-empty {lang: text} object")
    for lang, text in contents.items():
        if lang not in _LANGS or not isinstance(text, str):
            raise RpcError(INVALID_PARAMS, f"invalid contents entry {lang!r}")

    # Always write to the cohort-specific path (no fallback — a mutation
    # creates/overwrites the cohort's own file).
    files = {_rel_path(agent, cohort, lang): text for lang, text in contents.items()}
    prompt_sha256 = _prompt_sha256(files)
    branch: Optional[str] = params.get("branch") or None
    # Default keeps the existing autoresearch mutation path (a project-repo
    # feature branch); ``private_git`` is opt-in via an explicit ``target`` until
    # Phase 5 moves the evaluation worktree + read-at-ref to the private repo too.
    # (Flipping the default before then breaks the optimize→evaluate loop, since
    # ``autoresearch.prepare_worktree`` / ``prompts.read(ref)`` still use the
    # project repo. Phase 6's CI provenance guard is what blocks optimized
    # prompts from reaching project PRs in the interim.)
    target = params.get("target") or ("project_git" if branch else "working_tree")
    if target not in _WRITE_TARGETS:
        raise RpcError(INVALID_PARAMS, f"'target' must be one of {_WRITE_TARGETS}, got {target!r}")

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
            "delta_sharpe": row.get("delta_sharpe"),
            "created_at": row.get("created_at"),
            "decided_at": row.get("decided_at"),
            "modification_summary": row.get("modification_summary"),
        })
    return {"versions": safe_rows}


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
    version = _store().get_prompt_version(version_id)
    if version is None:
        raise RpcError(INVALID_PARAMS, f"prompt version {version_id} not found")

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
        },
    }
