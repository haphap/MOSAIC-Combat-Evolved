"""Tests for prompts.* JSON-RPC handlers (Plan §11.5 4B).

Uses MOSAIC_REPO_ROOT to point the handler at a throwaway git repo, then
exercises read (working tree + ref), write (working tree + branch commit),
and the cohort_default fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.protocol import RpcError
from mosaic.bridge.registry import get_handler
from mosaic.autoresearch.prompt_repo import init_private_prompt_repo

DEFAULT_REL = "prompts/mosaic/cohort_default/macro/volatility.zh.md"
BRANCH = "cohort/crisis_2008/auto/volatility/2008-09-15"


def dispatch(method: str, params: dict):
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    seed = repo / "prompts" / "mosaic" / "cohort_default" / "macro"
    seed.mkdir(parents=True)
    (seed / "volatility.zh.md").write_text("base zh\n## 输出 schema\n", encoding="utf-8")
    (seed / "volatility.en.md").write_text("base en\n## Output schema\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    (repo / "data").mkdir()
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "gitignore")
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(repo))
    return repo


# ── prompts.read ──────────────────────────────────────────────────────────


class TestRead:
    def test_working_tree(self, repo: Path):
        r = dispatch("prompts.read", {"agent": "volatility", "cohort": "cohort_default", "lang": "zh"})
        assert r["content"].startswith("base zh")
        assert r["path"] == DEFAULT_REL

    def test_cohort_default_fallback(self, repo: Path):
        # crisis_2008 has no file → falls back to cohort_default.
        r = dispatch("prompts.read", {"agent": "volatility", "cohort": "crisis_2008", "lang": "en"})
        assert r["content"].startswith("base en")
        assert "cohort_default" in r["path"]

    def test_at_ref(self, repo: Path):
        r = dispatch("prompts.read", {"agent": "volatility", "cohort": "cohort_default", "lang": "zh", "ref": "main"})
        assert r["content"].startswith("base zh")

    def test_unknown_agent(self, repo: Path):
        with pytest.raises(RpcError, match="unknown agent"):
            dispatch("prompts.read", {"agent": "nope", "cohort": "cohort_default", "lang": "zh"})

    def test_bad_lang(self, repo: Path):
        with pytest.raises(RpcError, match="lang"):
            dispatch("prompts.read", {"agent": "volatility", "cohort": "cohort_default", "lang": "fr"})

    def test_missing_file(self, repo: Path):
        with pytest.raises(RpcError, match="not found"):
            dispatch("prompts.read", {"agent": "cio", "cohort": "cohort_default", "lang": "zh"})


# ── prompts.write ─────────────────────────────────────────────────────────


class TestWrite:
    def test_default_branch_routes_to_project_git(self, repo: Path):
        # Orchestrator path: branch + no target → project feature-branch commit;
        # no escape hatch / private repo required (keeps the autoresearch loop
        # working until Phase 5 moves eval/read to the private repo).
        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n## 输出 schema\n"},
            "branch": BRANCH,
        })
        assert r["target"] == "project_git"
        assert len(r["commit_hash"]) == 40
        assert not (repo / "prompts/mosaic/crisis_2008").exists()

    def test_private_git_requires_config(self, repo: Path):
        with pytest.raises(RpcError, match="MOSAIC_PRIVATE_PROMPT_REPO"):
            dispatch("prompts.write", {
                "agent": "volatility", "cohort": "crisis_2008",
                "contents": {"zh": "new zh\n"},
                "target": "private_git",
                "branch": BRANCH,
            })

    def test_to_private_git_branch_commits(self, repo: Path, tmp_path: Path, monkeypatch):
        private_repo = tmp_path / "private-prompts"
        init_private_prompt_repo(private_repo, project_root=repo)
        monkeypatch.setenv("MOSAIC_PRIVATE_PROMPT_REPO", str(private_repo))

        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n## 输出 schema\n", "en": "new en\n## Output schema\n"},
            "target": "private_git",
            "branch": BRANCH,
        })
        assert r["target"] == "private_git"
        assert r["prompt_repo_id"] == "private"
        assert len(r["prompt_base_commit_hash"]) == 40
        assert len(r["prompt_commit_hash"]) == 40
        assert r["branch"] == BRANCH
        assert len(r["paths"]) == 2
        assert not (repo / "prompts/mosaic/crisis_2008").exists()
        assert not (private_repo / "prompts/mosaic/crisis_2008").exists()
        prompt_at_branch = _git(
            private_repo,
            "show",
            f"{BRANCH}:prompts/mosaic/crisis_2008/macro/volatility.zh.md",
        )
        assert prompt_at_branch.startswith("new zh")

    def test_to_project_git_branch_commits(self, repo: Path):
        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "new zh\n## 输出 schema\n", "en": "new en\n## Output schema\n"},
            "target": "project_git",
            "branch": BRANCH,
        })
        assert r["target"] == "project_git"
        assert r["prompt_repo_id"] == "project"
        assert len(r["commit_hash"]) == 40
        assert r["branch"] == BRANCH
        assert len(r["paths"]) == 2
        # primary tree untouched (commit built in a worktree)
        assert not (repo / "prompts/mosaic/crisis_2008").exists()
        # readable back at the branch ref
        back = dispatch("prompts.read", {
            "agent": "volatility", "cohort": "crisis_2008", "lang": "zh", "ref": BRANCH,
        })
        assert back["content"].startswith("new zh")

    def test_to_working_tree(self, repo: Path):
        r = dispatch("prompts.write", {
            "agent": "volatility", "cohort": "crisis_2008",
            "contents": {"zh": "wt zh\n"},
            "allow_public_prompt_write": True,
        })
        assert "commit_hash" not in r
        assert r["target"] == "working_tree"
        assert (repo / "prompts/mosaic/crisis_2008/macro/volatility.zh.md").exists()

    def test_working_tree_requires_allow(self, repo: Path):
        with pytest.raises(RpcError, match="allow_public_prompt_write"):
            dispatch("prompts.write", {
                "agent": "volatility", "cohort": "crisis_2008",
                "contents": {"zh": "wt zh\n"},
            })

    def test_bad_contents(self, repo: Path):
        with pytest.raises(RpcError, match="contents"):
            dispatch("prompts.write", {"agent": "volatility", "cohort": "c", "contents": {}})

    def test_bad_lang_key(self, repo: Path):
        with pytest.raises(RpcError, match="contents"):
            dispatch("prompts.write", {"agent": "volatility", "cohort": "c", "contents": {"fr": "x"}})


def test_prompts_methods_registered():
    from mosaic.bridge.registry import all_methods

    assert {"prompts.read", "prompts.write", "prompts.init_private_repo"}.issubset(set(all_methods()))


def test_init_private_repo_rpc(repo: Path, tmp_path: Path):
    private_repo = tmp_path / "private-prompts"
    r = dispatch("prompts.init_private_repo", {"path": str(private_repo)})

    assert r["seeded"] is False
    assert len(r["commit_hash"]) == 40
    assert (private_repo / "prompts" / "mosaic" / ".gitkeep").exists()


def test_init_private_repo_rpc_can_seed_baseline(repo: Path, tmp_path: Path):
    private_repo = tmp_path / "private-prompts"
    r = dispatch("prompts.init_private_repo", {"path": str(private_repo), "seed_baseline": True})

    assert r["seeded"] is True
    assert (
        private_repo
        / "prompts"
        / "mosaic"
        / "cohort_default"
        / "macro"
        / "volatility.zh.md"
    ).read_text(encoding="utf-8").startswith("base zh")
