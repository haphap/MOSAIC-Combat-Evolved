from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mosaic.rke.schema_validation import validate_json_schema_artifact
from mosaic.scorecard.canonical_json import canonical_hash
from mosaic.scorecard.l3_l4_preservation import (
    L3_TOOL_ROSTER,
    L4_STAGE_ROSTER,
    build_l3_l4_preservation_overlay,
    evaluate_l3_l4_significance_fixture,
    validate_l3_l4_preservation_overlay,
)


ROOT = Path(__file__).parents[1]
ARTIFACT = (
    ROOT
    / "registry/prompt_checks/capability_preservation/"
    "l3_l4_preservation_overlay_v1.json"
)


def _reseal(value: dict) -> None:
    body = {key: item for key, item in value.items() if key != "manifest_hash"}
    value["manifest_hash"] = canonical_hash(body)


def _binding_by(overlay: dict, *, agent_id: str, stage: str, tool_id: str) -> dict:
    return next(
        row
        for row in overlay["bindings"]
        if row["agent_id"] == agent_id
        and row["stage"] == stage
        and row["tool_id"] == tool_id
    )


def test_generated_l3_l4_overlay_is_current_and_schema_valid():
    expected = build_l3_l4_preservation_overlay(ROOT)
    assert expected == json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_l3_l4_preservation_overlay(expected, root=ROOT)

    result = validate_json_schema_artifact(
        root=ROOT,
        schema_path="schemas/l3_l4_preservation_overlay_v1.schema.json",
        artifact_path=(
            "registry/prompt_checks/capability_preservation/"
            "l3_l4_preservation_overlay_v1.json"
        ),
        artifact_kind="json",
    )
    assert result.accepted, result.failures


def test_overlay_preserves_exact_28_l3_and_5_l4_bindings_on_active_surface():
    overlay = build_l3_l4_preservation_overlay(ROOT)
    active = json.loads(
        (ROOT / "registry/prompt_checks/agent_tool_contract_manifest_v1.json").read_text(
            encoding="utf-8"
        )
    )
    preactivation = json.loads(
        (ARTIFACT.parent / "current_agent_tool_contract_snapshot_v1.json").read_text(
            encoding="utf-8"
        )
    )
    active_tools = {
        tool_id for agent in active["agents"] for tool_id in agent["allowed_tools"]
    }
    active_bindings = {
        (agent["agent_id"], stage, tool_id)
        for agent in active["agents"]
        for stage in agent["execution_stages"]
        for tool_id in agent["allowed_tools"]
    }
    restored = {(row["agent_id"], row["stage"], row["tool_id"]) for row in overlay["bindings"]}

    assert len(restored) == 33
    assert restored == {
        *((agent, agent, tool) for agent, tools in L3_TOOL_ROSTER.items() for tool in tools),
        *((agent, stage, "get_rke_research_context") for agent, stage in L4_STAGE_ROSTER),
    }
    active_stage_for_preservation = {
        "cro_review": "cro",
        "execution_feasibility": "autonomous_execution",
    }
    normalized_restored = {
        (agent_id, active_stage_for_preservation.get(stage, stage), tool_id)
        for agent_id, stage, tool_id in restored
    }
    assert normalized_restored <= active_bindings
    assert {
        "get_balance_sheet",
        "get_cashflow",
        "get_rke_research_context",
    } <= ({row["tool_id"] for row in overlay["bindings"]} & active_tools)
    assert overlay["activation_state"] == "staged"
    assert overlay["activation_gate"] == "PR13_L3_L4_ATOMIC_ACTIVATION"
    assert overlay["base_active_agent_tool_manifest_hash"] == canonical_hash(
        preactivation
    )
    assert _binding_by(
        overlay,
        agent_id="druckenmiller",
        stage="druckenmiller",
        tool_id="get_yield_curve_cn",
    )["source_route_ids"] == ["tushare.shibor_yield_curve"]


def test_l3_candidate_scope_and_initial_call_contracts_are_explicit():
    overlay = build_l3_l4_preservation_overlay(ROOT)
    expected_initial = {
        "ackman": [
            {"tool_id": "get_fundamentals", "ticker_source": "accepted_rank_1"},
            {
                "tool_id": "get_cashflow",
                "ticker_source": "accepted_rank_1",
                "frequency": "annual",
            },
        ],
        "munger": [
            {"tool_id": "get_fundamentals", "ticker_source": "accepted_rank_1"},
            {
                "tool_id": "get_cashflow",
                "ticker_source": "accepted_rank_1",
                "frequency": "annual",
            },
        ],
        "burry": [
            {"tool_id": "get_fundamentals", "ticker_source": "accepted_rank_1"},
            {
                "tool_id": "get_balance_sheet",
                "ticker_source": "accepted_rank_1",
                "frequency": "annual",
            },
        ],
        "druckenmiller": [],
    }
    assert overlay["l3_runtime_contract"] == {
        "candidate_authority": "get_superinvestor_candidate_snapshot",
        "candidate_scope_policy": "ACCEPTED_SCOPE_ONLY_NO_EXPANSION",
        "backup_candidate_policy": "ACCEPTED_SCOPE_ONLY",
        "report_rke_usage": "ANNOTATE_ONLY_CURRENT_CONFIRMATION_REQUIRED",
        "deterministic_initial_calls": expected_initial,
        "adaptive_follow_up_rounds": 3,
    }

    for row in overlay["bindings"]:
        if row["agent_id"] not in L3_TOOL_ROSTER:
            continue
        domain = row["authorized_domain_contract"]
        assert domain["candidate_scope_source"] == (
            "trusted_prepare_scope.accepted_candidate_tickers"
        )
        assert domain["candidate_expansion_allowed"] is False
        assert domain["backup_candidate_source"] == "accepted_candidate_tickers"
        if row["tool_id"] in {"get_rke_research_context", "get_stock_research"}:
            assert row["evidence_usage_contract"] == {
                "candidate_expansion_allowed": False,
                "usage": "ANNOTATE_ONLY",
                "current_confirmation_required": True,
            }


def test_l4_rke_prior_is_stage_bound_shadow_only_and_current_confirmed():
    overlay = build_l3_l4_preservation_overlay(ROOT)
    expected = {
        ("alpha_discovery", "alpha_discovery"),
        ("cro", "cro_review"),
        ("autonomous_execution", "execution_feasibility"),
        ("cio", "cio_proposal"),
        ("cio", "cio_final"),
    }
    actual = {
        (row["agent_id"], row["stage"])
        for row in overlay["bindings"]
        if row["agent_id"] not in L3_TOOL_ROSTER
    }
    assert actual == expected
    assert overlay["l4_rke_runtime_contract"] == {
        "injection_mode": "PROACTIVE_STAGE_BOUND_FROZEN_PRIOR",
        "layer": "decision",
        "max_items": 3,
        "shadow_only": True,
        "current_data_confirmation_required": True,
        "candidate_expansion_allowed": False,
        "transport_allowed_during_agent_run": False,
    }
    for agent_id, stage in expected:
        row = _binding_by(
            overlay,
            agent_id=agent_id,
            stage=stage,
            tool_id="get_rke_research_context",
        )
        assert row["adaptive_query_contract"] == {
            "max_rounds": 0,
            "model_selects_arguments": False,
            "transport_allowed_during_prepare": True,
            "transport_allowed_during_call": False,
        }
        assert row["argument_schema"]["properties"]["layer"]["const"] == "decision"


def test_binding_knot_and_significance_have_exact_closure():
    overlay = build_l3_l4_preservation_overlay(ROOT)
    binding_ids = {row["binding_id"] for row in overlay["bindings"]}
    assert binding_ids == {row["binding_id"] for row in overlay["knot_coverage"]}
    assert binding_ids == {
        row["binding_id"] for row in overlay["significance_fixtures"]
    }
    assert all(
        evaluate_l3_l4_significance_fixture(row)["passed"]
        for row in overlay["significance_fixtures"]
    )
    assert all(row["candidate_generation_allowed"] is False for row in overlay["knot_coverage"])

    missing = copy.deepcopy(overlay)
    missing["knot_coverage"].pop()
    _reseal(missing)
    with pytest.raises(ValueError, match="KNOT coverage exact closure"):
        validate_l3_l4_preservation_overlay(missing, root=ROOT)


def test_overlay_rejects_scope_expansion_activation_and_private_prose():
    overlay = build_l3_l4_preservation_overlay(ROOT)

    expanded = copy.deepcopy(overlay)
    expanded["bindings"][0]["authorized_domain_contract"][
        "candidate_expansion_allowed"
    ] = True
    _reseal(expanded)
    with pytest.raises(ValueError, match="candidate scope"):
        validate_l3_l4_preservation_overlay(expanded, root=ROOT)

    activated = copy.deepcopy(overlay)
    activated["activation_state"] = "active"
    _reseal(activated)
    with pytest.raises(ValueError, match="must remain staged"):
        validate_l3_l4_preservation_overlay(activated, root=ROOT)

    prose = copy.deepcopy(overlay)
    prose["bindings"][0]["report_title"] = "licensed source title"
    _reseal(prose)
    with pytest.raises(ValueError, match="private prose"):
        validate_l3_l4_preservation_overlay(prose, root=ROOT)
