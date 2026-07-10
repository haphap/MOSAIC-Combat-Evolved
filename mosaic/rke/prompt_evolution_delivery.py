"""Generate and verify prompt-evolution delivery status from same-run evidence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


SCHEMA_VERSION = "prompt_evolution_delivery_status_v1"
GENERATOR_ID = "prompt_evolution_delivery"
GENERATOR_VERSION = "1"
COMMAND_CONTRACT_VERSION = "prompt_evolution_delivery_commands_v1"

Status = Literal["pass", "fail", "blocked"]

PROMPT_CHECK_DIR = Path("registry/prompt_checks")
RUNTIME_MANIFEST_PATH = PROMPT_CHECK_DIR / "runtime_agent_manifest_v1.json"
DOMAIN_CATALOG_PATH = PROMPT_CHECK_DIR / "domain_knob_catalog_v1.json"
EVALUATION_CONTRACT_PATH = (
    PROMPT_CHECK_DIR / "domain_knob_evaluation_contract_v1.json"
)
TOKEN_BUDGET_PATH = PROMPT_CHECK_DIR / "prompt_token_budget_manifest_v1.json"

DELIVERY_INPUT_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path("docs/runbooks/position_aware_prompt_evolution.md"),
    Path("docs/wiki/CLI-Reference.md"),
    Path("docs/wiki/Self-Improvement.md"),
    Path("docs/wiki/TUI.md"),
    Path("docs/wiki/zh/CLI-Reference.md"),
    Path("docs/wiki/zh/Self-Improvement.md"),
    Path("docs/wiki/zh/TUI.md"),
    Path("mosaic-ts/package.json"),
    Path("mosaic-ts/pnpm-lock.yaml"),
    Path("pyproject.toml"),
    DOMAIN_CATALOG_PATH,
    EVALUATION_CONTRACT_PATH,
    RUNTIME_MANIFEST_PATH,
    TOKEN_BUDGET_PATH,
    Path("schemas/domain_knob_catalog_v1.schema.json"),
    Path("schemas/domain_knob_evaluation_contract_v1.schema.json"),
    Path("schemas/prompt_evolution_delivery_status_v1.schema.json"),
    Path("schemas/prompt_token_budget_manifest_v1.schema.json"),
    Path("schemas/runtime_agent_manifest_v1.schema.json"),
)

CHECK_IDS = (
    "git_clean_start",
    "ruff",
    "prompt_leak_guard",
    "python_gate_tests",
    "typescript_typecheck",
    "typescript_lint",
    "typescript_gate_tests",
    "bundled_prompt_contract",
    "runtime_manifest_reproducible",
    "domain_catalog_reproducible",
    "evaluation_contract_reproducible",
    "prompt_budget_attestation",
    "documentation_contract",
    "git_diff_check",
    "git_clean_end",
    "python_ci",
    "typescript_ci",
)

GATE_DEFINITIONS: Mapping[str, Mapping[str, Any]] = {
    "G0": {
        "title": "contract foundation",
        "checks": (
            "python_gate_tests",
            "typescript_gate_tests",
            "runtime_manifest_reproducible",
            "domain_catalog_reproducible",
            "evaluation_contract_reproducible",
        ),
        "gates": (),
    },
    "G1": {
        "title": "Layer 4 runtime safety",
        "checks": ("typescript_gate_tests", "python_gate_tests"),
        "gates": ("G0",),
    },
    "G2": {
        "title": "evidence runtime",
        "checks": ("typescript_gate_tests",),
        "gates": ("G0",),
    },
    "G3": {
        "title": "paired PIT evaluation",
        "checks": ("python_gate_tests", "typescript_gate_tests"),
        "gates": ("G0",),
    },
    "G4": {
        "title": "transaction and release",
        "checks": ("typescript_gate_tests", "python_gate_tests"),
        "gates": ("G3",),
    },
    "G5": {
        "title": "full default-cohort rollout",
        "checks": (
            "bundled_prompt_contract",
            "prompt_budget_attestation",
            "runtime_manifest_reproducible",
        ),
        "gates": ("G1", "G2", "G3", "G4"),
    },
    "G6": {
        "title": "integrations and operations",
        "checks": (
            "python_gate_tests",
            "typescript_gate_tests",
            "documentation_contract",
        ),
        "gates": ("G5",),
    },
    "G7": {
        "title": "clean delivery",
        "checks": (
            "git_clean_start",
            "ruff",
            "prompt_leak_guard",
            "typescript_typecheck",
            "typescript_lint",
            "git_diff_check",
            "git_clean_end",
            "python_ci",
            "typescript_ci",
        ),
        "gates": ("G0", "G1", "G2", "G3", "G4", "G5", "G6"),
    },
}

CONDITION_DEFINITIONS: Mapping[str, Mapping[str, Any]] = {
    "C01": {"title": "25 agents and 26 stages", "checks": (), "gates": ("G5",)},
    "C02": {"title": "claim-to-evidence closure", "checks": (), "gates": ("G2",)},
    "C03": {"title": "scoped real source statuses", "checks": (), "gates": ("G2",)},
    "C04": {"title": "registry and write-back closure", "checks": (), "gates": ("G0", "G3")},
    "C05": {"title": "canonical Layer 4 DAG", "checks": (), "gates": ("G1",)},
    "C06": {"title": "portfolio and action validators", "checks": (), "gates": ("G1",)},
    "C07": {"title": "end-to-end mutation release trace", "checks": (), "gates": ("G3", "G4")},
    "C08": {"title": "representative paired evaluations and rollback", "checks": ("python_gate_tests",), "gates": ("G3",)},
    "C09": {"title": "transaction recovery and idempotency", "checks": (), "gates": ("G4",)},
    "C10": {"title": "backtest, paper, partial-fill and TUI integration", "checks": (), "gates": ("G6",)},
    "C11": {"title": "privacy, PIT and compatibility boundaries", "checks": ("prompt_leak_guard",), "gates": ("G0", "G1", "G2")},
    "C12": {"title": "CI, budgets and documentation", "checks": ("prompt_budget_attestation",), "gates": ("G7",)},
}

PYTHON_GATE_TESTS = (
    "tests/test_autoresearch_domain_evaluator.py",
    "tests/test_bridge_autoresearch.py",
    "tests/test_bridge_prompts.py",
    "tests/test_mirofish.py",
    "tests/test_paper_engine.py",
    "tests/test_rke_schema_artifacts.py",
)

TYPESCRIPT_GATE_TESTS = (
    "test/daily_cycle.test.ts",
    "test/dashboard.test.tsx",
    "test/decision_layer4_agents.test.ts",
    "test/evidence_contract.test.ts",
    "test/evidence_runtime.test.ts",
    "test/layer4_source_adapters.test.ts",
    "test/mirofish_context_inject.test.ts",
    "test/mirofish_trainer.test.ts",
    "test/mutator.test.ts",
    "test/orchestrator.test.ts",
    "test/prompt_loader.test.ts",
    "test/prompt_release_canary_runtime.test.ts",
    "test/prompt_release_manager.test.ts",
    "test/prompt_token_budget.test.ts",
    "test/release_prompt_loader.test.ts",
    "test/research_knobs.test.ts",
    "test/research_knobs_checker.test.ts",
    "test/runtime_agent_spec.test.ts",
    "test/transaction_release_coordinator.test.ts",
)


@dataclass(frozen=True)
class CommandSpec:
    check_id: str
    argv: tuple[str, ...]
    cwd: Path
    evidence_refs: tuple[str, ...]
    compare_output_to: Path | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def empty_hash() -> str:
    return f"sha256:{hashlib.sha256(b'').hexdigest()}"


def git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_is_clean(root: Path) -> bool:
    return not git_value(root, "status", "--porcelain", "--untracked-files=all")


def command_specs(root: Path, run_dir: Path) -> tuple[CommandSpec, ...]:
    python_basetemp = run_dir / "pytest"
    generated_dir = run_dir / "generated"
    prompts_root = root / "prompts/mosaic"
    return (
        CommandSpec(
            "ruff",
            ("uvx", "ruff@0.15.15", "check", "mosaic", "tests"),
            root,
            ("mosaic", "tests"),
        ),
        CommandSpec(
            "prompt_leak_guard",
            ("uv", "run", "python", "scripts/check_prompt_leaks.py"),
            root,
            ("scripts/check_prompt_leaks.py",),
        ),
        CommandSpec(
            "python_gate_tests",
            (
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                *PYTHON_GATE_TESTS,
                "-q",
                "--durations=20",
                "--basetemp",
                str(python_basetemp),
            ),
            root,
            PYTHON_GATE_TESTS,
        ),
        CommandSpec(
            "typescript_typecheck",
            ("pnpm", "typecheck"),
            root / "mosaic-ts",
            ("mosaic-ts/tsconfig.json", "mosaic-ts/package.json"),
        ),
        CommandSpec(
            "typescript_lint",
            ("pnpm", "lint"),
            root / "mosaic-ts",
            ("mosaic-ts/src", "mosaic-ts/test"),
        ),
        CommandSpec(
            "typescript_gate_tests",
            ("pnpm", "exec", "vitest", "run", *TYPESCRIPT_GATE_TESTS),
            root / "mosaic-ts",
            tuple(f"mosaic-ts/{path}" for path in TYPESCRIPT_GATE_TESTS),
        ),
        CommandSpec(
            "bundled_prompt_contract",
            (
                "pnpm",
                "dev",
                "prompts",
                "check-research-knobs",
                "--prompts-root",
                str(prompts_root),
                "--enabled-agents",
                "*",
                "--enabled-stages",
                "*",
            ),
            root / "mosaic-ts",
            ("prompts/mosaic", str(RUNTIME_MANIFEST_PATH)),
        ),
        _artifact_export_spec(
            root,
            generated_dir,
            "runtime_manifest_reproducible",
            "export-runtime-agent-manifest",
            RUNTIME_MANIFEST_PATH,
        ),
        _artifact_export_spec(
            root,
            generated_dir,
            "domain_catalog_reproducible",
            "export-domain-knob-catalog",
            DOMAIN_CATALOG_PATH,
        ),
        _artifact_export_spec(
            root,
            generated_dir,
            "evaluation_contract_reproducible",
            "export-domain-knob-evaluation-contract",
            EVALUATION_CONTRACT_PATH,
        ),
        CommandSpec(
            "git_diff_check",
            ("git", "diff", "--check"),
            root,
            ("git:working-tree",),
        ),
    )


def _artifact_export_spec(
    root: Path,
    generated_dir: Path,
    check_id: str,
    command: str,
    committed_path: Path,
) -> CommandSpec:
    output = generated_dir / committed_path.name
    return CommandSpec(
        check_id,
        ("pnpm", "dev", "prompts", command, "--out", str(output)),
        root / "mosaic-ts",
        (str(committed_path),),
        compare_output_to=committed_path,
    )


def run_command(root: Path, run_dir: Path, spec: CommandSpec) -> dict[str, Any]:
    started_at = utc_now()
    started = time.monotonic()
    env = dict(os.environ)
    temp_dir = run_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    env["MOSAIC_RKE_TMPDIR"] = str(temp_dir)
    env["TMPDIR"] = str(temp_dir)
    result = subprocess.run(
        list(spec.argv),
        cwd=spec.cwd,
        env=env,
        check=False,
        capture_output=True,
        text=False,
    )
    reasons: list[str] = []
    status: Status = "pass" if result.returncode == 0 else "fail"
    if result.returncode != 0:
        reasons.append("COMMAND_EXIT_NONZERO")
    if status == "pass" and spec.compare_output_to is not None:
        output_path = Path(spec.argv[-1])
        committed_path = root / spec.compare_output_to
        if not output_path.exists() or output_path.read_bytes() != committed_path.read_bytes():
            status = "fail"
            reasons.append("GENERATED_ARTIFACT_DRIFT")
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    completed_at = utc_now()
    stdout = result.stdout or b""
    stderr = result.stderr or b""
    print(f"[{status}] {spec.check_id} ({duration_ms} ms)")
    if status != "pass":
        if stdout:
            print(stdout.decode("utf-8", errors="replace")[-4000:])
        if stderr:
            print(stderr.decode("utf-8", errors="replace")[-4000:])
    return {
        "check_id": spec.check_id,
        "executor": "command",
        "command": _redacted_argv(root, run_dir, spec.argv),
        "working_directory": _relative_or_token(root, spec.cwd),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "exit_code": result.returncode,
        "status": status,
        "reason_codes": reasons,
        "stdout_sha256": f"sha256:{hashlib.sha256(stdout).hexdigest()}",
        "stderr_sha256": f"sha256:{hashlib.sha256(stderr).hexdigest()}",
        "evidence_refs": list(spec.evidence_refs),
    }


def internal_receipt(
    check_id: str,
    status: Status,
    *,
    reason_codes: Sequence[str] = (),
    evidence_refs: Sequence[str] = (),
) -> dict[str, Any]:
    now = utc_now()
    return {
        "check_id": check_id,
        "executor": "internal",
        "command": [],
        "working_directory": ".",
        "started_at": now,
        "completed_at": now,
        "duration_ms": 0,
        "exit_code": 0 if status == "pass" else (1 if status == "fail" else None),
        "status": status,
        "reason_codes": list(reason_codes),
        "stdout_sha256": empty_hash(),
        "stderr_sha256": empty_hash(),
        "evidence_refs": list(evidence_refs),
    }


def verify_prompt_budget_attestation(root: Path) -> tuple[Status, list[str]]:
    reasons: list[str] = []
    try:
        budget = _load_json(root / TOKEN_BUDGET_PATH)
        runtime_manifest = _load_json(root / RUNTIME_MANIFEST_PATH)
    except (OSError, json.JSONDecodeError, ValueError):
        return "fail", ["PROMPT_BUDGET_UNREADABLE"]
    declared_hash = budget.get("manifest_hash")
    without_hash = dict(budget)
    without_hash.pop("manifest_hash", None)
    if declared_hash != canonical_hash(without_hash):
        reasons.append("PROMPT_BUDGET_HASH_MISMATCH")
    if budget.get("runtime_manifest_hash") != canonical_hash(runtime_manifest):
        reasons.append("PROMPT_BUDGET_RUNTIME_MANIFEST_DRIFT")
    summary = budget.get("summary")
    rows = budget.get("rows")
    if not isinstance(summary, Mapping) or summary.get("ready") is not True:
        reasons.append("PROMPT_BUDGET_NOT_READY")
    if not isinstance(rows, list) or len(rows) != 104:
        reasons.append("PROMPT_BUDGET_ROW_COUNT_MISMATCH")
        rows = []
    private_rows = [row for row in rows if row.get("source") == "private"]
    bundled_rows = [row for row in rows if row.get("source") == "bundled"]
    if len(private_rows) != 52 or len(bundled_rows) != 52:
        reasons.append("PROMPT_BUDGET_SOURCE_COVERAGE_MISMATCH")
    if any(row.get("passed") is not True for row in rows):
        reasons.append("PROMPT_BUDGET_ROW_FAILED")
    if not isinstance(budget.get("source_commits"), Mapping) or not budget[
        "source_commits"
    ].get("private"):
        reasons.append("PRIVATE_PROMPT_COMMIT_MISSING")
    prompts_root = root / "prompts/mosaic"
    for row in bundled_rows:
        relative = row.get("source_path")
        if not isinstance(relative, str):
            reasons.append("BUNDLED_PROMPT_PATH_INVALID")
            continue
        path = prompts_root / relative
        if not path.is_file() or file_hash(path) != row.get("source_sha256"):
            reasons.append("BUNDLED_PROMPT_HASH_DRIFT")
            break
    bundled_commit = str(budget.get("source_commits", {}).get("bundled") or "")
    if not bundled_commit or not _git_is_ancestor(root, bundled_commit):
        reasons.append("BUNDLED_SOURCE_COMMIT_NOT_ANCESTOR")
    return ("pass" if not reasons else "fail"), sorted(set(reasons))


def verify_documentation_contract(root: Path) -> tuple[Status, list[str]]:
    requirements = {
        Path("docs/runbooks/position_aware_prompt_evolution.md"): (
            "MOSAIC_PROMPT_CANARY_EVENT_LOG",
            "prompt-token-budget",
            "summarize-slo",
            "MOSAIC_TEST_PRIVATE_REPORT_INTELLIGENCE_FIXTURES",
            "--durations=20",
        ),
        Path("docs/wiki/CLI-Reference.md"): ("prompt-token-budget", "summarize-slo"),
        Path("docs/wiki/zh/CLI-Reference.md"): ("prompt-token-budget", "summarize-slo"),
        Path("docs/wiki/Self-Improvement.md"): ("canary", "rollback"),
        Path("docs/wiki/zh/Self-Improvement.md"): ("canary", "rollback"),
        Path("docs/wiki/TUI.md"): ("target/current", "MiroFish"),
        Path("docs/wiki/zh/TUI.md"): ("target/current", "MiroFish"),
    }
    reasons: list[str] = []
    for relative, snippets in requirements.items():
        path = root / relative
        if not path.is_file():
            reasons.append(f"DOC_MISSING:{relative}")
            continue
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in content:
                reasons.append(f"DOC_COMMAND_MISSING:{relative}:{snippet}")
    return ("pass" if not reasons else "fail"), reasons


def ci_receipt(
    check_id: str,
    *,
    provider: str,
    status: str,
    head_sha: str,
    code_commit: str,
    run_url: str,
) -> dict[str, Any]:
    if provider != "github_actions":
        return internal_receipt(
            check_id,
            "blocked",
            reason_codes=("UPSTREAM_CI_NOT_GITHUB_ACTIONS",),
            evidence_refs=(run_url,) if run_url else (),
        )
    if head_sha != code_commit:
        return internal_receipt(
            check_id,
            "fail",
            reason_codes=("UPSTREAM_CI_HEAD_SHA_MISMATCH",),
            evidence_refs=(run_url,),
        )
    if status != "success":
        return internal_receipt(
            check_id,
            "fail" if status in {"failure", "cancelled", "timed_out"} else "blocked",
            reason_codes=(f"UPSTREAM_CI_{status.upper() or 'MISSING'}",),
            evidence_refs=(run_url,),
        )
    return internal_receipt(check_id, "pass", evidence_refs=(run_url,))


def build_delivery_status(
    root: Path,
    *,
    run_id: str,
    generated_at: str,
    code_commit: str,
    git_tree: str,
    checks: Sequence[Mapping[str, Any]],
    upstream_ci: Mapping[str, Any],
) -> dict[str, Any]:
    checks_by_id = {str(check["check_id"]): dict(check) for check in checks}
    if set(checks_by_id) != set(CHECK_IDS):
        missing = sorted(set(CHECK_IDS) - set(checks_by_id))
        extra = sorted(set(checks_by_id) - set(CHECK_IDS))
        raise ValueError(f"delivery check set mismatch: missing={missing} extra={extra}")
    gates: list[dict[str, Any]] = []
    gates_by_id: dict[str, dict[str, Any]] = {}
    for gate_id, definition in GATE_DEFINITIONS.items():
        status, reasons = _derived_status(
            [checks_by_id[item]["status"] for item in definition["checks"]]
            + [gates_by_id[item]["status"] for item in definition["gates"]]
        )
        gate = {
            "gate_id": gate_id,
            "title": definition["title"],
            "status": status,
            "required_check_ids": list(definition["checks"]),
            "required_gate_ids": list(definition["gates"]),
            "blocking_reason_codes": _blocking_reasons(
                definition["checks"], definition["gates"], checks_by_id, gates_by_id
            )
            or reasons,
            "evidence_refs": sorted(
                {
                    reference
                    for check_id in definition["checks"]
                    for reference in checks_by_id[check_id].get("evidence_refs", [])
                }
            ),
        }
        gates.append(gate)
        gates_by_id[gate_id] = gate
    conditions: list[dict[str, Any]] = []
    for condition_id, definition in CONDITION_DEFINITIONS.items():
        status, reasons = _derived_status(
            [checks_by_id[item]["status"] for item in definition["checks"]]
            + [gates_by_id[item]["status"] for item in definition["gates"]]
        )
        conditions.append(
            {
                "condition_id": condition_id,
                "title": definition["title"],
                "status": status,
                "required_check_ids": list(definition["checks"]),
                "required_gate_ids": list(definition["gates"]),
                "blocking_reason_codes": _blocking_reasons(
                    definition["checks"],
                    definition["gates"],
                    checks_by_id,
                    gates_by_id,
                )
                or reasons,
            }
        )
    all_statuses = [item["status"] for item in gates + conditions]
    overall_status, _ = _derived_status(all_statuses)
    budget = _load_json(root / TOKEN_BUDGET_PATH)
    input_hashes = [
        {
            "path": path.as_posix(),
            "sha256": file_hash(root / path),
            "bytes": (root / path).stat().st_size,
        }
        for path in sorted(DELIVERY_INPUT_PATHS, key=lambda item: item.as_posix())
    ]
    without_hash = {
        "schema_version": SCHEMA_VERSION,
        "generator": {
            "id": GENERATOR_ID,
            "version": GENERATOR_VERSION,
            "command_contract_version": COMMAND_CONTRACT_VERSION,
        },
        "run": {
            "run_id": run_id,
            "generated_at": generated_at,
            "code_commit": code_commit,
            "git_tree": git_tree,
            "clean_start": checks_by_id["git_clean_start"]["status"] == "pass",
            "clean_end": checks_by_id["git_clean_end"]["status"] == "pass",
        },
        "prompt_sources": {
            "private_commit": str(budget["source_commits"]["private"]),
            "bundled_commit": str(budget["source_commits"]["bundled"]),
            "token_budget_manifest_hash": str(budget["manifest_hash"]),
        },
        "upstream_ci": dict(upstream_ci),
        "inputs": input_hashes,
        "checks": [checks_by_id[check_id] for check_id in CHECK_IDS],
        "gates": gates,
        "conditions": conditions,
        "summary": {
            "passed_check_count": sum(
                check["status"] == "pass" for check in checks_by_id.values()
            ),
            "failed_check_count": sum(
                check["status"] == "fail" for check in checks_by_id.values()
            ),
            "blocked_check_count": sum(
                check["status"] == "blocked" for check in checks_by_id.values()
            ),
            "passed_gate_count": sum(item["status"] == "pass" for item in gates),
            "passed_condition_count": sum(
                item["status"] == "pass" for item in conditions
            ),
            "overall_status": overall_status,
            "ready": overall_status == "pass",
        },
    }
    return {**without_hash, "manifest_hash": canonical_hash(without_hash)}


def validate_delivery_status(
    root: Path,
    artifact: Mapping[str, Any],
    *,
    check_current_inputs: bool = True,
) -> list[str]:
    reasons: list[str] = []
    if artifact.get("schema_version") != SCHEMA_VERSION:
        reasons.append("schema_version_mismatch")
    generator = artifact.get("generator")
    if not isinstance(generator, Mapping) or (
        generator.get("id"),
        generator.get("version"),
        generator.get("command_contract_version"),
    ) != (GENERATOR_ID, GENERATOR_VERSION, COMMAND_CONTRACT_VERSION):
        reasons.append("generator_contract_mismatch")
    without_hash = dict(artifact)
    declared_hash = without_hash.pop("manifest_hash", None)
    if declared_hash != canonical_hash(without_hash):
        reasons.append("manifest_hash_mismatch")
    checks = artifact.get("checks")
    if not isinstance(checks, list):
        return [*reasons, "checks_missing"]
    checks_by_id = {
        str(check.get("check_id")): check
        for check in checks
        if isinstance(check, Mapping)
    }
    if set(checks_by_id) != set(CHECK_IDS) or len(checks) != len(CHECK_IDS):
        reasons.append("check_set_mismatch")
    for check_id, check in checks_by_id.items():
        status = check.get("status")
        if status not in ("pass", "fail", "blocked"):
            reasons.append(f"check_status_invalid:{check_id}")
        if status == "pass" and check.get("exit_code") != 0:
            reasons.append(f"pass_without_zero_exit:{check_id}")
    contract_run_dir = root / ".mosaic/prompt-evolution-command-contract"
    expected_specs = {spec.check_id: spec for spec in command_specs(root, contract_run_dir)}
    for check_id, spec in expected_specs.items():
        check = checks_by_id.get(check_id, {})
        expected_command = _redacted_argv(root, contract_run_dir, spec.argv)
        expected_cwd = _relative_or_token(root, spec.cwd)
        if (
            check.get("executor") != "command"
            or check.get("command") != expected_command
            or check.get("working_directory") != expected_cwd
            or check.get("evidence_refs") != list(spec.evidence_refs)
        ):
            reasons.append(f"command_contract_mismatch:{check_id}")
    for check_id in set(CHECK_IDS) - set(expected_specs):
        check = checks_by_id.get(check_id, {})
        if check.get("executor") != "internal" or check.get("command") != []:
            reasons.append(f"internal_check_contract_mismatch:{check_id}")
    try:
        rebuilt = build_delivery_status(
            root,
            run_id=str(artifact["run"]["run_id"]),
            generated_at=str(artifact["run"]["generated_at"]),
            code_commit=str(artifact["run"]["code_commit"]),
            git_tree=str(artifact["run"]["git_tree"]),
            checks=list(checks_by_id.values()),
            upstream_ci=artifact["upstream_ci"],
        )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        reasons.append(f"artifact_rebuild_failed:{type(exc).__name__}")
        return reasons
    for field in ("prompt_sources", "inputs", "gates", "conditions", "summary"):
        if artifact.get(field) != rebuilt.get(field):
            reasons.append(f"derived_field_mismatch:{field}")
    if check_current_inputs:
        run = artifact.get("run")
        if not isinstance(run, Mapping):
            reasons.append("run_missing")
        else:
            if run.get("code_commit") != git_value(root, "rev-parse", "HEAD"):
                reasons.append("code_commit_drift")
            if run.get("git_tree") != git_value(root, "rev-parse", "HEAD^{tree}"):
                reasons.append("git_tree_drift")
        if not git_is_clean(root):
            reasons.append("working_tree_not_clean")
    return sorted(set(reasons))


def generate_delivery_status(
    root: Path,
    *,
    output: Path,
    run_id: str,
    ci_provider: str,
    ci_run_id: str,
    ci_run_url: str,
    ci_head_sha: str,
    python_ci_status: str,
    typescript_ci_status: str,
) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    run_dir = output.parent / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    code_commit = git_value(root, "rev-parse", "HEAD")
    git_tree = git_value(root, "rev-parse", "HEAD^{tree}")
    clean_start = git_is_clean(root)
    checks: list[dict[str, Any]] = [
        internal_receipt(
            "git_clean_start",
            "pass" if clean_start else "fail",
            reason_codes=() if clean_start else ("WORKING_TREE_DIRTY_AT_START",),
            evidence_refs=("git:status",),
        )
    ]
    for spec in command_specs(root, run_dir):
        checks.append(run_command(root, run_dir, spec))
    budget_status, budget_reasons = verify_prompt_budget_attestation(root)
    checks.append(
        internal_receipt(
            "prompt_budget_attestation",
            budget_status,
            reason_codes=budget_reasons,
            evidence_refs=(str(TOKEN_BUDGET_PATH),),
        )
    )
    docs_status, docs_reasons = verify_documentation_contract(root)
    checks.append(
        internal_receipt(
            "documentation_contract",
            docs_status,
            reason_codes=docs_reasons,
            evidence_refs=tuple(
                path.as_posix()
                for path in DELIVERY_INPUT_PATHS
                if path.as_posix().startswith("docs/")
            ),
        )
    )
    clean_end = git_is_clean(root)
    checks.append(
        internal_receipt(
            "git_clean_end",
            "pass" if clean_end else "fail",
            reason_codes=() if clean_end else ("WORKING_TREE_DIRTY_AT_END",),
            evidence_refs=("git:status",),
        )
    )
    checks.append(
        ci_receipt(
            "python_ci",
            provider=ci_provider,
            status=python_ci_status,
            head_sha=ci_head_sha,
            code_commit=code_commit,
            run_url=ci_run_url,
        )
    )
    checks.append(
        ci_receipt(
            "typescript_ci",
            provider=ci_provider,
            status=typescript_ci_status,
            head_sha=ci_head_sha,
            code_commit=code_commit,
            run_url=ci_run_url,
        )
    )
    upstream_ci = {
        "provider": ci_provider,
        "run_id": ci_run_id,
        "run_url": ci_run_url,
        "head_sha": ci_head_sha,
        "python_status": python_ci_status,
        "typescript_status": typescript_ci_status,
    }
    artifact = build_delivery_status(
        root,
        run_id=run_id,
        generated_at=utc_now(),
        code_commit=code_commit,
        git_tree=git_tree,
        checks=checks,
        upstream_ci=upstream_ci,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _git_is_ancestor(root: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _redacted_argv(root: Path, run_dir: Path, argv: Sequence[str]) -> list[str]:
    return [
        str(item).replace(str(run_dir), "$RUN_DIR").replace(str(root), "$REPO_ROOT")
        for item in argv
    ]


def _relative_or_token(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return "$EXTERNAL"


def _derived_status(statuses: Sequence[str]) -> tuple[Status, list[str]]:
    if any(status == "fail" for status in statuses):
        return "fail", ["REQUIRED_EVIDENCE_FAILED"]
    if any(status == "blocked" for status in statuses):
        return "blocked", ["REQUIRED_EVIDENCE_BLOCKED"]
    if not statuses or all(status == "pass" for status in statuses):
        return "pass", []
    return "fail", ["REQUIRED_EVIDENCE_INVALID"]


def _blocking_reasons(
    check_ids: Sequence[str],
    gate_ids: Sequence[str],
    checks: Mapping[str, Mapping[str, Any]],
    gates: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    reasons: set[str] = set()
    for check_id in check_ids:
        check = checks[check_id]
        if check["status"] != "pass":
            reasons.update(check.get("reason_codes", []))
            reasons.add(f"CHECK_{check_id.upper()}_{check['status'].upper()}")
    for gate_id in gate_ids:
        gate = gates[gate_id]
        if gate["status"] != "pass":
            reasons.update(gate.get("blocking_reason_codes", []))
            reasons.add(f"GATE_{gate_id}_{gate['status'].upper()}")
    return sorted(reasons)
