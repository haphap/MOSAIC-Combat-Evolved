from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mosaic.scorecard.darwinian_updates import freeze_evaluation_opportunity_set
from mosaic.scorecard.darwinian_v2 import canonical_hash, canonical_json
from mosaic.scorecard.knot_v2 import (
    append_knot_cio_dependency_blocked_audit,
    append_knot_control_dependency_result,
    append_knot_research_score_record,
    finalize_knot_pair,
    freeze_knot_pair_input,
    publish_knot_nomination_audit,
    publish_knot_promotion_batch,
    publish_knot_promotion_revision,
    publish_knot_rollback_revision,
    register_knot_research_track,
)
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


def _bindings() -> dict[str, dict[str, str | None]]:
    result = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        dimensions = contract["track_contract_dimensions"]
        result[agent_id] = {
            "agent_contract_version": f"{agent_id}_agent_v2",
            "prompt_behavior_version": f"{agent_id}_prompt_v2",
            "execution_behavior_version": f"{agent_id}_execution_v2",
            "component_weight_contract_version": (
                "macro_component_weights_v2"
                if dimensions["component_weight_contract"] == "REQUIRED"
                else None
            ),
            "reliability_adapter_contract_version": (
                f"{agent_id}_adapter_v2"
                if dimensions["reliability_adapter_contract"] == "REQUIRED"
                else None
            ),
            "confidence_semantics_contract_version": (
                f"{agent_id}_confidence_v2"
                if dimensions["confidence_semantics_contract"] == "REQUIRED"
                else None
            ),
        }
    return result


def _registered(
    tmp_path: Path, agent_id: str = "china"
) -> tuple[ScorecardStore, dict, str]:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-knot-1",
        behavior_bindings=_bindings(),
        effective_at="2026-07-17T08:00:00+08:00",
    )
    with store._connect() as conn:
        track_hash = conn.execute(
            "SELECT track_key_hash FROM darwinian_v2_evaluation_tracks "
            "WHERE production_variant_roster_id = ? AND agent_id = ?",
            (revision["production_variant_roster_id"], agent_id),
        ).fetchone()[0]
    return store, revision, track_hash


def _manifest(revision: dict) -> dict:
    common_hash = f"sha256:{'a' * 64}"
    immutable_contract_hash = f"sha256:{'9' * 64}"
    provider_binding = {
        "provider": "anthropic",
        "model": "claude-sonnet-4",
        "base_url_mode": "PROVIDER_DEFAULT",
        "structured_output_mode": "JSON_SCHEMA_STRICT",
        "repair_policy": "BOUNDED_SCHEMA_REPAIR_V1",
    }
    body = {
        "mutation_manifest_id": "mutation-china-1",
        "mutation_scope": "PRIVATE_PROMPT_BEHAVIOR_ONLY",
        "prompt_source_kind": "PRIVATE_PINNED",
        "private_prompt_commit": "ad0b8aa369ec03867d2c28b6330b2ed93e20ae4c",
        "variant_path": "cohort_default/macro/china.zh.md",
        "provider_binding": provider_binding,
        "provider_binding_hash": canonical_hash(provider_binding),
        "forbidden_contract_mutation_fields": [],
        "target_variants": [
            {
                "production_variant_roster_id": revision[
                    "production_variant_roster_id"
                ],
                "execution_behavior_release_id": revision[
                    "execution_behavior_release_id"
                ],
                "production_variant_roster_revision_id": revision[
                    "production_variant_roster_revision_id"
                ],
                "cohort_id": "cohort_default",
                "language": "zh",
            }
        ],
        "champion_behavior": {
            "prompt_behavior_version": "china_prompt_v2",
            "execution_behavior_version": "china_execution_v2",
            "content_hash": f"sha256:{'b' * 64}",
            "provider_mode": "PRODUCTION_PRIVATE_STRUCTURED",
            "structured_output_schema_binding_set_hash": common_hash,
            "immutable_phase_instruction_set_hash": f"sha256:{'c' * 64}",
            "immutable_contract_block_hash": immutable_contract_hash,
        },
        "candidate_behavior": {
            "prompt_behavior_version": "china_prompt_candidate_v3",
            "execution_behavior_version": "china_execution_v2",
            "content_hash": f"sha256:{'d' * 64}",
            "provider_mode": "PRODUCTION_PRIVATE_STRUCTURED",
            "structured_output_schema_binding_set_hash": common_hash,
            "immutable_phase_instruction_set_hash": f"sha256:{'c' * 64}",
            "immutable_contract_block_hash": immutable_contract_hash,
        },
        "maximum_research_slots": 40,
    }
    return {**body, "mutation_manifest_hash": canonical_hash(body)}


def _cio_manifest(revision: dict) -> dict:
    body = _manifest(revision)
    body.pop("mutation_manifest_hash")
    body["mutation_manifest_id"] = "mutation-cio-1"
    body["variant_path"] = "cohort_default/decision/cio.zh.md"
    body["champion_behavior"] = {
        **body["champion_behavior"],
        "prompt_behavior_version": "cio_prompt_v2",
        "execution_behavior_version": "cio_execution_v2",
    }
    body["candidate_behavior"] = {
        **body["candidate_behavior"],
        "prompt_behavior_version": "cio_prompt_candidate_v3",
        "execution_behavior_version": "cio_execution_v2",
    }
    return {**body, "mutation_manifest_hash": canonical_hash(body)}


def _capability(side: str) -> dict:
    suffix = "1" if side == "CHAMPION" else "2"
    return {
        "capability_id": f"capability-{side.lower()}",
        "nonce": f"nonce-{side.lower()}",
        "signature_hash": f"sha256:{suffix * 64}",
        "snapshot_bundle_id": "bundle-1",
        "snapshot_bundle_hash": f"sha256:{'e' * 64}",
        "allowed_tools": ["get_china_macro_snapshot", "get_role_event_snapshot"],
    }


def _insert_failure_audit(
    conn: sqlite3.Connection,
    *,
    revision: dict,
    track_hash: str,
    scheduled_sample_id: str,
    side: str,
) -> str:
    audit_id = f"operational:{side.lower()}"
    body = {
        "operational_opportunity_audit_id": audit_id,
        "agent_id": "china",
        "track_key_hash": track_hash,
        "sample_origin": "KNOT_RESEARCH_SHADOW",
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": scheduled_sample_id,
        "production_reliability_eligible": False,
        "disposition": "AGENT_FAILURE",
        "research_pair_side": side,
        "recorded_at": "2026-07-17T10:00:00+08:00",
    }
    record = {**body, "operational_opportunity_audit_hash": canonical_hash(body)}
    conn.execute(
        """
        INSERT INTO operational_opportunity_audits_v2 (
            operational_opportunity_audit_id, operational_opportunity_audit_hash,
            graph_run_id, run_slot_id, production_variant_roster_id,
            production_variant_roster_revision_id, execution_behavior_release_id,
            cohort_id, language, agent_id, track_key_hash, sample_origin,
            run_slot_kind, scheduled_sample_id, production_reliability_eligible,
            disposition, accountable, run_id, accepted_output_id, failure_reason,
            fallback_used, as_of, recorded_at, record_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'cohort_default', 'zh', 'china', ?,
                  'KNOT_RESEARCH_SHADOW', 'OUTCOME_SCHEDULED', ?, 0,
                  'AGENT_FAILURE', 1, ?, NULL, 'model_failure', 0, ?, ?, ?)
        """,
        (
            audit_id,
            record["operational_opportunity_audit_hash"],
            f"graph-{side.lower()}",
            f"slot-{side.lower()}",
            revision["production_variant_roster_id"],
            revision["production_variant_roster_revision_id"],
            revision["execution_behavior_release_id"],
            track_hash,
            scheduled_sample_id,
            f"run-{side.lower()}",
            "2026-07-17",
            "2026-07-17T10:00:00+08:00",
            canonical_json(record),
        ),
    )
    return audit_id


def _insert_nomination_checkpoints(
    conn: sqlite3.Connection,
    *,
    revision: dict,
) -> dict[str, dict]:
    states: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT track_key_hash, agent_id, rank_scope FROM "
        "darwinian_v2_evaluation_tracks WHERE production_variant_roster_id = ?",
        (revision["production_variant_roster_id"],),
    ).fetchall()
    sector_agents = {
        "agriculture",
        "biotech",
        "consumer",
        "energy",
        "financials",
        "industrials",
        "real_estate_construction",
        "semiconductor",
        "technology",
    }
    super_agents = {"ackman", "burry", "druckenmiller", "munger"}
    for track_hash, agent_id, rank_scope in rows:
        if agent_id in sector_agents:
            mean_score = -0.5 if agent_id == "agriculture" else 0.1
            maturity_state = "MATURE"
        elif agent_id in super_agents:
            mean_score = -0.4 if agent_id == "ackman" else 0.2
            maturity_state = "MATURE"
        else:
            mean_score = 0.1
            maturity_state = "MATURE"
        checkpoint_id = f"checkpoint:{agent_id}"
        body = {
            "evaluation_checkpoint_id": checkpoint_id,
            "track_key_hash": track_hash,
            "production_variant_roster_revision_id": revision[
                "production_variant_roster_revision_id"
            ],
            "rank_scope": rank_scope,
            "cutoff_at": "2026-07-17T11:00:00+08:00",
            "maturity_state": maturity_state,
            "performance_band": "Q2",
            "n_eligible_scores": 30,
            "window_coverage": 1,
            "mean_normalized_score": mean_score,
            "scoring_window_hash": canonical_hash({"agent_id": agent_id}),
            "max_consumed_outcome_sequence": 30,
            "recorded_at": "2026-07-17T11:00:00+08:00",
        }
        record = {**body, "evaluation_checkpoint_hash": canonical_hash(body)}
        conn.execute(
            """
            INSERT INTO darwinian_v2_evaluation_window_checkpoints (
                evaluation_checkpoint_id, evaluation_checkpoint_hash,
                track_key_hash, production_variant_roster_revision_id,
                rank_scope, cutoff_at, maturity_state, performance_band,
                n_eligible_scores, window_coverage, mean_normalized_score,
                scoring_window_hash, max_consumed_outcome_sequence,
                recorded_at, record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint_id,
                record["evaluation_checkpoint_hash"],
                track_hash,
                revision["production_variant_roster_revision_id"],
                rank_scope,
                body["cutoff_at"],
                maturity_state,
                "Q2",
                30,
                1,
                mean_score,
                body["scoring_window_hash"],
                30,
                body["recorded_at"],
                canonical_json(record),
            ),
        )
        states[track_hash] = {
            "evaluation_checkpoint_id": checkpoint_id,
            "operational_reliability": 0.95,
            "last_mutated_at": "2026-01-01T00:00:00Z",
            "last_research_served_slot": None,
            "active_candidate": False,
            "rollback_cooldown_active": False,
            "data_scoring_readiness": "READY",
        }
    return states


def _control_output(agent_id: str, evidence_id: str) -> dict:
    return {
        "agent": agent_id,
        "claims": [{"claim_id": f"claim:{agent_id}", "evidence_ids": [evidence_id]}],
        "claim_refs": [f"claim:{agent_id}"],
        "verified_claim_graph": {
            "run_id": f"control-run:{agent_id}",
            "snapshot_hash": f"sha256:{'8' * 64}",
            "evidence_ledger": [
                {
                    "evidence_id": evidence_id,
                    "source_fingerprint": f"sha256:{'7' * 64}",
                }
            ],
        },
    }


def test_cio_knot_control_dependencies_are_isolated_from_outcomes_and_weights(
    tmp_path: Path,
) -> None:
    store, revision, cio_track_hash = _registered(tmp_path, "cio")
    with store._connect() as conn:
        track = register_knot_research_track(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            target_evaluation_track_key_hash=cio_track_hash,
            mutation_manifest=_cio_manifest(revision),
            created_at="2026-07-17T08:30:00+08:00",
        )
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=cio_track_hash,
            scheduled_sample_id="knot:cio:slot-1",
            sample_origin="KNOT_RESEARCH_SHADOW",
            as_of="2026-07-17T09:00:00+08:00",
            member_refs=[{"portfolio_id": "portfolio-1"}],
            required_source_evidence_ids=["evidence:portfolio-1"],
            qualification_predicate_version="cio_portfolio_qualification_v2",
        )
        pair = freeze_knot_pair_input(
            conn,
            knot_research_track_id=track["knot_research_track_id"],
            research_slot_id="research-slot-cio-1",
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            root_snapshot_binding={
                "snapshot_bundle_id": "bundle-1",
                "snapshot_bundle_hash": f"sha256:{'e' * 64}",
                "runtime_input_hash": f"sha256:{'f' * 64}",
                "frozen_candidate_scope_hash": f"sha256:{'0' * 64}",
                "tool_payload_hashes": {
                    "get_cio_decision_snapshot": f"sha256:{'3' * 64}",
                },
                "allowed_tools": ["get_cio_decision_snapshot"],
            },
            champion_capability={
                **_capability("CHAMPION"),
                "allowed_tools": ["get_cio_decision_snapshot"],
            },
            candidate_capability={
                **_capability("CANDIDATE"),
                "allowed_tools": ["get_cio_decision_snapshot"],
            },
            frozen_at="2026-07-17T09:00:00+08:00",
        )
        alpha = append_knot_control_dependency_result(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            control_side="SHARED",
            agent_id="alpha_discovery",
            graph_run_id="graph-knot-cio-1",
            run_id="run-alpha-shared",
            result_disposition="ACCEPTED",
            frozen_object_set_id="bundle-1",
            frozen_object_set_hash=f"sha256:{'e' * 64}",
            evidence_ids=["evidence:alpha"],
            output=_control_output("alpha_discovery", "evidence:alpha"),
            recorded_at="2026-07-17T09:05:00+08:00",
        )
        alpha_retry = append_knot_control_dependency_result(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            control_side="SHARED",
            agent_id="alpha_discovery",
            graph_run_id="graph-knot-cio-1",
            run_id="run-alpha-shared",
            result_disposition="ACCEPTED",
            frozen_object_set_id="bundle-1",
            frozen_object_set_hash=f"sha256:{'e' * 64}",
            evidence_ids=["evidence:alpha"],
            output=_control_output("alpha_discovery", "evidence:alpha"),
            recorded_at="2026-07-17T09:05:00+08:00",
        )
        assert alpha_retry == alpha
        assert alpha["accepted_output"]["sample_origin"] == "KNOT_CONTROL_SHADOW"
        assert alpha["operational_opportunity_audit"][
            "production_reliability_eligible"
        ] is False

        cro_skip = append_knot_control_dependency_result(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            control_side="CHAMPION",
            agent_id="cro",
            graph_run_id="graph-knot-cio-1",
            run_id=None,
            result_disposition="NO_EVALUATION_OBJECT",
            frozen_object_set_id="candidate-empty",
            frozen_object_set_hash=f"sha256:{'5' * 64}",
            evidence_ids=["evidence:empty-candidate"],
            recorded_at="2026-07-17T09:06:00+08:00",
        )
        assert cro_skip["stage_skip"]["sample_origin"] == "KNOT_CONTROL_SHADOW"
        assert cro_skip["stage_skip"]["operational_opportunity_audit_hash"] == (
            cro_skip["operational_opportunity_audit"][
                "operational_opportunity_audit_hash"
            ]
        )
        assert cro_skip["operational_opportunity_audit"]["stage_skip_hash"] is None

        execution_failure = append_knot_control_dependency_result(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            control_side="CANDIDATE",
            agent_id="autonomous_execution",
            graph_run_id="graph-knot-cio-1",
            run_id="run-execution-candidate",
            result_disposition="AGENT_FAILURE",
            frozen_object_set_id="order-intents-candidate",
            frozen_object_set_hash=f"sha256:{'6' * 64}",
            evidence_ids=["evidence:orders"],
            failure_reason="MODEL_FAILURE",
            recorded_at="2026-07-17T09:07:00+08:00",
        )
        assert execution_failure["accepted_output"] is None
        assert execution_failure["operational_opportunity_audit"][
            "disposition"
        ] == "AGENT_FAILURE"

        assert conn.execute(
            "SELECT COUNT(*) FROM agent_outcome_eligibility_revisions_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM agent_outcome_labels_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM no_evaluation_object_stage_skips_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knot_control_stage_skips_v2"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM operational_opportunity_audits_v2 "
            "WHERE sample_origin = 'KNOT_CONTROL_SHADOW' "
            "AND production_reliability_eligible = 0"
        ).fetchone()[0] == 3
        with pytest.raises(ValueError, match="failure audit does not match"):
            append_knot_research_score_record(
                conn,
                knot_pair_id=pair["knot_pair_id"],
                pair_side="CANDIDATE",
                score_disposition="AGENT_FAILURE",
                operational_opportunity_audit_id=execution_failure[
                    "operational_opportunity_audit"
                ]["operational_opportunity_audit_id"],
                recorded_at="2026-07-17T09:08:00+08:00",
            )
        dependency_blocked = append_knot_cio_dependency_blocked_audit(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            control_side="CANDIDATE",
            blocked_dependency_operational_audit_id=execution_failure[
                "operational_opportunity_audit"
            ]["operational_opportunity_audit_id"],
            recorded_at="2026-07-17T09:08:00+08:00",
        )
        assert dependency_blocked["agent_id"] == "cio"
        assert dependency_blocked["accountable"] is False
        assert dependency_blocked["blocked_dependency_agent_id"] == (
            "autonomous_execution"
        )
        pairing = finalize_knot_pair(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            pair_disposition="DEPENDENCY_BLOCKED",
            exclusion_or_failure_reason="autonomous_execution:MODEL_FAILURE",
            dependency_blocked_audit_id=dependency_blocked[
                "operational_opportunity_audit_id"
            ],
            recorded_at="2026-07-17T09:09:00+08:00",
        )
        assert pairing["pair_disposition"] == "DEPENDENCY_BLOCKED"
        assert pairing["dependency_blocked_audit_hash"] == dependency_blocked[
            "operational_opportunity_audit_hash"
        ]

        with pytest.raises(ValueError, match="invalid KNOT control side"):
            append_knot_control_dependency_result(
                conn,
                knot_pair_id=pair["knot_pair_id"],
                control_side="CHAMPION",
                agent_id="alpha_discovery",
                graph_run_id="graph-knot-cio-1",
                run_id="run-alpha-duplicate",
                result_disposition="ACCEPTED",
                frozen_object_set_id="bundle-1",
                frozen_object_set_hash=f"sha256:{'e' * 64}",
                evidence_ids=["evidence:alpha"],
                output=_control_output("alpha_discovery", "evidence:alpha"),
                recorded_at="2026-07-17T09:10:00+08:00",
            )


def test_knot_ledgers_are_append_only_side_specific_and_idempotent(
    tmp_path: Path,
) -> None:
    store, revision, track_hash = _registered(tmp_path)
    with store._connect() as conn:
        track = register_knot_research_track(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            target_evaluation_track_key_hash=track_hash,
            mutation_manifest=_manifest(revision),
            created_at="2026-07-17T08:30:00+08:00",
        )
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=track_hash,
            scheduled_sample_id="knot:china:slot-1",
            sample_origin="KNOT_RESEARCH_SHADOW",
            as_of="2026-07-17T09:00:00+08:00",
            member_refs=[{"event_id": "cn-release-1"}],
            required_source_evidence_ids=["evidence:cn-release-1"],
            qualification_predicate_version="china_macro_qualification_v2",
        )
        pair = freeze_knot_pair_input(
            conn,
            knot_research_track_id=track["knot_research_track_id"],
            research_slot_id="research-slot-1",
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            root_snapshot_binding={
                "snapshot_bundle_id": "bundle-1",
                "snapshot_bundle_hash": f"sha256:{'e' * 64}",
                "runtime_input_hash": f"sha256:{'f' * 64}",
                "frozen_candidate_scope_hash": f"sha256:{'0' * 64}",
                "tool_payload_hashes": {
                    "get_china_macro_snapshot": f"sha256:{'3' * 64}",
                    "get_role_event_snapshot": f"sha256:{'4' * 64}",
                },
                "allowed_tools": [
                    "get_china_macro_snapshot",
                    "get_role_event_snapshot",
                ],
            },
            champion_capability=_capability("CHAMPION"),
            candidate_capability=_capability("CANDIDATE"),
            frozen_at="2026-07-17T09:00:00+08:00",
        )
        for side in ("CHAMPION", "CANDIDATE"):
            audit_id = _insert_failure_audit(
                conn,
                revision=revision,
                track_hash=track_hash,
                scheduled_sample_id=opportunity["scheduled_sample_id"],
                side=side,
            )
            score = append_knot_research_score_record(
                conn,
                knot_pair_id=pair["knot_pair_id"],
                pair_side=side,
                score_disposition="AGENT_FAILURE",
                operational_opportunity_audit_id=audit_id,
                recorded_at="2026-07-17T10:05:00+08:00",
            )
            assert score["raw_research_score"] == -2
            assert score["research_comparison_score"] == -2
        pairing = finalize_knot_pair(
            conn,
            knot_pair_id=pair["knot_pair_id"],
            pair_disposition="ACCOUNTABLE",
            recorded_at="2026-07-17T10:10:00+08:00",
        )
        assert pairing["pair_disposition"] == "ACCOUNTABLE"
        rejected = publish_knot_promotion_revision(
            conn,
            knot_research_track_id=track["knot_research_track_id"],
            champion_operational_reliability=0,
            candidate_operational_reliability=0,
            benjamini_hochberg_q=0.01,
            maximum_holdout_regime_degradation=0,
            hard_gate_failures=[],
            recorded_at="2026-07-17T10:15:00+08:00",
        )
        assert rejected["disposition"] == "REJECT"
        assert "accountable_pair_count:1:required:30" in rejected[
            "promotion_decision"
        ]["reasons"]
        retry = publish_knot_promotion_revision(
            conn,
            knot_research_track_id=track["knot_research_track_id"],
            champion_operational_reliability=0,
            candidate_operational_reliability=0,
            benjamini_hochberg_q=0.01,
            maximum_holdout_regime_degradation=0,
            hard_gate_failures=[],
            recorded_at="2026-07-17T10:15:00+08:00",
        )
        assert retry["knot_promotion_revision_id"] == rejected[
            "knot_promotion_revision_id"
        ]
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            conn.execute(
                "UPDATE knot_research_tracks_v2 SET agent_id = 'us_economy' "
                "WHERE knot_research_track_id = ?",
                (track["knot_research_track_id"],),
            )


def test_knot_nomination_is_scope_local_roster_scoped_and_idempotent(
    tmp_path: Path,
) -> None:
    store, revision, _ = _registered(tmp_path)
    with store._connect() as conn:
        states = _insert_nomination_checkpoints(conn, revision=revision)
        kwargs = {
            "production_variant_roster_revision_id": revision[
                "production_variant_roster_revision_id"
            ],
            "research_slot_id": "research-slot-2026-07-17",
            "track_states": states,
            "active_candidate_counts_by_layer": {
                "MACRO": 0,
                "SECTOR": 0,
                "SUPERINVESTOR": 0,
                "DECISION": 0,
            },
            "recorded_at": "2026-07-17T11:05:00+08:00",
        }
        audit = publish_knot_nomination_audit(conn, **kwargs)
        assert audit["disposition"] == "NOMINATED"
        assert audit["selected_scope_id"] == "sector_selection"
        assert audit["selected_agent_id"] == "agriculture"
        assert publish_knot_nomination_audit(conn, **kwargs) == audit


def test_knot_promotion_batch_rolls_back_every_record_when_any_gate_fails(
    tmp_path: Path,
) -> None:
    store, original_revision, track_hash = _registered(tmp_path)
    with store._connect() as conn:
        knot_track = register_knot_research_track(
            conn,
            production_variant_roster_revision_id=original_revision[
                "production_variant_roster_revision_id"
            ],
            target_evaluation_track_key_hash=track_hash,
            mutation_manifest=_manifest(original_revision),
            created_at="2026-07-17T08:30:00+08:00",
        )
    candidate_bindings = _bindings()
    candidate_bindings["china"]["prompt_behavior_version"] = (
        "china_prompt_candidate_v3"
    )
    candidate_revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-knot-candidate-batch",
        behavior_bindings=candidate_bindings,
        effective_at="2026-07-18T08:00:00+08:00",
    )
    with store._connect() as conn:
        with pytest.raises(ValueError, match="REJECT cannot publish"):
            publish_knot_promotion_batch(
                conn,
                targets=[
                    {
                        "knot_research_track_id": knot_track[
                            "knot_research_track_id"
                        ],
                        "champion_operational_reliability": 1,
                        "candidate_operational_reliability": 1,
                        "benjamini_hochberg_q": 0.01,
                        "maximum_holdout_regime_degradation": 0,
                        "hard_gate_failures": [],
                        "new_production_variant_roster_revision_id": (
                            candidate_revision[
                                "production_variant_roster_revision_id"
                            ]
                        ),
                    }
                ],
                effective_from_research_slot_id="research-slot-batch",
                new_execution_behavior_release_id="release-knot-candidate-batch",
                recorded_at="2026-07-18T08:00:00+08:00",
            )
        assert conn.execute(
            "SELECT COUNT(*) FROM knot_promotion_revisions_v2"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knot_promotion_batches_v2"
        ).fetchone()[0] == 0


def test_knot_hard_gate_rollback_is_prospective_and_restores_champion(
    tmp_path: Path,
) -> None:
    store, original_revision, track_hash = _registered(tmp_path)
    with store._connect() as conn:
        knot_track = register_knot_research_track(
            conn,
            production_variant_roster_revision_id=original_revision[
                "production_variant_roster_revision_id"
            ],
            target_evaluation_track_key_hash=track_hash,
            mutation_manifest=_manifest(original_revision),
            created_at="2026-07-17T08:30:00+08:00",
        )

    candidate_bindings = _bindings()
    candidate_bindings["china"]["prompt_behavior_version"] = (
        "china_prompt_candidate_v3"
    )
    candidate_revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-knot-candidate",
        behavior_bindings=candidate_bindings,
        effective_at="2026-07-18T08:00:00+08:00",
    )
    rollback_revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-knot-rollback",
        behavior_bindings=_bindings(),
        effective_at="2026-07-19T08:00:00+08:00",
    )
    with store._connect() as conn:
        promotion_body = {
            "knot_promotion_revision_id": "promotion:seed",
            "schema_version": "knot_promotion_revision_v2",
            "knot_research_track_id": knot_track["knot_research_track_id"],
            "knot_research_track_hash": knot_track["knot_research_track_hash"],
            "promotion_sequence": 1,
            "supersedes_revision_id": None,
            "disposition": "PROMOTE",
            "new_execution_behavior_release_id": "release-knot-candidate",
            "new_production_variant_roster_revision_id": candidate_revision[
                "production_variant_roster_revision_id"
            ],
            "knot_runtime_contract_manifest_hash": knot_track[
                "knot_runtime_contract_manifest_hash"
            ],
            "recorded_at": "2026-07-18T08:00:00+08:00",
        }
        promotion = {
            **promotion_body,
            "knot_promotion_revision_hash": canonical_hash(promotion_body),
        }
        conn.execute(
            """
            INSERT INTO knot_promotion_revisions_v2 (
                knot_promotion_revision_id, knot_promotion_revision_hash,
                knot_research_track_id, promotion_sequence,
                supersedes_revision_id, disposition,
                effective_from_research_slot_id,
                new_execution_behavior_release_id,
                new_production_variant_roster_revision_id,
                knot_runtime_contract_manifest_hash, recorded_at, record_json
            ) VALUES (?, ?, ?, 1, NULL, 'PROMOTE', ?, ?, ?, ?, ?, ?)
            """,
            (
                promotion["knot_promotion_revision_id"],
                promotion["knot_promotion_revision_hash"],
                knot_track["knot_research_track_id"],
                "research-slot-promote",
                "release-knot-candidate",
                candidate_revision["production_variant_roster_revision_id"],
                knot_track["knot_runtime_contract_manifest_hash"],
                promotion_body["recorded_at"],
                canonical_json(promotion),
            ),
        )
        rollback = publish_knot_rollback_revision(
            conn,
            knot_research_track_id=knot_track["knot_research_track_id"],
            champion_operational_reliability=1,
            candidate_operational_reliability=1,
            hard_gate_failures=["privacy_boundary"],
            effective_from_research_slot_id="research-slot-rollback",
            new_execution_behavior_release_id="release-knot-rollback",
            new_production_variant_roster_revision_id=rollback_revision[
                "production_variant_roster_revision_id"
            ],
            cooldown_until_research_slot_id="research-slot-rollback-plus-20",
            recorded_at="2026-07-19T08:00:00+08:00",
        )
        assert rollback["disposition"] == "ROLLBACK"
        assert rollback["supersedes_revision_id"] == "promotion:seed"
        assert rollback["rollback_cooldown_research_slots"] == 20


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda body: body.update(
                {"private_prompt_commit": "unpinned"}
            ),
            "private prompt commit",
        ),
        (
            lambda body: body.update(
                {"variant_path": "cohort_default/macro/us_economy.zh.md"}
            ),
            "variant_path",
        ),
        (
            lambda body: body["candidate_behavior"].update(
                {"execution_behavior_version": "candidate-execution-v3"}
            ),
            "execution behavior",
        ),
        (
            lambda body: body["candidate_behavior"].update(
                {"immutable_contract_block_hash": f"sha256:{'8' * 64}"}
            ),
            "immutable immutable_contract_block_hash",
        ),
    ],
)
def test_knot_registration_rejects_contract_or_variant_drift(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    store, revision, track_hash = _registered(tmp_path)
    manifest = _manifest(revision)
    manifest.pop("mutation_manifest_hash")
    mutate(manifest)
    manifest["mutation_manifest_hash"] = canonical_hash(manifest)
    with store._connect() as conn, pytest.raises(ValueError, match=message):
        register_knot_research_track(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            target_evaluation_track_key_hash=track_hash,
            mutation_manifest=manifest,
            created_at="2026-07-17T08:30:00+08:00",
        )
