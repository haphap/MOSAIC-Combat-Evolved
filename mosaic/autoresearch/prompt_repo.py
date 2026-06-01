"""Private prompt repository helpers.

The project repo may be public or broadly shared; optimized prompts must live
in a separate private git repo. This module centralizes the boundary checks so
callers do not accidentally route prompt writes back into the project tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict


class PromptRepoError(RuntimeError):
    """Raised when private prompt repo configuration is invalid."""


class InitResult(TypedDict):
    repo_root: str
    prompts_root: str
    seeded: bool
    commit_hash: str


_COMMIT_NAME = "mosaic-prompts"
_COMMIT_EMAIL = "prompts@mosaic.local"


def project_repo_root() -> Path:
    env = os.getenv("MOSAIC_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


def private_prompt_repo_from_env() -> Path | None:
    env = os.getenv("MOSAIC_PRIVATE_PROMPT_REPO")
    if not env or not env.strip():
        return None
    return Path(env).expanduser().resolve()


def validate_private_prompt_repo(path: Path | str, *, project_root: Path | str | None = None) -> Path:
    repo = Path(path).expanduser().resolve()
    project = Path(project_root).resolve() if project_root is not None else project_repo_root()

    if not repo.exists():
        raise PromptRepoError(f"private prompt repo does not exist: {_redact(repo)}")
    if not repo.is_dir():
        raise PromptRepoError(f"private prompt repo is not a directory: {_redact(repo)}")
    if repo == project:
        raise PromptRepoError("private prompt repo must not be the project repo")
    if _is_relative_to(repo, project):
        raise PromptRepoError("private prompt repo must not live inside the project repo")

    try:
        top = _git(repo, "rev-parse", "--show-toplevel").strip()
    except PromptRepoError as exc:
        raise PromptRepoError(f"private prompt repo is not a git repository: {_redact(repo)}") from exc
    if Path(top).resolve() != repo:
        raise PromptRepoError("private prompt repo path must be the git top-level")

    return repo


def init_private_prompt_repo(
    path: Path | str,
    *,
    project_root: Path | str | None = None,
    seed_baseline: bool = False,
) -> InitResult:
    repo = Path(path).expanduser().resolve()
    project = Path(project_root).resolve() if project_root is not None else project_repo_root()

    if repo == project or _is_relative_to(repo, project):
        raise PromptRepoError("private prompt repo must be outside the project repo")
    if repo.exists() and any(repo.iterdir()) and not (repo / ".git").exists():
        raise PromptRepoError(f"refusing to initialize non-empty non-git directory: {_redact(repo)}")

    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        # ``git init -b`` needs git >= 2.28; point the unborn HEAD at main via
        # symbolic-ref instead so this works on older git too.
        _git(repo, "init")
        _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")

    prompts_root = repo / "prompts" / "mosaic"
    prompts_root.mkdir(parents=True, exist_ok=True)

    if seed_baseline:
        src = project / "prompts" / "mosaic"
        if not src.exists():
            raise PromptRepoError(f"project baseline prompt root not found: {_redact(src)}")
        shutil.copytree(src, prompts_root, dirs_exist_ok=True)
    else:
        (prompts_root / ".gitkeep").write_text("", encoding="utf-8")

    _git(repo, "add", "prompts/mosaic")
    if _git(repo, "status", "--porcelain").strip():
        _git(
            repo,
            "-c",
            f"user.name={_COMMIT_NAME}",
            "-c",
            f"user.email={_COMMIT_EMAIL}",
            "commit",
            "-m",
            "init private prompt repo" if not seed_baseline else "seed private prompt repo from baseline",
        )

    commit = _git(repo, "rev-parse", "HEAD").strip()
    validate_private_prompt_repo(repo, project_root=project)
    return {
        "repo_root": str(repo),
        "prompts_root": str(prompts_root),
        "seeded": seed_baseline,
        "commit_hash": commit,
    }


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PromptRepoError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _redact(path: Path) -> str:
    home = Path.home().resolve()
    try:
        return "~/" + str(path.resolve().relative_to(home))
    except ValueError:
        return f"<path:{path.name}>"
