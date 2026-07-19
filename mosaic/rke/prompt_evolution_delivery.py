"""Generate and verify prompt-evolution delivery status from same-run evidence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


SCHEMA_VERSION = "prompt_evolution_delivery_status_v1"
GENERATOR_ID = "prompt_evolution_delivery"
GENERATOR_VERSION = "2"
COMMAND_CONTRACT_VERSION = "prompt_evolution_delivery_commands_v2"

Status = Literal["pass", "fail", "blocked"]

PROMPT_CHECK_DIR = Path("registry/prompt_checks")
RUNTIME_MANIFEST_PATH = PROMPT_CHECK_DIR / "runtime_agent_manifest_v4.json"
PRIVATE_KNOT_ASSETS_REF_PATH = PROMPT_CHECK_DIR / "private_knot_assets_ref_v1.json"
TOKEN_BUDGET_PATH = PROMPT_CHECK_DIR / "prompt_token_budget_manifest_v1.json"
PERFORMANCE_BUDGET_PATH = (
    PROMPT_CHECK_DIR / "prompt_evolution_performance_budget_v1.json"
)

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
    PRIVATE_KNOT_ASSETS_REF_PATH,
    PERFORMANCE_BUDGET_PATH,
    RUNTIME_MANIFEST_PATH,
    TOKEN_BUDGET_PATH,
    Path("schemas/prompt_evolution_delivery_status_v1.schema.json"),
    Path("schemas/prompt_evolution_performance_budget_v1.schema.json"),
    Path("schemas/prompt_token_budget_manifest_v1.schema.json"),
    Path("schemas/runtime_agent_manifest_v4.schema.json"),
)

CHECK_IDS = (
    "git_clean_start",
    "ruff",
    "prompt_leak_guard",
    "focused_schema_contract",
    "schema_artifact_tests",
    "python_gate_tests",
    "representative_evaluation_tests",
    "python_integration_contract_tests",
    "typescript_typecheck",
    "typescript_lint",
    "typescript_gate_tests",
    "typescript_integration_contract_tests",
    "bundled_prompt_contract",
    "runtime_manifest_reproducible",
    "domain_catalog_reproducible",
    "evaluation_contract_reproducible",
    "prompt_budget_attestation",
    "performance_budget",
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
            "focused_schema_contract",
            "schema_artifact_tests",
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
        "checks": (
            "python_gate_tests",
            "representative_evaluation_tests",
            "typescript_gate_tests",
        ),
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
            "performance_budget",
        ),
        "gates": ("G0", "G1", "G2", "G3", "G4", "G5", "G6"),
    },
}

CONDITION_DEFINITIONS: Mapping[str, Mapping[str, Any]] = {
    "C01": {"title": "28 agents and 29 stages", "checks": (), "gates": ("G5",)},
    "C02": {"title": "claim-to-evidence closure", "checks": (), "gates": ("G2",)},
    "C03": {"title": "scoped real source statuses", "checks": (), "gates": ("G2",)},
    "C04": {"title": "registry and write-back closure", "checks": (), "gates": ("G0", "G3")},
    "C05": {"title": "canonical Layer 4 DAG", "checks": (), "gates": ("G1",)},
    "C06": {"title": "portfolio and action validators", "checks": (), "gates": ("G1",)},
    "C07": {"title": "end-to-end mutation release trace", "checks": (), "gates": ("G3", "G4")},
    "C08": {
        "title": "representative paired evaluations and rollback",
        "checks": ("representative_evaluation_tests",),
        "gates": ("G3",),
    },
    "C09": {"title": "transaction recovery and idempotency", "checks": (), "gates": ("G4",)},
    "C10": {
        "title": "backtest, paper, partial-fill and TUI integration",
        "checks": (
            "python_integration_contract_tests",
            "typescript_integration_contract_tests",
        ),
        "gates": ("G6",),
    },
    "C11": {"title": "privacy, PIT and compatibility boundaries", "checks": ("prompt_leak_guard",), "gates": ("G0", "G1", "G2")},
    "C12": {
        "title": "CI, budgets and documentation",
        "checks": ("prompt_budget_attestation", "performance_budget"),
        "gates": ("G7",),
    },
}

PYTHON_GATE_TESTS = (
    "tests/test_knot_private_boundary.py",
    "tests/test_bridge_autoresearch.py",
    "tests/test_bridge_prompts.py",
    "tests/test_mirofish.py",
    "tests/test_paper_engine.py",
)

REPRESENTATIVE_EVALUATION_TESTS = (
    "tests/test_knot_private_boundary.py",
)

PYTHON_INTEGRATION_CONTRACT_TESTS = (
    "tests/test_paper_engine.py::TestPaperEngine::test_order_intent_is_idempotent_and_account_hash_is_compare_and_swap",
    "tests/test_pytest_registry_fixture.py::test_registry_copy_excludes_private_cache_and_stays_within_budget",
)

TYPESCRIPT_INTEGRATION_PATTERN = (
    "carries target positions across a 10-day replay loop|"
    "carries partial fills and residual target drift into the next cycle|"
    "delegates sizing to paper.suggest_order_from_signal so orders are target-current deltas|"
    "renders the Today [(]CIO plan[)] tab by default|"
    "switches to the paper tab on key '4'"
)

PERFORMANCE_TIMING_CHECK_IDS = frozenset(
    {
        "focused_schema_contract",
        "schema_artifact_tests",
        "bundled_prompt_contract",
    }
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
    "test/orchestrator.test.ts",
    "test/prompt_loader.test.ts",
    "test/prompt_release_canary_runtime.test.ts",
    "test/prompt_release_manager.test.ts",
    "test/prompt_token_budget.test.ts",
    "test/release_prompt_loader.test.ts",
    "test/knot_contract.test.ts",
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
    junit_expected_tests: int | None = None
    junit_path: Path | None = None
    json_expected_passed_tests: int | None = None
    json_report_path: Path | None = None


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


def prepare_run_dir(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "pytest").mkdir(parents=True, exist_ok=True)


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
            "focused_schema_contract",
            (
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                "tests/test_knot_private_boundary.py",
                "tests/test_rke_prompt_evolution_delivery.py::test_delivery_artifact_validates_against_json_schema",
                "-q",
                "--junitxml",
                str(run_dir / "focused-schema.xml"),
                "--basetemp",
                str(python_basetemp / "focused-schema"),
            ),
            root,
            (
                "tests/test_knot_private_boundary.py",
                "tests/test_rke_prompt_evolution_delivery.py::test_delivery_artifact_validates_against_json_schema",
            ),
            junit_expected_tests=16,
            junit_path=run_dir / "focused-schema.xml",
        ),
        CommandSpec(
            "schema_artifact_tests",
            (
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                "tests/test_rke_schema_artifacts.py",
                "-q",
                "--durations=20",
                "--basetemp",
                str(python_basetemp / "schema-artifacts"),
            ),
            root,
            ("tests/test_rke_schema_artifacts.py",),
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
                str(python_basetemp / "gates"),
            ),
            root,
            PYTHON_GATE_TESTS,
        ),
        CommandSpec(
            "representative_evaluation_tests",
            (
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                *REPRESENTATIVE_EVALUATION_TESTS,
                "-q",
                "--junitxml",
                str(run_dir / "representative-evaluation.xml"),
                "--basetemp",
                str(python_basetemp / "representative-evaluation"),
            ),
            root,
            REPRESENTATIVE_EVALUATION_TESTS,
            junit_expected_tests=15,
            junit_path=run_dir / "representative-evaluation.xml",
        ),
        CommandSpec(
            "python_integration_contract_tests",
            (
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                *PYTHON_INTEGRATION_CONTRACT_TESTS,
                "-q",
                "-s",
                "--junitxml",
                str(run_dir / "python-integration.xml"),
                "--basetemp",
                str(python_basetemp / "integration"),
            ),
            root,
            PYTHON_INTEGRATION_CONTRACT_TESTS,
            junit_expected_tests=2,
            junit_path=run_dir / "python-integration.xml",
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
            (
                "pnpm",
                "exec",
                "vitest",
                "run",
                *TYPESCRIPT_GATE_TESTS,
                "--no-file-parallelism",
            ),
            root / "mosaic-ts",
            tuple(f"mosaic-ts/{path}" for path in TYPESCRIPT_GATE_TESTS),
        ),
        CommandSpec(
            "typescript_integration_contract_tests",
            (
                "pnpm",
                "exec",
                "vitest",
                "run",
                "test/daily_cycle.test.ts",
                "test/dashboard.test.tsx",
                "-t",
                TYPESCRIPT_INTEGRATION_PATTERN,
                "--reporter=json",
                "--outputFile",
                str(run_dir / "typescript-integration.json"),
            ),
            root / "mosaic-ts",
            (
                "mosaic-ts/test/daily_cycle.test.ts:backtest position carry-over",
                "mosaic-ts/test/dashboard.test.tsx:Dashboard",
            ),
            json_expected_passed_tests=5,
            json_report_path=run_dir / "typescript-integration.json",
        ),
        CommandSpec(
            "bundled_prompt_contract",
            (
                "pnpm",
                "dev",
                "prompts",
                "check-bundled-contract",
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
        _private_knot_ref_spec(root, "domain_catalog_reproducible"),
        _private_knot_ref_spec(root, "evaluation_contract_reproducible"),
        CommandSpec(
            "git_diff_check",
            ("git", "diff", "--check"),
            root,
            ("git:working-tree",),
        ),
    )


def _private_knot_ref_spec(root: Path, check_id: str) -> CommandSpec:
    return CommandSpec(
        check_id,
        ("uv", "run", "python", "scripts/check_private_knot_boundary.py"),
        root,
        (str(PRIVATE_KNOT_ASSETS_REF_PATH),),
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
    if spec.junit_path is not None:
        spec.junit_path.unlink(missing_ok=True)
    if spec.json_report_path is not None:
        spec.json_report_path.unlink(missing_ok=True)
    if spec.compare_output_to is not None:
        Path(spec.argv[-1]).unlink(missing_ok=True)
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
    if spec.junit_expected_tests is not None:
        junit_reasons = _validate_junit_receipt(spec)
        if junit_reasons:
            status = "fail"
            reasons.extend(junit_reasons)
    if spec.json_expected_passed_tests is not None:
        json_reasons = _validate_json_test_receipt(spec)
        if json_reasons:
            status = "fail"
            reasons.extend(json_reasons)
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    completed_at = utc_now()
    stdout = result.stdout or b""
    stderr = result.stderr or b""
    measurements = _extract_measurements(stdout)
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
        "measurements": measurements,
    }


def _validate_junit_receipt(spec: CommandSpec) -> list[str]:
    if spec.junit_path is None or not spec.junit_path.is_file():
        return ["JUNIT_RECEIPT_MISSING"]
    try:
        root = ET.parse(spec.junit_path).getroot()
    except (OSError, ET.ParseError):
        return ["JUNIT_RECEIPT_INVALID"]
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        return ["JUNIT_RECEIPT_INVALID"]

    def total(field: str) -> int:
        return sum(int(suite.attrib.get(field, "0")) for suite in suites)

    tests = total("tests")
    failures = total("failures")
    errors = total("errors")
    skipped = total("skipped")
    reasons: list[str] = []
    if tests != spec.junit_expected_tests:
        reasons.append("JUNIT_TEST_COUNT_MISMATCH")
    if failures or errors:
        reasons.append("JUNIT_TEST_FAILURE")
    if skipped:
        reasons.append("JUNIT_SKIP_NOT_ALLOWED")
    return reasons


def _validate_json_test_receipt(spec: CommandSpec) -> list[str]:
    if spec.json_report_path is None or not spec.json_report_path.is_file():
        return ["JSON_TEST_RECEIPT_MISSING"]
    try:
        receipt = _load_json(spec.json_report_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return ["JSON_TEST_RECEIPT_INVALID"]
    reasons: list[str] = []
    if receipt.get("numPassedTests") != spec.json_expected_passed_tests:
        reasons.append("JSON_TEST_PASS_COUNT_MISMATCH")
    if receipt.get("numFailedTests") != 0 or receipt.get("numFailedTestSuites") != 0:
        reasons.append("JSON_TEST_FAILURE")
    return reasons


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
        "measurements": {},
    }


def _extract_measurements(stdout: bytes) -> dict[str, int | float | str]:
    prefix = "PROMPT_EVOLUTION_MEASUREMENTS="
    measurements: dict[str, int | float | str] = {}
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if prefix not in line:
            continue
        candidate = line.split(prefix, 1)[1].strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, (int, float, str)):
                measurements[key] = value
    return measurements


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
    agents = runtime_manifest.get("agents")
    expected_stage_count = (
        sum(len(row.get("stages", [])) for row in agents if isinstance(row, Mapping))
        if isinstance(agents, list)
        else 0
    )
    expected_source_rows = expected_stage_count * 2
    expected_row_count = expected_source_rows * 2
    if expected_stage_count < 1 or not isinstance(rows, list) or len(rows) != expected_row_count:
        reasons.append("PROMPT_BUDGET_ROW_COUNT_MISMATCH")
        rows = []
    private_rows = [row for row in rows if row.get("source") == "private"]
    bundled_rows = [row for row in rows if row.get("source") == "bundled"]
    if (
        len(private_rows) != expected_source_rows
        or len(bundled_rows) != expected_source_rows
    ):
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


def verify_performance_budget(
    root: Path,
    checks: Sequence[Mapping[str, Any]],
) -> tuple[Status, list[str]]:
    reasons: list[str] = []
    try:
        budget = _load_json(root / PERFORMANCE_BUDGET_PATH)
    except (OSError, json.JSONDecodeError, ValueError):
        return "fail", ["PERFORMANCE_BUDGET_UNREADABLE"]

    declared_hash = budget.get("manifest_hash")
    without_hash = dict(budget)
    without_hash.pop("manifest_hash", None)
    if declared_hash != canonical_hash(without_hash):
        reasons.append("PERFORMANCE_BUDGET_HASH_MISMATCH")

    checks_by_id = {
        str(check.get("check_id")): check
        for check in checks
        if isinstance(check, Mapping)
    }
    timing_budgets = budget.get("timing_budgets")
    if not isinstance(timing_budgets, list) or not timing_budgets:
        reasons.append("PERFORMANCE_TIMING_BUDGETS_MISSING")
        timing_budgets = []
    seen: set[str] = set()
    for timing_budget in timing_budgets:
        if not isinstance(timing_budget, Mapping):
            reasons.append("PERFORMANCE_TIMING_BUDGET_INVALID")
            continue
        check_id = str(timing_budget.get("check_id") or "")
        if not check_id or check_id in seen:
            reasons.append("PERFORMANCE_CHECK_ID_DUPLICATE_OR_MISSING")
            continue
        seen.add(check_id)
        try:
            baseline_ms = int(timing_budget["baseline_duration_ms"])
            multiplier = float(timing_budget["regression_multiplier"])
            absolute_cap_ms = int(timing_budget["absolute_cap_ms"])
            effective_cap_ms = int(timing_budget["effective_cap_ms"])
        except (KeyError, TypeError, ValueError):
            reasons.append(f"PERFORMANCE_BUDGET_INVALID:{check_id}")
            continue
        expected_cap = min(absolute_cap_ms, int(baseline_ms * multiplier))
        if (
            baseline_ms <= 0
            or multiplier != 1.5
            or absolute_cap_ms <= 0
            or effective_cap_ms != expected_cap
        ):
            reasons.append(f"PERFORMANCE_CAP_DERIVATION_INVALID:{check_id}")
            continue
        receipt = checks_by_id.get(check_id)
        if receipt is None:
            reasons.append(f"PERFORMANCE_RECEIPT_MISSING:{check_id}")
            continue
        if receipt.get("status") != "pass":
            reasons.append(f"PERFORMANCE_RECEIPT_NOT_PASS:{check_id}")
            continue
        duration_ms = receipt.get("duration_ms")
        if not isinstance(duration_ms, int) or duration_ms > effective_cap_ms:
            reasons.append(f"PERFORMANCE_DURATION_EXCEEDED:{check_id}")
    if seen != PERFORMANCE_TIMING_CHECK_IDS:
        reasons.append("PERFORMANCE_CHECK_SET_MISMATCH")

    fixture_budget = budget.get("fixture_budget")
    fixture_receipt = checks_by_id.get("python_integration_contract_tests")
    if not isinstance(fixture_budget, Mapping) or not isinstance(
        fixture_receipt, Mapping
    ):
        reasons.append("PERFORMANCE_FIXTURE_RECEIPT_MISSING")
    else:
        if fixture_budget.get("test_id") not in PYTHON_INTEGRATION_CONTRACT_TESTS:
            reasons.append("PERFORMANCE_FIXTURE_TEST_ID_MISMATCH")
        forbidden_prefixes = fixture_budget.get("forbidden_private_prefixes")
        if not isinstance(forbidden_prefixes, list) or not {
            "report_intelligence/pdfs",
            "report_intelligence/markdown",
            "report_intelligence/mineru",
        }.issubset(forbidden_prefixes):
            reasons.append("PERFORMANCE_PRIVATE_PREFIX_COVERAGE_MISSING")
        measurements = fixture_receipt.get("measurements")
        if not isinstance(measurements, Mapping):
            reasons.append("PERFORMANCE_FIXTURE_MEASUREMENTS_MISSING")
        else:
            for measurement, cap_field in (
                ("pytest_registry_copy_bytes", "max_copied_bytes"),
                ("pytest_registry_copy_files", "max_copied_files"),
            ):
                measured = measurements.get(measurement)
                cap = fixture_budget.get(cap_field)
                if not isinstance(measured, int) or not isinstance(cap, int):
                    reasons.append(f"PERFORMANCE_FIXTURE_MEASUREMENT_INVALID:{measurement}")
                elif measured > cap:
                    reasons.append(f"PERFORMANCE_FIXTURE_BUDGET_EXCEEDED:{measurement}")
        opt_in_env = str(fixture_budget.get("private_fixture_opt_in_env") or "")
        if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get(opt_in_env):
            reasons.append("PRIVATE_FIXTURE_OPT_IN_SET_IN_CI")

    runner = budget.get("runner_class")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if not isinstance(runner, Mapping):
            reasons.append("PERFORMANCE_RUNNER_CLASS_MISSING")
        else:
            required_environment = runner.get("required_environment")
            if not isinstance(required_environment, Mapping):
                reasons.append("PERFORMANCE_RUNNER_ENVIRONMENT_MISSING")
            else:
                for key, expected in required_environment.items():
                    if os.environ.get(str(key)) != expected:
                        reasons.append(f"PERFORMANCE_RUNNER_MISMATCH:{key}")

    return ("pass" if not reasons else "fail"), sorted(set(reasons))


def verify_documentation_contract(root: Path) -> tuple[Status, list[str]]:
    requirements = {
        Path("docs/runbooks/position_aware_prompt_evolution.md"): (
            "MOSAIC_KNOT_RUNTIME_ROOT",
            "check_private_knot_boundary.py",
            "check_prompt_leaks.py",
            "canary",
            "rollback",
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


def ci_context_from_environment(root: Path) -> dict[str, Any]:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return {
            "provider": "local",
            "repository": "",
            "workflow_ref": "",
            "job_name": "",
            "event_name": "local",
            "run_id": "local",
            "run_attempt": "",
            "run_url": "",
            "tested_sha": git_value(root, "rev-parse", "HEAD"),
            "source_head_sha": "",
            "base_sha": "",
            "context_complete": False,
            "python_status": "blocked",
            "typescript_status": "blocked",
        }

    event_payload: Mapping[str, Any] = {}
    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", ""))
    try:
        loaded_event = _load_json(event_path)
        event_payload = loaded_event
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    pull_request = event_payload.get("pull_request")
    if isinstance(pull_request, Mapping):
        head = pull_request.get("head")
        base = pull_request.get("base")
        source_head_sha = str(head.get("sha") or "") if isinstance(head, Mapping) else ""
        base_sha = str(base.get("sha") or "") if isinstance(base, Mapping) else ""
    else:
        source_head_sha = str(event_payload.get("after") or os.environ.get("GITHUB_SHA", ""))
        base_sha = str(event_payload.get("before") or "")

    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = (
        f"https://github.com/{repository}/actions/runs/{run_id}"
        if repository and run_id
        else ""
    )
    context = {
        "provider": "github_actions",
        "repository": repository,
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF", ""),
        "job_name": os.environ.get("PROMPT_EVOLUTION_CI_JOB_NAME", ""),
        "event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
        "run_id": run_id,
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "run_url": run_url,
        "tested_sha": os.environ.get("GITHUB_SHA", ""),
        "source_head_sha": source_head_sha,
        "base_sha": base_sha,
        "python_status": os.environ.get(
            "PROMPT_EVOLUTION_PYTHON_CI_STATUS", "blocked"
        ),
        "typescript_status": os.environ.get(
            "PROMPT_EVOLUTION_TYPESCRIPT_CI_STATUS", "blocked"
        ),
    }
    required_values = (
        context["repository"],
        context["workflow_ref"],
        context["run_id"],
        context["run_attempt"],
        context["run_url"],
        context["tested_sha"],
        context["source_head_sha"],
    )
    context["context_complete"] = bool(
        all(required_values)
        and event_path.is_file()
        and context["job_name"] == "Prompt evolution delivery (G0-G7)"
        and context["event_name"] in {"pull_request", "push"}
    )
    return context


def ci_receipt(
    check_id: str,
    *,
    context: Mapping[str, Any],
    status: str,
    code_commit: str,
) -> dict[str, Any]:
    run_url = str(context.get("run_url") or "")
    if context.get("provider") != "github_actions":
        return internal_receipt(
            check_id,
            "blocked",
            reason_codes=("UPSTREAM_CI_NOT_GITHUB_ACTIONS",),
            evidence_refs=(run_url,) if run_url else (),
        )
    if context.get("context_complete") is not True:
        return internal_receipt(
            check_id,
            "blocked",
            reason_codes=("UPSTREAM_CI_CONTEXT_INCOMPLETE",),
            evidence_refs=(run_url,) if run_url else (),
        )
    if context.get("tested_sha") != code_commit:
        return internal_receipt(
            check_id,
            "fail",
            reason_codes=("UPSTREAM_CI_TESTED_SHA_MISMATCH",),
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


def validate_upstream_ci_binding(
    upstream_ci: Mapping[str, Any],
    *,
    code_commit: str,
) -> list[str]:
    provider = upstream_ci.get("provider")
    if provider == "local":
        return [] if upstream_ci.get("context_complete") is False else [
            "local_ci_context_must_be_incomplete"
        ]
    if provider != "github_actions":
        return ["upstream_ci_provider_invalid"]

    reasons: list[str] = []
    repository = str(upstream_ci.get("repository") or "")
    run_id = str(upstream_ci.get("run_id") or "")
    expected_url = (
        f"https://github.com/{repository}/actions/runs/{run_id}"
        if repository and run_id
        else ""
    )
    if upstream_ci.get("context_complete") is not True:
        reasons.append("upstream_ci_context_incomplete")
    if upstream_ci.get("job_name") != "Prompt evolution delivery (G0-G7)":
        reasons.append("upstream_ci_job_name_mismatch")
    if upstream_ci.get("run_url") != expected_url:
        reasons.append("upstream_ci_run_url_mismatch")
    if not str(upstream_ci.get("workflow_ref") or "").startswith(
        f"{repository}/.github/workflows/ci.yml@"
    ):
        reasons.append("upstream_ci_workflow_ref_mismatch")
    if upstream_ci.get("event_name") not in {"pull_request", "push"}:
        reasons.append("upstream_ci_event_invalid")
    if upstream_ci.get("tested_sha") != code_commit:
        reasons.append("upstream_ci_tested_sha_mismatch")
    for field in ("tested_sha", "source_head_sha"):
        value = str(upstream_ci.get(field) or "")
        if len(value) not in {40, 64} or any(char not in "0123456789abcdef" for char in value):
            reasons.append(f"upstream_ci_{field}_invalid")
    base_sha = str(upstream_ci.get("base_sha") or "")
    if upstream_ci.get("event_name") == "pull_request" and (
        len(base_sha) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in base_sha)
    ):
        reasons.append("upstream_ci_base_sha_invalid")
    if not str(upstream_ci.get("run_attempt") or "").isdigit():
        reasons.append("upstream_ci_run_attempt_invalid")
    return sorted(set(reasons))


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
    run = artifact.get("run")
    upstream_ci = artifact.get("upstream_ci")
    if isinstance(run, Mapping) and isinstance(upstream_ci, Mapping):
        reasons.extend(
            validate_upstream_ci_binding(
                upstream_ci,
                code_commit=str(run.get("code_commit") or ""),
            )
        )
    else:
        reasons.append("upstream_ci_binding_missing")
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
        measurements = check.get("measurements")
        if check_id == "python_integration_contract_tests":
            if not isinstance(measurements, Mapping) or set(measurements) != {
                "pytest_registry_copy_bytes",
                "pytest_registry_copy_files",
            }:
                reasons.append("integration_measurements_invalid")
        elif measurements != {}:
            reasons.append(f"unexpected_measurements:{check_id}")
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
    recomputed_internal: dict[str, dict[str, Any]] = {}
    prompt_budget_status, prompt_budget_reasons = verify_prompt_budget_attestation(root)
    recomputed_internal["prompt_budget_attestation"] = internal_receipt(
        "prompt_budget_attestation",
        prompt_budget_status,
        reason_codes=prompt_budget_reasons,
        evidence_refs=(str(TOKEN_BUDGET_PATH),),
    )
    performance_status, performance_reasons = verify_performance_budget(
        root, list(checks_by_id.values())
    )
    recomputed_internal["performance_budget"] = internal_receipt(
        "performance_budget",
        performance_status,
        reason_codes=performance_reasons,
        evidence_refs=(str(PERFORMANCE_BUDGET_PATH),),
    )
    docs_status, docs_reasons = verify_documentation_contract(root)
    recomputed_internal["documentation_contract"] = internal_receipt(
        "documentation_contract",
        docs_status,
        reason_codes=docs_reasons,
        evidence_refs=tuple(
            path.as_posix()
            for path in DELIVERY_INPUT_PATHS
            if path.as_posix().startswith("docs/")
        ),
    )
    for check_id, expected in recomputed_internal.items():
        actual = checks_by_id.get(check_id, {})
        for field in (
            "executor",
            "command",
            "working_directory",
            "exit_code",
            "status",
            "reason_codes",
            "stdout_sha256",
            "stderr_sha256",
            "evidence_refs",
            "measurements",
        ):
            if actual.get(field) != expected.get(field):
                reasons.append(f"internal_receipt_mismatch:{check_id}:{field}")
    if isinstance(run, Mapping) and isinstance(upstream_ci, Mapping):
        for check_id, status_field in (
            ("python_ci", "python_status"),
            ("typescript_ci", "typescript_status"),
        ):
            expected = ci_receipt(
                check_id,
                context=upstream_ci,
                status=str(upstream_ci.get(status_field) or "blocked"),
                code_commit=str(run.get("code_commit") or ""),
            )
            actual = checks_by_id.get(check_id, {})
            for field in (
                "executor",
                "command",
                "working_directory",
                "exit_code",
                "status",
                "reason_codes",
                "stdout_sha256",
                "stderr_sha256",
                "evidence_refs",
                "measurements",
            ):
                if actual.get(field) != expected.get(field):
                    reasons.append(f"upstream_ci_receipt_mismatch:{check_id}:{field}")
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
    for field in ("run", "prompt_sources", "inputs", "gates", "conditions", "summary"):
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
    upstream_ci: Mapping[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    run_dir = output.parent / f"run-{run_id}"
    prepare_run_dir(run_dir)
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
    performance_status, performance_reasons = verify_performance_budget(root, checks)
    checks.append(
        internal_receipt(
            "performance_budget",
            performance_status,
            reason_codes=performance_reasons,
            evidence_refs=(str(PERFORMANCE_BUDGET_PATH),),
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
            context=upstream_ci,
            status=str(upstream_ci.get("python_status") or "blocked"),
            code_commit=code_commit,
        )
    )
    checks.append(
        ci_receipt(
            "typescript_ci",
            context=upstream_ci,
            status=str(upstream_ci.get("typescript_status") or "blocked"),
            code_commit=code_commit,
        )
    )
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
