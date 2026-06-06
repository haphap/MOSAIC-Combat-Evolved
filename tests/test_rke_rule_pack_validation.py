from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import (
    build_rule_pack_validation_report,
    write_rule_pack_validation_report,
)


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def _central_bank_rule_pack_path(root: Path) -> Path:
    return root / "registry/rule_packs/macro.central_bank.liquidity.v1.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_rule_pack_validation_accepts_repo_artifacts():
    report = build_rule_pack_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert {record.check_id for record in report.records} == {
        "RULE-PACK-CONTRACT",
        "RULE-PACK-DATA-MATRIX",
        "RULE-PACK-HORIZON-PARAMETERS",
        "RULE-PACK-PROMOTION-GATES",
    }
    data_matrix = next(
        record
        for record in report.records
        if record.check_id == "RULE-PACK-DATA-MATRIX"
    )
    assert data_matrix.details["checked_proxy_count"] == 5
    assert data_matrix.details["sandbox_only_proxy_count"] == 1


def test_rule_pack_validation_rejects_unknown_metric_proxy(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    path = _central_bank_rule_pack_path(tmp_path)
    payload = _read_json(path)
    payload["rules"]["macro.central_bank.soft.001"]["metric_proxies"].append(
        "missing_proxy"
    )
    _write_json(path, payload)

    report = build_rule_pack_validation_report(tmp_path)
    data_matrix = next(
        record
        for record in report.records
        if record.check_id == "RULE-PACK-DATA-MATRIX"
    )

    assert not report.accepted
    assert not data_matrix.accepted
    assert any("metric proxy not found" in failure for failure in data_matrix.failures)


def test_rule_pack_validation_rejects_invalid_horizon_and_parameter(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    path = _central_bank_rule_pack_path(tmp_path)
    payload = _read_json(path)
    rule = payload["rules"]["macro.central_bank.soft.001"]
    rule["horizon_days"] = [60, 20]
    rule["learnable_parameters"]["net_injection_window_days"]["value"] = 100
    _write_json(path, payload)

    report = build_rule_pack_validation_report(tmp_path)
    horizon = next(
        record
        for record in report.records
        if record.check_id == "RULE-PACK-HORIZON-PARAMETERS"
    )

    assert not report.accepted
    assert not horizon.accepted
    assert any("horizon max must be >= min" in failure for failure in horizon.failures)
    assert any("value above max" in failure for failure in horizon.failures)


def test_rule_pack_validation_rejects_production_without_lockbox_review(
    tmp_path: Path,
):
    _copy_registry(Path("."), tmp_path)
    path = _central_bank_rule_pack_path(tmp_path)
    payload = _read_json(path)
    payload["status"] = "production"
    rule = payload["rules"]["macro.central_bank.soft.001"]
    rule["status"] = "production"
    rule["validation_status"] = "pending"
    _write_json(path, payload)

    report = build_rule_pack_validation_report(tmp_path)
    promotion = next(
        record
        for record in report.records
        if record.check_id == "RULE-PACK-PROMOTION-GATES"
    )

    assert not report.accepted
    assert not promotion.accepted
    assert any("lockbox-reviewed" in failure for failure in promotion.failures)


def test_rule_pack_validation_writer_outputs_report(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)

    result = write_rule_pack_validation_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert len(payload["records"]) == 4
