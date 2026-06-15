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

from .claim_text_filters import is_non_research_claim_text
from .claim_vocabulary import load_claim_variable_vocabulary
from .manual_review_batches import gold_candidate_reviewable
from .phase_minus1 import build_gold_set_review_template, load_jsonl_with_errors
from .review_integrity import license_review_row_complete


GOLD_CANDIDATE_CLAIMS_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.jsonl"
GOLD_CANDIDATE_CLAIMS_SUMMARY_PATH = "registry/gold_sets/tushare_research_reports.candidate_claims.summary.json"
GOLD_CANDIDATES_PATH = "registry/sources/tushare_research_reports.gold_candidates.jsonl"
GOLD_REVIEW_TEMPLATE_PATH = "registry/gold_sets/tushare_research_reports.review_template.jsonl"
REPORT_FORECAST_CLAIMS_PATH = "registry/report_intelligence/forecast_claims.jsonl"
REPORT_METADATA_PATH = "registry/report_intelligence/report_metadata.jsonl"
SOURCE_LICENSE_REVIEW_TEMPLATE_PATH = "registry/compliance/tushare_license_review_template.jsonl"
MAX_REVIEW_CLAIMS_PER_SOURCE = 3
NEAR_DUPLICATE_CLAIM_SIMILARITY = 0.55

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
NEGATIVE_TERMS = ("下降", "承压", "风险", "压力", "下滑", "回落", "限制", "恶化", "偏弱", "走弱", "宽松", "收窄")
POSITIVE_TERMS = (
    "增长",
    "提升",
    "改善",
    "修复",
    "复苏",
    "景气",
    "盈利",
    "订单",
    "催化",
    "偏强",
    "企稳",
    "反弹",
    "支撑",
    "受益",
    "打开空间",
)
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]{12,260}[。！？!?；;]?")
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
PRICE_TARGET_TERMS = (
    "铜价",
    "铝价",
    "锡价",
    "金价",
    "银价",
    "油价",
    "水泥价格",
    "沥青",
    "价格",
)
PRICE_POSITIVE_TERMS = ("震荡偏强", "偏强", "上行", "上涨", "反弹", "企稳", "打开空间", "支撑", "回升")
PRICE_NEGATIVE_TERMS = ("下行", "下跌", "回落", "走弱", "偏弱", "压制")
STRONG_POSITIVE_EFFECT_TERMS = (
    "有利于",
    "有助于",
    "支撑",
    "受益",
    "提供稳定基础",
    "奠定基础",
    "触底反弹",
    "盈利能力显著改善",
    "利润修复",
    "业绩反转",
    "转正",
    "亏损幅度收窄",
    "边际改善",
)
STRONG_NEGATIVE_EFFECT_TERMS = (
    "下调",
    "下修",
    "减值压力",
    "盈利预测被下调",
    "业绩预测被下调",
    "亏损扩大",
    "拖累",
)
NEGATIVE_BACKGROUND_EXCEPTIONS = (
    "风险管理",
    "风险化解",
    "化解风险",
    "保交房",
    "保交付",
    "保障交付",
    "亏损幅度收窄",
    "收益空间持续收窄",
    "固收收益空间收窄",
)
DOLLAR_MACRO_CONTEXT_TERMS = (
    "美元指数",
    "美元流动性",
    "美元兑",
    "美元汇率",
    "美元走强",
    "美元走弱",
    "人民币汇率",
    "汇率风险",
    "跨境资金",
    "中美利差",
    "美联储",
    "美债",
    "DXY",
    "USDCNY",
    "USDCNH",
)
DOLLAR_MACRO_CONTEXT_LOWER_TERMS = (
    "fed",
    "dxy",
    "usd",
    "fx",
    "pce",
    "tips",
    "treasury",
)
AI_COMPUTE_CONTEXT_TERMS = (
    "AI",
    "AIGC",
    "算力",
    "人工智能",
    "大模型",
    "数据中心",
    "云",
    "Token",
    "推理",
)
SEMICONDUCTOR_CONTEXT_TERMS = (
    "半导体",
    "芯片",
    "晶圆",
    "封装",
    "封测",
    "EDA",
    "集成电路",
    "先进制程",
    "先进封装",
    "光刻",
    "CoWoS",
    "Chiplet",
    "硅光",
)
SEMICONDUCTOR_STORAGE_CYCLE_TERMS = (
    "存储芯片",
    "存储器",
    "存储厂商",
    "存储价格",
    "存储周期",
    "存储景气",
    "存储产能",
    "存储库存",
    "存储市场",
    "DRAM",
    "NAND",
    "HBM",
    "DDR",
    "内存",
    "闪存",
)
SEMICONDUCTOR_POLICY_TERMS = (
    "国产替代",
    "国产化",
    "自主可控",
    "出口管制",
    "制裁",
    "限制",
    "半导体设备",
    "EDA",
    "晶圆代工",
    "先进封装",
    "封测",
)
TRADE_OR_GEOPOLITICAL_TERMS = (
    "出口",
    "限制",
    "管制",
    "封锁",
    "制裁",
    "地缘",
    "贸易摩擦",
    "中美",
    "国产",
    "替代",
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
MANUAL_REVIEW_DECISION_FIELDS = (
    "manual_claim_text",
    "claim_correct",
    "source_span_supports_claim",
    "direction_correct",
    "target_correct",
    "horizon_correct",
    "variable_mapping_correct",
    "unsupported_field_false_grounded",
)
SUPPORTED_DIRECTIONS = {"positive", "negative", "neutral", "ambiguous", "unknown"}
TESTABLE_DIRECTIONS = {"positive", "negative"}


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


def _normalized_claim_key(text: str) -> str:
    return re.sub(r"[\s，。；;,.、:：]+", "", str(text or "")).lower()


def _claim_similarity(left: str, right: str) -> float:
    left_key = _normalized_claim_key(left)
    right_key = _normalized_claim_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key in right_key or right_key in left_key:
        return 1.0
    left_terms = {left_key[index : index + 2] for index in range(max(0, len(left_key) - 1))}
    right_terms = {right_key[index : index + 2] for index in range(max(0, len(right_key) - 1))}
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _similar_to_existing_claim(text: str, existing_texts: Sequence[str]) -> bool:
    return any(
        _claim_similarity(text, existing) >= NEAR_DUPLICATE_CLAIM_SIMILARITY
        for existing in existing_texts
        if existing
    )


def _is_boilerplate_risk_warning(text: str) -> bool:
    return is_non_research_claim_text(text)


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


def _manual_review_value_present(row: Mapping[str, Any]) -> bool:
    return any(row.get(field) not in (None, "", []) for field in MANUAL_REVIEW_DECISION_FIELDS)


def _review_rows_by_source(review_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in review_rows:
        source_id = str(row.get("source_id") or row.get("document_id") or "")
        if source_id:
            grouped.setdefault(source_id, []).append(row)
    return grouped


def _source_sentences(text: str) -> list[tuple[int, int, str, tuple[str, ...]]]:
    scored: list[tuple[int, int, int, str, tuple[str, ...]]] = []
    seen_keys: set[str] = set()
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        claim_key = _normalized_claim_key(sentence)
        if not claim_key or claim_key in seen_keys:
            continue
        seen_keys.add(claim_key)
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
    if "风险管理" in sentence and any(term in sentence for term in ("需求", "增长", "上升", "扩容", "重要配套")):
        return "positive"
    has_strong_negative = any(term in sentence for term in STRONG_NEGATIVE_EFFECT_TERMS)
    has_strong_positive = any(term in sentence for term in STRONG_POSITIVE_EFFECT_TERMS)
    if has_strong_negative:
        return "ambiguous" if has_strong_positive else "negative"
    if has_strong_positive:
        return "positive"
    if any(target in sentence for target in PRICE_TARGET_TERMS):
        has_price_positive = any(term in sentence for term in PRICE_POSITIVE_TERMS)
        has_price_negative = any(term in sentence for term in PRICE_NEGATIVE_TERMS)
        if has_price_positive and not has_price_negative:
            return "positive"
        if has_price_negative and not has_price_positive:
            return "negative"
        if has_price_positive and has_price_negative:
            return "ambiguous"
    negative_scan_text = sentence
    for exception in NEGATIVE_BACKGROUND_EXCEPTIONS:
        negative_scan_text = negative_scan_text.replace(exception, "")
    has_positive = any(term in sentence for term in POSITIVE_TERMS)
    has_negative = any(term in negative_scan_text for term in NEGATIVE_TERMS)
    if has_positive and not has_negative:
        return "positive"
    if has_negative and not has_positive:
        return "negative"
    if has_positive and has_negative:
        return "ambiguous"
    return "neutral"


def _normalized_report_direction(value: Any) -> str:
    direction = str(value or "").strip().lower()
    return direction if direction in SUPPORTED_DIRECTIONS else "unknown"


def _reconciled_direction(
    claim_text: str,
    raw_direction: Any,
) -> tuple[str, tuple[str, ...]]:
    """Return a conservative direction and flags for conflicting direction evidence."""
    inferred = _direction(claim_text)
    raw = _normalized_report_direction(raw_direction)
    flags: list[str] = []
    if raw in TESTABLE_DIRECTIONS and inferred in TESTABLE_DIRECTIONS:
        if raw == inferred:
            return raw, ()
        return "ambiguous", ("direction_conflict_requires_review",)
    if raw in TESTABLE_DIRECTIONS and inferred in {"neutral", "unknown"}:
        return raw, ()
    if raw in TESTABLE_DIRECTIONS and inferred == "ambiguous":
        return "ambiguous", ("direction_conflict_requires_review",)
    if inferred in TESTABLE_DIRECTIONS:
        return inferred, ()
    if inferred == "ambiguous" or raw == "ambiguous":
        flags.append("direction_conflict_requires_review")
    return inferred if inferred in SUPPORTED_DIRECTIONS else raw, tuple(flags)


def _append_known(target: list[str], variable_id: str, known_variable_ids: set[str]) -> None:
    if variable_id in known_variable_ids and variable_id not in target:
        target.append(variable_id)


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _has_dollar_macro_context(text: str) -> bool:
    if any(term in text for term in DOLLAR_MACRO_CONTEXT_TERMS):
        return True
    text_lower = text.lower()
    if any(term in text_lower for term in DOLLAR_MACRO_CONTEXT_LOWER_TERMS):
        return True
    if "美元" not in text:
        return False
    context_terms = ("汇率", "流动性", "指数", "走强", "走弱", "加息", "降息", "美债", "人民币")
    if not any(term in text for term in context_terms):
        return False
    for match in re.finditer("美元", text):
        previous = text[max(0, match.start() - 1) : match.start()]
        if previous and (previous.isdigit() or previous in {"亿", "万", "千", "百"}):
            continue
        return True
    return False


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
    text_upper = text.upper()
    cause: list[str] = []
    target: list[str] = []
    flags: list[str] = []

    construction_proxy_terms = ("洁净室", "建筑", "工程", "城市更新", "水泥", "沥青", "钢结构")
    construction_proxy_view = any(keyword in text for keyword in construction_proxy_terms)
    wealth_management_context = any(
        keyword in text
        for keyword in (
            "银行理财",
            "理财产品",
            "理财子",
            "理财公司",
            "资管",
            "固收",
            "破净",
            "净值",
            "多资产",
            "信用利差",
        )
    )
    bank_credit_growth_context = any(
        keyword in text
        for keyword in (
            "社融",
            "贷款",
            "信贷",
            "居民中长期",
            "企业中长期",
            "融资需求",
            "融资规模",
        )
    )
    has_ai_compute_context = any(keyword in text for keyword in AI_COMPUTE_CONTEXT_TERMS)
    has_semiconductor_context = any(keyword in text for keyword in SEMICONDUCTOR_CONTEXT_TERMS)
    has_storage_cycle_context = any(keyword in text_upper for keyword in SEMICONDUCTOR_STORAGE_CYCLE_TERMS)
    has_semiconductor_policy_context = any(keyword in text for keyword in SEMICONDUCTOR_POLICY_TERMS)
    if has_ai_compute_context or has_storage_cycle_context:
        _append_known(cause, "ai_compute_demand", known_variable_ids)
    if has_storage_cycle_context and not construction_proxy_view:
        _append_known(target, "semiconductor_storage_cycle", known_variable_ids)
    if any(keyword in text for keyword in TRADE_OR_GEOPOLITICAL_TERMS):
        _append_known(cause, "trade_friction_intensity", known_variable_ids)
    if (
        has_semiconductor_context
        and has_semiconductor_policy_context
        and not construction_proxy_view
    ):
        _append_known(target, "semiconductor_policy_substitution_alpha", known_variable_ids)
    if any(keyword in text for keyword in ("电池", "宁德", "300750", "补能", "充电", "储能")):
        if any(keyword in text for keyword in ("技术", "迭代", "电池", "能量密度", "充电")):
            _append_known(cause, "ev_battery_technology_iteration", known_variable_ids)
        if any(keyword in text for keyword in ("补能", "换电", "充电", "需求")):
            _append_known(cause, "ev_charging_ecosystem_demand", known_variable_ids)
        _append_known(target, "battery_profitability_expectation", known_variable_ids)
    if any(keyword in text for keyword in ("600519", "茅台", "白酒", "酒企", "高端酒")) or (
        "渠道" in text and "库存" in text and any(keyword in text for keyword in ("白酒", "酒企", "经销商"))
    ):
        _append_known(cause, "liquor_demand_recovery", known_variable_ids)
        _append_known(target, "consumer_leader_profitability_expectation", known_variable_ids)
    if (
        any(keyword in text for keyword in ("流动性", "央行", "利率", "资金"))
        and not wealth_management_context
        and not bank_credit_growth_context
        and not any(
        keyword in text for keyword in ("美元", "美联储", "Fed", "FED", "PCE", "TIPS", "美债", "汇率", "跨境", "境外", "全球")
        )
    ):
        _append_known(cause, "pboc_net_injection", known_variable_ids)
        _append_known(target, "short_term_liquidity_pressure", known_variable_ids)
    if wealth_management_context:
        if any(keyword in text for keyword in ("信用利差", "破净", "净值", "波动", "固收", "多资产")):
            _append_known(cause, "competitive_intensity_pressure", known_variable_ids)
        if any(keyword in text for keyword in ("配置", "多资产", "收益", "增长", "改善", "提升")):
            _append_known(cause, "industry_demand_cycle", known_variable_ids)
        _append_known(target, "wealth_management_nav_pressure", known_variable_ids)
    elif any(keyword in text for keyword in ("银行", "信贷", "贷款", "利差", "净息差", "息差")):
        _append_known(cause, "bank_credit_supply", known_variable_ids)
        if bank_credit_growth_context:
            _append_known(target, "bank_credit_growth_expectation", known_variable_ids)
        else:
            _append_known(target, "bank_net_interest_margin_pressure", known_variable_ids)
    elif bank_credit_growth_context:
        _append_known(cause, "bank_credit_supply", known_variable_ids)
        _append_known(target, "bank_credit_growth_expectation", known_variable_ids)
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
    ) or ("风险" in text and "风险管理" not in text):
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
            "黄金",
            "白银",
            "贵金属",
            "金属价格",
            "稀土",
            "钨",
            "锑",
            "商品",
            "大宗",
            "commodity",
            "gold",
            "copper",
            "aluminum",
            "lithium",
        )
    ):
        _append_known(cause, "commodity_price_cycle", known_variable_ids)
    if _has_dollar_macro_context(text):
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
    elif construction_proxy_view or any(
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

    target = list(
        _normalize_targets_for_context(
            target,
            text=text,
            query_key=query_key,
            industry=industry,
            ts_code=ts_code,
            known_variable_ids=known_variable_ids,
        )
    )
    if not cause or not target:
        flags.append("canonical_variable_mapping_needed")
    return tuple(cause), tuple(target), tuple(flags)


def _normalize_targets_for_context(
    target_variables: Sequence[str],
    *,
    text: str,
    query_key: str,
    industry: str,
    ts_code: str,
    known_variable_ids: set[str],
) -> tuple[str, ...]:
    target = list(dict.fromkeys(str(item) for item in target_variables if str(item)))
    stock_like = _stock_like_identifier(query_key) or _stock_like_identifier(ts_code)
    if stock_like and "stock_forward_excess_return" in known_variable_ids:
        return ("stock_forward_excess_return",)
    industry_like = _contains_any(
        text,
        (
            "行业",
            "板块",
            "主题",
            "产业链",
            "景气",
            "指数",
            "ETF",
            "市场基准",
        ),
    )
    if (
        industry_like
        and "industry_etf_forward_return" in known_variable_ids
        and not _contains_any(text, ("个股", "公司股价", "目标价"))
    ):
        if not target or any(
            item
            in {
                "stock_forward_excess_return",
                "short_term_liquidity_pressure",
                "bank_net_interest_margin_pressure",
                "forward_alpha_after_policy_catalyst",
            }
            for item in target
        ):
            return ("industry_etf_forward_return",)
    return tuple(target)


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
    if row_index < len(sentence_rows):
        start_char, end_char, sentence, keywords = sentence_rows[row_index]
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
    direction = _direction(sentence)
    direction_flags = (
        ("direction_conflict_requires_review",)
        if direction not in TESTABLE_DIRECTIONS
        else ()
    )
    risk_flags = [
        "manual_review_required",
        "sentence_fallback_requires_context_synthesis",
        *extra_risk_flags,
        *variable_flags,
        *direction_flags,
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
    return GoldCandidateClaim(
        claim_id=str(review_row.get("claim_id") or f"GOLD-{source_id}-{row_index + 1:03d}"),
        source_id=source_id,
        source_span_id=source_span_id,
        gold_set_domain=str(
            candidate.get("gold_set_domain") or review_row.get("gold_set_domain") or "other"
        ),
        gold_set_domains=tuple(
            candidate.get("gold_set_domains") or review_row.get("gold_set_domains") or ("other",)
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
        unsupported_fields=(),
        verifier_status="requires_review",
        extraction_confidence_bin="low",
        review_risk_flags=tuple(dict.fromkeys(risk_flags)),
    )


def _non_duplicate_sentence_rows(
    sentence_rows: Sequence[tuple[int, int, str, tuple[str, ...]]],
    used_claim_texts: Sequence[str],
) -> tuple[tuple[int, int, str, tuple[str, ...]], ...]:
    used_keys = {_normalized_claim_key(text) for text in used_claim_texts if text}
    out: list[tuple[int, int, str, tuple[str, ...]]] = []
    seen_keys: set[str] = set()
    seen_texts = [text for text in used_claim_texts if text]
    for row in sentence_rows:
        sentence = row[2]
        key = _normalized_claim_key(sentence)
        if (
            not key
            or key in used_keys
            or key in seen_keys
            or _similar_to_existing_claim(sentence, seen_texts)
        ):
            continue
        seen_keys.add(key)
        out.append(row)
        seen_texts.append(sentence)
    return tuple(out)


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
    seen_by_source: dict[str, set[str]] = {}
    for row in rows:
        source_id = str(row.get("source_id") or "")
        claim_text = str(row.get("claim_text") or "").strip()
        forecast_type = str(row.get("forecast_type") or "").lower()
        if any(term in forecast_type for term in ("rating", "recommendation")):
            continue
        if _is_boilerplate_risk_warning(claim_text):
            continue
        claim_key = _normalized_claim_key(claim_text)
        existing_texts = tuple(grouped.get(source_id, ()))
        existing_claim_texts = tuple(str(item.get("claim_text") or "") for item in existing_texts)
        if (
            source_id
            and claim_text
            and claim_key
            and claim_key not in seen_by_source.setdefault(source_id, set())
            and not _similar_to_existing_claim(claim_text, existing_claim_texts)
        ):
            seen_by_source[source_id].add(claim_key)
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
    variable_type_by_id: Mapping[str, str],
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
        item
        for item in metric_proxy_mapping
        if item in known_variable_ids and variable_type_by_id.get(item) == "cause"
    )
    llm_target_candidates = tuple(
        item
        for item in metric_proxy_mapping
        if item in known_variable_ids and variable_type_by_id.get(item) == "target"
    )
    target = report_claim.get("target")
    target_id = (
        str(target.get("target_id") or "")
        if isinstance(target, Mapping)
        else ""
    )
    llm_target_variables = (
        (target_id,)
        if target_id and target_id in known_variable_ids and variable_type_by_id.get(target_id) == "target"
        else ()
    )
    fallback_cause_variables, fallback_target_variables, _ = _variable_pair(
        claim_text,
        query_key=str(candidate.get("query_key") or ""),
        industry=str(candidate.get("industry") or ""),
        ts_code=str(candidate.get("ts_code") or ""),
        known_variable_ids=known_variable_ids,
    )
    cause_variables = llm_cause_variables or fallback_cause_variables
    target_variables = llm_target_variables or llm_target_candidates or fallback_target_variables
    target_variables = _normalize_targets_for_context(
        target_variables,
        text=claim_text,
        query_key=str(candidate.get("query_key") or ""),
        industry=str(candidate.get("industry") or ""),
        ts_code=str(candidate.get("ts_code") or ""),
        known_variable_ids=known_variable_ids,
    )
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

    direction, direction_flags = _reconciled_direction(
        claim_text,
        report_claim.get("direction"),
    )
    risk_flags.extend(direction_flags)
    return GoldCandidateClaim(
        claim_id=str(
            review_row.get("claim_id")
            or f"GOLD-{source_id}-{row_index + 1:03d}"
        ),
        source_id=source_id,
        source_span_id=source_span_id,
        gold_set_domain=str(
            candidate.get("gold_set_domain")
            or review_row.get("gold_set_domain")
            or "other"
        ),
        gold_set_domains=tuple(
            candidate.get("gold_set_domains")
            or review_row.get("gold_set_domains")
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
        direction=direction,
        unsupported_fields=(),
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
        variable_type_by_id = {
            variable.variable_id: variable.variable_type for variable in vocabulary.variables
        }
    except ValueError as exc:
        known_variable_ids = set()
        variable_type_by_id = {}
        vocabulary_blockers = (str(exc),)
    claims: list[GoldCandidateClaim] = []
    for candidate in candidates:
        source_id = str(candidate.get("source_id") or "")
        sentence_rows = _source_sentences(str(candidate.get("abstract") or candidate.get("source_span_text") or ""))
        review_rows_for_source = tuple(review_by_source.get(source_id, ()))[:MAX_REVIEW_CLAIMS_PER_SOURCE]
        report_claims = report_claims_by_source.get(source_id, ())[:MAX_REVIEW_CLAIMS_PER_SOURCE]
        markdown_sentence_rows = markdown_sentences_by_source.get(source_id, ())
        fallback_sentence_rows = _non_duplicate_sentence_rows(
            markdown_sentence_rows or sentence_rows,
            tuple(str(row.get("claim_text") or "") for row in report_claims),
        )
        for idx, review_row in enumerate(review_rows_for_source):
            source_claims_added = sum(1 for claim in claims if claim.source_id == source_id)
            if idx < len(report_claims):
                claims.append(
                    _candidate_claim_from_report_intelligence(
                        candidate,
                        review_row,
                        report_claims[idx],
                        idx,
                        known_variable_ids,
                        variable_type_by_id,
                        approved_license_source_ids,
                    )
                )
            else:
                fallback_row_index = idx - len(report_claims)
                if fallback_row_index >= len(fallback_sentence_rows):
                    break
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
                fallback_claim = _candidate_claim_for_review_row(
                    candidate,
                    review_row,
                    fallback_sentence_rows,
                    fallback_row_index,
                    known_variable_ids,
                    approved_license_source_ids,
                    source_span_id_override=fallback_span_id,
                    extra_risk_flags=extra_risk_flags,
                )
                if not fallback_claim.target_variables and source_claims_added:
                    continue
                claims.append(fallback_claim)
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
                    "gold_set_domain": claim.gold_set_domain,
                    "gold_set_domains": list(claim.gold_set_domains),
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
                    "proposed_candidate_current": True,
                }
            )
            if not _manual_review_value_present(out) and not gold_candidate_reviewable(out):
                continue
        elif not _manual_review_value_present(row):
            continue
        else:
            out["proposed_candidate_current"] = False
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
    retained_manual_fields_preserved = all(
        manual_before.get(claim_id) == fields
        for claim_id, fields in manual_after.items()
    )
    dropped_manual_claim_ids = [
        claim_id
        for claim_id, fields in manual_before.items()
        if claim_id not in manual_after and _manual_review_value_present(fields)
    ]
    return {
        "path": str(review_path),
        "rows": len(raw_rows) + len(review_parse_blockers),
        "rows_with_candidate_fields": sum("proposed_claim_text" in row for row in merged),
        "manual_fields_preserved": retained_manual_fields_preserved and not dropped_manual_claim_ids,
        "applied": not blockers,
        "blockers": tuple(blockers),
    }


def _ensure_candidate_review_rows(root_path: Path) -> dict[str, Any]:
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
    blockers: list[str] = [*candidate_parse_blockers, *review_parse_blockers]
    if invalid_candidate_rows:
        blockers.append(_malformed_row_blocker("gold candidate", invalid_candidate_rows))
    if invalid_review_rows:
        blockers.append(_malformed_row_blocker("gold-set review", invalid_review_rows))

    existing_document_ids = {
        str(row.get("document_id") or row.get("source_id") or "")
        for row in review_rows
        if str(row.get("document_id") or row.get("source_id") or "").strip()
    }
    missing_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.get("source_id") or "").strip()
        and str(candidate.get("source_id") or "") not in existing_document_ids
    ]
    starter_rows = build_gold_set_review_template(
        missing_candidates,
        claims_per_document=MAX_REVIEW_CLAIMS_PER_SOURCE,
    )
    existing_claim_ids = {
        str(row.get("claim_id") or "")
        for row in review_rows
        if str(row.get("claim_id") or "").strip()
    }
    added_rows = [
        row
        for row in starter_rows
        if str(row.get("claim_id") or "").strip()
        and str(row.get("claim_id") or "") not in existing_claim_ids
    ]
    if not blockers and added_rows:
        _write_jsonl(root_path / GOLD_REVIEW_TEMPLATE_PATH, [*review_rows, *added_rows])
    return {
        "path": GOLD_REVIEW_TEMPLATE_PATH,
        "candidate_documents": len(
            {
                str(candidate.get("source_id") or "")
                for candidate in candidates
                if str(candidate.get("source_id") or "").strip()
            }
        ),
        "existing_review_documents": len(existing_document_ids),
        "candidate_review_documents_added": len(
            {
                str(row.get("document_id") or row.get("source_id") or "")
                for row in added_rows
                if str(row.get("document_id") or row.get("source_id") or "").strip()
            }
        ),
        "candidate_review_rows_added": len(added_rows),
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


def write_gold_candidate_claims(
    root: str | Path = ".",
    *,
    ensure_candidate_review_rows: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    ensure_result: Mapping[str, Any] = {}
    ensure_blockers: tuple[str, ...] = ()
    if ensure_candidate_review_rows:
        ensure_result = _ensure_candidate_review_rows(root_path)
        ensure_blockers = tuple(str(blocker) for blocker in ensure_result.get("blockers") or ())
    claims, build_blockers = _build_gold_candidate_claims_with_blockers(root_path)
    claims_result = _write_jsonl(root_path / GOLD_CANDIDATE_CLAIMS_PATH, [asdict(claim) for claim in claims])
    merge_result = merge_candidate_claims_into_review_template(
        root_path,
        candidate_claims=claims,
        pre_merge_blockers=(*ensure_blockers, *build_blockers),
    )
    blockers = tuple(
        dict.fromkeys((*ensure_blockers, *build_blockers, *(merge_result.get("blockers") or ())))
    )
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
        "ensure_candidate_review_rows": ensure_candidate_review_rows,
        "candidate_review_documents_added": int(
            ensure_result.get("candidate_review_documents_added") or 0
        ),
        "candidate_review_rows_added": int(ensure_result.get("candidate_review_rows_added") or 0),
        "blockers": blockers,
    }
