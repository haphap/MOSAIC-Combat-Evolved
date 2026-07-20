from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.scorecard.canonical_json import (
    CANONICAL_JSON_CONTRACT_VERSION,
    canonical_hash,
    canonical_json,
)


_CASES_PATH = Path(__file__).parent / "fixtures" / "canonical_json_v1_cases.json"


def test_cross_runtime_canonical_json_golden_corpus() -> None:
    assert CANONICAL_JSON_CONTRACT_VERSION == "rfc8785_jcs_v1"
    cases = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    for row in cases:
        assert canonical_json(row["value"]) == row["canonical"], row["name"]
        assert canonical_hash(row["value"]).startswith("sha256:")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_cross_runtime_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"value": value})


def test_cross_runtime_canonical_json_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="surrogate"):
        canonical_json({"value": "\ud800"})
    with pytest.raises(ValueError, match="not exactly representable"):
        canonical_json({"value": 9_007_199_254_740_993})
    with pytest.raises(TypeError, match="keys"):
        canonical_json({1: "not a JSON object"})
