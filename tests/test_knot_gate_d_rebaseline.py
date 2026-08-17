from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from mosaic.bridge.handlers import prompt_optimizer
from mosaic.bridge.protocol import RpcError
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.capability_preservation import (
    canonical_tool_environment_hash,
    load_capability_contract_bundle,
)
from mosaic.scorecard.knot_gate_d import (
    build_knot_gate_d_candidate,
    build_knot_gate_d_fixture_evidence,
    build_knot_gate_d_receipt,
)


ROOT = Path(__file__).parents[1]
HASH = "sha256:" + "1" * 64


class _FakeExperimentStore:
    def __init__(
        self,
        experiments: dict[str, dict],
        runs: dict[str, list[dict]],
        roster_revisions: dict[str, dict],
        projections: dict[str, dict] | None = None,
    ):
        self.experiments = experiments
        self.runs = runs
        self.roster_revisions = roster_revisions
        self.projections = projections or {}

    def get_experiment(self, experiment_id: str) -> dict | None:
        value = self.experiments.get(experiment_id)
        return copy.deepcopy(value) if value is not None else None

    def list_runs(self, experiment_id: str) -> list[dict]:
        return copy.deepcopy(self.runs.get(experiment_id, []))

    def get_production_variant_roster_revision(
        self, revision_id: str
    ) -> dict | None:
        value = self.roster_revisions.get(revision_id)
        return copy.deepcopy(value) if value is not None else None

    def get_training_projection_v2(self, projection_hash: str) -> dict | None:
        value = next(
            (
                projection
                for projection in self.projections.values()
                if projection["projectionHash"] == projection_hash
            ),
            None,
        )
        return copy.deepcopy(value) if value is not None else None


def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _fixture() -> dict[str, Any]:
    runtime = _load("registry/prompt_checks/runtime_agent_manifest_v5.json")
    tool_manifest = _load("registry/prompt_checks/agent_tool_contract_manifest_v1.json")
    bundle = load_capability_contract_bundle(ROOT)
    audit = bundle["knot_audit_capability_track_v2"]
    execution_hash = audit["execution_behavior_release_hash"]
    environment = bundle["tool_environment_manifest"]
    release_ids = {
        row["execution_behavior_release_id"] for row in environment["environments"]
    }
    assert len(release_ids) == 1
    release_id = release_ids.pop()
    archive_ref = (
        "registry/prompt_checks/execution_behavior_releases/"
        f"{release_id.removeprefix('execution-behavior-release:')}--"
        f"{execution_hash.removeprefix('sha256:')}.json"
    )
    roster_revision_body = {
        "production_variant_roster_revision_id": "roster-revision:test",
        "production_variant_roster_id": "roster:test",
        "execution_behavior_release_id": release_id,
        "cohort_id": "cohort_default",
        "language": "zh",
        "evaluation_track_key_hashes": [
            canonical_hash({"evaluation": index}) for index in range(25)
        ],
        "usage_track_key_hashes": [
            canonical_hash({"usage": index}) for index in range(21)
        ],
        "decision_evaluation_track_key_hashes": [
            canonical_hash({"decision": index}) for index in range(4)
        ],
        "prepared_at": "2026-08-01T00:00:00Z",
        "recorded_at": "2026-08-01T00:00:00Z",
        "effective_at": "2026-08-01T00:00:00Z",
        "effective_slot_sequence": 1,
        "readiness": "READY",
    }
    roster_revision = {
        **roster_revision_body,
        "production_variant_roster_revision_hash": canonical_hash(
            roster_revision_body
        ),
    }
    roster_refs = [
        {
            "revisionId": roster_revision[
                "production_variant_roster_revision_id"
            ],
            "revisionHash": roster_revision[
                "production_variant_roster_revision_hash"
            ],
        }
    ]
    stage_keys = [
        f"{agent['agent']}:{stage['stage']}"
        for agent in runtime["agents"]
        for stage in agent["stages"]
    ]
    experiments: dict[str, dict] = {}
    runs: dict[str, list[dict]] = {}
    experiment_ids_by_stage: dict[str, str] = {}
    projections: dict[str, dict] = {}
    for stage_key in stage_keys:
        agent_id, stage = stage_key.split(":", 1)
        experiment_stage = "cio_final" if stage_key == "cio:cio_proposal" else stage
        experiment_id = f"experiment:{agent_id}:{experiment_stage}"
        experiment_ids_by_stage[stage_key] = experiment_id
        if experiment_id not in experiments:
            run_rows = []
            for partition in ("VALIDATION", "HOLDOUT"):
                for side in ("CHAMPION", "CANDIDATE"):
                    run_rows.append(
                        {
                            "runId": f"run:{experiment_id}:{partition}:{side}",
                            "experimentId": experiment_id,
                            "partition": partition,
                            "side": side,
                            "sampleId": f"sample:{partition.lower()}",
                            "seed": 7,
                            "status": "COMPLETE",
                            "effectiveInputHash": canonical_hash(
                                {"experiment": experiment_id, "partition": partition}
                            ),
                        }
                    )
            runs[experiment_id] = run_rows
            experiments[experiment_id] = {
                "experimentId": experiment_id,
                "status": "COMPLETE",
                "target": {
                    "agentId": agent_id,
                    "stage": experiment_stage,
                    "cohort": "cohort_default",
                },
                "modelConfigHash": HASH,
                "toolConfigHash": canonical_tool_environment_hash(environment),
                "executorAdapterHash": HASH,
                "evaluatorAdapterHash": HASH,
                "evaluatorConfigHash": HASH,
                "codeCommit": "1" * 40,
                "executionBehaviorRelease": {
                    "release_id": release_id,
                    "release_hash": execution_hash,
                    "archive_ref": archive_ref,
                },
                "repeatSeeds": [7],
                "runIds": sorted(row["runId"] for row in run_rows),
            }
        projection_body = {
            "schemaVersion": "prompt_training_projection_v2",
            "target": {
                "agentId": agent_id,
                "stage": stage,
                "cohort": "cohort_default",
            },
            "capabilityTrack": bundle["accepted_output_capability_track"],
            "knotAuditCapabilityTrack": audit,
            "capabilityUseAggregates": [
                {"binding_id": row["binding_id"]}
                for row in bundle["binding_manifest"]["bindings"]
            ],
            "productionVariantRosterRevisions": roster_refs,
            "productionVariantRosterRevisionSetHash": canonical_hash(roster_refs),
        }
        projections[stage_key] = {
            **projection_body,
            "projectionHash": canonical_hash(projection_body),
        }
    full_bundle_body = {
        "schema_version": "capability_full_bundle_v1",
        "prompt_hash": HASH,
        "execution_behavior_release_hash": execution_hash,
        "production_variant_roster_hash": canonical_hash(roster_refs),
        "runtime_agent_manifest_hash": canonical_hash(runtime),
        "agent_tool_manifest_hash": canonical_hash(tool_manifest),
        "tool_environment_hash": canonical_tool_environment_hash(environment),
        "capability_binding_manifest_hash": bundle["binding_manifest"]["manifest_hash"],
        "knot_coverage_manifest_hash": bundle["knot_coverage_manifest_v2"]["manifest_hash"],
        "knot_audit_capability_track_hash": audit["track_hash"],
        "private_companion_pin_hash": "sha256:" + "3" * 64,
    }
    full_bundle = {
        **full_bundle_body,
        "full_bundle_hash": canonical_hash(full_bundle_body),
    }
    return {
        "store": _FakeExperimentStore(
            experiments,
            runs,
            {
                roster_revision["production_variant_roster_revision_id"]: (
                    roster_revision
                )
            },
            projections,
        ),
        "runtime": runtime,
        "tool_manifest": tool_manifest,
        "bundle": bundle,
        "full_bundle": full_bundle,
        "experiment_ids_by_stage": experiment_ids_by_stage,
        "projections": projections,
        "pin": {
            "public_commit": "1" * 40,
            "public_tree_hash": "sha256:" + "8" * 64,
            "private_commit": "2" * 40,
            "private_tree_hash": "sha256:" + "9" * 64,
            "private_companion_pin_hash": full_bundle[
                "private_companion_pin_hash"
            ],
        },
    }


def _build(data: dict[str, Any]) -> dict[str, Any]:
    return build_knot_gate_d_candidate(
        experiment_store=data["store"],
        runtime_agent_manifest=data["runtime"],
        current_agent_tool_manifest=data["tool_manifest"],
        capability_bundle=data["bundle"],
        capability_full_bundle=data["full_bundle"],
        experiment_ids_by_stage=data["experiment_ids_by_stage"],
        training_projections_by_stage=data["projections"],
        repository_root=ROOT,
        public_private_pin=data["pin"],
    )


def test_gate_d_candidate_closes_26_stages_190_bindings_and_shared_cio_prompt():
    data = _fixture()
    candidate = _build(data)
    assert candidate["runtime_stage_count"] == 26
    assert candidate["binding_count"] == 190
    assert len(candidate["stage_evidence"]) == 26
    proposal = next(
        row
        for row in candidate["stage_evidence"]
        if row["agent_id"] == "cio" and row["stage"] == "cio_proposal"
    )
    final = next(
        row
        for row in candidate["stage_evidence"]
        if row["agent_id"] == "cio" and row["stage"] == "cio_final"
    )
    assert proposal["experiment_target_stage"] == "cio_final"
    assert proposal["experiment_id"] == final["experiment_id"]
    assert candidate["candidate_hash"] == canonical_hash(
        {key: value for key, value in candidate.items() if key != "candidate_hash"}
    )
    release_schema = _load("schemas/active_prompt_release_manifest_v4.schema.json")
    candidate_schema = release_schema["properties"]["gate_d_receipt"]["properties"][
        "candidate"
    ]
    Draft202012Validator(candidate_schema).validate(candidate)


def test_gate_d_fixture_evidence_is_derived_from_current_overlays_and_tracks():
    data = _fixture()
    evidence = build_knot_gate_d_fixture_evidence(
        root=ROOT,
        capability_bundle=data["bundle"],
        training_projections_by_stage=data["projections"],
    )
    assert evidence["significance_fixture_count"] == 110
    assert evidence["runtime_binding_count"] == 190
    assert evidence["projection_count"] == 26
    assert evidence["source_route_migration_count"] == 6
    assert evidence["source_route_migrations_hash"] == canonical_hash(
        [
            {
                "from_route_id": "tushare.shibor_yield_curve",
                "source_binding_id": "binding:09a1f45221b66acbf024d00808aa5bf0312d58b2258061ab92442a10ac1c8586",
                "to_route_id": "composite.cn_rates",
            },
            {
                "from_route_id": "eurostat.euro_macro",
                "source_binding_id": "binding:2b2825ddc945411a920208f7803b0b77ee2b19395b6c87cd5187b87f4903962f",
                "to_route_id": "ecb.eu_real_economy",
            },
            {
                "from_route_id": "tushare.shibor_yield_curve",
                "source_binding_id": "binding:340b17f9c81c93426e3c2222aa9116a9f560acb8326a126fa641ebf2772f85d6",
                "to_route_id": "composite.cn_rates",
            },
            {
                "from_route_id": "tushare.shibor_yield_curve",
                "source_binding_id": "binding:89e79aebe666737155b439ab23251e04957eac43011e0f115653bebf248abdeb",
                "to_route_id": "composite.cn_rates",
            },
            {
                "from_route_id": "tushare.shibor_yield_curve",
                "source_binding_id": "binding:9c0380d8e572a2014178bc01e1c8cc2f281591d2ffcd9e60ca366bdd9c2f27cb",
                "to_route_id": "composite.cn_rates",
            },
            {
                "from_route_id": "tushare.shibor_yield_curve",
                "source_binding_id": "binding:bd7d647d99fc1550c60456640bc4341943ee6601628f04849d3dabd6d1ec5fab",
                "to_route_id": "composite.cn_rates",
            },
        ]
    )
    assert evidence["source_contract_migration_count"] == 3
    assert evidence["source_contract_migrations_hash"] == canonical_hash(
        [
            {
                "from_contract_version": "eurostat_forward_archive_v1",
                "from_route_id": "eurostat.euro_macro",
                "source_binding_id": "binding:2b2825ddc945411a920208f7803b0b77ee2b19395b6c87cd5187b87f4903962f",
                "to_contract_version": "ecb_eu_real_economy_history_v1",
                "to_route_id": "ecb.eu_real_economy",
            },
            {
                "from_contract_version": "ecb_euro_macro_v1",
                "from_route_id": "ecb.euro_macro",
                "source_binding_id": "binding:2b2825ddc945411a920208f7803b0b77ee2b19395b6c87cd5187b87f4903962f",
                "to_contract_version": "ecb_euro_macro_v2",
                "to_route_id": "ecb.euro_macro",
            },
            {
                "from_contract_version": "ecb_euro_macro_v1",
                "from_route_id": "ecb.euro_macro",
                "source_binding_id": "binding:5d22ffdac9730113fc227c0fb88f77dda8045bcef24a7df62cceb420154c88a2",
                "to_contract_version": "ecb_euro_macro_v2",
                "to_route_id": "ecb.euro_macro",
            },
        ]
    )
    assert evidence["evidence_hash"] == canonical_hash(
        {key: value for key, value in evidence.items() if key != "evidence_hash"}
    )
    candidate = _build(data)
    for field in (
        "significance_fixture_hash",
        "counterevidence_fixture_hash",
        "cross_track_isolation_hash",
        "public_safe_scan_hash",
    ):
        assert candidate[field] == evidence[field]


def test_gate_d_candidate_rejects_missing_stage_and_environment_drift():
    data = _fixture()
    data["experiment_ids_by_stage"].pop("china:agent_run")
    with pytest.raises(ValueError, match="stage experiment exact closure"):
        _build(data)

    data = _fixture()
    experiment_id = data["experiment_ids_by_stage"]["china:agent_run"]
    data["store"].experiments[experiment_id]["modelConfigHash"] = (
        "sha256:" + "f" * 64
    )
    with pytest.raises(ValueError, match="paired environment drift"):
        _build(data)


def test_gate_d_candidate_rejects_experiment_code_release_pin_mismatch():
    data = _fixture()
    data["pin"]["public_commit"] = "4" * 40

    with pytest.raises(ValueError, match="experiment code commit mismatch"):
        _build(data)


def test_gate_d_candidate_rejects_unpaired_inputs_and_projection_track_drift():
    data = _fixture()
    experiment_id = data["experiment_ids_by_stage"]["china:agent_run"]
    candidate_run = next(
        row for row in data["store"].runs[experiment_id] if row["side"] == "CANDIDATE"
    )
    candidate_run["effectiveInputHash"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="paired frozen input"):
        _build(data)

    data = _fixture()
    projection = data["projections"]["china:agent_run"]
    projection["capabilityTrack"] = {}
    body = {key: value for key, value in projection.items() if key != "projectionHash"}
    projection["projectionHash"] = canonical_hash(body)
    with pytest.raises(ValueError, match="training projection fixed-point"):
        _build(data)


def test_gate_d_candidate_rejects_unresolved_or_tampered_roster_revision():
    data = _fixture()
    data["store"].roster_revisions.clear()
    with pytest.raises(ValueError, match="production roster revision is unavailable"):
        _build(data)

    data = _fixture()
    revision = next(iter(data["store"].roster_revisions.values()))
    revision["readiness"] = "REJECTED"
    body = {
        key: value
        for key, value in revision.items()
        if key != "production_variant_roster_revision_hash"
    }
    revision["production_variant_roster_revision_hash"] = canonical_hash(body)
    ref = next(iter(data["projections"].values()))[
        "productionVariantRosterRevisions"
    ][0]
    ref["revisionHash"] = revision["production_variant_roster_revision_hash"]
    for projection in data["projections"].values():
        projection["productionVariantRosterRevisions"] = [copy.deepcopy(ref)]
        projection["productionVariantRosterRevisionSetHash"] = canonical_hash([ref])
        projection["projectionHash"] = canonical_hash(
            {key: value for key, value in projection.items() if key != "projectionHash"}
        )
    data["full_bundle"]["production_variant_roster_hash"] = canonical_hash([ref])
    full_body = {
        key: value
        for key, value in data["full_bundle"].items()
        if key != "full_bundle_hash"
    }
    data["full_bundle"]["full_bundle_hash"] = canonical_hash(full_body)
    with pytest.raises(ValueError, match="production roster revision is not READY"):
        _build(data)


def test_gate_d_receipt_binds_public_private_pi_reviews_to_candidate():
    candidate = _build(_fixture())
    receipt = build_knot_gate_d_receipt(
        candidate=candidate,
        public_pi_review={
            "repository": "public",
            "reviewed_commit": candidate["public_private_pin"]["public_commit"],
            "review_ref": "pi-review:public:1",
            "disposition": "APPROVE",
            "reviewed_candidate_hash": candidate["candidate_hash"],
        },
        private_pi_review={
            "repository": "private",
            "reviewed_commit": candidate["public_private_pin"]["private_commit"],
            "review_ref": "pi-review:private:1",
            "disposition": "APPROVE",
            "reviewed_candidate_hash": candidate["candidate_hash"],
        },
    )
    assert receipt["receipt_hash"] == canonical_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    release_schema = _load("schemas/active_prompt_release_manifest_v4.schema.json")
    receipt_schema = release_schema["properties"]["gate_d_receipt"]
    Draft202012Validator(receipt_schema).validate(receipt)
    invalid = copy.deepcopy(receipt["pi_reviews"]["private"])
    invalid["reviewed_commit"] = "3" * 40
    with pytest.raises(ValueError, match="Pi review binding"):
        build_knot_gate_d_receipt(
            candidate=candidate,
            public_pi_review=receipt["pi_reviews"]["public"],
            private_pi_review=invalid,
        )


def test_gate_d_bridge_builds_only_from_persisted_projection_hashes(
    monkeypatch: pytest.MonkeyPatch,
):
    data = _fixture()
    monkeypatch.setattr(prompt_optimizer, "_store", lambda: data["store"])
    request = {
        "capability_full_bundle": data["full_bundle"],
        "experiment_ids_by_stage": data["experiment_ids_by_stage"],
        "training_projection_hashes_by_stage": {
            stage_key: projection["projectionHash"]
            for stage_key, projection in data["projections"].items()
        },
        "public_private_pin": data["pin"],
    }
    candidate = prompt_optimizer.build_knot_gate_d_candidate_handler(request)[
        "candidate"
    ]
    assert candidate == _build(data)
    receipt = prompt_optimizer.build_knot_gate_d_receipt_handler(
        {
            "candidate": candidate,
            "public_pi_review": {
                "repository": "public",
                "reviewed_commit": candidate["public_private_pin"][
                    "public_commit"
                ],
                "review_ref": "pi-review:public:bridge",
                "disposition": "APPROVE",
                "reviewed_candidate_hash": candidate["candidate_hash"],
            },
            "private_pi_review": {
                "repository": "private",
                "reviewed_commit": candidate["public_private_pin"][
                    "private_commit"
                ],
                "review_ref": "pi-review:private:bridge",
                "disposition": "APPROVE",
                "reviewed_candidate_hash": candidate["candidate_hash"],
            },
        }
    )["receipt"]
    assert receipt["candidate"]["candidate_hash"] == candidate["candidate_hash"]

    missing = copy.deepcopy(request)
    missing["training_projection_hashes_by_stage"]["china:agent_run"] = HASH
    with pytest.raises(RpcError, match="training projection is unavailable"):
        prompt_optimizer.build_knot_gate_d_candidate_handler(missing)
