from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator

from mosaic.scorecard import prompt_optimizer_store
from mosaic.scorecard.canonical_json import canonical_string_sort_key


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "prompt_optimizer_cross_runtime_conformance_v1.json"
)
SCHEMA_ROOT = Path(__file__).parent.parent / "schemas"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_prompt_optimizer_numeric_seed_order_matches_fixture() -> None:
    row = _fixture()["numericSeedOrder"]

    assert sorted(row["input"]) == row["expected"]


def test_prompt_optimizer_ordered_aggregate_matches_fixture() -> None:
    row = _fixture()["orderedAggregation"]
    candidate_scores = [row["candidateScore"]] * row["repeatCount"]
    champion_scores = [row["championScore"]] * row["repeatCount"]
    deltas = [
        candidate - champion
        for candidate, champion in zip(
            candidate_scores, champion_scores, strict=True
        )
    ]

    assert prompt_optimizer_store._mean(candidate_scores) == row[
        "expectedCandidateMean"
    ]
    assert prompt_optimizer_store._mean(champion_scores) == row[
        "expectedChampionMean"
    ]
    assert prompt_optimizer_store._mean(deltas) == row["expectedPairedDelta"]


def test_prompt_optimizer_jcs_utf16_order_matches_fixture() -> None:
    row = _fixture()["unicodeRefOrder"]

    assert sorted(row["input"], key=canonical_string_sort_key) == row[
        "expected"
    ]


def test_prompt_optimizer_equal_score_tie_matches_fixture() -> None:
    row = _fixture()["equalScoreTie"]
    scored = [
        (row["score"], candidate_id)
        for candidate_id in row["inputCandidateIds"]
    ]
    winner = sorted(
        scored,
        key=lambda item: (-item[0], canonical_string_sort_key(item[1])),
    )[0][1]

    assert winner == row["expectedWinner"]


def test_prompt_optimizer_timestamp_precision_matches_fixture() -> None:
    row = _fixture()["timestampPrecision"]

    assert [
        prompt_optimizer_store._instant(value).microsecond
        for value in row["accepted"]
    ] == [0, 100_000, 120_000, 123_000]
    with pytest.raises(ValueError, match="timestamp_precision_invalid"):
        prompt_optimizer_store._instant(row["rejectedMinute"])
    with pytest.raises(ValueError, match="timestamp_precision_invalid"):
        prompt_optimizer_store._instant(row["rejectedSubMillisecond"])


def test_generated_prompt_optimizer_schema_uses_strict_string_boundaries() -> None:
    candidate_schema = json.loads(
        (SCHEMA_ROOT / "prompt_candidate_v1.schema.json").read_text(encoding="utf-8")
    )
    run_schema = json.loads(
        (SCHEMA_ROOT / "prompt_experiment_run_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    fragments = [
        candidate_schema["properties"]["candidateId"],
        candidate_schema["properties"]["promptRefs"]["properties"]["zh"],
        candidate_schema["properties"]["hypothesis"],
        run_schema["properties"]["metrics"]["propertyNames"],
    ]

    for fragment in fragments:
        validator = Draft7Validator(fragment)
        assert validator.is_valid("canonical")
        for suffix in ("\n", "\r", "\r\n", "\u2028", "\ufeff"):
            assert not validator.is_valid(f"canonical{suffix}")
