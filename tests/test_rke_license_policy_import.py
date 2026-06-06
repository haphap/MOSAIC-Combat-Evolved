from __future__ import annotations

import json
from pathlib import Path

from mosaic.rke import (
    apply_source_license_review_import,
    build_source_license_policy_import,
    build_source_license_policy_template,
    write_source_license_policy_template,
)
from mosaic.rke.cli import main
from mosaic.rke.license_policy_import import (
    MATCHED_ROWS_FINGERPRINT_FIELD,
    SOURCE_LICENSE_REVIEWED_POLICY_PATH,
    _matched_rows_fingerprint,
)


def _copy_registry(dst_root: Path) -> None:
    dst = dst_root / "registry/compliance/tushare_license_review_template.jsonl"
    dst.parent.mkdir(parents=True, exist_ok=True)
    rows = _load_jsonl(Path("registry/compliance/tushare_license_review_template.jsonl"))[:3]
    dst.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _policy(root: Path, **overrides) -> dict:
    payload = dict(build_source_license_policy_template(root))
    payload.update(
        {
            "approved_for_derived_claim_storage": True,
            "approved_for_production_runtime": False,
            "notes": "compliance policy fixture",
            "review_date": "2026-06-06",
            "reviewer": "compliance",
        }
    )
    payload.update(overrides)
    return payload


def _legacy_policy(**overrides) -> dict:
    payload = {
        "approved_for_derived_claim_storage": True,
        "approved_for_production_runtime": False,
        "filters": {
            "current_license_status": ["pending_review"],
            "source_type": ["tushare_research_report"],
        },
        "notes": "compliance policy fixture",
        "review_date": "2026-06-06",
        "reviewer": "compliance",
    }
    payload.update(overrides)
    return payload


def test_build_source_license_policy_import_expands_signed_policy(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy(tmp_path))

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)
    rows = _load_jsonl(output_path)
    dry_run = apply_source_license_review_import(tmp_path, output_path, dry_run=True)

    assert report.accepted
    assert report.matched_rows == len(rows)
    assert report.output_rows == len(rows)
    assert rows
    assert rows[0]["target_row_hash"].startswith("sha256:")
    assert rows[0]["target_review_path"] == "registry/compliance/tushare_license_review_template.jsonl"
    assert rows[0]["reviewer"] == "compliance"
    assert rows[0]["approved_for_derived_claim_storage"] is True
    assert rows[0]["approved_for_production_runtime"] is False
    assert dry_run.accepted
    assert dry_run.applied_rows == 0


def test_source_license_policy_template_requires_reviewer_decision():
    template = build_source_license_policy_template(".")

    assert template["approved_for_derived_claim_storage"] is None
    assert template["approved_for_production_runtime"] is None
    assert template["reviewer"] == ""
    assert template["review_date"] == ""
    assert template["matched_row_count"] == 9812
    assert template["matched_rows_fingerprint"].startswith("sha256:")
    assert template["filters"]["source_type"] == ["tushare_research_report"]
    assert template["filters"]["current_license_status"] == ["pending_review"]
    assert "build-license-review-import" in template["build_command"]
    assert SOURCE_LICENSE_REVIEWED_POLICY_PATH in template["build_command"]
    assert "source_license_policy_template.json" not in template["build_command"]


def test_write_source_license_policy_template_outputs_registry_artifact(tmp_path: Path):
    _copy_registry(tmp_path)

    result = write_source_license_policy_template(tmp_path)
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert result["rows"] == 1
    assert payload["approved_for_production_runtime"] is None
    assert payload["matched_row_count"] == 3
    assert payload["matched_rows_fingerprint"].startswith("sha256:")
    assert (tmp_path / "registry/review_batches/source_license_policy_template.json").exists()


def test_source_license_policy_template_ignores_malformed_review_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    template = build_source_license_policy_template(tmp_path)

    assert template["matched_row_count"] == 3
    assert template["matched_rows_fingerprint"].startswith("sha256:")


def test_source_license_policy_template_ignores_malformed_json_review_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    review_path.write_text(review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")

    template = build_source_license_policy_template(tmp_path)

    assert template["matched_row_count"] == 3
    assert template["matched_rows_fingerprint"].startswith("sha256:")


def test_build_source_license_policy_import_rejects_malformed_review_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    expected_row = len(review_path.read_text(encoding="utf-8").splitlines()) + 1
    review_path.write_text(
        review_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert report.total_review_rows == expected_row
    assert f"source license review row must be object at row(s): {expected_row}" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_malformed_json_review_rows(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    expected_row = len(review_path.read_text(encoding="utf-8").splitlines()) + 1
    review_path.write_text(review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert report.total_review_rows == expected_row
    assert any(
        f"source license review row {expected_row} must contain valid JSON" in blocker
        for blocker in report.blockers
    )
    assert not output_path.exists()


def test_build_source_license_policy_import_reports_review_rows_when_policy_invalid(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    expected_row = len(review_path.read_text(encoding="utf-8").splitlines()) + 1
    review_path.write_text(review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    policy_path.write_text("{", encoding="utf-8")

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert report.total_review_rows == expected_row
    assert any("source-license policy must contain valid JSON" in blocker for blocker in report.blockers)
    assert any(
        f"source license review row {expected_row} must contain valid JSON" in blocker
        for blocker in report.blockers
    )
    assert not output_path.exists()


def test_build_source_license_policy_import_dry_run_does_not_write_output(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy(tmp_path))

    report = build_source_license_policy_import(
        tmp_path,
        policy_path,
        output_path=output_path,
        dry_run=True,
    )

    assert report.accepted
    assert report.output_rows == 0
    assert not output_path.exists()
    assert (tmp_path / "registry/review_batches/source_license_policy_import_report.json").exists()


def test_build_source_license_policy_import_rejects_unscoped_policy(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy(tmp_path, filters={}))

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "at least one policy filter is required" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_stale_policy_fingerprint(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    rows = _load_jsonl(review_path)
    rows[0]["title"] = "changed after policy template export"
    review_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "matched_rows_fingerprint does not match current matched rows" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_legacy_policy_without_fingerprint(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _legacy_policy())

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "matched_rows_fingerprint does not match current matched rows" in report.blockers
    assert "matched_row_count must be integer" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_forbidden_source_text_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["source_text"] = "long source text must stay out of source-license policy imports"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "source_text forbidden in source-license policy import" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_nested_forbidden_source_text_fields(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["review_context"] = {
        "full_text": "nested source text must stay out of source-license policy imports"
    }
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "review_context.full_text forbidden in source-license policy import" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_unexpected_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["extra_context"] = "reviewer accidentally pasted non-template context"
    policy["filters"]["extra_filter"] = "not supported"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "extra_context unexpected in source-license policy import" in report.blockers
    assert "filters.extra_filter unexpected in source-license policy import" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_non_object_filters(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["filters"] = ["not", "an", "object"]
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "filters must be object" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_non_object_policy(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert report.matched_rows == 0
    assert report.output_rows == 0
    assert report.blockers == ("source-license policy must be object",)
    assert not output_path.exists()
    assert (tmp_path / "registry/review_batches/source_license_policy_import_report.json").exists()


def test_build_source_license_policy_import_rejects_invalid_json_policy(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy_path.write_text("{", encoding="utf-8")

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert report.matched_rows == 0
    assert report.output_rows == 0
    assert len(report.blockers) == 1
    assert "source-license policy must contain valid JSON" in report.blockers[0]
    assert not output_path.exists()
    assert (tmp_path / "registry/review_batches/source_license_policy_import_report.json").exists()


def test_build_source_license_policy_import_rejects_non_string_filter_values(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["filters"]["source_type"] = ["tushare_research_report", 123]
    policy["filters"]["source_id_prefix"] = {"prefix": "SRC"}
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "filters.source_type[1] must be string" in report.blockers
    assert "filters.source_id_prefix must be string or list of strings" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_non_string_review_fields(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["reviewer"] = {"name": "not a string"}
    policy["notes"] = ["not", "a", "string"]
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "reviewer must be string" in report.blockers
    assert "notes must be string" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_invalid_review_date_format(tmp_path: Path):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["review_date"] = "2026/06/06"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "review_date must be YYYY-MM-DD" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_accepts_valid_publish_date_filters(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["filters"]["publish_date_min"] = policy["publish_date_min"]
    policy["filters"]["publish_date_max"] = policy["publish_date_max"]
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert report.accepted
    assert report.filters.publish_date_min == policy["publish_date_min"]
    assert report.filters.publish_date_max == policy["publish_date_max"]
    assert output_path.exists()


def test_build_source_license_policy_import_accepts_scoped_publish_date_metadata(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    review_rows = _load_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl")
    matched = [review_rows[0]]
    publish_date = matched[0]["publish_date"]
    policy = _policy(tmp_path)
    policy["filters"] = {"source_id_prefix": [matched[0]["source_id"]]}
    policy["matched_row_count"] = len(matched)
    policy[MATCHED_ROWS_FINGERPRINT_FIELD] = _matched_rows_fingerprint(matched)
    policy["publish_date_min"] = publish_date
    policy["publish_date_max"] = publish_date
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)
    rows = _load_jsonl(output_path)

    assert report.accepted
    assert report.matched_rows == 1
    assert rows[0]["source_id"] == matched[0]["source_id"]


def test_build_source_license_policy_import_rejects_stale_publish_date_metadata(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    review_rows = _load_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl")
    matched = [review_rows[0]]
    policy = _policy(tmp_path)
    policy["filters"] = {"source_id_prefix": [matched[0]["source_id"]]}
    policy["matched_row_count"] = len(matched)
    policy[MATCHED_ROWS_FINGERPRINT_FIELD] = _matched_rows_fingerprint(matched)
    policy["publish_date_min"] = "2026-01-01"
    policy["publish_date_max"] = "2026-01-01"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "publish_date_min does not match current matched rows" in report.blockers
    assert "publish_date_max does not match current matched rows" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_bool_matched_row_count(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    review_rows = _load_jsonl(tmp_path / "registry/compliance/tushare_license_review_template.jsonl")
    matched = [review_rows[0]]
    publish_date = matched[0]["publish_date"]
    policy = _policy(tmp_path)
    policy["filters"] = {"source_id_prefix": [matched[0]["source_id"]]}
    policy["matched_row_count"] = True
    policy[MATCHED_ROWS_FINGERPRINT_FIELD] = _matched_rows_fingerprint(matched)
    policy["publish_date_min"] = publish_date
    policy["publish_date_max"] = publish_date
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "matched_row_count must be integer" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_invalid_filter_date_format(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["filters"]["publish_date_min"] = "2026/06/01"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "filters.publish_date_min must be YYYY-MM-DD" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_non_string_filter_date(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["filters"]["publish_date_max"] = ["2026-06-06"]
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "filters.publish_date_max must be string" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_reversed_filter_date_range(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["filters"]["publish_date_min"] = "2026-06-06"
    policy["filters"]["publish_date_max"] = "2026-02-05"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "filters.publish_date_min must be <= filters.publish_date_max" in report.blockers
    assert not output_path.exists()


def test_build_source_license_policy_import_rejects_invalid_policy_date_metadata(
    tmp_path: Path,
):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy = _policy(tmp_path)
    policy["publish_date_min"] = "2026/02/05"
    _write_json(policy_path, policy)

    report = build_source_license_policy_import(tmp_path, policy_path, output_path=output_path)

    assert not report.accepted
    assert "publish_date_min must be YYYY-MM-DD" in report.blockers
    assert not output_path.exists()


def test_cli_build_license_review_import(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    _write_json(policy_path, _policy(tmp_path))

    code = main(
        (
            "build-license-review-import",
            "--root",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--output",
            str(output_path),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["matched_rows"] == len(_load_jsonl(output_path))


def test_cli_build_license_review_import_rejects_non_object_policy(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy_path.write_text(json.dumps("not an object"), encoding="utf-8")

    code = main(
        (
            "build-license-review-import",
            "--root",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--output",
            str(output_path),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert output["blockers"] == ["source-license policy must be object"]
    assert not output_path.exists()


def test_cli_build_license_review_import_rejects_invalid_json_policy(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    policy_path = tmp_path / "policy.json"
    output_path = tmp_path / "policy_import.jsonl"
    policy_path.write_text("{", encoding="utf-8")

    code = main(
        (
            "build-license-review-import",
            "--root",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "--output",
            str(output_path),
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["accepted"] is False
    assert len(output["blockers"]) == 1
    assert "source-license policy must contain valid JSON" in output["blockers"][0]
    assert not output_path.exists()
