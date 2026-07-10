from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke.prompt_evolution_delivery import (
    CHECK_IDS,
    _redacted_argv,
    _relative_or_token,
    build_delivery_status,
    canonical_hash,
    ci_receipt,
    command_specs,
    empty_hash,
    git_value,
    internal_receipt,
    validate_delivery_status,
    verify_prompt_budget_attestation,
)
from mosaic.rke.schema_validation import validate_json_schema_artifact


ROOT = Path(__file__).resolve().parents[1]


def _checks(*, python_status="success", typescript_status="success"):
    commit = git_value(ROOT, "rev-parse", "HEAD")
    run_dir = ROOT / ".mosaic/prompt-evolution-command-contract"
    specs = {spec.check_id: spec for spec in command_specs(ROOT, run_dir)}
    checks = []
    for check_id in CHECK_IDS:
        if check_id in {"python_ci", "typescript_ci"}:
            status = python_status if check_id == "python_ci" else typescript_status
            checks.append(
                ci_receipt(
                    check_id,
                    provider="github_actions",
                    status=status,
                    head_sha=commit,
                    code_commit=commit,
                    run_url="https://github.com/example/repo/actions/runs/1",
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
                }
            )
        else:
            checks.append(internal_receipt(check_id, "pass", evidence_refs=(check_id,)))
    return checks


def _artifact(checks=None):
    commit = git_value(ROOT, "rev-parse", "HEAD")
    return build_delivery_status(
        ROOT,
        run_id="test-run",
        generated_at="2026-07-10T00:00:00+00:00",
        code_commit=commit,
        git_tree=git_value(ROOT, "rev-parse", "HEAD^{tree}"),
        checks=checks or _checks(),
        upstream_ci={
            "provider": "github_actions",
            "run_id": "1",
            "run_url": "https://github.com/example/repo/actions/runs/1",
            "head_sha": commit,
            "python_status": "success",
            "typescript_status": "success",
        },
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


def test_upstream_ci_block_propagates_without_self_assertion():
    checks = _checks(python_status="queued")
    artifact = _artifact(checks)

    assert next(item for item in artifact["gates"] if item["gate_id"] == "G7")[
        "status"
    ] == "blocked"
    assert artifact["summary"]["overall_status"] == "blocked"
    assert artifact["summary"]["ready"] is False


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
