from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mosaic.scorecard.darwinian_updates import (
    append_outcome_eligibility_revision,
    freeze_evaluation_opportunity_set,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.store import ScorecardStore


def _bindings() -> dict[str, dict[str, str | None]]:
    bindings: dict[str, dict[str, str | None]] = {}
    for agent_id, contract in OUTCOME_CONTRACTS.items():
        dimensions = contract["track_contract_dimensions"]
        bindings[agent_id] = {
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
    return bindings


def _insert_private_pair_ledgers(
    conn: sqlite3.Connection,
    *,
    revision: dict,
    track_hash: str,
    opportunity: dict,
    execution_revision: dict | None = None,
    execution_track_hash: str | None = None,
) -> tuple[dict, dict]:
    conn.executescript(
        """
        CREATE TABLE knot_research_tracks_v2 (
            knot_research_track_id TEXT PRIMARY KEY,
            record_json TEXT NOT NULL
        );
        CREATE TABLE knot_pair_input_sets_v2 (
            knot_pair_id TEXT PRIMARY KEY,
            record_json TEXT NOT NULL
        );
        CREATE TABLE knot_promotion_revisions_v2 (
            knot_promotion_revision_id TEXT PRIMARY KEY,
            record_json TEXT NOT NULL
        );
        """
    )
    track_body = {
        "knot_research_track_id": "knot-track:china:1",
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": "cohort_default",
        "language": "zh",
        "target_evaluation_track_key_hash": track_hash,
        "agent_id": "china",
        "champion_prompt_behavior_version": "china_prompt_v2",
        "candidate_prompt_behavior_version": "china_prompt_candidate_v3",
        "champion_execution_behavior_version": "china_execution_v2",
        "candidate_execution_behavior_version": "china_execution_v2",
    }
    research_track = {
        **track_body,
        "knot_research_track_hash": canonical_hash(track_body),
    }
    conn.execute(
        "INSERT INTO knot_research_tracks_v2 VALUES (?, ?)",
        (
            research_track["knot_research_track_id"],
            json.dumps(research_track, separators=(",", ":"), sort_keys=True),
        ),
    )
    bundle_hash = f"sha256:{'b' * 64}"
    capabilities = {
        side: {
            "capability_id": f"capability:{side.lower()}",
            "capability_signature_hash": f"sha256:{digest * 64}",
            "snapshot_bundle_id": "snapshot-bundle:china:1",
            "snapshot_bundle_hash": bundle_hash,
        }
        for side, digest in (("CHAMPION", "c"), ("CANDIDATE", "d"))
    }
    pair_body: dict = {
        "knot_pair_id": "knot-pair:china:1",
        "knot_research_track_id": research_track["knot_research_track_id"],
        "knot_research_track_hash": research_track["knot_research_track_hash"],
        "sample_origin": "KNOT_RESEARCH_SHADOW",
        "scheduled_sample_id": opportunity["scheduled_sample_id"],
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "evaluation_opportunity_set_hash": opportunity[
            "evaluation_opportunity_set_hash"
        ],
        "snapshot_bundle_id": "snapshot-bundle:china:1",
        "snapshot_bundle_hash": bundle_hash,
        "runtime_input_hash": f"sha256:{'e' * 64}",
        "champion_capability": capabilities["CHAMPION"],
        "candidate_capability": capabilities["CANDIDATE"],
        "as_of": "2026-07-17",
        "frozen_at": "2026-07-17T09:00:00+08:00",
    }
    if execution_revision is not None:
        assert execution_track_hash is not None
        promotion_body = {
            "knot_promotion_revision_id": "knot-promotion:china:1",
            "schema_version": "knot_promotion_revision_v2",
            "knot_research_track_id": research_track["knot_research_track_id"],
            "knot_research_track_hash": research_track["knot_research_track_hash"],
            "promotion_sequence": 1,
            "supersedes_revision_id": None,
            "disposition": "PROMOTE",
            "effective_from_research_slot_id": "research-slot:post-promotion:1",
            "effective_from_research_slot_sequence": 2,
            "new_execution_behavior_release_id": execution_revision[
                "execution_behavior_release_id"
            ],
            "new_production_variant_roster_revision_id": execution_revision[
                "production_variant_roster_revision_id"
            ],
            "new_production_variant_roster_revision_hash": execution_revision[
                "production_variant_roster_revision_hash"
            ],
            "recorded_at": "2026-07-17T08:30:00+08:00",
        }
        promotion = {
            **promotion_body,
            "knot_promotion_revision_hash": canonical_hash(promotion_body),
        }
        conn.execute(
            "INSERT INTO knot_promotion_revisions_v2 VALUES (?, ?)",
            (
                promotion["knot_promotion_revision_id"],
                json.dumps(promotion, separators=(",", ":"), sort_keys=True),
            ),
        )
        pair_body.update(
            {
                "pair_phase": "POST_PROMOTION_SHADOW",
                "sample_origin": "KNOT_POST_PROMOTION_CHAMPION_SHADOW",
                "promotion_revision_id": promotion["knot_promotion_revision_id"],
                "execution_context": {
                    "production_variant_roster_id": execution_revision[
                        "production_variant_roster_id"
                    ],
                    "production_variant_roster_revision_id": execution_revision[
                        "production_variant_roster_revision_id"
                    ],
                    "execution_behavior_release_id": execution_revision[
                        "execution_behavior_release_id"
                    ],
                    "cohort_id": execution_revision["cohort_id"],
                    "language": execution_revision["language"],
                    "track_key_hash": execution_track_hash,
                    "agent_id": "china",
                },
            }
        )
    pair = {**pair_body, "knot_pair_input_hash": canonical_hash(pair_body)}
    conn.execute(
        "INSERT INTO knot_pair_input_sets_v2 VALUES (?, ?)",
        (
            pair["knot_pair_id"],
            json.dumps(pair, separators=(",", ":"), sort_keys=True),
        ),
    )
    return research_track, pair


def _insert_pair_side_acceptance(
    conn: sqlite3.Connection,
    *,
    revision: dict,
    research_track: dict,
    pair: dict,
    side: str,
    execution_track_hash: str | None = None,
) -> tuple[dict, dict]:
    side_lower = side.lower()
    capability = pair[f"{side_lower}_capability"]
    evaluation_object_hash = f"sha256:{('1' if side == 'CHAMPION' else '2') * 64}"
    accepted_id = f"accepted:china:{side_lower}"
    operational_id = f"operational:china:{side_lower}"
    lineage = {
        "knot_pair_id": pair["knot_pair_id"],
        "knot_pair_input_hash": pair["knot_pair_input_hash"],
        "research_pair_side": side,
        "capability_id": capability["capability_id"],
        "capability_signature_hash": capability["capability_signature_hash"],
        "snapshot_bundle_id": pair["snapshot_bundle_id"],
        "snapshot_bundle_hash": pair["snapshot_bundle_hash"],
        "runtime_input_hash": pair["runtime_input_hash"],
        "prompt_behavior_version": research_track[
            f"{side_lower}_prompt_behavior_version"
        ],
        "execution_behavior_version": research_track[
            f"{side_lower}_execution_behavior_version"
        ],
        "evaluation_object_hash": evaluation_object_hash,
    }
    accepted_body = {
        "accepted_output_id": accepted_id,
        "graph_run_id": f"graph:china:{side_lower}",
        "run_id": f"run:china:{side_lower}",
        "run_slot_id": f"slot:china:{side_lower}",
        "operational_opportunity_audit_id": operational_id,
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "track_key_hash": execution_track_hash
        or research_track["target_evaluation_track_key_hash"],
        "agent_id": "china",
        "accepted_output_kind": OUTCOME_CONTRACTS["china"]["accepted_output_kind"],
        "sample_origin": pair["sample_origin"],
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": pair["scheduled_sample_id"],
        **lineage,
        "output": {
            "evaluation_object_hash": evaluation_object_hash,
            "claims": [{"claim_id": f"claim:{side_lower}"}],
        },
        "as_of": pair["as_of"],
        "accepted_at": "2026-07-17T10:00:00+08:00",
    }
    accepted = {
        **accepted_body,
        "accepted_output_hash": canonical_hash(accepted_body),
    }
    accepted_columns = (
        "accepted_output_id",
        "accepted_output_hash",
        "graph_run_id",
        "run_id",
        "run_slot_id",
        "operational_opportunity_audit_id",
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
        "track_key_hash",
        "agent_id",
        "accepted_output_kind",
        "sample_origin",
        "run_slot_kind",
        "scheduled_sample_id",
        *lineage,
        "as_of",
        "accepted_at",
        "record_json",
    )
    conn.execute(
        f"INSERT INTO accepted_agent_outputs_v2 ({', '.join(accepted_columns)}) "
        f"VALUES ({', '.join('?' for _ in accepted_columns)})",
        (
            *(accepted[column] for column in accepted_columns[:-1]),
            json.dumps(accepted, separators=(",", ":"), sort_keys=True),
        ),
    )
    operational_body = {
        "operational_opportunity_audit_id": operational_id,
        "graph_run_id": accepted["graph_run_id"],
        "run_slot_id": accepted["run_slot_id"],
        "production_variant_roster_id": revision["production_variant_roster_id"],
        "production_variant_roster_revision_id": revision[
            "production_variant_roster_revision_id"
        ],
        "execution_behavior_release_id": revision["execution_behavior_release_id"],
        "cohort_id": revision["cohort_id"],
        "language": revision["language"],
        "agent_id": "china",
        "track_key_hash": execution_track_hash
        or research_track["target_evaluation_track_key_hash"],
        "sample_origin": pair["sample_origin"],
        "run_slot_kind": "OUTCOME_SCHEDULED",
        "scheduled_sample_id": pair["scheduled_sample_id"],
        "production_reliability_eligible": False,
        "disposition": "ACCEPTED",
        "accountable": True,
        "run_id": accepted["run_id"],
        "accepted_output_id": accepted_id,
        "accepted_output_hash": accepted["accepted_output_hash"],
        **lineage,
        "failure_reason": None,
        "fallback_used": False,
        "as_of": pair["as_of"],
        "recorded_at": "2026-07-17T10:00:00+08:00",
    }
    operational = {
        **operational_body,
        "operational_opportunity_audit_hash": canonical_hash(operational_body),
    }
    operational_columns = (
        "operational_opportunity_audit_id",
        "operational_opportunity_audit_hash",
        "graph_run_id",
        "run_slot_id",
        "production_variant_roster_id",
        "production_variant_roster_revision_id",
        "execution_behavior_release_id",
        "cohort_id",
        "language",
        "agent_id",
        "track_key_hash",
        "sample_origin",
        "run_slot_kind",
        "scheduled_sample_id",
        *lineage,
        "production_reliability_eligible",
        "disposition",
        "accountable",
        "run_id",
        "accepted_output_id",
        "failure_reason",
        "fallback_used",
        "as_of",
        "recorded_at",
        "record_json",
    )
    conn.execute(
        f"INSERT INTO operational_opportunity_audits_v2 "
        f"({', '.join(operational_columns)}) "
        f"VALUES ({', '.join('?' for _ in operational_columns)})",
        (
            *(operational[column] for column in operational_columns[:-1]),
            json.dumps(operational, separators=(",", ":"), sort_keys=True),
        ),
    )
    return accepted, operational


def _knot_fixture(tmp_path: Path) -> tuple[ScorecardStore, dict, dict, dict, dict]:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-07-17T08:00:00+08:00",
    )
    with store._connect() as conn:
        placeholders = ",".join("?" for _ in revision["evaluation_track_key_hashes"])
        track_hash = conn.execute(
            f"SELECT track_key_hash FROM darwinian_v2_evaluation_tracks "
            f"WHERE agent_id = 'china' AND track_key_hash IN ({placeholders})",
            tuple(revision["evaluation_track_key_hashes"]),
        ).fetchone()[0]
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=revision[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=track_hash,
            scheduled_sample_id="knot:china:2026-07-17",
            sample_origin="KNOT_RESEARCH_SHADOW",
            as_of="2026-07-17T09:00:00+08:00",
            member_refs=[{"event_id": "cn-gdp-2026q2"}],
            required_source_evidence_ids=["official:cn-gdp-2026q2"],
            qualification_predicate_version="china_macro_qualification_v2",
        )
        research_track, pair = _insert_private_pair_ledgers(
            conn,
            revision=revision,
            track_hash=track_hash,
            opportunity=opportunity,
        )
        accepted, operational = _insert_pair_side_acceptance(
            conn,
            revision=revision,
            research_track=research_track,
            pair=pair,
            side="CHAMPION",
        )
    return store, opportunity, pair, accepted, operational


def _post_promotion_knot_fixture(
    tmp_path: Path,
    *,
    promoted_cohort_id: str = "cohort_default",
) -> tuple[ScorecardStore, dict, dict, dict, dict, dict]:
    store = ScorecardStore(tmp_path / "scorecard-post-promotion.db")
    original_bindings = _bindings()
    original = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=original_bindings,
        effective_at="2026-07-17T08:00:00+08:00",
    )
    promoted_bindings = _bindings()
    promoted_bindings["china"] = {
        **promoted_bindings["china"],
        "prompt_behavior_version": "china_prompt_candidate_v3",
    }
    promoted = store.register_darwinian_production_variant(
        cohort_id=promoted_cohort_id,
        language="zh",
        execution_behavior_release_id="release-v3",
        behavior_bindings=promoted_bindings,
        effective_at="2026-07-17T08:30:00+08:00",
    )
    with store._connect() as conn:
        original_track_hash = next(
            track_hash
            for track_hash in original["evaluation_track_key_hashes"]
            if json.loads(
                conn.execute(
                    "SELECT contract_json FROM darwinian_v2_evaluation_tracks "
                    "WHERE track_key_hash = ?",
                    (track_hash,),
                ).fetchone()[0]
            )["agent_id"]
            == "china"
        )
        promoted_track_hash = next(
            track_hash
            for track_hash in promoted["evaluation_track_key_hashes"]
            if json.loads(
                conn.execute(
                    "SELECT contract_json FROM darwinian_v2_evaluation_tracks "
                    "WHERE track_key_hash = ?",
                    (track_hash,),
                ).fetchone()[0]
            )["agent_id"]
            == "china"
        )
        opportunity = freeze_evaluation_opportunity_set(
            conn,
            production_variant_roster_revision_id=promoted[
                "production_variant_roster_revision_id"
            ],
            track_key_hash=promoted_track_hash,
            scheduled_sample_id="knot:china:post-promotion:2026-07-17",
            sample_origin="KNOT_POST_PROMOTION_CHAMPION_SHADOW",
            as_of="2026-07-17T09:00:00+08:00",
            member_refs=[{"event_id": "cn-gdp-post-promotion"}],
            required_source_evidence_ids=["official:cn-gdp-post-promotion"],
            qualification_predicate_version="china_macro_qualification_v2",
        )
        research_track, pair = _insert_private_pair_ledgers(
            conn,
            revision=original,
            track_hash=original_track_hash,
            opportunity=opportunity,
            execution_revision=promoted,
            execution_track_hash=promoted_track_hash,
        )
        accepted, operational = _insert_pair_side_acceptance(
            conn,
            revision=promoted,
            research_track=research_track,
            pair=pair,
            side="CHAMPION",
            execution_track_hash=promoted_track_hash,
        )
    return store, promoted, opportunity, pair, accepted, operational


def test_knot_eligibility_persists_and_replays_complete_pair_lineage(
    tmp_path: Path,
) -> None:
    store, opportunity, pair, accepted, operational = _knot_fixture(tmp_path)
    kwargs = {
        "track_key_hash": accepted["track_key_hash"],
        "scheduled_sample_id": pair["scheduled_sample_id"],
        "sample_origin": pair["sample_origin"],
        "recorded_at": "2026-07-17T10:00:00+08:00",
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "accepted_output_id": accepted["accepted_output_id"],
        "research_pair_side": "CHAMPION",
        "knot_pair_id": pair["knot_pair_id"],
        "operational_opportunity_audit_id": operational[
            "operational_opportunity_audit_id"
        ],
    }
    with store._connect() as conn:
        pending = append_outcome_eligibility_revision(
            conn,
            disposition="PENDING",
            **kwargs,
        )
        assert append_outcome_eligibility_revision(
            conn,
            disposition="PENDING",
            **kwargs,
        ) == pending
        score = append_outcome_eligibility_revision(
            conn,
            disposition="SCORE",
            recorded_at="2026-07-24T10:00:00+08:00",
            **{key: value for key, value in kwargs.items() if key != "recorded_at"},
        )
        assert score["supersedes_revision_id"] == pending["audit_revision_id"]
        for field in (
            "knot_pair_id",
            "knot_pair_input_hash",
            "research_pair_side",
            "capability_id",
            "capability_signature_hash",
            "snapshot_bundle_id",
            "snapshot_bundle_hash",
            "runtime_input_hash",
            "prompt_behavior_version",
            "execution_behavior_version",
            "evaluation_object_hash",
            "accepted_output_hash",
            "operational_opportunity_audit_id",
            "operational_opportunity_audit_hash",
        ):
            assert score[field] is not None
        persisted = conn.execute(
            "SELECT knot_pair_id, research_pair_side, capability_id, "
            "evaluation_object_hash, accepted_output_hash, "
            "operational_opportunity_audit_hash "
            "FROM agent_outcome_eligibility_revisions_v2 "
            "WHERE audit_revision_id = ?",
            (score["audit_revision_id"],),
        ).fetchone()
        assert tuple(persisted) == (
            pair["knot_pair_id"],
            "CHAMPION",
            pair["champion_capability"]["capability_id"],
            accepted["evaluation_object_hash"],
            accepted["accepted_output_hash"],
            operational["operational_opportunity_audit_hash"],
        )


def test_post_promotion_knot_eligibility_uses_promoted_execution_context(
    tmp_path: Path,
) -> None:
    store, promoted, opportunity, pair, accepted, operational = (
        _post_promotion_knot_fixture(tmp_path)
    )
    with store._connect() as conn:
        revision = append_outcome_eligibility_revision(
            conn,
            track_key_hash=accepted["track_key_hash"],
            scheduled_sample_id=pair["scheduled_sample_id"],
            sample_origin=pair["sample_origin"],
            disposition="PENDING",
            recorded_at="2026-07-17T10:00:00+08:00",
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            accepted_output_id=accepted["accepted_output_id"],
            research_pair_side="CHAMPION",
            knot_pair_id=pair["knot_pair_id"],
            operational_opportunity_audit_id=operational[
                "operational_opportunity_audit_id"
            ],
        )
    assert accepted["production_variant_roster_revision_id"] == promoted[
        "production_variant_roster_revision_id"
    ]
    assert revision["track_key_hash"] == pair["execution_context"]["track_key_hash"]
    assert revision["prompt_behavior_version"] == "china_prompt_v2"
    assert revision["execution_behavior_version"] == "china_execution_v2"


def test_post_promotion_knot_rejects_cross_cohort_execution_context(
    tmp_path: Path,
) -> None:
    store, _promoted, opportunity, pair, accepted, operational = (
        _post_promotion_knot_fixture(
            tmp_path,
            promoted_cohort_id="cohort_bull_2007",
        )
    )
    with store._connect() as conn, pytest.raises(
        ValueError,
        match="post-promotion KNOT pair changed production_variant_roster_id identity",
    ):
        append_outcome_eligibility_revision(
            conn,
            track_key_hash=accepted["track_key_hash"],
            scheduled_sample_id=pair["scheduled_sample_id"],
            sample_origin=pair["sample_origin"],
            disposition="PENDING",
            recorded_at="2026-07-17T10:00:00+08:00",
            evaluation_opportunity_set_id=opportunity[
                "evaluation_opportunity_set_id"
            ],
            accepted_output_id=accepted["accepted_output_id"],
            research_pair_side="CHAMPION",
            knot_pair_id=pair["knot_pair_id"],
            operational_opportunity_audit_id=operational[
                "operational_opportunity_audit_id"
            ],
        )


def test_knot_eligibility_rejects_rehashed_track_contract_under_stale_key(
    tmp_path: Path,
) -> None:
    store, _promoted, opportunity, pair, accepted, operational = (
        _post_promotion_knot_fixture(tmp_path)
    )
    with store._connect() as conn:
        row = conn.execute(
            "SELECT contract_json FROM darwinian_v2_evaluation_tracks "
            "WHERE track_key_hash = ?",
            (accepted["track_key_hash"],),
        ).fetchone()
        tampered = json.loads(row[0])
        tampered["agent_contract_version"] = "tampered_agent_contract_v3"
        conn.execute("DROP TRIGGER no_update_darwinian_v2_evaluation_tracks")
        conn.execute(
            "UPDATE darwinian_v2_evaluation_tracks "
            "SET agent_contract_version = ?, contract_json = ? "
            "WHERE track_key_hash = ?",
            (
                tampered["agent_contract_version"],
                json.dumps(tampered, separators=(",", ":"), sort_keys=True),
                accepted["track_key_hash"],
            ),
        )
        with pytest.raises(ValueError, match="evaluation track key hash mismatch"):
            append_outcome_eligibility_revision(
                conn,
                track_key_hash=accepted["track_key_hash"],
                scheduled_sample_id=pair["scheduled_sample_id"],
                sample_origin=pair["sample_origin"],
                disposition="PENDING",
                recorded_at="2026-07-17T10:00:00+08:00",
                evaluation_opportunity_set_id=opportunity[
                    "evaluation_opportunity_set_id"
                ],
                accepted_output_id=accepted["accepted_output_id"],
                research_pair_side="CHAMPION",
                knot_pair_id=pair["knot_pair_id"],
                operational_opportunity_audit_id=operational[
                    "operational_opportunity_audit_id"
                ],
            )


def test_knot_eligibility_rejects_cross_side_or_unbound_operational_records(
    tmp_path: Path,
) -> None:
    store, opportunity, pair, accepted, operational = _knot_fixture(tmp_path)
    common = {
        "track_key_hash": accepted["track_key_hash"],
        "scheduled_sample_id": pair["scheduled_sample_id"],
        "sample_origin": pair["sample_origin"],
        "disposition": "PENDING",
        "recorded_at": "2026-07-17T10:00:00+08:00",
        "evaluation_opportunity_set_id": opportunity[
            "evaluation_opportunity_set_id"
        ],
        "accepted_output_id": accepted["accepted_output_id"],
        "knot_pair_id": pair["knot_pair_id"],
        "operational_opportunity_audit_id": operational[
            "operational_opportunity_audit_id"
        ],
    }
    with store._connect() as conn:
        with pytest.raises(ValueError, match="accepted output research_pair_side"):
            append_outcome_eligibility_revision(
                conn,
                research_pair_side="CANDIDATE",
                **common,
            )
        with pytest.raises(ValueError, match="requires an operational audit"):
            append_outcome_eligibility_revision(
                conn,
                research_pair_side="CHAMPION",
                **{
                    key: value
                    for key, value in common.items()
                    if key != "operational_opportunity_audit_id"
                },
            )


def test_production_eligibility_cannot_carry_knot_identity(tmp_path: Path) -> None:
    store = ScorecardStore(tmp_path / "scorecard.db")
    revision = store.register_darwinian_production_variant(
        cohort_id="cohort_default",
        language="zh",
        execution_behavior_release_id="release-v2",
        behavior_bindings=_bindings(),
        effective_at="2026-07-17T08:00:00+08:00",
    )
    with store._connect() as conn:
        placeholders = ",".join("?" for _ in revision["evaluation_track_key_hashes"])
        track_hash = conn.execute(
            f"SELECT track_key_hash FROM darwinian_v2_evaluation_tracks "
            f"WHERE agent_id = 'china' AND track_key_hash IN ({placeholders})",
            tuple(revision["evaluation_track_key_hashes"]),
        ).fetchone()[0]
        with pytest.raises(ValueError, match="cannot carry KNOT lineage"):
            append_outcome_eligibility_revision(
                conn,
                track_key_hash=track_hash,
                scheduled_sample_id="sample",
                sample_origin="PRODUCTION_ACTIVE",
                disposition="AGENT_FAILURE",
                recorded_at="2026-07-17T10:00:00+08:00",
                evaluation_opportunity_set_id=None,
                exclusion_or_failure_reason="failure",
                research_pair_side="CHAMPION",
                knot_pair_id="knot-pair:forbidden",
            )
        accepted_body = {
            "accepted_output_id": "accepted:production:forbidden-lineage",
            "graph_run_id": "graph:production",
            "run_id": "run:production",
            "run_slot_id": "slot:production",
            "operational_opportunity_audit_id": "operational:production",
            "production_variant_roster_id": revision[
                "production_variant_roster_id"
            ],
            "production_variant_roster_revision_id": revision[
                "production_variant_roster_revision_id"
            ],
            "execution_behavior_release_id": revision[
                "execution_behavior_release_id"
            ],
            "cohort_id": "cohort_default",
            "language": "zh",
            "track_key_hash": track_hash,
            "agent_id": "china",
            "accepted_output_kind": OUTCOME_CONTRACTS["china"][
                "accepted_output_kind"
            ],
            "sample_origin": "PRODUCTION_ACTIVE",
            "run_slot_kind": "OUTCOME_SCHEDULED",
            "scheduled_sample_id": "production:sample",
            "as_of": "2026-07-17",
            "accepted_at": "2026-07-17T10:00:00+08:00",
            "knot_pair_id": None,
        }
        accepted = {
            **accepted_body,
            "accepted_output_hash": canonical_hash(accepted_body),
        }
        columns = (
            "accepted_output_id",
            "accepted_output_hash",
            "graph_run_id",
            "run_id",
            "run_slot_id",
            "operational_opportunity_audit_id",
            "production_variant_roster_id",
            "production_variant_roster_revision_id",
            "execution_behavior_release_id",
            "cohort_id",
            "language",
            "track_key_hash",
            "agent_id",
            "accepted_output_kind",
            "sample_origin",
            "run_slot_kind",
            "scheduled_sample_id",
            "as_of",
            "accepted_at",
            "record_json",
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="production accepted output cannot carry KNOT lineage",
        ):
            conn.execute(
                f"INSERT INTO accepted_agent_outputs_v2 ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                (
                    *(accepted[column] for column in columns[:-1]),
                    json.dumps(accepted, separators=(",", ":"), sort_keys=True),
                ),
            )
