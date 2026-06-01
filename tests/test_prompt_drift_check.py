"""Tests for scripts/check_prompt_drift.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_prompt_drift.py"
_SPEC = importlib.util.spec_from_file_location("check_prompt_drift", _SCRIPT)
assert _SPEC and _SPEC.loader
check_prompt_drift = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = check_prompt_drift
_SPEC.loader.exec_module(check_prompt_drift)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    return path


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def _baseline_prompt(repo: Path, text: str = "baseline\n") -> Path:
    prompt = repo / "prompts" / "mosaic" / "cohort_default" / "macro" / "volatility.zh.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text(text, encoding="utf-8")
    return prompt


def test_no_drift_without_private_override(tmp_path: Path):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")
    _baseline_prompt(project, "v1\n")
    _commit(project, "add baseline")
    _baseline_prompt(project, "v2\n")
    _commit(project, "change baseline")

    findings = check_prompt_drift.check_drift(
        project_repo=project,
        private_repo=private,
        base_ref="HEAD~1",
    )

    assert findings == []


def test_detects_private_override_shadowing_changed_baseline(tmp_path: Path):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")
    _baseline_prompt(project, "v1\n")
    _commit(project, "add baseline")
    private_prompt = private / "prompts" / "mosaic" / "cohort_default" / "macro" / "volatility.zh.md"
    private_prompt.parent.mkdir(parents=True)
    private_prompt.write_text("private override\n", encoding="utf-8")
    _commit(private, "add private override")
    _baseline_prompt(project, "v2\n")
    _commit(project, "change baseline")

    findings = check_prompt_drift.check_drift(
        project_repo=project,
        private_repo=private,
        base_ref="HEAD~1",
    )

    assert len(findings) == 1
    assert findings[0].agent == "volatility"
    assert findings[0].lang == "zh"
    assert findings[0].path == "prompts/mosaic/cohort_default/macro/volatility.zh.md"


def test_main_json_output(tmp_path: Path, capsys):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")
    _baseline_prompt(project, "v1\n")
    _commit(project, "add baseline")
    private_prompt = private / "prompts" / "mosaic" / "cohort_default" / "macro" / "volatility.zh.md"
    private_prompt.parent.mkdir(parents=True)
    private_prompt.write_text("private override\n", encoding="utf-8")
    _commit(private, "add private override")
    _baseline_prompt(project, "v2\n")
    _commit(project, "change baseline")

    rc = check_prompt_drift.main(
        [
            "--repo",
            str(project),
            "--base-ref",
            "HEAD~1",
            "--private-repo",
            str(private),
            "--json",
        ]
    )

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["agent"] == "volatility"


def test_main_requires_private_repo(tmp_path: Path, monkeypatch, capsys):
    project = _init_repo(tmp_path / "project")
    monkeypatch.delenv("MOSAIC_PRIVATE_PROMPT_REPO", raising=False)

    rc = check_prompt_drift.main(["--repo", str(project), "--base-ref", "HEAD"])

    assert rc == 2
    assert "requires --private-repo" in capsys.readouterr().err


def test_main_accepts_pnpm_separator(tmp_path: Path):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")

    rc = check_prompt_drift.main(
        [
            "--",
            "--repo",
            str(project),
            "--base-ref",
            "HEAD",
            "--private-repo",
            str(private),
        ]
    )

    assert rc == 0


def test_main_requires_base_ref_or_state_file(tmp_path: Path, capsys):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")

    rc = check_prompt_drift.main(
        [
            "--repo",
            str(project),
            "--private-repo",
            str(private),
        ]
    )

    assert rc == 2
    assert "requires --base-ref or --state-file" in capsys.readouterr().err


def test_state_file_updates_after_passing_scheduled_check(tmp_path: Path):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")
    _baseline_prompt(project, "v1\n")
    _commit(project, "add baseline")
    old_head = _git(project, "rev-parse", "HEAD").strip()
    _baseline_prompt(project, "v2\n")
    _commit(project, "change baseline")
    new_head = _git(project, "rev-parse", "HEAD").strip()
    state_file = tmp_path / "state" / "prompt-drift.json"
    state_file.parent.mkdir()
    state_file.write_text(json.dumps({"baseline_ref": old_head}), encoding="utf-8")

    rc = check_prompt_drift.main(
        [
            "--repo",
            str(project),
            "--private-repo",
            str(private),
            "--state-file",
            str(state_file),
        ]
    )

    assert rc == 0
    assert json.loads(state_file.read_text(encoding="utf-8"))["baseline_ref"] == new_head


def test_state_file_not_updated_when_drift_found(tmp_path: Path):
    project = _init_repo(tmp_path / "project")
    private = _init_repo(tmp_path / "private")
    _baseline_prompt(project, "v1\n")
    _commit(project, "add baseline")
    old_head = _git(project, "rev-parse", "HEAD").strip()
    private_prompt = private / "prompts" / "mosaic" / "cohort_default" / "macro" / "volatility.zh.md"
    private_prompt.parent.mkdir(parents=True)
    private_prompt.write_text("private override\n", encoding="utf-8")
    _commit(private, "add private override")
    _baseline_prompt(project, "v2\n")
    _commit(project, "change baseline")
    state_file = tmp_path / "state" / "prompt-drift.json"
    state_file.parent.mkdir()
    state_file.write_text(json.dumps({"baseline_ref": old_head}), encoding="utf-8")

    rc = check_prompt_drift.main(
        [
            "--repo",
            str(project),
            "--private-repo",
            str(private),
            "--state-file",
            str(state_file),
        ]
    )

    assert rc == 1
    assert json.loads(state_file.read_text(encoding="utf-8"))["baseline_ref"] == old_head
