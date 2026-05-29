"""Thin, fail-loud wrapper over the system ``git`` CLI (Plan §11.5 4A).

Phase 4 autoresearch needs to:
  * fork a short-lived feature branch off ``main`` for each prompt mutation
    (``cohort/<cohort>/auto/<agent>/<YYYY-MM-DD>``);
  * commit a single prompt-file change on that branch *without disturbing the
    primary working tree* (we use a throwaway ``git worktree`` for the write);
  * read a file's content at an arbitrary ref (for ``prompts.read``);
  * merge a kept branch back into ``main`` (keep) or delete it (revert);
  * check out a ref into an isolated worktree for backtest evaluation (4C).

Design notes:
  * We shell out to ``git`` rather than depend on GitPython (one fewer dep;
    consistent with the rest of the sidecar). Every command runs with
    ``check=True``; stderr is captured into the raised :class:`GitError`.
  * Writes go through a temporary worktree so the operator's primary working
    tree (usually sitting on ``main``) is never touched by a mutation commit.
  * Commits set an explicit identity via ``-c user.*`` so they succeed even in
    a bare CI repo with no global git config.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence

# Identity stamped on autoresearch commits when none is otherwise configured.
_COMMIT_NAME = "mosaic-autoresearch"
_COMMIT_EMAIL = "autoresearch@mosaic.local"


class GitError(RuntimeError):
    """Raised when a git command exits non-zero."""


def _slug(ref: str) -> str:
    """Filesystem-safe slug for a branch/commit ref (worktree dir name)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-") or "wt"


class GitOps:
    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        if not (self.repo_root / ".git").exists():
            raise GitError(f"{self.repo_root} is not a git repository (no .git)")
        # Worktrees live under data/ (gitignored). Created lazily.
        self.worktrees_dir = self.repo_root / "data" / "worktrees"

    # ── low-level runner ──────────────────────────────────────────────────

    def _run(self, *args: str, cwd: Optional[Path] = None) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo_root),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout

    # ── inspection ──────────────────────────────────────────────────────

    def current_commit(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def rev_parse(self, ref: str) -> str:
        return self._run("rev-parse", ref).strip()

    def is_clean(self) -> bool:
        """True when the working tree + index have no uncommitted changes."""
        return self._run("status", "--porcelain").strip() == ""

    def assert_clean(self) -> None:
        if not self.is_clean():
            raise GitError(
                "refusing to proceed: the working tree has uncommitted changes. "
                "Commit or stash them before running autoresearch."
            )

    def branch_exists(self, name: str) -> bool:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0

    def show_file(self, ref: str, path: str) -> str:
        """Return the content of ``path`` as it exists at ``ref``.

        Backs ``prompts.read`` when a commit/branch ref is supplied.
        """
        return self._run("show", f"{ref}:{path}")

    # ── branch lifecycle ────────────────────────────────────────────────

    def create_branch(self, name: str, from_ref: str = "main") -> None:
        """Create branch ``name`` at ``from_ref`` without checking it out."""
        self._run("branch", name, from_ref)

    def delete_branch(self, name: str, force: bool = True) -> None:
        """Delete a local branch. ``force`` is required for un-merged
        feature branches (the revert path)."""
        self._run("branch", "-D" if force else "-d", name)

    def write_and_commit(
        self,
        files: Mapping[str, str],
        message: str,
        branch: str,
        base_ref: str = "main",
    ) -> str:
        """Write ``files`` (repo-relative path → content) and commit them on
        ``branch``, returning the new commit hash.

        The branch is created from ``base_ref`` if it doesn't already exist.
        The commit is built inside a temporary worktree, so the primary
        working tree is never modified.
        """
        if not files:
            raise GitError("write_and_commit requires at least one file")
        if not self.branch_exists(branch):
            self.create_branch(branch, base_ref)

        wt = self._add_worktree(branch)
        try:
            for rel_path, content in files.items():
                dest = wt / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                self._run("add", "--", rel_path, cwd=wt)
            self._run(
                "-c",
                f"user.name={_COMMIT_NAME}",
                "-c",
                f"user.email={_COMMIT_EMAIL}",
                "commit",
                "-m",
                message,
                cwd=wt,
            )
            return self._run("rev-parse", "HEAD", cwd=wt).strip()
        finally:
            self._remove_worktree(wt)

    def merge_to_main(
        self,
        branch: str,
        into: str = "main",
        ff_only: bool = False,
    ) -> str:
        """Merge ``branch`` into ``into`` and return the resulting commit.

        Runs in the primary working tree (checks out ``into`` first), so the
        caller must guarantee a clean tree — we assert it. Leaves the repo on
        ``into`` afterwards, which is the natural resting state for the
        autoresearch loop.
        """
        self.assert_clean()
        self._run("checkout", into)
        args = ["merge", "--no-edit"]
        if ff_only:
            args.append("--ff-only")
        args.append(branch)
        self._run(*args)
        return self.current_commit()

    # ── worktrees (used by write_and_commit + 4C evaluation) ─────────────

    def add_worktree(self, ref: str, path: Optional[Path] = None) -> Path:
        """Public worktree checkout of ``ref`` (a branch or commit) for
        isolated backtest evaluation (Plan §11.5 4C). Detached so it never
        collides with a branch checked out elsewhere."""
        return self._add_worktree(ref, path, detach=True)

    def remove_worktree(self, path: Path | str) -> None:
        self._remove_worktree(Path(path))

    def _add_worktree(
        self, ref: str, path: Optional[Path] = None, detach: bool = False
    ) -> Path:
        if path is None:
            self.worktrees_dir.mkdir(parents=True, exist_ok=True)
            path = self.worktrees_dir / _slug(ref)
        # Clean any stale worktree at this path first.
        if path.exists():
            self._remove_worktree(path)
        args: Sequence[str] = ["worktree", "add", "--force"]
        if detach:
            args = [*args, "--detach"]
        self._run(*args, str(path), ref)
        return path

    def _remove_worktree(self, path: Path) -> None:
        try:
            self._run("worktree", "remove", "--force", str(path))
        except GitError:
            # Fall back to prune if the dir was already gone / corrupt.
            self._run("worktree", "prune")
