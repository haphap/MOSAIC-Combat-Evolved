from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke import TushareResearchReportRefreshResult
from mosaic.rke.cli import main


def _copy_registry(dst_root: Path) -> None:
    shutil.copytree(Path("registry"), dst_root / "registry")


def test_rke_cli_validate_required_success(capsys):
    code = main(("validate-required", "--root", "."))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["valid"] is True
    assert output["missing_required"] == []


def test_rke_cli_validate_required_failure(tmp_path: Path, capsys):
    code = main(("validate-required", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["valid"] is False
    assert "registry/audits/rke_completion_audit.json" in output["missing_required"]


def test_rke_cli_manifest_writes_file(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("manifest", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["valid"] is True
    assert Path(output["path"]).exists()


def test_rke_cli_master_plan_status_writes_coverage(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    shutil.copytree(Path("schemas"), tmp_path / "schemas")

    code = main(("master-plan-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["coverage_complete"] is True
    assert output["ready_for_broad_rollout"] is False
    assert output["blocked_count"] == 2
    assert (tmp_path / "registry/audits/rke_master_plan_coverage_report.json").exists()


def test_rke_cli_refresh_preserves_reviews(tmp_path: Path, capsys):
    _copy_registry(tmp_path)
    gold_review = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    original = gold_review.read_text(encoding="utf-8")

    code = main(("refresh", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["manifest_valid"] is True
    assert gold_review.read_text(encoding="utf-8") == original


def test_rke_cli_review_status_commands_write_summaries(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    gold_code = main(("gold-set-status", "--root", str(tmp_path)))
    gold_output = json.loads(capsys.readouterr().out)
    candidate_code = main(("gold-candidate-claims", "--root", str(tmp_path)))
    candidate_output = json.loads(capsys.readouterr().out)
    packet_code = main(("gold-review-packet", "--root", str(tmp_path)))
    packet_output = json.loads(capsys.readouterr().out)
    license_code = main(("license-status", "--root", str(tmp_path)))
    license_output = json.loads(capsys.readouterr().out)
    license_packet_code = main(("license-review-packet", "--root", str(tmp_path)))
    license_packet_output = json.loads(capsys.readouterr().out)

    assert gold_code == 0
    assert gold_output["pending_claims"] == 500
    assert (tmp_path / "registry/gold_sets/tushare_research_reports.review_summary.json").exists()
    assert candidate_code == 0
    assert candidate_output["candidate_claim_count"] == 500
    assert candidate_output["review_rows_with_candidate_fields"] == 500
    assert candidate_output["manual_fields_preserved"] is True
    assert (tmp_path / "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl").exists()
    assert (
        tmp_path / "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
    ).exists()
    assert packet_code == 0
    assert packet_output["pending_review_rows"] == 500
    assert packet_output["candidate_claim_count"] == 500
    assert packet_output["review_rows_with_candidate_fields"] == 500
    assert packet_output["candidate_span_ref_count"] > 0
    assert (tmp_path / "registry/gold_sets/tushare_research_reports.review_packet.json").exists()
    assert (tmp_path / "registry/gold_sets/tushare_research_reports.review_packet.md").exists()
    assert license_code == 0
    assert license_output["pending_sources"] == license_output["total_sources"]
    assert (tmp_path / "registry/compliance/tushare_license_review_summary.json").exists()
    assert license_packet_code == 0
    assert license_packet_output["pending_sources"] == license_output["total_sources"]
    assert license_packet_output["approved_for_production_runtime"] == 0
    assert (tmp_path / "registry/compliance/tushare_license_review_packet.json").exists()
    assert (tmp_path / "registry/compliance/tushare_license_review_packet.md").exists()


def test_rke_cli_prompt_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("prompt-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/prompt_checks/prompt_asset_validation_report.json").exists()


def test_rke_cli_claim_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("claim-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert (tmp_path / "registry/claim_checks/claim_variable_validation_report.json").exists()
    assert (tmp_path / "registry/vocabularies/claim_variable_vocabulary.json").exists()


def test_rke_cli_source_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("source-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted_for_sandbox"] is True
    assert output["accepted_for_production"] is False
    assert (tmp_path / "registry/source_checks/source_registry_validation_report.json").exists()


def test_rke_cli_source_text_status_writes_summary(tmp_path: Path, capsys):
    _copy_registry(tmp_path)

    code = main(("source-text-status", "--root", str(tmp_path)))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["accepted"] is True
    assert output["failure_count"] == 0
    assert output["source_text_count"] == 207
    assert (tmp_path / "registry/compliance/source_text_redaction_report.json").exists()


def test_rke_cli_fetch_tushare_reports_passes_query_args(monkeypatch, tmp_path: Path, capsys):
    captured = {}

    def fake_refresh(root, **kwargs):
        captured["root"] = str(root)
        captured.update(kwargs)
        return TushareResearchReportRefreshResult(
            root=str(root),
            source_rows=3,
            rows_with_abstract=3,
            gold_candidate_rows=3,
            gold_review_template_updated=True,
            license_review_template_updated=True,
            publish_date_min="2026-06-01",
            publish_date_max="2026-06-05",
            report_type_counts={"个股研报": 2, "行业研报": 1},
            query_key_counts={"600519.SH": 1, "300750.SZ": 1, "银行": 1},
            completion_ready_for_broad_rollout=False,
            manifest_valid=True,
            outputs={"source": "registry/sources/tushare_research_reports.jsonl"},
        )

    monkeypatch.setattr("mosaic.rke.cli.refresh_tushare_research_report_registry", fake_refresh)

    code = main(
        (
            "fetch-tushare-reports",
            "--root",
            str(tmp_path),
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-05",
            "--stock-code",
            "600519.SH,300750.SZ",
            "--industry-keyword",
            "银行",
            "--max-reports-per-query",
            "42",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["source_rows"] == 3
    assert captured["root"] == str(tmp_path)
    assert captured["stock_codes"] == ("600519.SH", "300750.SZ")
    assert captured["industry_keywords"] == ("银行",)
    assert captured["start_date"] == "2026-06-01"
    assert captured["end_date"] == "2026-06-05"
    assert captured["max_reports_per_query"] == 42
    assert captured["preserve_review_templates"] is True


def test_pyproject_exposes_mosaic_rke_console_script():
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'mosaic-rke = "mosaic.rke.cli:main"' in text
