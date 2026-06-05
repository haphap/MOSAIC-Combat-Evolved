from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    LockboxReview,
    evaluate_lockbox_review,
    summarize_lockbox_reviews,
)


def test_lockbox_not_opened_blocks_final_promotion():
    decision = evaluate_lockbox_review(None)

    assert decision.state == "not_ready"
    assert not decision.production_allowed
    assert decision.next_state == "paper_trading"


def test_lockbox_pass_allows_final_promotion():
    decision = evaluate_lockbox_review(
        LockboxReview(
            experiment_family_id="FAM-CB-LIQUIDITY-2026Q2",
            experiment_id="EXP-CB-20260605-0001",
            opened_at="2026-06-05T15:00:00+08:00",
            opened_by="quant_research",
            open_count=1,
            result="passed",
        )
    )

    assert decision.state == "final_promotion_eligible"
    assert decision.production_allowed
    assert decision.next_state == "production"


def test_lockbox_reuse_or_search_after_open_requires_redesign():
    decision = evaluate_lockbox_review(
        LockboxReview(
            experiment_family_id="FAM-CB-LIQUIDITY-2026Q2",
            experiment_id="EXP-CB-20260605-0001",
            opened_at="2026-06-05T15:00:00+08:00",
            opened_by="quant_research",
            open_count=2,
            result="passed",
            parameter_search_after_open=True,
        )
    )

    assert decision.state == "redesign_required"
    assert not decision.production_allowed
    assert any("reused" in reason for reason in decision.reasons)
    assert any("parameter search" in reason for reason in decision.reasons)


def test_lockbox_summary_counts_redesigns():
    summary = summarize_lockbox_reviews(
        (
            LockboxReview(
                experiment_family_id="FAM",
                experiment_id="EXP-1",
                opened_at="2026-06-05",
                opened_by="quant",
                open_count=1,
                result="passed",
            ),
            LockboxReview(
                experiment_family_id="FAM",
                experiment_id="EXP-2",
                opened_at="2026-06-05",
                opened_by="quant",
                open_count=2,
                result="failed",
            ),
        )
    )

    assert summary["review_count"] == 2
    assert summary["production_allowed_count"] == 1
    assert summary["redesign_required_count"] == 1
    assert summary["reused_lockbox_count"] == 1


def test_central_bank_lockbox_registry_is_not_opened():
    payload = json.loads(
        Path("registry/lockbox/central_bank_lockbox_review.json").read_text(encoding="utf-8")
    )
    review = LockboxReview(**payload)
    decision = evaluate_lockbox_review(review)

    assert review.result == "not_opened"
    assert decision.state == "not_ready"
    assert not decision.production_allowed
