from __future__ import annotations

import hashlib
import functools
import json
import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .exceptions import DataVendorUnavailable

logger = logging.getLogger(__name__)

_COMPACT_DATE_RE = re.compile(r"(?<!\d)(?P<year>19\d{2}|20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])(?!\d)")
_COMPACT_MONTH_RE = re.compile(r"(?<!\d)(?P<year>19\d{2}|20\d{2})(?P<month>0[1-9]|1[0-2])(?!\d)")
_SEPARATED_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>19\d{2}|20\d{2})[-_/](?P<month>0?[1-9]|1[0-2])[-_/](?P<day>0?[1-9]|[12]\d|3[01])(?!\d)"
)
_SEPARATED_MONTH_RE = re.compile(r"(?<!\d)(?P<year>19\d{2}|20\d{2})[-_/](?P<month>0?[1-9]|1[0-2])(?!\d)")


MACRO_AGENT_QUERY_BUNDLES: dict[str, tuple[str, ...]] = {
    "central_bank": (
        "PBOC MLF OMO liquidity",
        "央行 公开市场操作 MLF 降准",
        "FOMC Fed liquidity rates",
    ),
    "china": (
        "国务院 发改委 财政部 经济政策",
        "China growth policy property stimulus",
        "中国 PMI GDP CPI PPI 政策",
    ),
    "geopolitical": (
        "US China export controls sanctions Taiwan",
        "geopolitical risk oil supply China market",
        "中美 关税 制裁 地缘风险",
    ),
    "dollar": (
        "US dollar yuan CNH Federal Reserve",
        "人民币 汇率 美元指数 美债收益率",
        "DXY CNY capital outflow China",
    ),
    "yield_curve": (
        "China yield curve treasury bond yields",
        "US 2s10s yield curve recession signal",
        "国债收益率曲线 倒挂 流动性",
    ),
    "commodities": (
        "oil copper gold iron ore China demand",
        "原油 铜 黄金 铁矿石 中国需求",
        "commodity supply shock China futures",
    ),
    "volatility": (
        "VIX China market volatility risk off",
        "A股 波动率 风险偏好 VIX",
        "market drawdown volatility shock",
    ),
    "emerging_markets": (
        "Hong Kong stocks emerging markets China ADR",
        "港股 新兴市场 亚洲外汇 资金流",
        "EM risk appetite dollar yuan",
    ),
    "news_sentiment": (
        "财新 A股 市场情绪",
        "A股 热点 情绪 同花顺 东方财富",
        "China market sentiment retail investors",
    ),
    "institutional_flow": (
        "A股 主力资金 行业资金流",
        "龙虎榜 机构买入 ETF 份额",
        "China A-share institutional flow sector rotation",
    ),
}


def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _date_windowed_query(query: str, start_date: str, end_date: str) -> str:
    before_date = (_parse_date(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")
    return f"{query} after:{start_date} before:{before_date}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@functools.lru_cache(maxsize=1)
def _resolve_opencli_binary() -> str | None:
    """Find the first available opencli binary: opencli-rs preferred, opencli as fallback."""
    for name in ("opencli-rs", "opencli"):
        binary = shutil.which(name)
        if binary:
            return binary
    return None


def _ensure_opencli() -> str:
    binary = _resolve_opencli_binary()
    if not binary:
        raise DataVendorUnavailable("Neither opencli-rs nor opencli is installed or on PATH.")
    return binary


def _run_opencli(args: list[str]) -> list[dict]:
    binary = _ensure_opencli()
    try:
        result = subprocess.run(
            [binary, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DataVendorUnavailable(f"opencli execution failed: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise DataVendorUnavailable(f"opencli command failed: {stderr}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DataVendorUnavailable("opencli returned non-JSON output.") from exc

    if not isinstance(payload, list):
        raise DataVendorUnavailable("opencli returned an unexpected payload format.")

    return payload


def _safe_run_opencli(args: list[str]) -> tuple[list[dict], str | None]:
    try:
        return _run_opencli(args), None
    except DataVendorUnavailable as exc:
        return [], str(exc)


def _format_block(title: str, records: list[str]) -> str:
    if not records:
        return f"### {title}\nNo results."
    return f"### {title}\n" + "\n\n".join(records)


def _dedupe_records(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
    seen: set[str] = set()
    output: list[dict] = []
    for item in items:
        identity = " | ".join(str(item.get(key, "")).strip() for key in keys).strip()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        output.append(item)
    return output


def _clean_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _symbol_without_suffix(symbol: str) -> str:
    clean = _clean_symbol(symbol)
    return clean.split(".", 1)[0]


def _resolve_company_aliases(ticker: str) -> list[str]:
    aliases: list[str] = []

    try:
        from .tushare import _classify_market, _get_pro_client, _normalize_ts_code

        ts_code = _normalize_ts_code(ticker)
        market = _classify_market(ts_code)
        pro = _get_pro_client()

        if market == "a_share":
            basic = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
        elif market == "hk":
            basic = pro.hk_basic(ts_code=ts_code)
        else:
            basic = pro.us_basic(ts_code=ts_code)

        if basic is not None and not basic.empty:
            row = basic.iloc[0]
            for field in ("name", "fullname", "enname"):
                value = row.get(field)
                if value:
                    aliases.append(str(value).strip())
    except Exception:
        pass

    aliases.extend([_clean_symbol(ticker), _symbol_without_suffix(ticker)])

    expanded_aliases: list[str] = []
    for alias in aliases:
        alias = alias.strip()
        if not alias:
            continue
        expanded_aliases.append(alias)
        if alias.endswith("股份有限公司"):
            short_alias = alias[: -len("股份有限公司")].strip()
            if short_alias:
                expanded_aliases.append(short_alias)
        if alias.endswith("有限公司"):
            short_alias = alias[: -len("有限公司")].strip()
            if short_alias:
                expanded_aliases.append(short_alias)

    seen: set[str] = set()
    result: list[str] = []
    for alias in expanded_aliases:
        if alias not in seen:
            seen.add(alias)
            result.append(alias)
    return result


def _build_google_queries(ticker: str) -> list[str]:
    aliases = _resolve_company_aliases(ticker)
    queries: list[str] = []
    for alias in aliases:
        queries.append(f"{alias} stock")
        queries.append(alias)
    return queries


def _collect_google_news(ticker: str, limit: int = 8) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []

    for query in _build_google_queries(ticker):
        payload, error = _safe_run_opencli(
            ["google", "news", query, "--limit", str(limit), "--format", "json"]
        )
        if error:
            errors.append(f"{query}: {error}")
            continue
        items.extend(payload)
        if len(_dedupe_records(items, ("url", "title"))) >= limit:
            break

    return _dedupe_records(items, ("url", "title"))[:limit], errors


def _collect_google_search_results(ticker: str, limit: int = 8) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []

    for query in _build_google_queries(ticker):
        payload, error = _safe_run_opencli(
            ["google", "search", query, "--lang", "zh", "--limit", str(limit), "--format", "json"]
        )
        if error:
            errors.append(f"{query}: {error}")
            continue
        items.extend(payload)
        if len(_dedupe_records(items, ("url", "title"))) >= limit:
            break

    return _dedupe_records(items, ("url", "title"))[:limit], errors


def _collect_xueqiu_results(ticker: str, limit: int = 8) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []

    for keyword in _resolve_company_aliases(ticker):
        payload, error = _safe_run_opencli(
            ["xueqiu", "search", keyword, "--limit", str(limit), "--format", "json"]
        )
        if error:
            errors.append(f"{keyword}: {error}")
            continue
        items.extend(payload)
        if len(_dedupe_records(items, ("symbol", "name"))) >= limit:
            break

    return _dedupe_records(items, ("symbol", "name"))[:limit], errors


def _collect_weibo_results(ticker: str, limit: int = 8) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []

    for keyword in _resolve_company_aliases(ticker):
        payload, error = _safe_run_opencli(
            ["weibo", "search", keyword, "--limit", str(limit), "--format", "json"]
        )
        if error:
            errors.append(f"{keyword}: {error}")
            continue
        items.extend(payload)
        if len(_dedupe_records(items, ("url", "text", "word"))) >= limit:
            break

    return _dedupe_records(items, ("url", "text", "word"))[:limit], errors


def _collect_xiaohongshu_results(ticker: str, limit: int = 8) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []

    for keyword in _resolve_company_aliases(ticker):
        payload, error = _safe_run_opencli(
            ["xiaohongshu", "search", keyword, "--limit", str(limit), "--format", "json"]
        )
        if error:
            errors.append(f"{keyword}: {error}")
            continue
        items.extend(payload)
        if len(_dedupe_records(items, ("id", "note_id", "url", "title"))) >= limit:
            break

    return _dedupe_records(items, ("id", "note_id", "url", "title"))[:limit], errors


def _collect_sinafinance_results(ticker: str, limit: int = 8) -> tuple[list[dict], list[str]]:
    aliases = _resolve_company_aliases(ticker)
    payload, error = _safe_run_opencli(
        ["sinafinance", "news", "--type", "1", "--limit", "50", "--format", "json"]
    )
    if error:
        return [], [error]

    filtered: list[dict] = []
    for item in payload:
        haystack = " ".join(
            str(item.get(field, "")).strip()
            for field in ("content", "title", "symbol", "name")
        )
        if any(alias and alias in haystack for alias in aliases):
            filtered.append(item)

    return _dedupe_records(filtered, ("time", "content", "title"))[:limit], []


def _date_cutoff_warning(end_date: str) -> str:
    return (
        f"⚠️ 数据说明：以下新闻数据从实时数据源获取，结果可能包含 {end_date} 之后发布的内容。"
        f"分析时请严格仅参考 {end_date} 及之前发生的事件，忽略任何在此日期之后的信息。\n\n"
    )


def _filter_by_date(items: list[dict], end_date: str) -> list[dict]:
    """过滤掉发布日期晚于 end_date 的条目（仅适用于有 date 字段的来源）。"""
    end_dt = _parse_date(end_date)
    filtered = []
    for item in items:
        raw = item.get("date", "")
        if not raw:
            filtered.append(item)
            continue
        try:
            # Google News 常见格式: "2026-03-12" 或 "Mar 12, 2026"
            for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
                try:
                    item_dt = datetime.strptime(raw[:len(fmt) + 2].strip(), fmt)
                    break
                except ValueError:
                    continue
            else:
                filtered.append(item)
                continue
            if item_dt <= end_dt:
                filtered.append(item)
        except Exception:
            filtered.append(item)
    return filtered


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    _parse_date(start_date)
    _parse_date(end_date)

    sections: list[str] = []
    errors: list[str] = []

    xueqiu_items, xueqiu_errors = _collect_xueqiu_results(ticker, limit=6)
    errors.extend(xueqiu_errors)
    if xueqiu_items:
        sections.append(
            _format_block(
                "Xueqiu Search",
                [
                    (
                        f"- {item.get('name', item.get('symbol', 'Unknown'))} "
                        f"(symbol: {item.get('symbol', 'Unknown')})"
                    )
                    for item in xueqiu_items
                ],
            )
        )

    weibo_items, weibo_errors = _collect_weibo_results(ticker, limit=6)
    errors.extend(weibo_errors)
    if weibo_items:
        sections.append(
            _format_block(
                "Weibo Search",
                [
                    (
                        f"- {item.get('text', item.get('word', 'No text'))}\n"
                        f"  Link: {item.get('url', '')}"
                    )
                    for item in weibo_items
                ],
            )
        )

    xiaohongshu_items, xiaohongshu_errors = _collect_xiaohongshu_results(ticker, limit=6)
    errors.extend(xiaohongshu_errors)
    if xiaohongshu_items:
        sections.append(
            _format_block(
                "Xiaohongshu Search",
                [
                    (
                        f"- {item.get('title', item.get('desc', 'No title'))}\n"
                        f"  Link: {item.get('url', '')}"
                    )
                    for item in xiaohongshu_items
                ],
            )
        )

    sina_items, sina_errors = _collect_sinafinance_results(ticker, limit=6)
    errors.extend(sina_errors)
    if sina_items:
        sections.append(
            _format_block(
                "Sina Finance A-Share Flash",
                [
                    (
                        f"- {item.get('content', item.get('title', 'No content'))} "
                        f"(time: {item.get('time', 'Unknown')}, views: {item.get('views', 'Unknown')})"
                    )
                    for item in sina_items
                ],
            )
        )

    google_news_items, google_news_errors = _collect_google_news(ticker, limit=10)
    errors.extend(google_news_errors)
    google_news_items = _filter_by_date(google_news_items, end_date)
    if google_news_items:
        sections.append(
            _format_block(
                "Google News",
                [
                    (
                        f"- {item.get('title', 'No title')} "
                        f"(source: {item.get('source', 'Unknown')}, date: {item.get('date', 'Unknown')})\n"
                        f"  Link: {item.get('url', '')}"
                    )
                    for item in google_news_items
                ],
            )
        )

    google_search_items, google_search_errors = _collect_google_search_results(ticker, limit=6)
    errors.extend(google_search_errors)
    if google_search_items:
        sections.append(
            _format_block(
                "Google Search (ZH)",
                [
                    (
                        f"- {item.get('title', 'No title')}\n"
                        f"  Link: {item.get('url', '')}"
                    )
                    for item in google_search_items
                ],
            )
        )

    if not sections:
        aliases = ", ".join(_resolve_company_aliases(ticker))
        detail = (
            f"No relevant news found via opencli-rs for {ticker} "
            f"between {start_date} and {end_date}. "
            f"Queries tried: {aliases or ticker}."
        )
        if errors:
            detail += f" Source errors: {'; '.join(errors[:3])}."
        return detail

    header = f"## {ticker} News and Social Signals, from {start_date} to {end_date}:\n\n"
    return _date_cutoff_warning(end_date) + header + "\n\n".join(sections)


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 10) -> str:
    end_dt = _parse_date(curr_date)
    start_date = (end_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    sections = []

    google_items = _filter_by_date(
        _run_opencli(["google", "news", "--limit", str(limit * 2), "--format", "json"]),
        curr_date,
    )
    sections.append(
        _format_block(
            "Google News Top Stories",
            [
                (
                    f"- {item.get('title', 'No title')} "
                    f"(source: {item.get('source', 'Unknown')}, date: {item.get('date', 'Unknown')})\n"
                    f"  Link: {item.get('url', '')}"
                )
                for item in google_items[:limit]
            ],
        )
    )

    sina_items = _run_opencli(["sinafinance", "news", "--limit", str(limit), "--format", "json"])
    sections.append(
        _format_block(
            "Sina Finance Flash News",
            [
                (
                    f"- {item.get('content', 'No content')} "
                    f"(time: {item.get('time', 'Unknown')}, views: {item.get('views', 'Unknown')})"
                )
                for item in sina_items[:limit]
            ],
        )
    )

    xueqiu_hot = _run_opencli(["xueqiu", "hot", "--limit", str(min(limit, 8)), "--format", "json"])
    sections.append(
        _format_block(
            "Xueqiu Hot Discussions",
            [
                (
                    f"- {item.get('text', 'No text')} "
                    f"(author: {item.get('author', 'Unknown')}, likes: {item.get('likes', 'Unknown')})\n"
                    f"  Link: {item.get('url', '')}"
                )
                for item in xueqiu_hot[:limit]
            ],
        )
    )

    weibo_hot = _run_opencli(["weibo", "hot", "--limit", str(min(limit, 8)), "--format", "json"])
    sections.append(
        _format_block(
            "Weibo Hot Topics",
            [
                (
                    f"- {item.get('word', 'No topic')} "
                    f"(category: {item.get('category', 'Unknown')}, heat: {item.get('hot_value', 'Unknown')})\n"
                    f"  Link: {item.get('url', '')}"
                )
                for item in weibo_hot[:limit]
            ],
        )
    )

    header = f"## Global Market News and Social Signals, from {start_date} to {curr_date}:\n\n"
    return _date_cutoff_warning(curr_date) + header + "\n\n".join(sections)


def get_news_for_queries(
    queries: list[str],
    start_date: str,
    end_date: str,
    *,
    per_query_limit: int = 6,
    max_workers: int = 4,
) -> str:
    """Fetch news for multiple search queries in parallel and combine results.

    Each query runs ``get_news`` independently via a thread pool. Results are
    concatenated with clear query labels. If some queries fail, the others
    still contribute — the caller always gets a usable string.
    """
    if not queries:
        return "<no search queries provided>"

    _parse_date(start_date)
    _parse_date(end_date)

    results: dict[str, str] = {}
    errors: list[str] = []

    def _fetch(query: str) -> tuple[str, str]:
        try:
            return query, get_news(query, start_date, end_date)
        except Exception as exc:
            logger.warning("get_news_for_queries: query %r failed: %s", query, exc)
            return query, ""

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch, q): q for q in queries[:max_workers * 2]}
        for future in as_completed(futures):
            query, text = future.result()
            if text and not text.startswith("No relevant news found"):
                results[query] = text
            else:
                errors.append(query)

    if not results:
        detail = f"No relevant news found for any of: {', '.join(queries)}."
        if errors:
            detail += f" Failed queries: {', '.join(errors)}."
        return detail

    blocks = []
    for query, text in results.items():
        blocks.append(f"#### Search: {query}\n\n{text}")

    return "\n\n".join(blocks)


# Caixin (财新) is a high-signal A-share financial outlet; these queries pull
# its recent coverage as a market-sentiment proxy (Plan §5.1 news_sentiment).
_CAIXIN_QUERIES = ("财新 市场情绪", "财新 A股", "财新 经济")


def get_caixin_sentiment(curr_date: str, look_back_days: int = 7, limit: int = 10) -> str:
    """Caixin (财新) news/sentiment over a window via opencli (Plan §5.1).

    Window = ``[curr_date - look_back_days, curr_date]``. Runs a small set of
    Caixin-focused Google News + Search (zh) queries through opencli, date-
    filters to the window end, and returns a markdown block. Used by
    ``news_sentiment`` as a quality-press counterweight to retail Xueqiu heat.
    """
    end_dt = _parse_date(curr_date)
    start_date = (end_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    items: list[dict] = []
    errors: list[str] = []
    for query in _CAIXIN_QUERIES:
        news, err = _safe_run_opencli(
            ["google", "news", query, "--limit", str(limit), "--format", "json"]
        )
        if err:
            errors.append(f"{query}: {err}")
        else:
            items.extend(news)
        search, err2 = _safe_run_opencli(
            ["google", "search", query, "--lang", "zh", "--limit", str(limit), "--format", "json"]
        )
        if err2:
            errors.append(f"{query}: {err2}")
        else:
            items.extend(search)

    items = _filter_by_date(_dedupe_records(items, ("url", "title")), curr_date)

    if not items:
        detail = (
            f"No Caixin (财新) coverage found via opencli between {start_date} "
            f"and {curr_date}."
        )
        if errors:
            detail += f" Source errors: {'; '.join(errors[:3])}."
        return detail

    block = _format_block(
        "Caixin / 财新 Coverage",
        [
            (
                f"- {it.get('title', 'No title')} "
                f"(source: {it.get('source', 'Unknown')}, date: {it.get('date', 'Unknown')})\n"
                f"  Link: {it.get('url', '')}"
            )
            for it in items[:limit]
        ],
    )
    header = f"## 财新情绪 / Caixin Sentiment, {start_date} → {curr_date}:\n\n"
    return _date_cutoff_warning(curr_date) + header + block


def _parse_loose_date(value: str) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(raw[: max(len(raw), len(fmt))], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _date_from_match(match: re.Match[str], *, default_day: int | None = None) -> datetime | None:
    try:
        day = int(match.groupdict().get("day") or default_day or 1)
        return datetime(int(match.group("year")), int(match.group("month")), day)
    except ValueError:
        return None


def _infer_date_from_text(value: str) -> datetime | None:
    if not value:
        return None
    for regex, default_day in (
        (_SEPARATED_DATE_RE, None),
        (_COMPACT_DATE_RE, None),
        (_SEPARATED_MONTH_RE, 1),
        (_COMPACT_MONTH_RE, 1),
    ):
        match = regex.search(value)
        if match:
            parsed = _date_from_match(match, default_day=default_day)
            if parsed is not None:
                return parsed
    return None


def _extract_item_date(item: dict) -> datetime | None:
    raw = item.get("date") or item.get("datetime") or item.get("time") or item.get("published_at")
    parsed = _parse_loose_date(str(raw)) if raw else None
    if parsed is not None:
        return parsed
    for key in ("url", "title", "snippet", "desc", "content"):
        parsed = _infer_date_from_text(str(item.get(key) or ""))
        if parsed is not None:
            return parsed
    return None


def _filter_items_by_window(
    items: list[dict],
    start_date: str,
    end_date: str,
    *,
    keep_undated: bool = False,
) -> list[dict]:
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    out: list[dict] = []
    for item in items:
        parsed = _extract_item_date(item)
        if parsed is None:
            if keep_undated:
                out.append(item)
            continue
        naive = parsed.replace(tzinfo=None)
        if start_dt <= naive <= end_dt:
            out.append(item)
    return out


def _macro_document_hash(*parts: str) -> str:
    material = "\n".join(part.strip() for part in parts if part and part.strip())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _normalise_macro_document(
    *,
    item: dict,
    agent: str,
    query: str,
    source: str,
    channel: str,
    discovered_at: str,
) -> dict:
    title = str(item.get("title") or item.get("text") or item.get("word") or item.get("content") or "").strip()
    url = str(item.get("url") or item.get("link") or "").strip()
    published_at = str(
        item.get("date") or item.get("datetime") or item.get("time") or item.get("published_at") or ""
    ).strip() or None
    excerpt = str(item.get("content") or item.get("snippet") or item.get("desc") or title or "").strip()
    content_hash = _macro_document_hash(source, channel, query, title, url, published_at or "", excerpt)
    return {
        "document_id": content_hash,
        "source": source,
        "channel": channel,
        "query": query,
        "title": title or None,
        "url": url or None,
        "published_at": published_at,
        "discovered_at": discovered_at,
        "content_hash": content_hash,
        "content_excerpt": excerpt[:1000] if excerpt else None,
        "agent_tags": [agent],
        "event_tags": [],
        "sentiment_score": None,
        "quality_score": 1.0 if published_at else 0.5,
    }


def collect_macro_documents(
    curr_date: str,
    look_back_days: int = 7,
    *,
    agents: list[str] | None = None,
    per_query_limit: int = 5,
    discovered_at: str | None = None,
) -> list[dict]:
    """Collect date-bounded OpenCLI documents for macro agents.

    This function only collects and normalises evidence. Historical scoring
    should read rows already persisted via ``macro_documents`` rather than call
    OpenCLI in the scoring path.
    """
    end_dt = _parse_date(curr_date)
    start_date = (end_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    selected_agents = agents or sorted(MACRO_AGENT_QUERY_BUNDLES)
    discovered_at = discovered_at or _now_iso()
    docs: list[dict] = []
    seen: set[str] = set()
    for agent in selected_agents:
        for query in MACRO_AGENT_QUERY_BUNDLES.get(agent, ()):
            dated_query = _date_windowed_query(query, start_date, curr_date)
            calls = (
                ("google_news", ["google", "news", dated_query, "--limit", str(per_query_limit), "--format", "json"]),
                ("google_search_zh", ["google", "search", dated_query, "--lang", "zh", "--limit", str(per_query_limit), "--format", "json"]),
            )
            for channel, args in calls:
                items, error = _safe_run_opencli(args)
                if error:
                    logger.debug("macro OpenCLI collection failed for %s/%s: %s", agent, query, error)
                    continue
                for item in _filter_items_by_window(items, start_date, curr_date):
                    row = _normalise_macro_document(
                        item=item,
                        agent=agent,
                        query=query,
                        source="opencli",
                        channel=channel,
                        discovered_at=discovered_at,
                    )
                    if row["content_hash"] in seen:
                        continue
                    seen.add(row["content_hash"])
                    docs.append(row)
    return docs


def persist_macro_documents(store, curr_date: str, look_back_days: int = 7, **kwargs) -> int:
    docs = collect_macro_documents(curr_date, look_back_days, **kwargs)
    return store.append_macro_documents(docs) if docs else 0
