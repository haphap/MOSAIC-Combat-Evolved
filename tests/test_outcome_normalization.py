from __future__ import annotations

import json
from pathlib import Path

import pytest

from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.outcome_contracts import OUTCOME_CONTRACTS
from mosaic.scorecard.outcome_normalization import (
    OUTCOME_NORMALIZATION_REGISTRY_PATH,
    OUTCOME_NORMALIZATION_SCHEMA_PATH,
    load_outcome_normalization_registry,
    resolve_outcome_normalization_reference,
)


def _write_registry(path: Path, payload: dict) -> None:
    body = {key: value for key, value in payload.items() if key != "registry_hash"}
    path.write_text(
        json.dumps({**body, "registry_hash": canonical_hash(body)}),
        encoding="utf-8",
    )


def test_registry_resolves_every_agent_from_a_pit_release() -> None:
    registry = load_outcome_normalization_registry()
    assert registry["registry_hash"].startswith("sha256:")
    references = {
        agent_id: resolve_outcome_normalization_reference(
            agent_id,
            "2026-07-17T15:00:00+08:00",
        )
        for agent_id in OUTCOME_CONTRACTS
    }
    assert len(references) == 28
    assert all(row["scale"] == 1.0 for row in references.values())
    assert all(
        row["normalization_authority"] == "PRE_REGISTERED_COLD_START_UNIT_SCALE"
        for row in references.values()
    )
    assert all(
        row["normalization_registry_schema_hash"].startswith("sha256:")
        for row in references.values()
    )
    assert all(
        row["cutoff"] == "2026-07-17T15:00:00+08:00"
        for row in references.values()
    )
    assert all(
        row["normalization_effective_at"] == "2020-01-01T00:00:00+08:00"
        for row in references.values()
    )


def test_registry_has_no_implicit_pre_release_fallback() -> None:
    with pytest.raises(ValueError, match="no PIT normalization release"):
        resolve_outcome_normalization_reference(
            "china",
            "2019-12-31T15:00:00+08:00",
        )


def test_registry_rejects_rehashed_scale_or_authority_tampering(tmp_path: Path) -> None:
    payload = json.loads(
        OUTCOME_NORMALIZATION_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    payload["entries"][0]["scale"] = 0.01
    path = tmp_path / "normalization.json"
    _write_registry(path, payload)
    with pytest.raises(RuntimeError, match="cold-start normalization"):
        load_outcome_normalization_registry(path, OUTCOME_NORMALIZATION_SCHEMA_PATH)

    payload["entries"][0]["scale"] = 1.0
    payload["entries"][0]["scale_authority"] = "PIT_CALIBRATED_RELEASE"
    _write_registry(path, payload)
    with pytest.raises(RuntimeError, match="lacks a PIT window"):
        load_outcome_normalization_registry(path, OUTCOME_NORMALIZATION_SCHEMA_PATH)


def test_latest_effective_calibrated_release_wins_without_lookahead(tmp_path: Path) -> None:
    payload = json.loads(
        OUTCOME_NORMALIZATION_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    contract_version = OUTCOME_CONTRACTS["china"]["normalization_contract_version"]
    payload["entries"].append(
        {
            "normalization_contract_version": contract_version,
            "effective_at": "2026-07-18T00:00:00+08:00",
            "scale": 0.25,
            "scale_authority": "PIT_CALIBRATED_RELEASE",
            "calibration_sample_count": 60,
            "calibration_window_end": "2026-07-17T15:00:00+08:00",
        }
    )
    path = tmp_path / "normalization.json"
    _write_registry(path, payload)
    before = resolve_outcome_normalization_reference(
        "china",
        "2026-07-17T15:00:00+08:00",
        registry_path=path,
    )
    after = resolve_outcome_normalization_reference(
        "china",
        "2026-07-18T15:00:00+08:00",
        registry_path=path,
    )
    assert before["scale"] == 1.0
    assert after["scale"] == 0.25
    assert before["normalization_reference_id"] != after["normalization_reference_id"]


def test_registry_rejects_under_mature_or_reordered_calibration(tmp_path: Path) -> None:
    payload = json.loads(
        OUTCOME_NORMALIZATION_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    contract_version = OUTCOME_CONTRACTS["china"]["normalization_contract_version"]
    payload["entries"].append(
        {
            "normalization_contract_version": contract_version,
            "effective_at": "2026-07-18T00:00:00+08:00",
            "scale": 0.25,
            "scale_authority": "PIT_CALIBRATED_RELEASE",
            "calibration_sample_count": 29,
            "calibration_window_end": "2026-07-17T15:00:00+08:00",
        }
    )
    path = tmp_path / "normalization.json"
    _write_registry(path, payload)
    with pytest.raises(RuntimeError, match="at least 30 PIT samples"):
        load_outcome_normalization_registry(path, OUTCOME_NORMALIZATION_SCHEMA_PATH)

    payload["entries"][-1]["calibration_sample_count"] = 30
    payload["entries"][-1]["effective_at"] = "2019-12-31T00:00:00+08:00"
    payload["entries"][-1]["calibration_window_end"] = "2019-12-30T15:00:00+08:00"
    _write_registry(path, payload)
    with pytest.raises(RuntimeError, match="must begin with exactly one cold-start"):
        load_outcome_normalization_registry(path, OUTCOME_NORMALIZATION_SCHEMA_PATH)
