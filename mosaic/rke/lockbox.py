"""Lockbox governance for final RKE promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


@dataclass(frozen=True)
class LockboxPolicy:
    lockbox_required_for_final_promotion: bool = True
    max_open_count: int = 1
    allow_parameter_search_after_open: bool = False
    allow_rule_design_after_open: bool = False
    failure_next_state: Literal["redesign", "deprecated"] = "redesign"


@dataclass(frozen=True)
class LockboxReview:
    experiment_family_id: str
    experiment_id: str
    opened_at: str
    opened_by: str
    open_count: int
    result: Literal["not_opened", "passed", "failed"]
    parameter_search_after_open: bool = False
    rule_design_after_open: bool = False
    notes: str = ""


@dataclass(frozen=True)
class LockboxDecision:
    state: Literal["not_ready", "final_promotion_eligible", "redesign_required", "rejected"]
    production_allowed: bool
    reasons: tuple[str, ...]
    next_state: str


def evaluate_lockbox_review(
    review: LockboxReview | None,
    *,
    policy: LockboxPolicy = LockboxPolicy(),
) -> LockboxDecision:
    if review is None or review.result == "not_opened":
        if policy.lockbox_required_for_final_promotion:
            return LockboxDecision(
                state="not_ready",
                production_allowed=False,
                reasons=("lockbox has not been opened",),
                next_state="paper_trading",
            )
        return LockboxDecision(
            state="final_promotion_eligible",
            production_allowed=True,
            reasons=(),
            next_state="production",
        )
    reasons: list[str] = []
    if review.open_count > policy.max_open_count:
        reasons.append("lockbox reused more than once")
    if review.parameter_search_after_open and not policy.allow_parameter_search_after_open:
        reasons.append("parameter search after lockbox open is forbidden")
    if review.rule_design_after_open and not policy.allow_rule_design_after_open:
        reasons.append("rule design after lockbox open is forbidden")
    if review.result == "failed":
        reasons.append("lockbox failed")
    if reasons:
        return LockboxDecision(
            state="redesign_required" if policy.failure_next_state == "redesign" else "rejected",
            production_allowed=False,
            reasons=tuple(reasons),
            next_state=policy.failure_next_state,
        )
    if review.result == "passed":
        return LockboxDecision(
            state="final_promotion_eligible",
            production_allowed=True,
            reasons=(),
            next_state="production",
        )
    return LockboxDecision(
        state="not_ready",
        production_allowed=False,
        reasons=("unsupported lockbox result",),
        next_state="paper_trading",
    )


def summarize_lockbox_reviews(
    reviews: Sequence[LockboxReview],
    *,
    policy: LockboxPolicy = LockboxPolicy(),
) -> dict[str, object]:
    decisions = [evaluate_lockbox_review(review, policy=policy) for review in reviews]
    return {
        "review_count": len(reviews),
        "production_allowed_count": sum(decision.production_allowed for decision in decisions),
        "redesign_required_count": sum(decision.state == "redesign_required" for decision in decisions),
        "reused_lockbox_count": sum(
            any("reused" in reason for reason in decision.reasons) for decision in decisions
        ),
    }
