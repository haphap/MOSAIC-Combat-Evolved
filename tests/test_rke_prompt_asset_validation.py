from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mosaic.rke import (
    build_prompt_asset_validation_report,
    write_prompt_asset_validation_report,
)


def _copy_registry(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(src_root / "registry", dst_root / "registry")


def test_prompt_asset_validation_accepts_repo_artifacts():
    report = build_prompt_asset_validation_report(".")

    assert report.accepted
    assert report.failure_count == 0
    assert {record.check_id for record in report.records} == {
        "PROMPT-ASSET-FILES",
        "PROMPT-METADATA-REFS",
        "PROMPT-MARKDOWN-CONTRACT",
        "PROMPT-RUNTIME-EVIDENCE",
        "PROMPT-MUTATION-GATE",
        "PROMPT-LEAK-GUARD",
    }


def test_prompt_asset_validation_rejects_forbidden_mutation_target(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)
    mutation_path = (
        tmp_path / "registry/mutation_patches/central_bank_parameter_update.json"
    )
    mutation_patch = json.loads(mutation_path.read_text(encoding="utf-8"))
    mutation_patch["mutation"]["target_path"] = "/output_schema_ref"
    mutation_path.write_text(
        json.dumps(mutation_patch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_prompt_asset_validation_report(tmp_path)
    mutation_record = next(
        record for record in report.records if record.check_id == "PROMPT-MUTATION-GATE"
    )

    assert not report.accepted
    assert not mutation_record.accepted
    assert any("forbidden" in failure for failure in mutation_record.failures)


@pytest.mark.parametrize(
    ("mutator", "expected_failure"),
    (
        (
            lambda patch: patch["mutation"].update({"old_value": 999}),
            "old_value: does not match current rule-pack parameter",
        ),
        (
            lambda patch: patch["mutation"].update({"new_value": "10"}),
            "new_value: integer parameter requires int",
        ),
        (
            lambda patch: patch["mutation"].update(
                {"source_experiment_id": "EXP-UNKNOWN"}
            ),
            "source_experiment_id: must match validation experiment",
        ),
        (
            lambda patch: patch["mutation"].pop("rollback_condition", None),
            "rollback_condition: required object",
        ),
    ),
)
def test_prompt_asset_validation_replays_patch_checker_requirements(
    tmp_path: Path,
    mutator,
    expected_failure: str,
):
    _copy_registry(Path("."), tmp_path)
    mutation_path = (
        tmp_path / "registry/mutation_patches/central_bank_parameter_update.json"
    )
    mutation_patch = json.loads(mutation_path.read_text(encoding="utf-8"))
    mutator(mutation_patch)
    mutation_path.write_text(
        json.dumps(mutation_patch, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_prompt_asset_validation_report(tmp_path)
    mutation_record = next(
        record for record in report.records if record.check_id == "PROMPT-MUTATION-GATE"
    )

    assert not report.accepted
    assert not mutation_record.accepted
    assert expected_failure in mutation_record.failures


def test_prompt_asset_validation_writer_outputs_report(tmp_path: Path):
    _copy_registry(Path("."), tmp_path)

    result = write_prompt_asset_validation_report(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert payload["accepted"] is True
    assert payload["failure_count"] == 0
    assert len(payload["records"]) == 6
