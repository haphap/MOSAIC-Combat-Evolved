from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mosaic.scorecard.darwinian_v2 import canonical_hash
from mosaic.scorecard.store import (
    _load_trusted_execution_behavior_release,
)


def _release(seed: str) -> dict[str, Any]:
    release_content = {
        "schema_version": "execution_behavior_release_manifest_v3",
        "private_prompt_commit": seed * 40,
        "private_prompt_bootstrap": {"seed": seed},
        "provider_binding": {
            "provider": "provider",
            "model": f"model-{seed}",
            "base_url_mode": "PROVIDER_DEFAULT",
            "structured_output_mode": "JSON_SCHEMA_STRICT",
            "repair_policy": "BOUNDED_SCHEMA_REPAIR_V1",
        },
        "active_production_variants": [{"seed": seed}],
        "execution_contracts": [{"seed": seed}],
    }
    release_id = (
        "execution-behavior-release:"
        + canonical_hash(release_content).removeprefix("sha256:")
    )
    without_hash = {
        "schema_version": release_content["schema_version"],
        "execution_behavior_release_id": release_id,
        "private_prompt_commit": release_content["private_prompt_commit"],
        "private_prompt_bootstrap": release_content["private_prompt_bootstrap"],
        "provider_binding": release_content["provider_binding"],
        "active_production_variants": release_content[
            "active_production_variants"
        ],
        "execution_contracts": release_content["execution_contracts"],
    }
    return {
        **without_hash,
        "execution_behavior_release_hash": canonical_hash(without_hash),
    }


def _archive_path(root: Path, release: dict[str, Any]) -> Path:
    release_digest = release["execution_behavior_release_id"].removeprefix(
        "execution-behavior-release:"
    )
    release_hash = release["execution_behavior_release_hash"].removeprefix(
        "sha256:"
    )
    return root / f"{release_digest}--{release_hash}.json"


def _write_archive(root: Path, release: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = _archive_path(root, release)
    path.write_text(json.dumps(release), encoding="utf-8")
    return path


def test_committed_prompt_release_contract_points_to_an_exact_immutable_archive() -> None:
    root = Path(__file__).resolve().parents[1]
    contract_ref = json.loads(
        (
            root
            / "registry"
            / "prompt_checks"
            / "prompt_release_contract_ref_v2.json"
        ).read_text(encoding="utf-8")
    )
    execution_ref = contract_ref["sources"]["execution_behavior_release_archive"]
    active = json.loads(
        (root / execution_ref["path"]).read_text(encoding="utf-8")
    )

    assert active["execution_behavior_release_id"] == execution_ref["release_id"]
    assert active["execution_behavior_release_hash"] == execution_ref["release_hash"]
    assert (
        _load_trusted_execution_behavior_release(
            active["execution_behavior_release_id"]
        )
        == active
    )


def test_loader_resolves_future_prepared_release_without_trusting_active_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "archive"
    active = _release("a")
    prepared = _release("b")
    _write_archive(archive_root, active)
    _write_archive(archive_root, prepared)
    monkeypatch.setattr(
        "mosaic.scorecard.store._EXECUTION_BEHAVIOR_RELEASE_ARCHIVE_ROOT",
        archive_root,
    )
    assert (
        _load_trusted_execution_behavior_release(
            prepared["execution_behavior_release_id"]
        )
        == prepared
    )


def test_loader_rejects_release_id_or_archive_name_confusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "archive"
    requested = _release("a")
    different = _release("b")
    archive_root.mkdir()
    confused_path = _archive_path(archive_root, requested)
    confused_path.write_text(json.dumps(different), encoding="utf-8")
    monkeypatch.setattr(
        "mosaic.scorecard.store._EXECUTION_BEHAVIOR_RELEASE_ARCHIVE_ROOT",
        archive_root,
    )

    with pytest.raises(ValueError, match="release ID mismatch"):
        _load_trusted_execution_behavior_release(
            requested["execution_behavior_release_id"]
        )

    confused_path.unlink()
    valid_path = _write_archive(archive_root, requested)
    duplicate = valid_path.with_name(
        f"{requested['execution_behavior_release_id'].split(':', 1)[1]}--"
        f"{'f' * 64}.json"
    )
    duplicate.write_text(json.dumps(requested), encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        _load_trusted_execution_behavior_release(
            requested["execution_behavior_release_id"]
        )
