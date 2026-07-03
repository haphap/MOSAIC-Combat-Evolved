from __future__ import annotations

import subprocess
from pathlib import Path

from mosaic.bridge import handlers as _handlers_pkg  # noqa: F401
from mosaic.bridge.handlers import prompts as prompt_handlers
from mosaic.bridge.registry import get_handler


def dispatch(method: str, params: dict):
    handler = get_handler(method)
    if handler is None:
        raise AssertionError(f"method '{method}' not registered")
    return handler(params)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout


def _private_prompt_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "MOSAIC-Prompts"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    for layer, agents in prompt_handlers._AGENTS_BY_LAYER.items():
        root = repo / "prompts" / "mosaic" / "cohort_default" / layer
        root.mkdir(parents=True, exist_ok=True)
        for agent in agents:
            for lang in ("zh", "en"):
                (root / f"{agent}.{lang}.md").write_text(
                    f"{agent} {lang}\n", encoding="utf-8"
                )
    _git(repo, "add", "prompts/mosaic")
    _git(repo, "commit", "-m", "seed benchmark prompts")
    return repo


def test_fixed_episode_manifest_blocks_without_private_prompt_source():
    result = dispatch("rke_benchmark.fixed_episode_manifest", {})

    assert result["benchmark_status"] == "blocked_preflight"
    assert result["episode_count"] == 8
    assert result["as_of_date_count"] == 17
    assert result["agent_count"] == 25
    assert result["model_config_count"] == 4
    assert result["planned_run_count"] == 1700
    assert result["prompt_preflight"]["blocked_count"] == 50
    assert result["prompt_preflight"]["blocked_reasons"] == [
        "private_prompt_unavailable"
    ]
    assert result["promotion_allowed"] is False
    assert result["manual_review"]["status"] == "not_run"


def test_fixed_episode_manifest_is_ready_with_all_private_prompts(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch("rke_benchmark.fixed_episode_manifest", {})

    assert result["benchmark_status"] == "ready_to_run"
    assert result["prompt_preflight"] == {
        "ready": True,
        "row_count": 50,
        "blocked_count": 0,
        "blocked_reasons": [],
        "fallback_used": False,
    }
    assert set(result["agents_by_layer"]) == {
        "macro",
        "sector",
        "superinvestor",
        "decision",
    }
    assert "rke_prior_usage_quality" in result["scoring_metrics"]
    assert "current_data_confirmation" in result["scoring_metrics"]
    assert "private_prompt_hash_and_repo_revision" in result["input_requirements"]
