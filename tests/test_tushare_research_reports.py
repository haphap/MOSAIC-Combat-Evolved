from __future__ import annotations

import pandas as pd

from mosaic.dataflows import tushare


class FakeResearchReportClient:
    def __init__(self, responses: list[pd.DataFrame]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def research_report(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected research_report call")
        return self.responses.pop(0)


def _empty_reports() -> pd.DataFrame:
    return pd.DataFrame(columns=tushare._RESEARCH_REPORT_FIELDS.split(","))


def _wide_reports() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "20260420",
                "title": "Battery leader update",
                "abstr": "Recent report context outside the requested window.",
                "author": "Analyst A",
                "inst_csname": "Broker A",
                "ts_code": "300750.SZ",
                "ind_name": "battery",
                "url": "https://example.invalid/report-a",
            },
            {
                "trade_date": "20260318",
                "title": "Supply-chain review",
                "abstr": "Older context.",
                "author": "Analyst B",
                "inst_csname": "Broker B",
                "ts_code": "300750.SZ",
                "ind_name": "battery",
                "url": "",
            },
        ]
    )


def test_stock_reports_empty_requested_window_returns_wide_context(monkeypatch):
    fake = FakeResearchReportClient([_empty_reports(), _wide_reports()])
    monkeypatch.setattr(tushare, "_get_pro_client", lambda: fake)

    out = tushare.get_stock_reports(
        "300750.SZ",
        "2026-05-01",
        "2026-06-05",
        max_reports=1,
    )

    assert "Period: 2026-05-01 to 2026-06-05 | Total: 0 reports" in out
    assert "Fallback: 2 report(s) found within the past 120 days" in out
    assert "outside the requested window" in out
    assert "## Report 1: 2026-04-20 | Broker A" in out
    assert "Supply-chain review" not in out
    assert fake.calls[1]["start_date"] == "20260205"


def test_broker_reports_empty_requested_window_returns_wide_context(monkeypatch):
    fake = FakeResearchReportClient([_empty_reports(), _wide_reports()])
    monkeypatch.setattr(tushare, "_get_pro_client", lambda: fake)
    monkeypatch.setattr(
        tushare,
        "_resolve_broker_industry_keyword",
        lambda *args, **kwargs: ("battery", "unit-test", "battery"),
    )

    out = tushare.get_broker_reports(
        "300750.SZ",
        "2026-05-01",
        "2026-06-05",
        max_reports=2,
    )

    assert "Period: 2026-05-01 to 2026-06-05 | Total: 0 reports" in out
    assert "Industry keyword source: unit-test" in out
    assert "Fallback: 2 report(s) found within the past 120 days" in out
    assert "## Report 1: 2026-04-20 | Broker A" in out
    assert "## Report 2: 2026-03-18 | Broker B" in out


def test_broker_reports_unresolved_industry_returns_no_data_note(monkeypatch):
    fake = FakeResearchReportClient([_empty_reports(), _empty_reports()])
    monkeypatch.setattr(tushare, "_get_pro_client", lambda: fake)

    out = tushare.get_broker_reports(
        "600519.SH",
        "2026-05-01",
        "2026-06-05",
        max_reports=2,
    )

    assert "Industry Research Reports for unresolved industry" in out
    assert "Period: 2026-05-01 to 2026-06-05 | Total: 0 reports" in out
    assert "Industry keyword source: unresolved" in out
    assert "Resolution failed: Cannot determine broker-search industry keyword" in out
