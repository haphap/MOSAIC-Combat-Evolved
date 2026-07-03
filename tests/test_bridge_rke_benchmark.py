from __future__ import annotations

import subprocess
import json
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


def test_capture_agent_claim_footprints_writes_private_redacted_rows(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-001",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {
                        "target_type": "macro_series",
                        "target_id": "USDCNY",
                        "metric_family": "fx_rate",
                    },
                    "direction": "positive",
                    "rke_context_hash": "a" * 64,
                    "retrieval_rank": 1,
                    "reason_codes": ["used_ranked_rke_prior"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "cio",
                    "as_of_date": "2026-06-18",
                    "claim_type": "portfolio_action_claim",
                    "target": {"target_type": "portfolio", "target_id": "cn_equity"},
                    "reason_codes": ["kept_shadow_only"],
                    "current_data_confirmed": False,
                },
            ],
        },
    )

    assert result["capture_status"] == "captured"
    assert result["captured_count"] == 2
    assert result["aggregate_profile_summary"]["layer_counts"] == {
        "decision": 1,
        "macro": 1,
    }
    assert result["privacy_scan"]["forbidden_field_violation_count"] == 0
    private_path = project_root / result["private_rows_path"]
    rows = [
        json.loads(line)
        for line in private_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["private_text_included"] is False
    assert rows[0]["production_signal_allowed"] is False
    payload = json.dumps(rows, ensure_ascii=False)
    assert "claim_text" not in payload
    assert "source_span_ids" not in payload
    assert "used_ranked_rke_prior" in payload


def test_capture_agent_claim_footprints_blocks_private_text_fields(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-002",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "claim_text": "private source prose",
                    "source_span_ids": ["SRC:p1"],
                }
            ],
        },
    )

    assert result["capture_status"] == "blocked"
    assert result["captured_count"] == 0
    assert result["privacy_scan"]["forbidden_field_violation_count"] == 1
    assert "claim_text" in result["failures"][0]
    assert not (project_root / result["private_rows_path"]).exists()


def test_agent_footprint_summary_reads_private_rows_as_redacted_aggregate(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-003",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                    "stale_prior_rejected": True,
                },
                {
                    "agent": "semiconductor",
                    "as_of_date": "2026-06-18",
                    "claim_type": "sector_claim",
                    "target": {"target_type": "sector", "target_id": "半导体"},
                    "rke_prior_usage_quality": "not_used_missing_current_data",
                    "contradictory_prior_handled": True,
                },
            ],
        },
    )

    summary = dispatch(
        "rke_benchmark.agent_footprint_summary",
        {"benchmark_run_id": "bench-003"},
    )

    assert summary["summary_status"] == "ready"
    assert summary["row_count"] == 2
    assert summary["layer_counts"] == {"macro": 1, "sector": 1}
    assert summary["claim_type_counts"] == {"macro_series_claim": 1, "sector_claim": 1}
    assert summary["rke_prior_usage_quality_counts"] == {
        "not_used_missing_current_data": 1,
        "used_ranked_prior": 1,
    }
    assert summary["current_data_confirmed_count"] == 1
    assert summary["stale_prior_rejected_count"] == 1
    assert summary["contradictory_prior_handled_count"] == 1
    assert summary["privacy_scan"]["forbidden_field_violation_count"] == 0
    payload = json.dumps(summary, ensure_ascii=False)
    assert "agent_claim_footprint_id" not in payload
    assert "USDCNY" not in payload
    assert "半导体" not in payload


def test_agent_footprint_summary_is_empty_without_private_rows(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    summary = dispatch(
        "rke_benchmark.agent_footprint_summary",
        {"benchmark_run_id": "bench-missing"},
    )

    assert summary["summary_status"] == "empty"
    assert summary["row_count"] == 0


def test_darwinian_autoresearch_manifest_blocks_missing_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_input_manifest",
        {"benchmark_run_id": "bench-empty"},
    )

    assert manifest["manifest_status"] == "blocked_preflight"
    assert manifest["rke_prior_treated_as_current_data"] is False
    assert manifest["blocked_reasons"] == [
        "agent_footprint_summary_missing",
        "downstream_outcome_metrics_missing",
        "prompt_mutation_provenance_missing",
    ]
    assert (
        manifest["skill_inputs"]["risk_adjusted_downstream_outcome"]["status"]
        == "missing"
    )


def test_darwinian_autoresearch_manifest_distinguishes_rke_prior_from_current_data(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-004",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "rke_context_hash": "b" * 64,
                    "current_data_confirmed": True,
                    "stale_prior_rejected": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_input_manifest",
        {
            "benchmark_run_id": "bench-004",
            "downstream_outcome_metrics": {
                "risk_adjusted_return": 0.12,
                "alpha": 0.03,
                "max_drawdown": -0.04,
                "turnover": 0.8,
                "cost_bps": 12,
            },
            "prompt_mutation_provenance": {
                "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                "prompt_repo_revision": "a" * 40,
                "prompt_sha256": "c" * 64,
            },
        },
    )

    assert manifest["manifest_status"] == "ready"
    assert manifest["promotion_allowed"] is False
    assert manifest["rke_prior_treated_as_current_data"] is False
    assert (
        manifest["skill_inputs"]["current_data_skill"][
            "current_data_confirmed_count"
        ]
        == 1
    )
    assert manifest["skill_inputs"]["research_prior_usage_skill"][
        "rke_prior_usage_quality_counts"
    ] == {"used_ranked_prior": 1}
    assert (
        manifest["skill_inputs"]["risk_adjusted_downstream_outcome"]["metrics"][
            "alpha"
        ]
        == 0.03
    )
