"""Tests for scripts/check_prompt_leaks.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_prompt_leaks.py"
_SPEC = importlib.util.spec_from_file_location("check_prompt_leaks", _SCRIPT)
assert _SPEC and _SPEC.loader
check_prompt_leaks = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = check_prompt_leaks
_SPEC.loader.exec_module(check_prompt_leaks)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def _codes(findings) -> set[str]:
    return {finding.code for finding in findings}


def test_allows_human_baseline_prompt_edit(tmp_path: Path):
    repo = _init_repo(tmp_path)
    prompt = repo / "prompts" / "mosaic" / "cohort_default" / "macro" / "volatility.zh.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("manual baseline improvement\n", encoding="utf-8")
    _commit(repo, "docs: improve volatility baseline")

    findings = check_prompt_leaks.check_repo(repo, "main~1")

    assert findings == []


def test_blocks_autoresearch_marker_in_prompt_diff(tmp_path: Path):
    repo = _init_repo(tmp_path)
    prompt = repo / "prompts" / "mosaic" / "cohort_default" / "macro" / "volatility.zh.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("autoresearch fake-llm marker\n", encoding="utf-8")
    _commit(repo, "docs: update prompt")

    findings = check_prompt_leaks.check_repo(repo, "main~1")

    assert "autoresearch-prompt-diff" in _codes(findings)


def test_blocks_private_prompt_paths(tmp_path: Path):
    repo = _init_repo(tmp_path)
    private_file = repo / "private-prompts" / "prompts" / "mosaic" / ".gitkeep"
    private_file.parent.mkdir(parents=True)
    private_file.write_text("", encoding="utf-8")
    _commit(repo, "add private prompt repo by mistake")

    findings = check_prompt_leaks.check_repo(repo, "main~1")

    assert "private-path" in _codes(findings)


def test_blocks_private_prompt_submodule(tmp_path: Path):
    repo = _init_repo(tmp_path)
    (repo / ".gitmodules").write_text(
        '[submodule "private-prompts"]\n\tpath = private-prompts\n\turl = git@example/private.git\n',
        encoding="utf-8",
    )
    _commit(repo, "add private prompt submodule")

    findings = check_prompt_leaks.check_repo(repo, "main~1")

    assert "private-submodule" in _codes(findings)


def test_blocks_autoresearch_commit_subject(tmp_path: Path):
    repo = _init_repo(tmp_path)
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")
    _commit(repo, "autoresearch: mutate volatility prompt")

    findings = check_prompt_leaks.check_repo(repo, "main~1")

    assert "autoresearch-commit" in _codes(findings)


def test_blocks_project_autoresearch_runtime_branch(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "cohort/crisis_2008/auto/volatility/2008-09-15")

    findings = check_prompt_leaks.check_repo(repo, "main")

    assert "autoresearch-branch" in _codes(findings)
