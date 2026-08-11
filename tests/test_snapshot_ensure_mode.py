from __future__ import annotations

from pathlib import Path

import pytest

import mosaic.dataflows.agent_stage_preparer as stage_preparer
import mosaic.dataflows.fred as fred
from mosaic.dataflows.a_share_archive import a_share_archive_path
from mosaic.dataflows.agent_materialization import agent_data_materialization_db_path
from mosaic.dataflows.bound_runtime_snapshots import runtime_snapshot_root
from mosaic.dataflows.china_agent_data_archive import china_agent_archive_path
from mosaic.dataflows.economic_calendar import economic_calendar_cache_path
from mosaic.dataflows.europe_macro_archive import (
    europe_macro_archive_path,
    europe_macro_snapshot_root,
)
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.geopolitical_events import geopolitical_store_path
from mosaic.dataflows.macro_snapshots import snapshot_cache_root
from mosaic.dataflows.market_breadth import market_breadth_data_root
from mosaic.dataflows.outcome_runtime_inputs import outcome_runtime_cache_root
from mosaic.dataflows.runtime_paths import (
    agent_cache_root,
    agent_runtime_root_override,
)
from mosaic.dataflows.sector_archive import sector_archive_path
from mosaic.dataflows.sector_snapshots import sector_snapshot_root
from mosaic.dataflows.us_macro_archive import (
    us_macro_archive_path,
    us_macro_snapshot_root,
)


def _request() -> dict[str, str]:
    return {
        "agent_id": "china",
        "stage": "china",
        "as_of": "2026-07-09",
    }


@pytest.mark.parametrize("configured", [None, "", "observe", "ENFORCE"])
def test_production_ensure_mode_must_be_explicit_and_valid(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
) -> None:
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    if configured is None:
        monkeypatch.delenv("MOSAIC_ENSURE_SNAPSHOT_MODE", raising=False)
    else:
        monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", configured)

    with pytest.raises(
        DataVendorUnavailable,
        match="MOSAIC_ENSURE_SNAPSHOT_MODE must be one of off, shadow, enforce",
    ):
        stage_preparer.ensure_agent_stage_materialization(_request())


def test_structured_smoke_bypass_does_not_require_production_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_ENSURE_SNAPSHOT_MODE", raising=False)
    monkeypatch.setenv(
        "MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", "structured_smoke"
    )

    assert stage_preparer.ensure_agent_stage_materialization(_request()) == {
        "status": "SYNTHETIC_NON_PRODUCTION_BYPASS"
    }


def test_off_skips_trusted_ensure_core(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "off")
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)

    def unexpected(_request: object) -> dict[str, str]:
        raise AssertionError("off mode must not invoke the ensure core")

    monkeypatch.setattr(
        stage_preparer, "_ensure_agent_stage_materialization_core", unexpected
    )
    assert stage_preparer.ensure_agent_stage_materialization(_request()) == {
        "ensure_mode": "off",
        "status": "OFF",
    }


def test_enforce_runs_core_in_production_namespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    production_root = tmp_path / "production-cache"
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
    monkeypatch.setenv("MOSAIC_CACHE_DIR", str(production_root))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    observed: list[tuple[Path, object]] = []
    request = {"agent_id": "energy", "stage": "energy", "as_of": "2026-07-09"}

    def core(core_request: object) -> dict[str, str]:
        observed.append((agent_cache_root(), core_request))
        return {"status": "READY"}

    monkeypatch.setattr(stage_preparer, "_ensure_agent_stage_materialization_core", core)
    deferred = stage_preparer.trusted_deferred_request_only_request(
        request, tool_ids=("get_indicators",)
    )
    assert stage_preparer.ensure_agent_stage_materialization(deferred) == {
        "ensure_mode": "enforce",
        "status": "READY",
    }
    assert observed == [(production_root, request)]


def test_curve_stage_enforce_requires_license_receipt_but_shadow_does_not(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = {
        "agent_id": "central_bank",
        "stage": "central_bank",
        "as_of": "2026-07-09",
    }
    calls: list[str] = []
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    monkeypatch.setenv(
        "MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT", str(tmp_path / "shadow")
    )
    monkeypatch.setattr(
        stage_preparer,
        "_ensure_agent_stage_materialization_core",
        lambda _request: calls.append("core") or {"status": "READY"},
    )
    monkeypatch.setattr(
        stage_preparer,
        "production_license_receipt_ref",
        lambda **_kwargs: None,
    )

    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
    with pytest.raises(DataVendorUnavailable) as exc_info:
        stage_preparer.ensure_agent_stage_materialization(request)
    assert exc_info.value.reason_code == "LICENSE_REVIEW_REQUIRED"
    assert calls == []

    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "shadow")
    assert stage_preparer.ensure_agent_stage_materialization(request)["status"] == (
        "SHADOW_READY"
    )
    assert calls == ["core"]

    monkeypatch.setattr(
        stage_preparer,
        "production_license_receipt_ref",
        lambda **_kwargs: "sha256:" + "a" * 64,
    )
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
    assert stage_preparer.ensure_agent_stage_materialization(request)["status"] == (
        "READY"
    )
    assert calls == ["core", "core"]


def test_shadow_ignores_production_paths_and_restores_them(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    production_root = tmp_path / "production-cache"
    production_ledger = tmp_path / "production-ledger.sqlite3"
    production_china = tmp_path / "production-china.sqlite3"
    shadow_root = tmp_path / "shadow"
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "shadow")
    monkeypatch.setenv("MOSAIC_CACHE_DIR", str(production_root))
    monkeypatch.setenv("MOSAIC_AGENT_MATERIALIZATION_DB", str(production_ledger))
    monkeypatch.setenv("MOSAIC_CHINA_AGENT_ARCHIVE_DB", str(production_china))
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT", str(shadow_root))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    observed: list[tuple[Path, Path, Path]] = []

    def core(_request: object) -> dict[str, str]:
        observed.append(
            (
                agent_cache_root(),
                agent_data_materialization_db_path(),
                china_agent_archive_path(),
            )
        )
        return {"status": "READY"}

    monkeypatch.setattr(stage_preparer, "_ensure_agent_stage_materialization_core", core)
    assert stage_preparer.ensure_agent_stage_materialization(_request()) == {
        "ensure_mode": "shadow",
        "shadow_status": "READY",
        "status": "SHADOW_READY",
    }
    assert observed == [
        (
            shadow_root,
            shadow_root / "agent_materialization" / "materialization.sqlite3",
            shadow_root / "agent_data" / "china_agent_data.sqlite3",
        )
    ]
    assert agent_cache_root() == production_root
    assert agent_data_materialization_db_path() == production_ledger
    assert china_agent_archive_path() == production_china


def test_enforce_shadow_off_restore_drill_keeps_namespaces_separate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    production_root = tmp_path / "production-cache"
    shadow_root = tmp_path / "shadow-cache"
    monkeypatch.setenv("MOSAIC_CACHE_DIR", str(production_root))
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT", str(shadow_root))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)
    observed_roots: list[Path] = []

    def core(_request: object) -> dict[str, str]:
        root = agent_cache_root()
        observed_roots.append(root)
        root.mkdir(parents=True, exist_ok=True)
        marker = root / "rollout-mode-marker"
        marker.write_text(str(len(observed_roots)), encoding="utf-8")
        return {"status": "READY"}

    monkeypatch.setattr(stage_preparer, "_ensure_agent_stage_materialization_core", core)

    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
    assert stage_preparer.ensure_agent_stage_materialization(_request())["ensure_mode"] == "enforce"
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "shadow")
    assert stage_preparer.ensure_agent_stage_materialization(_request())["status"] == "SHADOW_READY"
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "off")
    assert stage_preparer.ensure_agent_stage_materialization(_request())["status"] == "OFF"
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "enforce")
    assert stage_preparer.ensure_agent_stage_materialization(_request())["ensure_mode"] == "enforce"

    assert observed_roots == [production_root, shadow_root, production_root]
    assert (production_root / "rollout-mode-marker").read_text(encoding="utf-8") == "3"
    assert (shadow_root / "rollout-mode-marker").read_text(encoding="utf-8") == "2"
    assert agent_cache_root() == production_root


def test_shadow_source_blocker_is_observable_but_nonblocking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_MODE", "shadow")
    monkeypatch.setenv("MOSAIC_ENSURE_SNAPSHOT_SHADOW_ROOT", str(tmp_path / "shadow"))
    monkeypatch.delenv("MOSAIC_NON_PRODUCTION_SOURCE_GAP_BYPASS", raising=False)

    def blocked(_request: object) -> dict[str, str]:
        raise DataVendorUnavailable("private upstream detail")

    monkeypatch.setattr(
        stage_preparer, "_ensure_agent_stage_materialization_core", blocked
    )
    result = stage_preparer.ensure_agent_stage_materialization(_request())
    assert result == {
        "blocker_codes": ["SHADOW_ENSURE_BLOCKED"],
        "ensure_mode": "shadow",
        "status": "SHADOW_BLOCKED",
    }
    assert "private upstream detail" not in repr(result)


def test_shadow_override_covers_every_preparer_runtime_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    production_path = tmp_path / "production"
    for name in (
        "MOSAIC_A_SHARE_ARCHIVE_DB",
        "MOSAIC_AGENT_MATERIALIZATION_DB",
        "MOSAIC_CHINA_AGENT_ARCHIVE_DB",
        "MOSAIC_CHINA_AGENT_SNAPSHOT_DIR",
        "MOSAIC_ECO_CAL_CACHE_PATH",
        "MOSAIC_EUROPE_MACRO_ARCHIVE_DB",
        "MOSAIC_EUROPE_MACRO_SNAPSHOT_DIR",
        "MOSAIC_GEOPOLITICAL_EVENT_DB",
        "MOSAIC_MACRO_SNAPSHOT_DIR",
        "MOSAIC_MARKET_BREADTH_DATA_DIR",
        "MOSAIC_OUTCOME_RUNTIME_DIR",
        "MOSAIC_RUNTIME_SNAPSHOT_DIR",
        "MOSAIC_SECTOR_ARCHIVE_PATH",
        "MOSAIC_SECTOR_SNAPSHOT_DIR",
        "MOSAIC_US_MACRO_ARCHIVE_DB",
        "MOSAIC_US_MACRO_SNAPSHOT_DIR",
    ):
        monkeypatch.setenv(name, str(production_path / name))

    shadow_root = tmp_path / "shadow"
    with agent_runtime_root_override(shadow_root):
        assert {
            "a_share": a_share_archive_path(production_path),
            "agent_materialization": agent_data_materialization_db_path(),
            "bound_runtime": runtime_snapshot_root(),
            "china_archive": china_agent_archive_path(),
            "economic_calendar": economic_calendar_cache_path(),
            "europe_archive": europe_macro_archive_path(),
            "europe_snapshots": europe_macro_snapshot_root(),
            "fred": fred._cache_dir(),
            "geopolitical": geopolitical_store_path(),
            "macro_snapshots": snapshot_cache_root(),
            "market_breadth": market_breadth_data_root(),
            "outcome_runtime": outcome_runtime_cache_root(),
            "sector_archive": sector_archive_path(production_path),
            "sector_snapshots": sector_snapshot_root(),
            "us_archive": us_macro_archive_path(),
            "us_snapshots": us_macro_snapshot_root(),
        } == {
            "a_share": shadow_root
            / "market_breadth"
            / "a_share_archive.sqlite3",
            "agent_materialization": shadow_root
            / "agent_materialization"
            / "materialization.sqlite3",
            "bound_runtime": shadow_root / "runtime_snapshots",
            "china_archive": shadow_root
            / "agent_data"
            / "china_agent_data.sqlite3",
            "economic_calendar": shadow_root
            / "economic_calendar"
            / "eco_cal.sqlite3",
            "europe_archive": shadow_root / "agent_data" / "europe_macro.sqlite3",
            "europe_snapshots": shadow_root
            / "agent_data"
            / "europe_macro_snapshots",
            "fred": shadow_root / "fred",
            "geopolitical": shadow_root
            / "geopolitical_events"
            / "events.sqlite3",
            "macro_snapshots": shadow_root / "macro_snapshots",
            "market_breadth": shadow_root / "market_breadth",
            "outcome_runtime": shadow_root / "outcome_runtime",
            "sector_archive": shadow_root
            / "agent_data"
            / "sector_relationship.sqlite3",
            "sector_snapshots": shadow_root / "sector_snapshots",
            "us_archive": shadow_root / "agent_data" / "us_macro.sqlite3",
            "us_snapshots": shadow_root / "agent_data" / "us_macro_snapshots",
        }
