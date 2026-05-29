"""Tests for mosaic.autoresearch.git_ops (Plan §11.5 4A).

Builds a throwaway git repo in tmp_path and exercises the branch/commit/
merge/worktree/show primitives. Verifies the key invariant: a mutation
commit on a feature branch never dirties the primary working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mosaic.autoresearch.git_ops import GitError, GitOps

PROMPT_REL = "prompts/mosaic/cohort_crisis_2008/macro/volatility.zh.md"
BRANCH = "cohort/crisis_2008/auto/volatility/2008-09-15"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal git repo on branch ``main`` with one committed file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    seed = repo / "prompts" / "mosaic" / "cohort_default" / "macro"
    seed.mkdir(parents=True)
    (seed / "volatility.zh.md").write_text("base volatility prompt\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    # data/ exists + is ignored (worktrees live there).
    (repo / "data").mkdir()
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "gitignore")
    return repo


@pytest.fixture
def git(repo: Path) -> GitOps:
    return GitOps(repo)


# ---------------------------------------------------------------------------
# Construction / inspection
# ---------------------------------------------------------------------------


def test_rejects_non_repo(tmp_path: Path):
    with pytest.raises(GitError, match="not a git repository"):
        GitOps(tmp_path / "nope")


def test_current_branch_and_commit(git: GitOps):
    assert git.current_branch() == "main"
    assert len(git.current_commit()) == 40


def test_is_clean_and_assert_clean(git: GitOps, repo: Path):
    assert git.is_clean()
    git.assert_clean()  # no raise
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    assert not git.is_clean()
    with pytest.raises(GitError, match="uncommitted changes"):
        git.assert_clean()


def test_branch_exists(git: GitOps):
    assert git.branch_exists("main")
    assert not git.branch_exists("does-not-exist")


# ---------------------------------------------------------------------------
# write_and_commit
# ---------------------------------------------------------------------------


def test_write_and_commit_creates_branch_and_commit(git: GitOps, repo: Path):
    head_before = git.current_commit()
    commit = git.write_and_commit(
        {PROMPT_REL: "improved volatility prompt\n"},
        message="auto: tighten volatility rule",
        branch=BRANCH,
        base_ref="main",
    )
    assert len(commit) == 40
    assert git.branch_exists(BRANCH)
    # main HEAD unchanged
    assert git.current_commit() == head_before
    # file content readable at the branch ref
    assert git.show_file(BRANCH, PROMPT_REL) == "improved volatility prompt\n"


def test_write_and_commit_does_not_dirty_primary_tree(git: GitOps, repo: Path):
    git.write_and_commit(
        {PROMPT_REL: "improved\n"}, message="m", branch=BRANCH
    )
    # The new prompt file must NOT appear in the primary working tree, and
    # the tree must still be clean.
    assert not (repo / PROMPT_REL).exists()
    assert git.is_clean()
    assert git.current_branch() == "main"


def test_write_and_commit_empty_files_raises(git: GitOps):
    with pytest.raises(GitError, match="at least one file"):
        git.write_and_commit({}, message="m", branch=BRANCH)


# ---------------------------------------------------------------------------
# show_file at refs
# ---------------------------------------------------------------------------


def test_show_file_at_main(git: GitOps):
    content = git.show_file("main", "prompts/mosaic/cohort_default/macro/volatility.zh.md")
    assert content == "base volatility prompt\n"


def test_show_file_missing_raises(git: GitOps):
    with pytest.raises(GitError):
        git.show_file("main", "prompts/does/not/exist.md")


# ---------------------------------------------------------------------------
# merge_to_main (keep) / delete_branch (revert)
# ---------------------------------------------------------------------------


def test_merge_to_main_keeps_change(git: GitOps, repo: Path):
    git.write_and_commit({PROMPT_REL: "kept content\n"}, message="m", branch=BRANCH)
    merged = git.merge_to_main(BRANCH)
    assert len(merged) == 40
    # After merge, main HEAD contains the prompt file in the working tree.
    assert (repo / PROMPT_REL).exists()
    assert (repo / PROMPT_REL).read_text(encoding="utf-8") == "kept content\n"
    assert git.current_branch() == "main"


def test_delete_branch_revert(git: GitOps):
    git.write_and_commit({PROMPT_REL: "rejected\n"}, message="m", branch=BRANCH)
    assert git.branch_exists(BRANCH)
    git.delete_branch(BRANCH, force=True)
    assert not git.branch_exists(BRANCH)
    # main untouched: the prompt file was never merged.
    with pytest.raises(GitError):
        git.show_file("main", PROMPT_REL)


# ---------------------------------------------------------------------------
# worktree lifecycle (4C evaluation uses these)
# ---------------------------------------------------------------------------


def test_add_and_remove_worktree(git: GitOps, repo: Path):
    commit = git.write_and_commit({PROMPT_REL: "wt content\n"}, message="m", branch=BRANCH)
    wt = git.add_worktree(commit)
    try:
        assert wt.exists()
        assert (wt / PROMPT_REL).read_text(encoding="utf-8") == "wt content\n"
    finally:
        git.remove_worktree(wt)
    assert not wt.exists()
