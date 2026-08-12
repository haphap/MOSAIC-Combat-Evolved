"""Verify the active Prompt-optimizer privacy and legacy-runtime boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from mosaic.scorecard.canonical_json import canonical_hash


ROOT = Path(__file__).resolve().parents[1]
PROMPT_CHECKS = ROOT / "registry" / "prompt_checks"
RUNTIME_AGENT_MANIFEST_PATH = PROMPT_CHECKS / "runtime_agent_manifest_v5.json"
PROMPT_RELEASE_CONTRACT_REF_PATH = (
    PROMPT_CHECKS / "prompt_release_contract_ref_v2.json"
)
EXECUTION_RELEASE_ARCHIVE_ROOT = PROMPT_CHECKS / "execution_behavior_releases"
PROMPT_TOKEN_BUDGET_MANIFEST_PATH = (
    PROMPT_CHECKS / "prompt_token_budget_manifest_v1.json"
)
AGENT_TOOL_CONTRACT_MANIFEST_PATH = (
    PROMPT_CHECKS / "agent_tool_contract_manifest_v1.json"
)
PRIVATE_PROMPT_BOOTSTRAP_PATH = Path(
    "registry/knot/prompt_parameter_bootstrap_release_v1.json"
)
PUBLIC_LEGACY_INVENTORY_PATH = ROOT / "registry" / "knot" / "legacy_read_only_v2.json"
PRIVATE_LEGACY_INVENTORY_PATH = Path("registry/knot/legacy_read_only_v1.json")
PRIVATE_PACKAGE_PATH = Path("runtime/typescript/package.json")
PRIVATE_BUILD_CONFIG_PATH = Path("runtime/typescript/tsconfig.build.json")
PRIVATE_ENTRY_PATH = Path("runtime/typescript/src/index.ts")
ACTIVE_PRIVATE_PACKAGE = "@mosaic/private-knot-prompt-mutator"
ACTIVE_PRIVATE_EXPORTS = {
    'export * from "./autoresearch/prompt_candidate_repository.js";',
    'export * from "./autoresearch/prompt_behavior_contract.js";',
    'export * from "./autoresearch/prompt_mutator.js";',
    'export * from "./autoresearch/prompt_parameter_contract.js";',
    'export * from "./autoresearch/prompt_parameter_renderer.js";',
    'export * from "./autoresearch/prompt_parameter_state.js";',
}
ACTIVE_PRIVATE_BUILD_ENTRIES = ["src/index.ts", "src/cli.ts"]
PRIVATE_ACTIVE_REQUIRED_SOURCES = {
    "autoresearch/prompt_behavior_contract.ts",
    "autoresearch/prompt_candidate_repository.ts",
    "autoresearch/prompt_mutator.ts",
    "autoresearch/prompt_parameter_contract.ts",
    "autoresearch/prompt_parameter_inventory.ts",
    "autoresearch/prompt_parameter_seed_inventory.ts",
    "autoresearch/prompt_parameter_renderer.ts",
    "autoresearch/prompt_parameter_state.ts",
    "autoresearch/prompt_training_evaluator.ts",
}
PRIVATE_LEGACY_IMPORT_MARKERS = (
    "domain_evaluator",
    "domain_metrics",
    "effect_runtime",
    "knot_cio_control_shadow",
    "knot_contract",
    "knot_v2",
    "pair_assignment",
    "private_runtime_manifest",
    "public_adapter",
    "replay_capsule",
    "research_knobs",
    "strict_receipt",
    "transaction_coordinator",
)
PRIVATE_IMPORT_RE = re.compile(
    r'(?:\bfrom\s+|\bimport\s*(?:\(\s*)?)["\']([^"\']+)["\']'
)
COHORT_BEHAVIOR_RE = re.compile(
    r"<!-- cohort-behavior:start -->\n([\s\S]*?)\n<!-- cohort-behavior:end -->"
)
CALIBRATION_MARKERS = ("判断校准：", "Decision calibration:")
CALIBRATION_CLAUSE_RE = re.compile(r"[。！？；.!?;]+")
RUNTIME_REBASE_PROMPT_RE = re.compile(
    r"^prompts/mosaic/cohort_default/sector/"
    r"(?:agriculture|biotech|consumer|energy|financials|industrials|"
    r"real_estate_construction|relationship_mapper|semiconductor|technology)"
    r"\.(?:zh|en)\.md$"
)
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MIN_CALIBRATION_FINGERPRINT_LENGTH = 12
FORBIDDEN_PUBLIC_ASSETS = (
    PROMPT_CHECKS / "knot_runtime_contract_manifest_v2.json",
    PROMPT_CHECKS / "domain_knob_catalog_v1.json",
    PROMPT_CHECKS / "domain_knob_evaluation_contract_v1.json",
    ROOT / "schemas" / "research_knobs_v1.schema.json",
    ROOT / "schemas" / "domain_knob_catalog_v1.schema.json",
    ROOT / "schemas" / "domain_knob_values_v1.schema.json",
    ROOT / "schemas" / "domain_knob_evaluation_contract_v1.schema.json",
    ROOT / "schemas" / "prompt_governance_values_v1.schema.json",
    ROOT / "schemas" / "prompt_mutation_transaction_v1.schema.json",
    ROOT / "schemas" / "prompt_mutation_recovery_v1.schema.json",
    ROOT / "mosaic-ts" / "src" / "agents" / "helpers" / "research_knobs.ts",
    ROOT / "mosaic-ts" / "src" / "agents" / "prompts" / "domain_knob_catalog.ts",
    ROOT / "mosaic-ts" / "src" / "agents" / "prompts" / "domain_knob_registry.ts",
    ROOT / "mosaic-ts" / "src" / "agents" / "prompts" / "prompt_ir_registry.ts",
    ROOT / "mosaic-ts" / "src" / "agents" / "prompts" / "prompt_governance_registry.ts",
    ROOT / "mosaic-ts" / "src" / "agents" / "prompts" / "tool_metric_registry.ts",
    ROOT / "mosaic-ts" / "src" / "autoresearch" / "transaction_coordinator.ts",
    ROOT / "mosaic-ts" / "src" / "agents" / "helpers" / "private_knot_boundary.ts",
    ROOT
    / "mosaic-ts"
    / "src"
    / "agents"
    / "prompts"
    / "private_knot_prompt_checker.ts",
    ROOT
    / "mosaic-ts"
    / "src"
    / "agents"
    / "prompts"
    / "private_knot_stage_enablement.ts",
    ROOT / "mosaic-ts" / "src" / "autoresearch" / "knot_contract.ts",
    ROOT / "mosaic-ts" / "src" / "autoresearch" / "private_knot_runtime.ts",
    ROOT / "mosaic" / "autoresearch" / "private_knot_runtime.py",
    PROMPT_CHECKS / "private_knot_assets_ref_v1.json",
    PROMPT_CHECKS / "knot_runtime_contract_ref_v2.json",
    ROOT / "schemas" / "private_knot_assets_ref_v1.schema.json",
    ROOT / "schemas" / "knot_runtime_contract_ref_v2.schema.json",
)
FORBIDDEN_SOURCE_MARKERS = (
    "confidence_caps",
    "evidence_weights",
    "mutation_targets",
    "knob_patches",
)
SOURCE_MARKER_ALLOWLIST = {
    ROOT / "mosaic-ts" / "src" / "agents" / "prompts" / "loader.ts",
    ROOT
    / "mosaic-ts"
    / "src"
    / "agents"
    / "prompts"
    / "private_knot_prompt_markers.ts",
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), label)


def _private_active_source_closure(private_root: Path) -> set[str]:
    source_root = (private_root / "runtime/typescript/src").resolve()
    pending = [source_root / "index.ts", source_root / "cli.ts"]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        if not path.is_file():
            raise ValueError(f"active private source is missing: {path}")
        visited.add(path)
        source = path.read_text(encoding="utf-8")
        for specifier in PRIVATE_IMPORT_RE.findall(source):
            if any(marker in specifier for marker in PRIVATE_LEGACY_IMPORT_MARKERS):
                raise ValueError(
                    f"active private Prompt path imports legacy protocol: {specifier}"
                )
            if not specifier.startswith("."):
                continue
            candidate = (path.parent / specifier).resolve()
            if candidate.suffix == ".js":
                candidate = candidate.with_suffix(".ts")
            elif not candidate.suffix:
                candidate = candidate.with_suffix(".ts")
            try:
                candidate.relative_to(source_root)
            except ValueError as exc:
                raise ValueError("active private Prompt import escapes source root") from exc
            pending.append(candidate)
    return {str(path.relative_to(source_root)) for path in visited}


def _private_root() -> Path | None:
    configured = (
        os.environ.get("MOSAIC_PROMPTS_REPO")
        or os.environ.get("MOSAIC_PRIVATE_PROMPT_REPO")
    )
    if not configured:
        return None
    root = Path(configured).expanduser().resolve()
    if root.name == "mosaic" and root.parent.name == "prompts":
        root = root.parents[1]
    return root


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _tracked_public_texts(public_root: Path) -> list[tuple[str, str, str]]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(public_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    root = public_root.resolve()
    texts: list[tuple[str, str, str]] = []
    for raw_ref in result.stdout.split(b"\0"):
        if not raw_ref:
            continue
        ref = raw_ref.decode("utf-8")
        path = public_root / ref
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError("public path escapes repository") from exc
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        texts.append((ref, text, _normalized_text(text)))
    staged = subprocess.run(
        [
            "git",
            "-C",
            str(public_root),
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--diff-filter=ACMR",
        ],
        check=True,
        capture_output=True,
    )
    for raw_ref in staged.stdout.split(b"\0"):
        if not raw_ref:
            continue
        ref = raw_ref.decode("utf-8")
        blob = subprocess.run(
            ["git", "-C", str(public_root), "show", f":{ref}"],
            check=True,
            capture_output=True,
        ).stdout
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue
        texts.append((ref, text, _normalized_text(text)))
    return texts


def _private_content_fingerprints(private_root: Path) -> tuple[set[str], set[str]]:
    contract = _read_object(
        private_root / "registry/knot/prompt_parameter_contract_v1.json",
        "private Prompt parameter contract",
    )
    parameters = contract.get("parameters")
    if not isinstance(parameters, list):
        raise ValueError("private Prompt parameter inventory is missing")
    private_ids: set[str] = set()
    for raw_parameter in parameters:
        parameter = _mapping(raw_parameter, "private Prompt parameter")
        parameter_id = parameter.get("parameterId")
        disposition = parameter.get("disposition")
        if not isinstance(parameter_id, str) or not parameter_id:
            raise ValueError("private Prompt parameter ID is invalid")
        if disposition not in {
            "PROMPT_KNOT",
            "DETERMINISTIC_ACTIVE",
            "DETERMINISTIC_GAP",
            "RETIRED",
        }:
            raise ValueError("private Prompt parameter disposition is invalid")
        if disposition != "DETERMINISTIC_ACTIVE":
            private_ids.add(parameter_id)

    calibration_fingerprints: set[str] = set()
    prompts_root = private_root / "prompts/mosaic"
    for path in prompts_root.rglob("*.md"):
        prompt = path.read_text(encoding="utf-8")
        matches = COHORT_BEHAVIOR_RE.findall(prompt)
        if len(matches) != 1:
            raise ValueError("private Prompt cohort behavior block is invalid")
        behavior = matches[0]
        matched_markers = [marker for marker in CALIBRATION_MARKERS if marker in behavior]
        if len(matched_markers) != 1:
            raise ValueError("private Prompt calibration marker is invalid")
        suffix = _normalized_text(behavior.split(matched_markers[0], 1)[1])
        if len(suffix) < MIN_CALIBRATION_FINGERPRINT_LENGTH:
            raise ValueError("private Prompt calibration suffix is too short")
        calibration_fingerprints.add(suffix)
        calibration_fingerprints.update(
            clause
            for clause in CALIBRATION_CLAUSE_RE.split(suffix)
            if len(clause) >= MIN_CALIBRATION_FINGERPRINT_LENGTH
        )
    if not calibration_fingerprints:
        raise ValueError("private Prompt calibration inventory is empty")
    return private_ids, calibration_fingerprints


def _check_cross_repository_content_boundary(
    public_root: Path, private_root: Path
) -> None:
    private_ids, calibration_fingerprints = _private_content_fingerprints(private_root)
    for ref, text, normalized in _tracked_public_texts(public_root):
        if any(parameter_id in text for parameter_id in private_ids):
            raise ValueError(
                f"private Prompt parameter identifier leaked into public path: {ref}"
            )
        if any(fingerprint in normalized for fingerprint in calibration_fingerprints):
            raise ValueError(
                f"private Prompt calibration text leaked into public path: {ref}"
            )


def _check_execution_release() -> Mapping[str, str]:
    contract_ref = _read_object(
        PROMPT_RELEASE_CONTRACT_REF_PATH, "Prompt Release contract ref"
    )
    if contract_ref.get("schema_version") != "prompt_release_contract_ref_v2":
        raise ValueError("Prompt Release contract ref version mismatch")
    sources = _mapping(contract_ref.get("sources"), "Prompt Release sources")
    binding = _mapping(
        sources.get("execution_behavior_release_archive"),
        "execution behavior release binding",
    )
    archive_ref = binding.get("path")
    release_id = binding.get("release_id")
    release_hash = binding.get("release_hash")
    if not all(isinstance(value, str) for value in (archive_ref, release_id, release_hash)):
        raise ValueError("execution behavior release binding is incomplete")
    match = re.fullmatch(
        r"registry/prompt_checks/execution_behavior_releases/"
        r"([0-9a-f]{64})--([0-9a-f]{64})\.json",
        archive_ref,
    )
    if (
        match is None
        or release_id != f"execution-behavior-release:{match.group(1)}"
        or release_hash != f"sha256:{match.group(2)}"
    ):
        raise ValueError("execution behavior release archive ref is not content-addressed")
    archive_path = (ROOT / archive_ref).resolve()
    if archive_path.parent != EXECUTION_RELEASE_ARCHIVE_ROOT.resolve():
        raise ValueError("execution behavior release archive escapes its registry")
    release = _read_object(archive_path, "execution behavior release archive")
    expected_keys = {
        "schema_version",
        "execution_behavior_release_id",
        "execution_behavior_release_hash",
        "provider_binding",
        "active_production_variants",
        "execution_contracts",
    }
    if (
        set(release) != expected_keys
        or release.get("schema_version") != "execution_behavior_release_manifest_v4"
        or release.get("execution_behavior_release_id") != release_id
        or release.get("execution_behavior_release_hash") != release_hash
    ):
        raise ValueError("execution behavior release archive identity mismatch")
    if (
        not isinstance(release.get("active_production_variants"), list)
        or len(release["active_production_variants"]) != 16
        or not isinstance(release.get("execution_contracts"), list)
        or len(release["execution_contracts"]) != 54
    ):
        raise ValueError("execution behavior release archive schema mismatch")
    without_hash = {
        key: release[key]
        for key in (
            "schema_version",
            "execution_behavior_release_id",
            "provider_binding",
            "active_production_variants",
            "execution_contracts",
        )
    }
    if canonical_hash(without_hash) != release_hash:
        raise ValueError("execution behavior release archive hash mismatch")
    release_content = {
        key: release[key]
        for key in (
            "schema_version",
            "provider_binding",
            "active_production_variants",
            "execution_contracts",
        )
    }
    expected_release_id = (
        "execution-behavior-release:"
        + canonical_hash(release_content).removeprefix("sha256:")
    )
    if expected_release_id != release_id:
        raise ValueError("execution behavior release ID mismatch")
    return {
        "archive_ref": archive_ref,
        "release_id": release_id,
        "release_hash": release_hash,
    }


def _prompt_build_source_commits() -> Mapping[str, Any]:
    manifest = _read_object(
        PROMPT_TOKEN_BUDGET_MANIFEST_PATH, "Prompt token budget manifest"
    )
    if manifest.get("schema_version") != "prompt_token_budget_manifest_v1":
        raise ValueError("Prompt token budget manifest version mismatch")
    source_commits = _mapping(
        manifest.get("source_commits"), "Prompt token budget source commits"
    )
    private_commit = source_commits.get("private")
    if (
        set(source_commits) != {"private", "bundled"}
        or not isinstance(private_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", private_commit) is None
        or not isinstance(source_commits.get("bundled"), str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commits["bundled"]) is None
    ):
        raise ValueError("Prompt token budget source commits are invalid")
    return source_commits


def _private_prompt_build_commit() -> str:
    return str(_prompt_build_source_commits()["private"])


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _check_private_token_budget_rows(private_root: Path) -> None:
    manifest = _read_object(
        PROMPT_TOKEN_BUDGET_MANIFEST_PATH, "Prompt token budget manifest"
    )
    if manifest.get("schema_version") != "prompt_token_budget_manifest_v1":
        raise ValueError("Prompt token budget manifest version mismatch")
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Prompt token budget rows are invalid")

    prompts_root = (private_root / "prompts/mosaic").resolve()
    private_row_count = 0
    for raw_row in rows:
        row = _mapping(raw_row, "Prompt token budget row")
        if row.get("source") != "private":
            continue
        private_row_count += 1
        source_path = row.get("source_path")
        source_sha256 = row.get("source_sha256")
        source_bytes = row.get("source_bytes")
        if (
            not isinstance(source_path, str)
            or not source_path
            or not isinstance(source_sha256, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", source_sha256) is None
            or not isinstance(source_bytes, int)
            or source_bytes < 0
        ):
            raise ValueError("private Prompt token budget row is invalid")
        prompt_path = (prompts_root / source_path).resolve()
        try:
            prompt_path.relative_to(prompts_root)
        except ValueError as exc:
            raise ValueError("private Prompt token budget path escapes prompt root") from exc
        if not prompt_path.is_file():
            raise ValueError("private Prompt token budget source is missing")
        content = prompt_path.read_bytes()
        if _sha256_bytes(content) != source_sha256 or len(content) != source_bytes:
            raise ValueError("private Prompt token budget row mismatch")
    if private_row_count == 0:
        raise ValueError("private Prompt token budget rows are missing")


def _check_runtime_contract_rebase_receipt(
    *,
    private_root: Path,
    receipt: Mapping[str, Any],
    prompt_paths: list[Path],
) -> None:
    expected_keys = {
        "schema_version",
        "previous_release_hash",
        "baseline_commit",
        "public_contract_commit",
        "runtime_contract_authority_hash",
        "affected_prompt_refs",
        "rebase_tool_version",
        "rebased_at",
    }
    affected = receipt.get("affected_prompt_refs")
    if (
        set(receipt) != expected_keys
        or receipt.get("schema_version") != "runtime_contract_rebase_receipt_v1"
        or not isinstance(receipt.get("previous_release_hash"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["previous_release_hash"])
        is None
        or not isinstance(receipt.get("baseline_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", receipt["baseline_commit"]) is None
        or not isinstance(receipt.get("public_contract_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", receipt["public_contract_commit"])
        is None
        or not isinstance(receipt.get("runtime_contract_authority_hash"), str)
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}", receipt["runtime_contract_authority_hash"]
        )
        is None
        or not isinstance(affected, list)
        or len(affected) != 20
        or affected != sorted(set(affected))
        or any(
            not isinstance(ref, str)
            or RUNTIME_REBASE_PROMPT_RE.fullmatch(ref) is None
            for ref in affected
        )
        or receipt.get("rebase_tool_version") != "runtime-contract-rebase-v1"
        or not isinstance(receipt.get("rebased_at"), str)
        or UTC_TIMESTAMP_RE.fullmatch(receipt["rebased_at"]) is None
    ):
        raise ValueError("private Prompt runtime-contract rebase receipt schema mismatch")

    prompt_refs = {path.relative_to(private_root).as_posix() for path in prompt_paths}
    if not set(affected) <= prompt_refs:
        raise ValueError("private Prompt runtime-contract affected roster mismatch")

    authority = _read_object(
        AGENT_TOOL_CONTRACT_MANIFEST_PATH, "Agent tool contract manifest"
    )
    if (
        authority.get("schema_version") != "agent_tool_contract_manifest_v1"
        or authority.get("agent_count") != 27
        or authority.get("execution_stage_count") != 28
        or authority.get("tool_count") != 31
        or canonical_hash(authority)
        != receipt["runtime_contract_authority_hash"]
    ):
        raise ValueError("private Prompt runtime-contract authority hash mismatch")
    if (
        _prompt_build_source_commits()["bundled"]
        != receipt["public_contract_commit"]
    ):
        raise ValueError("private Prompt runtime-contract public commit mismatch")

    baseline = subprocess.run(
        [
            "git",
            "-C",
            str(private_root),
            "show",
            f"{receipt['baseline_commit']}:{PRIVATE_PROMPT_BOOTSTRAP_PATH.as_posix()}",
        ],
        text=True,
        capture_output=True,
    )
    if baseline.returncode != 0:
        raise ValueError("private Prompt runtime-contract baseline release is missing")
    try:
        baseline_release = _mapping(
            json.loads(baseline.stdout), "private Prompt baseline bootstrap"
        )
    except json.JSONDecodeError as exc:
        raise ValueError("private Prompt runtime-contract baseline release is invalid") from exc
    baseline_body = dict(baseline_release)
    baseline_hash = baseline_body.pop("release_hash", None)
    if (
        baseline_hash != receipt["previous_release_hash"]
        or baseline_hash != canonical_hash(baseline_body)
    ):
        raise ValueError("private Prompt runtime-contract baseline release mismatch")

    changed = subprocess.run(
        [
            "git",
            "-C",
            str(private_root),
            "diff",
            "--name-only",
            receipt["baseline_commit"],
            "--",
            "prompts/mosaic",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    changed_prompts = sorted(
        ref.strip()
        for ref in changed
        if RUNTIME_REBASE_PROMPT_RE.fullmatch(ref.strip()) is not None
    )
    if changed_prompts != affected:
        raise ValueError("private Prompt runtime-contract affected Git diff mismatch")
    protected = subprocess.run(
        [
            "git",
            "-C",
            str(private_root),
            "diff",
            "--name-only",
            receipt["baseline_commit"],
            "--",
            "registry/prompt_parameter_states_v1",
            "registry/knot/prompt_parameter_contract_v1.json",
            "registry/knot/prompt_behavior_contract_v1.json",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    if protected.strip():
        raise ValueError("private Prompt runtime-contract state or contract drift")


def _check_private_prompt_bootstrap(private_root: Path) -> None:
    bootstrap = _read_object(
        private_root / PRIVATE_PROMPT_BOOTSTRAP_PATH,
        "private Prompt bootstrap",
    )
    base_keys = {
        "schema_version",
        "release_hash",
        "parameter_contract_hash",
        "behavior_contract_hash",
        "state_tree_hash",
        "prompt_tree_hash",
        "state_count",
        "agent_count",
        "cohort_count",
        "prompt_count",
    }
    actual_keys = frozenset(bootstrap)
    if (
        actual_keys not in {frozenset(base_keys), frozenset(base_keys | {"rebase_receipt"})}
        or bootstrap.get("schema_version")
        != "private_prompt_parameter_bootstrap_release_v1"
        or bootstrap.get("state_count") != 224
        or bootstrap.get("agent_count") != 28
        or bootstrap.get("cohort_count") != 8
        or bootstrap.get("prompt_count") != 448
        or any(
            not isinstance(bootstrap.get(key), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", bootstrap[key]) is None
            for key in (
                "release_hash",
                "parameter_contract_hash",
                "behavior_contract_hash",
                "state_tree_hash",
                "prompt_tree_hash",
            )
        )
    ):
        raise ValueError("private Prompt bootstrap schema mismatch")
    bootstrap_body = dict(bootstrap)
    declared_release_hash = bootstrap_body.pop("release_hash")
    if declared_release_hash != canonical_hash(bootstrap_body):
        raise ValueError("private Prompt bootstrap release hash mismatch")

    parameter_contract = dict(
        _read_object(
            private_root / "registry/knot/prompt_parameter_contract_v1.json",
            "private Prompt parameter contract",
        )
    )
    declared_parameter_hash = parameter_contract.pop("contract_hash", None)
    if (
        declared_parameter_hash != canonical_hash(parameter_contract)
        or bootstrap["parameter_contract_hash"] != declared_parameter_hash
    ):
        raise ValueError("private Prompt parameter contract hash mismatch")
    behavior_contract = _read_object(
        private_root / "registry/knot/prompt_behavior_contract_v1.json",
        "private Prompt behavior contract",
    )
    if bootstrap["behavior_contract_hash"] != canonical_hash(behavior_contract):
        raise ValueError("private Prompt behavior contract hash mismatch")

    prompt_paths = sorted((private_root / "prompts/mosaic").rglob("*.md"))
    state_paths = sorted(
        (private_root / "registry/prompt_parameter_states_v1").rglob("*.json")
    )
    if len(prompt_paths) != 448 or len(state_paths) != 224:
        raise ValueError("private Prompt bootstrap roster mismatch")
    receipt = bootstrap.get("rebase_receipt")
    if receipt is not None:
        _check_runtime_contract_rebase_receipt(
            private_root=private_root,
            receipt=_mapping(receipt, "private Prompt runtime-contract rebase receipt"),
            prompt_paths=prompt_paths,
        )
    prompt_tree_hash = canonical_hash(
        {
            "files": [
                {
                    "ref": path.relative_to(private_root).as_posix(),
                    "content_hash": _sha256_bytes(path.read_bytes()),
                }
                for path in prompt_paths
            ]
        }
    )
    state_tree_hash = canonical_hash(
        {
            "files": [
                {
                    "ref": path.relative_to(private_root).as_posix(),
                    "content_hash": _sha256_bytes(path.read_bytes()),
                }
                for path in state_paths
            ]
        }
    )
    if bootstrap["prompt_tree_hash"] != prompt_tree_hash:
        raise ValueError("private Prompt bootstrap Prompt tree mismatch")
    if bootstrap["state_tree_hash"] != state_tree_hash:
        raise ValueError("private Prompt bootstrap state tree mismatch")


def _check_public_boundary() -> str:
    for path in FORBIDDEN_PUBLIC_ASSETS:
        if path.exists():
            raise ValueError(f"private KNOT content is tracked publicly: {path.name}")

    runtime_manifest = _read_object(
        RUNTIME_AGENT_MANIFEST_PATH, "runtime Agent manifest"
    )
    if runtime_manifest.get("schema_version") != "runtime_agent_manifest_v5":
        raise ValueError("active runtime Agent manifest version mismatch")
    if runtime_manifest.get("runtime_agent_count") != 27:
        raise ValueError("active runtime Agent roster mismatch")
    if runtime_manifest.get("runtime_stage_count") != 28:
        raise ValueError("active runtime stage roster mismatch")
    if "knot" in json.dumps(runtime_manifest, sort_keys=True).lower():
        raise ValueError("KNOT authority leaked into the active runtime manifest")

    legacy = _read_object(PUBLIC_LEGACY_INVENTORY_PATH, "public legacy inventory")
    if (
        legacy.get("schema_version") != "knot_legacy_read_only_v2"
        or legacy.get("status") != "legacy_read_only"
        or legacy.get("active_runtime") is not False
        or legacy.get("writes_enabled") is not False
    ):
        raise ValueError("public legacy KNOT inventory is not fail-closed")

    for source_root in (ROOT / "mosaic", ROOT / "mosaic-ts" / "src"):
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            if path in SOURCE_MARKER_ALLOWLIST:
                continue
            text = path.read_text(encoding="utf-8")
            markers = [marker for marker in FORBIDDEN_SOURCE_MARKERS if marker in text]
            if markers:
                raise ValueError(
                    f"private KNOT implementation leaked into {path.relative_to(ROOT)}:"
                    f" {','.join(markers)}"
                )

    _check_execution_release()
    return _private_prompt_build_commit()


def _require_private_git_state(private_root: Path, expected_commit: str) -> None:
    head = subprocess.run(
        ["git", "-C", str(private_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != expected_commit:
        raise ValueError("private Prompt repository commit does not match public build-source pin")
    status = subprocess.run(
        ["git", "-C", str(private_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise ValueError("private Prompt repository must be clean")


def _check_private_repository(
    private_root: Path,
    expected_commit: str,
) -> None:
    _require_private_git_state(private_root, expected_commit)
    _check_private_token_budget_rows(private_root)
    _check_private_prompt_bootstrap(private_root)
    package = _read_object(private_root / PRIVATE_PACKAGE_PATH, "private package")
    if package.get("name") != ACTIVE_PRIVATE_PACKAGE or package.get("private") is not True:
        raise ValueError("active private package identity mismatch")

    build_config = _read_object(
        private_root / PRIVATE_BUILD_CONFIG_PATH, "private build config"
    )
    if build_config.get("include") != ACTIVE_PRIVATE_BUILD_ENTRIES:
        raise ValueError("private build includes legacy KNOT runtime modules")

    entry_lines = {
        line.strip()
        for line in (private_root / PRIVATE_ENTRY_PATH).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if entry_lines != ACTIVE_PRIVATE_EXPORTS:
        raise ValueError("private package exports exceed the Prompt Mutator boundary")

    active_sources = _private_active_source_closure(private_root)
    if not PRIVATE_ACTIVE_REQUIRED_SOURCES <= active_sources:
        missing = sorted(PRIVATE_ACTIVE_REQUIRED_SOURCES - active_sources)
        raise ValueError(f"private Prompt source closure is incomplete: {','.join(missing)}")

    legacy = _read_object(
        private_root / PRIVATE_LEGACY_INVENTORY_PATH, "private legacy inventory"
    )
    archive = _mapping(legacy.get("archive"), "private legacy archive")
    seed_audit = _mapping(
        legacy.get("seed_inventory_audit"), "private seed inventory audit"
    )
    if (
        legacy.get("schema_version") != "knot_legacy_read_only_v1"
        or legacy.get("status") != "archived_deleted"
        or legacy.get("writes_allowed") is not False
        or legacy.get("runtime_import_allowed") is not False
        or not isinstance(archive.get("commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", archive["commit"]) is None
        or archive.get("retrieval") != "git show <commit>:<historical-path>"
        or seed_audit.get("numeric_seed_count") != 215
        or seed_audit.get("runtime_authority") is not False
        or not isinstance(seed_audit.get("sha256"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", seed_audit["sha256"]) is None
    ):
        raise ValueError("private legacy KNOT inventory is not fail-closed")

def check(*, require_private: bool) -> None:
    expected_commit = _check_public_boundary()
    private_root = _private_root()
    if private_root is None:
        if require_private:
            raise ValueError("private Prompt repository is required")
        return
    _check_private_repository(private_root, expected_commit)
    _check_cross_repository_content_boundary(ROOT, private_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-private", action="store_true")
    args = parser.parse_args()
    check(require_private=args.require_private)
    print("private Prompt optimizer boundary passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
