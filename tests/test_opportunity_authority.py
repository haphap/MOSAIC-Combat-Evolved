from __future__ import annotations

import copy
import importlib
import json

import pytest

from mosaic.dataflows.sector_snapshots import SECTOR_UNIVERSE_MANIFEST
from mosaic.scorecard.opportunity_authority import (
    assert_authoritative_member_match,
    macro_authority_members,
    materialize_pre_run_authority,
    relationship_authority_members,
    sector_authority_members,
    superinvestor_authority_members,
)
from mosaic.scorecard.darwinian_v2 import canonical_hash


def test_event_macro_member_is_the_verified_schedule_trigger() -> None:
    authoritative = macro_authority_members(
        agent_id="china",
        snapshot={"snapshot_hash": "sha256:" + "1" * 64},
        schedule_slot={
            "trigger_event": {"event_id": "event:selected"},
            "outcome_schedule_slot_hash": "sha256:" + "2" * 64,
        },
    )

    assert authoritative == [{"event_id": "event:selected"}]
    with pytest.raises(ValueError, match="authoritative source"):
        assert_authoritative_member_match(
            agent_id="china",
            projected_members=[{"event_id": "event:other"}],
            authoritative_members=authoritative,
        )


def test_fixed_macro_path_identity_changes_with_source_snapshot() -> None:
    slot = {"trigger_event": None}
    first = macro_authority_members(
        agent_id="commodities",
        snapshot={"snapshot_hash": "sha256:" + "1" * 64},
        schedule_slot=slot,
    )
    second = macro_authority_members(
        agent_id="commodities",
        snapshot={"snapshot_hash": "sha256:" + "2" * 64},
        schedule_slot=slot,
    )

    assert first != second


def test_live_authority_binds_tool_snapshot_schedule_and_exact_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_hash = "sha256:" + "1" * 64
    slot_hash = "sha256:" + "2" * 64
    capabilities = importlib.import_module("mosaic.bridge.tool_capabilities")
    monkeypatch.setattr(
        capabilities,
        "materialize_tool_payload",
        lambda *_args, **_kwargs: json.dumps({"snapshot_hash": source_hash}),
    )

    authority = materialize_pre_run_authority(
        agent_id="commodities",
        as_of="2026-07-20T09:00:00+08:00",
        graph_run_id="graph-live-authority",
        schedule_slot={
            "outcome_schedule_slot_hash": slot_hash,
            "trigger_event": None,
        },
    )
    expected_body = {
        "contract_version": "evaluation_opportunity_source_authority_v1",
        "agent_id": "commodities",
        "source_tool_id": "get_commodity_conditions_snapshot",
        "source_snapshot_hash": source_hash,
        "schedule_slot_hash": slot_hash,
        "member_refs": authority["member_refs"],
    }
    expected_domain_hash = canonical_hash(expected_body)

    assert authority["domain_hash"] == expected_domain_hash
    assert authority["runtime_authority_binding"] == {
        "source_tool_id": "get_commodity_conditions_snapshot",
        "source_snapshot_hash": source_hash,
        "domain_hash": expected_domain_hash,
    }


def test_sector_authority_rejects_ticker_hash_and_member_tampering() -> None:
    scoring = SECTOR_UNIVERSE_MANIFEST["security_scoring_contract"]
    snapshot = {
        "sector_agent_id": "energy",
        "direction_ids": ["oil_gas"],
        "security_scoring_contract_version": scoring[
            "scoring_contract_version"
        ],
        "security_scoring_contract_hash": scoring["scoring_contract_hash"],
        "security_scoring_rows": [
            {
                "direction_id": "oil_gas",
                "availability_status": "AVAILABLE",
                "median_amount_20d_cny": 200.0,
                "ts_code": "600028.SH",
            },
            {
                "direction_id": "oil_gas",
                "availability_status": "AVAILABLE",
                "median_amount_20d_cny": 100.0,
                "ts_code": "601857.SH",
            },
        ],
    }
    authoritative = sector_authority_members(
        agent_id="energy", snapshot=snapshot
    )
    assert authoritative[0]["security_ts_codes"] == ["600028.SH", "601857.SH"]

    tampered_values = []
    ticker_tamper = copy.deepcopy(authoritative)
    ticker_tamper[0]["security_ts_codes"].pop()
    tampered_values.append(ticker_tamper)
    hash_tamper = copy.deepcopy(authoritative)
    hash_tamper[0]["security_shortlist_hash"] = "sha256:" + "0" * 64
    tampered_values.append(hash_tamper)
    tampered_values.append([])
    for tampered in tampered_values:
        with pytest.raises(ValueError, match="authoritative source"):
            assert_authoritative_member_match(
                agent_id="energy",
                projected_members=tampered,
                authoritative_members=authoritative,
            )


def test_relationship_authority_rejects_materiality_weight_tamper() -> None:
    authoritative = relationship_authority_members(
        {
            "prediction_opportunity_set": {
                "ordered_opportunities": [
                    {
                        "edge_candidate_id": "edge:1",
                        "materiality_weight": 0.75,
                    }
                ]
            }
        }
    )
    tampered = copy.deepcopy(authoritative)
    tampered[0]["materiality_weight"] = 0.5

    with pytest.raises(ValueError, match="authoritative source"):
        assert_authoritative_member_match(
            agent_id="relationship_mapper",
            projected_members=tampered,
            authoritative_members=authoritative,
        )


def test_superinvestor_authority_rejects_deleted_changed_or_forged_empty_set() -> None:
    authoritative = superinvestor_authority_members(
        agent_id="munger",
        snapshot={
            "candidate_universe": [
                {"candidate_ref": "candidate:1", "ts_code": "600001.SH"},
                {"candidate_ref": "candidate:2", "ts_code": "600002.SH"},
            ]
        },
    )
    changed = copy.deepcopy(authoritative)
    changed[0]["ts_code"] = "600003.SH"
    for tampered in ([], authoritative[:1], changed):
        with pytest.raises(ValueError, match="authoritative source"):
            assert_authoritative_member_match(
                agent_id="munger",
                projected_members=tampered,
                authoritative_members=authoritative,
            )
