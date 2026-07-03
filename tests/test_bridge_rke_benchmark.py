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
    release_checks = [
        {
            "agent": row["agent"],
            "lang": row["lang"],
            "prompt_version_id": index,
            "prompt_sha256": row["prompt_sha256"],
            "verify_release_ref": f"verify-release-{index}",
            "leak_drift_check_ref": f"leak-drift-{index}",
            "verify_release_passed": True,
            "leak_drift_passed": True,
        }
        for index, row in enumerate(preflight["rows"], 1)
    ]

    result = dispatch(
        "rke_benchmark.all_agent_prompt_provenance_readiness",
        {"release_checks": release_checks},
    )

    assert result["readiness_status"] == "ready"
    assert result["agent_count"] == 25
    assert result["prompt_row_count"] == 50
    assert result["ready_prompt_row_count"] == 50
    assert result["release_check_count"] == 50
    assert result["all_agent_prompt_provenance_ready"] is True
    assert result["fallback_used"] is False


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
    assert "private_prompt_preflight_not_ready" in result["blocked_reasons"]
    assert "paired_output_count_below_required" in result["blocked_reasons"]
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
            "evidence_refs": {
                "paired_output_manifest_ref": "bench-ready-paired-output-manifest",
                "output_schema_validation_report_ref": "bench-ready-schema-report",
                "deterministic_score_table_ref": "bench-ready-score-table",
                "investment_outcome_table_ref": "bench-ready-investment-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
        },
    )

    assert result["evidence_status"] == "ready"
    assert result["blocked_reasons"] == []
    assert result["paired_output_count"] == result["required_paired_output_count"]
    assert result["manual_review"]["decision"] == "approved"
    assert result["promotion_allowed"] is False


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
                },
                {
                    "agent": "semiconductor",
                    "as_of_date": "2026-06-18",
                    "claim_type": "sector_claim",
                    "target": {"target_type": "sector", "sector": "semiconductor"},
                    "rke_context_hash": "b" * 64,
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "c" * 64,
                },
                {
                    "agent": "cio",
                    "as_of_date": "2026-06-18",
                    "claim_type": "portfolio_action_claim",
                    "target": {"target_type": "portfolio", "target_id": "cn_equity"},
                    "rke_context_hash": "d" * 64,
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.agent_profile_evolution_readiness",
        {
            "benchmark_run_id": "bench-profile-ready",
            "profile_evidence": {
                "profile_update_ref": "profile-update-ready",
                "evolution_input_ref": "evolution-input-ready",
                "no_source_prose_audit_ref": "no-source-prose-ready",
            },
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
    assert manifest["privacy_scan"]["forbidden_field_violation_count"] == 0
    assert manifest["profile_evolution_ready"] is True
    assert manifest["production_signal_allowed"] is False


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
            ],
            "release_checks": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "prompt_version_id": 42,
                    "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                    "prompt_commit_hash": "a" * 40,
                    "prompt_sha256": "b" * 64,
                    "verify_release_ref": "verify-release-1",
                    "leak_drift_check_ref": "leak-drift-1",
                    "verify_release_passed": True,
                    "leak_drift_passed": True,
                    "release_ready": True,
                }
            ],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["prompt_release_ready"] is True
    assert manifest["promotion_allowed"] is False
    record = manifest["release_records"][0]
    assert record["prompt_version_id"] == 42
    assert record["release_ready"] is True


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
            ],
            "rollback_evidence": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "rollback_trigger_definition": "manual review or monitor breach",
                    "rollback_command_or_procedure": "restore previous prompt commit",
                    "monitor_output_ref": "monitor-run-1",
                    "post_rollback_verification_ref": "verify-run-1",
                }
            ],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["rollback_gate_ready"] is True
    assert manifest["promotion_allowed"] is False
    record = manifest["rollback_records"][0]
    assert record["rollback_ready"] is True
    assert len(record["previous_prompt_hashes"]) == 2


def test_shadow_replay_readiness_blocks_missing_proof(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.shadow_replay_readiness",
        {"benchmark_run_id": "bench-shadow-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert "benchmark_evidence_not_ready" in manifest["blocked_reasons"]
    assert "darwinian_autoresearch_input_not_ready" in manifest["blocked_reasons"]
    assert "rollback_readiness_not_ready" in manifest["blocked_reasons"]
    assert manifest["shadow_replay_ready"] is False
    assert manifest["paper_trading_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_shadow_replay_readiness_accepts_ready_shadow_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
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
                    "retrieval_rank": 1,
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.shadow_replay_readiness",
        {
            "benchmark_run_id": "bench-shadow-ready",
            "paired_output_count": 1275,
            "benchmark_evidence_refs": {
                "paired_output_manifest_ref": "bench-shadow-paired",
                "output_schema_validation_report_ref": "bench-shadow-schema",
                "deterministic_score_table_ref": "bench-shadow-scores",
                "investment_outcome_table_ref": "bench-shadow-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
            "downstream_outcome_metrics": {
                "risk_adjusted_return": 0.11,
                "alpha": 0.02,
                "max_drawdown": -0.03,
                "turnover": 0.5,
                "cost_bps": 8,
            },
            "prompt_mutation_provenance": {
                "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                "prompt_repo_revision": "a" * 40,
                "prompt_sha256": "b" * 64,
            },
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=[],
                )
            ],
            "rollback_evidence": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "rollback_trigger_definition": "shadow replay regression",
                    "rollback_command_or_procedure": "restore previous prompt commit",
                    "monitor_output_ref": "monitor-shadow-ready",
                    "post_rollback_verification_ref": "verify-shadow-ready",
                }
            ],
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["shadow_replay_ready"] is True
    assert manifest["paper_trading_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["rke_context_hash_count"] == 1
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
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.paper_trading_readiness",
        {
            "benchmark_run_id": "bench-paper-ready",
            "paired_output_count": 1275,
            "benchmark_evidence_refs": {
                "paired_output_manifest_ref": "bench-paper-paired",
                "output_schema_validation_report_ref": "bench-paper-schema",
                "deterministic_score_table_ref": "bench-paper-scores",
                "investment_outcome_table_ref": "bench-paper-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
            "downstream_outcome_metrics": {
                "risk_adjusted_return": 0.11,
                "alpha": 0.02,
                "max_drawdown": -0.03,
                "turnover": 0.5,
                "cost_bps": 8,
            },
            "prompt_mutation_provenance": {
                "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                "prompt_repo_revision": "a" * 40,
                "prompt_sha256": "b" * 64,
            },
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=[],
                )
            ],
            "rollback_evidence": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "rollback_trigger_definition": "paper trading risk breach",
                    "rollback_command_or_procedure": "restore previous prompt commit",
                    "monitor_output_ref": "monitor-paper-ready",
                    "post_rollback_verification_ref": "verify-paper-ready",
                }
            ],
            "paper_trading_plan": {
                "paper_trading_plan_ref": "paper-plan-ready",
                "risk_limit_ref": "paper-risk-limits",
                "stop_loss_or_rollback_ref": "paper-stop-loss",
                "operator_review_timestamp": "2026-07-03T12:30:00Z",
            },
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["shadow_replay_status"] == "ready"
    assert manifest["paper_trading_allowed"] is True
    assert manifest["promotion_allowed"] is False


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


def test_promotion_decision_readiness_accepts_reviewed_paper_evidence(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    private_repo = _private_prompt_repo(tmp_path)
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    monkeypatch.setenv("MOSAIC_PROMPTS_REPO", str(private_repo))
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
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                }
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.promotion_decision_readiness",
        {
            "benchmark_run_id": "bench-promotion-ready",
            "paired_output_count": 1275,
            "benchmark_evidence_refs": {
                "paired_output_manifest_ref": "bench-promotion-paired",
                "output_schema_validation_report_ref": "bench-promotion-schema",
                "deterministic_score_table_ref": "bench-promotion-scores",
                "investment_outcome_table_ref": "bench-promotion-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
            "downstream_outcome_metrics": {
                "risk_adjusted_return": 0.11,
                "alpha": 0.02,
                "max_drawdown": -0.03,
                "turnover": 0.5,
                "cost_bps": 8,
            },
            "prompt_mutation_provenance": {
                "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                "prompt_repo_revision": "a" * 40,
                "prompt_sha256": "b" * 64,
            },
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=[],
                )
            ],
            "rollback_evidence": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "rollback_trigger_definition": "promotion monitor breach",
                    "rollback_command_or_procedure": "restore previous prompt commit",
                    "monitor_output_ref": "monitor-promotion-ready",
                    "post_rollback_verification_ref": "verify-promotion-ready",
                }
            ],
            "paper_trading_plan": {
                "paper_trading_plan_ref": "paper-plan-promotion",
                "risk_limit_ref": "paper-risk-promotion",
                "stop_loss_or_rollback_ref": "paper-stop-promotion",
                "operator_review_timestamp": "2026-07-03T12:30:00Z",
            },
            "promotion_evidence": {
                "paper_trading_result_ref": "paper-results-promotion",
                "monitor_summary_ref": "monitor-summary-promotion",
                "second_review_timestamp": "2026-07-03T13:00:00Z",
                "lockbox_decision_ref": "lockbox-promotion",
                "decision": "approved_for_promotion_review",
            },
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["paper_trading_status"] == "ready"
    assert manifest["ready_for_operator_promotion_decision"] is True
    assert manifest["production_allowed"] is False
    assert manifest["promotion_allowed"] is False


def test_delivery_readiness_blocks_missing_evidence(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))

    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-missing"},
    )

    assert manifest["readiness_status"] == "blocked_preflight"
    assert manifest["condition_count"] == 10
    assert manifest["ready_condition_count"] == 0
    assert manifest["delivery_ready"] is False
    assert any(
        reason.startswith("all_agent_prompt_provenance:")
        for reason in manifest["blocked_reasons"]
    )
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
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
        },
    )
    partial = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-audit"},
    )

    assert missing["evidence_status"] == "missing"
    assert missing["recorded_key_count"] == 0
    assert partial["evidence_status"] == "partial"
    assert partial["recorded_keys"] == ["manual_review", "paired_output_count"]
    assert "benchmark_evidence_refs" in partial["missing_keys"]
    assert partial["delivery_readiness_can_load"] is True


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
            "benchmark_evidence_refs": {
                "paired_output_manifest_ref": "recorded-paired",
                "output_schema_validation_report_ref": "recorded-schema",
                "deterministic_score_table_ref": "recorded-scores",
                "investment_outcome_table_ref": "recorded-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
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
    dispatch(
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

    assert audit["cohort"] == "cohort_custom"
    assert manifest["cohort"] == "cohort_custom"
    assert "cohort" in audit["recorded_keys"]


def test_delivery_evidence_audit_reports_readiness_when_keys_complete(
    tmp_path: Path, monkeypatch
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("MOSAIC_REPO_ROOT", str(project_root))
    dispatch(
        "rke_benchmark.record_delivery_evidence",
        {
            "benchmark_run_id": "bench-delivery-key-complete",
            "all_agent_prompt_release_checks": [],
            "paired_output_count": 1275,
            "benchmark_evidence_refs": {},
            "manual_review": {},
            "profile_evidence": {},
            "downstream_outcome_metrics": {},
            "prompt_mutation_provenance": {},
            "candidates": [],
            "prompt_mutation_release_checks": [],
            "rollback_evidence": [],
            "paper_trading_plan": {},
            "promotion_evidence": {},
        },
    )

    audit = dispatch(
        "rke_benchmark.delivery_evidence_audit",
        {"benchmark_run_id": "bench-delivery-key-complete"},
    )

    assert audit["evidence_status"] == "complete"
    assert audit["delivery_readiness_status"] == "blocked_preflight"
    assert audit["condition_count"] == 10
    assert audit["ready_condition_count"] < audit["condition_count"]
    assert audit["delivery_blocked_reasons"]


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
            "benchmark_evidence_refs": {
                "paired_output_manifest_ref": "recorded-paired",
                "output_schema_validation_report_ref": "recorded-schema",
                "deterministic_score_table_ref": "recorded-scores",
                "investment_outcome_table_ref": "recorded-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
        },
    )

    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {"benchmark_run_id": "bench-delivery-recorded"},
    )

    assert record["record_status"] == "recorded"
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
    all_prompt_release_checks = [
        {
            "agent": row["agent"],
            "lang": row["lang"],
            "prompt_version_id": index,
            "prompt_sha256": row["prompt_sha256"],
            "verify_release_ref": f"verify-all-{index}",
            "leak_drift_check_ref": f"leak-all-{index}",
            "verify_release_passed": True,
            "leak_drift_passed": True,
        }
        for index, row in enumerate(preflight["rows"], 1)
    ]
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
                    "current_data_confirmed": True,
                },
                {
                    "agent": "semiconductor",
                    "as_of_date": "2026-06-18",
                    "claim_type": "sector_claim",
                    "target": {"target_type": "sector", "sector": "semiconductor"},
                    "rke_context_hash": "b" * 64,
                },
                {
                    "agent": "munger",
                    "as_of_date": "2026-06-18",
                    "claim_type": "style_candidate_claim",
                    "target": {"target_type": "stock", "ticker": "000001.SZ"},
                    "rke_context_hash": "c" * 64,
                    "rke_prior_usage_quality": "used_ranked_prior",
                    "current_data_confirmed": True,
                },
                {
                    "agent": "cio",
                    "as_of_date": "2026-06-18",
                    "claim_type": "portfolio_action_claim",
                    "target": {"target_type": "portfolio", "target_id": "cn_equity"},
                    "rke_context_hash": "d" * 64,
                },
            ],
        },
    )

    manifest = dispatch(
        "rke_benchmark.delivery_readiness",
        {
            "benchmark_run_id": "bench-delivery-ready",
            "all_agent_prompt_release_checks": all_prompt_release_checks,
            "paired_output_count": 1275,
            "benchmark_evidence_refs": {
                "paired_output_manifest_ref": "bench-delivery-paired",
                "output_schema_validation_report_ref": "bench-delivery-schema",
                "deterministic_score_table_ref": "bench-delivery-scores",
                "investment_outcome_table_ref": "bench-delivery-outcomes",
            },
            "manual_review": {
                "decision": "approved",
                "reviewer_timestamp": "2026-07-03T12:00:00Z",
            },
            "profile_evidence": {
                "profile_update_ref": "profile-delivery",
                "evolution_input_ref": "evolution-delivery",
                "no_source_prose_audit_ref": "no-source-delivery",
            },
            "downstream_outcome_metrics": {
                "risk_adjusted_return": 0.11,
                "alpha": 0.02,
                "max_drawdown": -0.03,
                "turnover": 0.5,
                "cost_bps": 8,
            },
            "prompt_mutation_provenance": {
                "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                "prompt_repo_revision": "a" * 40,
                "prompt_sha256": "b" * 64,
            },
            "candidates": [
                _mutation_candidate(
                    candidate_type="stock_prior_recipe_rule_candidate",
                    target_scope="stock",
                    target_component="superinvestor.munger",
                    blocked_by=[],
                )
            ],
            "prompt_mutation_release_checks": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "prompt_version_id": 51,
                    "prompt_repo_id": "https://github.com/haphap/MOSAIC-Prompts",
                    "prompt_commit_hash": "a" * 40,
                    "prompt_sha256": "b" * 64,
                    "verify_release_ref": "verify-mutation-delivery",
                    "leak_drift_check_ref": "leak-mutation-delivery",
                    "verify_release_passed": True,
                    "leak_drift_passed": True,
                    "release_ready": True,
                }
            ],
            "rollback_evidence": [
                {
                    "mutation_candidate_id": "PMUT-1",
                    "rollback_trigger_definition": "delivery monitor breach",
                    "rollback_command_or_procedure": "restore previous prompt commit",
                    "monitor_output_ref": "monitor-delivery",
                    "post_rollback_verification_ref": "verify-delivery",
                }
            ],
            "paper_trading_plan": {
                "paper_trading_plan_ref": "paper-plan-delivery",
                "risk_limit_ref": "paper-risk-delivery",
                "stop_loss_or_rollback_ref": "paper-stop-delivery",
                "operator_review_timestamp": "2026-07-03T12:30:00Z",
            },
            "promotion_evidence": {
                "paper_trading_result_ref": "paper-results-delivery",
                "monitor_summary_ref": "monitor-summary-delivery",
                "second_review_timestamp": "2026-07-03T13:00:00Z",
                "lockbox_decision_ref": "lockbox-delivery",
                "decision": "approved_for_promotion_review",
            },
        },
    )

    assert manifest["readiness_status"] == "ready"
    assert manifest["ready_condition_count"] == manifest["condition_count"]
    assert manifest["delivery_ready"] is True
    assert manifest["production_allowed"] is False
    assert manifest["promotion_allowed"] is False
