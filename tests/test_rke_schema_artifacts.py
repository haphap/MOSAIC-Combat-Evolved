from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    build_schema_validation_report,
    validate_json_schema_artifact,
)
from mosaic.rke.cli import main


REQUIRED_SCHEMA_FILES = {
    "source_metadata.schema.json",
    "source_grounded_claim.schema.json",
    "hypothesis.schema.json",
    "data_availability_matrix.schema.json",
    "rule_pack.schema.yaml",
    "parameter_prior.schema.json",
    "validation_experiment_v2.schema.json",
    "production_patch.schema.json",
    "confidence_policy.schema.yaml",
    "rule_aggregation_policy.schema.yaml",
}

REQUIRED_POLICY_DOCS = {
    "master_plan_v1_1.md",
    "validation_policy.md",
    "claim_extraction_guidelines.md",
    "confidence_policy.md",
    "compliance_policy.md",
}


def test_phase1_schema_artifacts_exist():
    schema_dir = Path("schemas")

    assert {path.name for path in schema_dir.iterdir()} >= REQUIRED_SCHEMA_FILES


def test_master_plan_policy_docs_exist():
    docs_dir = Path("docs")

    assert {path.name for path in docs_dir.iterdir()} >= REQUIRED_POLICY_DOCS


def test_json_schema_artifacts_are_parseable_and_have_required_fields():
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["type"] == "object"
        assert schema.get("required"), f"{path} must declare required fields"


def test_yaml_policy_schema_artifacts_pin_master_plan_defaults():
    confidence = Path("schemas/confidence_policy.schema.yaml").read_text(encoding="utf-8")
    aggregation = Path("schemas/rule_aggregation_policy.schema.yaml").read_text(encoding="utf-8")
    rule_pack = Path("schemas/rule_pack.schema.yaml").read_text(encoding="utf-8")

    assert "safe_default_function" in confidence
    assert "final_confidence_max: 0.50" in confidence
    assert "single_rule_max_adjustment: 0.05" in aggregation
    assert "conflict_object_required" in aggregation
    assert "<layer>.<agent>.<rule_type>.<serial>" in rule_pack


def test_schema_validation_report_accepts_current_registry():
    report = build_schema_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert len(report.records) >= 15
    assert {
        "schemas/source_metadata.schema.json",
        "schemas/source_grounded_claim.schema.json",
        "schemas/validation_experiment_v2.schema.json",
        "schemas/rule_pack.schema.yaml",
        "schemas/confidence_policy.schema.yaml",
    } <= {record.schema_path for record in report.records}


def test_schema_validation_rejects_missing_required_field(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    artifact_dir = tmp_path / "registry/sources"
    schema_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (schema_dir / "source_metadata.schema.json").write_text(
        Path("schemas/source_metadata.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (artifact_dir / "central_bank_sources.jsonl").write_text(
        json.dumps(
            {
                "source_id": "SRC-X",
                "source_type": "official",
                "publish_date": "2026-06-06",
                "ingest_time": "2026-06-06T00:00:00+00:00",
                "license_status": "approved",
                "point_in_time_available": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    record = validate_json_schema_artifact(
        root=tmp_path,
        schema_path="schemas/source_metadata.schema.json",
        artifact_path="registry/sources/central_bank_sources.jsonl",
        artifact_kind="jsonl",
    )

    assert not record.accepted
    assert any("source_hash" in failure for failure in record.failures)


def test_schema_status_cli_writes_report(capsys):
    code = main(("schema-status", "--root", "."))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert Path("registry/schemas/rke_schema_validation_report.json").exists()
