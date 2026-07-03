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


def _runtime_context_proof(rank: int = 1) -> dict:
    priority_bucket = "high" if rank <= 3 else "medium" if rank <= 10 else "low"
    return {
        "ranking_policy_id": "rke_agent_research_context_rank_v1",
        "retrieval_rank": rank,
        "priority_bucket": priority_bucket,
        "truncated_item_count": 0,
    }


def _model_config_output_counts(count: int = 425) -> dict:
    return {
        "baseline_current_config": count,
        "local_qwen_27b": count,
        "local_qwen3_6_35b": count,
    }


def _benchmark_quality_summary(
    benchmark_run_id: str = "bench-ready", **overrides: object
) -> dict:
    row = {
        "benchmark_run_id": benchmark_run_id,
        "quality_gate_ref": "benchmark-quality-gate-1",
        "schema_failure_gate_passed": True,
        "severe_safety_violation_count": 0,
        "current_data_confirmation_violation_count": 0,
        "fallback_prompt_run_count": 0,
    }
    row.update(overrides)
    return row


def _benchmark_evidence_refs(benchmark_run_id: str = "bench-ready") -> dict:
    return {
        "benchmark_run_id": benchmark_run_id,
        "episode_manifest_ref": f"{benchmark_run_id}-episode-manifest",
        "as_of_date_manifest_ref": f"{benchmark_run_id}-as-of-dates",
        "model_config_manifest_ref": f"{benchmark_run_id}-model-configs",
        "paired_output_manifest_ref": f"{benchmark_run_id}-paired-output-manifest",
        "output_schema_validation_report_ref": f"{benchmark_run_id}-schema-report",
        "deterministic_score_table_ref": f"{benchmark_run_id}-score-table",
        "investment_outcome_table_ref": f"{benchmark_run_id}-investment-outcomes",
    }


def _manual_review(benchmark_run_id: str = "bench-ready") -> dict:
    return {
        "benchmark_run_id": benchmark_run_id,
        "decision": "approved",
        "reviewer_timestamp": "2026-07-03T12:00:00Z",
    }


def _profile_evidence(benchmark_run_id: str = "bench-profile-ready") -> dict:
    return {
        "benchmark_run_id": benchmark_run_id,
        "profile_update_ref": f"{benchmark_run_id}-profile-update",
        "evolution_input_ref": f"{benchmark_run_id}-evolution-input",
        "no_source_prose_audit_ref": f"{benchmark_run_id}-no-source-prose",
    }


def _paper_trading_plan(benchmark_run_id: str, **overrides: object) -> dict:
    row = {
        "benchmark_run_id": benchmark_run_id,
        "paper_trading_plan_ref": f"{benchmark_run_id}-paper-plan",
        "risk_limit_ref": f"{benchmark_run_id}-risk-limits",
        "stop_loss_or_rollback_ref": f"{benchmark_run_id}-stop-loss",
        "operator_review_timestamp": "2026-07-03T12:30:00Z",
        "operator_review_approved": True,
    }
    row.update(overrides)
    return row


def _promotion_evidence(benchmark_run_id: str, **overrides: object) -> dict:
    row = {
        "benchmark_run_id": benchmark_run_id,
        "paper_trading_result_ref": f"{benchmark_run_id}-paper-results",
        "monitor_summary_ref": f"{benchmark_run_id}-monitor-summary",
        "second_review_timestamp": "2026-07-03T13:00:00Z",
        "lockbox_decision_ref": f"{benchmark_run_id}-lockbox",
        "decision": "approved_for_promotion_review",
        "second_review_approved": True,
    }
    row.update(overrides)
    return row


def _prompt_release_check() -> dict:
    return {
        "mutation_candidate_id": "PMUT-1",
        "prompt_version_id": 42,
        "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
        "prompt_commit_hash": "a" * 40,
        "prompt_sha256": "b" * 64,
        "audit_version_ref": "audit-release-1",
        "verify_release_ref": "verify-release-1",
        "leak_drift_check_ref": "leak-drift-1",
        "verify_release_passed": True,
        "leak_drift_passed": True,
        "release_ready": True,
    }


def _prompt_release_check_from_lifecycle(
    manifest: dict, **overrides: object
) -> dict:
    record = manifest["lifecycle_records"][0]
    prompt_pin = record["prompt_pins"][0]
    row = _prompt_release_check()
    row.update(
        {
            "mutation_candidate_id": record["mutation_candidate_id"],
            "prompt_repo_id": prompt_pin["prompt_repo_id"],
            "private_prompt_branch": record["private_prompt_branch"],
            "base_prompt_repo_revision": prompt_pin["prompt_repo_revision"],
            "overwrite_target_paths": record["overwrite_target_paths"],
            "prompt_sha256": prompt_pin["prompt_sha256"],
        }
    )
    row.update(overrides)
    return row


def _prompt_release_check_for_candidates(
    candidates: list[dict],
    benchmark_run_id: str | None = None,
    **overrides: object,
) -> dict:
    lifecycle = dispatch(
        "rke_benchmark.prompt_mutation_lifecycle_manifest",
        {"candidates": candidates},
    )
    row = _prompt_release_check_from_lifecycle(lifecycle, **overrides)
    if benchmark_run_id is not None:
        row["benchmark_run_id"] = benchmark_run_id
    return row


def _rollback_evidence_for_candidates(
    candidates: list[dict],
    benchmark_run_id: str | None = None,
    **overrides: object,
) -> dict:
    lifecycle = dispatch(
        "rke_benchmark.prompt_mutation_lifecycle_manifest",
        {"candidates": candidates},
    )
    record = lifecycle["lifecycle_records"][0]
    previous_hashes = sorted(
        {
            pin["prompt_sha256"]
            for pin in record["prompt_pins"]
            if pin.get("prompt_sha256")
        }
    )
    row = {
        "mutation_candidate_id": record["mutation_candidate_id"],
        "previous_prompt_hashes": previous_hashes,
        "rollback_trigger_definition": "manual review or monitor breach",
        "rollback_command_or_procedure": "restore previous prompt commit",
        "monitor_output_ref": "monitor-run-1",
        "post_rollback_verification_ref": "verify-run-1",
    }
    if benchmark_run_id is not None:
        row["benchmark_run_id"] = benchmark_run_id
    row.update(overrides)
    return row


def _patch_activation_evidence(
    benchmark_run_id: str | None = None, **overrides: object
) -> dict:
    row = {
        "mutation_candidate_id": "PMUT-1",
        "patch_artifact_ref": "patch-artifact-1",
        "patch_validation_ref": "patch-validation-1",
        "shadow_apply_ref": "shadow-apply-1",
        "runtime_activation_ref": "runtime-activation-1",
        "runtime_proof_ref": "runtime-proof-1",
        "rollback_ref": "rollback-1",
        "shadow_activation_passed": True,
        "runtime_proof_passed": True,
        "production_activation_allowed": False,
    }
    if benchmark_run_id is not None:
        row["benchmark_run_id"] = benchmark_run_id
    row.update(overrides)
    return row


def _darwinian_consumption_evidence(
    benchmark_run_id: str = "bench-consumption-ready", **overrides: object
) -> dict:
    row = {
        "benchmark_run_id": benchmark_run_id,
        "replay_run_id": "replay-1",
        "input_manifest_ref": "darwinian-input-1",
        "rke_prior_usage_metrics_ref": "rke-prior-usage-1",
        "downstream_outcome_metrics_ref": "downstream-outcome-1",
        "darwinian_weight_update_ref": "darwinian-weight-1",
        "autoresearch_update_ref": "autoresearch-update-1",
        "rollback_readiness_ref": "rollback-readiness-1",
        "darwinian_consumed": True,
        "autoresearch_consumed": True,
        "rke_prior_treated_as_current_data": False,
        "production_weight_update_allowed": False,
    }
    row.update(overrides)
    return row


def _downstream_outcome_metrics(benchmark_run_id: str) -> dict:
    return {
        "benchmark_run_id": benchmark_run_id,
        "risk_adjusted_return": 0.12,
        "alpha": 0.03,
        "max_drawdown": -0.04,
        "turnover": 0.8,
        "cost_bps": 12,
    }


def _prompt_mutation_provenance(benchmark_run_id: str) -> dict:
    return {
        "benchmark_run_id": benchmark_run_id,
        "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
        "prompt_repo_revision": "a" * 40,
        "prompt_sha256": "c" * 64,
    }


def _all_prompt_release_checks(
    rows: list[dict], benchmark_run_id: str | None = None
) -> list[dict]:
    release_checks = []
    for index, row in enumerate(rows, 1):
        release_check = {
            "agent": row["agent"],
            "lang": row["lang"],
            "prompt_version_id": index,
            "prompt_repo_id": row["prompt_repo_id"],
            "prompt_repo_revision": row["prompt_repo_revision"],
            "prompt_file_path": row["prompt_file_path"],
            "prompt_sha256": row["prompt_sha256"],
            "audit_version_ref": f"audit-all-{index}",
            "verify_release_ref": f"verify-all-{index}",
            "leak_drift_check_ref": f"leak-all-{index}",
            "verify_release_passed": True,
            "leak_drift_passed": True,
        }
        if benchmark_run_id is not None:
            release_check["benchmark_run_id"] = benchmark_run_id
        release_checks.append(release_check)
    return release_checks


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
    assert result["prompt_preflight"]["source_status"]["blocked_reason"] == (
        "private_prompt_unavailable"
    )
    assert result["prompt_preflight"]["source_status"]["prompt_repo_dirty_count"] == 0
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
        "source_status": {
            "ready": True,
            "blocked_reason": "",
            "resolved_source": "private_repo",
            "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
            "prompt_repo_revision": result["prompt_preflight"]["source_status"][
                "prompt_repo_revision"
            ],
            "prompt_repo_dirty_count": 0,
        },
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


def test_all_agent_prompt_provenance_readiness_blocks_missing_source():
    result = dispatch("rke_benchmark.all_agent_prompt_provenance_readiness", {})

    assert result["readiness_status"] == "blocked_preflight"
    assert result["prompt_row_count"] == 50
    assert result["release_check_count"] == 0
    assert result["prompt_source_status"]["blocked_reason"] == (
        "private_prompt_unavailable"
    )
    assert "prompt_preflight_not_ready" in result["blocked_reasons"]
    assert "release_check_missing" in result["blocked_reasons"]
    assert result["all_agent_prompt_provenance_ready"] is False
    assert result["production_prompt_change_allowed"] is False


def test_all_agent_prompt_provenance_readiness_accepts_private_release_checks(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {"release_checks": _all_prompt_release_checks(preflight["rows"])},
    )

    assert result["readiness_status"] == "ready"
    assert result["agent_count"] == 25
    assert result["prompt_row_count"] == 50
    assert result["ready_prompt_row_count"] == 50
    assert result["release_check_count"] == 50
    assert result["all_agent_prompt_provenance_ready"] is True
    assert result["fallback_used"] is False
    assert result["prompt_rows"][0]["audit_version_ref"].startswith("audit-all-")


def test_all_agent_prompt_provenance_readiness_requires_audit_versions(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    release_checks = _all_prompt_release_checks(preflight["rows"])
    release_checks[0].pop("audit_version_ref")

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {"release_checks": release_checks},
    )

    assert result["readiness_status"] == "blocked_preflight"
    assert "audit_version_ref_missing" in result["blocked_reasons"]
    assert result["all_agent_prompt_provenance_ready"] is False


def test_all_agent_prompt_provenance_readiness_rejects_bool_prompt_version(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    release_checks = _all_prompt_release_checks(preflight["rows"])
    release_checks[0]["prompt_version_id"] = True

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {"release_checks": release_checks},
    )

    assert result["readiness_status"] == "blocked_preflight"
    assert "prompt_version_id_missing" in result["blocked_reasons"]
    assert result["prompt_rows"][0]["prompt_version_id"] is None
    assert result["all_agent_prompt_provenance_ready"] is False


def test_all_agent_prompt_provenance_readiness_blocks_release_repo_mismatch(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    release_checks = _all_prompt_release_checks(preflight["rows"])
    release_checks[0]["prompt_repo_revision"] = "bad-revision"

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {"release_checks": release_checks},
    )

    assert result["readiness_status"] == "blocked_preflight"
    assert "prompt_repo_revision_mismatch" in result["blocked_reasons"]
    assert result["all_agent_prompt_provenance_ready"] is False


def test_all_agent_prompt_provenance_readiness_blocks_cross_run_release_checks(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {
            "benchmark_run_id": "bench-prompt-ready",
            "release_checks": _all_prompt_release_checks(
                preflight["rows"], "other-run"
            ),
        },
    )

    assert result["readiness_status"] == "blocked_preflight"
    assert "release_check_benchmark_run_id_mismatch" in result["blocked_reasons"]
    assert result["all_agent_prompt_provenance_ready"] is False


def test_all_agent_prompt_provenance_readiness_blocks_release_path_mismatch(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    release_checks = _all_prompt_release_checks(preflight["rows"])
    release_checks[0]["prompt_file_path"] = (
        "prompts/mosaic/cohort_default/macro/wrong.zh.md"
    )

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {"release_checks": release_checks},
    )

    assert result["readiness_status"] == "blocked_preflight"
    assert "prompt_file_path_mismatch" in result["blocked_reasons"]
    assert result["all_agent_prompt_provenance_ready"] is False


def test_fixed_episode_benchmark_evidence_blocks_missing_proof(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.delenv("MOSAIC_PROMPTS_REPO", raising=False)
    monkeypatch.delenv("MOSAIC_PRIVATE_PROMPT_REPO", raising=False)
    monkeypatch.delenv("MOSAIC_PROMPTS_ROOT", raising=False)

    result = dispatch(
        "rke_benchmark.fixed_episode_benchmark_evidence",
        {"benchmark_run_id": "bench-missing"},
    )

    assert result["evidence_status"] == "blocked_preflight"
    assert result["required_paired_output_count"] == 1275
    assert result["prompt_source_status"]["blocked_reason"] == (
        "private_prompt_unavailable"
    )
    assert "private_prompt_preflight_not_ready" in result["blocked_reasons"]
    assert "paired_output_count_below_required" in result["blocked_reasons"]
    assert (
        "model_config_output_count_below_required:baseline_current_config"
        in result["blocked_reasons"]
    )
    assert "quality_gate_ref_missing" in result["blocked_reasons"]
    assert "schema_failure_gate_not_passed" in result["blocked_reasons"]
    assert "episode_manifest_ref_missing" in result["blocked_reasons"]
    assert "model_config_manifest_ref_missing" in result["blocked_reasons"]
    assert "manual_review_not_approved" in result["blocked_reasons"]
    assert result["promotion_allowed"] is False


def test_fixed_episode_benchmark_evidence_accepts_no_body_proof(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "rke_benchmark.fixed_episode_benchmark_evidence",
        {
            "benchmark_run_id": "bench-ready",
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(),
            "evidence_refs": _benchmark_evidence_refs(),
            "manual_review": _manual_review(),
        },
    )

    assert result["evidence_status"] == "ready"
    assert result["blocked_reasons"] == []
    assert result["paired_output_count"] == result["required_paired_output_count"]
    assert result["model_config_output_counts"] == _model_config_output_counts()
    assert result["prompt_source_status"]["ready"] is True
    assert result["prompt_source_status"]["prompt_repo_dirty_count"] == 0
    assert result["manual_review"]["decision"] == "approved"
    assert result["promotion_allowed"] is False


def test_fixed_episode_benchmark_evidence_blocks_cross_run_proof_refs(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "rke_benchmark.fixed_episode_benchmark_evidence",
        {
            "benchmark_run_id": "bench-ready",
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary("other-run"),
            "evidence_refs": _benchmark_evidence_refs("other-run"),
            "manual_review": _manual_review("other-run"),
        },
    )

    assert result["evidence_status"] == "blocked_preflight"
    assert "benchmark_quality_summary_benchmark_run_id_mismatch" in result[
        "blocked_reasons"
    ]
    assert "evidence_refs_benchmark_run_id_mismatch" in result["blocked_reasons"]
    assert "manual_review_benchmark_run_id_mismatch" in result["blocked_reasons"]


def test_fixed_episode_benchmark_evidence_blocks_missing_required_model_counts(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    counts = _model_config_output_counts()
    counts["local_qwen_27b"] = 0
    result = dispatch(
        "rke_benchmark.fixed_episode_benchmark_evidence",
        {
            "benchmark_run_id": "bench-missing-model",
            "paired_output_count": 1275,
            "model_config_output_counts": counts,
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-missing-model"
            ),
            "evidence_refs": _benchmark_evidence_refs("bench-missing-model"),
            "manual_review": _manual_review("bench-missing-model"),
        },
    )

    assert result["evidence_status"] == "blocked_preflight"
    assert "paired_output_count_below_required" not in result["blocked_reasons"]
    assert (
        "model_config_output_count_below_required:local_qwen_27b"
        in result["blocked_reasons"]
    )
    assert result["model_config_output_counts"]["local_qwen_27b"] == 0


def test_fixed_episode_benchmark_evidence_blocks_quality_gate_failures(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    result = dispatch(
        "rke_benchmark.fixed_episode_benchmark_evidence",
        {
            "benchmark_run_id": "bench-quality-fail",
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-quality-fail",
                severe_safety_violation_count=1
            ),
            "evidence_refs": _benchmark_evidence_refs("bench-quality-fail"),
            "manual_review": _manual_review("bench-quality-fail"),
        },
    )

    assert result["evidence_status"] == "blocked_preflight"
    assert "severe_safety_violation_count_nonzero" in result["blocked_reasons"]
    assert result["benchmark_quality_summary"]["severe_safety_violation_count"] == 1


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
                    **_runtime_context_proof(1),
                    "reason_codes": ["used_ranked_rke_prior"],
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
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
    assert result["aggregate_profile_summary"]["report_claim_ref_count"] == 1
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
    assert "forecast_claim:macro-usdcny-001" in payload


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


def test_capture_agent_claim_footprints_blocks_invalid_context_hash(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-invalid-context-hash",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "not-a-sha256",
                }
            ],
        },
    )

    assert result["capture_status"] == "blocked"
    assert result["captured_count"] == 0
    assert "rke_context_hash must be a 64-character hex digest" in result[
        "failures"
    ][0]
    assert not (project_root / result["private_rows_path"]).exists()


def test_capture_agent_claim_footprints_blocks_invalid_retrieval_rank(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-invalid-retrieval-rank",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    "retrieval_rank": 0,
                }
            ],
        },
    )

    assert result["capture_status"] == "blocked"
    assert result["captured_count"] == 0
    assert "retrieval_rank must be a positive integer" in result["failures"][0]
    assert not (project_root / result["private_rows_path"]).exists()


def test_capture_agent_claim_footprints_blocks_wrong_ranking_policy(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-wrong-ranking-policy",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    "ranking_policy_id": "other_ranker",
                }
            ],
        },
    )

    assert result["capture_status"] == "blocked"
    assert result["captured_count"] == 0
    assert (
        "ranking_policy_id must be rke_agent_research_context_rank_v1"
        in result["failures"][0]
    )
    assert not (project_root / result["private_rows_path"]).exists()


def test_capture_agent_claim_footprints_blocks_unsupported_priority_bucket(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-wrong-priority-bucket",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    "priority_bucket": "agent_specific",
                }
            ],
        },
    )

    assert result["capture_status"] == "blocked"
    assert result["captured_count"] == 0
    assert "priority_bucket must be high, medium, or low" in result["failures"][0]
    assert not (project_root / result["private_rows_path"]).exists()


def test_capture_agent_claim_footprints_blocks_invalid_truncation_count(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-invalid-truncation-count",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    "truncated_item_count": -1,
                }
            ],
        },
    )

    assert result["capture_status"] == "blocked"
    assert result["captured_count"] == 0
    assert "truncated_item_count must be a non-negative integer" in result[
        "failures"
    ][0]
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
                    "rke_context_hash": "a" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
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
    assert summary["report_claim_ref_count"] == 1
    assert summary["ranking_policy_id_counts"] == {
        "rke_agent_research_context_rank_v1": 1
    }
    assert summary["retrieval_rank_count"] == 1
    assert summary["priority_bucket_counts"] == {"high": 1}
    assert summary["truncation_audit_count"] == 1
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


def test_agent_profile_evolution_readiness_blocks_missing_footprints(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {"benchmark_run_id": "bench-profile-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "agent_footprint_summary_missing" in manifest["blocked_reasons"]
    assert "layer_coverage_incomplete" in manifest["blocked_reasons"]
    assert manifest["profile_evolution_ready"] is False
    assert manifest["production_signal_allowed"] is False


def test_agent_profile_evolution_readiness_blocks_missing_report_claim_link(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-profile-missing-report-link",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {"benchmark_run_id": "bench-profile-missing-report-link"},
    )

    assert "report_claim_link_missing" in manifest["blocked_reasons"]
    assert manifest["report_claim_ref_count"] == 0
    assert manifest["profile_evolution_ready"] is False


def test_agent_profile_evolution_readiness_blocks_partial_report_claim_links(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-profile-partial-report-link",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "b" * 64,
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {"benchmark_run_id": "bench-profile-partial-report-link"},
    )

    assert "rke_context_report_claim_link_incomplete" in manifest["blocked_reasons"]
    assert manifest["rke_context_hash_count"] == 2
    assert manifest["rke_context_report_claim_linked_count"] == 1
    assert manifest["profile_evolution_ready"] is False


def test_agent_profile_evolution_readiness_blocks_missing_runtime_metadata(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-profile-missing-runtime-metadata",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {
            "benchmark_run_id": "bench-profile-missing-runtime-metadata",
            "profile_evidence": _profile_evidence(
                "bench-profile-missing-runtime-metadata"
            ),
        },
    )

    assert "ranking_policy_id_missing" in manifest["blocked_reasons"]
    assert "retrieval_rank_missing" in manifest["blocked_reasons"]
    assert "priority_bucket_missing" in manifest["blocked_reasons"]
    assert "truncation_audit_missing" in manifest["blocked_reasons"]
    assert manifest["profile_evolution_ready"] is False


def test_agent_profile_evolution_readiness_blocks_partial_current_data_confirmation(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-profile-partial-current-data",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "b" * 64,
                    **_runtime_context_proof(2),
                    "report_claim_refs": ["forecast_claim:stock-000001-001"],
                    "current_data_confirmed": False,
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {
            "benchmark_run_id": "bench-profile-partial-current-data",
            "profile_evidence": _profile_evidence("bench-profile-partial-current-data"),
        },
    )

    assert "current_data_confirmation_missing" in manifest["blocked_reasons"]
    assert manifest["rke_context_hash_count"] == 2
    assert manifest["current_data_confirmed_count"] == 1
    assert manifest["profile_evolution_ready"] is False


def test_agent_profile_evolution_readiness_accepts_redacted_all_layer_profile(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-profile-ready",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "semiconductor",
                    "as_of_date": "2026-06-18",
                    "claim_type": "sector_claim",
                    "target": {"target_type": "sector", "sector": "semiconductor"},
                    "rke_context_hash": "b" * 64,
                    **_runtime_context_proof(2),
                    "report_claim_refs": ["forecast_claim:sector-semi-001"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "c" * 64,
                    **_runtime_context_proof(3),
                    "report_claim_refs": ["forecast_claim:stock-000001-001"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "cio",
                    "as_of_date": "2026-06-18",
                    "claim_type": "portfolio_action_claim",
                    "target": {"target_type": "portfolio", "target_id": "cn_equity"},
                    "rke_context_hash": "d" * 64,
                    **_runtime_context_proof(4),
                    "report_claim_refs": ["forecast_claim:portfolio-cn-equity-001"],
                    "current_data_confirmed": True,
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {
            "benchmark_run_id": "bench-profile-ready",
            "profile_evidence": _profile_evidence("bench-profile-ready"),
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["observed_layers"] == [
        "decision",
        "macro",
        "sector",
        "superinvestor",
    ]
    assert manifest["missing_layers"] == []
    assert manifest["report_claim_ref_count"] == 4
    assert manifest["rke_context_report_claim_linked_count"] == 4
    assert manifest["current_data_confirmed_count"] == 4
    assert manifest["privacy_scan"]["forbidden_field_violation_count"] == 0
    assert manifest["profile_evolution_ready"] is True
    assert manifest["production_signal_allowed"] is False


def test_agent_profile_evolution_readiness_blocks_cross_run_profile_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-profile-ready",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
                },
                {
                    "agent": "semiconductor",
                    "as_of_date": "2026-06-18",
                    "claim_type": "sector_claim",
                    "target": {"target_type": "sector", "sector": "semiconductor"},
                    "rke_context_hash": "b" * 64,
                    **_runtime_context_proof(2),
                    "report_claim_refs": ["forecast_claim:sector-semi-001"],
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "c" * 64,
                    **_runtime_context_proof(3),
                    "report_claim_refs": ["forecast_claim:stock-000001-001"],
                },
                {
                    "agent": "cio",
                    "as_of_date": "2026-06-18",
                    "claim_type": "portfolio_action_claim",
                    "target": {"target_type": "portfolio", "target_id": "cn_equity"},
                    "rke_context_hash": "d" * 64,
                    **_runtime_context_proof(4),
                    "report_claim_refs": ["forecast_claim:portfolio-cn-equity-001"],
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {
            "benchmark_run_id": "bench-profile-ready",
            "profile_evidence": _profile_evidence("other-run"),
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "profile_evidence_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert manifest["profile_evolution_ready"] is False


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
    assert set(manifest["blocked_reasons"]) == {
        "agent_footprint_summary_missing",
        "downstream_outcome_metrics_benchmark_run_id_missing",
        "downstream_outcome_metrics_missing",
        "prompt_mutation_provenance_benchmark_run_id_missing",
        "prompt_mutation_provenance_missing",
    }
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
                    "report_claim_refs": ["forecast_claim:macro-usdcny-004"],
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
            "downstream_outcome_metrics": _downstream_outcome_metrics("bench-004"),
            "prompt_mutation_provenance": _prompt_mutation_provenance("bench-004"),
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
        manifest["skill_inputs"]["research_prior_usage_skill"][
            "rke_context_report_claim_linked_count"
        ]
        == 1
    )
    assert (
        manifest["skill_inputs"]["risk_adjusted_downstream_outcome"]["metrics"][
            "alpha"
        ]
        == 0.03
    )


def test_darwinian_autoresearch_manifest_blocks_partial_current_data_confirmation(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-partial-current-data-input",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "rke_context_hash": "b" * 64,
                    "report_claim_refs": ["forecast_claim:macro-usdcny-004"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "china",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "CN10Y"},
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "rke_context_hash": "c" * 64,
                    "report_claim_refs": ["forecast_claim:macro-cn10y-004"],
                    "current_data_confirmed": False,
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_input_manifest",
        {
            "benchmark_run_id": "bench-partial-current-data-input",
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-partial-current-data-input"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-partial-current-data-input"
            ),
        },
    )

    assert manifest["manifest_status"] == "blocked_preflight"
    assert "current_data_confirmation_missing" in manifest["blocked_reasons"]
    assert (
        manifest["skill_inputs"]["current_data_skill"][
            "current_data_confirmed_count"
        ]
        == 1
    )
    assert (
        manifest["skill_inputs"]["research_prior_usage_skill"]["rke_context_hash_count"]
        == 2
    )


def test_darwinian_autoresearch_manifest_blocks_cross_run_inputs(
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
                    "report_claim_refs": ["forecast_claim:macro-usdcny-004"],
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_input_manifest",
        {
            "benchmark_run_id": "bench-004",
            "downstream_outcome_metrics": _downstream_outcome_metrics("other-run"),
            "prompt_mutation_provenance": _prompt_mutation_provenance("other-run"),
        },
    )

    assert manifest["manifest_status"] == "blocked_preflight"
    assert "downstream_outcome_metrics_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert "prompt_mutation_provenance_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]


def test_darwinian_autoresearch_consumption_blocks_missing_replay_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_consumption_readiness",
        {"benchmark_run_id": "bench-consumption-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "darwinian_autoresearch_input_not_ready" in manifest["blocked_reasons"]
    assert (
        "darwinian_autoresearch_consumption_evidence_missing"
        in manifest["blocked_reasons"]
    )
    assert "replay_run_id_missing" in manifest["blocked_reasons"]
    assert manifest["darwinian_autoresearch_consumption_ready"] is False
    assert manifest["production_allowed"] is False


def test_darwinian_autoresearch_consumption_accepts_replay_refs(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-consumption-ready",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "rke_context_hash": "b" * 64,
                    "report_claim_refs": ["forecast_claim:macro-usdcny-consumption"],
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_consumption_readiness",
        {
            "benchmark_run_id": "bench-consumption-ready",
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-consumption-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-consumption-ready"
            ),
            "consumption_evidence": _darwinian_consumption_evidence(),
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["input_manifest_status"] == "ready"
    assert manifest["rke_prior_treated_as_current_data"] is False
    assert manifest["darwinian_autoresearch_consumption_ready"] is True
    assert manifest["consumption_evidence"]["replay_run_id"] == "replay-1"
    assert manifest["promotion_allowed"] is False


def test_darwinian_autoresearch_consumption_blocks_cross_run_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-consumption-ready",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "rke_context_hash": "b" * 64,
                    "report_claim_refs": ["forecast_claim:macro-usdcny-consumption"],
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.darwinian_autoresearch_consumption_readiness",
        {
            "benchmark_run_id": "bench-consumption-ready",
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-consumption-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-consumption-ready"
            ),
            "consumption_evidence": _darwinian_consumption_evidence("other-run"),
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "consumption_evidence_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert manifest["darwinian_autoresearch_consumption_ready"] is False


def _mutation_candidate(**overrides):
    row = {
        "mutation_candidate_id": "PMUT-1",
        "run_id": "run-1",
        "schema_version": "report_intelligence_prompt_mutation_candidate_v1",
        "candidate_type": "macro_prior_rule_parameter_refusal",
        "target_scope": "macro",
        "target_component": "macro.dollar",
        "proposed_change": "redacted aggregate rule evidence only",
        "trigger_sources": ["rke_prior_compiler"],
        "evidence_refs": [{"artifact": "prompt_mutation_candidates"}],
        "severity": "medium",
        "validation_requirements": ["pit_outcome_replay_pass"],
        "blocked_by": ["missing_pit_outcome", "source_dependent_cluster"],
        "promotion_state": "shadow_candidate_only",
        "manual_review_required": True,
        "production_prompt_change_allowed": False,
        "private_text_included": False,
        "policy": "shadow only",
    }
    row.update(overrides)
    return row


def test_candidate_consumption_manifest_blocks_missing_artifact(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch("rke_benchmark.candidate_consumption_manifest", {})

    assert manifest["manifest_status"] == "blocked_preflight"
    assert manifest["missing_artifact"] is True
    assert manifest["candidate_count"] == 0
    assert manifest["manifest_blockers"] == ["prompt_mutation_candidates_missing"]


def test_candidate_consumption_manifest_preserves_refusal_blockers():
    manifest = dispatch(
        "rke_benchmark.candidate_consumption_manifest",
        {
            "candidates": [
                _mutation_candidate(),
                _mutation_candidate(
                    mutation_candidate_id="PMUT-2",
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=["missing_validation_target"],
                ),
            ]
        },
    )

    assert manifest["manifest_status"] == "ready_for_private_prompt_lifecycle"
    assert manifest["candidate_count"] == 2
    assert manifest["refusal_count"] == 1
    assert manifest["blocked_reason_counts"] == {
        "missing_pit_outcome": 1,
        "missing_validation_target": 1,
        "source_dependent_cluster": 1,
    }
    assert manifest["production_prompt_change_allowed"] is False
    assert manifest["private_prompt_mutation_required"] is True
    payload = json.dumps(manifest, ensure_ascii=False)
    assert "redacted aggregate rule evidence only" not in payload
    assert "evidence_refs" not in payload


def test_candidate_consumption_manifest_rejects_prompt_bypass():
    manifest = dispatch(
        "rke_benchmark.candidate_consumption_manifest",
        {
            "candidates": [
                _mutation_candidate(
                    production_prompt_change_allowed=True,
                    promotion_state="ready_for_production",
                )
            ]
        },
    )

    assert manifest["manifest_status"] == "blocked_preflight"
    assert any(
        "production_prompt_change_allowed must be false" in failure
        for failure in manifest["manifest_blockers"]
    )
    assert any(
        "promotion_state must remain shadow_candidate_only" in failure
        for failure in manifest["manifest_blockers"]
    )


def test_patch_activation_readiness_blocks_missing_runtime_proof():
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.patch_activation_readiness",
        {"candidates": candidates},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "patch_activation_evidence_missing" in manifest["blocked_reasons"]
    assert "runtime_proof_ref_missing" in manifest["blocked_reasons"]
    assert manifest["patch_activation_ready"] is False
    assert manifest["production_allowed"] is False


def test_patch_activation_readiness_accepts_shadow_runtime_proof():
    benchmark_run_id = "bench-patch-ready"
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.patch_activation_readiness",
        {
            "benchmark_run_id": benchmark_run_id,
            "candidates": candidates,
            "patch_activation_evidence": [_patch_activation_evidence(benchmark_run_id)],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["patch_activation_ready"] is True
    assert manifest["direct_runtime_write_allowed"] is False
    record = manifest["activation_records"][0]
    assert record["runtime_proof_ref"] == "runtime-proof-1"
    assert record["patch_activation_ready"] is True


def test_patch_activation_readiness_blocks_missing_benchmark_run_id():
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.patch_activation_readiness",
        {
            "candidates": candidates,
            "patch_activation_evidence": [_patch_activation_evidence()],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "benchmark_run_id_missing" in manifest["blocked_reasons"]
    assert manifest["patch_activation_ready"] is False


def test_patch_activation_readiness_blocks_cross_run_evidence():
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.patch_activation_readiness",
        {
            "benchmark_run_id": "bench-patch-ready",
            "candidates": candidates,
            "patch_activation_evidence": [
                _patch_activation_evidence("other-benchmark-run")
            ],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "patch_activation_evidence_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert manifest["patch_activation_ready"] is False


def test_patch_activation_readiness_keeps_candidate_blockers():
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=["missing_validation_target"],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.patch_activation_readiness",
        {
            "candidates": candidates,
            "patch_activation_evidence": [_patch_activation_evidence()],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "candidate_blocked_by:missing_validation_target" in manifest[
        "blocked_reasons"
    ]
    assert manifest["patch_activation_ready"] is False


def test_prompt_mutation_lifecycle_manifest_blocks_missing_candidates(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch("rke_benchmark.prompt_mutation_lifecycle_manifest", {})

    assert manifest["manifest_status"] == "blocked_preflight"
    assert "candidate_consumption_manifest_not_ready" in manifest["blocked_reasons"]
    assert manifest["direct_prompt_write_allowed"] is False


def test_prompt_mutation_lifecycle_manifest_records_private_branch(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_lifecycle_manifest",
        {
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=["paper_trading_gate_pending"],
                )
            ]
        },
    )

    assert manifest["manifest_status"] == "ready_for_private_branch"
    assert manifest["direct_prompt_write_allowed"] is False
    assert manifest["rollback_required_before_promotion"] is True
    record = manifest["lifecycle_records"][0]
    assert record["candidate_action"] == "private_prompt_branch_after_blockers_clear"
    assert record["affected_agents"] == ["munger"]
    assert record["private_prompt_branch"].startswith("rke/pmut-1/")
    assert record["promotion_allowed"] is False
    assert "rollback" in record["fallback_rollback_rule"]
    assert (
        "prompts/mosaic/cohort_default/superinvestor/munger.zh.md"
        in record["overwrite_target_paths"]
    )


def test_prompt_mutation_lifecycle_manifest_keeps_refusal_out_of_prompt_branch(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_lifecycle_manifest",
        {"candidates": [_mutation_candidate()]},
    )

    assert manifest["manifest_status"] == "blocked_preflight"
    assert "refusal_only_no_prompt_branch_candidate" in manifest["blocked_reasons"]
    record = manifest["lifecycle_records"][0]
    assert record["candidate_action"] == "record_refusal_no_prompt_branch"
    assert record["private_prompt_branch"] == ""
    assert record["overwrite_target_paths"] == []
    assert "missing_pit_outcome" in record["blocked_by"]


def test_prompt_mutation_release_readiness_blocks_missing_release_check(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=[],
                )
            ]
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "release_check_missing" in manifest["blocked_reasons"]
    assert "prompt_version_id_missing" in manifest["blocked_reasons"]
    assert manifest["prompt_release_ready"] is False
    assert manifest["direct_prompt_write_allowed"] is False


def test_prompt_mutation_release_readiness_accepts_release_and_leak_drift(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {
            "candidates": candidates,
            "release_checks": [_prompt_release_check_for_candidates(candidates)],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["prompt_release_ready"] is True
    assert manifest["promotion_allowed"] is False
    record = manifest["release_records"][0]
    assert record["prompt_version_id"] == 42
    assert record["release_ready"] is True


def test_prompt_mutation_release_readiness_rejects_bool_prompt_version(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {
            "candidates": candidates,
            "release_checks": [
                _prompt_release_check_for_candidates(
                    candidates, prompt_version_id=True
                )
            ],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "prompt_version_id_missing" in manifest["blocked_reasons"]
    assert manifest["release_records"][0]["prompt_version_id"] is None
    assert manifest["prompt_release_ready"] is False


def test_prompt_mutation_release_readiness_blocks_mismatched_lifecycle_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    release_check = _prompt_release_check_for_candidates(
        candidates,
        private_prompt_branch="rke/wrong-branch",
        base_prompt_repo_revision="not-the-lifecycle-base",
        overwrite_target_paths=["prompts/mosaic/cohort_default/superinvestor/wrong.md"],
    )
    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {"candidates": candidates, "release_checks": [release_check]},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "private_prompt_branch_mismatch" in manifest["blocked_reasons"]
    assert "base_prompt_repo_revision_mismatch" in manifest["blocked_reasons"]
    assert "overwrite_target_paths_mismatch" in manifest["blocked_reasons"]
    assert manifest["prompt_release_ready"] is False


def test_prompt_mutation_release_readiness_blocks_cross_run_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {
            "benchmark_run_id": "bench-release-ready",
            "candidates": candidates,
            "release_checks": [
                _prompt_release_check_for_candidates(candidates, "other-run")
            ],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "release_check_benchmark_run_id_mismatch" in manifest["blocked_reasons"]
    assert manifest["prompt_release_ready"] is False


def test_prompt_mutation_release_readiness_blocks_candidate_blockers(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=["missing_pit_outcome"],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {
            "candidates": candidates,
            "release_checks": [_prompt_release_check_for_candidates(candidates)],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "candidate_blocked_by:missing_pit_outcome" in manifest["blocked_reasons"]
    assert manifest["prompt_release_ready"] is False


def test_prompt_mutation_release_readiness_requires_audit_version(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    release_check = _prompt_release_check_for_candidates(candidates)
    release_check.pop("audit_version_ref")

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_release_readiness",
        {"candidates": candidates, "release_checks": [release_check]},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "audit_version_ref_missing" in manifest["blocked_reasons"]
    assert manifest["prompt_release_ready"] is False


def test_prompt_mutation_rollback_readiness_blocks_missing_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_rollback_readiness",
        {
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=[],
                )
            ]
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "rollback_trigger_definition_missing" in manifest["blocked_reasons"]
    assert manifest["rollback_gate_ready"] is False
    assert manifest["promotion_allowed"] is False


def test_prompt_mutation_rollback_readiness_accepts_complete_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    benchmark_run_id = "bench-rollback-ready"
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_rollback_readiness",
        {
            "benchmark_run_id": benchmark_run_id,
            "candidates": candidates,
            "rollback_evidence": [
                _rollback_evidence_for_candidates(candidates, benchmark_run_id)
            ],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["rollback_gate_ready"] is True
    assert manifest["promotion_allowed"] is False
    record = manifest["rollback_records"][0]
    assert record["rollback_ready"] is True
    assert len(record["previous_prompt_hashes"]) == 2
    assert record["rollback_previous_prompt_hashes"] == record["previous_prompt_hashes"]


def test_prompt_mutation_rollback_readiness_blocks_missing_benchmark_run_id(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_rollback_readiness",
        {
            "candidates": candidates,
            "rollback_evidence": [_rollback_evidence_for_candidates(candidates)],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "benchmark_run_id_missing" in manifest["blocked_reasons"]
    assert manifest["rollback_gate_ready"] is False


def test_prompt_mutation_rollback_readiness_blocks_previous_hash_mismatch(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    rollback_evidence = _rollback_evidence_for_candidates(
        candidates, previous_prompt_hashes=["bad-hash"]
    )

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_rollback_readiness",
        {"candidates": candidates, "rollback_evidence": [rollback_evidence]},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "previous_prompt_hashes_mismatch" in manifest["blocked_reasons"]
    assert manifest["rollback_gate_ready"] is False


def test_prompt_mutation_rollback_readiness_blocks_cross_run_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_rollback_readiness",
        {
            "benchmark_run_id": "bench-rollback-ready",
            "candidates": candidates,
            "rollback_evidence": [
                _rollback_evidence_for_candidates(candidates, "other-run")
            ],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "rollback_evidence_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert manifest["rollback_gate_ready"] is False


def test_prompt_mutation_rollback_readiness_blocks_candidate_blockers(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=["missing_validation_target"],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.prompt_mutation_rollback_readiness",
        {
            "candidates": candidates,
            "rollback_evidence": [_rollback_evidence_for_candidates(candidates)],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert (
        "candidate_blocked_by:missing_validation_target"
        in manifest["blocked_reasons"]
    )
    assert manifest["rollback_gate_ready"] is False


def test_shadow_replay_readiness_blocks_missing_proof(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.shadow_replay_readiness",
        {"benchmark_run_id": "bench-shadow-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "all_agent_prompt_provenance_not_ready" in manifest["blocked_reasons"]
    assert "benchmark_evidence_not_ready" in manifest["blocked_reasons"]
    assert "darwinian_autoresearch_input_not_ready" in manifest["blocked_reasons"]
    assert "prompt_mutation_release_not_ready" in manifest["blocked_reasons"]
    assert "rollback_readiness_not_ready" in manifest["blocked_reasons"]
    assert manifest["shadow_replay_ready"] is False
    assert manifest["paper_trading_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_shadow_replay_blocks_context_without_runtime_ranking_proof(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-shadow-missing-runtime-proof",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "d" * 64,
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.shadow_replay_readiness",
        {
            "benchmark_run_id": "bench-shadow-missing-runtime-proof",
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-shadow-missing-runtime-proof"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-shadow-missing-runtime-proof"
            ),
        },
    )

    assert "ranking_policy_id_missing" in manifest["blocked_reasons"]
    assert "retrieval_rank_missing" in manifest["blocked_reasons"]
    assert "priority_bucket_missing" in manifest["blocked_reasons"]
    assert "truncation_audit_missing" in manifest["blocked_reasons"]
    assert manifest["shadow_replay_ready"] is False


def test_shadow_replay_readiness_accepts_ready_shadow_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-shadow-ready",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "d" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-shadow"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.shadow_replay_readiness",
        {
            "benchmark_run_id": "bench-shadow-ready",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-shadow-ready"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-shadow-ready"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs("bench-shadow-ready"),
            "manual_review": _manual_review("bench-shadow-ready"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-shadow-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-shadow-ready"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(candidates, "bench-shadow-ready")
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-shadow-ready",
                    rollback_trigger_definition="shadow replay regression",
                    monitor_output_ref="monitor-shadow-ready",
                    post_rollback_verification_ref="verify-shadow-ready",
                )
            ],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["prompt_provenance_readiness_status"] == "ready"
    assert manifest["prompt_release_readiness_status"] == "ready"
    assert manifest["shadow_replay_ready"] is True
    assert manifest["paper_trading_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["rke_context_hash_count"] == 1
    assert manifest["ranking_policy_id_counts"] == {
        "rke_agent_research_context_rank_v1": 1
    }
    assert manifest["retrieval_rank_count"] == 1
    assert manifest["priority_bucket_counts"] == {"high": 1}
    assert manifest["truncation_audit_count"] == 1
    assert manifest["current_data_confirmed_count"] == 1


def test_shadow_replay_blocks_partial_current_data_confirmation(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-shadow-partial-current-data",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "d" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-shadow"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                },
                {
                    "agent": "burry",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000002.SZ"},
                    "rke_context_hash": "e" * 64,
                    **_runtime_context_proof(2),
                    "report_claim_refs": ["forecast_claim:stock-000002-shadow"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": False,
                },
            ],
        },
    )

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.shadow_replay_readiness",
        {
            "benchmark_run_id": "bench-shadow-partial-current-data",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-shadow-partial-current-data"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-shadow-partial-current-data"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-shadow-partial-current-data"
            ),
            "manual_review": _manual_review("bench-shadow-partial-current-data"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-shadow-partial-current-data"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-shadow-partial-current-data"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(
                    candidates, "bench-shadow-partial-current-data"
                )
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-shadow-partial-current-data",
                    rollback_trigger_definition="shadow replay regression",
                    monitor_output_ref="monitor-shadow-partial-current-data",
                    post_rollback_verification_ref="verify-shadow-partial-current-data",
                )
            ],
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "current_data_confirmation_missing" in manifest["blocked_reasons"]
    assert manifest["rke_context_hash_count"] == 2
    assert manifest["current_data_confirmed_count"] == 1


def test_paper_trading_readiness_blocks_missing_shadow_and_plan(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.paper_trading_readiness",
        {"benchmark_run_id": "bench-paper-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "shadow_replay_not_ready" in manifest["blocked_reasons"]
    assert "paper_trading_plan_ref_missing" in manifest["blocked_reasons"]
    assert manifest["paper_trading_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_paper_trading_readiness_accepts_reviewed_shadow_plan(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-paper-ready",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "e" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-paper"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.paper_trading_readiness",
        {
            "benchmark_run_id": "bench-paper-ready",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-paper-ready"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-paper-ready"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs("bench-paper-ready"),
            "manual_review": _manual_review("bench-paper-ready"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-paper-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-paper-ready"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(candidates, "bench-paper-ready")
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-paper-ready",
                    rollback_trigger_definition="paper trading risk breach",
                    monitor_output_ref="monitor-paper-ready",
                    post_rollback_verification_ref="verify-paper-ready",
                )
            ],
            "paper_trading_plan": _paper_trading_plan("bench-paper-ready"),
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["shadow_replay_status"] == "ready"
    assert manifest["paper_trading_allowed"] is True
    assert manifest["promotion_allowed"] is False


def test_paper_trading_readiness_blocks_cross_run_plan(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-paper-ready",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "e" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-paper"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.paper_trading_readiness",
        {
            "benchmark_run_id": "bench-paper-ready",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-paper-ready"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-paper-ready"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs("bench-paper-ready"),
            "manual_review": _manual_review("bench-paper-ready"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-paper-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-paper-ready"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(candidates, "bench-paper-ready")
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-paper-ready",
                    rollback_trigger_definition="paper trading risk breach",
                    monitor_output_ref="monitor-paper-ready",
                    post_rollback_verification_ref="verify-paper-ready",
                )
            ],
            "paper_trading_plan": _paper_trading_plan("other-run"),
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "paper_trading_plan_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert manifest["paper_trading_allowed"] is False


def test_paper_trading_readiness_blocks_unapproved_operator_review(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-paper-unapproved",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "e" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-paper"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.paper_trading_readiness",
        {
            "benchmark_run_id": "bench-paper-unapproved",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-paper-unapproved"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-paper-unapproved"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-paper-unapproved"
            ),
            "manual_review": _manual_review("bench-paper-unapproved"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-paper-unapproved"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-paper-unapproved"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(
                    candidates, "bench-paper-unapproved"
                )
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-paper-unapproved",
                    rollback_trigger_definition="paper trading risk breach",
                    monitor_output_ref="monitor-paper-unapproved",
                    post_rollback_verification_ref="verify-paper-unapproved",
                )
            ],
            "paper_trading_plan": _paper_trading_plan(
                "bench-paper-unapproved", operator_review_approved=False
            ),
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "operator_review_not_approved" in manifest["blocked_reasons"]
    assert manifest["paper_trading_plan"]["operator_review_approved"] is False
    assert manifest["paper_trading_allowed"] is False


def test_promotion_decision_readiness_blocks_missing_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.promotion_decision_readiness",
        {"benchmark_run_id": "bench-promotion-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "paper_trading_not_ready" in manifest["blocked_reasons"]
    assert "paper_trading_result_ref_missing" in manifest["blocked_reasons"]
    assert manifest["ready_for_operator_promotion_decision"] is False
    assert manifest["production_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_promotion_decision_readiness_blocks_unapproved_second_review(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.promotion_decision_readiness",
        {
            "benchmark_run_id": "bench-promotion-unapproved",
            "promotion_evidence": _promotion_evidence(
                "bench-promotion-unapproved", second_review_approved=False
            ),
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "second_review_not_approved" in manifest["blocked_reasons"]
    assert manifest["promotion_evidence"]["second_review_approved"] is False
    assert manifest["ready_for_operator_promotion_decision"] is False


def test_promotion_decision_readiness_accepts_reviewed_paper_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-promotion-ready",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "f" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-promotion"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.promotion_decision_readiness",
        {
            "benchmark_run_id": "bench-promotion-ready",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-promotion-ready"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-promotion-ready"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-promotion-ready"
            ),
            "manual_review": _manual_review("bench-promotion-ready"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-promotion-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-promotion-ready"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(
                    candidates, "bench-promotion-ready"
                )
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-promotion-ready",
                    rollback_trigger_definition="promotion monitor breach",
                    monitor_output_ref="monitor-promotion-ready",
                    post_rollback_verification_ref="verify-promotion-ready",
                )
            ],
            "paper_trading_plan": _paper_trading_plan("bench-promotion-ready"),
            "promotion_evidence": _promotion_evidence("bench-promotion-ready"),
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["paper_trading_status"] == "ready"
    assert manifest["promotion_evidence"]["second_review_approved"] is True
    assert manifest["ready_for_operator_promotion_decision"] is True
    assert manifest["production_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_promotion_decision_readiness_blocks_cross_run_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-promotion-ready",
            "rows": [
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "f" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:stock-000001-promotion"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )
    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]

    manifest = dispatch(
        "rke_benchmark.promotion_decision_readiness",
        {
            "benchmark_run_id": "bench-promotion-ready",
            "all_agent_prompt_release_checks": _all_prompt_release_checks(
                preflight["rows"], "bench-promotion-ready"
            ),
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-promotion-ready"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-promotion-ready"
            ),
            "manual_review": _manual_review("bench-promotion-ready"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-promotion-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-promotion-ready"
            ),
            "candidates": candidates,
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(
                    candidates, "bench-promotion-ready"
                )
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-promotion-ready",
                    rollback_trigger_definition="promotion monitor breach",
                    monitor_output_ref="monitor-promotion-ready",
                    post_rollback_verification_ref="verify-promotion-ready",
                )
            ],
            "paper_trading_plan": _paper_trading_plan("bench-promotion-ready"),
            "promotion_evidence": _promotion_evidence("other-run"),
        },
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "promotion_evidence_benchmark_run_id_mismatch" in manifest[
        "blocked_reasons"
    ]
    assert manifest["ready_for_operator_promotion_decision"] is False


def test_delivery_readiness_blocks_missing_evidence(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert manifest["condition_count"] == 12
    assert manifest["ready_condition_count"] == 0
    assert manifest["delivery_ready"] is False
    assert any(
        reason.startswith("all_agent_prompt_provenance:")
        for reason in manifest["blocked_reasons"]
    )
    prompt_condition = next(
        condition
        for condition in manifest["conditions"]
        if condition["condition_id"] == "all_agent_prompt_provenance"
    )
    benchmark_condition = next(
        condition
        for condition in manifest["conditions"]
        if condition["condition_id"] == "fixed_episode_benchmark"
    )
    assert prompt_condition["evidence_summary"]["prompt_source_status"][
        "blocked_reason"
    ] == "private_prompt_unavailable"
    assert benchmark_condition["evidence_summary"]["prompt_source_status"][
        "blocked_reason"
    ] == "private_prompt_unavailable"
    assert manifest["production_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_record_delivery_evidence_blocks_private_fields(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    result = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-private",
            "benchmark_evidence_refs": {"source_url": "https://private/report.pdf"},
        },
    )

    assert result["record_status"] == "blocked"
    assert result["recorded_key_count"] == 0
    assert result["recorded_context_key_count"] == 0
    assert result["failures"]


def test_delivery_evidence_audit_reports_recorded_and_missing_keys(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    missing = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-audit"},
    )
    dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-audit",
            "paired_output_count": 1275,
            "manual_review": _manual_review("bench-delivery-audit"),
        },
    )
    partial = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-audit"},
    )

    assert missing["evidence_status"] == "missing"
    assert missing["recorded_key_count"] == 0
    assert missing["recorded_context_keys"] == []
    assert partial["evidence_status"] == "partial"
    assert partial["recorded_keys"] == ["manual_review", "paired_output_count"]
    assert partial["recorded_key_count"] == 2
    assert "benchmark_evidence_refs" in partial["missing_keys"]
    assert partial["delivery_readiness_can_load"] is True


def test_delivery_evidence_audit_keeps_context_out_of_proof_keys(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    path = project_root / ".mosaic" / "rke" / "all_agent_evolution"
    path.mkdir(parents=True)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    (path / "delivery_evidence.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "rke_delivery_evidence_v1",
                "benchmark_run_id": "bench-delivery-context-only",
                "evidence": {"cohort": "cohort_context_only"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-context-only"},
    )
    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-context-only"},
    )

    assert audit["cohort"] == "cohort_context_only"
    assert audit["evidence_status"] == "missing"
    assert audit["recorded_context_keys"] == ["cohort"]
    assert audit["recorded_keys"] == []
    assert audit["recorded_key_count"] == 0
    assert audit["delivery_readiness_can_load"] is False
    assert manifest["cohort"] == "cohort_context_only"
    assert manifest["recorded_evidence_loaded"] is False


def test_delivery_evidence_audit_records_prompt_source_status_context(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    record = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-source-status",
            "prompt_source_status": {
                "ready": False,
                "blocked_reason": "private_prompt_repo_dirty",
                "resolved_source": "private_repo",
                "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                "prompt_repo_revision": "a" * 40,
                "prompt_repo_dirty_count": 406,
            },
        },
    )
    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-source-status"},
    )

    assert record["record_status"] == "recorded"
    assert record["recorded_key_count"] == 0
    assert record["recorded_context_key_count"] == 1
    assert audit["evidence_status"] == "missing"
    assert audit["recorded_context_keys"] == ["prompt_source_status"]
    assert audit["recorded_keys"] == []
    assert audit["recorded_prompt_source_status"]["blocked_reason"] == (
        "private_prompt_repo_dirty"
    )
    assert audit["delivery_readiness_can_load"] is False


def test_delivery_evidence_store_blocks_wrong_context_types(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    evidence_dir = project_root / ".mosaic" / "rke" / "all_agent_evolution"
    evidence_dir.mkdir(parents=True)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    record = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-context-type",
            "cohort": 123,
            "prompt_source_status": [],
        },
    )
    (evidence_dir / "delivery_evidence.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "rke_delivery_evidence_v1",
                "benchmark_run_id": "bench-delivery-context-type",
                "evidence": {"cohort": "   "},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-context-type"},
    )

    assert record["record_status"] == "blocked"
    assert "invalid delivery context type cohort: expected str" in record["failures"]
    assert (
        "empty delivery context values prompt_source_status" in record["failures"]
    )
    assert audit["evidence_status"] == "blocked"
    assert audit["recorded_context_keys"] == []
    assert audit["failures"] == ["line 1: empty delivery context values cohort"]


def test_delivery_evidence_records_merge_incrementally(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-incremental",
            "paired_output_count": 1275,
        },
    )
    dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-incremental",
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-delivery-incremental"
            ),
            "manual_review": _manual_review("bench-delivery-incremental"),
        },
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-incremental"},
    )
    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-incremental"},
    )

    assert audit["recorded_keys"] == [
        "benchmark_evidence_refs",
        "manual_review",
        "paired_output_count",
    ]
    assert all(
        "fixed_episode_benchmark:paired_output_count_below_required" != reason
        for reason in manifest["blocked_reasons"]
    )


def test_delivery_readiness_uses_recorded_cohort(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    record = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-cohort",
            "cohort": "cohort_custom",
            "paired_output_count": 1275,
        },
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-cohort"},
    )
    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-cohort"},
    )

    assert record["recorded_key_count"] == 1
    assert record["recorded_context_key_count"] == 1
    assert audit["cohort"] == "cohort_custom"
    assert manifest["cohort"] == "cohort_custom"
    assert audit["recorded_context_keys"] == ["cohort"]
    assert "cohort" not in audit["recorded_keys"]


def test_delivery_evidence_store_blocks_empty_proof_values(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    evidence_dir = project_root / ".mosaic" / "rke" / "all_agent_evolution"
    evidence_dir.mkdir(parents=True)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    record = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-empty",
            "all_agent_prompt_release_checks": [],
            "paired_output_count": 1275,
            "model_config_output_counts": {},
        },
    )
    (evidence_dir / "delivery_evidence.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "rke_delivery_evidence_v1",
                "benchmark_run_id": "bench-delivery-empty",
                "evidence": {
                    "paired_output_count": 1275,
                    "model_config_output_counts": {},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-empty"},
    )

    assert record["record_status"] == "blocked"
    assert record["recorded_key_count"] == 0
    assert "empty delivery evidence values all_agent_prompt_release_checks" in record[
        "failures"
    ][0]
    assert audit["evidence_status"] == "blocked"
    assert audit["recorded_keys"] == []
    assert any(
        "empty delivery evidence values model_config_output_counts" in failure
        for failure in audit["failures"]
    )
    assert audit["delivery_readiness_status"] == "blocked_preflight"
    assert "delivery_evidence_store:line 1: empty delivery evidence values model_config_output_counts" in audit[
        "delivery_blocked_reasons"
    ]


def test_delivery_evidence_store_blocks_wrong_proof_types(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    evidence_dir = project_root / ".mosaic" / "rke" / "all_agent_evolution"
    evidence_dir.mkdir(parents=True)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    record = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-wrong-type",
            "manual_review": True,
            "candidates": {"candidate": "wrong-shape"},
        },
    )
    (evidence_dir / "delivery_evidence.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "rke_delivery_evidence_v1",
                "benchmark_run_id": "bench-delivery-wrong-type",
                "evidence": {"paired_output_count": False},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-wrong-type"},
    )

    assert record["record_status"] == "blocked"
    assert "invalid delivery evidence type manual_review: expected dict" in record[
        "failures"
    ]
    assert "invalid delivery evidence type candidates: expected list" in record[
        "failures"
    ]
    assert audit["evidence_status"] == "blocked"
    assert audit["recorded_keys"] == []
    assert audit["failures"] == [
        "line 1: invalid delivery evidence type paired_output_count: expected int"
    ]


def test_delivery_evidence_store_rejects_schema_mismatch(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    evidence_dir = project_root / ".mosaic" / "rke" / "all_agent_evolution"
    evidence_dir.mkdir(parents=True)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    rows = [
        {
            "schema_version": "legacy_delivery_evidence_v0",
            "benchmark_run_id": "other-run",
            "evidence": {"paired_output_count": 1275},
        },
        {
            "schema_version": "legacy_delivery_evidence_v0",
            "benchmark_run_id": "bench-delivery-schema",
            "evidence": {"paired_output_count": 1275},
        },
    ]
    (evidence_dir / "delivery_evidence.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-schema"},
    )

    assert audit["evidence_status"] == "blocked"
    assert audit["recorded_keys"] == []
    assert audit["failures"] == ["line 2: schema_version mismatch"]
    assert "delivery_evidence_store:line 2: schema_version mismatch" in audit[
        "delivery_blocked_reasons"
    ]


def test_delivery_readiness_loads_recorded_private_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    record = dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-recorded",
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-delivery-recorded"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-delivery-recorded"
            ),
            "manual_review": _manual_review("bench-delivery-recorded"),
        },
    )

    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-recorded"},
    )

    assert record["record_status"] == "recorded"
    assert record["recorded_key_count"] == 5
    assert record["recorded_context_key_count"] == 0
    assert manifest["recorded_evidence_loaded"] is True
    assert all(
        "fixed_episode_benchmark:paired_output_count_below_required" != reason
        for reason in manifest["blocked_reasons"]
    )


def test_delivery_readiness_accepts_all_no_write_gate_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
    preflight = dispatch("prompts.preflight", {"langs": ["zh", "en"]})
    all_prompt_release_checks = _all_prompt_release_checks(
        preflight["rows"], "bench-delivery-ready"
    )
    dispatch(
        "rke_benchmark.capture_agent_claim_footprints",
        {
            "benchmark_run_id": "bench-delivery-ready",
            "rows": [
                {
                    "agent": "dollar",
                    "as_of_date": "2026-06-18",
                    "claim_type": "macro_series_claim",
                    "target": {"target_type": "macro_series", "target_id": "USDCNY"},
                    "rke_context_hash": "a" * 64,
                    **_runtime_context_proof(1),
                    "report_claim_refs": ["forecast_claim:macro-usdcny-001"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "semiconductor",
                    "as_of_date": "2026-06-18",
                    "claim_type": "sector_claim",
                    "target": {"target_type": "sector", "sector": "semiconductor"},
                    "rke_context_hash": "b" * 64,
                    **_runtime_context_proof(2),
                    "report_claim_refs": ["forecast_claim:sector-semi-delivery"],
                    "current_data_confirmed": True,
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "c" * 64,
                    **_runtime_context_proof(3),
                    "report_claim_refs": ["forecast_claim:stock-000001-delivery"],
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                },
                {
                    "agent": "cio",
                    "as_of_date": "2026-06-18",
                    "claim_type": "portfolio_action_claim",
                    "target": {"target_type": "portfolio", "target_id": "cn_equity"},
                    "rke_context_hash": "d" * 64,
                    **_runtime_context_proof(4),
                    "report_claim_refs": ["forecast_claim:portfolio-cn-equity-delivery"],
                    "current_data_confirmed": True,
                },
            ],
        },
    )

    candidates = [
        _mutation_candidate(
            candidate_type="stock_prior_recipe_rule_candidate",
            target_scope="stock",
            target_component="superinvestor.munger",
            blocked_by=[],
        )
    ]
    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {
            "benchmark_run_id": "bench-delivery-ready",
            "all_agent_prompt_release_checks": all_prompt_release_checks,
            "paired_output_count": 1275,
            "model_config_output_counts": _model_config_output_counts(),
            "benchmark_quality_summary": _benchmark_quality_summary(
                "bench-delivery-ready"
            ),
            "benchmark_evidence_refs": _benchmark_evidence_refs(
                "bench-delivery-ready"
            ),
            "manual_review": _manual_review("bench-delivery-ready"),
            "profile_evidence": _profile_evidence("bench-delivery-ready"),
            "downstream_outcome_metrics": _downstream_outcome_metrics(
                "bench-delivery-ready"
            ),
            "prompt_mutation_provenance": _prompt_mutation_provenance(
                "bench-delivery-ready"
            ),
            "darwinian_autoresearch_consumption_evidence": (
                _darwinian_consumption_evidence("bench-delivery-ready")
            ),
            "candidates": candidates,
            "patch_activation_evidence": [
                _patch_activation_evidence("bench-delivery-ready")
            ],
            "prompt_mutation_release_checks": [
                _prompt_release_check_for_candidates(
                    candidates,
                    "bench-delivery-ready",
                    prompt_version_id=51,
                    verify_release_ref="verify-mutation-delivery",
                    leak_drift_check_ref="leak-mutation-delivery",
                )
            ],
            "rollback_evidence": [
                _rollback_evidence_for_candidates(
                    candidates,
                    "bench-delivery-ready",
                    rollback_trigger_definition="delivery monitor breach",
                    monitor_output_ref="monitor-delivery",
                    post_rollback_verification_ref="verify-delivery",
                )
            ],
            "paper_trading_plan": _paper_trading_plan("bench-delivery-ready"),
            "promotion_evidence": _promotion_evidence("bench-delivery-ready"),
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["ready_condition_count"] == manifest["condition_count"]
    assert manifest["delivery_ready"] is True
    assert manifest["production_allowed"] is False
    assert manifest["promotion_allowed"] is False
