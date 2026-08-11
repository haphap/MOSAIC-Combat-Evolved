"""Strict parsers for official China macro release documents.

The adapters freeze public document identity, publication time and content.
They do not decide economic correctness and do not make historical releases
point-in-time eligible: that boundary belongs to the forward source archive.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Final
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

from .exceptions import DataVendorUnavailable
from .pboc_ops import (
    PBOC_OMO_CATEGORIES,
    fetch_pboc_text,
    parse_article_page as parse_pboc_article_page,
)


ADAPTER_VERSION: Final = "official_china_adapters_v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DATETIME_RE = re.compile(
    r"(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})"
    r"\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
)
_DATE_RE = re.compile(
    r"(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})"
)
_CHINESE_DATE_RE = re.compile(
    r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
)
_CHINESE_PERIOD_RE = re.compile(
    r"(?P<year>20\d{2})年(?:(?P<start>\d{1,2})[-—–至](?P<end>\d{1,2})月|(?P<month>\d{1,2})月份?)"
)
_CHINESE_NAMED_PERIOD_RE = re.compile(
    r"(?P<year>20\d{2})年(?P<period>上半年|前三季度|一季度|二季度|三季度|四季度|全年)"
)
_ENGLISH_MONTHS = {
    name.casefold(): month
    for month in range(1, 13)
    for name in (calendar.month_name[month], calendar.month_abbr[month])
}
_ENGLISH_PERIOD_RE = re.compile(
    r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)


OFFICIAL_CHINA_DOCUMENT_SPECS: Final[dict[str, dict[str, Any]]] = {
    "nbs_monthly_activity": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": (
            "official.nbs_industrial_value_added",
            "official.nbs_fixed_asset_investment",
            "official.nbs_retail_sales",
            "official.nbs_employment_release",
            "official.nbs_price_release_verification",
        ),
        "metric_parser": "nbs",
        "required_metric_count": 6,
    },
    "nbs_industrial_activity": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": ("official.nbs_industrial_value_added",),
        "metric_parser": "nbs_industrial",
        "required_metric_count": 1,
    },
    "nbs_fixed_asset_investment": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": ("official.nbs_fixed_asset_investment",),
        "metric_parser": "nbs_fixed_asset_investment",
        "required_metric_count": 1,
    },
    "nbs_retail_sales": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": ("official.nbs_retail_sales",),
        "metric_parser": "nbs_retail_sales",
        "required_metric_count": 1,
        "period_mode": "previous_month",
    },
    "nbs_employment_release": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": ("official.nbs_employment_release",),
        "metric_parser": "nbs_employment",
        "required_metric_count": 1,
        "period_mode": "previous_month",
    },
    "nbs_cpi_release": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": ("official.nbs_price_release_verification",),
        "metric_parser": "nbs_cpi",
        "required_metric_count": 1,
    },
    "nbs_ppi_release": {
        "provider": "NBS",
        "hosts": ("stats.gov.cn", "www.stats.gov.cn"),
        "branches": ("official.nbs_price_release_verification",),
        "metric_parser": "nbs_ppi",
        "required_metric_count": 1,
    },
    "pboc_financial_statistics": {
        "provider": "PBOC",
        "hosts": ("pbc.gov.cn", "www.pbc.gov.cn"),
        "branches": (
            "official.pboc_financial_statistics",
            "official.pboc_tsfin_flow_stock",
            "official.pboc_rmb_loans",
            "official.pboc_money_stock",
        ),
        "metric_parser": "pboc_financial",
        "required_metric_count": 3,
    },
    "pboc_omo_document": {
        "provider": "PBOC",
        "hosts": ("pbc.gov.cn", "www.pbc.gov.cn"),
        "branches": ("official.pboc_omo_catalog",),
        "metric_parser": "pboc_omo",
        "required_metric_count": 1,
        "period_mode": "publication_date",
    },
    "pboc_lpr_document": {
        "provider": "PBOC",
        "hosts": ("pbc.gov.cn", "www.pbc.gov.cn"),
        "branches": ("official.pboc_lpr_catalog",),
        "metric_parser": "pboc_lpr",
        "required_metric_count": 1,
        "period_mode": "publication_date",
    },
    "pboc_mpc_meeting": {
        "provider": "PBOC",
        "hosts": ("pbc.gov.cn", "www.pbc.gov.cn"),
        "branches": ("official.pboc_mpc_meeting_catalog",),
        "metric_parser": None,
        "required_metric_count": 0,
    },
    "pboc_monetary_policy_report": {
        "provider": "PBOC",
        "hosts": ("pbc.gov.cn", "www.pbc.gov.cn"),
        "branches": ("official.pboc_monetary_policy_report_catalog",),
        "metric_parser": None,
        "required_metric_count": 0,
    },
    "customs_monthly_trade": {
        "provider": "GACC_VIA_GOV_CN",
        "hosts": ("english.www.gov.cn",),
        "branches": (
            "official.customs_total_trade",
            "official.customs_partner_trade",
            "official.customs_major_goods_trade",
        ),
        "metric_parser": "customs",
        "required_metric_count": 4,
        "period_mode": "previous_month",
    },
    "mof_fiscal_release": {
        "provider": "MOF",
        "hosts": ("mof.gov.cn", "www.mof.gov.cn", "gks.mof.gov.cn"),
        "branches": (
            "official.mof_general_public_budget",
            "official.mof_government_fund_budget",
        ),
        "metric_parser": "mof",
        "required_metric_count": 2,
    },
}

OFFICIAL_CHINA_CATALOG_SPECS: Final[dict[str, dict[str, str]]] = {
    "nbs_industrial_activity": {
        "catalog_url": "https://www.stats.gov.cn/sj/zxfb/",
        "title_pattern": r"规模以上工业增加值",
    },
    "nbs_fixed_asset_investment": {
        "catalog_url": "https://www.stats.gov.cn/sj/zxfb/",
        "title_pattern": r"全国固定资产投资基本情况",
    },
    "nbs_retail_sales": {
        "catalog_url": "https://www.stats.gov.cn/sj/zxfb/",
        "title_pattern": r"社会消费品零售总额",
    },
    "nbs_employment_release": {
        "catalog_url": "https://www.stats.gov.cn/sj/zxfb/",
        "title_pattern": r"经济运行",
    },
    "nbs_cpi_release": {
        "catalog_url": "https://www.stats.gov.cn/sj/zxfb/",
        "title_pattern": r"居民消费价格同比",
    },
    "nbs_ppi_release": {
        "catalog_url": "https://www.stats.gov.cn/sj/zxfb/",
        "title_pattern": r"工业生产者出厂价格同比",
    },
    "pboc_financial_statistics": {
        "catalog_url": "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html",
        "title_pattern": r"金融统计数据报告",
    },
    "pboc_omo_document": {
        "catalog_url": next(
            category.url
            for category in PBOC_OMO_CATEGORIES
            if category.id == "transaction_notice"
        ),
        "title_pattern": r"公开市场业务交易公告",
    },
    "pboc_lpr_document": {
        "catalog_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html",
        "title_pattern": r"贷款市场报价利率|LPR",
    },
    "pboc_mpc_meeting": {
        "catalog_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/3870933/3870936/index.html",
        "title_pattern": r"货币政策委员会.*例会",
    },
    "pboc_monetary_policy_report": {
        "catalog_url": "https://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html",
        "title_pattern": r"货币政策执行报告",
    },
    "customs_monthly_trade": {
        "catalog_url": "https://english.www.gov.cn/archive/statistics/",
        "title_pattern": (
            r"China(?:'s)?(?:\s+\S+){0,4}\s+foreign trade\s+"
            r"(?:expands|maintains|posts|records)"
        ),
    },
    "mof_fiscal_release": {
        "catalog_url": "https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/",
        "title_pattern": r"财政收支情况",
    },
}

_CATALOG_LINK_RE = re.compile(
    r"<a\b[^>]*\bhref\s*=\s*(?P<quote>['\"])(?P<href>.*?)(?P=quote)[^>]*>"
    r"(?P<label>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_NBS_PAGE_COUNT_RE = re.compile(
    r"createPageHTML\(\s*(?P<count>\d+)\s*,\s*\d+\s*,\s*['\"]index['\"]",
    re.IGNORECASE,
)
_GOV_CN_STATS_PAGE_RE = re.compile(r"/archive/statistics/page_(?P<page>\d+)\.html")
_TAG_RE = re.compile(r"<[^>]+>")
_HTTP_TIMEOUT_SECONDS = 20
_USER_AGENT = "MOSAIC-Agent-Data/official-china-forward-archive"
FetchText = Callable[[str], str]
PostJson = Callable[..., Any]
MOF_CHINABOND_YIELD_CURVE_URL: Final = (
    "https://yield.chinabond.com.cn/cbweb-czb-web/czb/historyQuery"
)
MOF_CHINABOND_CURVE_SCHEMA_VERSION: Final = (
    "mof_chinabond_government_yield_curve_v1"
)
MOF_CHINABOND_REQUIRED_TENORS: Final[dict[int, str]] = {
    1: "oneYear",
    2: "twoYear",
    3: "threeYear",
    5: "fiveYear",
    7: "sevenYear",
    10: "tenYear",
    30: "thirtyYear",
}
_PBOC_TRANSACTION_CATEGORY = next(
    category
    for category in PBOC_OMO_CATEGORIES
    if category.id == "transaction_notice"
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.publication_candidates: list[str] = []
        self._in_title = False
        self._suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        if normalized == "meta":
            values = {
                key.casefold(): value
                for key, value in attrs
                if value is not None
            }
            identity = (
                values.get("name") or values.get("property") or ""
            ).casefold()
            if identity in {
                "pubdate",
                "publishdate",
                "publicationdate",
                "article:published_time",
            } and values.get("content"):
                self.publication_candidates.append(values["content"])
        if normalized == "title":
            self._in_title = True
        if normalized in {"script", "style", "noscript"}:
            self._suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self._in_title = False
        if normalized in {"script", "style", "noscript"} and self._suppressed_depth:
            self._suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        value = unescape(data).strip()
        if not value:
            return
        self.text_parts.append(value)
        if self._in_title:
            self.title_parts.append(value)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DataVendorUnavailable(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DataVendorUnavailable(f"{field} must include timezone")
    return parsed


def _published_at(text: str) -> tuple[datetime, str]:
    match = _DATETIME_RE.search(text)
    if match:
        values = {key: int(value or 0) for key, value in match.groupdict().items()}
        return (
            datetime(
                values["year"],
                values["month"],
                values["day"],
                values["hour"],
                values["minute"],
                values["second"],
                tzinfo=_SHANGHAI,
            ),
            "SECOND" if match.group("second") is not None else "MINUTE",
        )
    match = _DATE_RE.search(text) or _CHINESE_DATE_RE.search(text)
    if not match:
        raise DataVendorUnavailable(
            "official China document lacks a publication timestamp"
        )
    values = {key: int(value) for key, value in match.groupdict().items()}
    return (
        datetime.combine(
            datetime(values["year"], values["month"], values["day"]).date(),
            time(23, 59, 59),
            tzinfo=_SHANGHAI,
        ),
        "DAY",
    )


def _number(value: str) -> float:
    return float(re.sub(r"[\s,]", "", value))


def _period_bounds(title: str, published: datetime) -> tuple[str, str]:
    named = _CHINESE_NAMED_PERIOD_RE.search(title)
    if named:
        year = int(named.group("year"))
        start_month, end_month = {
            "上半年": (1, 6),
            "前三季度": (1, 9),
            "一季度": (1, 3),
            "二季度": (4, 6),
            "三季度": (7, 9),
            "四季度": (10, 12),
            "全年": (1, 12),
        }[named.group("period")]
    elif chinese := _CHINESE_PERIOD_RE.search(title):
        year = int(chinese.group("year"))
        start_month = int(chinese.group("start") or chinese.group("month"))
        end_month = int(chinese.group("end") or chinese.group("month"))
    else:
        english = _ENGLISH_PERIOD_RE.search(title)
        if english:
            year = int(english.group("year"))
            start_month = end_month = _ENGLISH_MONTHS[
                english.group("month").casefold()
            ]
        else:
            # Documents without a stated reference period are event records;
            # their observation date is the conservative publication date.
            year = published.year
            start_month = end_month = published.month
    if not (1 <= start_month <= end_month <= 12):
        raise DataVendorUnavailable("official China document has invalid period")
    start = datetime(year, start_month, 1).date()
    end = datetime(
        year,
        end_month,
        calendar.monthrange(year, end_month)[1],
    ).date()
    return start.isoformat(), end.isoformat()


def _previous_month_bounds(published: datetime) -> tuple[str, str]:
    year = published.year if published.month > 1 else published.year - 1
    month = published.month - 1 if published.month > 1 else 12
    start = datetime(year, month, 1).date()
    end = datetime(year, month, calendar.monthrange(year, month)[1]).date()
    return start.isoformat(), end.isoformat()


def _directional(match: re.Match[str]) -> float:
    value = _number(match.group("value"))
    direction = (match.groupdict().get("direction") or "").casefold()
    return (
        -value
        if direction
        in {
            "下降",
            "减少",
            "下跌",
            "fell",
            "decreased",
            "declined",
            "dropped",
            "contracted",
        }
        else value
    )


def _metric(
    *,
    series_id: str,
    source: str,
    actual: float,
    unit: str,
    value_qualifier: str | None = None,
) -> dict[str, Any]:
    metric = {
        "series_id": series_id,
        "source": source,
        "actual": actual,
        "unit": unit,
    }
    if value_qualifier is not None:
        metric["value_qualifier"] = value_qualifier
    return metric


def _required_match(pattern: str, text: str, label: str, *, flags: int = 0) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if match is None:
        raise DataVendorUnavailable(
            f"official China document missing required metric: {label}"
        )
    return match


def _parse_nbs(text: str) -> list[dict[str, Any]]:
    patterns = (
        (
            "cn_industrial_yoy",
            "official.nbs_industrial_value_added",
            r"规模以上工业增加值[^。；]*?同比(?:实际)?(?P<direction>增长|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        ),
        (
            "cn_fixed_asset_investment_yoy",
            "official.nbs_fixed_asset_investment",
            r"固定资产投资（不含农户）[^。；]*?同比(?P<direction>增长|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        ),
        (
            "cn_retail_sales_yoy",
            "official.nbs_retail_sales",
            r"社会消费品零售总额[^。；]*?同比(?P<direction>增长|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        ),
        (
            "cn_urban_unemployment_rate",
            "official.nbs_employment_release",
            r"全国城镇调查失业率[^。；]*?(?:为|平均为)(?P<value>\d+(?:\.\d+)?)%",
        ),
        (
            "cn_cpi_official_yoy",
            "official.nbs_price_release_verification",
            r"居民消费价格[^。；]*?同比(?P<direction>上涨|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        ),
        (
            "cn_ppi_official_yoy",
            "official.nbs_price_release_verification",
            r"工业生产者出厂价格[^。；]*?同比(?P<direction>上涨|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        ),
    )
    return [
        _metric(
            series_id=series_id,
            source=source,
            actual=(
                _number(match.group("value"))
                if "direction" not in match.groupdict()
                else _directional(match)
            ),
            unit="percent_yoy" if series_id != "cn_urban_unemployment_rate" else "percent",
        )
        for series_id, source, pattern in patterns
        for match in (_required_match(pattern, text, series_id),)
    ]


def _parse_nbs_industrial(text: str) -> list[dict[str, Any]]:
    match = _required_match(
        r"规模以上工业增加值[^。；]*?同比\s*(?:实际)?\s*"
        r"(?P<direction>增长|下降)\s*(?P<value>-?\d+(?:\.\d+)?)\s*%",
        text,
        "cn_industrial_yoy",
    )
    return [
        _metric(
            series_id="cn_industrial_yoy",
            source="official.nbs_industrial_value_added",
            actual=_directional(match),
            unit="percent_yoy",
        )
    ]


def _parse_nbs_fixed_asset_investment(text: str) -> list[dict[str, Any]]:
    match = _required_match(
        r"固定资产投资（不含农户）[^。；]*?同比\s*"
        r"(?P<direction>增长|下降)\s*(?P<value>-?\d+(?:\.\d+)?)\s*%",
        text,
        "cn_fixed_asset_investment_yoy",
    )
    return [
        _metric(
            series_id="cn_fixed_asset_investment_yoy",
            source="official.nbs_fixed_asset_investment",
            actual=_directional(match),
            unit="percent_yoy",
        )
    ]


def _parse_nbs_retail_sales(text: str) -> list[dict[str, Any]]:
    match = _required_match(
        r"\d{1,2}\s*月份\s*，\s*社会消费品零售总额[^。；]*?同比\s*"
        r"(?P<direction>增长|下降)\s*(?P<value>-?\d+(?:\.\d+)?)\s*%",
        text,
        "cn_retail_sales_yoy",
    )
    return [
        _metric(
            series_id="cn_retail_sales_yoy",
            source="official.nbs_retail_sales",
            actual=_directional(match),
            unit="percent_yoy",
        )
    ]


def _parse_nbs_employment(text: str) -> list[dict[str, Any]]:
    match = _required_match(
        r"\d{1,2}\s*月份\s*，\s*全国城镇调查失业率为\s*"
        r"(?P<value>\d+(?:\.\d+)?)\s*%",
        text,
        "cn_urban_unemployment_rate",
    )
    return [
        _metric(
            series_id="cn_urban_unemployment_rate",
            source="official.nbs_employment_release",
            actual=_number(match.group("value")),
            unit="percent",
        )
    ]


def _parse_nbs_cpi(text: str) -> list[dict[str, Any]]:
    match = _required_match(
        r"居民消费价格[^。；]*?同比(?P<direction>上涨|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        text,
        "cn_cpi_official_yoy",
    )
    return [
        _metric(
            series_id="cn_cpi_official_yoy",
            source="official.nbs_price_release_verification",
            actual=_directional(match),
            unit="percent_yoy",
        )
    ]


def _parse_nbs_ppi(text: str) -> list[dict[str, Any]]:
    match = _required_match(
        r"工业生产者出厂价格[^。；]*?同比(?P<direction>上涨|下降)(?P<value>-?\d+(?:\.\d+)?)%",
        text,
        "cn_ppi_official_yoy",
    )
    return [
        _metric(
            series_id="cn_ppi_official_yoy",
            source="official.nbs_price_release_verification",
            actual=_directional(match),
            unit="percent_yoy",
        )
    ]


def _parse_pboc_financial(text: str) -> list[dict[str, Any]]:
    tsfin = _required_match(
        r"社会融资规模存量(?:为)?[\d,.]+万亿元[^。；]*?同比(?P<direction>增长|下降)(?P<value>\d+(?:\.\d+)?)%",
        text,
        "social financing stock",
    )
    loans = _required_match(
        r"人民币贷款(?P<direction>增加|减少)(?P<value>\d+(?:\.\d+)?)万亿元",
        text,
        "RMB loan flow",
    )
    m2 = _required_match(
        r"广义货币\s*\(?M2\)?余额(?:为)?[\d,.]+万亿元[^。；]*?同比(?P<direction>增长|下降)(?P<value>\d+(?:\.\d+)?)%",
        text,
        "M2 growth",
        flags=re.IGNORECASE,
    )
    return [
        _metric(
            series_id="cn_tsfin_stock_yoy",
            source="official.pboc_tsfin_flow_stock",
            actual=_directional(tsfin),
            unit="percent_yoy",
        ),
        _metric(
            series_id="cn_rmb_loan_flow",
            source="official.pboc_rmb_loans",
            actual=_directional(loans),
            unit="trillion_cny",
        ),
        _metric(
            series_id="cn_m2_yoy",
            source="official.pboc_money_stock",
            actual=_directional(m2),
            unit="percent_yoy",
        ),
    ]


def _parse_customs(text: str) -> list[dict[str, Any]]:
    direction = (
        r"(?P<direction>grew|rose|increased|surged|jumped|expanded|fell|"
        r"decreased|declined|dropped|contracted)"
    )
    total = _required_match(
        r"(?:China(?:'s)? foreign trade(?: in [^.;]*?)?|"
        r"The total value of goods imports and exports(?: in [^.;]*?)?)\s+"
        + direction
        + r"\s+(?:by\s+)?(?P<value>\d+(?:\.\d+)?) percent",
        text,
        "cn_trade_total_yoy",
        flags=re.IGNORECASE,
    )
    exports = _required_match(
        r"\bExports\s+"
        + direction
        + r"\s+(?:by\s+)?(?P<value>\d+(?:\.\d+)?) percent",
        text,
        "cn_trade_exports_yoy",
        flags=re.IGNORECASE,
    )
    imports = _required_match(
        r"\bimports\s+"
        + direction
        + r"\s+(?:by\s+)?(?P<value>\d+(?:\.\d+)?) percent",
        text,
        "cn_trade_imports_yoy",
        flags=re.IGNORECASE,
    )
    high_tech = re.search(
        r"Exports of high-tech products[^.;]*?"
        + direction
        + r"\s+(?:by\s+)?(?P<qualifier>over\s+|more than\s+)?"
        r"(?P<value>\d+(?:\.\d+)?) percent",
        text,
        re.IGNORECASE,
    )
    if high_tech is not None:
        qualifier = (
            "LOWER_BOUND" if (high_tech.group("qualifier") or "").strip() else None
        )
        structural = _metric(
            series_id="cn_trade_high_tech_exports_yoy",
            source="official.customs_major_goods_trade",
            actual=_directional(high_tech),
            unit=(
                "percent_yoy_lower_bound"
                if qualifier == "LOWER_BOUND"
                else "percent_yoy"
            ),
            value_qualifier=qualifier,
        )
    else:
        mechanical = re.search(
            r"(?:Exports of mechanical and electrical products|"
            r"Mechanical and electrical products[^.]*\.\s*Exports of these products)"
            r"[^.;]*?"
            + direction
            + r"\s+(?:by\s+)?(?P<value>\d+(?:\.\d+)?) percent",
            text,
            re.IGNORECASE,
        )
        if mechanical is None:
            raise DataVendorUnavailable(
                "official China document missing required metric: "
                "cn_trade_structural_goods_exports_yoy"
            )
        structural = _metric(
            series_id="cn_trade_electromechanical_exports_yoy",
            source="official.customs_major_goods_trade",
            actual=_directional(mechanical),
            unit="percent_yoy",
        )
    return [
        _metric(
            series_id=series_id,
            source=source,
            actual=_directional(match),
            unit="percent_yoy",
        )
        for series_id, source, match in (
            ("cn_trade_total_yoy", "official.customs_total_trade", total),
            ("cn_trade_exports_yoy", "official.customs_partner_trade", exports),
            ("cn_trade_imports_yoy", "official.customs_partner_trade", imports),
        )
    ] + [structural]


def _parse_mof(text: str) -> list[dict[str, Any]]:
    patterns = (
        (
            "cn_fiscal_general_budget_yoy",
            "official.mof_general_public_budget",
            r"全国一般公共预算收入[^。；]*?同比\s*(?P<direction>增长|下降)\s*"
            r"(?P<value>\d+\s*(?:\.\s*\d+)?)\s*%",
        ),
        (
            "cn_fiscal_government_fund_yoy",
            "official.mof_government_fund_budget",
            r"政府性基金预算收入[^。；]*?同比\s*(?P<direction>增长|下降)\s*"
            r"(?P<value>\d+\s*(?:\.\s*\d+)?)\s*%",
        ),
    )
    return [
        _metric(
            series_id=series_id,
            source=source,
            actual=_directional(_required_match(pattern, text, series_id)),
            unit="percent_yoy",
        )
        for series_id, source, pattern in patterns
    ]


def _parse_pboc_lpr(text: str) -> list[dict[str, Any]]:
    rate = _required_match(
        r"1年期LPR(?:为)?(?P<value>\d+(?:\.\d+)?)%",
        text,
        "one-year LPR",
        flags=re.IGNORECASE,
    )
    return [
        _metric(
            series_id="pboc_lpr_1y",
            source="official.pboc_lpr_catalog",
            actual=_number(rate.group("value")),
            unit="percent",
        )
    ]


_METRIC_PARSERS = {
    "nbs": _parse_nbs,
    "nbs_industrial": _parse_nbs_industrial,
    "nbs_fixed_asset_investment": _parse_nbs_fixed_asset_investment,
    "nbs_retail_sales": _parse_nbs_retail_sales,
    "nbs_employment": _parse_nbs_employment,
    "nbs_cpi": _parse_nbs_cpi,
    "nbs_ppi": _parse_nbs_ppi,
    "pboc_financial": _parse_pboc_financial,
    "pboc_lpr": _parse_pboc_lpr,
    "customs": _parse_customs,
    "mof": _parse_mof,
}


def _document_id(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        raise DataVendorUnavailable("official China document URL lacks identity")
    leaf = parts[-1]
    if leaf.casefold() == "index.html" and len(parts) > 1:
        leaf = parts[-2]
    identity = leaf.rsplit(".", 1)[0]
    if not identity:
        raise DataVendorUnavailable("official China document URL lacks identity")
    return identity


def parse_official_china_document(
    *,
    document_type: str,
    url: str,
    html: str,
    retrieved_at: str,
) -> dict[str, Any]:
    """Parse and freeze one allowlisted official release document."""
    if document_type not in OFFICIAL_CHINA_DOCUMENT_SPECS:
        raise ValueError(f"unknown official China document_type: {document_type!r}")
    spec = OFFICIAL_CHINA_DOCUMENT_SPECS[document_type]
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in spec["hosts"]:
        raise DataVendorUnavailable(
            f"official China source URL is outside the {document_type} allowlist"
        )
    if not isinstance(html, str) or not html.strip():
        raise DataVendorUnavailable("official China document body is empty")
    parser = _VisibleTextParser()
    parser.feed(html)
    text = _normalized_text(" ".join(parser.text_parts))
    title = _normalized_text(" ".join(parser.title_parts))
    if not title:
        raise DataVendorUnavailable("official China document lacks title")
    publication_text = _normalized_text(" ".join(parser.publication_candidates))
    published, precision = _published_at(publication_text or text)
    retrieved = _parse_timestamp(retrieved_at, "retrieved_at")
    if published.astimezone(retrieved.tzinfo) > retrieved:
        raise DataVendorUnavailable(
            "official China publication timestamp is after retrieval"
        )
    parser_name = spec["metric_parser"]
    if parser_name == "pboc_omo":
        parsed_omo = parse_pboc_article_page(
            html,
            url,
            _PBOC_TRANSACTION_CATEGORY.id,
        )
        rates = parsed_omo.get("rates")
        if not isinstance(rates, list) or not rates:
            raise DataVendorUnavailable(
                "official China document missing required metric: PBOC OMO rate"
            )
        observations = [
            _metric(
                series_id="pboc_omo_rate",
                source="official.pboc_omo_catalog",
                actual=_number(str(rates[0]).removesuffix("%")),
                unit="percent",
            )
        ]
    else:
        observations = (
            [] if parser_name is None else _METRIC_PARSERS[parser_name](text)
        )
    if len(observations) < spec["required_metric_count"]:
        raise DataVendorUnavailable(
            f"official China document missing required metric set: {document_type}"
        )
    if spec.get("period_mode") == "previous_month":
        period_start, period_end = _previous_month_bounds(published)
    elif spec.get("period_mode") == "publication_date":
        period_start = period_end = published.date().isoformat()
    else:
        period_start, period_end = _period_bounds(title, published)
    observations = [
        {
            **observation,
            "period_start": period_start,
            "period_end": period_end,
        }
        for observation in observations
    ]
    raw = html.encode("utf-8")
    content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    document_id = _document_id(url)
    revision_material = (
        f"{document_type}\0{document_id}\0{published.isoformat()}\0{content_hash}"
    ).encode()
    revision_id = (
        "official-cn-revision:" + hashlib.sha256(revision_material).hexdigest()
    )
    return {
        "adapter_version": ADAPTER_VERSION,
        "document_type": document_type,
        "provider": spec["provider"],
        "document_id": document_id,
        "source_url": url,
        "title": title,
        "published_at": published.isoformat(),
        "release_precision": precision,
        "retrieved_at": retrieved.isoformat(),
        "content_hash": content_hash,
        "revision_id": revision_id,
        "branches_covered": list(spec["branches"]),
        "observations": observations,
        "raw_payload_b64": base64.b64encode(raw).decode("ascii"),
    }


def _fetch_text(url: str) -> str:
    if urlparse(url).hostname in {"pbc.gov.cn", "www.pbc.gov.cn"}:
        return fetch_pboc_text(url)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DataVendorUnavailable(
            f"official China fetch failed for {urlparse(url).hostname}: {exc}"
        ) from exc
    encoding = response.apparent_encoding or response.encoding or "utf-8"
    if encoding.casefold().replace("_", "-") in {"iso-8859-1", "ascii"}:
        encoding = "utf-8"
    response.encoding = encoding
    return response.text


def _post_json(url: str, *, params: dict[str, str]) -> Any:
    try:
        response = requests.post(
            url,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise DataVendorUnavailable(
            "MOF/ChinaBond government yield curve transport failed"
        ) from exc


def _mof_curve_request_windows(start: date, end: date) -> list[tuple[date, date]]:
    if end < start:
        raise ValueError("ChinaBond curve end_date precedes start_date")
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=364), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _mof_curve_date(value: Any) -> date:
    text = str(value or "").strip().replace("/", "-")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DataVendorUnavailable(
            "MOF/ChinaBond curve has an invalid workTime"
        ) from exc


def _mof_curve_yield(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise DataVendorUnavailable(
            f"MOF/ChinaBond curve has invalid {field} yield"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DataVendorUnavailable(
            f"MOF/ChinaBond curve has invalid {field} yield"
        ) from exc
    if not math.isfinite(parsed):
        raise DataVendorUnavailable(
            f"MOF/ChinaBond curve has invalid {field} yield"
        )
    return parsed


def fetch_mof_chinabond_government_yield_curve(
    *,
    start_date: str,
    end_date: str,
    post_json: PostJson = _post_json,
) -> dict[str, Any]:
    """Fetch the official government maturity curve in bounded date windows."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("ChinaBond curve dates must be ISO calendar dates") from exc
    rows: list[dict[str, Any]] = []
    seen_dates: set[date] = set()
    request_windows: list[dict[str, str]] = []
    response_hashes: list[str] = []
    for window_start, window_end in _mof_curve_request_windows(start, end):
        params = {
            "startDate": window_start.isoformat(),
            "endDate": window_end.isoformat(),
            "gjqx": "0",
            "locale": "cn_ZH",
            "qxmc": "1",
        }
        payload = post_json(MOF_CHINABOND_YIELD_CURVE_URL, params=params)
        if not isinstance(payload, dict) or str(payload.get("flag")) != "0":
            raise DataVendorUnavailable(
                "MOF/ChinaBond curve returned an unsuccessful response"
            )
        source_rows = payload.get("heList")
        if not isinstance(source_rows, list):
            raise DataVendorUnavailable(
                "MOF/ChinaBond curve response lacks heList"
            )
        request_windows.append(
            {
                "start_date": window_start.isoformat(),
                "end_date": window_end.isoformat(),
            }
        )
        response_hashes.append(
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        for source_row in source_rows:
            if not isinstance(source_row, dict):
                raise DataVendorUnavailable(
                    "MOF/ChinaBond curve contains a non-object row"
                )
            work_date = _mof_curve_date(source_row.get("workTime"))
            if work_date < window_start or work_date > window_end:
                raise DataVendorUnavailable(
                    "MOF/ChinaBond curve row is outside the requested window"
                )
            if work_date in seen_dates:
                raise DataVendorUnavailable(
                    "MOF/ChinaBond curve contains a duplicate work date"
                )
            missing = [
                field
                for field in MOF_CHINABOND_REQUIRED_TENORS.values()
                if source_row.get(field) in (None, "")
            ]
            if missing:
                raise DataVendorUnavailable(
                    "MOF/ChinaBond curve lacks the seven required tenors"
                )
            seen_dates.add(work_date)
            released_at = datetime.combine(
                work_date,
                time(17, 30),
                tzinfo=_SHANGHAI,
            ).isoformat()
            rows.extend(
                {
                    "trade_date": work_date.isoformat(),
                    "released_at": released_at,
                    "curve_type": "0",
                    "curve_term": tenor,
                    "yield": _mof_curve_yield(source_row[field], field),
                }
                for tenor, field in MOF_CHINABOND_REQUIRED_TENORS.items()
            )
    if not rows:
        raise DataVendorUnavailable(
            "MOF/ChinaBond curve returned no workday rows in the requested window"
        )
    return {
        "schema_version": MOF_CHINABOND_CURVE_SCHEMA_VERSION,
        "provider": "MOF_CHINABOND",
        "source_url": MOF_CHINABOND_YIELD_CURVE_URL,
        "yield_type": "MATURITY",
        "release_time": "17:30:00+08:00",
        "request_windows": request_windows,
        "response_hashes": response_hashes,
        "rows": sorted(
            rows,
            key=lambda row: (row["trade_date"], row["curve_term"]),
        ),
    }


def _catalog_candidates(
    html: str,
    *,
    catalog_url: str,
    title_pattern: str,
) -> list[tuple[datetime | None, int, str]]:
    pattern = re.compile(title_pattern, re.IGNORECASE)
    candidates: list[tuple[datetime | None, int, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(_CATALOG_LINK_RE.finditer(html)):
        title = _normalized_text(_TAG_RE.sub(" ", match.group("label")))
        if not title or pattern.search(title) is None:
            continue
        url = urljoin(catalog_url, unescape(match.group("href")))
        parsed_url = urlparse(url)
        if parsed_url.scheme == "http" and parsed_url.hostname == "gks.mof.gov.cn":
            url = "https://" + url.removeprefix("http://")
        if url in seen:
            continue
        seen.add(url)
        trailing = html[match.end() : match.end() + 240]
        date_match = _DATE_RE.search(_TAG_RE.sub(" ", trailing))
        listed_at = None
        if date_match:
            listed_at = datetime(
                int(date_match.group("year")),
                int(date_match.group("month")),
                int(date_match.group("day")),
                23,
                59,
                59,
                tzinfo=_SHANGHAI,
            )
        candidates.append((listed_at, index, url))
    return sorted(
        candidates,
        key=lambda row: (
            row[0] or datetime.min.replace(tzinfo=_SHANGHAI),
            -row[1],
        ),
        reverse=True,
    )


def fetch_latest_official_china_document(
    *,
    document_type: str,
    cutoff_at: str,
    retrieved_at: str | None = None,
    historical_replay: bool = False,
    fetch_text: FetchText = _fetch_text,
) -> dict[str, Any]:
    """Fetch the newest allowlisted release that was available by ``cutoff_at``."""
    if document_type not in OFFICIAL_CHINA_CATALOG_SPECS:
        raise ValueError(f"unknown official China document_type: {document_type!r}")
    if not isinstance(historical_replay, bool):
        raise ValueError("historical_replay must be a boolean")
    cutoff = _parse_timestamp(cutoff_at, "cutoff_at")
    retrieved_text = retrieved_at or datetime.now(timezone.utc).isoformat()
    retrieved = _parse_timestamp(retrieved_text, "retrieved_at")
    if retrieved > cutoff and not historical_replay:
        raise DataVendorUnavailable(
            "official China retrieval time exceeds the requested cutoff"
        )
    override_name = (
        "MOSAIC_OFFICIAL_CN_" + document_type.upper() + "_URL"
    )
    direct_url = os.getenv(override_name)
    if direct_url:
        result = parse_official_china_document(
            document_type=document_type,
            url=direct_url,
            html=fetch_text(direct_url),
            retrieved_at=retrieved.isoformat(),
        )
        if _parse_timestamp(result["published_at"], "published_at") > cutoff:
            raise DataVendorUnavailable(
                "configured official China release is after the requested cutoff"
            )
        return result
    catalog = OFFICIAL_CHINA_CATALOG_SPECS[document_type]
    catalog_url = catalog["catalog_url"]
    first_page = fetch_text(catalog_url)
    page_urls = [catalog_url]
    parsed_catalog = urlparse(catalog_url)
    if (
        parsed_catalog.hostname in {"stats.gov.cn", "www.stats.gov.cn"}
        and parsed_catalog.path.rstrip("/") == "/sj/zxfb"
        and (page_count := _NBS_PAGE_COUNT_RE.search(first_page)) is not None
    ):
        page_urls.extend(
            urljoin(catalog_url, f"index_{page}.html")
            for page in range(1, int(page_count.group("count")))
        )
    elif (
        parsed_catalog.hostname == "english.www.gov.cn"
        and parsed_catalog.path.rstrip("/") == "/archive/statistics"
    ):
        page_numbers = []
        for match in _CATALOG_LINK_RE.finditer(first_page):
            page_url = urljoin(catalog_url, unescape(match.group("href")))
            parsed_page = urlparse(page_url)
            page_match = _GOV_CN_STATS_PAGE_RE.fullmatch(parsed_page.path)
            if parsed_page.hostname == parsed_catalog.hostname and page_match:
                page_numbers.append(int(page_match.group("page")))
        if page_numbers:
            page_urls.extend(
                urljoin(catalog_url, f"page_{page}.html")
                for page in range(2, max(page_numbers) + 1)
            )
    for page_index, page_url in enumerate(page_urls):
        page_html = first_page if page_index == 0 else fetch_text(page_url)
        candidates = _catalog_candidates(
            page_html,
            catalog_url=page_url,
            title_pattern=catalog["title_pattern"],
        )
        for listed_at, _, url in candidates:
            if listed_at is not None and listed_at > cutoff:
                continue
            try:
                result = parse_official_china_document(
                    document_type=document_type,
                    url=url,
                    html=fetch_text(url),
                    retrieved_at=retrieved.isoformat(),
                )
            except DataVendorUnavailable:
                continue
            if _parse_timestamp(result["published_at"], "published_at") <= cutoff:
                return result
    raise DataVendorUnavailable(
        f"official China catalog has no eligible release for {document_type}"
    )


def fetch_official_china_release_set(
    *,
    cutoff_at: str,
    retrieved_at: str | None = None,
    historical_replay: bool = False,
    document_types: tuple[str, ...] | None = None,
    fetch_text: FetchText = _fetch_text,
) -> list[dict[str, Any]]:
    """Fetch one latest eligible release for every requested document contract."""
    if not isinstance(historical_replay, bool):
        raise ValueError("historical_replay must be a boolean")
    selected = document_types or tuple(sorted(OFFICIAL_CHINA_CATALOG_SPECS))
    if len(selected) != len(set(selected)):
        raise ValueError("official China document_types must be unique")
    fetched: dict[str, str] = {}

    def cached_fetch(url: str) -> str:
        if url not in fetched:
            fetched[url] = fetch_text(url)
        return fetched[url]

    return [
        fetch_latest_official_china_document(
            document_type=document_type,
            cutoff_at=cutoff_at,
            retrieved_at=retrieved_at,
            historical_replay=historical_replay,
            fetch_text=cached_fetch,
        )
        for document_type in selected
    ]


__all__ = [
    "ADAPTER_VERSION",
    "MOF_CHINABOND_CURVE_SCHEMA_VERSION",
    "MOF_CHINABOND_REQUIRED_TENORS",
    "MOF_CHINABOND_YIELD_CURVE_URL",
    "OFFICIAL_CHINA_CATALOG_SPECS",
    "OFFICIAL_CHINA_DOCUMENT_SPECS",
    "fetch_latest_official_china_document",
    "fetch_mof_chinabond_government_yield_curve",
    "fetch_official_china_release_set",
    "parse_official_china_document",
]
