from __future__ import annotations

import pytest

from mosaic.scorecard.knot_v2 import (
    KNOT_RESEARCH_SCORE_CONTRACT,
    KNOT_RUNTIME_CONTRACT,
    build_knot_research_score,
    evaluate_knot_promotion,
    evaluate_knot_rollback,
    normalized_sector_inference_cost,
)


def test_python_loads_the_typescript_generated_knot_contract() -> None:
    assert KNOT_RUNTIME_CONTRACT["knot_runtime_contract_manifest_version"] == (
        "knot_runtime_contract_manifest_v2"
    )
    assert KNOT_RESEARCH_SCORE_CONTRACT["agent_failure_score"] == -2


def test_knot_score_formula_matches_typescript_fixture() -> None:
    cost = normalized_sector_inference_cost(
        input_tokens=50,
        output_tokens=25,
        total_stage_input_token_cap=100,
        total_stage_output_token_cap=100,
    )
    assert cost == pytest.approx(0.375)
    assert build_knot_research_score(
        disposition="SCORE",
        agent_kind="STANDARD_SECTOR",
        normalized_score=-1,
        normalized_inference_cost=1,
        conflict_review_triggered=True,
    )["research_comparison_score"] == pytest.approx(-1.25)
    assert build_knot_research_score(
        disposition="AGENT_FAILURE",
        agent_kind="NON_SECTOR",
    )["research_comparison_score"] == -2


def _pairs(delta: float) -> list[dict]:
    contract_hash = KNOT_RESEARCH_SCORE_CONTRACT["research_score_contract_hash"]
    return [
        {
            "knot_pair_id": f"pair-{index:02d}",
            "pair_sequence": index,
            "pair_disposition": "ACCOUNTABLE",
            "research_score_contract_hash": contract_hash,
            "champion_research_comparison_score": 0.1,
            "candidate_research_comparison_score": 0.1 + delta,
            "champion_raw_research_score": 0.1,
            "candidate_raw_research_score": 0.1 + delta,
        }
        for index in range(1, 31)
    ]


def test_knot_promotion_requires_all_paired_gates() -> None:
    promoted = evaluate_knot_promotion(
        paired_scores=_pairs(0.1),
        champion_operational_reliability=0.95,
        candidate_operational_reliability=0.94,
        benjamini_hochberg_q=0.01,
        maximum_holdout_regime_degradation=0.02,
    )
    assert promoted["promotion_disposition"] == "PROMOTE"
    assert promoted["block_bootstrap_95pct_ci_lower"] == pytest.approx(0.1)

    rejected = evaluate_knot_promotion(
        paired_scores=_pairs(0.04),
        champion_operational_reliability=0.95,
        candidate_operational_reliability=0.8,
        benjamini_hochberg_q=0.1,
        maximum_holdout_regime_degradation=0.06,
        hard_gate_failures=["unauthorized_tool"],
    )
    assert rejected["promotion_disposition"] == "REJECT"
    assert {
        "comparison_mean_delta_below_floor",
        "candidate_operational_reliability_regressed",
        "multiple_testing_q_exceeded",
        "holdout_regime_degradation_exceeded",
        "hard_gate:unauthorized_tool",
    }.issubset(rejected["reasons"])


def test_knot_post_promotion_shadow_monitors_retains_and_rolls_back() -> None:
    monitoring = evaluate_knot_rollback(
        paired_scores=_pairs(0.1)[:19],
        champion_operational_reliability=0.95,
        candidate_operational_reliability=0.95,
    )
    assert monitoring["rollback_disposition"] == "MONITOR"

    retained = evaluate_knot_rollback(
        paired_scores=_pairs(0.1)[:20],
        champion_operational_reliability=0.95,
        candidate_operational_reliability=0.9,
    )
    assert retained["rollback_disposition"] == "RETAIN"

    rolled_back = evaluate_knot_rollback(
        paired_scores=_pairs(-0.1)[:20],
        champion_operational_reliability=0.95,
        candidate_operational_reliability=0.8,
    )
    assert rolled_back["rollback_disposition"] == "ROLLBACK"
    assert {
        "post_promotion_comparison_mean_breached",
        "post_promotion_raw_mean_negative",
        "post_promotion_operational_reliability_breached",
    }.issubset(rolled_back["reasons"])

    immediate = evaluate_knot_rollback(
        paired_scores=[],
        champion_operational_reliability=1,
        candidate_operational_reliability=1,
        hard_gate_failures=["privacy_boundary"],
    )
    assert immediate["rollback_disposition"] == "ROLLBACK"
