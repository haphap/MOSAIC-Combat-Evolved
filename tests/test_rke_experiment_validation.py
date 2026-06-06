from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_experiment_validation_report,
    write_experiment_validation_report,
)
from mosaic.rke.experiment_validation import (
    COST_MODEL_PATH,
    EXPERIMENT_PATH,
    EXPERIMENT_VALIDATION_REPORT_PATH,
    HARDENING_PATH,
    LOCKBOX_POLICY_PATH,
    OVERLAP_PATH,
    PREREGISTRATION_PATH,
    STATISTICAL_SIGNIFICANCE_PATH,
    FAMILY_PATH,
)


RELEVANT_REGISTRY_PATHS = (
    EXPERIMENT_PATH,
    PREREGISTRATION_PATH,
    FAMILY_PATH,
    OVERLAP_PATH,
    COST_MODEL_PATH,
    LOCKBOX_POLICY_PATH,
    HARDENING_PATH,
    STATISTICAL_SIGNIFICANCE_PATH,
)


def _copy_relevant_registry(src_root: Path, dst_root: Path) -> None:
    for relative in RELEVANT_REGISTRY_PATHS:
        source = src_root / relative
        target = dst_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _record(report, check_id: str):
    return next(record for record in report.records if record.check_id == check_id)


def test_experiment_validation_accepts_repo_artifacts():
    report = build_experiment_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert {record.check_id for record in report.records} == {
        "EXPERIMENT-REGISTRATION-CONTRACT",
        "EXPERIMENT-GOVERNANCE-POLICIES",
        "EXPERIMENT-VALIDATION-RESULTS",
        "EXPERIMENT-REGIME-BUCKET-RULES",
    }
    regime = _record(report, "EXPERIMENT-REGIME-BUCKET-RULES")
    assert regime.details["diagnostic_failure_count"] == 1
    assert regime.details["insufficient_bucket_count"] == 1


def test_experiment_validation_rejects_unfrozen_preregistration(tmp_path: Path):
    _copy_relevant_registry(Path("."), tmp_path)
    prereg_path = tmp_path / PREREGISTRATION_PATH
    prereg = _read_json(prereg_path)
    prereg["protocol_status"] = "draft"
    prereg["validation_results_seen_before_freeze"] = True
    _write_json(prereg_path, prereg)

    report = build_experiment_validation_report(tmp_path)
    registration = _record(report, "EXPERIMENT-REGISTRATION-CONTRACT")

    assert not report.accepted
    assert not registration.accepted
    assert any(
        "protocol_status must be frozen" in item for item in registration.failures
    )
    assert any(
        "must not see validation results" in item for item in registration.failures
    )


def test_experiment_validation_rejects_effective_n_below_minimum(tmp_path: Path):
    _copy_relevant_registry(Path("."), tmp_path)
    experiment_path = tmp_path / EXPERIMENT_PATH
    experiment = _read_json(experiment_path)
    experiment["sampling_design"]["effective_n"] = 20
    _write_json(experiment_path, experiment)

    overlap_path = tmp_path / OVERLAP_PATH
    overlap = _read_json(overlap_path)
    overlap["effective_n"] = 20
    overlap["gate_status"] = "failed"
    _write_json(overlap_path, overlap)

    report = build_experiment_validation_report(tmp_path)
    governance = _record(report, "EXPERIMENT-GOVERNANCE-POLICIES")

    assert not report.accepted
    assert not governance.accepted
    assert any("effective_n below minimum" in item for item in governance.failures)
    assert any("gate_status must be passed" in item for item in governance.failures)


def test_experiment_validation_rejects_missing_cost_model_contract(tmp_path: Path):
    _copy_relevant_registry(Path("."), tmp_path)
    experiment_path = tmp_path / EXPERIMENT_PATH
    experiment = _read_json(experiment_path)
    experiment["acceptance_rule"]["cost_model_required"] = False
    _write_json(experiment_path, experiment)

    cost_path = tmp_path / COST_MODEL_PATH
    cost = _read_json(cost_path)
    cost["net_alpha_after_cost"] = 0.003
    _write_json(cost_path, cost)

    report = build_experiment_validation_report(tmp_path)
    governance = _record(report, "EXPERIMENT-GOVERNANCE-POLICIES")

    assert not report.accepted
    assert not governance.accepted
    assert any(
        "cost_model_required must be true" in item for item in governance.failures
    )
    assert any(
        "net_alpha_after_cost must exceed" in item for item in governance.failures
    )


def test_experiment_validation_treats_regime_insufficient_data_as_diagnostic():
    report = build_experiment_validation_report(".")
    regime = _record(report, "EXPERIMENT-REGIME-BUCKET-RULES")

    assert regime.accepted
    assert regime.failures == ()
    assert "risk_off" in " ".join(regime.details["diagnostic_failures"])


def test_experiment_validation_writer_outputs_report(tmp_path: Path):
    _copy_relevant_registry(Path("."), tmp_path)

    result = write_experiment_validation_report(tmp_path)
    payload = _read_json(Path(result["path"]))

    assert result["path"].endswith(EXPERIMENT_VALIDATION_REPORT_PATH)
    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert len(payload["records"]) == 4
