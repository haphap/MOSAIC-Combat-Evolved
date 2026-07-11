"""Deterministic point-in-time calculators for domain knob evaluation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


class DomainMetricInputError(ValueError):
    """Raised when a sample cannot satisfy a calculator contract."""


def _arm(sample: Mapping[str, Any], arm: str) -> Mapping[str, Any]:
    value = sample.get(arm)
    if not isinstance(value, Mapping):
        raise DomainMetricInputError(f"sample {arm!r} arm must be an object")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainMetricInputError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise DomainMetricInputError(f"{field} must be a finite number")
    return result


def calculate_signed_return(sample: Mapping[str, Any], arm: str) -> float:
    """Read a signed PIT outcome return for one experiment arm."""
    return _number(_arm(sample, arm).get("signed_return"), f"{arm}.signed_return")


def calculate_nonnegative_loss(sample: Mapping[str, Any], arm: str) -> float:
    """Read a loss magnitude represented as a nonnegative number."""
    value = _number(_arm(sample, arm).get("loss_magnitude"), f"{arm}.loss_magnitude")
    if value < 0:
        raise DomainMetricInputError(f"{arm}.loss_magnitude must be nonnegative")
    return value


def calculate_rate(sample: Mapping[str, Any], arm: str) -> float:
    """Read a binary event used by hit-rate and breach-rate metrics."""
    raw = _arm(sample, arm).get("event")
    if isinstance(raw, bool):
        return float(raw)
    value = _number(raw, f"{arm}.event")
    if value not in (0.0, 1.0):
        raise DomainMetricInputError(f"{arm}.event must be 0 or 1")
    return value


def calculate_bps_cost(sample: Mapping[str, Any], arm: str) -> float:
    """Read a realized nonnegative execution cost in basis points."""
    value = _number(_arm(sample, arm).get("cost_bps"), f"{arm}.cost_bps")
    if value < 0:
        raise DomainMetricInputError(f"{arm}.cost_bps must be nonnegative")
    return value


def calculate_calibration_error(sample: Mapping[str, Any], arm: str) -> float:
    """Calculate absolute probability calibration error for one observation."""
    values = _arm(sample, arm)
    probability = _number(values.get("probability"), f"{arm}.probability")
    outcome = _number(values.get("outcome"), f"{arm}.outcome")
    if not 0 <= probability <= 1:
        raise DomainMetricInputError(f"{arm}.probability must be in [0, 1]")
    if outcome not in (0.0, 1.0):
        raise DomainMetricInputError(f"{arm}.outcome must be 0 or 1")
    return abs(probability - outcome)


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for index, _ in indexed[start:end]:
            ranks[index] = average_rank
        start = end
    return ranks


def _spearman(scores: Sequence[float], outcomes: Sequence[float]) -> float:
    if len(scores) != len(outcomes) or len(scores) < 2:
        raise DomainMetricInputError("rank arrays must have equal length >= 2")
    score_ranks = _average_ranks(scores)
    outcome_ranks = _average_ranks(outcomes)
    score_mean = sum(score_ranks) / len(score_ranks)
    outcome_mean = sum(outcome_ranks) / len(outcome_ranks)
    covariance = sum(
        (left - score_mean) * (right - outcome_mean)
        for left, right in zip(score_ranks, outcome_ranks)
    )
    score_variance = sum((value - score_mean) ** 2 for value in score_ranks)
    outcome_variance = sum((value - outcome_mean) ** 2 for value in outcome_ranks)
    denominator = math.sqrt(score_variance * outcome_variance)
    if denominator == 0:
        raise DomainMetricInputError("rank arrays must not be constant")
    return covariance / denominator


def calculate_rank_correlation(sample: Mapping[str, Any], arm: str) -> float:
    """Calculate Spearman rank correlation from registered score/outcome arrays."""
    values = _arm(sample, arm)
    raw_scores = values.get("scores")
    raw_outcomes = values.get("outcomes")
    if (
        not isinstance(raw_scores, Sequence)
        or isinstance(raw_scores, (str, bytes))
        or not isinstance(raw_outcomes, Sequence)
        or isinstance(raw_outcomes, (str, bytes))
    ):
        raise DomainMetricInputError(f"{arm}.scores and {arm}.outcomes must be arrays")
    scores = [_number(value, f"{arm}.scores") for value in raw_scores]
    outcomes = [_number(value, f"{arm}.outcomes") for value in raw_outcomes]
    return _spearman(scores, outcomes)
