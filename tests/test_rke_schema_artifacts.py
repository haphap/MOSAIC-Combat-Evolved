from __future__ import annotations

import json
from pathlib import Path


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
