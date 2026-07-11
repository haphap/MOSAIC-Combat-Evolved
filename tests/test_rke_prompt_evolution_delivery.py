from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke.prompt_evolution_delivery import (
    CHECK_IDS,
    CommandSpec,
    DELIVERY_INPUT_PATHS,
    PERFORMANCE_BUDGET_PATH,
    TOKEN_BUDGET_PATH,
    _redacted_argv,
    _relative_or_token,
    _validate_json_test_receipt,
    _validate_junit_receipt,
    build_delivery_status,
    canonical_hash,
    ci_context_from_environment,
    ci_receipt,
    command_specs,
    empty_hash,
    git_value,
    internal_receipt,
    prepare_run_dir,
    validate_delivery_status,
    verify_performance_budget,
    verify_prompt_budget_attestation,
)
from mosaic.rke.schema_validation import validate_json_schema_artifact


ROOT = Path(__file__).resolve().parents[1]


def _upstream_ci(*, python_status="success", typescript_status="success"):
    commit = git_value(ROOT, "rev-parse", "HEAD")
    return {
        "provider": "github_actions",
        "repository": "example/repo",
        "workflow_ref": "example/repo/.github/workflows/ci.yml@refs/pull/1/merge",
        "job_name": "Prompt evolution delivery (G0-G7)",
        "event_name": "pull_request",
        "run_id": "1",
        "run_attempt": "1",
        "run_url": "https://github.com/example/repo/actions/runs/1",
        "tested_sha": commit,
        "source_head_sha": "1" * 40,
        "base_sha": "2" * 40,
        "context_complete": True,
        "python_status": python_status,
        "typescript_status": typescript_status,
    }


def _checks(*, python_status="success", typescript_status="success"):
    commit = git_value(ROOT, "rev-parse", "HEAD")
    upstream_ci = _upstream_ci(
        python_status=python_status,
        typescript_status=typescript_status,
    )
    run_dir = ROOT / ".mosaic/prompt-evolution-command-contract"
    specs = {spec.check_id: spec for spec in command_specs(ROOT, run_dir)}
    checks = []
    for check_id in CHECK_IDS:
        if check_id in {"python_ci", "typescript_ci"}:
            status = python_status if check_id == "python_ci" else typescript_status
            checks.append(
                ci_receipt(
                    check_id,
                    context=upstream_ci,
                    status=status,
                    code_commit=commit,
                )
            )
        elif check_id in specs:
            spec = specs[check_id]
            checks.append(
                {
                    **internal_receipt(check_id, "pass"),
                    "executor": "command",
                    "command": _redacted_argv(ROOT, run_dir, spec.argv),
                    "working_directory": _relative_or_token(ROOT, spec.cwd),
                    "evidence_refs": list(spec.evidence_refs),
                    "measurements": (
                        {
                            "pytest_registry_copy_bytes": 1,
                            "pytest_registry_copy_files": 1,
                        }
                        if check_id == "python_integration_contract_tests"
                        else {}
                    ),
                }
            )
        elif check_id == "prompt_budget_attestation":
            checks.append(
                internal_receipt(
                    check_id,
                    "pass",
                    evidence_refs=(str(TOKEN_BUDGET_PATH),),
                )
            )
        elif check_id == "performance_budget":
            checks.append(
                internal_receipt(
                    check_id,
                    "pass",
                    evidence_refs=(str(PERFORMANCE_BUDGET_PATH),),
                )
            )
        elif check_id == "documentation_contract":
            checks.append(
                internal_receipt(
                    check_id,
                    "pass",
                    evidence_refs=tuple(
                        path.as_posix()
                        for path in DELIVERY_INPUT_PATHS
                        if path.as_posix().startswith("docs/")
                    ),
                )
            )
        else:
            checks.append(internal_receipt(check_id, "pass", evidence_refs=(check_id,)))
    return checks


def _artifact(checks=None, upstream_ci=None):
    commit = git_value(ROOT, "rev-parse", "HEAD")
    return build_delivery_status(
        ROOT,
        run_id="test-run",
        generated_at="2026-07-10T00:00:00+00:00",
        code_commit=commit,
        git_tree=git_value(ROOT, "rev-parse", "HEAD^{tree}"),
        checks=checks or _checks(),
        upstream_ci=upstream_ci or _upstream_ci(),
    )


def test_all_pass_receipts_derive_all_gates_and_conditions():
    artifact = _artifact()

    assert artifact["summary"] == {
        "passed_check_count": len(CHECK_IDS),
        "failed_check_count": 0,
        "blocked_check_count": 0,
        "passed_gate_count": 8,
        "passed_condition_count": 12,
        "overall_status": "pass",
        "ready": True,
    }
    assert validate_delivery_status(ROOT, artifact, check_current_inputs=False) == []


def test_local_context_cannot_claim_github_receipts(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    context = ci_context_from_environment(ROOT)

    assert context["provider"] == "local"
    assert context["context_complete"] is False
    receipt = ci_receipt(
        "python_ci",
        context=context,
        status="success",
        code_commit=git_value(ROOT, "rev-parse", "HEAD"),
    )
    assert receipt["status"] == "blocked"


def test_run_directory_prepares_pytest_basetemp_parent(tmp_path: Path):
    run_dir = tmp_path / "fresh" / "run"

    prepare_run_dir(run_dir)

    assert (run_dir / "pytest").is_dir()


def test_upstream_ci_block_propagates_without_self_assertion():
    checks = _checks(python_status="queued")
    artifact = _artifact(checks, _upstream_ci(python_status="queued"))

    assert next(item for item in artifact["gates"] if item["gate_id"] == "G7")[
        "status"
    ] == "blocked"
    assert artifact["summary"]["overall_status"] == "blocked"
    assert artifact["summary"]["ready"] is False


def test_ci_binding_rejects_locally_forged_job_identity():
    artifact = _artifact()
    artifact["upstream_ci"]["job_name"] = "local shell"
    without_hash = dict(artifact)
    without_hash.pop("manifest_hash")
    artifact["manifest_hash"] = canonical_hash(without_hash)

    reasons = validate_delivery_status(ROOT, artifact, check_current_inputs=False)

    assert "upstream_ci_job_name_mismatch" in reasons


def test_failed_command_propagates_to_dependent_gates():
    checks = _checks()
    index = next(
        index for index, check in enumerate(checks) if check["check_id"] == "python_gate_tests"
    )
    checks[index] = {
        **checks[index],
        "status": "fail",
        "exit_code": 1,
        "reason_codes": ["COMMAND_EXIT_NONZERO"],
        "stdout_sha256": empty_hash(),
    }
    artifact = _artifact(checks)

    assert artifact["summary"]["overall_status"] == "fail"
    assert next(item for item in artifact["gates"] if item["gate_id"] == "G3")[
        "status"
    ] == "fail"


def test_tampered_derived_status_is_rejected_even_with_rehashed_artifact():
    artifact = _artifact()
    artifact["gates"][0]["status"] = "blocked"
    without_hash = dict(artifact)
    without_hash.pop("manifest_hash")
    artifact["manifest_hash"] = canonical_hash(without_hash)

    reasons = validate_delivery_status(ROOT, artifact, check_current_inputs=False)

    assert "derived_field_mismatch:gates" in reasons


def test_prompt_budget_attestation_closes_current_bundled_inputs():
    status, reasons = verify_prompt_budget_attestation(ROOT)

    assert status == "pass", reasons
    assert reasons == []


def test_performance_budget_closes_fixed_command_receipts():
    status, reasons = verify_performance_budget(ROOT, _checks())

    assert status == "pass", reasons
    assert reasons == []


def test_performance_budget_rejects_duration_regression():
    checks = _checks()
    focused = next(
        check for check in checks if check["check_id"] == "focused_schema_contract"
    )
    focused["duration_ms"] = 5000

    status, reasons = verify_performance_budget(ROOT, checks)

    assert status == "fail"
    assert "PERFORMANCE_DURATION_EXCEEDED:focused_schema_contract" in reasons


def test_exact_evidence_junit_rejects_skipped_assertion(tmp_path: Path):
    junit = tmp_path / "receipt.xml"
    junit.write_text(
        '<testsuite tests="2" failures="0" errors="0" skipped="1" />',
        encoding="utf-8",
    )
    spec = CommandSpec(
        "exact_evidence",
        ("pytest",),
        ROOT,
        ("test",),
        junit_expected_tests=2,
        junit_path=junit,
    )

    assert _validate_junit_receipt(spec) == ["JUNIT_SKIP_NOT_ALLOWED"]


def test_exact_vitest_evidence_rejects_missing_target_assertion(tmp_path: Path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "numPassedTests": 4,
                "numFailedTests": 0,
                "numFailedTestSuites": 0,
            }
        ),
        encoding="utf-8",
    )
    spec = CommandSpec(
        "exact_vitest_evidence",
        ("vitest",),
        ROOT,
        ("test",),
        json_expected_passed_tests=5,
        json_report_path=receipt,
    )

    assert _validate_json_test_receipt(spec) == ["JSON_TEST_PASS_COUNT_MISMATCH"]


def test_delivery_artifact_validates_against_json_schema(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "schemas/prompt_evolution_delivery_status_v1.schema.json",
        schema_dir / "prompt_evolution_delivery_status_v1.schema.json",
    )
    (artifact_dir / "prompt_evolution_delivery_status_v1.json").write_text(
        json.dumps(_artifact()),
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_evolution_delivery_status_v1.schema.json",
        artifact_path="registry/prompt_checks/prompt_evolution_delivery_status_v1.json",
        artifact_kind="json",
    )

    assert record.accepted, record.failures


def test_performance_budget_validates_against_json_schema(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/prompt_checks"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "schemas/prompt_evolution_performance_budget_v1.schema.json",
        schema_dir / "prompt_evolution_performance_budget_v1.schema.json",
    )
    shutil.copyfile(
        ROOT / "registry/prompt_checks/prompt_evolution_performance_budget_v1.json",
        artifact_dir / "prompt_evolution_performance_budget_v1.json",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/prompt_evolution_performance_budget_v1.schema.json",
        artifact_path="registry/prompt_checks/prompt_evolution_performance_budget_v1.json",
        artifact_kind="json",
    )

    assert record.accepted, record.failures
