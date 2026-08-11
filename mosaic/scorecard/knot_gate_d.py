"""Public-safe Gate-D authority over existing paired Prompt experiments."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.capability_preservation import (
    canonical_tool_environment_hash,
    validate_capability_contract_bundle,
    validate_capability_full_bundle,
    validate_public_safe_projection,
)
from mosaic.scorecard.darwinian_v2 import (
    validate_production_variant_roster_revision,
)


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_RUNTIME_STAGE_COUNT = 29
_EXPECTED_BINDING_COUNT = 187
_EXPECTED_SIGNIFICANCE_FIXTURE_COUNT = 113
_LEGACY_CN_CURVE_ROUTE_ID = "tushare.shibor_yield_curve"
_ACTIVE_CN_RATES_ROUTE_ID = "composite.cn_rates"
_CN_CURVE_PRESERVATION_BINDING_IDS = frozenset(
    {
        "binding:09a1f45221b66acbf024d00808aa5bf0312d58b2258061ab92442a10ac1c8586",
        "binding:9c0380d8e572a2014178bc01e1c8cc2f281591d2ffcd9e60ca366bdd9c2f27cb",
        "binding:bd7d647d99fc1550c60456640bc4341943ee6601628f04849d3dabd6d1ec5fab",
    }
)
_CN_CURVE_FULL_PRESERVATION_BINDING_IDS = frozenset(
    {
        "binding:340b17f9c81c93426e3c2222aa9116a9f560acb8326a126fa641ebf2772f85d6",
        "binding:89e79aebe666737155b439ab23251e04957eac43011e0f115653bebf248abdeb",
    }
)
_EU_ECONOMY_PRESERVATION_BINDING_ID = (
    "binding:2b2825ddc945411a920208f7803b0b77ee2b19395b6c87cd5187b87f4903962f"
)
_EU_FINANCIAL_PRESERVATION_BINDING_ID = (
    "binding:5d22ffdac9730113fc227c0fb88f77dda8045bcef24a7df62cceb420154c88a2"
)
_BINDING_CONTRACT_KEY_FIELDS = (
    "agent_id",
    "phase",
    "semantic_capability_id",
    "tool_id",
    "argument_schema_hash",
    "argument_domain_selector_hash",
    "materializer_contract_hash",
    "privacy_contract_hash",
    "route_contract_hash",
    "output_semantics_hash",
    "query_bundle_contract_version",
    "source_route_ids",
)


class PromptExperimentReader(Protocol):
    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None: ...

    def list_runs(self, experiment_id: str) -> list[dict[str, Any]]: ...

    def get_production_variant_roster_revision(
        self, revision_id: str
    ) -> dict[str, Any] | None: ...


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a sha256 hash")
    return value


def _require_commit(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _COMMIT_RE.fullmatch(value):
        raise ValueError(f"{field} must be an exact 40-hex commit")
    return value


def _binding_contract_key(binding: Mapping[str, Any]) -> str:
    if any(field not in binding for field in _BINDING_CONTRACT_KEY_FIELDS):
        raise ValueError("Gate D fixture binding contract is incomplete")
    return canonical_hash(
        {field: binding[field] for field in _BINDING_CONTRACT_KEY_FIELDS}
    )


def _preservation_source_route_ids(
    *, source_binding_id: str, source_binding: Mapping[str, Any]
) -> tuple[list[str], list[dict[str, str]]]:
    raw_route_ids = source_binding.get("source_route_ids")
    if (
        not isinstance(raw_route_ids, list)
        or not raw_route_ids
        or not all(isinstance(route_id, str) and route_id for route_id in raw_route_ids)
        or len(set(raw_route_ids)) != len(raw_route_ids)
    ):
        raise ValueError("Gate D fixture source routes are invalid")
    if source_binding_id in (
        _CN_CURVE_PRESERVATION_BINDING_IDS
        | _CN_CURVE_FULL_PRESERVATION_BINDING_IDS
    ):
        if (
            _LEGACY_CN_CURVE_ROUTE_ID not in raw_route_ids
            or _ACTIVE_CN_RATES_ROUTE_ID in raw_route_ids
            or (
                source_binding_id in _CN_CURVE_PRESERVATION_BINDING_IDS
                and "base_binding_hash" not in source_binding
            )
            or (
                source_binding_id in _CN_CURVE_FULL_PRESERVATION_BINDING_IDS
                and "base_binding_hash" in source_binding
            )
        ):
            raise ValueError("Gate D curve preservation migration is invalid")
        active_route_ids = sorted(
            _ACTIVE_CN_RATES_ROUTE_ID
            if route_id == _LEGACY_CN_CURVE_ROUTE_ID
            else route_id
            for route_id in raw_route_ids
        )
        if len(set(active_route_ids)) != len(active_route_ids):
            raise ValueError("Gate D curve preservation migration is ambiguous")
        return active_route_ids, [
            {
                "from_route_id": _LEGACY_CN_CURVE_ROUTE_ID,
                "to_route_id": _ACTIVE_CN_RATES_ROUTE_ID,
            }
        ]
    if source_binding_id == _EU_ECONOMY_PRESERVATION_BINDING_ID:
        if (
            "base_binding_hash" not in source_binding
            or "eurostat.euro_macro" not in raw_route_ids
            or "ecb.eu_real_economy" in raw_route_ids
        ):
            raise ValueError("Gate D Europe preservation migration is invalid")
        active_route_ids = sorted(
            "ecb.eu_real_economy"
            if route_id == "eurostat.euro_macro"
            else route_id
            for route_id in raw_route_ids
        )
        return active_route_ids, [
            {
                "from_route_id": "eurostat.euro_macro",
                "to_route_id": "ecb.eu_real_economy",
            }
        ]
    if _LEGACY_CN_CURVE_ROUTE_ID in raw_route_ids:
        raise ValueError("Gate D fixture has an unapproved source-route migration")
    if "eurostat.euro_macro" in raw_route_ids:
        raise ValueError("Gate D fixture has an unapproved Europe route migration")
    return list(raw_route_ids), []


def _route_contract_versions(root: Path, relative_path: str) -> dict[str, str]:
    manifest = json.loads((root / relative_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("Gate D route contract manifest is malformed")
    body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if manifest.get("manifest_hash") != canonical_hash(body):
        raise ValueError("Gate D route contract manifest hash mismatch")
    routes = manifest.get("routes")
    if not isinstance(routes, list) or not all(isinstance(row, Mapping) for row in routes):
        raise ValueError("Gate D route contract rows are malformed")
    versions = {
        str(row.get("route_id")): str(row.get("contract_version")) for row in routes
    }
    if len(versions) != len(routes):
        raise ValueError("Gate D route contract rows are duplicated")
    return versions


def _preservation_source_contract_migrations(
    *,
    source_binding_id: str,
    source_binding: Mapping[str, Any],
    frozen_versions: Mapping[str, str],
    active_versions: Mapping[str, str],
) -> list[dict[str, str]]:
    if source_binding_id not in {
        _EU_ECONOMY_PRESERVATION_BINDING_ID,
        _EU_FINANCIAL_PRESERVATION_BINDING_ID,
    }:
        return []
    raw_route_ids = source_binding.get("source_route_ids")
    if not isinstance(raw_route_ids, list) or "ecb.euro_macro" not in raw_route_ids:
        raise ValueError("Gate D Europe contract migration binding is invalid")
    if (
        frozen_versions.get("ecb.euro_macro") != "ecb_euro_macro_v1"
        or active_versions.get("ecb.euro_macro") != "ecb_euro_macro_v2"
    ):
        raise ValueError("Gate D ECB contract migration version drift")
    migrations = [
        {
            "from_route_id": "ecb.euro_macro",
            "from_contract_version": "ecb_euro_macro_v1",
            "to_route_id": "ecb.euro_macro",
            "to_contract_version": "ecb_euro_macro_v2",
        }
    ]
    if source_binding_id == _EU_ECONOMY_PRESERVATION_BINDING_ID:
        if (
            "eurostat.euro_macro" not in raw_route_ids
            or frozen_versions.get("eurostat.euro_macro")
            != "eurostat_forward_archive_v1"
            or active_versions.get("ecb.eu_real_economy")
            != "ecb_eu_real_economy_history_v1"
        ):
            raise ValueError("Gate D Europe real-economy contract migration drift")
        migrations.insert(
            0,
            {
                "from_route_id": "eurostat.euro_macro",
                "from_contract_version": "eurostat_forward_archive_v1",
                "to_route_id": "ecb.eu_real_economy",
                "to_contract_version": "ecb_eu_real_economy_history_v1",
            },
        )
    return migrations


def _runtime_stage_keys(runtime_manifest: Mapping[str, Any]) -> list[str]:
    agents = runtime_manifest.get("agents")
    if (
        runtime_manifest.get("schema_version") != "runtime_agent_manifest_v5"
        or not isinstance(agents, list)
        or runtime_manifest.get("runtime_agent_count") != len(agents)
    ):
        raise ValueError("Gate D runtime agent manifest is invalid")
    keys: list[str] = []
    for agent in agents:
        if not isinstance(agent, Mapping) or not isinstance(agent.get("agent"), str):
            raise ValueError("Gate D runtime agent manifest is invalid")
        stages = agent.get("stages")
        if not isinstance(stages, list):
            raise ValueError("Gate D runtime stage manifest is invalid")
        for stage in stages:
            if not isinstance(stage, Mapping) or not isinstance(stage.get("stage"), str):
                raise ValueError("Gate D runtime stage manifest is invalid")
            keys.append(f"{agent['agent']}:{stage['stage']}")
    if (
        runtime_manifest.get("runtime_stage_count") != len(keys)
        or len(keys) != _EXPECTED_RUNTIME_STAGE_COUNT
        or len(set(keys)) != len(keys)
    ):
        raise ValueError("Gate D runtime stage exact closure mismatch")
    return sorted(keys)


def _validate_current_fixed_point(
    *,
    runtime_agent_manifest: Mapping[str, Any],
    current_agent_tool_manifest: Mapping[str, Any],
    capability_bundle: Mapping[str, Any],
    capability_full_bundle: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    validate_capability_contract_bundle(
        capability_bundle,
        current_tool_manifest=current_agent_tool_manifest,
    )
    validate_capability_full_bundle(capability_full_bundle)
    stage_keys = _runtime_stage_keys(runtime_agent_manifest)
    bindings = capability_bundle["binding_manifest"]["bindings"]
    binding_ids = sorted(str(row["binding_id"]) for row in bindings)
    if len(binding_ids) != _EXPECTED_BINDING_COUNT or len(set(binding_ids)) != len(
        binding_ids
    ):
        raise ValueError("Gate D binding exact closure mismatch")
    environment = capability_bundle["tool_environment_manifest"]
    coverage_v2 = capability_bundle["knot_coverage_manifest_v2"]
    audit_v2 = capability_bundle["knot_audit_capability_track_v2"]
    expected = {
        "execution_behavior_release_hash": audit_v2[
            "execution_behavior_release_hash"
        ],
        "runtime_agent_manifest_hash": canonical_hash(runtime_agent_manifest),
        "agent_tool_manifest_hash": canonical_hash(current_agent_tool_manifest),
        "tool_environment_hash": canonical_tool_environment_hash(environment),
        "capability_binding_manifest_hash": capability_bundle["binding_manifest"][
            "manifest_hash"
        ],
        "knot_coverage_manifest_hash": coverage_v2["manifest_hash"],
        "knot_audit_capability_track_hash": audit_v2["track_hash"],
    }
    if any(capability_full_bundle.get(key) != value for key, value in expected.items()):
        raise ValueError("Gate D capability full-bundle fixed-point mismatch")
    return stage_keys, binding_ids


def _experiment_target_stage(stage_key: str) -> str:
    return "cio_final" if stage_key == "cio:cio_proposal" else stage_key.split(":", 1)[1]


def _experiment_environment(experiment: Mapping[str, Any]) -> dict[str, Any]:
    release = experiment.get("executionBehaviorRelease")
    if not isinstance(release, Mapping):
        raise ValueError("Gate D experiment execution behavior binding is invalid")
    repeat_seeds = experiment.get("repeatSeeds")
    if (
        not isinstance(repeat_seeds, list)
        or not repeat_seeds
        or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in repeat_seeds)
    ):
        raise ValueError("Gate D experiment repeat seeds are invalid")
    fields = {
        "model_config_hash": experiment.get("modelConfigHash"),
        "tool_config_hash": experiment.get("toolConfigHash"),
        "executor_adapter_hash": experiment.get("executorAdapterHash"),
        "evaluator_adapter_hash": experiment.get("evaluatorAdapterHash"),
        "evaluator_config_hash": experiment.get("evaluatorConfigHash"),
        "code_commit": experiment.get("codeCommit"),
        "execution_behavior_release_hash": release.get("release_hash"),
        "execution_behavior_release_id": release.get("release_id"),
        "repeat_seeds_hash": canonical_hash(repeat_seeds),
    }
    for key in (
        "model_config_hash",
        "tool_config_hash",
        "executor_adapter_hash",
        "evaluator_adapter_hash",
        "evaluator_config_hash",
        "execution_behavior_release_hash",
    ):
        _require_sha256(fields[key], key)
    _require_commit(fields["code_commit"], "code_commit")
    if not isinstance(fields["execution_behavior_release_id"], str) or not fields[
        "execution_behavior_release_id"
    ]:
        raise ValueError("Gate D experiment execution behavior binding is invalid")
    return fields


def _validate_runs(
    experiment: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> tuple[str, list[str]]:
    experiment_id = str(experiment["experimentId"])
    run_ids = sorted(str(row.get("runId")) for row in runs)
    if (
        not runs
        or run_ids != experiment.get("runIds")
        or len(run_ids) != len(set(run_ids))
        or any(
            row.get("experimentId") != experiment_id or row.get("status") != "COMPLETE"
            for row in runs
        )
    ):
        raise ValueError("Gate D experiment run manifest is incomplete")
    coordinates: dict[tuple[str, str, int], dict[str, str]] = defaultdict(dict)
    for row in runs:
        partition = row.get("partition")
        sample_id = row.get("sampleId")
        seed = row.get("seed")
        side = row.get("side")
        if (
            partition not in {"VALIDATION", "HOLDOUT"}
            or not isinstance(sample_id, str)
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            or side not in {"CHAMPION", "CANDIDATE"}
            or seed not in experiment["repeatSeeds"]
        ):
            raise ValueError("Gate D paired run coordinates are invalid")
        effective_hash = _require_sha256(
            row.get("effectiveInputHash"), "effectiveInputHash"
        )
        coordinate = (partition, sample_id, seed)
        if side in coordinates[coordinate]:
            raise ValueError("Gate D paired run coordinate is duplicated")
        coordinates[coordinate][str(side)] = effective_hash
    if any(
        set(sides) != {"CHAMPION", "CANDIDATE"}
        or sides["CHAMPION"] != sides["CANDIDATE"]
        for sides in coordinates.values()
    ):
        raise ValueError("Gate D paired frozen input mismatch")
    ordered_runs = sorted(runs, key=lambda row: str(row["runId"]))
    input_hashes = sorted({value for sides in coordinates.values() for value in sides.values()})
    return canonical_hash(ordered_runs), input_hashes


def _validate_training_projection(
    projection: Mapping[str, Any],
    *,
    stage_key: str,
    capability_bundle: Mapping[str, Any],
    binding_ids: Sequence[str],
) -> tuple[str, list[dict[str, str]]]:
    body = {key: value for key, value in projection.items() if key != "projectionHash"}
    projection_hash = _require_sha256(projection.get("projectionHash"), "projectionHash")
    if (
        projection.get("schemaVersion") != "prompt_training_projection_v2"
        or projection_hash != canonical_hash(body)
    ):
        raise ValueError("Gate D training projection hash mismatch")
    agent_id, stage = stage_key.split(":", 1)
    target = projection.get("target")
    if not isinstance(target, Mapping) or (
        target.get("agentId"), target.get("stage")
    ) != (agent_id, stage):
        raise ValueError("Gate D training projection target mismatch")
    aggregates = projection.get("capabilityUseAggregates")
    aggregate_ids = (
        sorted(str(row.get("binding_id")) for row in aggregates)
        if isinstance(aggregates, list)
        and all(isinstance(row, Mapping) for row in aggregates)
        else []
    )
    if (
        projection.get("capabilityTrack")
        != capability_bundle["accepted_output_capability_track"]
        or projection.get("knotAuditCapabilityTrack")
        != capability_bundle["knot_audit_capability_track_v2"]
        or aggregate_ids != list(binding_ids)
    ):
        raise ValueError("Gate D training projection fixed-point mismatch")
    roster_refs = projection.get("productionVariantRosterRevisions")
    if not isinstance(roster_refs, list) or not roster_refs:
        raise ValueError("Gate D production roster revision set is empty")
    normalized_refs: list[dict[str, str]] = []
    for ref in roster_refs:
        if not isinstance(ref, Mapping) or set(ref) != {"revisionId", "revisionHash"}:
            raise ValueError("Gate D production roster revision ref is invalid")
        revision_id = ref.get("revisionId")
        if not isinstance(revision_id, str) or not revision_id:
            raise ValueError("Gate D production roster revision ref is invalid")
        normalized_refs.append(
            {
                "revisionId": revision_id,
                "revisionHash": _require_sha256(
                    ref.get("revisionHash"), "revisionHash"
                ),
            }
        )
    if (
        normalized_refs
        != sorted(normalized_refs, key=lambda ref: ref["revisionId"])
        or len({ref["revisionId"] for ref in normalized_refs}) != len(normalized_refs)
        or projection.get("productionVariantRosterRevisionSetHash")
        != canonical_hash(normalized_refs)
    ):
        raise ValueError("Gate D production roster revision set hash mismatch")
    validate_public_safe_projection(projection)
    return projection_hash, normalized_refs


def build_knot_gate_d_fixture_evidence(
    *,
    root: Path,
    capability_bundle: Mapping[str, Any],
    training_projections_by_stage: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    from mosaic.scorecard.l3_l4_preservation import (
        validate_l3_l4_preservation_overlay,
    )
    from mosaic.scorecard.macro_europe_preservation import (
        validate_macro_europe_preservation_overlay,
    )
    from mosaic.scorecard.macro_us_preservation import (
        validate_macro_us_preservation_overlay,
    )
    from mosaic.scorecard.sector_relationship_preservation import (
        validate_sector_relationship_preservation_overlay,
    )

    directory = root / "registry/prompt_checks/capability_preservation"
    overlay_specs = (
        (
            "macro_us",
            "macro_us_preservation_overlay_v1.json",
            validate_macro_us_preservation_overlay,
        ),
        (
            "macro_europe",
            "macro_europe_preservation_overlay_v1.json",
            validate_macro_europe_preservation_overlay,
        ),
        (
            "sector_relationship",
            "sector_relationship_preservation_overlay_v1.json",
            validate_sector_relationship_preservation_overlay,
        ),
        (
            "l3_l4",
            "l3_l4_preservation_overlay_v1.json",
            validate_l3_l4_preservation_overlay,
        ),
    )
    overlay_hashes: dict[str, str] = {}
    fixtures: list[Mapping[str, Any]] = []
    source_bindings: dict[str, Mapping[str, Any]] = {}
    for name, filename, validator in overlay_specs:
        overlay = json.loads((directory / filename).read_text(encoding="utf-8"))
        validator(overlay, root=root)
        overlay_hashes[name] = _require_sha256(
            overlay.get("manifest_hash"), f"{name}_overlay_hash"
        )
        rows = overlay.get("significance_fixtures")
        bindings = overlay.get("bindings")
        if (
            not isinstance(rows, list)
            or not all(isinstance(row, Mapping) for row in rows)
            or not isinstance(bindings, list)
            or not all(isinstance(row, Mapping) for row in bindings)
        ):
            raise ValueError("Gate D significance fixtures are invalid")
        for binding in bindings:
            binding_id = str(binding.get("binding_id"))
            if binding_id in source_bindings:
                raise ValueError("Gate D fixture source binding is duplicated")
            source_bindings[binding_id] = binding
        fixtures.extend(rows)
    fixtures = sorted(fixtures, key=lambda row: str(row.get("binding_id")))
    fixture_binding_ids = [str(row.get("binding_id")) for row in fixtures]
    current_bindings = capability_bundle["binding_manifest"]["bindings"]
    current_binding_ids = {str(row["binding_id"]) for row in current_bindings}
    current_by_contract: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for binding in current_bindings:
        current_by_contract[_binding_contract_key(binding)].append(binding)
    if (
        len(current_binding_ids) != _EXPECTED_BINDING_COUNT
        or len(fixtures) != _EXPECTED_SIGNIFICANCE_FIXTURE_COUNT
        or len(set(fixture_binding_ids)) != len(fixture_binding_ids)
        or set(fixture_binding_ids) != set(source_bindings)
    ):
        raise ValueError("Gate D significance fixture binding closure mismatch")
    binding_mappings = []
    source_route_migrations = []
    source_contract_migrations = []
    frozen_route_versions = _route_contract_versions(
        root,
        "registry/prompt_checks/capability_preservation/"
        "current_agent_data_route_manifest_snapshot_v1.json",
    )
    active_route_versions = _route_contract_versions(
        root, "registry/data_sources/agent_data_route_manifest_v1.json"
    )
    for source_binding_id in sorted(source_bindings):
        source_binding = source_bindings[source_binding_id]
        active_source_route_ids, route_migrations = _preservation_source_route_ids(
            source_binding_id=source_binding_id,
            source_binding=source_binding,
        )
        contract_migrations = _preservation_source_contract_migrations(
            source_binding_id=source_binding_id,
            source_binding=source_binding,
            frozen_versions=frozen_route_versions,
            active_versions=active_route_versions,
        )
        if source_binding_id in _CN_CURVE_FULL_PRESERVATION_BINDING_IDS:
            full_comparison_fields = tuple(
                field
                for field in _BINDING_CONTRACT_KEY_FIELDS
                if field not in {"source_route_ids", "route_contract_hash"}
            )
            matches = [
                binding
                for binding in current_bindings
                if all(
                    binding.get(field) == source_binding.get(field)
                    for field in full_comparison_fields
                )
                and binding.get("source_route_ids") == active_source_route_ids
            ]
            contract_key = (
                canonical_hash(
                    {
                        "source_binding_contract_key": _binding_contract_key(
                            source_binding
                        ),
                        "active_binding_contract_key": _binding_contract_key(matches[0]),
                    }
                )
                if len(matches) == 1
                else ""
            )
        elif "base_binding_hash" in source_binding:
            compact_fields = (
                "agent_id",
                "semantic_capability_id",
                "tool_id",
                "query_bundle_contract_version",
            )
            matches = [
                binding
                for binding in current_bindings
                if all(
                    binding.get(field) == source_binding.get(field)
                    for field in compact_fields
                )
                and binding.get("source_route_ids") == active_source_route_ids
            ]
            contract_key = (
                canonical_hash(
                    {
                        "base_binding_hash": _require_sha256(
                            source_binding.get("base_binding_hash"),
                            "base_binding_hash",
                        ),
                        "active_binding_contract_key": _binding_contract_key(matches[0]),
                    }
                )
                if len(matches) == 1
                else ""
            )
        else:
            contract_key = _binding_contract_key(source_binding)
            matches = current_by_contract.get(contract_key, [])
        if len(matches) != 1:
            raise ValueError("Gate D fixture active binding mapping mismatch")
        mapping = {
            "source_binding_id": source_binding_id,
            "active_binding_id": str(matches[0]["binding_id"]),
            "binding_contract_key": contract_key,
        }
        if route_migrations:
            mapping["source_route_migrations"] = route_migrations
            source_route_migrations.extend(
                {
                    "source_binding_id": source_binding_id,
                    **migration,
                }
                for migration in route_migrations
            )
        if contract_migrations:
            mapping["source_contract_migrations"] = contract_migrations
            source_contract_migrations.extend(
                {
                    "source_binding_id": source_binding_id,
                    **migration,
                }
                for migration in contract_migrations
            )
        binding_mappings.append(mapping)
    active_fixture_binding_ids = [
        row["active_binding_id"] for row in binding_mappings
    ]
    if len(set(active_fixture_binding_ids)) != len(active_fixture_binding_ids):
        raise ValueError("Gate D fixture active binding mapping is not one-to-one")
    significance_body = {
        "schema_version": "knot_gate_d_significance_fixture_report_v1",
        "capability_binding_manifest_hash": capability_bundle["binding_manifest"][
            "manifest_hash"
        ],
        "overlay_manifest_hashes": overlay_hashes,
        "binding_mappings_hash": canonical_hash(binding_mappings),
        "fixture_hashes": [
            _require_sha256(row.get("fixture_hash"), "fixture_hash")
            for row in fixtures
        ],
    }
    significance_fixture_hash = canonical_hash(significance_body)
    counterevidence_body = {
        "schema_version": "knot_gate_d_counterevidence_fixture_report_v1",
        "rows": [
            {
                "binding_id": str(row["binding_id"]),
                "active_binding_id": binding_mappings[index]["active_binding_id"],
                "fixture_hash": str(row["fixture_hash"]),
                "handled_hash": canonical_hash(row["counterevidence_handled"]),
                "ignored_hash": canonical_hash(row["counterevidence_ignored"]),
                "lineage_hash": canonical_hash(row["lineage_fixture"]),
            }
            for index, row in enumerate(fixtures)
        ],
    }
    counterevidence_fixture_hash = canonical_hash(counterevidence_body)
    if len(training_projections_by_stage) != _EXPECTED_RUNTIME_STAGE_COUNT:
        raise ValueError("Gate D projection fixture stage closure mismatch")
    projection_rows = []
    capability_track = capability_bundle["accepted_output_capability_track"]
    audit_track = capability_bundle["knot_audit_capability_track_v2"]
    for stage_key in sorted(training_projections_by_stage):
        projection = training_projections_by_stage[stage_key]
        projection_hash = _require_sha256(
            projection.get("projectionHash"), "projectionHash"
        )
        body = {
            key: value for key, value in projection.items() if key != "projectionHash"
        }
        if (
            projection_hash != canonical_hash(body)
            or projection.get("capabilityTrack") != capability_track
            or projection.get("knotAuditCapabilityTrack") != audit_track
        ):
            raise ValueError("Gate D cross-track isolation mismatch")
        validate_public_safe_projection(projection)
        projection_rows.append(
            {"stage_key": stage_key, "projection_hash": projection_hash}
        )
    cross_track_body = {
        "schema_version": "knot_gate_d_cross_track_isolation_v1",
        "accepted_output_capability_track_hash": canonical_hash(capability_track),
        "knot_audit_capability_track_hash": audit_track["track_hash"],
        "projections": projection_rows,
    }
    cross_track_isolation_hash = canonical_hash(cross_track_body)
    public_safe_scan_body = {
        "schema_version": "knot_gate_d_public_safe_scan_v1",
        "scanner_version": "capability_public_safe_projection_v1",
        "overlay_manifest_hashes": overlay_hashes,
        "significance_fixture_hash": significance_fixture_hash,
        "counterevidence_fixture_hash": counterevidence_fixture_hash,
        "cross_track_isolation_hash": cross_track_isolation_hash,
        "projection_hashes": [row["projection_hash"] for row in projection_rows],
    }
    validate_public_safe_projection(public_safe_scan_body)
    public_safe_scan_hash = canonical_hash(public_safe_scan_body)
    evidence_body = {
        "schema_version": "knot_gate_d_fixture_evidence_v1",
        "capability_binding_manifest_hash": capability_bundle["binding_manifest"][
            "manifest_hash"
        ],
        "runtime_binding_count": len(current_binding_ids),
        "significance_fixture_count": len(fixtures),
        "significance_binding_ids_hash": canonical_hash(fixture_binding_ids),
        "active_significance_binding_ids_hash": canonical_hash(
            active_fixture_binding_ids
        ),
        "source_route_migration_count": len(source_route_migrations),
        "source_route_migrations_hash": canonical_hash(source_route_migrations),
        "source_contract_migration_count": len(source_contract_migrations),
        "source_contract_migrations_hash": canonical_hash(
            source_contract_migrations
        ),
        "overlay_manifest_hashes": overlay_hashes,
        "projection_count": len(projection_rows),
        "significance_fixture_hash": significance_fixture_hash,
        "counterevidence_fixture_hash": counterevidence_fixture_hash,
        "cross_track_isolation_hash": cross_track_isolation_hash,
        "public_safe_scan_hash": public_safe_scan_hash,
    }
    evidence = {**evidence_body, "evidence_hash": canonical_hash(evidence_body)}
    validate_public_safe_projection(evidence)
    return evidence


def build_knot_gate_d_candidate(
    *,
    experiment_store: PromptExperimentReader,
    runtime_agent_manifest: Mapping[str, Any],
    current_agent_tool_manifest: Mapping[str, Any],
    capability_bundle: Mapping[str, Any],
    capability_full_bundle: Mapping[str, Any],
    experiment_ids_by_stage: Mapping[str, str],
    training_projections_by_stage: Mapping[str, Mapping[str, Any]],
    repository_root: Path,
    public_private_pin: Mapping[str, str],
) -> dict[str, Any]:
    stage_keys, binding_ids = _validate_current_fixed_point(
        runtime_agent_manifest=runtime_agent_manifest,
        current_agent_tool_manifest=current_agent_tool_manifest,
        capability_bundle=capability_bundle,
        capability_full_bundle=capability_full_bundle,
    )
    if set(experiment_ids_by_stage) != set(stage_keys):
        raise ValueError("Gate D stage experiment exact closure mismatch")
    if set(training_projections_by_stage) != set(stage_keys):
        raise ValueError("Gate D stage training projection exact closure mismatch")
    distinct_experiments: dict[str, Mapping[str, Any]] = {}
    runs_by_experiment: dict[str, list[dict[str, Any]]] = {}
    environments: dict[str, dict[str, Any]] = {}
    run_authority: dict[str, tuple[str, list[str]]] = {}
    for stage_key in stage_keys:
        experiment_id = experiment_ids_by_stage[stage_key]
        if not isinstance(experiment_id, str) or not experiment_id:
            raise ValueError("Gate D experiment id is invalid")
        experiment = experiment_store.get_experiment(experiment_id)
        if experiment is None or experiment.get("status") != "COMPLETE":
            raise ValueError("Gate D experiment is not COMPLETE")
        agent_id, _ = stage_key.split(":", 1)
        target = experiment.get("target")
        expected_target = (agent_id, _experiment_target_stage(stage_key))
        if not isinstance(target, Mapping) or (
            target.get("agentId"), target.get("stage")
        ) != expected_target:
            raise ValueError("Gate D experiment target mapping mismatch")
        previous = distinct_experiments.get(experiment_id)
        if previous is not None and previous != experiment:
            raise ValueError("Gate D experiment id resolved inconsistently")
        distinct_experiments[experiment_id] = experiment
        if experiment_id not in runs_by_experiment:
            experiment_runs = experiment_store.list_runs(experiment_id)
            runs_by_experiment[experiment_id] = experiment_runs
            run_authority[experiment_id] = _validate_runs(experiment, experiment_runs)
            environments[experiment_id] = _experiment_environment(experiment)
    environment_values = list(environments.values())
    if not environment_values or any(
        value != environment_values[0] for value in environment_values[1:]
    ):
        raise ValueError("Gate D paired environment drift")
    base_environment = environment_values[0]
    if (
        base_environment["tool_config_hash"]
        != capability_full_bundle["tool_environment_hash"]
        or base_environment["execution_behavior_release_hash"]
        != capability_full_bundle["execution_behavior_release_hash"]
    ):
        raise ValueError("Gate D paired environment fixed-point mismatch")
    projection_authority: dict[str, tuple[str, list[dict[str, str]]]] = {}
    roster_refs_by_id: dict[str, dict[str, str]] = {}
    for stage_key in stage_keys:
        authority = _validate_training_projection(
            training_projections_by_stage[stage_key],
            stage_key=stage_key,
            capability_bundle=capability_bundle,
            binding_ids=binding_ids,
        )
        projection_authority[stage_key] = authority
        for ref in authority[1]:
            previous_ref = roster_refs_by_id.get(ref["revisionId"])
            if previous_ref is not None and previous_ref != ref:
                raise ValueError("Gate D production roster revision ref drift")
            roster_refs_by_id[ref["revisionId"]] = ref
    roster_refs = [roster_refs_by_id[key] for key in sorted(roster_refs_by_id)]
    for ref in roster_refs:
        revision = experiment_store.get_production_variant_roster_revision(
            ref["revisionId"]
        )
        if revision is None:
            raise ValueError("Gate D production roster revision is unavailable")
        revision = validate_production_variant_roster_revision(revision)
        if (
            revision["production_variant_roster_revision_id"] != ref["revisionId"]
            or revision["production_variant_roster_revision_hash"]
            != ref["revisionHash"]
        ):
            raise ValueError("Gate D production roster revision ref mismatch")
        if revision["readiness"] != "READY":
            raise ValueError("Gate D production roster revision is not READY")
        if (
            revision["execution_behavior_release_id"]
            != base_environment["execution_behavior_release_id"]
        ):
            raise ValueError("Gate D production roster execution release mismatch")
    production_variant_roster_hash = canonical_hash(roster_refs)
    if (
        capability_full_bundle["production_variant_roster_hash"]
        != production_variant_roster_hash
    ):
        raise ValueError("Gate D production roster fixed-point mismatch")
    frozen_bundle_set_hash = canonical_hash(
        {
            stage_key: run_authority[experiment_ids_by_stage[stage_key]][1]
            for stage_key in stage_keys
        }
    )
    paired_environment = {
        **{
            key: value
            for key, value in base_environment.items()
            if key != "execution_behavior_release_id"
        },
        "production_variant_roster_hash": production_variant_roster_hash,
        "frozen_bundle_set_hash": frozen_bundle_set_hash,
    }
    paired_environment_hash = canonical_hash(paired_environment)
    evidence = []
    for stage_key in stage_keys:
        agent_id, stage = stage_key.split(":", 1)
        experiment_id = experiment_ids_by_stage[stage_key]
        experiment = distinct_experiments[experiment_id]
        evidence.append(
            {
                "agent_id": agent_id,
                "stage": stage,
                "experiment_target_stage": _experiment_target_stage(stage_key),
                "experiment_id": experiment_id,
                "experiment_hash": canonical_hash(experiment),
                "run_set_hash": run_authority[experiment_id][0],
                "training_projection_hash": projection_authority[stage_key][0],
                "paired_environment_hash": paired_environment_hash,
            }
        )
    pin_fields = {
        "public_commit": _require_commit(
            public_private_pin.get("public_commit"), "public_commit"
        ),
        "public_tree_hash": _require_sha256(
            public_private_pin.get("public_tree_hash"), "public_tree_hash"
        ),
        "private_commit": _require_commit(
            public_private_pin.get("private_commit"), "private_commit"
        ),
        "private_tree_hash": _require_sha256(
            public_private_pin.get("private_tree_hash"), "private_tree_hash"
        ),
        "private_companion_pin_hash": _require_sha256(
            public_private_pin.get("private_companion_pin_hash"),
            "private_companion_pin_hash",
        ),
    }
    if base_environment["code_commit"] != pin_fields["public_commit"]:
        raise ValueError("Gate D experiment code commit mismatch")
    if (
        pin_fields["private_companion_pin_hash"]
        != capability_full_bundle["private_companion_pin_hash"]
    ):
        raise ValueError("Gate D private companion pin mismatch")
    pin = {**pin_fields, "pair_hash": canonical_hash(pin_fields)}
    required_fixture_fields = {
        "significance_fixture_hash",
        "counterevidence_fixture_hash",
        "cross_track_isolation_hash",
        "public_safe_scan_hash",
    }
    fixture_evidence = build_knot_gate_d_fixture_evidence(
        root=repository_root,
        capability_bundle=capability_bundle,
        training_projections_by_stage=training_projections_by_stage,
    )
    fixtures = {
        key: _require_sha256(fixture_evidence[key], key)
        for key in sorted(required_fixture_fields)
    }
    body = {
        "schema_version": "knot_gate_d_candidate_v1",
        "full_bundle_hash": capability_full_bundle["full_bundle_hash"],
        "runtime_agent_manifest_hash": capability_full_bundle[
            "runtime_agent_manifest_hash"
        ],
        "runtime_stage_count": len(stage_keys),
        "capability_binding_manifest_hash": capability_full_bundle[
            "capability_binding_manifest_hash"
        ],
        "binding_count": len(binding_ids),
        "paired_environment": paired_environment,
        "paired_environment_hash": paired_environment_hash,
        "stage_evidence": evidence,
        **fixtures,
        "public_private_pin": pin,
    }
    candidate = {**body, "candidate_hash": canonical_hash(body)}
    validate_public_safe_projection(candidate)
    return candidate


def build_knot_gate_d_receipt(
    *,
    candidate: Mapping[str, Any],
    public_pi_review: Mapping[str, Any],
    private_pi_review: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_body = {
        key: value for key, value in candidate.items() if key != "candidate_hash"
    }
    if (
        candidate.get("schema_version") != "knot_gate_d_candidate_v1"
        or candidate.get("candidate_hash") != canonical_hash(candidate_body)
    ):
        raise ValueError("Gate D candidate hash mismatch")
    pin = candidate.get("public_private_pin")
    if not isinstance(pin, Mapping):
        raise ValueError("Gate D public/private pin is missing")
    reviews = {"public": dict(public_pi_review), "private": dict(private_pi_review)}
    for repository, review in reviews.items():
        expected_commit = pin[f"{repository}_commit"]
        if (
            set(review)
            != {
                "repository",
                "reviewed_commit",
                "review_ref",
                "disposition",
                "reviewed_candidate_hash",
            }
            or review["repository"] != repository
            or review["reviewed_commit"] != expected_commit
            or not isinstance(review["review_ref"], str)
            or not review["review_ref"]
            or review["disposition"] != "APPROVE"
            or review["reviewed_candidate_hash"] != candidate["candidate_hash"]
        ):
            raise ValueError("Gate D Pi review binding mismatch")
    body = {
        "schema_version": "knot_gate_d_receipt_v1",
        "candidate": dict(candidate),
        "pi_reviews": reviews,
    }
    receipt = {**body, "receipt_hash": canonical_hash(body)}
    validate_public_safe_projection(receipt)
    return receipt


__all__ = [
    "build_knot_gate_d_candidate",
    "build_knot_gate_d_fixture_evidence",
    "build_knot_gate_d_receipt",
]
