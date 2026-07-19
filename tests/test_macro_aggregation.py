from __future__ import annotations

import pytest

from mosaic.scorecard.macro_aggregation import (
    MACRO_AGENTS,
    TOMBSTONED_MACRO_AGENTS,
    MacroAggregationRetiredError,
    MacroTransmissionRejectedError,
    aggregate_macro_transmissions,
    validate_macro_transmissions,
)


def transmissions():
    return {
        agent: {
            "agent_id": agent,
            "direction": "NEUTRAL",
            "strength": 0,
            "confidence": 0.5,
        }
        for agent in MACRO_AGENTS
    }


def test_exact_v2_roster_and_tombstones():
    assert len(MACRO_AGENTS) == 10
    assert set(TOMBSTONED_MACRO_AGENTS).isdisjoint(MACRO_AGENTS)
    assert {"eu_economy", "us_financial_conditions", "euro_area_financial_conditions"} <= set(
        MACRO_AGENTS
    )


def test_validator_preserves_canonical_independent_transmissions():
    accepted = validate_macro_transmissions(transmissions())
    assert tuple(row["agent_id"] for row in accepted) == MACRO_AGENTS
    assert all("stance" not in row for row in accepted)


def test_missing_extra_identity_or_signal_semantics_reject():
    missing = transmissions()
    missing.pop("china")
    with pytest.raises(MacroTransmissionRejectedError, match="exact Macro roster"):
        validate_macro_transmissions(missing)
    invalid = transmissions()
    invalid["china"] = {**invalid["china"], "direction": "NEUTRAL", "strength": 2}
    with pytest.raises(MacroTransmissionRejectedError, match="strength=0"):
        validate_macro_transmissions(invalid)


def test_retired_six_factor_api_fails_closed():
    with pytest.raises(MacroAggregationRetiredError, match="consume ten"):
        aggregate_macro_transmissions(transmissions())
