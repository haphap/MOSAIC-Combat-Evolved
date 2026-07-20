from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.scorecard.outcome_contracts import (
    EVOLUTION_ONLY_AGENT_IDS,
    OUTCOME_CONTRACTS,
    OUTCOME_CONTRACT_MANIFEST_PATH,
    OUTCOME_REALIZED_METRIC_SCHEMAS,
    TOOL_CONTRACT_MANIFEST_PATH,
    USAGE_WEIGHT_AGENT_IDS,
    load_outcome_contracts,
)


def test_outcome_contracts_cover_exact_runtime_roster_and_modes() -> None:
    assert len(OUTCOME_CONTRACTS) == 28
    assert len(USAGE_WEIGHT_AGENT_IDS) == 24
    assert set(EVOLUTION_ONLY_AGENT_IDS) == {
        "alpha_discovery",
        "autonomous_execution",
        "cio",
        "cro",
    }
    assert not set(USAGE_WEIGHT_AGENT_IDS) & set(EVOLUTION_ONLY_AGENT_IDS)
    assert len(OUTCOME_REALIZED_METRIC_SCHEMAS) == 8
    assert {
        row["realized_metric_schema_id"] for row in OUTCOME_CONTRACTS.values()
    } == set(OUTCOME_REALIZED_METRIC_SCHEMAS)


def test_outcome_contracts_freeze_schedule_and_label_ownership() -> None:
    assert OUTCOME_CONTRACTS["china"]["sample_schedule"]["kind"] == "EVENT_TRIGGERED"
    assert (
        OUTCOME_CONTRACTS["geopolitical"]["sample_schedule"]["kind"]
        == "EVENT_TRIGGERED"
    )
    assert (
        OUTCOME_CONTRACTS["market_breadth"]["sample_schedule"]["kind"]
        == "FIXED_NON_OVERLAP"
    )
    for row in OUTCOME_CONTRACTS.values():
        assert row["label_owner"] == "DETERMINISTIC_RUNTIME"
        assert row["fallback_allowed"] is False
        assert row["required_source_ids"]
    component_contracts = [
        row
        for row in OUTCOME_CONTRACTS.values()
        if row["component_composition_contract"] is not None
    ]
    assert len(component_contracts) == 7
    assert all(row["layer"] == "MACRO" for row in component_contracts)


def test_standard_sector_outcomes_bind_active_v4_scoring_snapshots() -> None:
    sector_contracts = [
        row
        for row in OUTCOME_CONTRACTS.values()
        if row["metric_family"] == "STANDARD_SECTOR"
    ]
    assert len(sector_contracts) == 9
    for contract in sector_contracts:
        assert contract["metric_schema_id"] == (
            "standard_sector_direction_pick_metrics_v3"
        )
        assert "sector_research_snapshot_v4" in contract["required_source_ids"]
        assert (
            "sector_pit_direction_constituent_snapshot_v3"
            not in contract["required_source_ids"]
        )


def test_outcome_contract_loader_rejects_registry_hash_tampering(tmp_path: Path) -> None:
    payload = json.loads(OUTCOME_CONTRACT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["contracts"][0]["primary_label_id"] = "tampered"
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="registry_hash mismatch"):
        load_outcome_contracts(path, TOOL_CONTRACT_MANIFEST_PATH)
