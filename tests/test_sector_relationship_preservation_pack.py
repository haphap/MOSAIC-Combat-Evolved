from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.sector_relationship_preservation import (
    LEGACY_SECTOR_AGENT_IDS,
    NEW_SECTOR_AGENT_IDS,
    SECTOR_COMMON_TOOL_IDS,
    build_sector_relationship_preservation_overlay,
    evaluate_sector_relationship_significance_fixture,
    validate_sector_relationship_preservation_overlay,
)
from mosaic.rke.schema_validation import validate_json_schema_artifact


ROOT = Path(__file__).parents[1]
ARTIFACT = (
    ROOT
    / "registry/prompt_checks/capability_preservation/"
    "sector_relationship_preservation_overlay_v1.json"
)


def _reseal(value: dict) -> None:
    body = {key: item for key, item in value.items() if key != "manifest_hash"}
    value["manifest_hash"] = canonical_hash(body)


def _binding_by(overlay: dict, *, agent_id: str, tool_id: str) -> dict:
    return next(
        row
        for row in overlay["bindings"]
        if row["agent_id"] == agent_id and row["tool_id"] == tool_id
    )


def test_generated_sector_relationship_overlay_is_current_and_schema_valid():
    expected = build_sector_relationship_preservation_overlay(ROOT)
    assert expected == json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_sector_relationship_preservation_overlay(expected, root=ROOT)

    result = validate_json_schema_artifact(
        root=ROOT,
        schema_path="schemas/sector_relationship_preservation_overlay_v1.schema.json",
        artifact_path=(
            "registry/prompt_checks/capability_preservation/"
            "sector_relationship_preservation_overlay_v1.json"
        ),
        artifact_kind="json",
    )
    assert result.accepted, result.failures


def test_overlay_keeps_active_surface_frozen_and_covers_all_70_restored_bindings():
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    active = json.loads(
        (ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    active_tools = {
        tool
        for agent in active["agents"]
        for tool in agent["allowed_tools"]
    }
    restored_tools = {row["tool_id"] for row in overlay["bindings"]}

    assert len(overlay["bindings"]) == 70
    assert overlay["activation_state"] == "staged"
    assert overlay["activation_gate"] == "PR12_L1_L2_ATOMIC_ACTIVATION"
    assert restored_tools.isdisjoint(active_tools)
    assert overlay["base_active_agent_tool_manifest_hash"] == canonical_hash(active)

    for agent_id in (*LEGACY_SECTOR_AGENT_IDS, *NEW_SECTOR_AGENT_IDS):
        tools = {
            row["tool_id"]
            for row in overlay["bindings"]
            if row["agent_id"] == agent_id
        }
        assert set(SECTOR_COMMON_TOOL_IDS) <= tools
    assert {
        "get_income_statement",
        "get_balance_sheet",
        "get_cashflow",
    } <= {
        row["tool_id"]
        for row in overlay["bindings"]
        if row["agent_id"] == "semiconductor"
    }
    assert "get_yield_curve_cn" in {
        row["tool_id"]
        for row in overlay["bindings"]
        if row["agent_id"] == "financials"
    }
    assert {
        "get_rke_research_context",
        "get_stock_research",
        "get_supply_chain_evidence",
    } == {
        row["tool_id"]
        for row in overlay["bindings"]
        if row["agent_id"] == "relationship_mapper"
    }


def test_legacy_parameter_domains_and_new_sector_safe_contracts_are_explicit():
    overlay = build_sector_relationship_preservation_overlay(ROOT)

    report = _binding_by(
        overlay, agent_id="semiconductor", tool_id="get_broker_research"
    )
    report_properties = report["argument_schema"]["properties"]
    assert list(report_properties) == ["ticker", "date_from", "date_to", "max_reports"]
    assert report["argument_semantics"]["date_interval"] == "inclusive"
    assert report_properties["max_reports"]["minimum"] == 1
    assert report["authorized_domain_contract"]["max_reports_source"] == (
        "trusted_prepare_query_set"
    )
    assert report["materializer_contract"] == {
        "contract_version": "trusted_frozen_query_materializer_v1",
        "tool_id": "get_broker_research",
        "prepare_transport_policy": "TRUSTED_ONLY",
        "call_transport": False,
        "payload_store": "gitignored_private_sqlite",
        "source_receipt_descriptor_binding": True,
        "no_implicit_fallback": True,
        "derivation_contract": {
            "contract_version": "frozen_research_digest_lineage_v1",
            "model_hash_required": True,
            "prompt_hash_required": True,
            "source_payload_hash_required": True,
        },
    }
    assert report["materializer_contract_hash"] == canonical_hash(
        report["materializer_contract"]
    )

    policy = _binding_by(
        overlay, agent_id="semiconductor", tool_id="get_industry_policy_digest"
    )
    assert policy["materializer_contract"]["derivation_contract"] == report[
        "materializer_contract"
    ]["derivation_contract"]

    etf = _binding_by(overlay, agent_id="energy", tool_id="get_etf_holdings")
    assert list(etf["argument_schema"]["properties"]) == ["etf", "as_of", "top_n"]
    assert etf["argument_schema"]["properties"]["top_n"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 12,
        "default": 8,
    }

    indicators = _binding_by(
        overlay, agent_id="technology", tool_id="get_indicators"
    )
    assert list(indicators["argument_schema"]["properties"]) == [
        "ticker",
        "as_of",
        "lookback",
        "indicator",
    ]
    assert indicators["argument_schema"]["properties"]["lookback"]["minimum"] == 1
    assert indicators["argument_schema"]["properties"]["indicator"]["enum"] == [
        "atr",
        "boll",
        "boll_lb",
        "boll_ub",
        "close_10_ema",
        "close_200_sma",
        "close_50_sma",
        "macd",
        "macdh",
        "macds",
        "mfi",
        "rsi",
        "vwma",
    ]

    supply = _binding_by(
        overlay, agent_id="relationship_mapper", tool_id="get_supply_chain_evidence"
    )
    assert supply["materializer_contract"]["derivation_contract"] == {
        "contract_version": "official_supply_chain_evidence_v1",
        "authoritative_document_hash_required": True,
        "holder_graph_fallback_allowed": False,
        "capture_revision_policy": "FIRST_COMPLETE_CAPTURE_WINS",
        "same_key_retry_policy": "REUSE_WITHOUT_TRANSPORT",
    }

    for row in overlay["bindings"]:
        assert row["adaptive_query_contract"] == {
            "max_rounds": 3,
            "model_selects_arguments": True,
            "transport_allowed_during_prepare": True,
            "transport_allowed_during_call": False,
        }
        assert row["argument_schema_hash"] == canonical_hash(row["argument_schema"])
        assert row["argument_domain_selector_hash"] == canonical_hash(
            row["authorized_domain_contract"]
        )


def test_supply_chain_is_introduced_authoritative_evidence_not_holder_graph():
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    supply_chain = _binding_by(
        overlay,
        agent_id="relationship_mapper",
        tool_id="get_supply_chain_evidence",
    )
    holder_graph = _binding_by(
        overlay,
        agent_id="relationship_mapper",
        tool_id="get_rke_research_context",
    )

    assert supply_chain["semantic_capability_id"] == "relationship_supply_chain_evidence"
    assert supply_chain["disposition"] == "introduced"
    assert supply_chain["source_route_ids"] == ["official.company_supply_chain_disclosures"]
    assert "tushare.relationship_graph" not in supply_chain["source_route_ids"]
    assert supply_chain["output_semantics_hash"] != holder_graph["output_semantics_hash"]
    assert supply_chain["no_evidence_policy"] == "ABSTAIN_NO_FACTUAL_EDGE"

    corrupted = copy.deepcopy(overlay)
    row = _binding_by(
        corrupted,
        agent_id="relationship_mapper",
        tool_id="get_supply_chain_evidence",
    )
    row["source_route_ids"] = ["tushare.relationship_graph"]
    _reseal(corrupted)
    with pytest.raises(ValueError, match="supply-chain.*holder graph"):
        validate_sector_relationship_preservation_overlay(corrupted, root=ROOT)


def test_binding_knot_coverage_and_significance_fixtures_have_exact_closure():
    overlay = build_sector_relationship_preservation_overlay(ROOT)
    binding_ids = {row["binding_id"] for row in overlay["bindings"]}
    coverage_ids = {row["binding_id"] for row in overlay["knot_coverage"]}
    fixture_ids = {row["binding_id"] for row in overlay["significance_fixtures"]}
    assert binding_ids == coverage_ids == fixture_ids
    assert all(
        evaluate_sector_relationship_significance_fixture(row)["passed"]
        for row in overlay["significance_fixtures"]
    )

    missing = copy.deepcopy(overlay)
    missing["knot_coverage"].pop()
    _reseal(missing)
    with pytest.raises(ValueError, match="KNOT coverage exact closure"):
        validate_sector_relationship_preservation_overlay(missing, root=ROOT)

    ignored = copy.deepcopy(overlay["significance_fixtures"][0])
    ignored["counterevidence_handled"]["accepted_utility"] = ignored[
        "counterevidence_ignored"
    ]["accepted_utility"]
    assert not evaluate_sector_relationship_significance_fixture(ignored)["passed"]


def test_overlay_rejects_activation_round_drift_and_private_prose():
    overlay = build_sector_relationship_preservation_overlay(ROOT)

    activated = copy.deepcopy(overlay)
    activated["activation_state"] = "active"
    _reseal(activated)
    with pytest.raises(ValueError, match="must remain staged"):
        validate_sector_relationship_preservation_overlay(activated, root=ROOT)

    four_rounds = copy.deepcopy(overlay)
    four_rounds["bindings"][0]["adaptive_query_contract"]["max_rounds"] = 4
    _reseal(four_rounds)
    with pytest.raises(ValueError, match="max_rounds"):
        validate_sector_relationship_preservation_overlay(four_rounds, root=ROOT)

    prose = copy.deepcopy(overlay)
    prose["bindings"][0]["report_title"] = "licensed source title"
    _reseal(prose)
    with pytest.raises(ValueError, match="private prose"):
        validate_sector_relationship_preservation_overlay(prose, root=ROOT)


def test_overlay_rejects_self_resealed_route_and_binding_roster_drift():
    overlay = build_sector_relationship_preservation_overlay(ROOT)

    route_drift = copy.deepcopy(overlay)
    route_drift["routes"][0]["contract_version"] = "invented_contract_v9"
    _reseal(route_drift)
    with pytest.raises(ValueError, match="route catalog drift"):
        validate_sector_relationship_preservation_overlay(route_drift, root=ROOT)

    binding_drift = copy.deepcopy(overlay)
    report = _binding_by(
        binding_drift, agent_id="energy", tool_id="get_broker_research"
    )
    report["tool_id"] = "get_stock_research"
    body = {key: value for key, value in report.items() if key != "binding_id"}
    report["binding_id"] = "binding:" + canonical_hash(body)[7:]
    _reseal(binding_drift)
    with pytest.raises(ValueError, match="binding roster drift"):
        validate_sector_relationship_preservation_overlay(binding_drift, root=ROOT)
