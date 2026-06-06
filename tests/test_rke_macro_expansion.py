from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_macro_expansion_data_matrix,
    build_macro_expansion_plan,
    central_bank_phase4_readiness_from_registry,
    central_bank_phase4_ready_from_registry,
    write_macro_expansion_registry,
)


def test_macro_expansion_unlocked_by_central_bank_phase4_gate():
    assert central_bank_phase4_ready_from_registry(".")
    ready, blockers = central_bank_phase4_readiness_from_registry(".")

    plan = build_macro_expansion_plan(central_bank_phase4_ready=True)

    assert ready is True
    assert blockers == ()
    assert plan.phase == "Phase 6"
    assert len(plan.candidates) == 3
    assert {candidate.agent_id for candidate in plan.candidates} == {
        "macro.volatility",
        "macro.dollar",
        "macro.yield_curve",
    }
    assert {candidate.status for candidate in plan.candidates} == {"candidate"}
    assert plan.production_allowed is False
    assert all(candidate.production_allowed is False for candidate in plan.candidates)
    assert plan.blockers == ()


def test_macro_expansion_blocks_candidates_without_central_bank_phase4():
    plan = build_macro_expansion_plan(central_bank_phase4_ready=False)

    assert {candidate.status for candidate in plan.candidates} == {"blocked"}


def test_macro_expansion_data_matrix_has_validation_but_not_production_proxies():
    matrix = build_macro_expansion_data_matrix()

    assert set(matrix.proxies) >= {
        "vix_close",
        "realized_volatility_rk_th2",
        "fred_dtwexbgs",
        "usdcny_fixing",
        "cn_us_rate_spread_10y",
        "cn_yield_curve_10y_1y_spread",
    }
    assert matrix.require(("fred_dtwexbgs",), production=False) == ()
    assert any(
        "not allowed for production" in failure
        for failure in matrix.require(("fred_dtwexbgs",), production=True)
    )


def test_macro_expansion_registry_writer(tmp_path: Path):
    # Copy the paper-trading evidence needed by the unlock gate.
    source = Path("registry/monitoring/central_bank_paper_trading_report.json")
    target = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    outputs = write_macro_expansion_registry(tmp_path)
    plan = json.loads(Path(outputs["expansion_plan"]).read_text(encoding="utf-8"))
    matrix = json.loads(Path(outputs["data_availability"]).read_text(encoding="utf-8"))

    assert plan["central_bank_phase4_ready"] is True
    assert plan["blockers"] == []
    assert plan["production_allowed"] is False
    assert len(plan["candidates"]) == 3
    assert matrix["matrix_id"] == "DAM-MACRO-EXPANSION-2026Q2"


def test_macro_expansion_registry_writer_blocks_on_malformed_paper_report(tmp_path: Path):
    target = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{", encoding="utf-8")

    ready, blockers = central_bank_phase4_readiness_from_registry(tmp_path)
    outputs = write_macro_expansion_registry(tmp_path)
    plan = json.loads(Path(outputs["expansion_plan"]).read_text(encoding="utf-8"))

    assert ready is False
    assert len(blockers) == 1
    assert "paper-trading report must contain valid JSON" in blockers[0]
    assert plan["central_bank_phase4_ready"] is False
    assert "paper-trading report must contain valid JSON" in plan["blockers"][0]
    assert {candidate["status"] for candidate in plan["candidates"]} == {"blocked"}


def test_macro_expansion_registry_writer_blocks_on_non_object_paper_report(tmp_path: Path):
    target = tmp_path / "registry/monitoring/central_bank_paper_trading_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    ready, blockers = central_bank_phase4_readiness_from_registry(tmp_path)

    assert ready is False
    assert blockers == ("central_bank paper-trading report must be object",)


def test_macro_expansion_repo_registry_is_candidate_only():
    plan = json.loads(Path("registry/expansion/macro_phase6_expansion.json").read_text(encoding="utf-8"))

    assert plan["central_bank_phase4_ready"] is True
    assert plan.get("blockers", []) == []
    assert plan["production_allowed"] is False
    assert {candidate["status"] for candidate in plan["candidates"]} == {"candidate"}
