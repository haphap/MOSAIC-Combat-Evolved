"""Verify that public KNOT assets are opaque and private assets are hash-pinned."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
PROMPT_CHECKS = ROOT / "registry" / "prompt_checks"
KNOT_REF_PATH = PROMPT_CHECKS / "knot_runtime_contract_ref_v2.json"
ASSET_REF_PATH = PROMPT_CHECKS / "private_knot_assets_ref_v1.json"
RUNTIME_AGENT_MANIFEST_PATH = PROMPT_CHECKS / "runtime_agent_manifest_v4.json"
OUTCOME_CONTRACT_MANIFEST_PATH = (
    PROMPT_CHECKS / "agent_outcome_contract_manifest_v2.json"
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
)
SENSITIVE_KEYS = {
    "minimum_accountable_pairs",
    "promotion_mean_delta_floor",
    "rollback_mean_delta_ceiling",
    "agent_failure_score",
    "card_bindings",
    "generic_bindings",
    "evaluation_metrics",
    "evaluation_calculators",
}
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
    / "private_knot_prompt_checker.ts",
    ROOT
    / "mosaic-ts"
    / "src"
    / "agents"
    / "prompts"
    / "private_knot_prompt_markers.ts",
}
EXPECTED_KNOT_COHORTS = {
    "cohort_default",
    "cohort_bull_2007",
    "cohort_bull_2016",
    "cohort_crisis_2008",
    "cohort_crisis_covid",
    "cohort_euphoria_2021",
    "cohort_rate_tightening",
    "cohort_recovery_2020",
}


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _ordered_json_hash(value: Any) -> str:
    """Match the private TS artifact generator's JSON.stringify hash."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _confined_private_path(private_root: Path, relative_path: Any, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError(f"{label} path is invalid")
    path = (private_root / relative_path).resolve()
    if not path.is_relative_to(private_root.resolve()):
        raise ValueError(f"{label} path escaped the private repository")
    return path


def _private_root() -> Path | None:
    configured = (
        os.environ.get("MOSAIC_KNOT_RUNTIME_ROOT")
        or os.environ.get("MOSAIC_PROMPTS_REPO")
        or os.environ.get("MOSAIC_PRIVATE_PROMPT_REPO")
    )
    if not configured:
        return None
    root = Path(configured).expanduser().resolve()
    if root.name == "mosaic" and root.parent.name == "prompts":
        root = root.parents[1]
    return root


def _check_knot_contract_reference(
    private_root: Path,
    knot_ref: Mapping[str, Any],
) -> None:
    manifest_path = (
        private_root / "registry" / "knot" / "knot_runtime_contract_manifest_v2.json"
    )
    manifest = _mapping(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        "private KNOT contract manifest",
    )
    manifest_without_hash = dict(manifest)
    manifest_hash = manifest_without_hash.pop(
        "knot_runtime_contract_manifest_hash", None
    )
    if manifest_hash != _canonical_hash(manifest_without_hash):
        raise ValueError("private KNOT contract manifest self-hash mismatch")

    public_top_fields = (
        "knot_runtime_contract_manifest_id",
        "knot_runtime_contract_manifest_version",
        "knot_runtime_contract_manifest_hash",
    )
    for field in public_top_fields:
        if knot_ref.get(field) != manifest.get(field):
            raise ValueError(f"private KNOT contract reference mismatch: {field}")

    nested_contracts = (
        (
            "research_score_contract",
            "research_score_contract_ref",
            "research_score_contract_hash",
        ),
        ("scheduler_contract", "scheduler_contract_ref", "scheduler_contract_hash"),
    )
    for private_key, public_key, hash_key in nested_contracts:
        contract = dict(_mapping(manifest.get(private_key), private_key))
        supplied_hash = contract.pop(hash_key, None)
        if supplied_hash != _canonical_hash(contract):
            raise ValueError(f"private KNOT nested contract self-hash mismatch: {private_key}")
        expected_ref = {
            f"{private_key}_id": contract.get(f"{private_key}_id"),
            f"{private_key}_version": contract.get(f"{private_key}_version"),
            hash_key: supplied_hash,
        }
        if _mapping(knot_ref.get(public_key), public_key) != expected_ref:
            raise ValueError(f"private KNOT nested contract reference mismatch: {public_key}")


def _check_private_asset_references(
    private_root: Path,
    asset_ref: Mapping[str, Any],
) -> None:
    if asset_ref.get("schema_version") != "private_knot_assets_ref_v1":
        raise ValueError("private KNOT asset reference version mismatch")

    catalog_ref = _mapping(asset_ref.get("domain_knob_catalog"), "domain knob catalog")
    catalog_relative_path = "registry/knot/domain_knob_catalog_v1.json"
    if catalog_ref.get("private_relative_path") != catalog_relative_path:
        raise ValueError("private domain-knob catalog path mismatch")
    catalog_path = private_root / catalog_relative_path
    if _sha256(catalog_path) != catalog_ref.get("file_hash"):
        raise ValueError("private KNOT asset hash mismatch: domain_knob_catalog")
    catalog = _mapping(
        json.loads(catalog_path.read_text(encoding="utf-8")),
        "private domain-knob catalog",
    )
    catalog_hash = _ordered_json_hash(catalog)
    if catalog.get("schema_version") != "domain_knob_catalog_v1":
        raise ValueError("private domain-knob catalog schema version mismatch")
    if catalog.get("catalog_version") != "domain_knob_catalog_v1":
        raise ValueError("private domain-knob catalog version mismatch")
    if catalog_ref.get("catalog_version") != catalog.get("catalog_version"):
        raise ValueError("private domain-knob catalog reference version mismatch")
    if catalog_ref.get("catalog_hash") != catalog_hash:
        raise ValueError("private domain-knob catalog reference hash mismatch")

    contract_ref = _mapping(asset_ref.get("evaluation_contract"), "evaluation contract")
    contract_relative_path = "registry/knot/domain_knob_evaluation_contract_v1.json"
    if contract_ref.get("private_relative_path") != contract_relative_path:
        raise ValueError("private evaluation contract path mismatch")
    contract_path = private_root / contract_relative_path
    if _sha256(contract_path) != contract_ref.get("file_hash"):
        raise ValueError("private KNOT asset hash mismatch: evaluation_contract")
    contract = dict(
        _mapping(
            json.loads(contract_path.read_text(encoding="utf-8")),
            "private evaluation contract",
        )
    )
    supplied_contract_hash = contract.pop("contract_hash", None)
    if supplied_contract_hash != _ordered_json_hash(contract):
        raise ValueError("private evaluation contract self-hash mismatch")
    if contract.get("schema_version") != "domain_knob_evaluation_contract_v1":
        raise ValueError("private evaluation contract schema version mismatch")
    if contract.get("contract_version") != "domain_knob_evaluation_contract_v1":
        raise ValueError("private evaluation contract version mismatch")
    if contract.get("catalog_version") != catalog.get("catalog_version"):
        raise ValueError("private evaluation contract catalog version mismatch")
    if contract.get("catalog_hash") != catalog_hash:
        raise ValueError("private evaluation contract catalog hash mismatch")

    schema_path = (
        private_root / "schemas" / "domain_knob_evaluation_contract_v1.schema.json"
    )
    if contract.get("schema_hash") != _sha256(schema_path):
        raise ValueError("private evaluation contract schema hash mismatch")
    if contract.get("metric_registry_hash") != _ordered_json_hash(
        _mapping(contract.get("evaluation_metrics"), "evaluation metrics")
    ):
        raise ValueError("private evaluation metric registry hash mismatch")
    if contract.get("calculator_registry_hash") != _ordered_json_hash(
        _mapping(contract.get("evaluation_calculators"), "evaluation calculators")
    ):
        raise ValueError("private evaluation calculator registry hash mismatch")

    expected_contract_ref = {
        "private_relative_path": contract_relative_path,
        "file_hash": _sha256(contract_path),
        "contract_version": contract.get("contract_version"),
        "schema_hash": contract.get("schema_hash"),
        "catalog_hash": contract.get("catalog_hash"),
        "metric_registry_hash": contract.get("metric_registry_hash"),
        "calculator_registry_hash": contract.get("calculator_registry_hash"),
        "contract_hash": supplied_contract_hash,
    }
    if contract_ref != expected_contract_ref:
        raise ValueError("private evaluation contract reference metadata mismatch")


def check(*, require_private: bool) -> None:
    for path in FORBIDDEN_PUBLIC_ASSETS:
        if path.exists():
            raise ValueError(f"private KNOT content is tracked publicly: {path.name}")
    knot_ref = _mapping(json.loads(KNOT_REF_PATH.read_text(encoding="utf-8")), "knot ref")
    asset_ref = _mapping(json.loads(ASSET_REF_PATH.read_text(encoding="utf-8")), "asset ref")
    public_payload = json.dumps([knot_ref, asset_ref], sort_keys=True)
    leaked = sorted(key for key in SENSITIVE_KEYS if key in public_payload)
    if leaked:
        raise ValueError(f"private KNOT fields leaked into public refs: {','.join(leaked)}")
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

    private_root = _private_root()
    if private_root is None:
        if require_private:
            raise ValueError("private KNOT repository is required")
        return

    _check_knot_contract_reference(private_root, knot_ref)
    _check_private_asset_references(private_root, asset_ref)

    runtime_manifest_path = (
        private_root / "registry" / "knot" / "private_runtime_manifest_v1.json"
    )
    if _sha256(runtime_manifest_path) != knot_ref.get("private_runtime_manifest_hash"):
        raise ValueError("private KNOT runtime manifest hash mismatch")
    runtime_manifest = _mapping(
        json.loads(runtime_manifest_path.read_text(encoding="utf-8")),
        "private runtime manifest",
    )
    runtime_files = _mapping(runtime_manifest.get("files"), "runtime files")
    if "typescript_agent_policy_adapter" not in runtime_files:
        raise ValueError("private KNOT TypeScript policy adapter is not registered")
    if "runtime_agent_contract_snapshot" not in runtime_files:
        raise ValueError("private runtime Agent contract snapshot is not registered")
    for logical_name, raw_entry in runtime_files.items():
        entry = _mapping(raw_entry, f"runtime file {logical_name}")
        path = _confined_private_path(
            private_root,
            entry.get("relative_path"),
            f"runtime file {logical_name}",
        )
        if _sha256(path) != entry.get("sha256"):
            raise ValueError(f"private KNOT runtime hash mismatch: {logical_name}")

    _check_runtime_agent_contract_snapshot(private_root)

    projection_ref = _mapping(
        asset_ref.get("research_knob_projections"), "research knob projections"
    )
    projection_manifest_path = private_root / str(
        projection_ref.get("private_manifest_relative_path")
    )
    if _sha256(projection_manifest_path) != projection_ref.get("manifest_hash"):
        raise ValueError("private research-knob projection manifest hash mismatch")
    projection_manifest = _mapping(
        json.loads(projection_manifest_path.read_text(encoding="utf-8")),
        "research knob projection manifest",
    )
    if projection_manifest.get("schema_version") != "research_knob_projection_manifest_v2":
        raise ValueError("private research-knob projection manifest version mismatch")
    cohort_files = _mapping(projection_manifest.get("files"), "projection cohort files")
    if set(cohort_files) != EXPECTED_KNOT_COHORTS:
        raise ValueError("private research-knob projection cohort roster mismatch")
    projection_count = sum(
        len(_mapping(files, f"projection cohort {cohort}"))
        for cohort, files in cohort_files.items()
    )
    if projection_count != projection_ref.get("projection_count"):
        raise ValueError("private research-knob projection count mismatch")
    for cohort, raw_files in cohort_files.items():
        projection_files = _mapping(raw_files, f"projection cohort {cohort}")
        if len(projection_files) != 28:
            raise ValueError(f"private research-knob Agent roster mismatch: {cohort}")
        for agent, raw_entry in projection_files.items():
            entry = _mapping(raw_entry, f"projection {cohort}/{agent}")
            expected_path = f"registry/research_knobs/{cohort}/{agent}.json"
            if entry.get("relative_path") != expected_path:
                raise ValueError(
                    f"private research-knob projection path mismatch: {cohort}/{agent}"
                )
            path = private_root / expected_path
            if _sha256(path) != entry.get("sha256"):
                raise ValueError(
                    f"private research-knob projection hash mismatch: {cohort}/{agent}"
                )
            projection = _mapping(
                json.loads(path.read_text(encoding="utf-8")),
                f"projection payload {cohort}/{agent}",
            )
            metadata = _mapping(
                projection.get("projection_metadata"),
                f"projection metadata {cohort}/{agent}",
            )
            if metadata.get("cohort") != cohort:
                raise ValueError(
                    f"private research-knob projection cohort mismatch: {cohort}/{agent}"
                )


def _check_runtime_agent_contract_snapshot(private_root: Path) -> None:
    runtime_manifest = _mapping(
        json.loads(RUNTIME_AGENT_MANIFEST_PATH.read_text(encoding="utf-8")),
        "public runtime Agent manifest",
    )
    outcome_manifest = _mapping(
        json.loads(OUTCOME_CONTRACT_MANIFEST_PATH.read_text(encoding="utf-8")),
        "public outcome contract manifest",
    )
    runtime_contract_keys = (
        "schema_version",
        "runtime_agent_count",
        "runtime_stage_count",
        "default_cohort",
        "private_knot_cohort_enablement",
        "canonical_l4_sequence",
        "agents",
    )
    runtime_contract = {key: runtime_manifest.get(key) for key in runtime_contract_keys}
    contracts = outcome_manifest.get("contracts")
    if not isinstance(contracts, list):
        raise ValueError("public outcome contract roster is invalid")
    outcomes = {
        str(contract.get("agent_id")): _mapping(contract, "public outcome contract")
        for contract in contracts
        if isinstance(contract, Mapping)
    }
    agents = runtime_manifest.get("agents")
    if not isinstance(agents, list) or len(agents) != 28 or len(outcomes) != 28:
        raise ValueError("public Agent contract roster mismatch")
    expected_agents = []
    for raw_agent in agents:
        agent = dict(_mapping(raw_agent, "public runtime Agent"))
        outcome = outcomes.get(str(agent.get("agent")))
        if outcome is None:
            raise ValueError(f"public outcome contract missing: {agent.get('agent')}")
        primary_label = outcome.get("primary_label_id")
        expected_agents.append(
            {
                **agent,
                "evaluation_object": outcome.get("evaluation_object"),
                "primary_label_id": primary_label,
                "primary_target_variable": primary_label,
                "maturity_horizon": outcome.get("maturity_horizon"),
                "maturity": outcome.get("maturity"),
            }
        )

    snapshot_path = (
        private_root
        / "registry"
        / "knot"
        / "runtime_agent_contract_snapshot_v1.json"
    )
    snapshot = _mapping(
        json.loads(snapshot_path.read_text(encoding="utf-8")),
        "private runtime Agent contract snapshot",
    )
    expected_sources = {
        "runtime_agent_manifest_version": runtime_manifest.get("schema_version"),
        "runtime_contract_hash": _canonical_hash(runtime_contract),
        "outcome_manifest_version": outcome_manifest.get("manifest_version"),
        "outcome_registry_hash": outcome_manifest.get("registry_hash"),
    }
    if snapshot.get("schema_version") != "private_runtime_agent_contract_snapshot_v1":
        raise ValueError("private runtime Agent contract snapshot version mismatch")
    if snapshot.get("source_contracts") != expected_sources:
        raise ValueError("private runtime Agent contract snapshot source mismatch")
    if snapshot.get("agents") != expected_agents:
        raise ValueError("private runtime Agent contract snapshot drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-private", action="store_true")
    args = parser.parse_args()
    check(require_private=args.require_private)
    print("private KNOT boundary passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
