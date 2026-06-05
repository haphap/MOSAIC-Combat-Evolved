from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_production_monitor_diagnostics,
    write_production_monitor_diagnostics,
)
from mosaic.rke.cli import main


def test_production_monitor_diagnostics_cover_decay_drift_and_rollback():
    report = build_production_monitor_diagnostics()

    assert report.accepted
    assert report.scenario_count == 6
    assert report.failure_count == 0
    scenarios = {scenario.scenario_id: scenario for scenario in report.scenarios}
    assert scenarios["healthy_production"].result.state == "production"
    assert scenarios["insufficient_live_events"].result.state == "insufficient_data"
    assert "alpha effect decayed" in " ".join(scenarios["alpha_decay"].result.reasons)
    assert "confidence calibration drift" in " ".join(
        scenarios["calibration_drift"].result.reasons
    )
    assert "turnover increased" in " ".join(scenarios["turnover_spike"].result.reasons)
    assert scenarios["negative_alpha_with_calibration_drift"].result.action == "rollback"


def test_write_production_monitor_diagnostics_outputs_registry_artifact(tmp_path: Path):
    result = write_production_monitor_diagnostics(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted"] is True
    assert payload["scenario_count"] == 6
    assert payload["failure_count"] == 0


def test_cli_monitoring_diagnostics_writes_report(tmp_path: Path, capsys):
    code = main(("monitoring-diagnostics", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["scenario_count"] == 6
    assert (tmp_path / "registry/monitoring/central_bank_monitoring_diagnostics.json").exists()
