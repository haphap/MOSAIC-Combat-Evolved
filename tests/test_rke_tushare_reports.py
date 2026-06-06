from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from mosaic.rke.tushare_reports import (
    fetch_tushare_research_reports,
    load_tushare_research_reports_from_file,
    normalize_research_report_row,
    refresh_tushare_research_report_registry,
    write_research_reports_jsonl,
)


class FakeTusharePro:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def research_report(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("report_type") == "个股研报":
            rows = []
            for ts_code in str(kwargs["ts_code"]).split(","):
                rows.append(
                    {
                        "trade_date": "20260603",
                        "title": f"Liquidity leader update {ts_code}",
                        "abstr": "PBOC liquidity support may improve short-term risk appetite.",
                        "author": "Analyst A",
                        "inst_csname": "Broker A",
                        "ts_code": ts_code,
                        "ind_name": "银行",
                        "url": "https://example.invalid/a",
                    }
                )
            return pd.DataFrame(rows)
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260602",
                    "title": "Banking sector liquidity review",
                    "abstr": "Liquidity injection requires confirmation from rates and flows.",
                    "author": "Analyst B",
                    "inst_csname": "Broker B",
                    "ts_code": "",
                    "ind_name": kwargs["ind_name"],
                    "url": "https://example.invalid/b",
                }
            ]
        )


class LegacySingleRowFakeTusharePro:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def research_report(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("report_type") == "个股研报":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20260603",
                        "title": "Liquidity leader update",
                        "abstr": "PBOC liquidity support may improve short-term risk appetite.",
                        "author": "Analyst A",
                        "inst_csname": "Broker A",
                        "ts_code": kwargs["ts_code"],
                        "ind_name": "银行",
                        "url": "https://example.invalid/a",
                    }
                ]
            )
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260602",
                    "title": "Banking sector liquidity review",
                    "abstr": "Liquidity injection requires confirmation from rates and flows.",
                    "author": "Analyst B",
                    "inst_csname": "Broker B",
                    "ts_code": "",
                    "ind_name": kwargs["ind_name"],
                    "url": "https://example.invalid/b",
                }
            ]
        )


class BatchUnsupportedFakeTusharePro(FakeTusharePro):
    def research_report(self, **kwargs):
        if kwargs.get("report_type") == "个股研报" and "," in str(kwargs.get("ts_code") or ""):
            self.calls.append(kwargs)
            return pd.DataFrame(columns=["trade_date", "title", "abstr", "author", "inst_csname", "ts_code", "ind_name", "url"])
        return super().research_report(**kwargs)


class FullMarketFakeTusharePro:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def research_report(self, **kwargs):
        self.calls.append(kwargs)
        report_type = str(kwargs["report_type"])
        start_date = str(kwargs["start_date"])
        if report_type == "个股研报":
            return pd.DataFrame(
                [
                    {
                        "trade_date": start_date,
                        "title": f"Full-market stock report {start_date}",
                        "abstr": "Stock report text.",
                        "author": "Analyst C",
                        "inst_csname": "Broker C",
                        "ts_code": "000001.SZ",
                        "ind_name": "银行",
                        "url": "https://example.invalid/c",
                    }
                ]
            )
        return pd.DataFrame(
            [
                {
                    "trade_date": start_date,
                    "title": f"Full-market industry report {start_date}",
                    "abstr": "Industry report text.",
                    "author": "Analyst D",
                    "inst_csname": "Broker D",
                    "ts_code": "",
                    "ind_name": "半导体",
                    "url": "https://example.invalid/d",
                }
            ]
        )


class PaginatedFullMarketFakeTusharePro:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def research_report(self, **kwargs):
        self.calls.append(kwargs)
        offset = int(kwargs.get("offset") or 0)
        page_size = int(kwargs.get("limit") or 1000)
        if offset == 0:
            count = page_size
        elif offset == page_size:
            count = 2
        else:
            count = 0
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260601",
                    "title": f"Paged report {offset + index}",
                    "abstr": f"Paged report text {offset + index}.",
                    "author": "Analyst P",
                    "inst_csname": "Broker P",
                    "ts_code": f"{index:06d}.SZ",
                    "ind_name": "银行",
                    "url": f"https://example.invalid/paged/{offset + index}",
                }
                for index in range(count)
            ]
        )


class RaisingTusharePro:
    def research_report(self, **kwargs):
        raise AssertionError(f"Tushare should not be called for local import: {kwargs}")


def _write_local_tushare_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "trade_date,report_type,name,title,abstr,author,inst_csname,ts_code,ind_name,url,fetched_at,query_value",
                "20260603,个股研报,平安银行,Local stock report,Local stock thesis.,Analyst A,Broker A,000001.SZ,银行,https://example.invalid/a,2026-06-06T00:00:00+00:00,all",
                "20260602,行业研报,半导体,Local industry report,Local industry thesis.,Analyst B,Broker B,,半导体,https://example.invalid/b,2026-06-06T00:00:00+00:00,all",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_fetch_tushare_research_reports_uses_stock_and_industry_queries():
    fake = FakeTusharePro()

    reports = fetch_tushare_research_reports(
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )

    assert len(reports) == 2
    assert fake.calls[0]["ts_code"] == "600519.SH"
    assert fake.calls[0]["start_date"] == "20260601"
    assert fake.calls[0]["report_type"] == "个股研报"
    assert fake.calls[1]["ind_name"] == "银行"
    assert fake.calls[1]["report_type"] == "行业研报"
    assert all(report.source_hash.startswith("sha256:") for report in reports)
    assert all(report.point_in_time_available for report in reports)
    assert all(report.license_status == "pending_review" for report in reports)


def test_fetch_tushare_research_reports_batches_stock_codes_in_one_ts_code_query():
    fake = FakeTusharePro()

    reports = fetch_tushare_research_reports(
        stock_codes=("600519.SH", "300750.SZ"),
        start_date="2026-06-01",
        end_date="2026-06-05",
        stock_query_batch_size=2,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )

    assert len(fake.calls) == 1
    assert fake.calls[0]["ts_code"] == "600519.SH,300750.SZ"
    assert {report.query_key for report in reports} == {"600519.SH", "300750.SZ"}


def test_fetch_tushare_research_reports_falls_back_when_stock_batch_returns_empty():
    fake = BatchUnsupportedFakeTusharePro()

    reports = fetch_tushare_research_reports(
        stock_codes=("601100.SH", "920033.BJ"),
        start_date="2026-06-01",
        end_date="2026-06-05",
        stock_query_batch_size=2,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )

    assert [call["ts_code"] for call in fake.calls] == [
        "601100.SH,920033.BJ",
        "601100.SH",
        "920033.BJ",
    ]
    assert {report.query_key for report in reports} == {"601100.SH", "920033.BJ"}


def test_fetch_tushare_research_reports_queries_full_market_by_report_type_windows():
    fake = FullMarketFakeTusharePro()

    reports = fetch_tushare_research_reports(
        report_types=("个股研报", "行业研报"),
        start_date="2026-06-01",
        end_date="2026-06-03",
        date_chunk_days=2,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )

    assert len(fake.calls) == 4
    assert [(call["report_type"], call["start_date"], call["end_date"]) for call in fake.calls] == [
        ("个股研报", "20260601", "20260602"),
        ("个股研报", "20260603", "20260603"),
        ("行业研报", "20260601", "20260602"),
        ("行业研报", "20260603", "20260603"),
    ]
    assert len(reports) == 4
    assert {report.report_type for report in reports} == {"个股研报", "行业研报"}
    assert {report.query_key for report in reports} == {"000001.SZ", "半导体"}


def test_fetch_tushare_research_reports_paginates_full_market_report_type():
    fake = PaginatedFullMarketFakeTusharePro()

    reports = fetch_tushare_research_reports(
        report_types=("个股研报",),
        start_date="2026-06-01",
        end_date="2026-06-01",
        max_reports_per_query=1002,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )

    assert len(reports) == 1002
    assert [call["offset"] for call in fake.calls] == [0, 1000]
    assert {call["limit"] for call in fake.calls} == {1000}


def test_normalize_research_report_row_builds_source_and_span_ids():
    report = normalize_research_report_row(
        {
            "trade_date": "20260603",
            "title": "Policy support",
            "abstr": "Policy support is a prior, not a trading signal.",
            "author": "A",
            "inst_csname": "B",
            "ts_code": "600000.SH",
            "ind_name": "银行",
            "url": "",
        },
        report_type="个股研报",
        query_key="600000.SH",
        discovered_at="2026-06-05T12:00:00+00:00",
    )

    assert report.source_id.startswith("SRC-TSRR-20260603-")
    assert report.source_span_id.endswith(":abstract")
    assert "Policy support" in report.source_span_text
    assert report.publish_date == "2026-06-03"


def test_write_research_reports_jsonl(tmp_path):
    fake = LegacySingleRowFakeTusharePro()
    reports = fetch_tushare_research_reports(
        stock_codes=("600519.SH",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )
    path = tmp_path / "reports.jsonl"

    result = write_research_reports_jsonl(reports, path)

    assert result == {"path": str(path), "rows": 1}
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["source_type"] == "tushare_research_report"
    assert row["source_span_id"].endswith(":abstract")


def test_load_tushare_research_reports_from_local_csv(tmp_path: Path):
    path = tmp_path / "reports.csv"
    _write_local_tushare_csv(path)

    reports = load_tushare_research_reports_from_file(path)

    assert len(reports) == 2
    assert {report.report_type for report in reports} == {"个股研报", "行业研报"}
    assert {report.query_key for report in reports} == {"000001.SZ", "半导体"}
    assert {report.discovered_at for report in reports} == {"2026-06-06T00:00:00+00:00"}
    assert all(report.source_type == "tushare_research_report" for report in reports)


def test_refresh_tushare_research_report_registry_updates_dependent_artifacts(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    fake = FakeTusharePro()

    result = refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        max_reports_per_query=6000,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=fake,
    )

    source_rows = [
        json.loads(line)
        for line in (tmp_path / "registry/sources/tushare_research_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    manifest = json.loads(
        (tmp_path / "registry/sources/tushare_research_reports.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    license_rows = (
        tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    gold_rows = (
        tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    ).read_text(encoding="utf-8").splitlines()

    assert result.source_rows == 2
    assert result.rows_with_abstract == 2
    assert result.skipped_empty_abstract_rows == 0
    assert result.gold_candidate_rows == 2
    assert result.gold_review_template_updated
    assert result.license_review_template_updated
    assert result.manifest_valid
    assert "operator_handoff.json" in result.outputs
    assert "lockbox_review_import_template" in result.outputs
    assert "lockbox_review_import_report" in result.outputs
    assert "gold_set_full_import_template" in result.outputs
    assert "manual_review_gold_set_full_import_template" in result.outputs
    assert "gold_review_import_report" in result.outputs
    assert "source_license_policy_template" in result.outputs
    assert "source_license_policy_import_report" in result.outputs
    assert "manual_review_bundle_manifest" in result.outputs
    assert "manual_review_runbook" in result.outputs
    assert "promotion_dry_run_report" in result.outputs
    assert "rollback_readiness_report" in result.outputs
    assert "operator_readiness_report" in result.outputs
    assert "production_monitor_diagnostics" in result.outputs
    assert len(source_rows) == 2
    assert len(license_rows) == 2
    assert len(gold_rows) == 20
    assert manifest["output_path"] == "registry/sources/tushare_research_reports.jsonl"
    assert manifest["max_reports_per_query"] == 6000
    assert manifest["stock_query_batch_size"] == 50
    assert manifest["date_chunk_days"] == 31
    assert manifest["query_set"]["report_types"] == []
    assert manifest["query_key_counts"] == {"600519.SH": 1, "银行": 1}
    assert manifest["rows_with_abstract"] == 2
    assert manifest["skipped_empty_abstract_rows"] == 0


def test_refresh_tushare_research_report_registry_imports_local_file_without_tushare(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    local_input = tmp_path / "reports.csv"
    _write_local_tushare_csv(local_input)

    result = refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=(),
        industry_keywords=(),
        input_path=local_input,
        max_reports_per_query=6000,
        pro=RaisingTusharePro(),
    )

    source_rows = [
        json.loads(line)
        for line in (tmp_path / "registry/sources/tushare_research_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    manifest = json.loads(
        (tmp_path / "registry/sources/tushare_research_reports.manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.source_rows == 2
    assert result.rows_with_abstract == 2
    assert result.skipped_empty_abstract_rows == 0
    assert result.manifest_valid
    assert len(source_rows) == 2
    assert manifest["source"] == "local_file"
    assert manifest["input_path"] == str(local_input)
    assert manifest["query_window"] == {"start_date": "2026-06-02", "end_date": "2026-06-03"}
    assert manifest["report_type_counts"] == {"个股研报": 1, "行业研报": 1}
    assert manifest["skipped_empty_abstract_rows"] == 0


def test_refresh_tushare_research_report_registry_skips_empty_abstract_rows(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    local_input = tmp_path / "reports.csv"
    local_input.write_text(
        "\n".join(
            [
                "trade_date,report_type,name,title,abstr,author,inst_csname,ts_code,ind_name,url,fetched_at,query_value",
                "20260603,个股研报,平安银行,Local stock report,Local stock thesis.,Analyst A,Broker A,000001.SZ,银行,https://example.invalid/a,2026-06-06T00:00:00+00:00,all",
                "20260602,行业研报,半导体,No abstract report,,Analyst B,Broker B,,半导体,https://example.invalid/b,2026-06-06T00:00:00+00:00,all",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=(),
        industry_keywords=(),
        input_path=local_input,
        max_reports_per_query=6000,
        pro=RaisingTusharePro(),
    )
    manifest = json.loads(
        (tmp_path / "registry/sources/tushare_research_reports.manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.source_rows == 1
    assert result.rows_with_abstract == 1
    assert result.skipped_empty_abstract_rows == 1
    assert manifest["skipped_empty_abstract_rows"] == 1


def test_refresh_tushare_research_report_registry_preserves_existing_discovered_at(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    existing_reports = fetch_tushare_research_reports(
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        discovered_at="2026-06-01T00:00:00+00:00",
        pro=FakeTusharePro(),
    )
    write_research_reports_jsonl(existing_reports, source_path)
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )

    refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        max_reports_per_query=6000,
        pro=FakeTusharePro(),
    )

    source_rows = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines()]

    assert {row["discovered_at"] for row in source_rows} == {"2026-06-01T00:00:00+00:00"}


def test_refresh_ignores_malformed_existing_source_when_preserving_discovered_at(
    tmp_path: Path,
):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    source_path = tmp_path / "registry/sources/tushare_research_reports.jsonl"
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "{\n",
        encoding="utf-8",
    )

    result = refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        max_reports_per_query=6000,
        pro=FakeTusharePro(),
    )

    source_rows = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines()]

    assert result.source_rows == 2
    assert len(source_rows) == 2
    assert {row["query_key"] for row in source_rows} == {"600519.SH", "银行"}


def test_refresh_preserves_malformed_review_templates_for_gate_blockers(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    gold_review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    license_review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    gold_review_path.write_text(
        gold_review_path.read_text(encoding="utf-8") + json.dumps("not an object") + "\n",
        encoding="utf-8",
    )
    license_review_path.write_text(
        license_review_path.read_text(encoding="utf-8") + json.dumps(["not", "an", "object"]) + "\n",
        encoding="utf-8",
    )

    result = refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        max_reports_per_query=6000,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=FakeTusharePro(),
    )
    gold_rows = [json.loads(line) for line in gold_review_path.read_text(encoding="utf-8").splitlines()]
    license_rows = [json.loads(line) for line in license_review_path.read_text(encoding="utf-8").splitlines()]
    gold_summary = json.loads(
        (tmp_path / "registry/gold_sets/tushare_research_reports.review_summary.json").read_text(
            encoding="utf-8"
        )
    )
    license_packet = json.loads(
        (tmp_path / "registry/compliance/tushare_license_review_packet.json").read_text(
            encoding="utf-8"
        )
    )

    assert not result.gold_review_template_updated
    assert not result.license_review_template_updated
    assert gold_rows[-1] == "not an object"
    assert license_rows[-1] == ["not", "an", "object"]
    assert any("gold-set review row must be object" in blocker for blocker in gold_summary["blockers"])
    assert any("source license review row must be object" in blocker for blocker in license_packet["blockers"])


def test_refresh_preserves_malformed_json_review_templates_for_gate_blockers(tmp_path: Path):
    shutil.copytree(Path("registry"), tmp_path / "registry")
    gold_review_path = tmp_path / "registry/gold_sets/tushare_research_reports.review_template.jsonl"
    license_review_path = tmp_path / "registry/compliance/tushare_license_review_template.jsonl"
    gold_expected_row = len(gold_review_path.read_text(encoding="utf-8").splitlines()) + 1
    license_expected_row = len(license_review_path.read_text(encoding="utf-8").splitlines()) + 1
    gold_review_path.write_text(gold_review_path.read_text(encoding="utf-8") + "{\n", encoding="utf-8")
    license_review_path.write_text(
        license_review_path.read_text(encoding="utf-8") + "{\n",
        encoding="utf-8",
    )

    result = refresh_tushare_research_report_registry(
        tmp_path,
        stock_codes=("600519.SH",),
        industry_keywords=("银行",),
        start_date="2026-06-01",
        end_date="2026-06-05",
        max_reports_per_query=6000,
        discovered_at="2026-06-05T12:00:00+00:00",
        pro=FakeTusharePro(),
    )
    gold_summary = json.loads(
        (tmp_path / "registry/gold_sets/tushare_research_reports.review_summary.json").read_text(
            encoding="utf-8"
        )
    )
    license_packet = json.loads(
        (tmp_path / "registry/compliance/tushare_license_review_packet.json").read_text(
            encoding="utf-8"
        )
    )

    assert not result.gold_review_template_updated
    assert not result.license_review_template_updated
    assert gold_review_path.read_text(encoding="utf-8").endswith("{\n")
    assert license_review_path.read_text(encoding="utf-8").endswith("{\n")
    assert any(
        f"gold-set review row {gold_expected_row} must contain valid JSON" in blocker
        for blocker in gold_summary["blockers"]
    )
    assert any(
        f"source license review row {license_expected_row} must contain valid JSON" in blocker
        for blocker in license_packet["blockers"]
    )
