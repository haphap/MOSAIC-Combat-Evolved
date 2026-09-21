import json

import pytest

from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.rke.agent_research_context import (
    FORBIDDEN_FIELD_NAMES,
    FORBIDDEN_FIELD_POLICY,
    RESEARCH_PRIOR_USE_POLICY,
    SECTOR_DIRECTION_KEYWORDS,
    SAFE_ACTIONABILITY,
    SCHEMA_VERSION,
    assert_research_context_boundary,
    build_rke_agent_research_materialization,
    build_rke_agent_research_context,
    build_rke_agent_research_context_from_rows,
    format_rke_agent_research_context,
    normalize_agent_id,
)
from mosaic.agents.utils import rke_research_tools


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_sector_direction_keyword_authority_closes_frozen_directions():
    from mosaic.dataflows.sector_snapshots import SECTOR_DIRECTION_IDS

    expected_keys = {
        (agent_id, direction_id)
        for agent_id, direction_ids in SECTOR_DIRECTION_IDS.items()
        for direction_id in direction_ids
    }
    assert set(SECTOR_DIRECTION_KEYWORDS) == expected_keys


def test_removed_superinvestor_gets_explicit_no_prior_reason():
    context = build_rke_agent_research_context_from_rows(
        agent_id="aschenbrenner",
        layer="superinvestor",

        metadata=[{"report_id": "RPT-REMOVED", "report_type": "个股研报"}],
    )

    assert context["context_items"] == []
    assert context["summary"]["no_prior_reason"] == "unsupported_superinvestor_agent"


def test_context_safety_rejects_forbidden_fields():
    with pytest.raises(ValueError, match="forbidden field"):
        assert_research_context_boundary({"claim_text": "private prose"})
    with pytest.raises(ValueError, match="forbidden field"):
        assert_research_context_boundary({"source_excerpt": "private prose"})


def test_max_items_zero_returns_no_context_items():
    context = build_rke_agent_research_context_from_rows(
        agent_id="dollar",
        layer="macro",
        max_items=0,

    )

    assert context["context_items"] == []


def test_rke_research_tool_formats_context(monkeypatch):
    def fake_context(**_kwargs):
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "no_prior_reason": "no_applicable_prior_for_agent_request",
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }

    monkeypatch.setattr(rke_research_tools, "build_rke_agent_research_context", fake_context)
    output = rke_research_tools.get_rke_research_context.invoke(
        {"agent_id": "dollar", "as_of_date": "2026-06-27", "layer": "macro"}
    )

    assert "Runtime preflight:" not in output
    assert "RKE research context for macro.dollar" in output
    assert "research_only=true" in output


def test_rke_preflight_failure_is_a_tool_execution_error(monkeypatch):
    from types import SimpleNamespace

    from mosaic.bridge.handlers import tools as bridge_tools
    from mosaic.bridge.protocol import RpcError, TOOL_EXECUTION_ERROR

    monkeypatch.setattr(
        rke_research_tools, "build_rke_agent_research_context", lambda **_kwargs: {}
    )
    monkeypatch.setattr(
        bridge_tools,
        "get_capability_store",
        lambda: SimpleNamespace(
            call_tool_result=lambda _capability, _name, args: (
                rke_research_tools.get_rke_research_context.invoke(args)
            )
        ),
    )
    with pytest.raises(RpcError) as error:
        bridge_tools.tools_call(
            {
                "capability": {},
                "name": "get_rke_research_context",
                "args": {"agent_id": "cro", "as_of_date": "2026-07-09"},
            }
        )
    assert error.value.code == TOOL_EXECUTION_ERROR
    assert error.value.data == {"reason_code": "RKE_CONTEXT_PREFLIGHT_FAILED"}
    assert "RKE context preflight failed" in error.value.message
    assert "context_items_missing" in error.value.message


def test_rke_runtime_context_preflight_blocks_summary_current_data_missing():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": False,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "summary_current_data_required_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_current_data_guard():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "current_data_required_missing" in str(error.value)
    assert "current_data_required_fields_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_bad_current_data_fields():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": [],
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "current_data_required_fields_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_bad_item_shadow_policy():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": True,
                    "use_policy": "production_signal",
                    "actionability": "trade_allowed",
                    "actionability_guard": "none",
                }
            ],
            "summary": {"truncated_item_count": 0, "current_data_required": True},
        }
    )

    assert "item_production_signal_not_disabled" in str(error.value)
    assert "item_use_policy_invalid" in str(error.value)
    assert "item_actionability_invalid" in str(error.value)
    assert "item_actionability_guard_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_context_metadata():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_series",
                    "target_id": "USDCNY",
                    "metric_family": "fx_rate",
                    "statistical_reliability_bucket": "limited",
                    "n_effective": 3.0,
                    "regime_types": ["", 3],
                    "known_failure_mode_tags": [],
                    "recipe_ids": [],
                    "tool_gap_ids": [],
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "item_context_metadata_missing" in str(error.value)
    assert "item_regime_types_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_item_target_metadata():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "item_target_metadata_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_missing_redacted_claim_id():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "item_count": 1,
                "matched_item_count": 1,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "redacted_claim_id_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_empty_context_without_no_prior_reason():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "no_prior_reason_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_requested_agent_mismatch():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "requested_agent_id": "burry",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026-06-27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "requested_agent_id_mismatch" in str(error.value)


def test_rke_runtime_context_preflight_blocks_bad_as_of_date():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "macro",
            "as_of_date": "2026/06/27",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "as_of_date_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_layer_agent_mismatch():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "schema_version": SCHEMA_VERSION,
            "layer": "sector",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "forbidden_field_count": len(FORBIDDEN_FIELD_NAMES),
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "layer_agent_mismatch" in str(error.value)


def test_rke_runtime_context_preflight_blocks_schema_version_mismatch():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "schema_version": "legacy_context",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": FORBIDDEN_FIELD_POLICY,
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "schema_version_mismatch" in str(error.value)


def test_rke_runtime_context_preflight_blocks_forbidden_field_policy():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [],
            "summary": {
                "item_count": 0,
                "matched_item_count": 0,
                "private_text_included": False,
                "forbidden_field_policy": "not_enforced",
                "truncated_item_count": 0,
                "current_data_required": True,
                "ranking_policy_id": "rke_agent_research_context_rank_v3",
            },
        }
    )

    assert "forbidden_field_policy_invalid" in str(error.value)


def test_rke_runtime_context_preflight_blocks_top_level_policy_boundary():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": False,
            "production_signal_allowed": False,
            "actionability": "trade_allowed",
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "ranking_reason_codes": ["agent_specific_match"],
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                }
            ],
            "summary": {
                "private_text_included": True,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "research_only_missing" in str(error.value)
    assert "context_actionability_guard_invalid" in str(error.value)
    assert "private_text_boundary_missing" in str(error.value)


def test_rke_runtime_context_preflight_blocks_hidden_private_fields():
    error = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": [
                {
                    "redacted_claim_id": "FCRED-1",
                    "target_type": "macro_asset",
                    "target_id": ".mosaic/rke/private.pdf",
                    "retrieval_rank": 1,
                    "priority_bucket": "high",
                    "current_data_required": True,
                    "current_data_required_fields": ["current_data_confirmation"],
                    "production_signal_allowed": False,
                    "use_policy": RESEARCH_PRIOR_USE_POLICY,
                    "actionability_guard": SAFE_ACTIONABILITY,
                    "claim_text": "private prose",
                }
            ],
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "public_safe_context_violation" in str(error.value)
    assert ".mosaic/rke/private.pdf" not in str(error.value)


def test_rke_runtime_context_preflight_blocks_malformed_context_items():
    malformed = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": "not-a-list",
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )
    non_object = pytest.raises(
        DataVendorUnavailable,
        rke_research_tools.format_rke_runtime_context,
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "ranking_policy_id": "rke_agent_research_context_rank_v3",
            "context_items": ["not-an-object"],
            "summary": {
                "private_text_included": False,
                "truncated_item_count": 0,
                "current_data_required": True,
            },
        }
    )

    assert "context_items_malformed" in str(malformed.value)
    assert "context_item_not_object" in str(non_object.value)


def test_normalize_agent_id_accepts_ts_and_rke_forms():
    assert normalize_agent_id("dollar", "macro") == "macro.dollar"
    assert normalize_agent_id("sector.semiconductor") == "sector.semiconductor"
    assert normalize_agent_id("ackman", "superinvestor") == "superinvestor.ackman"
    assert (
        normalize_agent_id("autonomous_execution", "decision")
        == "decision.autonomous_execution"
    )
    assert format_rke_agent_research_context(
        {
            "agent_id": "macro.dollar",
            "research_only": True,
            "production_signal_allowed": False,
            "actionability": SAFE_ACTIONABILITY,
            "context_items": [],
        }
    )


def test_basic_context_respects_later_report_accessibility():
    context = build_rke_agent_research_context_from_rows(
        agent_id="financials", layer="sector", as_of_date="2026-07-09",

        metadata=[{
            "report_id": "RPT-ACCESS", "publish_datetime": "2026-07-01",
            "accessible_datetime": "2026-07-10",
        }],
    )
    assert context["context_items"] == []


def test_research_cases_reach_runtime_with_authorization_pit_and_source_diversity(tmp_path):
    case = {
        "question": "Inventory and margins", "historical_regime": "Inventory liquidation",
        "reasoning_chain": ["Inventory falls", "Discounting slows", "Margins recover"],
        "evidence": [], "assumptions": [], "invalidation_conditions": [], "conclusion": "",
    }
    metadata = [
        {"report_id": report, "source_id": f"SRC-{report}", "report_type": "行业研报",
         "sector": "半导体", "publish_datetime": "2025-01-01",
         "license_class": "operator_approved_internal_research_use",
         "derived_claim_storage_allowed": "operator_approved_internal_use"}
        for report in ("R1", "R2", "UNAUTHORIZED", "FUTURE")
    ]
    metadata[2]["derived_claim_storage_allowed"] = False
    metadata[3]["accessible_datetime"] = "2027-01-01"
    footprints = [
        {"footprint_id": ident, "report_id": report, "source_id": f"SRC-{report}",
         "source_span_ids": ["PRIVATE-SPAN"], "sector": "半导体", "research_case": case,
         "target_agent_candidates": ["sector.semiconductor"]}
        for ident, report in (("A", "R1"), ("B", "R1"), ("C", "R2"),
                              ("D", "UNAUTHORIZED"), ("E", "FUTURE"))
    ]
    context = build_rke_agent_research_context_from_rows(
        agent_id="semiconductor", as_of_date="2026-01-01", footprints=footprints,
        metadata=metadata, max_items=2,
    )
    assert len(context["context_items"]) == 2
    assert context["summary"]["matched_item_count"] == 2
    assert context["summary"]["private_text_included"] is True
    rendered = rke_research_tools.format_rke_runtime_context(context)
    assert "Inventory falls → Discounting slows → Margins recover" in rendered
    assert "Current applicability: unassessed" in rendered
    assert "PRIVATE-SPAN" not in rendered
    assert "SRC-R1" not in json.dumps(context)
    assert all(item["research_case"] == case for item in context["context_items"])
    directory = tmp_path / "registry/report_intelligence"
    directory.mkdir(parents=True)
    for name, rows in (("analytical_footprints", footprints), ("report_metadata", metadata),
                       ("forecast_claims", [])):
        _write_jsonl(directory / f"{name}.jsonl", rows)
    materialized = build_rke_agent_research_materialization(
        root=tmp_path, agent_id="semiconductor", as_of_date="2026-01-01", max_items=2,
    )
    assert materialized["context"] == context
    assert "forecast_claims.jsonl" not in materialized["input_bytes"]
    (directory / "forecast_claims.jsonl").write_text("not valid JSON: retired")
    assert build_rke_agent_research_materialization(
        root=tmp_path, agent_id="semiconductor", as_of_date="2026-01-01", max_items=2,
    ) == materialized
    assert set(materialized["source_ids"]) == {"SRC-R1", "SRC-R2"}
    assert materialized["input_bytes"]["analytical_footprints.jsonl"] == (
        directory / "analytical_footprints.jsonl"
    ).read_bytes()

    first_only = build_rke_agent_research_context_from_rows(
        agent_id="semiconductor", as_of_date="2026-01-01", footprints=footprints[:2],
        metadata=metadata, max_items=2,
    )
    assert {r["redacted_claim_id"] for r in context["context_items"]} != {
        r["redacted_claim_id"] for r in first_only["context_items"]
    }


def test_macro_research_case_is_not_routed_as_a_generic_industry():
    case = {"question": "How does tightening affect liquidity?",
            "historical_regime": "Monetary tightening",
            "reasoning_chain": ["Funding costs rise", "Liquidity demand increases"]}
    context = build_rke_agent_research_context_from_rows(
        agent_id="cio", as_of_date="2026-01-01",
        metadata=[{"report_id": "R", "source_id": "S", "report_type": "宏观策略-海外",
                   "sector": "宏观策略", "publish_datetime": "2025-01-01",
                   "license_class": "operator_approved_internal_research_use",
                   "derived_claim_storage_allowed": True}],
        footprints=[{"footprint_id": "F", "report_id": "R", "source_id": "S",
                     "source_span_ids": ["PRIVATE"], "sector": "宏观策略",
                     "research_case": case}],
    )
    item = context["context_items"][0]
    assert item["domain"] == "macro"
    assert item["target_type"] == "unknown"
    assert item["target_id"] == "unknown"
    assert item["research_case"]["historical_regime"] == "Monetary tightening"


def test_research_case_transfer_keeps_original_target_and_prefers_requested_stock():
    case = {"question": "Inventory and margins", "historical_regime": "",
            "reasoning_chain": ["Inventory falls", "Discounting slows"],
            "evidence": [], "assumptions": [], "invalidation_conditions": [], "conclusion": ""}
    metadata = [{"report_id": ticker, "source_id": ticker, "ts_code": ticker,
                 "publish_datetime": "2025-01-01", "sector": "半导体",
                 "license_class": "operator_approved_internal_research_use",
                 "derived_claim_storage_allowed": True}
                for ticker in ("000001.SZ", "000002.SZ")]
    footprints = [{"footprint_id": ticker, "report_id": ticker, "source_id": ticker,
                   "source_span_ids": ["PRIVATE"], "research_case": case,
                   "target_agent_candidates": ["superinvestor.munger"]}
                  for ticker in ("000001.SZ", "000002.SZ")]
    context = build_rke_agent_research_context_from_rows(
        agent_id="superinvestor.munger", ticker="000002.SZ", as_of_date="2026-01-01",
        metadata=metadata, footprints=footprints,
    )
    items = context["context_items"]
    assert [item["ticker"] for item in items] == ["000002.SZ", "000001.SZ"]
    assert all(item["case_transfer_requires_current_data"] for item in items)
    assert items[1]["ticker_match"] is False


@pytest.mark.parametrize("agent_id", [
    "macro.us_financial_conditions", "macro.central_bank", "sector.financials",
    "superinvestor.munger", "decision.cio",
])
def test_research_case_access_does_not_require_entity_industry_or_role_tags(agent_id):
    case = {"question": "融资成本如何影响银行收入？", "historical_regime": "高利率与市场波动",
            "reasoning_chain": ["企业提前融资", "银行的融资中介需求增加"]}
    metadata = [{"report_id": "R", "source_id": "S", "report_type": "宏观策略-海外",
                 "sector": "宏观策略", "publish_datetime": "2025-01-01",
                 "license_class": "operator_approved_internal_research_use",
                 "derived_claim_storage_allowed": True}]
    footprint = {"footprint_id": "F", "report_id": "R", "source_id": "S",
                 "source_span_ids": ["PRIVATE"], "research_case": case}
    context = build_rke_agent_research_context_from_rows(
        agent_id=agent_id, ticker="600519.SH", sector="food_beverage",
        as_of_date="2026-01-01", metadata=metadata, footprints=[footprint],
    )
    assert context["summary"]["matched_item_count"] == 1
    assert context["context_items"][0]["research_case"]["question"] == case["question"]
    assert context["context_items"][0]["ticker_match"] is False
    assert case["question"] in rke_research_tools.format_rke_runtime_context(context)
    assert build_rke_agent_research_context_from_rows(
        agent_id="macro.not_a_real_agent", as_of_date="2026-01-01",
        metadata=metadata, footprints=[footprint],
    )["context_items"] == []


def test_explicit_stock_precedes_role_keywords_without_excluding_transfer_cases():
    metadata = [{"report_id": report, "source_id": report,
                 "ts_code": "600519.SH" if report == "unrelated" else "",
                 "sector": "银行" if report == "unrelated" else "宏观策略",
                 "publish_datetime": "2025-01-01",
                 "license_class": "operator_approved_internal_research_use",
                 "derived_claim_storage_allowed": True}
                for report in ("related", "unrelated")]
    footprints = [{"footprint_id": report, "report_id": report, "source_id": report,
                   "source_span_ids": ["PRIVATE"], "research_case": case}
                  for report, case in [
                      ("related", {"question": "银行在高利率环境下如何增加融资收入？",
                                   "historical_regime": "流动性收紧，融资成本上升",
                                   "reasoning_chain": ["企业提前融资", "银行中介收入增加"]}),
                      ("unrelated", {"question": "新品投放能否提高销量？",
                                     "reasoning_chain": ["新品投放", "渠道铺货增加"]}),
                  ]]
    for agent_id in ("sector.financials", "macro.us_financial_conditions"):
        context = build_rke_agent_research_context_from_rows(
            agent_id=agent_id, ticker="600519.SH", as_of_date="2026-01-01",
            metadata=metadata, footprints=footprints,
        )
        assert context["summary"]["matched_item_count"] == 2
        assert context["context_items"][0]["ticker_match"] is True
        broad = build_rke_agent_research_context_from_rows(
            agent_id=agent_id, as_of_date="2026-01-01",
            metadata=metadata, footprints=footprints,
        )
        assert broad["context_items"][0]["research_case"]["question"].startswith("银行")
        focused = build_rke_agent_research_context_from_rows(
            agent_id=agent_id, sector="新品", as_of_date="2026-01-01",
            metadata=metadata, footprints=footprints,
        )
        assert focused["summary"]["matched_item_count"] == 2
        assert focused["context_items"][0]["research_case"]["question"].startswith("新品")


@pytest.mark.parametrize("agent_id", ["cio", "decision.cio"])
@pytest.mark.parametrize("layer", ["", "decision"])
def test_decision_agent_name_is_stable_through_runtime_preflight(agent_id, layer):
    assert normalize_agent_id(agent_id, layer=layer) == "decision.cio"
    context = build_rke_agent_research_context_from_rows(
        agent_id=agent_id, layer=layer, as_of_date="2026-09-12",
    )
    assert "No matching RKE context" in rke_research_tools.format_rke_runtime_context(context)


def test_standalone_forecasts_cannot_be_retrieved_or_formatted(tmp_path):
    directory = tmp_path / "registry/report_intelligence"
    directory.mkdir(parents=True)
    (directory / "forecast_claims.jsonl").write_text("not valid JSON: retired")
    context = build_rke_agent_research_context(root=tmp_path, agent_id="cio", as_of_date="2026-01-01")
    assert context["context_items"] == []
    assert "No matching RKE context" in format_rke_agent_research_context(context)
