"""Deterministic candidate claims for the RKE gold-set review queue.

These rows are not accepted labels. They are source-bound proposals that make
manual C02 review auditable and faster while keeping the manual gate closed
until reviewers fill the review fields.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .claim_vocabulary import load_claim_variable_vocabulary
from .phase_minus1 import load_jsonl_with_errors
from .review_integrity import license_review_row_complete


GOLD_CANDIDATE_CLAIMS_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"
GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
GOLD_CANDIDATES_PATH = "registry/sources/tushare_research_reports.gold_candidates.jsonl"
GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"
REPORT_FORECAST_CLAIMS_PATH = "registry/report_intelligence/forecast_claims.jsonl"
REPORT_METADATA_PATH = "registry/report_intelligence/report_metadata.jsonl"
SOURCE_LICENSE_REVIEW_TEMPLATE_PATH = "registry/compliance/tushare_license_review_template.jsonl"

MECHANISM_KEYWORDS = (
    "政策",
    "流动性",
    "需求",
    "供给",
    "价格",
    "订单",
    "盈利",
    "估值",
    "国产",
    "替代",
    "出口",
    "限制",
    "利率",
    "资金",
    "景气",
    "增长",
    "下降",
    "提升",
    "改善",
    "风险",
    "催化",
    "复苏",
    "承压",
    "修复",
    "技术",
    "补能",
    "库存",
    "利差",
    "信贷",
    "渠道",
)
NEGATIVE_TERMS = ("下降", "承压", "风险", "压力", "下滑", "回落", "限制", "恶化")
POSITIVE_TERMS = ("增长", "提升", "改善", "修复", "复苏", "景气", "盈利", "需求", "订单", "催化")
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]{12,260}[。！？!?；;]?")
RISK_WARNING_PREFIX_RE = re.compile(
    r"^\s*(?:风险提示|风险因素|风险声明|免责声明)\s*[:：]"
)
GENERIC_RISK_ENUM_RE = re.compile(
    r"^\s*(?:\d+[、.)）]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.)）])?\s*"
    r".{0,24}(?:不及预期|低于预期|超预期变化|大盘系统性风险|业绩不达预期|数据误差|竞争加剧|客户依赖|政策落地)"
    r"(?:.*风险)?\s*[。；;]?\s*$"
)
CLAIM_MECHANISM_TERMS = (
    "预计",
    "预期",
    "有望",
    "未来",
    "后续",
    "长期",
    "短期",
    "中期",
    "看好",
    "维持",
    "建议",
    "上调",
    "下调",
    "优于",
    "跑赢",
    "跑输",
    "超配",
    "低配",
    "增持",
    "减持",
    "驱动",
    "推动",
    "带动",
    "导致",
    "受益",
    "压制",
    "制约",
    "改善",
    "修复",
    "恶化",
    "承压",
    "风险",
    "压力",
    "催化",
    "拐点",
    "弹性",
    "传导",
    "供需",
    "库存",
    "产能",
    "景气",
    "周期",
    "格局",
    "regime",
    "outperform",
    "underperform",
)
DESCRIPTIVE_ONLY_TERMS = (
    "涨跌幅",
    "区间涨幅",
    "区间跌幅",
    "年初至",
    "当前",
    "截至",
    "分别为",
    "最高",
    "其次",
    "排在",
    "排名",
    "环比",
    "同比",
    "ROE",
    "毛利率",
    "净利率",
    "资产负债率",
    "研发比例",
    "存量规模",
    "价格为",
    "涨跌不一",
    "规模",
)
MANUAL_REVIEW_FIELDS = (
    "manual_claim_text",
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "target_correct",
    "horizon_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
    "reviewer",
    "review_notes",
)


@dataclass(frozen=True)
class GoldCandidateClaim:
    claim_id: str
    source_id: str
    source_span_id: str
    gold_set_domain: str
    gold_set_domains: Sequence[str]
    source_span_ref_id: str
    source_start_char: int
    source_end_char: int
    source_text_hash: str
    candidate_available: bool
    claim_type: str
    claim_text: str
    cause_variables: Sequence[str]
    target_variables: Sequence[str]
    direction: str
    unsupported_fields: Sequence[str]
    verifier_status: str
    extraction_confidence_bin: str
    review_risk_flags: Sequence[str]


@dataclass(frozen=True)
class GoldCandidateClaimSummary:
    summary_id: str
    candidate_claim_path: str
    review_path: str
    candidate_claim_count: int
    candidate_available_count: int
    missing_variable_mapping_count: int
    domain_counts: Mapping[str, int]
    direction_counts: Mapping[str, int]
    claim_type_counts: Mapping[str, int]
    risk_flag_counts: Mapping[str, int]
    review_rows_with_candidate_fields: int
    manual_fields_preserved: bool
    blockers: Sequence[str]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "rows": 1}


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"path": str(path), "rows": len(rows)}


def _split_mapping_rows(rows: Sequence[Any]) -> tuple[list[Mapping[str, Any]], tuple[int, ...]]:
    valid_rows: list[Mapping[str, Any]] = []
    invalid_row_numbers: list[int] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, Mapping):
            valid_rows.append(row)
        else:
            invalid_row_numbers.append(index)
    return valid_rows, tuple(invalid_row_numbers)


def _malformed_row_blocker(label: str, row_numbers: Sequence[int]) -> str:
    return f"{label} row must be object at row(s): " + ", ".join(str(row_number) for row_number in row_numbers)


def _short_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()[:16]


def _is_boilerplate_risk_warning(text: str) -> bool:
    stripped = text.strip()
    return bool(RISK_WARNING_PREFIX_RE.match(stripped) or GENERIC_RISK_ENUM_RE.match(stripped))


def _claim_sentence_score(sentence: str, keywords: Sequence[str]) -> int | None:
    text = sentence.strip()
    if not text or _is_boilerplate_risk_warning(text):
        return None
    mechanism_hits = sum(1 for term in CLAIM_MECHANISM_TERMS if term in text)
    descriptive_hits = sum(1 for term in DESCRIPTIVE_ONLY_TERMS if term in text)
    numeric_heavy = len(re.findall(r"\d+(?:\.\d+)?%?", text)) >= 3
    has_source_relation = any(token in text for token in ("因为", "由于", "若", "如果", "随着", "在", "当", "使得"))
    has_mechanism = mechanism_hits > 0 or has_source_relation
    if not has_mechanism and (descriptive_hits or numeric_heavy):
        return None
    if mechanism_hits == 0 and len(keywords) < 2:
        return None
    score = mechanism_hits * 4 + len(keywords)
    if has_source_relation:
        score += 2
    if descriptive_hits:
        score -= descriptive_hits * 3
    if numeric_heavy:
        score -= 4
    return score if score > 0 else None


def _string_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = (value,)
    return tuple(text for item in items if (text := str(item).strip()))


def _review_rows_by_source(review_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in review_rows:
        source_id = str(row.get("source_id") or row.get("document_id") or "")
        if source_id:
            grouped.setdefault(source_id, []).append(row)
    return grouped


def _source_sentences(text: str) -> list[tuple[int, int, str, tuple[str, ...]]]:
    scored: list[tuple[int, int, int, str, tuple[str, ...]]] = []
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        keywords = tuple(keyword for keyword in MECHANISM_KEYWORDS if keyword in sentence)
        score = _claim_sentence_score(sentence, keywords)
        if score is None:
            continue
        scored.append((score, match.start(), match.end(), sentence, keywords))
    return [
        (start, end, sentence, keywords)
        for _, start, end, sentence, keywords in sorted(
            scored,
            key=lambda row: (-row[0], row[1]),
        )
    ]


def _claim_type(sentence: str, keywords: Sequence[str]) -> str:
    if any(term in sentence for term in NEGATIVE_TERMS):
        return "failure_or_constraint"
    if any(keyword in sentence for keyword in ("估值", "价格", "盈利", "利差")):
        return "valuation_or_fundamental_link"
    if keywords:
        return "causal_mechanism"
    return "source_context_requires_review"


def _direction(sentence: str) -> str:
    has_positive = any(term in sentence for term in POSITIVE_TERMS)
    has_negative = any(term in sentence for term in NEGATIVE_TERMS)
    if has_positive and not has_negative:
        return "positive"
    if has_negative and not has_positive:
        return "negative"
    if has_positive and has_negative:
        return "ambiguous"
    return "neutral"


def _append_known(target: list[str], variable_id: str, known_variable_ids: set[str]) -> None:
    if variable_id in known_variable_ids and variable_id not in target:
        target.append(variable_id)


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _stock_like_identifier(value: str) -> bool:
    return bool(re.search(r"\b(?:00|30|60|68|90|92)\d{4}\.(?:SZ|SH|BJ)\b", value))


def _variable_pair(
    sentence: str,
    *,
    query_key: str,
    industry: str,
    ts_code: str,
    known_variable_ids: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    text = sentence
    text_lower = text.lower()
    cause: list[str] = []
    target: list[str] = []
    flags: list[str] = []

    if any(keyword in text for keyword in ("半导体", "芯片", "存储", "AI", "算力", "国产", "替代")):
        if any(keyword in text for keyword in ("AI", "算力", "存储", "数据中心")):
            _append_known(cause, "ai_compute_demand", known_variable_ids)
            _append_known(target, "semiconductor_storage_cycle", known_variable_ids)
        if any(keyword in text for keyword in ("国产", "替代", "政策", "出口", "限制")):
            _append_known(cause, "trade_friction_intensity", known_variable_ids)
            _append_known(target, "semiconductor_policy_substitution_alpha", known_variable_ids)
    if any(keyword in text for keyword in ("电池", "宁德", "300750", "补能", "充电", "储能")):
        if any(keyword in text for keyword in ("技术", "迭代", "电池", "能量密度", "充电")):
            _append_known(cause, "ev_battery_technology_iteration", known_variable_ids)
        if any(keyword in text for keyword in ("补能", "换电", "充电", "需求")):
            _append_known(cause, "ev_charging_ecosystem_demand", known_variable_ids)
        _append_known(target, "battery_profitability_expectation", known_variable_ids)
    if any(keyword in text for keyword in ("600519", "茅台", "白酒", "渠道", "库存", "消费")):
        _append_known(cause, "liquor_demand_recovery", known_variable_ids)
        _append_known(target, "consumer_leader_profitability_expectation", known_variable_ids)
    if any(keyword in text for keyword in ("银行", "信贷", "利差", "净息差", "流动性", "央行")):
        if any(keyword in text for keyword in ("流动性", "央行", "利率", "资金")):
            _append_known(cause, "pboc_net_injection", known_variable_ids)
            _append_known(target, "short_term_liquidity_pressure", known_variable_ids)
        _append_known(cause, "bank_credit_supply", known_variable_ids)
        _append_known(target, "bank_net_interest_margin_pressure", known_variable_ids)
    if any(keyword in text for keyword in ("利率债", "收益率", "资金面", "短端", "长端利率", "债券市场")):
        _append_known(cause, "pboc_net_injection", known_variable_ids)
        _append_known(target, "short_term_liquidity_pressure", known_variable_ids)
    if any(keyword in text for keyword in ("估值", "PE", "PB", "分位")):
        _append_known(cause, "valuation_percentile", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "上涨",
            "下跌",
            "涨幅",
            "跌幅",
            "跑输",
            "跑赢",
            "领先",
            "落后",
            "排名",
            "指数表现",
            "累计上涨",
            "累计下跌",
            "环比",
            "同比",
            "pct",
        )
    ):
        _append_known(cause, "recent_price_momentum", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "技术",
            "创新",
            "模型",
            "芯片",
            "产品",
            "功能",
            "升级",
            "研发",
            "工艺",
            "架构",
            "制程",
            "封装",
            "IPO",
            "Agent",
            "灰测",
            "试商用",
            "tech",
            "technology",
            "model",
            "product",
            "innovation",
        )
    ):
        _append_known(cause, "technology_innovation_cycle", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "毛利",
            "净利",
            "归母",
            "ROE",
            "收入",
            "营收",
            "利润",
            "现金流",
            "出租率",
            "融资成本",
            "资本开支",
            "客流",
            "费用",
            "资产负债",
            "订单",
            "revenue",
            "profit",
            "margin",
            "cash flow",
            "capex",
        )
    ):
        _append_known(cause, "company_fundamental_momentum", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "竞争",
            "风险",
            "低于预期",
            "不及预期",
            "放缓",
            "下行",
            "压力",
            "承压",
            "亏损",
            "封锁",
            "危机",
            "冲突",
            "管制",
            "competition",
            "risk",
            "pressure",
        )
    ):
        _append_known(cause, "competitive_intensity_pressure", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "政策",
            "监管",
            "财政",
            "补贴",
            "基建",
            "更新",
            "国产替代",
            "供给侧",
            "改革",
            "challenge mode",
            "budget",
        )
    ):
        _append_known(cause, "industry_policy_catalyst", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "需求",
            "订单",
            "装机",
            "市场规模",
            "增长",
            "复苏",
            "景气",
            "出货",
            "收入",
            "营收",
            "利润",
            "盈利",
            "cagr",
            "market size",
            "revenue",
            "shipment",
            "growth",
        )
    ):
        _append_known(cause, "industry_demand_cycle", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "供给",
            "产能",
            "库存",
            "短缺",
            "瓶颈",
            "紧平衡",
            "缺口",
            "限产",
            "出口",
            "封锁",
            "管制",
            "capacity",
            "inventory",
            "shortage",
            "supply",
        )
    ):
        _append_known(cause, "industry_supply_constraint", known_variable_ids)
    if any(
        keyword in text
        for keyword in (
            "铜",
            "铝",
            "锂",
            "钴",
            "镍",
            "锌",
            "铅",
            "金",
            "银",
            "稀土",
            "钨",
            "锑",
            "商品",
            "大宗",
            "价格",
            "commodity",
            "gold",
            "copper",
            "aluminum",
            "lithium",
        )
    ):
        _append_known(cause, "commodity_price_cycle", known_variable_ids)
    if any(
        keyword in text_lower
        for keyword in (
            "美元",
            "汇率",
            "美联储",
            "fed",
            "dollar",
            "usd",
            "fx",
            "pce",
            "tips",
            "treasury",
        )
    ):
        _append_known(cause, "global_dollar_liquidity_pressure", known_variable_ids)

    stock_like = _stock_like_identifier(query_key) or _stock_like_identifier(ts_code)
    has_target_view = _contains_any(
        text,
        (
            "看好",
            "增持",
            "买入",
            "上调",
            "下调",
            "跑赢",
            "跑输",
            "优于",
            "强于",
            "弱于",
            "未来",
            "后续",
            "有望",
            "预期",
            "预计",
            "目标价",
            "上涨",
            "下跌",
            "改善",
            "修复",
            "承压",
            "盈利",
            "利润",
            "估值",
        ),
    )
    if stock_like and (cause or has_target_view):
        _append_known(target, "stock_forward_excess_return", known_variable_ids)
    elif any(
        keyword in text
        for keyword in (
            "行业",
            "指数",
            "ETF",
            "板块",
            "主题",
            "景气",
            "市场基准",
            "沪深300",
            "优于市场",
            "强于大市",
            "看好",
            "增持",
            "跑赢",
            "跑输",
            "后续",
            "未来",
            "有望",
            "预期",
            "预计",
        )
    ) or any(keyword in text_lower for keyword in ("industry", "sector", "market benchmark", "outperform")):
        _append_known(target, "industry_etf_forward_return", known_variable_ids)
    elif cause and _contains_any(text, ("政策", "催化", "流动性", "风险偏好", "市场", "指数")):
        _append_known(target, "forward_alpha_after_policy_catalyst", known_variable_ids)

    if not cause or not target:
        flags.append("canonical_variable_mapping_needed")
    return tuple(cause), tuple(target), tuple(flags)


def _candidate_claim_for_review_row(
    candidate: Mapping[str, Any],
    review_row: Mapping[str, Any],
    sentence_rows: Sequence[tuple[int, int, str, tuple[str, ...]]],
    row_index: int,
    known_variable_ids: set[str],
    approved_license_source_ids: set[str],
    source_span_id_override: str | None = None,
    extra_risk_flags: Sequence[str] = (),
) -> GoldCandidateClaim:
    source_id = str(candidate.get("source_id") or review_row.get("source_id") or "")
    source_span_id = str(
        source_span_id_override
        or candidate.get("source_span_id")
        or review_row.get("source_span_id")
        or f"{source_id}:abstract"
    )
    if sentence_rows:
        start_char, end_char, sentence, keywords = sentence_rows[row_index % len(sentence_rows)]
        candidate_available = True
    else:
        sentence = "Candidate extraction did not find a source-grounded mechanism sentence; manual claim required."
        start_char = 0
        end_char = 0
        keywords = ()
        candidate_available = False

    cause_variables, target_variables, variable_flags = _variable_pair(
        sentence,
        query_key=str(candidate.get("query_key") or ""),
        industry=str(candidate.get("industry") or ""),
        ts_code=str(candidate.get("ts_code") or ""),
        known_variable_ids=known_variable_ids,
    )
    risk_flags = [
        "manual_review_required",
        "sentence_fallback_requires_context_synthesis",
        *extra_risk_flags,
        *variable_flags,
    ]
    if not candidate_available:
        risk_flags.append("candidate_unavailable")
    if not keywords:
        risk_flags.append("low_mechanism_keyword_support")
    if source_id not in approved_license_source_ids and str(candidate.get("license_status") or "") != "approved":
        risk_flags.append("license_pending")
    if len(sentence) > 220:
        risk_flags.append("long_candidate_sentence")

    claim_type = _claim_type(sentence, keywords)
    direction = _direction(sentence)
    return GoldCandidateClaim(
        claim_id=str(review_row.get("claim_id") or f"GOLD-{source_id}-{row_index + 1:03d}"),
        source_id=source_id,
        source_span_id=source_span_id,
        gold_set_domain=str(
            review_row.get("gold_set_domain") or candidate.get("gold_set_domain") or "other"
        ),
        gold_set_domains=tuple(
            review_row.get("gold_set_domains") or candidate.get("gold_set_domains") or ("other",)
        ),
        source_span_ref_id=f"{source_span_id}:candidate-{row_index + 1:02d}",
        source_start_char=start_char,
        source_end_char=end_char,
        source_text_hash=_short_hash(sentence),
        candidate_available=candidate_available,
        claim_type=claim_type,
        claim_text=sentence,
        cause_variables=cause_variables,
        target_variables=target_variables,
        direction=direction,
        unsupported_fields=("failure_modes", "valid_conditions"),
        verifier_status="requires_review",
        extraction_confidence_bin="low",
        review_risk_flags=tuple(dict.fromkeys(risk_flags)),
    )


def _source_report_claims(
    root_path: Path,
) -> tuple[dict[str, list[Mapping[str, Any]]], tuple[str, ...]]:
    path = root_path / REPORT_FORECAST_CLAIMS_PATH
    if not path.exists():
        return {}, ()
    raw_rows, parse_blockers = load_jsonl_with_errors(
        path,
        label="report-intelligence forecast claim",
    )
    rows, invalid_rows = _split_mapping_rows(raw_rows)
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        source_id = str(row.get("source_id") or "")
        claim_text = str(row.get("claim_text") or "").strip()
        if _is_boilerplate_risk_warning(claim_text):
            continue
        if source_id and claim_text:
            grouped.setdefault(source_id, []).append(row)
    blockers = list(parse_blockers)
    if invalid_rows:
        blockers.append(
            _malformed_row_blocker("report-intelligence forecast claim", invalid_rows)
        )
    return grouped, tuple(blockers)


def _source_markdown_sentences(
    root_path: Path,
) -> tuple[dict[str, list[tuple[int, int, str, tuple[str, ...]]]], tuple[str, ...]]:
    path = root_path / REPORT_METADATA_PATH
    if not path.exists():
        return {}, ()
    raw_rows, parse_blockers = load_jsonl_with_errors(
        path,
        label="report-intelligence metadata",
    )
    rows, invalid_rows = _split_mapping_rows(raw_rows)
    grouped: dict[str, list[tuple[int, int, str, tuple[str, ...]]]] = {}
    blockers = list(parse_blockers)
    for row in rows:
        source_id = str(row.get("source_id") or "")
        markdown = row.get("markdown")
        markdown_rel = str(markdown.get("path") or "") if isinstance(markdown, Mapping) else ""
        markdown_path = (
            root_path / markdown_rel
            if markdown_rel
            else None
        )
        if not source_id or markdown_path is None or not markdown_path.exists():
            continue
        text = markdown_path.read_text(encoding="utf-8", errors="replace")
        sentences = _source_sentences(text)
        if sentences:
            grouped[source_id] = sentences
    if invalid_rows:
        blockers.append(_malformed_row_blocker("report-intelligence metadata", invalid_rows))
    return grouped, tuple(blockers)


def _approved_license_source_ids(root_path: Path) -> tuple[set[str], tuple[str, ...]]:
    path = root_path / SOURCE_LICENSE_REVIEW_TEMPLATE_PATH
    if not path.exists():
        return set(), ()
    raw_rows, parse_blockers = load_jsonl_with_errors(
        path,
        label="source license review",
    )
    rows, invalid_rows = _split_mapping_rows(raw_rows)
    approved = {
        source_id
        for row in rows
        if (
            (source_id := str(row.get("source_id") or "").strip())
            and license_review_row_complete(row)
            and row.get("approved_for_derived_claim_storage") is True
            and row.get("approved_for_production_runtime") is True
        )
    }
    blockers = list(parse_blockers)
    if invalid_rows:
        blockers.append(_malformed_row_blocker("source license review", invalid_rows))
    return approved, tuple(blockers)


def _source_span_ref_id_from_report_claim(
    report_claim: Mapping[str, Any],
    fallback_source_span_id: str,
) -> str:
    span_ids = _string_sequence(report_claim.get("source_span_ids"))
    span_id = span_ids[0] if span_ids else ""
    if not span_id:
        span_id = str(report_claim.get("source_span_id") or "").strip()
    return span_id or fallback_source_span_id


def _candidate_claim_from_report_intelligence(
    candidate: Mapping[str, Any],
    review_row: Mapping[str, Any],
    report_claim: Mapping[str, Any],
    row_index: int,
    known_variable_ids: set[str],
    approved_license_source_ids: set[str],
) -> GoldCandidateClaim:
    source_id = str(candidate.get("source_id") or review_row.get("source_id") or "")
    source_span_id = str(
        candidate.get("source_span_id")
        or review_row.get("source_span_id")
        or f"{source_id}:original_markdown"
    )
    claim_text = str(report_claim.get("claim_text") or "").strip()
    span_ref_id = _source_span_ref_id_from_report_claim(
        report_claim,
        source_span_id,
    )
    metric_proxy_mapping = _string_sequence(report_claim.get("metric_proxy_mapping"))
    llm_cause_variables = tuple(
        item for item in metric_proxy_mapping if item in known_variable_ids
    )
    target = report_claim.get("target")
    target_id = (
        str(target.get("target_id") or "")
        if isinstance(target, Mapping)
        else ""
    )
    llm_target_variables = (
        (target_id,) if target_id and target_id in known_variable_ids else ()
    )
    fallback_cause_variables, fallback_target_variables, _ = _variable_pair(
        claim_text,
        query_key=str(candidate.get("query_key") or ""),
        industry=str(candidate.get("industry") or ""),
        ts_code=str(candidate.get("ts_code") or ""),
        known_variable_ids=known_variable_ids,
    )
    cause_variables = llm_cause_variables or fallback_cause_variables
    target_variables = llm_target_variables or fallback_target_variables
    extraction_quality = report_claim.get("extraction_quality")
    mapping_gaps = _string_sequence(extraction_quality.get("mapping_gaps")) if isinstance(extraction_quality, Mapping) else ()
    risk_flags = [
        "manual_review_required",
        "original_markdown_forecast_claim",
    ]
    if not cause_variables or not target_variables:
        risk_flags.append("canonical_variable_mapping_needed")
    if str(report_claim.get("forecast_testability") or "") != "testable":
        risk_flags.append("forecast_not_testable")
    if mapping_gaps:
        risk_flags.append("forecast_mapping_insufficient")
    if str(report_claim.get("claim_provenance") or "") != "source_grounded":
        risk_flags.append("not_source_grounded")
    if source_id not in approved_license_source_ids and str(candidate.get("license_status") or "") != "approved":
        risk_flags.append("license_pending")

    return GoldCandidateClaim(
        claim_id=str(
            review_row.get("claim_id")
            or f"GOLD-{source_id}-{row_index + 1:03d}"
        ),
        source_id=source_id,
        source_span_id=source_span_id,
        gold_set_domain=str(
            review_row.get("gold_set_domain")
            or candidate.get("gold_set_domain")
            or "other"
        ),
        gold_set_domains=tuple(
            review_row.get("gold_set_domains")
            or candidate.get("gold_set_domains")
            or ("other",)
        ),
        source_span_ref_id=f"{span_ref_id}:forecast-{report_claim.get('forecast_claim_id') or 'unknown'}",
        source_start_char=0,
        source_end_char=len(claim_text),
        source_text_hash=_short_hash(claim_text),
        candidate_available=True,
        claim_type=str(report_claim.get("forecast_type") or "forecast_claim"),
        claim_text=claim_text,
        cause_variables=cause_variables,
        target_variables=target_variables,
        direction=str(report_claim.get("direction") or "unknown"),
        unsupported_fields=tuple(f"mapping_gap:{gap}" for gap in mapping_gaps),
        verifier_status="requires_review",
        extraction_confidence_bin=(
            "medium" if not mapping_gaps else "low"
        ),
        review_risk_flags=tuple(dict.fromkeys(risk_flags)),
    )


def _build_gold_candidate_claims_with_blockers(
    root: str | Path = ".",
) -> tuple[tuple[GoldCandidateClaim, ...], tuple[str, ...]]:
    root_path = Path(root)
    raw_candidates, candidate_parse_blockers = load_jsonl_with_errors(
        root_path / GOLD_CANDIDATES_PATH,
        label="gold candidate",
    )
    raw_review_rows, review_parse_blockers = load_jsonl_with_errors(
        root_path / GOLD_REVIEW_TEMPLATE_PATH,
        label="gold-set review",
    )
    candidates, invalid_candidate_rows = _split_mapping_rows(raw_candidates)
    review_rows, invalid_review_rows = _split_mapping_rows(raw_review_rows)
    review_by_source = _review_rows_by_source(review_rows)
    report_claims_by_source, report_claim_blockers = _source_report_claims(root_path)
    markdown_sentences_by_source, markdown_sentence_blockers = _source_markdown_sentences(root_path)
    approved_license_source_ids, license_review_blockers = _approved_license_source_ids(root_path)
    vocabulary_blockers: tuple[str, ...] = ()
    try:
        vocabulary = load_claim_variable_vocabulary(root_path)
        known_variable_ids = {variable.variable_id for variable in vocabulary.variables}
    except ValueError as exc:
        known_variable_ids = set()
        vocabulary_blockers = (str(exc),)
    claims: list[GoldCandidateClaim] = []
    for candidate in candidates:
        source_id = str(candidate.get("source_id") or "")
        sentence_rows = _source_sentences(str(candidate.get("abstract") or candidate.get("source_span_text") or ""))
        for idx, review_row in enumerate(review_by_source.get(source_id, ())):
            report_claims = report_claims_by_source.get(source_id, ())
            markdown_sentence_rows = markdown_sentences_by_source.get(source_id, ())
            if report_claims:
                claims.append(
                    _candidate_claim_from_report_intelligence(
                        candidate,
                        review_row,
                        report_claims[idx % len(report_claims)],
                        idx,
                        known_variable_ids,
                        approved_license_source_ids,
                    )
                )
            else:
                fallback_sentence_rows = markdown_sentence_rows or sentence_rows
                fallback_span_id = (
                    f"{source_id}:original_markdown"
                    if markdown_sentence_rows
                    else None
                )
                extra_risk_flags = (
                    ("original_markdown_sentence_fallback",)
                    if markdown_sentence_rows
                    else ()
                )
                claims.append(
                    _candidate_claim_for_review_row(
                        candidate,
                        review_row,
                        fallback_sentence_rows,
                        idx,
                        known_variable_ids,
                        approved_license_source_ids,
                        source_span_id_override=fallback_span_id,
                        extra_risk_flags=extra_risk_flags,
                    )
                )
    blockers: list[str] = [
        *candidate_parse_blockers,
        *review_parse_blockers,
        *report_claim_blockers,
        *markdown_sentence_blockers,
        *license_review_blockers,
        *vocabulary_blockers,
    ]
    if invalid_candidate_rows:
        blockers.append(_malformed_row_blocker("gold candidate", invalid_candidate_rows))
    if invalid_review_rows:
        blockers.append(_malformed_row_blocker("gold-set review", invalid_review_rows))
    return tuple(claims), tuple(blockers)


def build_gold_candidate_claims(root: str | Path = ".") -> tuple[GoldCandidateClaim, ...]:
    claims, _ = _build_gold_candidate_claims_with_blockers(root)
    return claims


def merge_candidate_claims_into_review_template(
    root: str | Path = ".",
    *,
    candidate_claims: Sequence[GoldCandidateClaim] | None = None,
    pre_merge_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    root_path = Path(root)
    review_path = root_path / GOLD_REVIEW_TEMPLATE_PATH
    raw_rows, review_parse_blockers = load_jsonl_with_errors(
        review_path,
        label="gold-set review",
    )
    rows, invalid_review_rows = _split_mapping_rows(raw_rows)
    if candidate_claims is None:
        claims, build_blockers = _build_gold_candidate_claims_with_blockers(root_path)
        pre_merge_blockers = tuple(dict.fromkeys((*pre_merge_blockers, *build_blockers)))
    else:
        claims = tuple(candidate_claims)
    by_claim_id = {claim.claim_id: claim for claim in claims}
    manual_before = {
        str(row.get("claim_id") or ""): {field: row.get(field) for field in MANUAL_REVIEW_FIELDS}
        for row in rows
    }
    merged: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        claim = by_claim_id.get(str(row.get("claim_id") or ""))
        if claim is not None:
            out.update(
                {
                    "proposed_claim_text": claim.claim_text,
                    "proposed_claim_type": claim.claim_type,
                    "proposed_gold_set_domain": claim.gold_set_domain,
                    "proposed_gold_set_domains": list(claim.gold_set_domains),
                    "proposed_cause_variables": list(claim.cause_variables),
                    "proposed_target_variables": list(claim.target_variables),
                    "proposed_direction": claim.direction,
                    "proposed_source_span_ref_id": claim.source_span_ref_id,
                    "proposed_source_start_char": claim.source_start_char,
                    "proposed_source_end_char": claim.source_end_char,
                    "proposed_source_text_hash": claim.source_text_hash,
                    "proposed_extraction_confidence_bin": claim.extraction_confidence_bin,
                    "proposed_review_risk_flags": list(claim.review_risk_flags),
                    "proposed_verifier_status": claim.verifier_status,
                }
            )
        merged.append(out)
    blockers = [*pre_merge_blockers, *review_parse_blockers]
    if invalid_review_rows:
        blockers.append(_malformed_row_blocker("gold-set review", invalid_review_rows))
    if not blockers:
        _write_jsonl(review_path, merged)
    manual_after = {
        str(row.get("claim_id") or ""): {field: row.get(field) for field in MANUAL_REVIEW_FIELDS}
        for row in merged
    }
    return {
        "path": str(review_path),
        "rows": len(raw_rows) + len(review_parse_blockers),
        "rows_with_candidate_fields": sum("proposed_claim_text" in row for row in merged),
        "manual_fields_preserved": manual_before == manual_after,
        "applied": not blockers,
        "blockers": tuple(blockers),
    }


def build_gold_candidate_claim_summary(
    root: str | Path = ".",
    *,
    candidate_claims: Sequence[GoldCandidateClaim] | None = None,
    review_merge_result: Mapping[str, Any] | None = None,
    blockers: Sequence[str] = (),
) -> GoldCandidateClaimSummary:
    if candidate_claims is None:
        claims, build_blockers = _build_gold_candidate_claims_with_blockers(root)
        blockers = tuple(dict.fromkeys((*build_blockers, *blockers)))
    else:
        claims = tuple(candidate_claims)
    risk_counts = Counter(flag for claim in claims for flag in claim.review_risk_flags)
    domain_counts = Counter(claim.gold_set_domain for claim in claims)
    direction_counts = Counter(claim.direction for claim in claims)
    claim_type_counts = Counter(claim.claim_type for claim in claims)
    return GoldCandidateClaimSummary(
        summary_id="RKE-GOLD-CANDIDATE-CLAIMS-SUMMARY-20260606",
        candidate_claim_path=GOLD_CANDIDATE_CLAIMS_PATH,
        review_path=GOLD_REVIEW_TEMPLATE_PATH,
        candidate_claim_count=len(claims),
        candidate_available_count=sum(claim.candidate_available for claim in claims),
        missing_variable_mapping_count=sum(
            "canonical_variable_mapping_needed" in claim.review_risk_flags for claim in claims
        ),
        domain_counts=dict(domain_counts),
        direction_counts=dict(direction_counts),
        claim_type_counts=dict(claim_type_counts),
        risk_flag_counts=dict(risk_counts),
        review_rows_with_candidate_fields=int((review_merge_result or {}).get("rows_with_candidate_fields") or 0),
        manual_fields_preserved=bool((review_merge_result or {}).get("manual_fields_preserved")),
        blockers=tuple(blockers),
    )


def write_gold_candidate_claims(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    claims, build_blockers = _build_gold_candidate_claims_with_blockers(root_path)
    claims_result = _write_jsonl(root_path / GOLD_CANDIDATE_CLAIMS_PATH, [asdict(claim) for claim in claims])
    merge_result = merge_candidate_claims_into_review_template(
        root_path,
        candidate_claims=claims,
        pre_merge_blockers=build_blockers,
    )
    blockers = tuple(dict.fromkeys((*build_blockers, *(merge_result.get("blockers") or ()))))
    summary = build_gold_candidate_claim_summary(
        root_path,
        candidate_claims=claims,
        review_merge_result=merge_result,
        blockers=blockers,
    )
    summary_result = _write_json(root_path / GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH, asdict(summary))
    return {
        "candidate_claims": str(claims_result["path"]),
        "summary": str(summary_result["path"]),
        "review_template": str(merge_result["path"]),
    }
