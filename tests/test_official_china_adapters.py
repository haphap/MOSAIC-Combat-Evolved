from __future__ import annotations

import base64

import pytest

from mosaic.dataflows import official_china_adapters
from mosaic.dataflows.exceptions import DataVendorUnavailable
from mosaic.dataflows.official_china_adapters import (
    OFFICIAL_CHINA_CATALOG_SPECS,
    OFFICIAL_CHINA_DOCUMENT_SPECS,
    fetch_latest_official_china_document,
    parse_official_china_document,
)
from mosaic.dataflows.pboc_ops import PBOC_OMO_CATEGORIES


def _html(title: str, published: str, body: str) -> str:
    return f"""
    <html><head><title>{title}</title></head>
    <body><div class="published">{published}</div><div id="zoom">{body}</div></body>
    </html>
    """


@pytest.mark.parametrize(
    ("document_type", "url", "html", "expected_branches", "expected_series"),
    [
        (
            "nbs_monthly_activity",
            "https://www.stats.gov.cn/sj/zxfb/202607/t20260715_1964123.html",
            _html(
                "2026年6月份国民经济运行情况",
                "2026/07/15 10:00",
                "规模以上工业增加值同比实际增长5.3%。"
                "固定资产投资（不含农户）同比下降4.1%。"
                "社会消费品零售总额同比增长1.3%。"
                "全国城镇调查失业率为5.0%。"
                "居民消费价格同比上涨0.1%，工业生产者出厂价格同比下降2.2%。",
            ),
            {
                "official.nbs_industrial_value_added",
                "official.nbs_fixed_asset_investment",
                "official.nbs_retail_sales",
                "official.nbs_employment_release",
                "official.nbs_price_release_verification",
            },
            {
                "cn_industrial_yoy",
                "cn_fixed_asset_investment_yoy",
                "cn_retail_sales_yoy",
                "cn_urban_unemployment_rate",
                "cn_cpi_official_yoy",
                "cn_ppi_official_yoy",
            },
        ),
        (
            "nbs_industrial_activity",
            "https://www.stats.gov.cn/sj/zxfb/202607/t20260715_1964123.html",
            _html(
                "2026年6月份规模以上工业增加值增长5.3%",
                "2026/07/15 10:00",
                "<span>6</span> 月份，规模以上工业增加值同比实际增长 <span>5.3</span> %。",
            ),
            {"official.nbs_industrial_value_added"},
            {"cn_industrial_yoy"},
        ),
        (
            "nbs_fixed_asset_investment",
            "https://www.stats.gov.cn/sj/zxfb/202607/t20260715_1964124.html",
            _html(
                "2026年1—6月份全国固定资产投资基本情况",
                "2026/07/15 10:00",
                "1—6月份，全国固定资产投资（不含农户） <span>226370</span> 亿元，"
                "同比下降 <span>5.7</span> %。",
            ),
            {"official.nbs_fixed_asset_investment"},
            {"cn_fixed_asset_investment_yoy"},
        ),
        (
            "nbs_retail_sales",
            "https://www.stats.gov.cn/sj/zxfbhjd/202607/t20260715_1964127.html",
            _html(
                "2026年上半年社会消费品零售总额增长1.3%",
                "2026/07/15 10:00",
                "上半年，社会消费品零售总额同比增长1.3%。"
                "<span>6</span> 月份，社会消费品零售总额 <span>42691</span> 亿元，"
                "同比增长 <span>1.0</span> %。",
            ),
            {"official.nbs_retail_sales"},
            {"cn_retail_sales_yoy"},
        ),
        (
            "nbs_employment_release",
            "https://www.stats.gov.cn/sj/zxfbhjd/202607/t20260715_1964121.html",
            _html(
                "上半年经济运行在合理区间 新动能快速成长",
                "2026/07/15 10:00",
                "上半年，全国城镇调查失业率平均值为5.2%。"
                "<span>6</span> 月份，全国城镇调查失业率为 <span>5.0</span> %。",
            ),
            {"official.nbs_employment_release"},
            {"cn_urban_unemployment_rate"},
        ),
        (
            "nbs_cpi_release",
            "https://www.stats.gov.cn/sj/zxfbhjd/202607/t20260709_1964084.html",
            _html(
                "2026年6月份居民消费价格同比上涨1.0%",
                "2026/07/09 09:30",
                "2026年6月份，全国居民消费价格同比上涨 <span>1.0</span> %。",
            ),
            {"official.nbs_price_release_verification"},
            {"cn_cpi_official_yoy"},
        ),
        (
            "nbs_ppi_release",
            "https://www.stats.gov.cn/sj/zxfb/202607/t20260709_1964083.html",
            _html(
                "2026年6月份工业生产者出厂价格同比上涨4.1%",
                "2026/07/09 09:30",
                "2026年6月份，全国工业生产者出厂价格同比上涨 <span>4.1</span> %。",
            ),
            {"official.nbs_price_release_verification"},
            {"cn_ppi_official_yoy"},
        ),
        (
            "pboc_financial_statistics",
            "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/abc/index.html",
            _html(
                "2026年6月金融统计数据报告",
                "文章来源： 2026-07-10 17:00:00",
                "社会融资规模存量为430.2万亿元，同比增长8.7%。"
                "人民币贷款增加12.3万亿元。"
                "广义货币(M2)余额为340.1万亿元，同比增长8.3%。",
            ),
            {
                "official.pboc_financial_statistics",
                "official.pboc_tsfin_flow_stock",
                "official.pboc_rmb_loans",
                "official.pboc_money_stock",
            },
            {"cn_tsfin_stock_yoy", "cn_rmb_loan_flow", "cn_m2_yoy"},
        ),
        (
            "customs_monthly_trade",
            (
                "https://english.www.gov.cn/archive/statistics/202608/07/"
                "content_WS6a7599d2c6d00ca5f9a0c8c9.html"
            ),
            _html(
                "China's foreign trade expands 19.2 pct in July",
                "2026/08/07",
                "China's foreign trade in yuan-denominated terms grew 19.2 percent "
                "year on year in July, data from the General Administration of "
                "Customs showed on Friday. Exports rose 17.8 percent from the same "
                "period last year, while imports increased 21.2 percent. Exports of "
                "high-tech products surged by over 50 percent year on year in July.",
            ),
            {
                "official.customs_total_trade",
                "official.customs_partner_trade",
                "official.customs_major_goods_trade",
            },
            {
                "cn_trade_total_yoy",
                "cn_trade_exports_yoy",
                "cn_trade_imports_yoy",
                "cn_trade_high_tech_exports_yoy",
            },
        ),
        (
            "mof_fiscal_release",
            "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/abc.htm",
            _html(
                "2026年1-6月财政收支情况",
                "2026-07-22",
                "全国一般公共预算收入同比增长1.5%。政府性基金预算收入同比下降2.5%。",
            ),
            {
                "official.mof_general_public_budget",
                "official.mof_government_fund_budget",
            },
            {"cn_fiscal_general_budget_yoy", "cn_fiscal_government_fund_yoy"},
        ),
    ],
)
def test_source_specific_parsers_freeze_identity_time_units_and_metrics(
    document_type: str,
    url: str,
    html: str,
    expected_branches: set[str],
    expected_series: set[str],
) -> None:
    result = parse_official_china_document(
        document_type=document_type,
        url=url,
        html=html,
        retrieved_at="2026-08-08T06:00:00+00:00",
    )

    assert set(result["branches_covered"]) == expected_branches
    assert {row["series_id"] for row in result["observations"]} == expected_series
    assert all(row["source"] in expected_branches for row in result["observations"])
    assert all(row["unit"] for row in result["observations"])
    assert all(row["period_start"] <= row["period_end"] for row in result["observations"])
    assert result["document_id"]
    assert result["published_at"].endswith("+08:00")
    assert result["content_hash"].startswith("sha256:")
    assert result["revision_id"].startswith("official-cn-revision:")
    assert base64.b64decode(result["raw_payload_b64"]) == html.encode()


def test_day_precision_release_is_conservatively_end_of_day() -> None:
    result = parse_official_china_document(
        document_type="mof_fiscal_release",
        url="https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/abc.htm",
        html=_html(
            "2026年1-6月财政收支情况",
            "2026-07-22",
            "全国一般公共预算收入同比增长1.5%。政府性基金预算收入同比增长2.5%。",
        ),
        retrieved_at="2026-07-23T00:00:00+00:00",
    )

    assert result["release_precision"] == "DAY"
    assert result["published_at"] == "2026-07-22T23:59:59+08:00"


def test_document_identity_is_stable_but_revision_changes_with_content() -> None:
    kwargs = {
        "document_type": "mof_fiscal_release",
        "url": "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/abc.htm",
        "retrieved_at": "2026-07-23T00:00:00+00:00",
    }
    first = parse_official_china_document(
        **kwargs,
        html=_html(
            "财政收支情况",
            "2026-07-22",
            "全国一般公共预算收入同比增长1.5%。政府性基金预算收入同比增长2.5%。",
        ),
    )
    revised = parse_official_china_document(
        **kwargs,
        html=_html(
            "财政收支情况",
            "2026-07-22",
            "全国一般公共预算收入同比增长1.6%。政府性基金预算收入同比增长2.5%。",
        ),
    )

    assert first["document_id"] == revised["document_id"]
    assert first["content_hash"] != revised["content_hash"]
    assert first["revision_id"] != revised["revision_id"]


@pytest.mark.parametrize(
    ("document_type", "url"),
    [
        ("nbs_monthly_activity", "https://example.com/fake.html"),
        ("pboc_financial_statistics", "https://stats.gov.cn/wrong-agency.html"),
        ("unknown", "https://www.stats.gov.cn/sj/zxfb/x.html"),
    ],
)
def test_unknown_or_cross_agency_sources_are_denied(
    document_type: str, url: str
) -> None:
    with pytest.raises((DataVendorUnavailable, ValueError), match="allowlist|document_type"):
        parse_official_china_document(
            document_type=document_type,
            url=url,
            html=_html("title", "2026-07-22", "body"),
            retrieved_at="2026-07-23T00:00:00+00:00",
        )


def test_missing_publication_time_or_required_metric_fails_closed() -> None:
    with pytest.raises(DataVendorUnavailable, match="publication timestamp"):
        parse_official_china_document(
            document_type="nbs_monthly_activity",
            url="https://www.stats.gov.cn/sj/zxfb/x.html",
            html="<html><title>missing</title><body>工业增加值增长5%</body></html>",
            retrieved_at="2026-07-23T00:00:00+00:00",
        )

    with pytest.raises(DataVendorUnavailable, match="required metric"):
        parse_official_china_document(
            document_type="nbs_monthly_activity",
            url="https://www.stats.gov.cn/sj/zxfb/x.html",
            html=_html("title", "2026/07/15 10:00", "只有工业增加值同比增长5%"),
            retrieved_at="2026-07-23T00:00:00+00:00",
        )


def test_document_spec_closure_has_no_unowned_branch() -> None:
    branches = {
        branch
        for spec in OFFICIAL_CHINA_DOCUMENT_SPECS.values()
        for branch in spec["branches"]
    }
    assert {
        "official.nbs_industrial_value_added",
        "official.pboc_tsfin_flow_stock",
        "official.customs_total_trade",
        "official.mof_general_public_budget",
    } <= branches


def test_nbs_catalog_contract_uses_independent_release_documents() -> None:
    required = {
        "nbs_industrial_activity",
        "nbs_fixed_asset_investment",
        "nbs_retail_sales",
        "nbs_employment_release",
        "nbs_cpi_release",
        "nbs_ppi_release",
    }

    assert required <= set(OFFICIAL_CHINA_DOCUMENT_SPECS)
    assert required <= set(OFFICIAL_CHINA_CATALOG_SPECS)
    assert "nbs_monthly_activity" not in OFFICIAL_CHINA_CATALOG_SPECS


def test_catalog_selector_skips_future_release_and_fetches_latest_eligible_document() -> None:
    catalog_url = OFFICIAL_CHINA_CATALOG_SPECS["mof_fiscal_release"]["catalog_url"]
    eligible_url = "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/eligible.htm"
    future_url = "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/future.htm"
    calls: list[str] = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if url == catalog_url:
            return f"""
            <ul>
              <li><a href="{future_url}">2026年1-7月财政收支情况</a><span>2026-08-20</span></li>
              <li><a href="{eligible_url}">2026年1-6月财政收支情况</a><span>2026-07-22</span></li>
            </ul>
            """
        if url == eligible_url:
            return _html(
                "2026年1-6月财政收支情况",
                "2026-07-22",
                "全国一般公共预算收入同比增长1.5%。政府性基金预算收入同比下降2.5%。",
            )
        raise AssertionError(f"future or unknown document fetched: {url}")

    result = fetch_latest_official_china_document(
        document_type="mof_fiscal_release",
        cutoff_at="2026-08-08T15:00:00+08:00",
        retrieved_at="2026-08-08T06:00:00+00:00",
        fetch_text=fetch_text,
    )

    assert result["source_url"] == eligible_url
    assert calls == [catalog_url, eligible_url]


def test_catalog_selector_fails_closed_when_no_matching_eligible_release() -> None:
    catalog_url = OFFICIAL_CHINA_CATALOG_SPECS["mof_fiscal_release"]["catalog_url"]

    with pytest.raises(DataVendorUnavailable, match="eligible release"):
        fetch_latest_official_china_document(
            document_type="mof_fiscal_release",
            cutoff_at="2026-08-08T15:00:00+08:00",
            retrieved_at="2026-08-08T06:00:00+00:00",
            fetch_text=lambda url: (
                '<a href="future.htm">2026年1-7月财政收支情况</a><span>2026-08-20</span>'
                if url == catalog_url
                else pytest.fail("future release must not be fetched")
            ),
        )


def test_customs_catalog_uses_strict_tls_gov_cn_mirror_and_real_monthly_shape() -> None:
    catalog_url = OFFICIAL_CHINA_CATALOG_SPECS["customs_monthly_trade"]["catalog_url"]
    release_url = (
        "https://english.www.gov.cn/archive/statistics/202608/07/"
        "content_WS6a7599d2c6d00ca5f9a0c8c9.html"
    )
    calls: list[str] = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if url == catalog_url:
            return (
                '<h3><a href="//english.www.gov.cn/archive/statistics/202608/07/'
                'content_WS6a7599d2c6d00ca5f9a0c8c9.html">'
                "China's foreign trade expands 19.2 pct in July</a></h3>"
                "<h4>2026/08/07</h4>"
            )
        if url == release_url:
            return """
            <html><head>
              <title>China's foreign trade expands 19.2 pct in July</title>
              <meta name="publishdate" content="2026-08-07" />
            </head><body>
              <p>China's foreign trade in yuan-denominated terms grew 19.2 percent
              year on year in July, data from the General Administration of Customs
              showed on Friday.</p>
              <p>Exports rose 17.8 percent from the same period last year, while
              imports increased 21.2 percent.</p>
              <p>Exports of high-tech products surged by over 50 percent year on
              year in July.</p>
            </body></html>
            """
        raise AssertionError(f"unexpected fetch: {url}")

    result = fetch_latest_official_china_document(
        document_type="customs_monthly_trade",
        cutoff_at="2026-08-08T15:00:00+08:00",
        retrieved_at="2026-08-08T06:00:00+00:00",
        fetch_text=fetch_text,
    )

    assert OFFICIAL_CHINA_DOCUMENT_SPECS["customs_monthly_trade"]["provider"] == (
        "GACC_VIA_GOV_CN"
    )
    assert result["source_url"] == release_url
    assert result["published_at"] == "2026-08-07T23:59:59+08:00"
    high_tech = next(
        row
        for row in result["observations"]
        if row["series_id"] == "cn_trade_high_tech_exports_yoy"
    )
    assert high_tech["actual"] == 50.0
    assert high_tech["value_qualifier"] == "LOWER_BOUND"
    assert high_tech["unit"] == "percent_yoy_lower_bound"
    assert high_tech["period_start"] == "2026-07-01"
    assert high_tech["period_end"] == "2026-07-31"
    assert calls == [catalog_url, release_url]


def test_nbs_catalog_selector_walks_observed_pagination_until_price_release() -> None:
    catalog_url = OFFICIAL_CHINA_CATALOG_SPECS["nbs_cpi_release"]["catalog_url"]
    second_page = "https://www.stats.gov.cn/sj/zxfb/index_1.html"
    release_url = "https://www.stats.gov.cn/sj/zxfbhjd/202607/cpi.html"
    calls: list[str] = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if url == catalog_url:
            return '<script>createPageHTML(2, 0, "index", "html");</script>'
        if url == second_page:
            return (
                f'<a href="{release_url}">2026年6月份居民消费价格同比上涨1.0%</a>'
                '<span>2026-07-09</span>'
            )
        if url == release_url:
            return _html(
                "2026年6月份居民消费价格同比上涨1.0%",
                "2026/07/09 09:30",
                "2026年6月份，全国居民消费价格同比上涨1.0%。",
            )
        raise AssertionError(f"unexpected fetch: {url}")

    result = fetch_latest_official_china_document(
        document_type="nbs_cpi_release",
        cutoff_at="2026-08-08T15:00:00+08:00",
        retrieved_at="2026-08-08T06:00:00+00:00",
        fetch_text=fetch_text,
    )

    assert result["source_url"] == release_url
    assert calls == [catalog_url, second_page, release_url]


def test_mof_catalog_upgrades_allowlisted_http_article_to_verified_https() -> None:
    catalog_url = OFFICIAL_CHINA_CATALOG_SPECS["mof_fiscal_release"]["catalog_url"]
    insecure_url = "http://gks.mof.gov.cn/tongjishuju/202607/release.htm"
    release_url = "https://gks.mof.gov.cn/tongjishuju/202607/release.htm"
    calls: list[str] = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if url == catalog_url:
            return (
                f'<a href="{insecure_url}">2026年上半年财政收支情况</a>'
                '<span>2026-07-22</span>'
            )
        if url == release_url:
            return """
            <html><head>
              <title>2026年上半年财政收支情况</title>
              <meta name="PubDate" content="2026-07-22 09:58:00" />
            </head><body>
              <nav>2017-11-21</nav>
              <div>全国一般公共预算收入同比增长 <span>4 .7</span> %。
              全国政府性基金预算收入同比下降21.6%。</div>
            </body></html>
            """
        raise AssertionError(f"plain HTTP or unknown URL fetched: {url}")

    result = fetch_latest_official_china_document(
        document_type="mof_fiscal_release",
        cutoff_at="2026-08-08T15:00:00+08:00",
        retrieved_at="2026-08-08T06:00:00+00:00",
        fetch_text=fetch_text,
    )

    assert result["source_url"] == release_url
    assert result["published_at"] == "2026-07-22T09:58:00+08:00"
    assert calls == [catalog_url, release_url]


def test_pboc_omo_adapter_reuses_existing_article_table_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def parse_article(html: str, url: str, category: str) -> dict:
        calls.append((url, category))
        assert "operation table" in html
        return {"rates": ["1.40%"]}

    monkeypatch.setattr(
        official_china_adapters,
        "parse_pboc_article_page",
        parse_article,
    )
    result = parse_official_china_document(
        document_type="pboc_omo_document",
        url=(
            "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/"
            "125431/125475/release/index.html"
        ),
        html=_html(
            "公开市场业务交易公告 [2026]第152号",
            "2026-08-07 09:00:00",
            "operation table",
        ),
        retrieved_at="2026-08-08T06:00:00+00:00",
    )

    transaction_category = next(
        row for row in PBOC_OMO_CATEGORIES if row.id == "transaction_notice"
    )
    assert OFFICIAL_CHINA_CATALOG_SPECS["pboc_omo_document"]["catalog_url"] == (
        transaction_category.url
    )
    assert result["observations"][0]["actual"] == 1.4
    assert result["observations"][0]["period_start"] == "2026-08-07"
    assert result["observations"][0]["period_end"] == "2026-08-07"
    assert calls == [(result["source_url"], "transaction_notice")]
