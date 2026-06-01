from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mosaic.autoresearch.prompt_repo import (
    PromptRepoError,
    init_private_prompt_repo,
    validate_private_prompt_repo,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def project_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    prompt_root = repo / "prompts" / "mosaic" / "cohort_default" / "macro"
    prompt_root.mkdir(parents=True)
    (prompt_root / "volatility.zh.md").write_text("baseline zh\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed project")
    return repo


def test_init_private_prompt_repo_defaults_to_sparse(project_repo: Path, tmp_path: Path):
    private_repo = tmp_path / "private-prompts"

    result = init_private_prompt_repo(private_repo, project_root=project_repo)

    assert result["seeded"] is False
    assert len(result["commit_hash"]) == 40
    assert (private_repo / "prompts" / "mosaic" / ".gitkeep").exists()
    assert not (
        private_repo
        / "prompts"
        / "mosaic"
        / "cohort_default"
        / "macro"
        / "volatility.zh.md"
    ).exists()
    assert validate_private_prompt_repo(private_repo, project_root=project_repo) == private_repo


def test_init_private_prompt_repo_can_seed_baseline(project_repo: Path, tmp_path: Path):
    private_repo = tmp_path / "private-prompts"

    result = init_private_prompt_repo(private_repo, project_root=project_repo, seed_baseline=True)

    assert result["seeded"] is True
    assert (
        private_repo
        / "prompts"
        / "mosaic"
        / "cohort_default"
        / "macro"
        / "volatility.zh.md"
    ).read_text(encoding="utf-8") == "baseline zh\n"


def test_validate_rejects_project_repo(project_repo: Path):
    with pytest.raises(PromptRepoError, match="must not be the project repo"):
        validate_private_prompt_repo(project_repo, project_root=project_repo)


def test_validate_rejects_repo_inside_project(project_repo: Path):
    nested = project_repo / "private-prompts"
    nested.mkdir()
    _git(nested, "init", "-b", "main")

    with pytest.raises(PromptRepoError, match="must not live inside"):
        validate_private_prompt_repo(nested, project_root=project_repo)


def test_validate_rejects_non_git_directory(project_repo: Path, tmp_path: Path):
    private_repo = tmp_path / "not-git"
    private_repo.mkdir()

    with pytest.raises(PromptRepoError, match="not a git repository"):
        validate_private_prompt_repo(private_repo, project_root=project_repo)
