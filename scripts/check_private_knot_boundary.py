"""Verify the active Prompt-optimizer privacy and legacy-runtime boundaries."""

from __future__ import annotations

import argparse
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


def _execution_release_private_commit() -> str:
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
        "private_prompt_commit",
        "private_prompt_bootstrap",
        "provider_binding",
        "active_production_variants",
        "execution_contracts",
    }
    private_commit = release.get("private_prompt_commit")
    if (
        set(release) != expected_keys
        or release.get("schema_version") != "execution_behavior_release_manifest_v3"
        or release.get("execution_behavior_release_id") != release_id
        or release.get("execution_behavior_release_hash") != release_hash
        or not isinstance(private_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", private_commit) is None
    ):
        raise ValueError("execution behavior release archive identity mismatch")
    bootstrap = _mapping(
        release.get("private_prompt_bootstrap"), "private Prompt bootstrap"
    )
    if (
        bootstrap.get("schema_version")
        != "private_prompt_parameter_bootstrap_release_v1"
        or bootstrap.get("state_count") != 224
        or not isinstance(release.get("active_production_variants"), list)
        or len(release["active_production_variants"]) != 16
        or not isinstance(release.get("execution_contracts"), list)
        or len(release["execution_contracts"]) != 56
    ):
        raise ValueError("execution behavior release archive schema mismatch")
    without_hash = {
        key: release[key]
        for key in (
            "schema_version",
            "execution_behavior_release_id",
            "private_prompt_commit",
            "private_prompt_bootstrap",
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
            "private_prompt_commit",
            "private_prompt_bootstrap",
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
    return private_commit


def _check_public_boundary() -> str:
    for path in FORBIDDEN_PUBLIC_ASSETS:
        if path.exists():
            raise ValueError(f"private KNOT content is tracked publicly: {path.name}")

    runtime_manifest = _read_object(
        RUNTIME_AGENT_MANIFEST_PATH, "runtime Agent manifest"
    )
    if runtime_manifest.get("schema_version") != "runtime_agent_manifest_v5":
        raise ValueError("active runtime Agent manifest version mismatch")
    if runtime_manifest.get("runtime_agent_count") != 28:
        raise ValueError("active runtime Agent roster mismatch")
    if runtime_manifest.get("runtime_stage_count") != 29:
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

    return _execution_release_private_commit()


def _check_private_repository(private_root: Path, expected_commit: str) -> None:
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

    result = subprocess.run(
        ["git", "-C", str(private_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != expected_commit:
        raise ValueError("private Prompt repository commit does not match public release")


def check(*, require_private: bool) -> None:
    expected_commit = _check_public_boundary()
    private_root = _private_root()
    if private_root is None:
        if require_private:
            raise ValueError("private Prompt repository is required")
        return
    _check_private_repository(private_root, expected_commit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-private", action="store_true")
    args = parser.parse_args()
    check(require_private=args.require_private)
    print("private Prompt optimizer boundary passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
