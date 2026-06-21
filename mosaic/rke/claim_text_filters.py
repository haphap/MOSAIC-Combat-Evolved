"""Shared filters for report claim candidate text."""

from __future__ import annotations

import re


RISK_WARNING_PREFIX_RE = re.compile(
    r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[、.)）]|[（(]\d+[）)])?\s*"
    r"(?:风险提示|风险因素|风险声明|免责声明)\s*[:：.。]"
)
RISK_ITEM_PREFIX_RE = re.compile(
    r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[、.)）]|[（(]\d+[）)])?\s*"
    r"[^。；;]{0,32}风险\s*[:：]"
)
GENERIC_RISK_WARNING_ENUM_RE = re.compile(
    r"^\s*(?:\d+[、.)）]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.)）])?\s*"
    r".{0,24}(?:不及预期|低于预期|超预期变化|大盘系统性风险|业绩不达预期|数据误差|竞争加剧|客户依赖|政策落地)"
    r"(?:.*风险)?\s*[。；;]?\s*$"
)
GENERIC_RISK_SCENARIO_RE = re.compile(
    r"^\s*.{0,40}(?:竞争加剧|价格波动|需求不及预期|进展不及预期|成本上升|毛利率下降)"
    r".{0,80}(?:不及预期|下降|下滑|承压|风险)\s*[。；;]?\s*$"
)

DISCLAIMER_TERMS = (
    "前瞻性表述",
    "完整来源见末页",
    "不构成投资建议",
    "不代表推介",
    "资产管理和证券自营部门",
    "独立做出与本报告中的意见和建议不一致",
    "并不预示其未来表现",
    "过往业绩并不预示",
    "业绩比较基准及过往业绩",
    "本报告所载",
    "准确性及完整性不作任何保证",
    "市场有风险",
    "投资有风险",
    "自担投资风险",
    "分析师承诺",
    "作者在过去、现在或未来",
    "未就其研究报告所提供的具体建议",
    "收取任何报酬",
    "特此声明",
    "免责声明",
    "法律声明",
)
GENERIC_RISK_LIST_TERMS = (
    "判断误差",
    "测算误差",
    "数据误差",
    "假设与实际偏离",
    "不及预期",
    "低于预期",
    "不达预期",
    "超预期恶化",
    "大面积暴露",
    "竞争加剧",
    "行业竞争加剧",
    "客户依赖",
    "政策落地",
    "政策变化",
    "宏观经济",
    "货币政策风险",
)
RATING_DEFINITION_TERMS = (
    "公司评级",
    "行业评级",
    "预期未来6个月内",
    "股价相对市场基准指数",
    "行业指数优于市场指数",
    "行业指数弱于市场指数",
    "行业指数相对市场指数持平",
)
RATING_DEFINITION_LABELS = (
    "强烈推荐",
    "推荐",
    "看好",
    "中性",
    "看淡",
    "卖出",
)
GENERIC_VIEW_LABELS = {
    "看好",
    "买入",
    "增持",
    "推荐",
    "中性",
    "卖出",
    "维持推荐",
    "维持买入",
    "维持增持",
    "强于大市",
    "优于大市",
}
INVESTMENT_RECOMMENDATION_RE = re.compile(
    r"^\s*(?:投资建议|投资方向上|建议关注|建议重点关注|建议聚焦|建议布局|"
    r"重点关注|短期需关注|长期布局|维持|给予|首次覆盖|上调至|下调至).{0,160}"
    r"(?:标的|公司|评级|买入|增持|推荐|目标价|机会|方向|主线|盈利预测)"
)
FORECAST_VALUATION_HEADING_RE = re.compile(
    r"^\s*(?:盈利预测[、,，]?\s*估值与评级|盈利预测与投资评级|投资建议[：:]?\s*维持盈利预测)\s*[。；;]?\s*$"
)
ATTENTION_OR_ALLOCATION_RE = re.compile(
    r"^\s*(?:后续需|短期需|长期需|重点关注|需重点关注|建议关注|建议聚焦|建议布局|长期布局).{0,120}\s*[。；;]?\s*$"
)
TRAILING_RATING_SUFFIX_RE = re.compile(
    r"(?:[，,；;。]\s*)?"
    r"(?:(?:首次覆盖(?:[，,]\s*)?)|(?:维持|给予|上调至|下调至|调升至|调降至)\s*(?:至)?\s*)"
    r"[“\"']?"
    r"(?:强烈推荐|推荐|买入|增持|减持|中性|卖出|看好|看淡|优于大市|强于大市|跑赢市场|跑赢行业)"
    r"[”\"']?\s*评级\s*[。；;]?\s*$"
)
SHORT_VIEW_SLOGAN_RE = re.compile(r"^\s*(?:关注|看好|建议关注).{0,24}(?:机会|主线|方向|标的)\s*[。；;]?\s*$")
DESCRIPTIVE_NEWS_PREFIX_RE = re.compile(r"^\s*据.{0,32}消息[，,]")
RESEARCH_CITATION_RE = re.compile(
    r"^\s*(?:\d+[、.．]\s*)?《[^》]{4,120}(?:研究|报告|点评|周报|月报)[^》]{0,80}》\s*$"
)
FORWARD_LOOKING_TERMS = (
    "预计",
    "预期",
    "未来",
    "后续",
    "有望",
    "将",
    "可能",
    "看好",
    "受益",
    "推动",
    "带动",
    "导致",
    "短期",
    "中期",
    "长期",
)
HTML_TABLE_MARKUP_TERMS = ("<table", "<tr", "<td", "</table>", "</tr>", "</td>")
TOC_DOT_LEADER_RE = re.compile(r"^\s*.{1,48}\.{2,}\s*\d+\s*$")
HEADING_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d{1,2}|[一二三四五六七八九十]+)[、.．\s]+.{2,80}$")
RESEARCH_LOGIC_TERMS = (
    "预计",
    "预期",
    "有望",
    "推动",
    "带动",
    "导致",
    "受益",
    "承压",
    "增长",
    "改善",
    "修复",
    "压制",
)
FRAGMENT_SEPARATOR_TERMS = ("·", "+", " / ", "｜", "|")
EARNINGS_FORECAST_VALUE_ACTION_TERMS = ("上调", "下调", "调整", "维持", "预计", "预测")
EARNINGS_FORECAST_VALUE_METRIC_TERMS = (
    "盈利预测",
    "业绩预测",
    "净利润预测",
    "归母净利润预测",
    "扣非归母净利润",
    "归母净利润",
    "净利润",
    "每股收益",
)
EARNINGS_FORECAST_MECHANISM_TERMS = (
    "因为",
    "由于",
    "若",
    "如果",
    "随着",
    "受益",
    "推动",
    "带动",
    "导致",
    "催化",
    "景气",
    "需求",
    "供给",
    "价格",
    "订单",
    "政策",
    "竞争",
    "出海",
    "库存",
    "产能",
    "利率",
    "流动性",
)
EARNINGS_FORECAST_PERIOD_RE = re.compile(
    r"(?:20)?2\d\s*(?:[-~至—－]\s*(?:20)?2\d)?\s*(?:年|E|e)"
)
HISTORICAL_OPERATING_PERIOD_RE = re.compile(
    r"(?:20)?\d{2}\s*Q[1-4]|Q[1-4]|[一二三四]季度|上半年|下半年|前三季度|"
    r"报告期|本期|期内|本周|上周|近期|目前|当前|已经|已|同比|环比"
)
HISTORICAL_OPERATING_METRIC_TERMS = (
    "销售回款",
    "经营性现金流",
    "现金流",
    "营收",
    "营业收入",
    "收入",
    "利润",
    "净利润",
    "毛利率",
    "费用率",
    "订单",
    "出货",
    "交付",
    "产量",
    "销量",
    "库存",
    "回款",
    "周转",
    "市占率",
    "资产质量",
    "不良率",
)
HISTORICAL_RESULT_TERMS = (
    "量价齐升",
    "驱动增长",
    "实现营收",
    "实现营业收入",
    "实现归母净利润",
    "同比增长",
    "同比提高",
    "同比减少",
    "同比下降",
    "同比下滑",
)
HISTORICAL_RESULT_YEAR_RE = re.compile(r"20\d{2}年")
STRICT_FORWARD_CLAIM_TERMS = (
    "预计",
    "预期",
    "预测",
    "未来",
    "后续",
    "有望",
    "将",
    "可能",
    "若",
    "如果",
    "随着",
    "受益",
    "推动",
    "带动",
    "导致",
    "展望",
    "看好",
    "催化",
)
EXPLICIT_FORWARD_CLAIM_TERMS = (
    "预计",
    "预期",
    "预测",
    "未来",
    "后续",
    "有望",
    "将",
    "可能",
    "若",
    "如果",
    "随着",
    "展望",
)
CURRENT_MARKET_STATUS_TERMS = (
    "本周",
    "上周",
    "近期",
    "截至",
    "当前",
    "目前",
)
MARKET_STATUS_NOUNS = (
    "价格",
    "金价",
    "油价",
    "市场",
    "板块",
    "行业",
    "格局",
    "走势",
)
TRUNCATED_CLAIM_SUFFIXES = ("并", "同时", "以及", "叠加", "且", "和", "及", "、", "，", ",")


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def strip_trailing_rating_suffix(text: str) -> str:
    """Remove trailing rating boilerplate while preserving the forecast clause."""

    normalized = _normalized_text(text)
    if not normalized:
        return ""
    cleaned = normalized
    while True:
        next_value = TRAILING_RATING_SUFFIX_RE.sub("", cleaned).strip()
        if next_value == cleaned:
            break
        cleaned = next_value.rstrip("，,；;。 ")
    if not cleaned:
        return ""
    if normalized.endswith(("。", "；", ";")) and not cleaned.endswith(("。", "；", ";")):
        cleaned += "。"
    return cleaned


def _non_overlapping_risk_term_hits(text: str) -> tuple[str, ...]:
    hits: list[str] = []
    for term in sorted(GENERIC_RISK_LIST_TERMS, key=len, reverse=True):
        if term not in text:
            continue
        if any(term in selected for selected in hits):
            continue
        hits.append(term)
    return tuple(hits)


def is_boilerplate_risk_warning_text(text: str) -> bool:
    stripped = _normalized_text(text)
    if not stripped:
        return False
    if RISK_WARNING_PREFIX_RE.match(stripped) or RISK_ITEM_PREFIX_RE.match(stripped):
        return True
    if len(stripped) <= 80 and GENERIC_RISK_WARNING_ENUM_RE.match(stripped):
        return True
    if len(stripped) <= 120 and GENERIC_RISK_SCENARIO_RE.match(stripped):
        return True
    risk_term_hits = _non_overlapping_risk_term_hits(stripped)
    return len(risk_term_hits) >= 2 and ("风险" in stripped or stripped.endswith("等"))


def is_disclaimer_text(text: str) -> bool:
    normalized = _normalized_text(text)
    return bool(normalized and any(term in normalized for term in DISCLAIMER_TERMS))


def is_rating_definition_text(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return False
    compact = re.sub(r"\s+", "", normalized)
    if normalized in GENERIC_VIEW_LABELS:
        return True
    if FORECAST_VALUATION_HEADING_RE.match(normalized):
        return True
    if INVESTMENT_RECOMMENDATION_RE.search(normalized):
        return True
    if ATTENTION_OR_ALLOCATION_RE.match(normalized):
        return True
    if SHORT_VIEW_SLOGAN_RE.search(normalized):
        return True
    if RESEARCH_CITATION_RE.search(normalized):
        return True
    if DESCRIPTIVE_NEWS_PREFIX_RE.search(normalized) and not any(
        term in normalized for term in FORWARD_LOOKING_TERMS
    ):
        return True
    if "预期未来6个月内" in compact and any(
        term in compact
        for term in (
            "行业指数优于市场指数",
            "行业指数弱于市场指数",
            "行业指数相对市场指数",
            "行业指数相对强于基准",
            "相对强于市场表现",
            "股价相对市场基准指数",
        )
    ):
        return True
    lower = normalized.lower()
    has_table_markup = any(term in lower for term in HTML_TABLE_MARKUP_TERMS)
    has_rating_definition = (
        sum(1 for term in RATING_DEFINITION_TERMS if term in normalized) >= 2
        and any(label in normalized for label in RATING_DEFINITION_LABELS)
    )
    if has_rating_definition:
        return True
    return has_table_markup and any(term in normalized for term in RATING_DEFINITION_TERMS)


def is_heading_or_toc_text(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return False
    has_research_logic = any(term in normalized for term in RESEARCH_LOGIC_TERMS)
    fragment_separator_hits = sum(1 for term in FRAGMENT_SEPARATOR_TERMS if term in normalized)
    if fragment_separator_hits and len(normalized) <= 64:
        return True
    if TOC_DOT_LEADER_RE.match(normalized):
        return True
    if normalized.startswith("#") and len(normalized) <= 120:
        return True
    return bool(HEADING_PREFIX_RE.match(normalized) and not has_research_logic)


def is_pure_earnings_forecast_value_text(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return False
    lower = normalized.lower()
    has_metric = any(term in normalized for term in EARNINGS_FORECAST_VALUE_METRIC_TERMS) or "eps" in lower
    if not has_metric:
        return False
    if not any(term in normalized for term in EARNINGS_FORECAST_VALUE_ACTION_TERMS):
        return False
    if any(term in normalized for term in EARNINGS_FORECAST_MECHANISM_TERMS):
        return False
    numeric_count = len(re.findall(r"\d+(?:\.\d+)?", normalized))
    return numeric_count >= 2 and bool(EARNINGS_FORECAST_PERIOD_RE.search(normalized))


def is_historical_operating_fact_text(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return False
    if any(term in normalized for term in EXPLICIT_FORWARD_CLAIM_TERMS):
        return False
    if HISTORICAL_RESULT_YEAR_RE.search(normalized) and any(
        term in normalized for term in HISTORICAL_RESULT_TERMS
    ):
        return True
    if not HISTORICAL_OPERATING_PERIOD_RE.search(normalized):
        return False
    return any(term in normalized for term in HISTORICAL_OPERATING_METRIC_TERMS) or any(
        term in normalized for term in HISTORICAL_RESULT_TERMS
    )


def is_truncated_claim_fragment_text(text: str) -> bool:
    normalized = _normalized_text(text).rstrip("。；;")
    return bool(normalized and normalized.endswith(TRUNCATED_CLAIM_SUFFIXES))


def is_current_market_status_text(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return False
    if any(term in normalized for term in EXPLICIT_FORWARD_CLAIM_TERMS):
        return False
    return any(term in normalized for term in CURRENT_MARKET_STATUS_TERMS) and any(
        term in normalized for term in MARKET_STATUS_NOUNS
    )


def is_non_research_claim_text(text: str) -> bool:
    return (
        is_boilerplate_risk_warning_text(text)
        or is_disclaimer_text(text)
        or is_rating_definition_text(text)
        or is_heading_or_toc_text(text)
        or is_truncated_claim_fragment_text(text)
    )


def is_gold_candidate_noise_text(text: str) -> bool:
    return (
        is_non_research_claim_text(text)
        or is_pure_earnings_forecast_value_text(text)
        or is_historical_operating_fact_text(text)
        or is_current_market_status_text(text)
    )
