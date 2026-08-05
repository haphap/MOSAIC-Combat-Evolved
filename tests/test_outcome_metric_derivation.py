from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from mosaic.scorecard.outcome_metric_derivation import (
    derive_authoritative_outcome_metrics,
)
from mosaic.scorecard.darwinian_updates import compute_outcome_utility


def _derive(
    agent_id: str,
    payload: dict[str, Any],
    members: list[dict[str, Any]],
    realized: dict[str, Any],
) -> dict[str, Any]:
    return derive_authoritative_outcome_metrics(
        agent_id=agent_id,
        accepted_payload=payload,
        opportunity_member_refs=members,
        realized_metrics=realized,
    )


def test_macro_actual_payload_forecast_mutations_are_authoritative() -> None:
    payload = {
        "agent_id": "china",
        "agent_contract_version": "macro_agent_contract_v2",
        "prompt_behavior_version": "macro_prompt_behavior_v2",
        "execution_behavior_version": "macro_execution_behavior_v2",
        "component_weight_contract_version": "macro_component_weights_v2",
        "direction": "SUPPORTIVE",
        "strength": 4,
        "persistence_horizon": "WEEKS",
        "evaluation_horizon_trading_days": 5,
        "model_confidence": 0.9,
        "deterministic_data_quality": 0.8,
        "confidence": 0.72,
        "channels": ["growth"],
        "claims": [{"claim_id": "claim:1"}],
        "claim_refs": ["claim:1"],
        "key_drivers": ["growth impulse"],
    }
    realized = {"role_path_metric": 0.3, "pit_volatility_scale": 0.5}

    supportive = _derive("china", payload, [{"event_id": "event:1"}], realized)
    adverse_payload = {**payload, "direction": "ADVERSE"}
    adverse = _derive("china", adverse_payload, [{"event_id": "event:1"}], realized)

    assert supportive["direction_sign"] == 1
    assert adverse["direction_sign"] == -1
    with pytest.raises(ValueError, match="owner mismatch"):
        _derive(
            "china",
            {**payload, "agent_id": "us_economy"},
            [{"event_id": "event:1"}],
            realized,
        )


def _sector_payload() -> dict[str, Any]:
    return {
        "sector_agent_id": "energy",
        "agent_contract_version": "sector_agent_contract_v3",
        "prompt_behavior_version": "sector_prompt_behavior_v3",
        "execution_behavior_version": "sector_execution_behavior_v3",
        "selection": {
            "selection_status": "SELECTED",
            "preferred_direction": {
                "direction_local_id": "direction-local:oil",
                "direction_id": "oil",
                "selection_role": "PREFERRED",
                "strength": 4,
            },
            "least_preferred_direction": {
                "direction_local_id": "direction-local:solar",
                "direction_id": "solar",
                "selection_role": "LEAST_PREFERRED",
                "strength": 3,
            },
            "preferred_security_status": "PICKS_PRESENT",
            "long_picks": [
                {
                    "pick_local_id": "pick:oil",
                    "ts_code": "600001.SH",
                    "position_action": "LONG",
                    "conviction": 0.8,
                }
            ],
            "least_preferred_security_status": "PICKS_PRESENT",
            "short_or_avoid_picks": [
                {
                    "pick_local_id": "pick:solar",
                    "ts_code": "600002.SH",
                    "position_action": "SHORT",
                    "conviction": 0.7,
                }
            ],
        },
        "preferred_security_shortlist_id": "shortlist:oil",
        "preferred_security_shortlist_hash": "sha256:oil",
        "least_preferred_security_shortlist_id": "shortlist:solar",
        "least_preferred_security_shortlist_hash": "sha256:solar",
        "security_scoring_contract_version": "sector_security_scoring_v3",
        "security_scoring_contract_hash": "sha256:scoring",
        "model_confidence": 0.6,
        "directional_confidence": 0.6,
    }


def _sector_members() -> list[dict[str, Any]]:
    return [
        {
            "subindustry_id": "oil",
            "security_shortlist_id": "shortlist:oil",
            "security_shortlist_hash": "sha256:oil",
            "security_ts_codes": ["600001.SH", "600003.SH"],
        },
        {
            "subindustry_id": "solar",
            "security_shortlist_id": "shortlist:solar",
            "security_shortlist_hash": "sha256:solar",
            "security_ts_codes": ["600002.SH"],
        },
        {
            "subindustry_id": "wind",
            "security_shortlist_id": "shortlist:wind",
            "security_shortlist_hash": "sha256:wind",
            "security_ts_codes": [],
        },
    ]


def _sector_realized() -> dict[str, Any]:
    return {
        "direction_paths": [
            {
                "direction_id": "oil",
                "realized_return_5d": 0.03,
                "parent_sector_return_5d": 0.01,
                "realized_scaled_path": 0.3,
            },
            {
                "direction_id": "solar",
                "realized_return_5d": -0.02,
                "parent_sector_return_5d": 0.01,
                "realized_scaled_path": -0.3,
            },
            {
                "direction_id": "wind",
                "realized_return_5d": 0.0,
                "parent_sector_return_5d": 0.01,
                "realized_scaled_path": -0.1,
            },
        ],
        "security_paths": [
            {
                "side": "PREFERRED",
                "direction_id": "oil",
                "ts_code": "600001.SH",
                "net_alpha_5d": 0.03,
                "realized_scaled_alpha": 0.3,
            },
            {
                "side": "PREFERRED",
                "direction_id": "oil",
                "ts_code": "600003.SH",
                "net_alpha_5d": 0.01,
                "realized_scaled_alpha": 0.1,
            },
            {
                "side": "LEAST_PREFERRED",
                "direction_id": "solar",
                "ts_code": "600002.SH",
                "net_alpha_5d": -0.02,
                "realized_scaled_alpha": -0.2,
            },
        ],
    }


def test_sector_uses_exact_frozen_direction_and_security_domains() -> None:
    metrics = _derive(
        "energy", _sector_payload(), _sector_members(), _sector_realized()
    )
    utility, _ = compute_outcome_utility("STANDARD_SECTOR", metrics)
    assert [row["shortlist_size"] for row in metrics["security_leg_metrics"]] == [2, 1]
    assert sum(row["action"] == "UNSELECTED" for row in metrics["security_metrics"]) == 1
    assert utility == pytest.approx(metrics["combined_utility_delta"])

    extra = deepcopy(_sector_realized())
    extra["security_paths"].append(
        {
            "side": "PREFERRED",
            "direction_id": "oil",
            "ts_code": "600099.SH",
            "net_alpha_5d": 1.0,
            "realized_scaled_alpha": 1.0,
        }
    )
    with pytest.raises(ValueError, match="exactly equal the frozen shortlists"):
        _derive("energy", _sector_payload(), _sector_members(), extra)

    incomplete_authority = [
        {"subindustry_id": row["subindustry_id"]} for row in _sector_members()
    ]
    with pytest.raises(ValueError, match="must contain exactly"):
        _derive(
            "energy", _sector_payload(), incomplete_authority, _sector_realized()
        )

    hash_mutation = _sector_payload()
    hash_mutation["preferred_security_shortlist_hash"] = "sha256:mutated"
    with pytest.raises(ValueError, match="shortlist hash drift"):
        _derive("energy", hash_mutation, _sector_members(), _sector_realized())


def _relationship_payload() -> dict[str, Any]:
    return {
        "relationship_agent_id": "relationship_mapper",
        "agent_contract_version": "relationship_mapper_contract_v2",
        "prompt_behavior_version": "relationship_mapper_prompt_v2",
        "execution_behavior_version": "relationship_mapper_execution_v2",
        "opportunity_set_id": "relationship-opportunities:1",
        "opportunity_set_hash": "sha256:opportunities",
        "predictive_graph_status": "EDGES_PRESENT",
        "predictive_graph_abstention_confidence": None,
        "predictive_edges": [
            {
                "edge_candidate_id": "edge:1",
                "edge_id": "accepted-edge:1",
                "edge_hash": "sha256:edge1",
                "transmission_direction": "POSITIVE",
                "calibrated_confidence": 1.0,
            }
        ],
        "directional_confidence": 1.0,
    }


def test_relationship_uses_frozen_materiality_and_exact_edge_domain() -> None:
    realized = {
        "edge_paths": [
            {
                "edge_candidate_id": "edge:1",
                "realized_edge_state": "POSITIVE",
                "matched_non_edge_lift": 0.5,
            },
            {
                "edge_candidate_id": "edge:2",
                "realized_edge_state": "POSITIVE",
                "matched_non_edge_lift": 0.5,
            },
        ]
    }
    members = [
        {"edge_candidate_id": "edge:1", "materiality_weight": 9.0},
        {"edge_candidate_id": "edge:2", "materiality_weight": 1.0},
    ]
    metrics = _derive("relationship_mapper", _relationship_payload(), members, realized)
    assert [row["materiality_weight"] for row in metrics["edge_metrics"]] == [9.0, 1.0]
    assert metrics["weighted_edge_utility_delta"] == pytest.approx(0.625)

    reversed_weights = [
        {"edge_candidate_id": "edge:1", "materiality_weight": 1.0},
        {"edge_candidate_id": "edge:2", "materiality_weight": 9.0},
    ]
    reversed_metrics = _derive(
        "relationship_mapper", _relationship_payload(), reversed_weights, realized
    )
    assert reversed_metrics["weighted_edge_utility_delta"] == pytest.approx(-0.375)

    extra = deepcopy(realized)
    extra["edge_paths"].append(
        {
            "edge_candidate_id": "edge:3",
            "realized_edge_state": "POSITIVE",
            "matched_non_edge_lift": 1.0,
        }
    )
    with pytest.raises(ValueError, match="unexpected edge:3"):
        _derive("relationship_mapper", _relationship_payload(), members, extra)


def _superinvestor_payload() -> dict[str, Any]:
    return {
        "superinvestor_agent_id": "druckenmiller",
        "agent_contract_version": "superinvestor_contract_v2",
        "prompt_behavior_version": "superinvestor_prompt_v2",
        "execution_behavior_version": "superinvestor_execution_v2",
        "selection": {
            "selection_status": "SELECTED",
            "holding_period": "MONTHS",
            "picks": [
                {
                    "pick_local_id": "pick:1",
                    "ts_code": "600010.SH",
                    "position_action": "LONG",
                    "conviction": 0.8,
                }
            ],
        },
        "model_confidence": 0.7,
        "directional_confidence": 0.7,
        "abstention_confidence": 0.0,
    }


def test_superinvestor_freezes_candidate_tickers_and_does_not_penalize_losers() -> None:
    members = [
        {"candidate_ref": "candidate:1", "ts_code": "600010.SH"},
        {"candidate_ref": "candidate:2", "ts_code": "600011.SH"},
    ]
    realized = {
        "candidate_paths": [
            {
                "candidate_ref": "candidate:1",
                "ts_code": "600010.SH",
                "realized_net_excess_return_21d": 0.2,
            },
            {
                "candidate_ref": "candidate:2",
                "ts_code": "600011.SH",
                "realized_net_excess_return_21d": -0.4,
            },
        ]
    }
    metrics = _derive("druckenmiller", _superinvestor_payload(), members, realized)
    missed = next(row for row in metrics["pick_metrics"] if not row["selected"])
    assert missed["missed_opportunity_utility"] == 0.0

    ticker_mutation = deepcopy(realized)
    ticker_mutation["candidate_paths"][1]["ts_code"] = "600099.SH"
    with pytest.raises(ValueError, match="candidate_ref/ts_code binding drift"):
        _derive(
            "druckenmiller", _superinvestor_payload(), members, ticker_mutation
        )

    extra = deepcopy(realized)
    extra["candidate_paths"].append(
        {
            "candidate_ref": "candidate:3",
            "ts_code": "600012.SH",
            "realized_net_excess_return_21d": 1.0,
        }
    )
    with pytest.raises(ValueError, match="unexpected candidate:3"):
        _derive("druckenmiller", _superinvestor_payload(), members, extra)


def _cro_payload(probability: float = 0.8) -> dict[str, Any]:
    return {
        "agent_id": "cro",
        "agent_contract_version": "cro_contract_v2",
        "prompt_behavior_version": "cro_prompt_v2",
        "execution_behavior_version": "cro_execution_v2",
        "accepted_cro_review_id": "accepted-cro:1",
        "accepted_cro_review_hash": "sha256:cro",
        "frozen_candidate_universe_id": "risk-universe:1",
        "frozen_candidate_universe_hash": "sha256:risk",
        "review": {
            "review_disposition": "REVIEW_ACTIONS",
            "candidate_actions": [
                {
                    "action_local_id": "action:1",
                    "candidate_ref": "risk:1",
                    "ts_code": "600020.SH",
                    "action": "CAP_WEIGHT",
                    "predicted_risk_probability": probability,
                    "cro_action_ref": "cro-action:1",
                    "cro_action_hash": "sha256:action",
                }
            ],
        },
        "model_confidence": 0.8,
    }


def test_cro_actual_payload_and_realized_domain_mutations() -> None:
    members = [
        {
            "risk_candidate_id": "risk:1",
            "ts_code": "600020.SH",
            "proposed_target_weight": 0.1,
        }
    ]
    realized = {
        "candidate_states": [
            {
                "candidate_ref": "risk:1",
                "ts_code": "600020.SH",
                "realized_risk_state": 1,
                "realized_risk_evidence_ids": ["risk:evidence:1"],
            }
        ]
    }
    high = _derive("cro", _cro_payload(0.8), members, realized)
    low = _derive("cro", _cro_payload(0.2), members, realized)
    assert high["combined_utility_delta"] > low["combined_utility_delta"]

    extra = deepcopy(realized)
    extra["candidate_states"].append(
        {
            "candidate_ref": "risk:2",
            "ts_code": "600021.SH",
            "realized_risk_state": 1,
            "realized_risk_evidence_ids": ["risk:evidence:2"],
        }
    )
    with pytest.raises(ValueError, match="unexpected risk:2"):
        _derive("cro", _cro_payload(), members, extra)


def _alpha_none_payload(confidence: float) -> dict[str, Any]:
    return {
        "agent_id": "alpha_discovery",
        "agent_contract_version": "alpha_contract_v2",
        "prompt_behavior_version": "alpha_prompt_v2",
        "execution_behavior_version": "alpha_execution_v2",
        "accepted_alpha_discovery_id": "accepted-alpha:1",
        "accepted_alpha_discovery_hash": "sha256:alpha",
        "frozen_novel_candidate_universe_id": "alpha-universe:1",
        "frozen_novel_candidate_universe_hash": "sha256:alpha-universe",
        "selection": {"discovery_disposition": "NONE_FOUND", "novel_picks": []},
        "model_confidence": confidence,
    }


def test_alpha_none_found_target_and_confidence_skill_are_in_final_utility() -> None:
    members = [
        {"candidate_ref": "alpha:1", "ts_code": "600030.SH"},
        {"candidate_ref": "alpha:2", "ts_code": "600031.SH"},
    ]
    realized = {
        "candidate_paths": [
            {
                "candidate_ref": "alpha:1",
                "ts_code": "600030.SH",
                "realized_net_excess_return_5d": -0.2,
            },
            {
                "candidate_ref": "alpha:2",
                "ts_code": "600031.SH",
                "realized_net_excess_return_5d": 0.0,
            },
        ]
    }
    confident = _derive(
        "alpha_discovery", _alpha_none_payload(0.9), members, realized
    )
    unconfident = _derive(
        "alpha_discovery", _alpha_none_payload(0.1), members, realized
    )
    assert confident["output_confidence_forecast_loss"] == pytest.approx(0.01)
    assert confident["output_confidence_null_loss"] == pytest.approx(0.25)
    assert confident["combined_utility_delta"] == pytest.approx(0.024)
    assert confident["combined_utility_delta"] > unconfident["combined_utility_delta"]

    extra = deepcopy(realized)
    extra["candidate_paths"].append(
        {
            "candidate_ref": "alpha:3",
            "ts_code": "600032.SH",
            "realized_net_excess_return_5d": 1.0,
        }
    )
    with pytest.raises(ValueError, match="unexpected alpha:3"):
        _derive("alpha_discovery", _alpha_none_payload(0.9), members, extra)


@pytest.mark.parametrize(
    ("realized_return", "expected_sign"),
    [(-1.0, -1), (0.0, 0), (1.0, -1)],
)
def test_alpha_zero_conviction_candidate_cannot_erase_action_or_regret(
    realized_return: float,
    expected_sign: int,
) -> None:
    payload = _alpha_none_payload(0.0)
    payload["selection"] = {
        "discovery_disposition": "CANDIDATES",
        "novel_picks": [
            {
                "candidate_ref": "alpha:1",
                "ts_code": "600030.SH",
                "conviction": 0.0,
            }
        ],
    }
    metrics = _derive(
        "alpha_discovery",
        payload,
        [{"candidate_ref": "alpha:1", "ts_code": "600030.SH"}],
        {
            "candidate_paths": [
                {
                    "candidate_ref": "alpha:1",
                    "ts_code": "600030.SH",
                    "realized_net_excess_return_5d": realized_return,
                }
            ]
        },
    )
    combined = metrics["combined_utility_delta"]
    assert (combined > 0) - (combined < 0) == expected_sign
    if realized_return < 0:
        assert metrics["selected_pick_utility_delta"] == -1.0
    if realized_return > 0:
        assert metrics["incremental_candidate_utility_delta"] == -1.0


def _execution_payload(predicted_cost_bps: float) -> dict[str, Any]:
    return {
        "agent_id": "autonomous_execution",
        "agent_contract_version": "execution_contract_v2",
        "prompt_behavior_version": "execution_prompt_v2",
        "execution_behavior_version": "execution_v2",
        "accepted_execution_assessment_id": "accepted-execution:1",
        "accepted_execution_assessment_hash": "sha256:execution",
        "execution_mode": "PAPER",
        "frozen_order_intent_set_id": "order-set:1",
        "frozen_order_intent_set_hash": "sha256:orders",
        "assessment": {
            "execution_disposition": "ORDERS_ASSESSED",
            "order_assessments": [
                {
                    "assessment_local_id": "assessment:1",
                    "order_intent_ref": "order:1",
                    "ts_code": "600040.SH",
                    "requested_delta_weight": 0.1,
                    "feasibility": "FEASIBLE",
                    "feasibility_confidence": 0.8,
                    "predicted_cost_bps": predicted_cost_bps,
                    "execution_assessment_ref": "execution-assessment:1",
                    "execution_assessment_hash": "sha256:assessment",
                }
            ],
        },
        "model_confidence": 0.8,
    }


def test_execution_actual_payload_forecast_and_domain_mutations() -> None:
    members = [
        {
            "order_intent_id": "order:1",
            "ts_code": "600040.SH",
            "action": "BUY",
            "requested_delta_weight": 0.1,
        }
    ]
    realized = {
        "order_paths": [
            {
                "order_intent_ref": "order:1",
                "ts_code": "600040.SH",
                "realized_feasibility": "FEASIBLE",
                "realized_cost_bps": 10.0,
                "pit_cost_scale_bps": 10.0,
                "realized_delta_weight": 0.1,
                "realized_policy_compliance": 1,
                "outcome_evidence_ids": ["execution:evidence:1"],
            }
        ]
    }
    exact = _derive(
        "autonomous_execution", _execution_payload(10.0), members, realized
    )
    wrong = _derive(
        "autonomous_execution", _execution_payload(20.0), members, realized
    )
    assert exact["combined_utility_delta"] > wrong["combined_utility_delta"]

    extra = deepcopy(realized)
    extra["order_paths"].append(
        {
            **realized["order_paths"][0],
            "order_intent_ref": "order:2",
            "ts_code": "600041.SH",
        }
    )
    with pytest.raises(ValueError, match="unexpected order:2"):
        _derive(
            "autonomous_execution", _execution_payload(10.0), members, extra
        )


def _cio_payload(
    disposition: str,
    cash_weight: float,
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "agent_id": "cio",
        "decision_stage": "FINAL",
        "agent_contract_version": "cio_contract_v2",
        "prompt_behavior_version": "cio_prompt_v2",
        "execution_behavior_version": "cio_execution_v2",
        "frozen_controlled_target_set_id": "controlled-targets:1",
        "frozen_controlled_target_set_hash": "sha256:controlled",
        "final_portfolio_id": "final-portfolio:1",
        "final_portfolio_hash": "sha256:portfolio",
        "decision": {
            "decision_disposition": disposition,
            "cash_weight": cash_weight,
            "target_positions": targets,
        },
        "model_confidence": 0.8,
    }


def _cio_realized(
    *,
    realized_a: float,
    realized_b: float,
    realized_cash: float,
) -> dict[str, Any]:
    return {
        "position_paths": [
            {
                "ts_code": "600050.SH",
                "realized_weight": realized_a,
                "realized_net_return_5d": 0.02,
            },
            {
                "ts_code": "600051.SH",
                "realized_weight": realized_b,
                "realized_net_return_5d": -0.01,
            },
        ],
        "realized_cash_weight": realized_cash,
        "accepted_portfolio_net_return_5d": 0.0,
        "baseline_portfolio_net_return_5d": 0.01,
        "accepted_portfolio_max_drawdown_5d": -0.005,
        "baseline_portfolio_max_drawdown_5d": -0.02,
        "accepted_portfolio_turnover_cost": 0.002,
        "baseline_portfolio_turnover_cost": 0.0,
        "realized_constraint_compliance": 1,
    }


def _cio_context() -> list[dict[str, Any]]:
    return [
        {
            "controlled_target_set_id": "controlled-targets:1",
            "baseline_cash_weight": 0.2,
            "positions": [
                {
                    "position_ref": "position-ref:a",
                    "ts_code": "600050.SH",
                    "baseline_weight": 0.6,
                    "controlled_target_weight": 0.7,
                },
                {
                    "position_ref": "position-ref:b",
                    "ts_code": "600051.SH",
                    "baseline_weight": 0.2,
                    "controlled_target_weight": 0.0,
                },
            ],
        }
    ]


def test_cio_all_cash_and_exit_keep_the_pre_cio_baseline() -> None:
    all_cash = _derive(
        "cio",
        _cio_payload("ALL_CASH", 1.0, []),
        _cio_context(),
        _cio_realized(realized_a=0.0, realized_b=0.0, realized_cash=1.0),
    )
    assert all_cash["pre_cio_cash_weight"] == 0.2
    assert [row["pre_cio_weight"] for row in all_cash["portfolio_metrics"]] == [
        0.6,
        0.2,
    ]
    assert [row["target_weight"] for row in all_cash["portfolio_metrics"]] == [
        0.0,
        0.0,
    ]

    exit_payload = _cio_payload(
        "TARGET_PORTFOLIO",
        0.3,
        [
            {
                "position_local_id": "position:a",
                "ts_code": "600050.SH",
                "target_weight": 0.7,
                "position_decision": "ADD",
            },
            {
                "position_local_id": "position:b",
                "ts_code": "600051.SH",
                "target_weight": 0.0,
                "position_decision": "EXIT",
            },
        ],
    )
    exit_metrics = _derive(
        "cio",
        exit_payload,
        _cio_context(),
        _cio_realized(realized_a=0.7, realized_b=0.0, realized_cash=0.3),
    )
    exited = next(
        row for row in exit_metrics["portfolio_metrics"] if row["ts_code"] == "600051.SH"
    )
    assert exited["pre_cio_weight"] == 0.2
    assert exited["target_weight"] == 0.0

    invalid_all_cash = _cio_payload(
        "ALL_CASH",
        1.0,
        [{"ts_code": "600050.SH", "target_weight": 0.0}],
    )
    with pytest.raises(ValueError, match="ALL_CASH cannot carry"):
        _derive(
            "cio",
            invalid_all_cash,
            _cio_context(),
            _cio_realized(realized_a=0.0, realized_b=0.0, realized_cash=1.0),
        )


def test_cio_rejects_projection_baseline_and_extra_ticker_mutations() -> None:
    payload = _cio_realized(realized_a=0.7, realized_b=0.0, realized_cash=0.3)
    payload["baseline_cash_weight"] = 0.9
    with pytest.raises(ValueError):
        _derive(
            "cio",
            _cio_payload("ALL_CASH", 1.0, []),
            _cio_context(),
            payload,
        )

    payload = _cio_realized(realized_a=0.7, realized_b=0.0, realized_cash=0.3)
    payload["position_paths"].append(
        {
            "ts_code": "600052.SH",
            "realized_weight": 0.0,
            "realized_net_return_5d": 1.0,
        }
    )
    with pytest.raises(ValueError, match="unexpected 600052.SH"):
        _derive(
            "cio",
            _cio_payload("ALL_CASH", 1.0, []),
            _cio_context(),
            payload,
        )

    payload = _cio_realized(realized_a=0.7, realized_b=0.0, realized_cash=0.3)
    payload["baseline_portfolio_net_return_5d"] = 0.9
    with pytest.raises(ValueError, match="baseline return differs"):
        _derive(
            "cio",
            _cio_payload("ALL_CASH", 1.0, []),
            _cio_context(),
            payload,
        )

    payload = _cio_realized(realized_a=0.7, realized_b=0.0, realized_cash=0.3)
    payload["baseline_portfolio_turnover_cost"] = 0.001
    with pytest.raises(ValueError, match="baseline turnover must equal zero"):
        _derive(
            "cio",
            _cio_payload("ALL_CASH", 1.0, []),
            _cio_context(),
            payload,
        )
